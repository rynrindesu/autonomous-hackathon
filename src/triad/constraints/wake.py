"""ATC wake-separation check (ICAO categories only)."""

from __future__ import annotations

from typing import Any, Callable

from triad.config import load_yaml
from triad.constraints.runway import find_slot
from triad.constraints.shared import is_divert, make_check
from triad.schemas import AtcPrivate, CandidateOption, ConstraintCheck, PerceivedFact, PublicEvent


def check_wake(
    public: PublicEvent,
    private: AtcPrivate,
    facts: dict[str, PerceivedFact],
    option: CandidateOption,
    next_id: Callable[[], str],
) -> list[ConstraintCheck]:
    if is_divert(option):
        return [
            make_check(
                constraint_id="ATC-WAKE-01",
                owner="ATC",
                option=option,
                next_id=next_id,
                passed=True,
                value="divert",
                limit="n/a",
                unit="NM",
                detail="divert to alternate: destination wake sequence not applicable",
            )
        ]

    cfg = load_yaml("constraints")
    wake_cfg: dict[str, dict[str, float]] = cfg.get("wake_min_nm", {})
    radar_min = float(cfg.get("radar_min_nm", 3))

    slot = find_slot(private.slots, option.runway, option.arrival_slot)
    follower = public.aircraft.wake.value
    if slot is None:
        return [
            make_check(
                constraint_id="ATC-WAKE-01",
                owner="ATC",
                option=option,
                next_id=next_id,
                passed=False,
                value="no slot",
                limit="slot required",
                unit="NM",
                detail=f"no arrival slot at {option.arrival_slot} on runway {option.runway}",
            )
        ]

    leader = slot.leader_wake.value if slot.leader_wake is not None else None
    if leader is None:
        required = radar_min
        detail = f"no wake leader; radar minimum {radar_min:g} NM"
    else:
        required = float(wake_cfg.get(leader, {}).get(follower, radar_min))
        detail = (
            f"leader {slot.leader_type or '?'} ({leader}) -> follower {follower}: "
            f"available {slot.gap_nm:g} NM, required {required:g} NM"
        )

    return [
        make_check(
            constraint_id="ATC-WAKE-01",
            owner="ATC",
            option=option,
            next_id=next_id,
            passed=slot.gap_nm >= required,
            value=float(slot.gap_nm),
            limit=required,
            unit="NM",
            detail=detail,
        )
    ]
