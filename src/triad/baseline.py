"""SIMULATED first-come-first-served (FCFS) baseline (PLAN §13).

Not a model of any real ATC procedure: a simple stand-in for "no negotiation".
It takes the generated options, keeps those that pass every hard check (shared
checks + all three agents' checkers), and commits the one with the earliest
arrival slot, ignoring agent priorities and costs. Ties break by ``option_id``.
Destination options always come first (FCFS lands at the destination); the
diversion is taken only if no destination option is safe, the same last resort
the protocol has. If nothing is safe the baseline returns ``ESCALATED``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from triad.metrics import DIVERT_ID, ROLES, RunMetrics, run_metrics
from triad.schemas import AgentRole, CandidateOption, ConstraintCheck, DisruptionEvent, Resolution

FCFS_LABEL = "fcfs"
FCFS_REASON = "SIMULATED_FCFS_BASELINE"


def _all_checks(
    event: DisruptionEvent, option: CandidateOption, agents: Mapping[AgentRole, Any], next_id
) -> list[ConstraintCheck]:
    from triad.constraints.shared import shared_checks

    checks = list(shared_checks(event.public, option, next_id))
    for role in ROLES:
        checks.extend(agents[role].check(event.public, option))
    return checks


def _is_divert(option: CandidateOption) -> bool:
    return bool(option.divert_to) or option.option_id == DIVERT_ID


def _safe_options(
    event: DisruptionEvent, agents: Mapping[AgentRole, Any], options: list[CandidateOption]
) -> list[tuple[CandidateOption, list[ConstraintCheck]]]:
    """Options passing every hard check: destination options by earliest arrival, divert last."""
    from triad.agents.base import CheckIdGen

    next_id = CheckIdGen("FCFS")
    safe: list[tuple[CandidateOption, list[ConstraintCheck]]] = []
    for option in sorted(options, key=lambda o: (_is_divert(o), o.arrival_slot, o.option_id)):
        checks = _all_checks(event, option, agents, next_id)
        if not any(c.hard and not c.passed for c in checks):
            safe.append((option, checks))
    return safe


def _defaults(
    event: DisruptionEvent,
    agents: Mapping[AgentRole, Any] | None,
    options: list[CandidateOption] | None,
) -> tuple[Mapping[AgentRole, Any], list[CandidateOption]]:
    if agents is None:
        from triad.agents import build_agents

        agents = build_agents(event, impl="stub")
    if options is None:
        from triad.options.generator import generate_options

        options = generate_options(event.public)
    return agents, options


def _resolve(
    event: DisruptionEvent,
    agents: Mapping[AgentRole, Any],
    safe: list[tuple[CandidateOption, list[ConstraintCheck]]],
) -> Resolution:
    if not safe:
        return Resolution(
            run_id=event.public.run_id,
            status="ESCALATED",
            turn=0,
            decided_by="HUMAN_ESCALATION",
            option=None,
            reason=f"{FCFS_REASON}: NO_SAFE_OPTION",
        )
    option, checks = safe[0]
    costs = {
        role.value: round(float(sum(agents[role].cost_eur(event.public, option).values())), 2)
        for role in ROLES
    }
    return Resolution(
        run_id=event.public.run_id,
        status="FALLBACK",
        turn=0,
        decided_by="FALLBACK",
        option=option,
        reason=FCFS_REASON,
        checks=checks,
        costs_eur=costs,
    )


def fcfs_resolution(
    event: DisruptionEvent,
    agents: Mapping[AgentRole, Any] | None = None,
    options: list[CandidateOption] | None = None,
) -> Resolution:
    """Earliest-arrival safe option, or ESCALATED. Agents default to stubs."""
    agents, options = _defaults(event, agents, options)
    return _resolve(event, agents, _safe_options(event, agents, options))


def run_fcfs(
    event: DisruptionEvent,
    agents: Mapping[AgentRole, Any] | None = None,
    options: list[CandidateOption] | None = None,
) -> tuple[Resolution, RunMetrics]:
    """FCFS resolution plus its metrics, in the same shape as negotiated runs."""
    agents, options = _defaults(event, agents, options)
    safe = _safe_options(event, agents, options)
    resolution = _resolve(event, agents, safe)
    metrics = run_metrics(
        resolution, None, event=event, agents=agents, label=FCFS_LABEL, simulated=True
    )
    return resolution, metrics.model_copy(
        update={"n_feasible": sum(1 for o, _ in safe if not _is_divert(o))}
    )


__all__ = ["FCFS_LABEL", "FCFS_REASON", "fcfs_resolution", "run_fcfs"]
