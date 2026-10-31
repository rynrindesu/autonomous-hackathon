"""Pilot turbulence check (PLT-WX-01) and flight-duty check (PLT-FDP-01)."""

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
    """PLT-FDP-01: touchdown within the max duty period from crew report time.

    Workbook fuel_and_crew: flight crew max duty 13 h from report time
    (simplified FAA Part 117).  For a divert the touchdown is the option's
    arrival estimate as well.
    """

    max_duty = int(private.crew_max_duty_min)
    arrival = int(option.arrival_slot)
    if private.crew_report_time is not None:
        report = int(private.crew_report_time)
        duty = arrival - report
        detail = (
            f"report {report} -> touchdown {arrival}: duty {duty} min vs max "
            f"{max_duty} min ({max_duty / 60:g} h from report)"
        )
    else:
        # Legacy data without a report time: derive it from the remaining duty.
        report = int(public.decision_time) + int(private.crew_duty_remaining_min) - max_duty
        duty = arrival - report
        detail = (
            f"decision-to-touchdown {max(0, arrival - int(public.decision_time))} min vs crew "
            f"duty remaining {private.crew_duty_remaining_min} min"
        )
    return [
        make_check(
            constraint_id="PLT-FDP-01",
            owner="PILOT",
            option=option,
            next_id=next_id,
            passed=duty <= max_duty,
            value=duty,
            limit=max_duty,
            unit="min",
            detail=detail,
        )
    ]
