"""Build ``config/negotiable_rows.yaml``: the curated row catalogue for the UI picker.

    uv run python scripts/build_negotiable_rows.py [--n 150] [--scan 3000] [--workers 1]

Deterministic: a fixed-seed stratified sample of candidate rows (roughly 40%
WEATHER/AIRBORNE, 60% LATE_AIRCRAFT/GROUND, spread over months and destination
airports) is evaluated with the stub world + stub agents at seed 0
(``triad.data.catalog.evaluate_row_choice``; nothing is written to runs/).
Rows meeting ``triad.data.catalog.CRITERIA`` are kept, preferring Turn-2/Turn-3
consensus with a validated counter while keeping some variety.  The three demo
rows from config/demo_scenarios.yaml are always included first.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from typing import Any

import numpy as np
import yaml

from triad.config import CONFIG_DIR, load_yaml
from triad.data.catalog import CATALOG_FILE, CRITERIA, RowChoice, evaluate_row_choice
from triad.data.limits import limits_info
from triad.data.loader import load_flights

GENERATOR_VERSION = "negotiable-rows v1"
SAMPLE_SEED = 20150101
WEATHER_SHARE = 0.4
MAX_PER_DESTINATION = 6
# Variety inside each stratum: at most this share of FALLBACK rows and of rows
# without a validated counter; the rest prefer TURN2/TURN3 + counter.
MAX_FALLBACK_SHARE = 0.15
MAX_NO_COUNTER_SHARE = 0.30


def _sample(scan: int) -> list[tuple[int, str]]:
    """Fixed-seed stratified sample: [(row_index, "WEATHER"|"LATE_AIRCRAFT")]."""

    df = load_flights()
    weather = df["WEATHER_DELAY"].to_numpy(dtype=np.int64)
    late = df["LATE_AIRCRAFT_DELAY"].to_numpy(dtype=np.int64)
    month = df["MONTH"].to_numpy(dtype=np.int64)
    rows = df["row_index"].to_numpy(dtype=np.int64)
    is_weather = weather > 15
    is_late = (~is_weather) & (late > 20)

    rng = random.Random(SAMPLE_SEED)
    out: list[tuple[int, str]] = []
    for kind, mask, share in (
        ("WEATHER", is_weather, WEATHER_SHARE),
        ("LATE_AIRCRAFT", is_late, 1.0 - WEATHER_SHARE),
    ):
        quota = int(round(scan * share))
        by_month: dict[int, list[int]] = defaultdict(list)
        for r, m in zip(rows[mask].tolist(), month[mask].tolist()):
            by_month[int(m)].append(int(r))
        months = sorted(by_month)
        per_month = max(1, quota // max(1, len(months)))
        for m in months:
            pool = by_month[m]
            out.extend((r, kind) for r in rng.sample(pool, min(per_month, len(pool))))
    return out


def _evaluate(item: tuple[int, str | None, str | None]) -> tuple[dict[str, Any], dict[str, Any]] | None:
    row, defect, demo = item
    try:
        choice, info = evaluate_row_choice(row, defect_id=defect, demo=demo)
    except Exception as exc:  # noqa: BLE001 - a broken row is simply skipped
        print(f"  row {row}: skipped ({type(exc).__name__}: {exc})", file=sys.stderr)
        return None
    return choice.model_dump(), info


def _demo_items() -> list[tuple[int, str | None, str]]:
    scenarios = (load_yaml("demo_scenarios") or {}).get("scenarios", {})
    items: list[tuple[int, str | None, str]] = []
    for name in ("scenario_a", "scenario_b", "scenario_c"):
        item = scenarios.get(name)
        if item:
            items.append((int(item["row"]), item.get("defect"), name[-1].upper()))
    return items


def _round_robin_by_month(choices: list[RowChoice]) -> list[RowChoice]:
    by_month: dict[str, list[RowChoice]] = defaultdict(list)
    for c in sorted(choices, key=lambda c: (c.date, c.row_index)):
        by_month[c.date[:7]].append(c)
    out: list[RowChoice] = []
    queues = [by_month[m] for m in sorted(by_month)]
    while any(queues):
        for q in queues:
            if q:
                out.append(q.pop(0))
    return out


def _select(kept: list[RowChoice], quota: int, dest_count: Counter) -> list[RowChoice]:
    best = [c for c in kept if c.stub_outcome in ("TURN2", "TURN3") and c.has_valid_counter]
    no_counter = [c for c in kept if c.stub_outcome in ("TURN2", "TURN3") and not c.has_valid_counter]
    fallback = [c for c in kept if c.stub_outcome == "FALLBACK"]
    caps = [
        (fallback, int(quota * MAX_FALLBACK_SHARE)),
        (no_counter, int(quota * MAX_NO_COUNTER_SHARE)),
        (best, quota),
    ]
    chosen: list[RowChoice] = []
    taken: set[int] = set()

    def take(bucket: list[RowChoice], limit: int) -> None:
        n = 0
        for c in _round_robin_by_month(bucket):
            if len(chosen) >= quota or n >= limit:
                return
            if c.row_index in taken or dest_count[c.destination] >= MAX_PER_DESTINATION:
                continue
            chosen.append(c)
            taken.add(c.row_index)
            dest_count[c.destination] += 1
            n += 1

    for bucket, limit in caps:
        take(bucket, limit)
    # Shortfall: fill from anything left, relaxing the destination cap last.
    if len(chosen) < quota:
        take(best + no_counter + fallback, quota)
    if len(chosen) < quota:
        for c in _round_robin_by_month(best + no_counter + fallback):
            if len(chosen) >= quota:
                break
            if c.row_index not in taken:
                chosen.append(c)
                taken.add(c.row_index)
    return chosen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=150, help="target catalogue size (incl. demo rows)")
    parser.add_argument("--scan", type=int, default=3000, help="candidate rows to evaluate")
    parser.add_argument("--workers", type=int, default=1, help="process-pool size (1 = in-process)")
    args = parser.parse_args(argv)

    t0 = time.time()
    demos = _demo_items()
    demo_rows = {row for row, _, _ in demos}
    sample = [(row, kind) for row, kind in _sample(args.scan) if row not in demo_rows]
    items: list[tuple[int, str | None, str | None]] = [(row, None, None) for row, _ in sample]
    print(f"evaluating {len(items)} sampled rows + {len(demos)} demo rows (seed 0, stub) ...")

    all_items = [(r, d, m) for r, d, m in demos] + items
    if args.workers > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            results = list(pool.map(_evaluate, all_items, chunksize=25))
    else:
        results = [_evaluate(item) for item in all_items]

    demo_choices: list[RowChoice] = []
    kept: dict[str, list[RowChoice]] = {"WEATHER": [], "LATE_AIRCRAFT": []}
    n_eval = n_meet = 0
    for item, result in zip(all_items, results):
        if result is None:
            continue
        data, info = result
        choice = RowChoice(**data)
        if item[2] is not None:
            demo_choices.append(choice)
            continue
        n_eval += 1
        if info["meets_criteria"]:
            n_meet += 1
            kept[choice.disruption].append(choice)

    remaining = max(0, args.n - len(demo_choices))
    weather_quota = int(round(remaining * WEATHER_SHARE))
    quotas = {"WEATHER": weather_quota, "LATE_AIRCRAFT": remaining - weather_quota}
    dest_count: Counter = Counter(c.destination for c in demo_choices)
    selected: list[RowChoice] = []
    for kind in ("WEATHER", "LATE_AIRCRAFT"):
        selected.extend(_select(kept[kind], quotas[kind], dest_count))
    selected.sort(key=lambda c: (c.date, c.row_index))
    final = demo_choices + selected

    counts = {
        "rows": len(final),
        "demo_rows": len(demo_choices),
        "by_disruption": dict(sorted(Counter(c.disruption for c in final).items())),
        "by_stub_outcome": dict(sorted(Counter(c.stub_outcome for c in final).items())),
        "with_valid_counter": sum(c.has_valid_counter for c in final),
        "distinct_destinations": len({c.destination for c in final}),
        "distinct_months": len({c.date[:7] for c in final}),
        "scanned": n_eval,
        "scanned_meeting_criteria": n_meet,
    }
    header = {
        "generator": GENERATOR_VERSION,
        "script": "scripts/build_negotiable_rows.py",
        "seed": 0,
        "sample_seed": SAMPLE_SEED,
        "workbook": limits_info()["workbook"],
        "workbook_sha256": limits_info()["workbook_sha256"],
        "criteria": CRITERIA,
        "preference": (
            "TURN2/TURN3 consensus with a validated counter first; at most "
            f"{int(MAX_FALLBACK_SHARE * 100)}% FALLBACK and {int(MAX_NO_COUNTER_SHARE * 100)}% "
            f"without a counter per disruption type; <= {MAX_PER_DESTINATION} rows per destination "
            "where possible; demo rows always included (they need not meet the criteria)"
        ),
        "counts": counts,
    }
    text = (
        "# GENERATED by scripts/build_negotiable_rows.py -- do not edit by hand.\n"
        "# Curated dataset rows where the three stub agents negotiate (seed 0). Loaded by\n"
        "# triad.data.catalog.negotiable_rows().\n"
        + yaml.safe_dump(
            {"header": header, "rows": [c.model_dump() for c in final]},
            sort_keys=False,
            allow_unicode=True,
            width=1000,
        )
    )
    CATALOG_FILE.write_text(text, encoding="utf-8")
    print(f"wrote {CATALOG_FILE.relative_to(CONFIG_DIR.parent)} in {time.time() - t0:.1f}s")
    print(yaml.safe_dump(counts, sort_keys=False, allow_unicode=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
