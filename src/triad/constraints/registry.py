"""Role-owned constraint registry.

The orchestrator calls ``check_owned`` for counter-options and at commit; each
agent's ``check`` calls the same function.  Only the matching private model is
passed, so an agent can never see another party's data.
"""

from __future__ import annotations

from typing import Callable

from triad.constraints import crew, fuel, gate, mel, runway, turnaround, wake, weather
from triad.schemas import (
    AgentRole,
    AtcPrivate,
    CandidateOption,
    ConstraintCheck,
    GroundPrivate,
    PerceivedFact,
    PilotPrivate,
    PublicEvent,
)


def check_owned(
    role: AgentRole,
    public: PublicEvent,
    private: AtcPrivate | PilotPrivate | GroundPrivate,
    facts: dict[str, PerceivedFact],
    option: CandidateOption,
    next_id: Callable[[], str],
) -> list[ConstraintCheck]:
    if role == AgentRole.ATC:
        assert isinstance(private, AtcPrivate)
        return (
            wake.check_wake(public, private, facts, option, next_id)
            + runway.check_runway(public, private, facts, option, next_id)
            + runway.check_taxiway(public, private, facts, option, next_id)
        )

    if role == AgentRole.PILOT:
        assert isinstance(private, PilotPrivate)
        return (
            fuel.check_fuel(public, private, facts, option, next_id)
            + weather.check_weather(public, private, facts, option, next_id)
            + weather.check_duty(public, private, facts, option, next_id)
        )

    if role == AgentRole.GROUND:
        assert isinstance(private, GroundPrivate)
        return (
            gate.check_gates(public, private, facts, option, next_id)
            + turnaround.check_turnaround(public, private, facts, option, next_id)
            + crew.check_crew(public, private, facts, option, next_id)
            + mel.check_mel(public, private, facts, option, next_id)
        )

    raise ValueError(f"unknown role {role!r}")
