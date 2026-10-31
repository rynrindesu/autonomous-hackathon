"""Deterministic, no-AI fallback: pick the cheapest safe option."""

from __future__ import annotations

from collections.abc import Mapping

from triad.schemas import AgentRole, CandidateOption, PublicEvent

_ROLES = (AgentRole.ATC, AgentRole.PILOT, AgentRole.GROUND)


def _eur(value: float) -> str:
    return f"€{value:,.0f}"


def explain_choice(
    chosen_id: str,
    costs: Mapping[str, Mapping[str, float]],
) -> str:
    """Human-readable tie-break explanation for the fallback choice.

    ``costs`` maps option_id -> {role: total_eur} (the second value returned by ``solve``).
    """
    totals = {oid: float(sum(per.values())) for oid, per in costs.items()}
    if chosen_id not in totals:
        return f"{chosen_id} chosen (no cost data)."
    per = costs[chosen_id]
    breakdown = " + ".join(f"{role} {_eur(float(per.get(role, 0.0)))}" for role in per)
    total = totals[chosen_id]
    if len(totals) == 1:
        return f"{chosen_id} is the only safe candidate (total {_eur(total)} = {breakdown})."
    ranked = sorted(totals, key=lambda oid: (totals[oid], oid))
    tied = [oid for oid in ranked if abs(totals[oid] - total) < 1e-6]
    text = (
        f"{chosen_id} has the lowest total disclosed cost among {len(totals)} safe candidates: "
        f"{_eur(total)} ({breakdown})."
    )
    if len(tied) > 1:
        others = ", ".join(oid for oid in tied if oid != chosen_id)
        text += f" It ties with {others} at {_eur(total)}; the tie is broken by option_id ({chosen_id} sorts first)."
    else:
        runner_up = next(oid for oid in ranked if oid != chosen_id)
        text += (
            f" Next cheapest is {runner_up} at {_eur(totals[runner_up])} "
            f"(+{_eur(totals[runner_up] - total)})."
        )
    return text


def solve_explained(
    public: PublicEvent,
    candidates: list[CandidateOption],
    agents: Mapping[AgentRole, object],
) -> tuple[CandidateOption | None, dict[str, dict[str, float]], str]:
    """Like ``solve`` but also returns the tie-break explanation for the log."""
    if not candidates:
        return None, {}, "no safe candidate: nothing to choose from."

    costs: dict[str, dict[str, float]] = {}
    totals: dict[str, float] = {}
    for option in candidates:
        per_agent: dict[str, float] = {}
        for role in _ROLES:
            agent = agents[role]
            breakdown = agent.cost_eur(public, option)  # type: ignore[attr-defined]
            per_agent[role.value] = float(sum(breakdown.values()))
        costs[option.option_id] = per_agent
        totals[option.option_id] = float(sum(per_agent.values()))

    chosen = min(candidates, key=lambda o: (totals[o.option_id], o.option_id))
    return chosen, costs, explain_choice(chosen.option_id, costs)


def solve(
    public: PublicEvent,
    candidates: list[CandidateOption],
    agents: Mapping[AgentRole, object],
) -> tuple[CandidateOption | None, dict[str, dict[str, float]]]:
    """Return the cheapest option by total disclosed EUR cost, tie-broken by option_id.

    ``costs`` maps option_id -> {role: total_eur} for the log.
    Use ``solve_explained`` (or ``explain_choice``) for the human-readable tie-break.
    """
    chosen, costs, _explanation = solve_explained(public, candidates, agents)
    return chosen, costs
