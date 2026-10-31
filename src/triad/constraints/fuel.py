"""Pilot fuel checks.  All burn rates come from the public aircraft type; fuel
quantities and the alternate come from Pilot private data."""

from __future__ import annotations

from typing import Callable

from triad.config import load_yaml
from triad.constraints.shared import is_divert, make_check
from triad.schemas import CandidateOption, ConstraintCheck, PerceivedFact, PilotPrivate, PublicEvent


def _fuel_cfg() -> dict:
    return load_yaml("synthetic")["fuel"]


def extra_burn_kg(public: PublicEvent, private: PilotPrivate, option: CandidateOption) -> float:
    """Fuel burned *in addition to* the planned trip for the chosen option."""

    cfg = _fuel_cfg()
    cruise = public.aircraft.cruise_burn_kg_min
    hold = public.aircraft.holding_burn_kg_min
    if is_divert(option):
        return 0.0
    if public.mode.value == "AIRBORNE":
        absorb = option.enroute_absorb_min * cruise * (1.0 - cfg["enroute_absorb_burn_saving"])
        return absorb + option.holding_min * hold
    # GROUND: flying faster burns more on the recovered portion.
    return option.speed_recovery_min * cruise * cfg["speed_recovery_burn_penalty"] + (
        option.holding_min * hold
    )


def landing_fuel_kg(public: PublicEvent, private: PilotPrivate, option: CandidateOption) -> float:
    """Estimated fuel at touchdown (or at the alternate for a divert)."""

    if is_divert(option):
        return private.fuel_on_board_kg - private.fuel_to_alternate_kg

    cruise = public.aircraft.cruise_burn_kg_min
    hold = public.aircraft.holding_burn_kg_min
    if public.mode.value == "AIRBORNE":
        cfg = _fuel_cfg()
        used = private.fuel_to_destination_kg
        used += option.enroute_absorb_min * cruise * (1.0 - cfg["enroute_absorb_burn_saving"])
        used += option.holding_min * hold
        return private.fuel_on_board_kg - used

    # GROUND: extra uplift may be loaded up to the tank/MTOW headroom.
    cfg = _fuel_cfg()
    penalty = option.speed_recovery_min * cruise * cfg["speed_recovery_burn_penalty"]
    uplift = min(penalty, private.max_extra_fuel_kg)
    used = private.fuel_to_destination_kg + penalty + option.holding_min * hold
    return private.fuel_on_board_kg + uplift - used


def required_landing_fuel_kg(private: PilotPrivate) -> float:
    if False:  # pragma: no cover - kept explicit for readability
        return 0.0
    return private.fuel_to_alternate_kg + private.reserve_45_kg


def max_holding_min(public: PublicEvent, private: PilotPrivate, option: CandidateOption) -> float:
    """Most holding the remaining fuel supports (PLT-FUEL-02)."""

    if is_divert(option) or public.mode.value != "AIRBORNE":
        return 0.0
    cfg = _fuel_cfg()
    cruise = public.aircraft.cruise_burn_kg_min
    hold = public.aircraft.holding_burn_kg_min
    absorb_burn = option.enroute_absorb_min * cruise * (1.0 - cfg["enroute_absorb_burn_saving"])
    spare = (
        private.fuel_on_board_kg
        - private.fuel_to_destination_kg
        - private.fuel_to_alternate_kg
        - private.reserve_45_kg
        - absorb_burn
    )
    return max(0.0, spare / hold) if hold > 0 else 0.0


def check_fuel(
    public: PublicEvent,
    private: PilotPrivate,
    facts: dict[str, PerceivedFact],
    option: CandidateOption,
    next_id: Callable[[], str],
) -> list[ConstraintCheck]:
    cfg = load_yaml("constraints")
    reserve_min = int(cfg.get("fuel_reserve_min", 45))
    checks: list[ConstraintCheck] = []

    if is_divert(option):
        available = private.fuel_on_board_kg
        needed = private.fuel_to_alternate_kg + private.reserve_45_kg
        checks.append(
            make_check(
                constraint_id="PLT-FUEL-01",
                owner="PILOT",
                option=option,
                next_id=next_id,
                passed=available >= needed,
                value=round(available, 1),
                limit=round(needed, 1),
                unit="kg",
                detail=(
                    f"divert to {option.divert_to}: fuel on board {available:.0f} kg vs "
                    f"alternate {private.fuel_to_alternate_kg:.0f} kg + {reserve_min} min reserve"
                ),
            )
        )
        checks.append(
            make_check(
                constraint_id="PLT-FUEL-02",
                owner="PILOT",
                option=option,
                next_id=next_id,
                passed=True,
                value=0,
                limit=0,
                unit="min",
                detail="divert: no holding planned",
            )
        )
        return checks

    landing = landing_fuel_kg(public, private, option)
    required = required_landing_fuel_kg(private)
    checks.append(
        make_check(
            constraint_id="PLT-FUEL-01",
            owner="PILOT",
            option=option,
            next_id=next_id,
            passed=landing >= required,
            value=round(landing, 1),
            limit=round(required, 1),
            unit="kg",
            detail=(
                f"landing fuel {landing:.0f} kg vs alternate {private.fuel_to_alternate_kg:.0f} kg "
                f"+ {reserve_min} min reserve {private.reserve_45_kg:.0f} kg"
            ),
        )
    )

    limit_hold = max_holding_min(public, private, option)
    checks.append(
        make_check(
            constraint_id="PLT-FUEL-02",
            owner="PILOT",
            option=option,
            next_id=next_id,
            passed=option.holding_min <= limit_hold + 1e-6,
            value=float(option.holding_min),
            limit=round(limit_hold, 1),
            unit="min",
            detail=f"planned holding {option.holding_min} min; fuel supports {limit_hold:.1f} min",
        )
    )
    return checks
