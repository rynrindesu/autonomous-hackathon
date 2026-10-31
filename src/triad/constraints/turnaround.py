"""Ground turnaround check (GND-TURN-01)."""

from __future__ import annotations

from typing import Callable

from triad.constraints.shared import is_divert, make_check
from triad.schemas import CandidateOption, ConstraintCheck, GroundPrivate, PerceivedFact, PublicEvent


def next_leg_delay_min(public: PublicEvent, private: GroundPrivate, option: CandidateOption) -> int:
    """Minutes of delay actually imposed on the next leg (used by scoring/costs)."""

    if private.next_leg is None:
        return 0
    if option.next_leg_action == "DELAY":
        return max(0, int(option.next_leg_delay_min))
    if option.next_leg_action == "SWAP_AIRCRAFT":
        return 0
    if is_divert(option):
        return 0
    gap = private.next_leg.scheduled_departure - option.arrival_slot
    return max(0, int(private.min_turnaround_min - gap))


def check_turnaround(
    public: PublicEvent,
    private: GroundPrivate,
    facts: dict[str, PerceivedFact],
    option: CandidateOption,
    next_id: Callable[[], str],
) -> list[ConstraintCheck]:
    if is_divert(option):
        return [
            make_check(
                constraint_id="GND-TURN-01",
                owner="GROUND",
                option=option,
                next_id=next_id,
                passed=True,
                value="divert",
                limit=private.min_turnaround_min,
                unit="min",
                detail="aircraft diverts; next leg must be reassigned by operations",
            )
        ]

    if private.next_leg is None:
        return [
            make_check(
                constraint_id="GND-TURN-01",
                owner="GROUND",
                option=option,
                next_id=next_id,
                passed=True,
                value="no next leg",
                limit=private.min_turnaround_min,
                unit="min",
                detail="aircraft has no next flight in the data",
            )
        ]

    leg = private.next_leg
    required = int(private.min_turnaround_min)
    action = option.next_leg_action

    if action == "SWAP_AIRCRAFT":
        return [
            make_check(
                constraint_id="GND-TURN-01",
                owner="GROUND",
                option=option,
                next_id=next_id,
                passed=bool(private.spare_aircraft_available),
                value="spare" if private.spare_aircraft_available else "no spare",
                limit="spare aircraft required",
                unit="aircraft",
                detail=(
                    "spare aircraft available to protect the next leg"
                    if private.spare_aircraft_available
                    else "no spare aircraft available for a swap"
                ),
            )
        ]

    extra = max(0, int(option.next_leg_delay_min)) if action == "DELAY" else 0
    gap = leg.scheduled_departure + extra - option.arrival_slot
    passed = gap >= required
    return [
        make_check(
            constraint_id="GND-TURN-01",
            owner="GROUND",
            option=option,
            next_id=next_id,
            passed=passed,
            value=int(gap),
            limit=required,
            unit="min",
            detail=(
                f"{action}: next leg {leg.flight_number} at {leg.scheduled_departure}"
                + (f" (+{extra} min delay)" if extra else "")
                + f", arrival {option.arrival_slot}, gap {gap} min vs minimum {required}"
            ),
        )
    ]
