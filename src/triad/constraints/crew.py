"""Ground ramp-crew shift accounting (GND-CREW-01).

Workbook fuel_and_crew: "Ground crew shift: 8 hours; overtime costs 1.5x after
that".  There is no hard labour limit in the workbook, so GND-CREW-01 is an
informational, non-hard check (``hard=False``, always passed): it reports the
overtime minutes; the money cost (minutes beyond shift end x base x 1.5) is a
Ground soft objective in ``triad.agents.scoring``.
"""

from __future__ import annotations

from typing import Callable

from triad.constraints.shared import is_divert, make_check
from triad.schemas import CandidateOption, ConstraintCheck, CrewShift, GroundPrivate, PerceivedFact, PublicEvent


def covering_shift(private: GroundPrivate, arrival: int) -> tuple[CrewShift | None, int]:
    """Return the shift on duty at ``arrival`` and the continuous-time arrival used."""

    for t in (arrival, arrival + 1440, arrival - 1440):
        covering = [s for s in private.shifts if s.start <= t < max(s.end, s.hard_limit_end)]
        if covering:
            # Prefer the most recently started shift (the one actually on duty).
            return max(covering, key=lambda s: s.start), t
    return None, arrival


def overtime_min(private: GroundPrivate, arrival: int) -> int:
    """Minutes the turnaround (arrival + minimum turnaround) runs past the shift end."""

    shift, t = covering_shift(private, arrival)
    if shift is None:
        return 0
    work_end = t + int(private.min_turnaround_min)
    return max(0, work_end - shift.end)


def overtime_rate_eur_per_min(shift: CrewShift) -> float:
    """Workbook: overtime costs base x 1.5 (``CrewShift.overtime_multiplier``)."""

    if shift.base_eur_per_min > 0:
        return float(shift.base_eur_per_min) * float(shift.overtime_multiplier)
    return float(shift.overtime_eur_per_min)


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
                hard=False,
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
                passed=True,
                value="no shift",
                limit="cost only",
                unit="min",
                detail=f"no ramp shift template covers arrival {option.arrival_slot}; no overtime costed",
                hard=False,
            )
        ]

    work_end = t + int(private.min_turnaround_min)
    over = max(0, work_end - shift.end)
    rate = overtime_rate_eur_per_min(shift)
    return [
        make_check(
            constraint_id="GND-CREW-01",
            owner="GROUND",
            option=option,
            next_id=next_id,
            passed=True,  # workbook: overtime is a cost, never a veto
            value=over,
            limit=shift.end,
            unit="min overtime",
            detail=(
                f"shift {shift.shift_id} ({shift.start}-{shift.end}, {shift.end - shift.start} min); "
                f"turnaround ends {work_end}; overtime {over} min at {rate:g} EUR/min "
                f"(base x {shift.overtime_multiplier:g}) - cost only"
            ),
            hard=False,
        )
    ]
