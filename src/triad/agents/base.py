"""Agent interface (frozen contract).

Each subagent = perceive (stub now, LLM+RAG later) -> check (code) -> decide (stub now, LLM later).
The orchestrator only calls: turn1, turn2, turn3, check, cost_eur, private_fingerprint.
Protocol: T1 PROPOSE -> T2 BALLOT (+ optional counter) -> T3 FINAL BALLOT -> deterministic fallback.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from triad.schemas import (
    AgentRole,
    BallotMessage,
    CandidateOption,
    ConstraintCheck,
    PerceivedFact,
    ProposalMessage,
    PublicEvent,
    PublicSummary,
)


class CheckIdGen:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.n = 0

    def __call__(self) -> str:
        self.n += 1
        return f"chk-{self.prefix}-{self.n:04d}"


class BaseAgent(ABC):
    impl: str = "base"

    def __init__(self, role: AgentRole, private: BaseModel, cfg: dict[str, Any]) -> None:
        self.role = role
        self._private = private  # never exposed to the orchestrator or other agents
        self.cfg = cfg  # config/agents/<role>.yaml
        self.weights: dict[str, float] = cfg.get("weights", {})
        self._facts: list[PerceivedFact] | None = None
        self._next_check_id = CheckIdGen(role.value)

    # ---------------------------------------------------------------- perceive
    def perceive(self, public: PublicEvent) -> list[PerceivedFact]:
        """Cached per run. Override in LLM agents; default is stub perception."""
        if self._facts is None:
            from triad.agents.perception import stub_perceive

            self._facts = stub_perceive(self.role, public, self._private)
        return self._facts

    def facts_dict(self, public: PublicEvent) -> dict[str, PerceivedFact]:
        return {f.key: f for f in self.perceive(public)}

    # ---------------------------------------------------------------- check (code only)
    def check(self, public: PublicEvent, option: CandidateOption) -> list[ConstraintCheck]:
        from triad.constraints.registry import check_owned

        return check_owned(self.role, public, self._private, self.facts_dict(public), option, self._next_check_id)

    def feasible(self, public: PublicEvent, option: CandidateOption) -> bool:
        return all(c.passed for c in self.check(public, option) if c.hard)

    # ---------------------------------------------------------------- scoring (code only, own weights)
    def objectives(self, public: PublicEvent, option: CandidateOption) -> dict[str, float]:
        from triad.agents.scoring import objectives

        return objectives(self.role, public, self._private, self.facts_dict(public), option)

    def utility(self, public: PublicEvent, option: CandidateOption) -> float:
        obj = self.objectives(public, option)
        return 1.0 - sum(self.weights.get(k, 0.0) * v for k, v in obj.items())

    def cost_eur(self, public: PublicEvent, option: CandidateOption) -> dict[str, float]:
        """Disclosed money cost (no raw private values). Used by fallback + tie-breaks."""
        from triad.agents.scoring import cost_eur

        return cost_eur(self.role, public, self._private, self.facts_dict(public), option)

    def private_fingerprint(self) -> str:
        return hashlib.sha256(self._private.model_dump_json().encode()).hexdigest()

    # ---------------------------------------------------------------- decide
    @abstractmethod
    def turn1(self, public: PublicEvent, options: list[CandidateOption]) -> ProposalMessage: ...

    @abstractmethod
    def turn2(
        self,
        public: PublicEvent,
        shortlist: list[CandidateOption],
        summaries: list[PublicSummary],
        *,
        fallback_option: CandidateOption | None = None,
    ) -> BallotMessage: ...

    def turn3(
        self,
        public: PublicEvent,
        shortlist: list[CandidateOption],
        summaries: list[PublicSummary],
        *,
        fallback_option: CandidateOption | None = None,
    ) -> BallotMessage:
        """Final ballot. Default: same decision logic as turn2, no counter-option allowed.

        ``summaries`` describe the other agents' Turn 2 ballots (votes + reasons).
        Override in agents that reason differently in the final round.
        """
        msg = self.turn2(public, shortlist, summaries, fallback_option=fallback_option)
        return msg.model_copy(update={"turn": 3, "counter_option": None})
