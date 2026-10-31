"""Batch scenario picker: find rows where the three agents really disagree.

Run with ``uv run triad pick --n 300 --seed 0 --write``.  The picker intentionally
uses only code (no LLM and no protocol-lane StubAgent): it builds each event,
generates options, runs the shared + role checkers, and ranks each role with its
own config weights.
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from triad.agents.base import CheckIdGen
from triad.agents.perception import stub_perceive
from triad.agents.scoring import objectives
from triad.config import CONFIG_DIR, load_yaml
from triad.constraints.registry import check_owned
from triad.constraints.shared import shared_checks
from triad.data.enrich import build_event
from triad.data.loader import get_record, load_flights
from triad.data.scenario import is_candidate
from triad.options.generator import generate_options
from triad.schemas import AgentRole, CandidateOption, DisruptionEvent, Mode


ROLES = (AgentRole.ATC, AgentRole.PILOT, AgentRole.GROUND)


@dataclass
class RowReport:
    row: int
    mode: str
    feasible_non_divert: list[str]
    top_choices: dict[str, str | None]
    next_leg_real: bool
    weather_delay: int
    late_aircraft_delay: int

    @property
    def n_feasible(self) -> int:
        return len(self.feasible_non_divert)

    @property
    def distinct_tops(self) -> int:
        return len({v for v in self.top_choices.values() if v is not None})

    @property
    def meets_criteria(self) -> bool:
        return self.n_feasible >= 3 and self.distinct_tops >= 2


def _private_for(event: DisruptionEvent, role: AgentRole):
    return {
        AgentRole.ATC: event.atc,
        AgentRole.PILOT: event.pilot,
        AgentRole.GROUND: event.ground,
    }[role]


def _weights() -> dict[AgentRole, dict[str, float]]:
    return {
        AgentRole.ATC: load_yaml("agents/atc").get("weights", {}),
        AgentRole.PILOT: load_yaml("agents/pilot").get("weights", {}),
        AgentRole.GROUND: load_yaml("agents/ground").get("weights", {}),
    }


def _utility(role: AgentRole, weights: dict[AgentRole, dict[str, float]], event: DisruptionEvent,
             facts: dict, option: CandidateOption) -> float:
    private = _private_for(event, role)
    obj = objectives(role, event.public, private, facts, option)
    return 1.0 - sum(weights[role].get(k, 0.0) * v for k, v in obj.items())


def evaluate_row(
    row_index: int, seed: int, *, defect_id: str | None = None
) -> tuple[RowReport, DisruptionEvent, list[CandidateOption]]:
    rec = get_record(row_index)
    event = build_event(rec, seed=seed, defect_id=defect_id)
    options = generate_options(event.public)

    shared_next = CheckIdGen("PICK-SHARED")
    shared_ok: list[CandidateOption] = [
        option
        for option in options
        if all(c.passed for c in shared_checks(event.public, option, shared_next) if c.hard)
    ]

    weights = _weights()
    role_feasible: dict[AgentRole, set[str]] = {}
    facts_by_role: dict[AgentRole, dict] = {}
    for role in ROLES:
        private = _private_for(event, role)
        facts = {f.key: f for f in stub_perceive(role, event.public, private)}
        facts_by_role[role] = facts
        feasible: set[str] = set()
        next_id = CheckIdGen(f"PICK-{role.value}")
        for option in shared_ok:
            checks = check_owned(role, event.public, private, facts, option, next_id)
            if all(c.passed for c in checks if c.hard):
                feasible.add(option.option_id)
        role_feasible[role] = feasible

    common = set.intersection(*(role_feasible[r] for r in ROLES)) if shared_ok else set()
    common_options = [o for o in shared_ok if o.option_id in common]
    non_divert = [o for o in common_options if not o.divert_to]

    top: dict[str, str | None] = {}
    for role in ROLES:
        candidates = [o for o in non_divert if o.option_id in role_feasible[role]]
        if not candidates:
            top[role.value] = None
            continue
        best = max(
            candidates,
            key=lambda o: (_utility(role, weights, event, facts_by_role[role], o), o.option_id),
        )
        top[role.value] = best.option_id

    report = RowReport(
        row=row_index,
        mode=event.public.mode.value,
        feasible_non_divert=[o.option_id for o in non_divert],
        top_choices=top,
        next_leg_real=bool(event.ground.next_leg and event.ground.next_leg.real),
        weather_delay=rec.weather_delay,
        late_aircraft_delay=rec.late_aircraft_delay,
    )
    return report, event, options


def _sample_rows(n: int, seed: int) -> list[int]:
    df = load_flights()
    dest = df["DESTINATION_AIRPORT"].to_numpy()
    weather = df["WEATHER_DELAY"].to_numpy(dtype=np.int64)
    late = df["LATE_AIRCRAFT_DELAY"].to_numpy(dtype=np.int64)
    candidate = (weather > 15) | (late > 20)
    rows = np.flatnonzero(candidate)
    hubs = set(load_yaml("runways").get("airports", {}))
    hub_rows = rows[np.isin(dest[rows], list(hubs))]
    other_rows = rows[~np.isin(dest[rows], list(hubs))]

    rng = random.Random(seed)
    n_hub = min(len(hub_rows), int(round(n * 0.8)))
    chosen = rng.sample(hub_rows.tolist(), n_hub) if n_hub else []
    remaining = max(0, n - len(chosen))
    if remaining and len(other_rows):
        chosen.extend(rng.sample(other_rows.tolist(), min(remaining, len(other_rows))))
    if len(chosen) < n:
        already = set(chosen)
        pool = [int(r) for r in rows.tolist() if int(r) not in already]
        chosen.extend(rng.sample(pool, min(n - len(chosen), len(pool))))
    rng.shuffle(chosen)
    return chosen[:n]


def _candidate_rows(n: int, seed: int) -> list[int]:
    rows = _sample_rows(n, seed)
    return [r for r in rows if is_candidate(get_record(r))]


def _choose_scenarios(
    reports: list[RowReport],
    seed: int,
    *,
    defect_id: str = "DEF-HYD-02",
) -> dict[str, dict[str, Any]]:
    scenario_a = next(
        (r for r in reports if r.mode == "AIRBORNE" and r.meets_criteria), None
    )
    if scenario_a is None:
        scenario_a = next((r for r in reports if r.mode == "AIRBORNE"), reports[0])

    def ground_ok(report: RowReport) -> bool:
        return report.mode == "GROUND" and report.next_leg_real and report.meets_criteria

    scenario_b: RowReport | None = None
    for report in reports:
        if report.mode != "GROUND" or not report.next_leg_real:
            continue
        forced, _, _ = evaluate_row(report.row, seed, defect_id=defect_id)
        if ground_ok(forced):
            scenario_b = forced
            break
    if scenario_b is None:
        scenario_b = next((r for r in reports if r.mode == "GROUND" and r.next_leg_real), None)
    if scenario_b is None:
        scenario_b = next((r for r in reports if r.mode == "GROUND"), scenario_a)

    airborne_alternatives = [
        r
        for r in reports
        if r.mode == "AIRBORNE" and r.row not in {scenario_a.row, scenario_b.row}
    ]
    scenario_c = (
        max(airborne_alternatives, key=lambda r: (r.meets_criteria, r.n_feasible, r.distinct_tops))
        if airborne_alternatives
        else scenario_a
    )

    return {
        "scenario_a": {
            "row": scenario_a.row,
            "seed": seed,
            "defect": None,
            "mode": scenario_a.mode,
            "notes": (
                f"weather/AIRBORNE hub demo; {scenario_a.n_feasible} safe non-divert options; "
                f"tops {scenario_a.top_choices}"
            ),
        },
        "scenario_b": {
            "row": scenario_b.row,
            "seed": seed,
            "defect": defect_id,
            "mode": scenario_b.mode,
            "notes": (
                f"late aircraft/GROUND with forced non-deferrable defect {defect_id}; "
                f"real next leg={scenario_b.next_leg_real}; {scenario_b.n_feasible} safe options"
            ),
        },
        "scenario_c": {
            "row": scenario_c.row,
            "seed": seed,
            "defect": None,
            "mode": scenario_c.mode,
            "notes": (
                f"AIRBORNE red-team/fuel-reserve demo; {scenario_c.n_feasible} safe non-divert "
                f"options; tops {scenario_c.top_choices}"
            ),
        },
    }


def _summary(reports: list[RowReport]) -> dict[str, float]:
    total = len(reports) or 1
    with_any = [r for r in reports if r.n_feasible >= 1]
    tops_any = [r for r in reports if r.distinct_tops >= 2]
    return {
        "rows": float(len(reports)),
        "ge2_feasible": sum(r.n_feasible >= 2 for r in reports) / total,
        "ge3_feasible": sum(r.n_feasible >= 3 for r in reports) / total,
        "ge2_distinct_tops": sum(r.distinct_tops >= 2 for r in reports) / total,
        "ge2_tops_among_feasible": (
            sum(r.distinct_tops >= 2 for r in with_any) / len(with_any) if with_any else 0.0
        ),
        "criteria": sum(r.meets_criteria for r in reports) / total,
        "ground_real_next_leg": sum(
            r.mode == "GROUND" and r.next_leg_real for r in reports
        ) / total,
        "mean_feasible": sum(r.n_feasible for r in reports) / total,
        "top_disagreement_rows": float(len(tops_any)),
    }


def pick_main(args: argparse.Namespace | Any) -> None:
    n = int(getattr(args, "n", 300))
    seed = int(getattr(args, "seed", 0))
    write = bool(getattr(args, "write", False))

    rows = _candidate_rows(n, seed)
    reports: list[RowReport] = []
    for row in rows:
        report, _, _ = evaluate_row(row, seed)
        reports.append(report)

    print(f"Evaluated {len(reports)} candidate rows (seed={seed}, n={n})")
    print(
        "row  mode      feas  tops  nextReal  weather  late  top choices"
    )
    for report in reports:
        if not report.meets_criteria and len(reports) > 25:
            continue
        tops = "/".join(
            f"{k[:1]}:{v}" for k, v in report.top_choices.items() if v is not None
        )
        print(
            f"{report.row:>5} {report.mode:<9} {report.n_feasible:>4} "
            f"{report.distinct_tops:>5} {str(report.next_leg_real):<9} "
            f"{report.weather_delay:>7} {report.late_aircraft_delay:>5}  {tops}"
        )

    stats = _summary(reports)
    print("\nSummary")
    print(f"  rows with >=2 feasible non-divert options : {stats['ge2_feasible']:.1%}")
    print(f"  rows with >=3 feasible non-divert options : {stats['ge3_feasible']:.1%}")
    print(f"  rows with >=2 distinct agent top choices  : {stats['ge2_distinct_tops']:.1%}")
    print(f"  ... among rows with any feasible option   : {stats['ge2_tops_among_feasible']:.1%}")
    print(f"  rows meeting full demo criteria           : {stats['criteria']:.1%}")
    print(f"  mean feasible non-divert options          : {stats['mean_feasible']:.2f}")

    if not reports:
        print("No candidate rows found.")
        return

    scenarios = _choose_scenarios(reports, seed)
    print("\nSelected scenarios")
    for name, payload in scenarios.items():
        print(f"  {name}: row={payload['row']} mode={payload['mode']} defect={payload['defect']}")

    if write:
        path = Path(CONFIG_DIR) / "demo_scenarios.yaml"
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump({"scenarios": scenarios}, fh, sort_keys=False)
        print(f"\nWrote {path}")
