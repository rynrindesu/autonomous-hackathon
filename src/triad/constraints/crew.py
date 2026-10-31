"""Ground ramp-crew shift check (GND-CREW-01)."""

from __future__ import annotations

from typing import Callable

from triad.constraints.shared import is_divert, make_check
from triad.schemas import CandidateOption, ConstraintCheck, CrewShift, GroundPrivate, PerceivedFact, PublicEvent


def covering_shift(private: GroundPrivate, arrival: int) -> tuple[CrewShift | None, int]:
    """Return the shift covering ``arrival`` and the continuous-time arrival used."""

    for t in (arrival, arrival + 1440, arrival - 1440):
        covering = [s for s in private.shifts if s.start <= t < s.hard_limit_end]
        if covering:
            # Prefer the most recently started shift (the one actually on duty).
            return max(covering, key=lambda s: s.start), t
    return None, arrival


def overtime_min(private: GroundPrivate, arrival: int) -> int:
    shift, t = covering_shift(private, arrival)
    if shift is None:
        return 0
    work_end = t + int(private.min_turnaround_min)
    return max(0, work_end - shift.end)


def check_crew(
    public: PublicEvent,
    private: GroundPrivate,
    facts: dict[str, PerceivedFact],
    option: CandidateOption,
    next_id: Callable[[], str],
) -> list[ConstraintCheck]:
    if is_divert(option):
        return [
            make_check(
                constraint_id="GND-CREW-01",
                owner="GROUND",
                option=option,
                next_id=next_id,
                passed=True,
                value="divert",
                limit="n/a",
                unit="min",
                detail="aircraft diverts to alternate; destination ramp crew release",
            )
        ]

    shift, t = covering_shift(private, option.arrival_slot)
    if shift is None:
        return [
            make_check(
                constraint_id="GND-CREW-01",
                owner="GROUND",
                option=option,
                next_id=next_id,
                passed=False,
                value="no shift",
                limit="covering shift required",
                unit="min",
                detail=f"no ramp shift covers arrival {option.arrival_slot}",
            )
        ]

    work_end = t + int(private.min_turnaround_min)
    return [
        make_check(
            constraint_id="GND-CREW-01",
            owner="GROUND",
            option=option,
            next_id=next_id,
            passed=work_end <= shift.hard_limit_end,
            value=work_end,
            limit=shift.hard_limit_end,
            unit="min",
            detail=(
                f"shift {shift.shift_id} ({shift.start}-{shift.end}, hard {shift.hard_limit_end}); "
                f"turnaround ends {work_end}"
            ),
        )
    ]
