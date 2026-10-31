"""Pilot turbulence check (PLT-WX-01)."""

from __future__ import annotations

from typing import Callable

from triad.config import load_yaml
from triad.constraints.shared import is_divert, make_check
from triad.schemas import CandidateOption, ConstraintCheck, PerceivedFact, PilotPrivate, PublicEvent


def _turbulence_level(private: PilotPrivate, option: CandidateOption) -> tuple[int, str]:
    if option.cruise_level is not None:
        level = int(option.cruise_level)
    elif private.cruise_levels:
        level = int(private.cruise_levels[0])  # None = keep the current level
    else:
        level = 340
    return level, f"FL{level}"


def check_weather(
    public: PublicEvent,
    private: PilotPrivate,
    facts: dict[str, PerceivedFact],
    option: CandidateOption,
    next_id: Callable[[], str],
) -> list[ConstraintCheck]:
    hard_level = str(load_yaml("constraints").get("turbulence_hard_level", "SEVERE"))
    level, key = _turbulence_level(private, option)

    if is_divert(option):
        return [
            make_check(
                constraint_id="PLT-WX-01",
                owner="PILOT",
                option=option,
                next_id=next_id,
                passed=True,
                value="divert",
                limit=hard_level,
                unit="intensity",
                detail="divert routing: turbulence forecast for destination levels not used",
                facts_used=["turbulence"],
            )
        ]

    fact = facts.get("turbulence")
    levels = fact.value if fact is not None and isinstance(fact.value, dict) else {}
    # Unknown/missing perception is treated as the worst case.
    observed = str(levels.get(key, "SEVERE"))
    passed = observed != hard_level
    return [
        make_check(
            constraint_id="PLT-WX-01",
            owner="PILOT",
            option=option,
            next_id=next_id,
            passed=passed,
            value=observed,
            limit=hard_level,
            unit="intensity",
            detail=(
                f"{key} reported {observed}"
                if key in levels
                else f"no turbulence report for {key}; conservative SEVERE"
            ),
            facts_used=["turbulence"] if fact is not None else [],
        )
    ]


def check_duty(
    public: PublicEvent,
    private: PilotPrivate,
    facts: dict[str, PerceivedFact],
    option: CandidateOption,
    next_id: Callable[[], str],
) -> list[ConstraintCheck]:
    """PLT-FDP-01: flight duty period from the decision point to touchdown."""

    remaining = int(private.crew_duty_remaining_min)
    # Duty runs from the decision point to touchdown (block + any delay).
    elapsed = max(0, int(option.arrival_slot) - int(public.decision_time))
    return [
        make_check(
            constraint_id="PLT-FDP-01",
            owner="PILOT",
            option=option,
            next_id=next_id,
            passed=elapsed <= remaining,
            value=elapsed,
            limit=remaining,
            unit="min",
            detail=f"decision-to-touchdown {elapsed} min vs crew duty remaining {remaining} min",
        )
    ]
