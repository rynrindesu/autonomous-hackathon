"""Batch evaluation (PLAN §13): compare negotiation modes on the same sampled rows.

    uv run python scripts/batch_eval.py --n 50 --modes stub,ai-off,fcfs

Modes
  stub    negotiation with stub agents (code-only ranking)
  llm     negotiation with LLM agents (only when explicitly requested; uses the response cache)
  ai-off  deterministic fallback solver only
  fcfs    SIMULATED first-come-first-served baseline (earliest safe arrival)

Rows are sampled deterministically (seeded) from the brief's filter
WEATHER_DELAY > 15 OR LATE_AIRCRAFT_DELAY > 20. Per-run logs go under runs/.
Physical metrics and cost components are evaluated with stub (ground-truth
perception) agents for every mode, so all modes share one yardstick.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from triad.config import RUNS_DIR  # noqa: E402
from triad.metrics import RunMetrics, aggregate, negotiation_delta, run_metrics  # noqa: E402

MODES = ("stub", "llm", "ai-off", "fcfs")


def sample_rows(n: int, seed: int) -> list[int]:
    """Deterministic uniform sample of candidate rows (sorted)."""
    import numpy as np

    from triad.data.loader import load_flights

    df = load_flights()
    weather = df["WEATHER_DELAY"].to_numpy(dtype=np.int64)
    late = df["LATE_AIRCRAFT_DELAY"].to_numpy(dtype=np.int64)
    rows = np.flatnonzero((weather > 15) | (late > 20)).tolist()
    rng = random.Random(seed)
    return sorted(int(r) for r in rng.sample(rows, min(n, len(rows))))


def _parse_modes(raw: str | None, impl: str) -> list[str]:
    modes = [m.strip() for m in (raw or f"{impl},ai-off,fcfs").split(",") if m.strip()]
    unknown = [m for m in modes if m not in MODES]
    if unknown:
        raise SystemExit(f"error: unknown mode(s) {unknown}; choose from {list(MODES)}")
    return list(dict.fromkeys(modes))


def evaluate_row(row: int, seed: int, modes: list[str], run_root: Path) -> tuple[dict[str, RunMetrics], dict[str, str]]:
    """Run every mode on one row. Returns (metrics by mode, error by mode)."""
    from triad.agents import build_agents
    from triad.baseline import run_fcfs
    from triad.data.enrich import build_event
    from triad.data.loader import get_record
    from triad.log.manifest import write_resolution
    from triad.runner import run_scenario

    record = get_record(row)
    event = build_event(record, seed=seed)
    evaluator = build_agents(event, impl="stub")
    out: dict[str, RunMetrics] = {}
    errors: dict[str, str] = {}
    for mode in modes:
        run_dir = run_root / f"{record.run_id}-{mode}"
        try:
            if mode == "fcfs":
                resolution, metrics = run_fcfs(event, evaluator)
                run_dir.mkdir(parents=True, exist_ok=True)
                write_resolution(resolution, run_dir)
            else:
                resolution, log = run_scenario(
                    row,
                    seed=seed,
                    ai_off=(mode == "ai-off"),
                    impl="llm" if mode == "llm" else "stub",
                    run_dir=run_dir,
                )
                write_resolution(resolution, run_dir)
                metrics = run_metrics(resolution, log, event=event, agents=evaluator, label=mode)
            out[mode] = metrics
        except Exception as exc:  # noqa: BLE001 - count and keep going
            errors[mode] = f"{type(exc).__name__}: {exc}"
    return out, errors


def _fmt(value: Any, digits: int = 0) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    return str(value)


def print_table(report: dict[str, Any]) -> None:
    reports = report["reports"]
    deltas = report["deltas"]
    errors = report["error_counts"]
    print(f"\nBatch eval: {report['n_rows']} rows, seed {report['seed']}, impl {report['impl']}")
    header = (
        f"{'mode':<7} {'runs':>4} {'T1':>3} {'T2':>3} {'T3':>3} {'FB':>3} {'ESC':>3} {'err':>3} {'unsafe':>6} "
        f"{'feas>=2':>7} {'cost EUR':>9} {'hold':>5} {'fuel kg':>7} {'CO2 kg':>7} {'delay':>5} "
        f"{'missed':>6} {'OT':>4} {'NL':>4} {'chg%':>5} {'dCost':>7} {'veto y/t':>8}"
    )
    print(header)
    print("-" * len(header))
    for mode, r in reports.items():
        o = r["outcomes"]
        d = deltas.get(mode)
        chg = f"{d['changed_rate'] * 100:.0f}" if d and d["changed_rate"] is not None else "-"
        dcost = _fmt(d["mean_cost_diff_eur"]) if d else "-"
        feas = f"{r['feasible_ge2_rate'] * 100:.0f}%" if r["feasible_ge2_rate"] is not None else "-"
        print(
            f"{mode:<7} {r['n_runs']:>4} {o['TURN1']:>3} {o['TURN2']:>3} {o.get('TURN3', 0):>3} {o['FALLBACK']:>3} "
            f"{o['ESCALATED']:>3} {errors.get(mode, 0):>3} {r['unsafe_commits']:>6} {feas:>7} "
            f"{_fmt(r['mean_total_cost_eur']):>9} {_fmt(r['mean_holding_min'], 1):>5} "
            f"{_fmt(r['mean_fuel_kg']):>7} {_fmt(r['mean_co2_kg']):>7} "
            f"{_fmt(r['mean_arrival_delay_min'], 1):>5} {_fmt(r['mean_missed_connections'], 1):>6} "
            f"{_fmt(r['mean_overtime_min'], 1):>4} {_fmt(r['mean_next_leg_delay_min'], 1):>4} "
            f"{chg:>5} {dcost:>7} {r['veto_yield']:>3}/{r['vetoes_total']:<4}"
        )
    print(
        "chg% / dCost: share of rows whose committed option differs from 'stub', and mean cost "
        "(mode - stub). fcfs is SIMULATED."
    )
    print(f"Report: {report['out']}")


def main(argv: list[str] | None = None) -> dict[str, Any]:
    parser = argparse.ArgumentParser(description="Triad batch evaluation (PLAN §13)")
    parser.add_argument("--n", type=int, default=50, help="number of sampled candidate rows")
    parser.add_argument("--seed", type=int, default=0, help="sampling + scenario seed")
    parser.add_argument("--impl", choices=["stub", "llm"], default="stub")
    parser.add_argument("--modes", default=None, help="comma list of stub,llm,ai-off,fcfs (default: <impl>,ai-off,fcfs)")
    parser.add_argument("--out", default=None, help="report JSON (default runs/eval/batch-<impl>-<n>.json)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    modes = _parse_modes(args.modes, args.impl)
    out = Path(args.out) if args.out else RUNS_DIR / "eval" / f"batch-{args.impl}-{args.n}.json"
    run_root = out.with_suffix("")
    out.parent.mkdir(parents=True, exist_ok=True)

    rows = sample_rows(args.n, args.seed)
    by_mode: dict[str, list[RunMetrics]] = {m: [] for m in modes}
    errors: list[dict[str, Any]] = []
    for row in rows:
        try:
            metrics, row_errors = evaluate_row(row, args.seed, modes, run_root)
        except Exception as exc:  # noqa: BLE001 - row could not even be built
            metrics, row_errors = {}, {m: f"{type(exc).__name__}: {exc}" for m in modes}
        for mode, m in metrics.items():
            by_mode[mode].append(m)
        errors.extend({"row": row, "mode": mode, "error": err} for mode, err in row_errors.items())

    reports = {mode: aggregate(runs, label=mode).model_dump() for mode, runs in by_mode.items()}
    deltas = (
        {
            mode: negotiation_delta(by_mode["stub"], runs).model_dump()
            for mode, runs in by_mode.items()
            if mode != "stub"
        }
        if "stub" in by_mode
        else {}
    )
    error_counts: dict[str, int] = {}
    for e in errors:
        error_counts[e["mode"]] = error_counts.get(e["mode"], 0) + 1

    report: dict[str, Any] = {
        "n_rows": len(rows),
        "seed": args.seed,
        "impl": args.impl,
        "modes": modes,
        "rows": rows,
        "out": str(out),
        "reports": reports,
        "deltas": deltas,
        "error_counts": error_counts,
        "errors": errors,
        "runs": {mode: [m.model_dump() for m in runs] for mode, runs in by_mode.items()},
    }
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    if not args.quiet:
        print_table(report)
    return report


if __name__ == "__main__":
    main()
