"""Pilot fuel checks (workbook fuel_and_crew).

* Final reserve = 30 min of holding fuel; PLT-FUEL-01 never lets planned landing
  fuel drop below it (divert: fuel to alternate + final reserve).
* Fuel on board carries contingency (5% of trip) + spare (45 min holding) ON TOP
  of the final reserve, so ~45 min of holding/absorption fits before PLT-FUEL-02
  vetoes.
* Holding burn is the workbook narrowbody/widebody figure (public aircraft info);
  fuel quantities and the alternate come from Pilot private data.
"""

from __future__ import annotations

from typing import Callable

from triad.config import load_yaml
from triad.constraints.shared import is_divert, make_check
from triad.data.limits import fuel_crew
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
    """Workbook: never plan to land below the final reserve (30 min holding)."""

    return private.final_reserve_kg


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
        - required_landing_fuel_kg(private)
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
    reserve_min = fuel_crew().final_reserve_holding_min
    checks: list[ConstraintCheck] = []

    if is_divert(option):
        available = private.fuel_on_board_kg
        needed = private.fuel_to_alternate_kg + private.final_reserve_kg
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
                    f"alternate {private.fuel_to_alternate_kg:.0f} kg + final reserve "
                    f"{private.final_reserve_kg:.0f} kg ({reserve_min:g} min holding)"
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
                f"planned landing fuel {landing:.0f} kg vs final reserve "
                f"{required:.0f} kg ({reserve_min:g} min holding at "
                f"{public.aircraft.holding_burn_kg_min:g} kg/min)"
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
            detail=(
                f"planned holding {option.holding_min} min; fuel above final reserve "
                f"supports {limit_hold:.1f} min"
            ),
        )
    )
    return checks
