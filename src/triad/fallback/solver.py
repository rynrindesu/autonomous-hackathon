"""Deterministic, no-AI fallback: pick the cheapest safe option."""

from __future__ import annotations

from collections.abc import Mapping

from triad.schemas import AgentRole, CandidateOption, PublicEvent


def solve(
    public: PublicEvent,
    candidates: list[CandidateOption],
    agents: Mapping[AgentRole, object],
) -> tuple[CandidateOption | None, dict[str, dict[str, float]]]:
    """Return the cheapest option by total disclosed EUR cost, tie-broken by option_id.

    ``costs`` maps option_id -> {role: total_eur} for the log.
    """
    if not candidates:
        return None, {}

    costs: dict[str, dict[str, float]] = {}
    totals: dict[str, float] = {}
    for option in candidates:
        per_agent: dict[str, float] = {}
        for role in (AgentRole.ATC, AgentRole.PILOT, AgentRole.GROUND):
            agent = agents[role]
            breakdown = agent.cost_eur(public, option)  # type: ignore[attr-defined]
            per_agent[role.value] = float(sum(breakdown.values()))
        costs[option.option_id] = per_agent
        totals[option.option_id] = float(sum(per_agent.values()))

    chosen = min(candidates, key=lambda o: (totals[o.option_id], o.option_id))
    return chosen, costs
