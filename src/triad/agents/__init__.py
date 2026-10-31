"""Agent construction and failover (the only place private parts are unpacked)."""

from __future__ import annotations

import os

from triad.agents.base import BaseAgent
from triad.agents.stub import StubAgent
from triad.config import load_yaml
from triad.schemas import AgentRole, DisruptionEvent

_ROLES = (AgentRole.ATC, AgentRole.PILOT, AgentRole.GROUND)


def _private_for(event: DisruptionEvent, role: AgentRole):
    if role is AgentRole.ATC:
        return event.atc
    if role is AgentRole.PILOT:
        return event.pilot
    return event.ground


def build_agents(
    event: DisruptionEvent,
    *,
    impl: str = "stub",
    red_team: bool = False,
    client=None,
    use_cache: bool = True,
) -> dict[AgentRole, BaseAgent]:
    """Build fresh agents, giving each one only its private part and its own config."""
    if impl not in {"stub", "llm"}:
        raise NotImplementedError(f"agent impl {impl!r} is not available; use 'stub' or 'llm'")

    shared_client = client
    clients_by_model: dict[str, object] = {}
    default_model = None
    if impl == "llm" and shared_client is None:
        from triad.llm.client import DEFAULT_MODEL, LLMClient, _load_env

        _load_env()  # .env must be loaded before LLM_MODEL / LLM_MODEL_<ROLE> are read
        default_model = os.getenv("LLM_MODEL") or DEFAULT_MODEL

    def client_for(role: AgentRole):
        if impl != "llm" or shared_client is not None:
            return shared_client
        from triad.llm.client import LLMClient

        assert default_model is not None
        model = os.getenv(f"LLM_MODEL_{role.value}") or default_model
        if model not in clients_by_model:
            clients_by_model[model] = LLMClient(model=model, cache=use_cache)
        return clients_by_model[model]

    agents: dict[AgentRole, BaseAgent] = {}
    for role in _ROLES:
        cfg = load_yaml(f"agents/{role.value.lower()}")
        private = _private_for(event, role)
        if impl == "llm":
            from triad.agents.llm import LLMAgent

            agents[role] = LLMAgent(
                role,
                private,
                cfg,
                client_for(role),
                red_team=red_team and role is AgentRole.PILOT,
            )
        else:
            agents[role] = StubAgent(
                role,
                private,
                cfg,
                red_team=red_team and role is AgentRole.PILOT,
            )
    return agents


def failover(agent: BaseAgent) -> BaseAgent:
    """Replace a bad agent with its stub, preserving role, private state and config."""
    return StubAgent(agent.role, agent._private, agent.cfg)  # noqa: SLF001 (inside agents package)
