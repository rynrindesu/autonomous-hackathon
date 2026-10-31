"""Curated catalogue of "negotiable" dataset rows for the UI row picker.

``config/negotiable_rows.yaml`` is precomputed by ``scripts/build_negotiable_rows.py``
(stub world + stub agents, always ``seed=0``).  Every row there makes the three
agents genuinely negotiate: at least two safe non-divert options, different
Turn-1 first choices, no diversion and no escalation.  The three demo rows from
``config/demo_scenarios.yaml`` are always included first.

Public API (for the UI)::

    from triad.data.catalog import negotiable_rows, row_choice
    rows = negotiable_rows()          # list[RowChoice], demo rows first then by date
    choice = row_choice(293614)       # RowChoice | None
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

from triad.config import CONFIG_DIR

CATALOG_FILE = CONFIG_DIR / "negotiable_rows.yaml"

Outcome = Literal["TURN1", "TURN2", "TURN3", "FALLBACK"]


class RowChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    row_index: int
    run_id: str
    label: str  # e.g. "2015-06-08 · AA1691 DFW→DEN · Weather +45 min"
    date: str  # YYYY-MM-DD
    airline: str
    flight_number: int
    origin: str
    destination: str
    mode: Literal["AIRBORNE", "GROUND"]
    disruption: Literal["WEATHER", "LATE_AIRCRAFT"]
    delay_min: int  # the qualifying delay (WEATHER_DELAY or LATE_AIRCRAFT_DELAY)
    stub_outcome: Outcome
    stub_option_id: str | None
    n_safe_options: int  # non-divert options passing shared + every agent's hard checks
    has_valid_counter: bool  # a counter-option was validated in Turn 1 or 2
    demo: Literal["A", "B", "C"] | None = None  # demo scenario letter, if any
    defect: str | None = None  # forced defect id (demo scenario B only)


def make_label(
    *,
    date: str,
    airline: str,
    flight_number: int,
    origin: str,
    destination: str,
    disruption: str,
    delay_min: int,
    demo: str | None = None,
) -> str:
    kind = "Weather" if disruption == "WEATHER" else "Late aircraft"
    label = f"{date} · {airline}{flight_number} {origin}→{destination} · {kind} +{delay_min} min"
    return f"★ Demo {demo} · {label}" if demo else label


@lru_cache(maxsize=1)
def _load() -> tuple[RowChoice, ...]:
    if not CATALOG_FILE.exists():
        return ()
    data: dict[str, Any] = yaml.safe_load(CATALOG_FILE.read_text(encoding="utf-8")) or {}
    return tuple(RowChoice(**item) for item in data.get("rows") or [])


@lru_cache(maxsize=1)
def _by_row() -> dict[int, RowChoice]:
    return {choice.row_index: choice for choice in _load()}


def negotiable_rows() -> list[RowChoice]:
    """All catalogue rows: demo rows first (A, B, C), then by date."""

    return list(_load())


def row_choice(row_index: int) -> RowChoice | None:
    return _by_row().get(int(row_index))


CRITERIA = (
    "stub world + stub agents, seed 0: >=2 non-divert options pass every hard check; "
    "Turn-1 first choices are not all equal (no Turn-1 fast path); the committed option "
    "is not OPT-DIV; the run is not ESCALATED"
)


def evaluate_row_choice(
    row_index: int, *, defect_id: str | None = None, demo: str | None = None
) -> tuple[RowChoice, dict[str, Any]]:
    """Run the stub protocol for ``row_index`` (seed 0) and summarise it.

    Returns the :class:`RowChoice` plus diagnostics ``{"status", "first_choices",
    "meets_criteria"}``.  Nothing is written to disk.
    """

    from triad.picker import evaluate_row
    from triad.runner import run_scenario

    report, event, _options = evaluate_row(int(row_index), 0, defect_id=defect_id)
    resolution, log = run_scenario(int(row_index), seed=0, defect_id=defect_id, impl="stub")
    rec = event.public.flight

    first: dict[str, str | None] = {}
    for entry in log.entries:
        if entry.event == "PROPOSAL" and entry.turn == 1:
            ranking = entry.payload.get("ranking") or []
            first[entry.actor] = ranking[0] if ranking else None
    has_counter = any(e.event == "COUNTER_VALIDATED" for e in log.entries)

    if resolution.status == "CONSENSUS":
        outcome = f"TURN{max(1, min(3, int(resolution.turn)))}"
    else:
        outcome = "FALLBACK"
    option_id = resolution.option.option_id if resolution.option is not None else None

    disruption = event.public.disruption_type.value
    delay = rec.weather_delay if disruption == "WEATHER" else rec.late_aircraft_delay
    date = f"{rec.year:04d}-{rec.month:02d}-{rec.day:02d}"
    choice = RowChoice(
        row_index=rec.row_index,
        run_id=rec.run_id,
        label=make_label(
            date=date,
            airline=rec.airline,
            flight_number=rec.flight_number,
            origin=rec.origin,
            destination=rec.destination,
            disruption=disruption,
            delay_min=int(delay),
            demo=demo,
        ),
        date=date,
        airline=rec.airline,
        flight_number=rec.flight_number,
        origin=rec.origin,
        destination=rec.destination,
        mode=event.public.mode.value,
        disruption=disruption,
        delay_min=int(delay),
        stub_outcome=outcome,  # type: ignore[arg-type]
        stub_option_id=option_id,
        n_safe_options=report.n_feasible,
        has_valid_counter=has_counter,
        demo=demo,  # type: ignore[arg-type]
        defect=defect_id,
    )
    first_values = [v for v in first.values() if v is not None]
    meets = (
        report.n_feasible >= 2
        and len(first_values) == 3
        and len(set(first_values)) > 1
        and option_id is not None
        and option_id != "OPT-DIV"
        and resolution.status != "ESCALATED"
    )
    return choice, {
        "status": resolution.status,
        "first_choices": first,
        "meets_criteria": bool(meets),
    }


def catalog_header() -> dict[str, Any]:
    """Generator metadata (version, workbook sha, criteria, counts)."""

    if not CATALOG_FILE.exists():
        return {}
    data = yaml.safe_load(CATALOG_FILE.read_text(encoding="utf-8")) or {}
    return dict(data.get("header") or {})


__all__ = [
    "CRITERIA",
    "RowChoice",
    "catalog_header",
    "evaluate_row_choice",
    "make_label",
    "negotiable_rows",
    "row_choice",
]
