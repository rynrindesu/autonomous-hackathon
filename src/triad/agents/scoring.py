"""Per-agent soft objectives and disclosed money costs (code only).

Objectives are normalised to ``[0, 1]`` with 0 = best.  The keys match the
weights in ``config/agents/*.yaml`` so the stub can rank options without an LLM.
"""

from __future__ import annotations

from typing import Any

from triad.config import load_yaml
from triad.constraints import crew, fuel, turnaround
from triad.schemas import (
    AgentRole,
    AtcPrivate,
    CandidateOption,
    GroundPrivate,
    Mode,
    PerceivedFact,
    PilotPrivate,
    PublicEvent,
)


def _clip(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _level_for(private: PilotPrivate, option: CandidateOption) -> str:
    if option.cruise_level is not None:
        level = int(option.cruise_level)
    elif private.cruise_levels:
        level = int(private.cruise_levels[0])
    else:
        level = 340
    return f"FL{level}"


def _turbulence_obj(
    private: PilotPrivate, facts: dict[str, PerceivedFact], option: CandidateOption
) -> float:
    if option.divert_to:
        return 0.5
    key = _level_for(private, option)
    fact = facts.get("turbulence")
    levels = fact.value if fact is not None and isinstance(fact.value, dict) else {}
    observed = str(levels.get(key, "SEVERE"))
    return {"NONE": 0.0, "LIGHT": 0.25, "MODERATE": 0.7, "SEVERE": 1.0}.get(observed, 1.0)


def _delay_min(public: PublicEvent, option: CandidateOption) -> int:
    return max(0, int(option.arrival_slot) - int(public.expected_eta))


def _missed_connection_pax(private: PilotPrivate, option: CandidateOption) -> int:
    missed = 0
    for connection in private.connections:
        latest_connect = connection.scheduled_departure - connection.mct_min
        if option.arrival_slot > latest_connect:
            missed += connection.pax
    return missed


def _fuel_objective(
    public: PublicEvent, private: PilotPrivate, option: CandidateOption
) -> float:
    if option.divert_to:
        return 0.85
    capacity = (
        private.fuel_on_board_kg
        + (private.max_extra_fuel_kg if public.mode == Mode.GROUND else 0.0)
        - private.fuel_to_destination_kg
        - private.fuel_to_alternate_kg
        - private.reserve_45_kg
    )
    extra = fuel.extra_burn_kg(public, private, option)
    return _clip(extra / max(1.0, capacity))


def _atc_objectives(
    public: PublicEvent, private: AtcPrivate, option: CandidateOption
) -> dict[str, float]:
    delay = _delay_min(public, option)
    baseline_runway = public.destination_runways[0] if public.destination_runways else None
    runway_changed = 1.0 if baseline_runway and option.runway != baseline_runway else 0.0
    return {
        "THROUGHPUT": _clip(delay / 90.0),
        "HOLDING_STACK": _clip(option.holding_min / 90.0),
        "OTHER": _clip(0.5 * runway_changed + 0.5 * delay / 120.0),
    }


def _pilot_objectives(
    public: PublicEvent,
    private: PilotPrivate,
    facts: dict[str, PerceivedFact],
    option: CandidateOption,
) -> dict[str, float]:
    total_pax = sum(c.pax for c in private.connections)
    missed = _missed_connection_pax(private, option)
    missed_frac = (missed / total_pax) if total_pax else 0.0
    return {
        "FUEL": _fuel_objective(public, private, option),
        "DELAY": _clip(_delay_min(public, option) / 120.0),
        "PAX_CONNECTIONS": _clip(missed_frac),
        "TURBULENCE": _turbulence_obj(private, facts, option),
    }


def _ground_objectives(
    public: PublicEvent, private: GroundPrivate, option: CandidateOption
) -> dict[str, float]:
    overtime = crew.overtime_min(private, option.arrival_slot)
    gate_change = 1.0 if option.gate != private.current_gate else 0.0
    if option.divert_to:
        next_leg = 1.0 if private.next_leg is not None else 0.0
    else:
        next_leg = _clip(turnaround.next_leg_delay_min(public, private, option) / 120.0)
    return {
        "OVERTIME": _clip(overtime / 120.0),
        "GATE_CHANGE": gate_change,
        "NEXT_LEG": next_leg,
        "DELAY": _clip(_delay_min(public, option) / 120.0),
    }


def objectives(
    role: AgentRole,
    public: PublicEvent,
    private: AtcPrivate | PilotPrivate | GroundPrivate,
    facts: dict[str, PerceivedFact],
    option: CandidateOption,
) -> dict[str, float]:
    if role == AgentRole.ATC:
        assert isinstance(private, AtcPrivate)
        return _atc_objectives(public, private, option)
    if role == AgentRole.PILOT:
        assert isinstance(private, PilotPrivate)
        return _pilot_objectives(public, private, facts, option)
    if role == AgentRole.GROUND:
        assert isinstance(private, GroundPrivate)
        return _ground_objectives(public, private, option)
    raise ValueError(f"unknown role {role!r}")


# --------------------------------------------------------------------------- money


def _atc_cost(
    public: PublicEvent, private: AtcPrivate, option: CandidateOption, costs: dict[str, Any]
) -> dict[str, float]:
    out = {
        "holding_stack": float(costs["holding_stack_eur_per_min"]) * option.holding_min,
    }
    baseline_runway = public.destination_runways[0] if public.destination_runways else None
    if baseline_runway and option.runway != baseline_runway:
        out["runway_change"] = float(costs["runway_change_eur"])
    return out


def _pilot_cost(
    public: PublicEvent,
    private: PilotPrivate,
    facts: dict[str, PerceivedFact],
    option: CandidateOption,
    costs: dict[str, Any],
) -> dict[str, float]:
    out: dict[str, float] = {}
    extra_kg = fuel.extra_burn_kg(public, private, option)
    out["fuel"] = extra_kg * float(costs["fuel_eur_per_kg"])
    out["arrival_delay"] = _delay_min(public, option) * float(
        costs["arrival_delay_eur_per_min"]
    )
    out["missed_connections"] = _missed_connection_pax(private, option) * float(
        costs["missed_connection_eur_per_pax"]
    )
    if not option.divert_to and _turbulence_obj(private, facts, option) >= 0.7:
        out["turbulence"] = float(costs["turbulence_moderate_eur"])
    if option.divert_to:
        out["divert"] = float(costs["divert_eur"])
    return out


def _ground_cost(
    public: PublicEvent, private: GroundPrivate, option: CandidateOption, costs: dict[str, Any]
) -> dict[str, float]:
    out: dict[str, float] = {}
    overtime = crew.overtime_min(private, option.arrival_slot)
    shift, _ = crew.covering_shift(private, option.arrival_slot)
    rate = shift.overtime_eur_per_min if shift is not None else 6.0
    out["overtime"] = overtime * float(rate)
    if option.gate != private.current_gate:
        out["gate_change"] = float(private.gate_change_eur)
    next_delay = turnaround.next_leg_delay_min(public, private, option)
    out["next_leg_delay"] = next_delay * float(costs["next_leg_delay_eur_per_min"])
    if option.next_leg_action == "SWAP_AIRCRAFT":
        out["swap"] = float(costs["swap_aircraft_eur"])
    return out


def cost_eur(
    role: AgentRole,
    public: PublicEvent,
    private: AtcPrivate | PilotPrivate | GroundPrivate,
    facts: dict[str, PerceivedFact],
    option: CandidateOption,
) -> dict[str, float]:
    """Component money costs in EUR (no ``total`` key: callers sum components)."""

    costs = load_yaml("costs")
    if role == AgentRole.ATC:
        assert isinstance(private, AtcPrivate)
        return _atc_cost(public, private, option, costs)
    if role == AgentRole.PILOT:
        assert isinstance(private, PilotPrivate)
        return _pilot_cost(public, private, facts, option, costs)
    if role == AgentRole.GROUND:
        assert isinstance(private, GroundPrivate)
        return _ground_cost(public, private, option, costs)
    raise ValueError(f"unknown role {role!r}")
