"""The deterministic orchestrator (PLAN §5).

Receives only ``PublicEvent`` + agent objects.  It never sees a
``DisruptionEvent`` or any private data.  Hard feasibility always comes from
code checkers, never from an agent's (possibly compromised) veto list.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from triad.agents.base import CheckIdGen
from triad.coordinator.aggregate import borda, order
from triad.coordinator.safety import UnsafeCommitError, assert_commit_safe
from triad.fallback.solver import solve
from triad.log.consensus_log import ConsensusLog, sha256_json
from triad.schemas import (
    AgentRole,
    BallotMessage,
    CandidateOption,
    ConstraintCheck,
    CounterOption,
    ProposalMessage,
    PublicEvent,
    PublicSummary,
    Resolution,
)

TURN_ORDER = (AgentRole.ATC, AgentRole.PILOT, AgentRole.GROUND)
_FORBIDDEN_COUNTER_FIELDS = {"option_id", "origin", "proposed_by", "base_option_id"}
_DIVERT_ID = "OPT-DIV"


class Orchestrator:
    def __init__(
        self,
        public: PublicEvent,
        agents: Mapping[AgentRole, Any],
        log: ConsensusLog,
        *,
        option_generator: Callable[[PublicEvent], list[CandidateOption]] | None = None,
        shared_checker: Callable[[PublicEvent, CandidateOption, Callable[[], str]], list[ConstraintCheck]]
        | None = None,
        max_turns: int = 2,
        failover_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        assert max_turns == 2, "the protocol is hard-capped at two turns"
        self.public = public
        self.agents: dict[AgentRole, Any] = dict(agents)
        self.log = log
        self._option_generator = option_generator
        self._shared_checker = shared_checker
        self._failover_factory = failover_factory
        self._next_shared_id = CheckIdGen("SHR")
        self._all_options: list[CandidateOption] = []

    # ------------------------------------------------------------------ lazy WORLD deps
    def _generate(self, public: PublicEvent) -> list[CandidateOption]:
        if self._option_generator is not None:
            return self._option_generator(public)
        from triad.options.generator import generate_options

        return generate_options(public)

    def _shared_call(
        self, public: PublicEvent, option: CandidateOption, next_id: Callable[[], str]
    ) -> list[ConstraintCheck]:
        if self._shared_checker is not None:
            return self._shared_checker(public, option, next_id)
        from triad.constraints.shared import shared_checks

        return shared_checks(public, option, next_id)

    def _shared(self, option: CandidateOption) -> list[ConstraintCheck]:
        return self._shared_call(self.public, option, self._next_shared_id)

    def _failover(self, agent: Any) -> Any:
        if self._failover_factory is not None:
            return self._failover_factory(agent)
        from triad.agents import failover

        return failover(agent)

    # ------------------------------------------------------------------ entry point
    def run(self, ai_off: bool = False) -> Resolution:
        options = self._setup()
        if ai_off:
            return self._run_ai_off(options)
        return self._run_negotiation(options)

    # ------------------------------------------------------------------ setup (turn 0)
    def _setup(self) -> list[CandidateOption]:
        public = self.public
        self.log.append(
            0,
            "ORCHESTRATOR",
            "SETUP",
            {
                "run_id": public.run_id,
                "mode": public.mode.value,
                "disruption_type": public.disruption_type.value,
                "decision_time": public.decision_time,
                "original_eta": public.original_eta,
                "expected_eta": public.expected_eta,
            },
        )
        raw = list(self._generate(public))
        self._all_options = list(raw)
        shared: dict[str, list[ConstraintCheck]] = {}
        for option in raw:
            checks = list(self._shared(option))
            shared[option.option_id] = checks
            self.log.append(
                0,
                "ORCHESTRATOR",
                "SHARED_CHECKS",
                {
                    "option_id": option.option_id,
                    "passed": all(c.passed for c in checks if c.hard),
                    "checks": [c.model_dump(mode="json") for c in checks],
                },
            )

        kept = [o for o in raw if all(c.passed for c in shared[o.option_id] if c.hard)]
        self.log.append(
            0,
            "ORCHESTRATOR",
            "OPTIONS_GENERATED",
            {
                "option_ids": [o.option_id for o in raw],
                "shared_passed": [o.option_id for o in kept],
                "options": [o.model_dump(mode="json") for o in raw],
            },
        )
        return kept

    # ------------------------------------------------------------------ AI off
    def _run_ai_off(self, options: list[CandidateOption]) -> Resolution:
        feasible = [o for o in options if self._passes_all_agents(o)]
        if not feasible:
            return self._escalate(
                turn=0,
                reason="NO_SAFE_OPTION; recommend diversion to " + self._first_alternate(),
            )
        chosen, costs = solve(self.public, feasible, self.agents)
        assert chosen is not None
        self.log.append(
            0,
            "FALLBACK",
            "FALLBACK_INVOKED",
            {
                "reason": "AI_OFF",
                "pool": [o.option_id for o in feasible],
                "option_id": chosen.option_id,
                "costs": costs,
            },
        )
        return self._commit(
            chosen,
            turn=0,
            status="FALLBACK",
            decided_by="FALLBACK",
            reason="AI_OFF",
            pool=feasible,
        )

    # ------------------------------------------------------------------ negotiation
    def _run_negotiation(self, options: list[CandidateOption]) -> Resolution:
        if not options:
            return self._escalate(
                turn=1, reason="NO_SAFE_OPTION; recommend diversion to " + self._first_alternate()
            )

        proposals: dict[AgentRole, ProposalMessage] = {}
        turn1_results = self._collect_turn1(options)
        for role in TURN_ORDER:
            agent, message, manifest = turn1_results[role]
            proposals[role] = message
            self.log.append(
                1,
                role.value,
                "PROPOSAL",
                message.model_dump(mode="json"),
                context_manifest={role.value: manifest},
                usage=self._usage_payload(agent),
            )

        # ---- code truth, never the veto list
        table: dict[tuple[AgentRole, str], list[ConstraintCheck]] = {}
        for role in TURN_ORDER:
            agent = self.agents[role]
            for option in options:
                table[(role, option.option_id)] = list(agent.check(self.public, option))

        for role in TURN_ORDER:
            message = proposals[role]
            code_failed = {
                o.option_id
                for o in options
                if any(c.hard and not c.passed for c in table[(role, o.option_id)])
            }
            declared = {v.option_id for v in message.vetoes}
            for oid in sorted(declared - code_failed):
                self.log.append(
                    1,
                    "ORCHESTRATOR",
                    "SAFETY_BLOCK",
                    {"role": role.value, "option_id": oid, "detail": "fabricated veto"},
                )
            for oid in sorted(code_failed - declared):
                self.log.append(
                    1,
                    "ORCHESTRATOR",
                    "SAFETY_BLOCK",
                    {"role": role.value, "option_id": oid, "detail": "omitted veto"},
                )

        feasible = [o for o in options if self._passes_all(o, table)]

        # ---- counters: materialise + code-only validation
        counters = self._validate_counters(proposals, options)

        if not feasible and not counters:
            return self._escalate(
                turn=1,
                reason="NO_SAFE_OPTION; recommend diversion to " + self._first_alternate(),
            )

        # ---- fast path
        tops = [proposals[role].ranking[0] if proposals[role].ranking else None for role in TURN_ORDER]
        if tops[0] is not None and all(t == tops[0] for t in tops):
            top_id = tops[0]
            top = next((o for o in feasible if o.option_id == top_id), None)
            objected = any(obj.option_id == top_id for role in TURN_ORDER for obj in proposals[role].objections)
            if top is not None and not objected:
                return self._commit(
                    top,
                    turn=1,
                    status="CONSENSUS",
                    decided_by="AGENTS",
                    reason="UNANIMOUS_FIRST_CHOICE",
                    pool=feasible + counters,
                )

        # ---- Borda shortlist (divert only if it is the only feasible option)
        base_pool = [o for o in feasible if o.option_id != _DIVERT_ID] or list(feasible)
        rankings = {role: proposals[role].ranking for role in TURN_ORDER}
        base_scores = borda(rankings, [o.option_id for o in base_pool])
        first_votes = {
            oid: sum(1 for r in rankings.values() if r and r[0] == oid) for oid in base_scores
        }
        tie_cost = self._total_costs(base_pool)
        ordered_pool = order(base_scores, first_votes, tie_cost)

        scores: dict[str, float] = dict(base_scores)
        for counter in counters:
            scores[counter.option_id] = base_scores.get(counter.base_option_id or "", 0.0)
            first_votes[counter.option_id] = first_votes.get(counter.base_option_id or "", 0)

        counter_cost = self._total_costs(counters)
        ordered_counters = sorted(
            (c.option_id for c in counters),
            key=lambda oid: (-scores.get(oid, 0.0), -first_votes.get(oid, 0), counter_cost.get(oid, 0.0), oid),
        )
        shortlist_ids = list(ordered_pool[:3])
        for oid in ordered_counters:
            if oid not in shortlist_ids:
                shortlist_ids.append(oid)
        shortlist_ids = shortlist_ids[:6]
        by_id = {o.option_id: o for o in list(base_pool) + counters}
        shortlist = [by_id[oid] for oid in shortlist_ids if oid in by_id]

        # Shadow of the fallback: tell agents what will happen if they don't agree.
        fallback_projection, _fallback_costs = solve(
            self.public, feasible + counters, self.agents
        )
        fallback_option_id = (
            fallback_projection.option_id if fallback_projection is not None else None
        )

        self.log.append(
            1,
            "ORCHESTRATOR",
            "SHORTLIST",
            {
                "option_ids": [o.option_id for o in shortlist],
                "scores": scores,
                "first_votes": first_votes,
                "fallback_option_id": fallback_option_id,
            },
        )

        if not shortlist:
            return self._escalate(
                turn=1,
                reason="NO_SAFE_OPTION; recommend diversion to " + self._first_alternate(),
            )

        summaries = self._summaries(proposals, counters, table, options)

        # ---- turn 2
        ballots: dict[AgentRole, BallotMessage] = {}
        turn2_results = self._collect_turn2(shortlist, summaries, fallback_projection)
        for role in TURN_ORDER:
            agent, ballot, manifest = turn2_results[role]
            ballots[role] = ballot
            self.log.append(
                2,
                role.value,
                "BALLOT",
                ballot.model_dump(mode="json"),
                context_manifest={role.value: manifest},
                usage=self._usage_payload(agent),
            )

        # ---- honour only shortlisted, code-safe approvals
        shortlist_checks = {
            option.option_id: self._checks_for_all(option) for option in shortlist
        }
        safe_shortlist = {
            oid for oid, checks in shortlist_checks.items() if all(c.passed for c in checks if c.hard)
        }
        approvals: dict[AgentRole, set[str]] = {}
        for role in TURN_ORDER:
            ballot = ballots[role]
            allowed: set[str] = set()
            for vote in ballot.votes:
                if vote.option_id not in shortlist_ids:
                    if vote.vote == "APPROVE":
                        self.log.append(
                            2,
                            "ORCHESTRATOR",
                            "SAFETY_BLOCK",
                            {
                                "role": role.value,
                                "option_id": vote.option_id,
                                "detail": "approve outside shortlist",
                            },
                        )
                    continue
                if vote.vote == "APPROVE":
                    if vote.option_id not in safe_shortlist:
                        self.log.append(
                            2,
                            "ORCHESTRATOR",
                            "SAFETY_BLOCK",
                            {
                                "role": role.value,
                                "option_id": vote.option_id,
                                "detail": "approve of unsafe option",
                            },
                        )
                        continue
                    allowed.add(vote.option_id)
            approvals[role] = allowed

        approved_by_all = [
            oid
            for oid in shortlist_ids
            if all(oid in approvals[role] for role in TURN_ORDER)
        ]

        if approved_by_all:
            rankings2 = {role: ballots[role].ranking for role in TURN_ORDER}
            scores2 = borda(rankings2, approved_by_all)
            first2 = {
                oid: sum(1 for r in rankings2.values() if r and r[0] == oid) for oid in approved_by_all
            }
            cost2 = self._total_costs([by_id[oid] for oid in approved_by_all if oid in by_id])
            chosen_id = order(scores2, first2, cost2)[0]
            chosen = next(
                (o for o in shortlist if o.option_id == chosen_id),
                by_id.get(chosen_id),
            )
            if chosen is not None:
                return self._commit(
                    chosen,
                    turn=2,
                    status="CONSENSUS",
                    decided_by="AGENTS",
                    reason="UNANIMOUS_APPROVAL",
                    pool=feasible + counters,
                )

        pool = feasible + counters
        chosen, costs = solve(self.public, pool, self.agents)
        if chosen is None:
            return self._escalate(
                turn=2,
                reason="NO_SAFE_OPTION; recommend diversion to " + self._first_alternate(),
            )
        self.log.append(
            2,
            "FALLBACK",
            "FALLBACK_INVOKED",
            {
                "reason": "NO_UNANIMOUS_APPROVAL",
                "pool": [o.option_id for o in pool],
                "option_id": chosen.option_id,
                "costs": costs,
            },
        )
        return self._commit(
            chosen,
            turn=2,
            status="FALLBACK",
            decided_by="FALLBACK",
            reason="NO_UNANIMOUS_APPROVAL",
            pool=pool,
        )

    # ------------------------------------------------------------------ turns
    def _parallel(self, call: Callable[[AgentRole], Any]) -> dict[AgentRole, Any]:
        """Run one call per role concurrently; return results/errors keyed by role."""
        results: dict[AgentRole, Any] = {}
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="triad-turn") as pool:
            futures = {role: pool.submit(call, role) for role in TURN_ORDER}
            for role in TURN_ORDER:
                try:
                    results[role] = futures[role].result()
                except Exception as exc:  # noqa: BLE001 - surfaced as failover
                    results[role] = exc
        return results

    def _usage_payload(self, agent: Any) -> dict[str, Any] | None:
        usage = getattr(agent, "last_usage", None)
        if not usage:
            return None
        return {agent.role.value: usage}

    def _collect_turn1(
        self, options: list[CandidateOption]
    ) -> dict[AgentRole, tuple[Any, ProposalMessage, str]]:
        known = {o.option_id for o in options}

        def attempt(role: AgentRole) -> tuple[Any, ProposalMessage | None, Exception | None]:
            agent = self.agents[role]
            try:
                message = agent.turn1(self.public, options)
                self._validate_proposal(role, message, known)
                return agent, message, None
            except Exception as exc:  # noqa: BLE001 - any bad response triggers failover
                return agent, None, exc

        raw = self._parallel(attempt)
        results: dict[AgentRole, tuple[Any, ProposalMessage, str]] = {}
        for role in TURN_ORDER:
            item = raw[role]
            if isinstance(item, Exception):
                agent, message, exc = self.agents[role], None, item
            else:
                agent, message, exc = item
            if exc is not None or message is None:
                self.log.append(
                    1,
                    "ORCHESTRATOR",
                    "AGENT_FAILOVER",
                    {
                        "role": role.value,
                        "turn": 1,
                        "error": f"{type(exc).__name__}: {exc}" if exc else "no proposal",
                    },
                )
                agent = self._failover(agent)
                self.agents[role] = agent
                message = agent.turn1(self.public, options)
                self._validate_proposal(role, message, known)
            manifest = self._context_manifest(
                role, 1, {"kind": "turn1", "options": _dump(options)}, agent
            )
            results[role] = (agent, message, manifest)
        return results

    def _collect_turn2(
        self,
        shortlist: list[CandidateOption],
        summaries: list[PublicSummary],
        fallback_option: CandidateOption | None = None,
    ) -> dict[AgentRole, tuple[Any, BallotMessage, str]]:
        shortlist_ids = [o.option_id for o in shortlist]
        known = set(shortlist_ids) | {o.option_id for o in self._all_options}

        def attempt(role: AgentRole) -> tuple[Any, BallotMessage | None, Exception | None]:
            agent = self.agents[role]
            try:
                ballot = agent.turn2(
                    self.public,
                    shortlist,
                    [s for s in summaries if s.sender != role],
                    fallback_option=fallback_option,
                )
                self._validate_ballot(role, ballot, shortlist_ids, known)
                return agent, ballot, None
            except Exception as exc:  # noqa: BLE001
                return agent, None, exc

        raw = self._parallel(attempt)
        results: dict[AgentRole, tuple[Any, BallotMessage, str]] = {}
        for role in TURN_ORDER:
            item = raw[role]
            if isinstance(item, Exception):
                agent, ballot, exc = self.agents[role], None, item
            else:
                agent, ballot, exc = item
            if exc is not None or ballot is None:
                self.log.append(
                    2,
                    "ORCHESTRATOR",
                    "AGENT_FAILOVER",
                    {
                        "role": role.value,
                        "turn": 2,
                        "error": f"{type(exc).__name__}: {exc}" if exc else "no ballot",
                    },
                )
                agent = self._failover(agent)
                self.agents[role] = agent
                ballot = agent.turn2(
                    self.public,
                    shortlist,
                    [s for s in summaries if s.sender != role],
                    fallback_option=fallback_option,
                )
                self._validate_ballot(role, ballot, shortlist_ids, known)
            manifest = self._context_manifest(
                role,
                2,
                {"kind": "turn2", "shortlist": _dump(shortlist), "summaries": _dump(summaries)},
                agent,
            )
            results[role] = (agent, ballot, manifest)
        return results

    # ------------------------------------------------------------------ validation
    def _validate_proposal(self, role: AgentRole, message: ProposalMessage, known: set[str]) -> None:
        if message.sender != role:
            raise ValueError(f"wrong sender {message.sender} for {role}")
        if message.run_id != self.public.run_id:
            raise ValueError(f"wrong run_id {message.run_id}")
        if len(set(message.ranking)) != len(message.ranking):
            raise ValueError("ranking contains duplicate option ids")
        unknown = [oid for oid in message.ranking if oid not in known]
        if unknown:
            raise ValueError(f"ranking contains unknown option ids: {unknown}")
        checks_by_id = {c.check_id: c for c in message.checks}
        for veto in message.vetoes:
            check = checks_by_id.get(veto.check_id)
            if check is None:
                raise ValueError(f"veto {veto.option_id} references unknown check {veto.check_id}")
            if check.option_id != veto.option_id:
                raise ValueError("veto option_id does not match its check")
            if check.constraint_id != veto.constraint_id:
                raise ValueError("veto constraint_id does not match its check")
            if check.passed:
                raise ValueError("veto references a passing check")

    def _validate_ballot(
        self,
        role: AgentRole,
        ballot: BallotMessage,
        shortlist_ids: list[str],
        known: set[str],
    ) -> None:
        if ballot.sender != role:
            raise ValueError(f"wrong sender {ballot.sender} for {role}")
        if ballot.run_id != self.public.run_id:
            raise ValueError(f"wrong run_id {ballot.run_id}")
        seen: set[str] = set()
        for vote in ballot.votes:
            if vote.option_id in seen:
                raise ValueError(f"duplicate vote for {vote.option_id}")
            seen.add(vote.option_id)
            if vote.vote == "DISAPPROVE" and not (vote.reason or "").strip():
                raise ValueError(f"DISAPPROVE for {vote.option_id} needs a reason")
        missing = [oid for oid in shortlist_ids if oid not in seen]
        if missing:
            raise ValueError(f"ballot missing votes for {missing}")
        unknown = [oid for oid in ballot.ranking if oid not in known]
        if unknown:
            raise ValueError(f"ballot ranking contains unknown option ids: {unknown}")

    # ------------------------------------------------------------------ counters
    def _validate_counters(
        self,
        proposals: dict[AgentRole, ProposalMessage],
        options: list[CandidateOption],
    ) -> list[CandidateOption]:
        by_base = {o.option_id: o for o in options}
        counters: list[CandidateOption] = []
        for role in TURN_ORDER:
            counter = proposals[role].counter_option
            if counter is None:
                continue
            candidate, error = self._materialise(role, counter, by_base)
            if candidate is None:
                self.log.append(
                    1,
                    "ORCHESTRATOR",
                    "COUNTER_REJECTED",
                    {"role": role.value, "base_option_id": counter.base_option_id, "error": error},
                )
                continue
            checks = list(self._shared(candidate))
            for other in TURN_ORDER:
                checks.extend(self.agents[other].check(self.public, candidate))
            failures = [c for c in checks if c.hard and not c.passed]
            if failures:
                self.log.append(
                    1,
                    "ORCHESTRATOR",
                    "COUNTER_REJECTED",
                    {
                        "role": role.value,
                        "option_id": candidate.option_id,
                        "failing_checks": [c.model_dump(mode="json") for c in failures],
                    },
                )
                self.log.append(
                    1,
                    "ORCHESTRATOR",
                    "SAFETY_BLOCK",
                    {
                        "role": role.value,
                        "option_id": candidate.option_id,
                        "detail": "unsafe counter rejected",
                    },
                )
                continue
            counters.append(candidate)
            self.log.append(
                1,
                "ORCHESTRATOR",
                "COUNTER_VALIDATED",
                {
                    "role": role.value,
                    "option_id": candidate.option_id,
                    "base_option_id": candidate.base_option_id,
                    "checks": [c.model_dump(mode="json") for c in checks],
                },
            )
        return counters

    def _materialise(
        self,
        role: AgentRole,
        counter: CounterOption,
        by_base: dict[str, CandidateOption],
    ) -> tuple[CandidateOption | None, str | None]:
        base = by_base.get(counter.base_option_id)
        if base is None:
            return None, f"unknown base option {counter.base_option_id}"
        fields = set(CandidateOption.model_fields)
        for key in counter.changes:
            if key in _FORBIDDEN_COUNTER_FIELDS or key not in fields:
                return None, f"illegal counter field {key!r}"
        data = base.model_dump()
        data.update(counter.changes)
        data.update(
            option_id=f"CTR-{role.value}-1",
            origin="COUNTER",
            proposed_by=role,
            base_option_id=base.option_id,
        )
        try:
            return CandidateOption(**data), None
        except Exception as exc:  # noqa: BLE001 - invalid field value
            return None, f"invalid counter value: {exc}"

    # ------------------------------------------------------------------ commit
    def _commit(
        self,
        chosen: CandidateOption,
        *,
        turn: int,
        status: str,
        decided_by: str,
        reason: str,
        pool: list[CandidateOption],
    ) -> Resolution:
        candidates = [chosen] + sorted(
            (o for o in pool if o.option_id != chosen.option_id),
            key=lambda o: (self._total_costs([o]).get(o.option_id, 0.0), o.option_id),
        )
        for index, option in enumerate(candidates):
            try:
                checks = assert_commit_safe(
                    self.public, option, self.agents, self._shared_call, self._next_shared_id
                )
            except UnsafeCommitError as exc:
                self.log.append(
                    turn,
                    "ORCHESTRATOR",
                    "SAFETY_BLOCK",
                    {"option_id": option.option_id, "detail": "commit re-check failed", "error": str(exc)},
                )
                continue

            final_status = status
            final_decided_by = decided_by
            final_reason = reason
            if index > 0:
                final_status = "FALLBACK"
                final_decided_by = "FALLBACK"
                final_reason = f"COMMIT_BLOCKED; {reason}"
                self.log.append(
                    turn,
                    "ORCHESTRATOR",
                    "FALLBACK_INVOKED",
                    {"option_id": option.option_id, "reason": final_reason},
                )

            costs = {
                role.value: float(sum(self.agents[role].cost_eur(self.public, option).values()))
                for role in TURN_ORDER
            }
            resolution = Resolution(
                run_id=self.public.run_id,
                status=final_status,  # type: ignore[arg-type]
                turn=turn,
                decided_by=final_decided_by,  # type: ignore[arg-type]
                option=option,
                reason=final_reason,
                checks=checks,
                costs_eur=costs,
            )
            self.log.append(
                turn,
                "ORCHESTRATOR",
                "COMMIT",
                {
                    "option_id": option.option_id,
                    "status": final_status,
                    "reason": final_reason,
                    "costs_eur": costs,
                },
            )
            return resolution

        return self._escalate(
            turn=turn,
            reason="NO_SAFE_OPTION; recommend diversion to " + self._first_alternate(),
        )

    def _escalate(self, *, turn: int, reason: str) -> Resolution:
        self.log.append(
            turn,
            "ORCHESTRATOR",
            "ESCALATED",
            {"reason": reason, "alternate": self._first_alternate()},
        )
        return Resolution(
            run_id=self.public.run_id,
            status="ESCALATED",
            turn=turn,
            decided_by="HUMAN_ESCALATION",
            option=None,
            reason=reason,
            checks=[],
            costs_eur={},
        )

    # ------------------------------------------------------------------ misc helpers
    def _passes_all_agents(self, option: CandidateOption) -> bool:
        for role in TURN_ORDER:
            checks = self.agents[role].check(self.public, option)
            if any(c.hard and not c.passed for c in checks):
                return False
        return True

    def _passes_all(
        self,
        option: CandidateOption,
        table: dict[tuple[AgentRole, str], list[ConstraintCheck]],
    ) -> bool:
        return all(
            all(c.passed for c in table[(role, option.option_id)] if c.hard) for role in TURN_ORDER
        )

    def _checks_for_all(self, option: CandidateOption) -> list[ConstraintCheck]:
        checks = list(self._shared(option))
        for role in TURN_ORDER:
            checks.extend(self.agents[role].check(self.public, option))
        return checks

    def _total_costs(self, options: list[CandidateOption]) -> dict[str, float]:
        out: dict[str, float] = {}
        for option in options:
            total = 0.0
            for role in TURN_ORDER:
                total += float(sum(self.agents[role].cost_eur(self.public, option).values()))
            out[option.option_id] = total
        return out

    def _summaries(
        self,
        proposals: dict[AgentRole, ProposalMessage],
        counters: list[CandidateOption],
        table: dict[tuple[AgentRole, str], list[ConstraintCheck]],
        options: list[CandidateOption],
    ) -> list[PublicSummary]:
        counter_by_role = {c.proposed_by: c.option_id for c in counters}
        summaries: list[PublicSummary] = []
        for role in TURN_ORDER:
            message = proposals[role]
            code_failed = sorted(
                o.option_id
                for o in options
                if any(c.hard and not c.passed for c in table[(role, o.option_id)])
            )
            summaries.append(
                PublicSummary(
                    sender=role,
                    top_choice=message.ranking[0] if message.ranking else None,
                    vetoed_option_ids=code_failed,
                    objections=message.objections,
                    counter_option_id=counter_by_role.get(role),
                    rationale=message.rationale,
                )
            )
        return summaries

    def _context_manifest(
        self,
        role: AgentRole,
        turn: int,
        inputs: dict[str, Any],
        agent: Any,
    ) -> str:
        return sha256_json(
            {
                "role": role.value,
                "turn": turn,
                "public": self.public.model_dump(mode="json"),
                "inputs": inputs,
                "private_fingerprint": agent.private_fingerprint(),
            }
        )

    def _first_alternate(self) -> str:
        return self.public.alternate_candidates[0] if self.public.alternate_candidates else "nearest suitable airport"


def _dump(models: list[Any]) -> list[dict[str, Any]]:
    return [m.model_dump(mode="json") if hasattr(m, "model_dump") else m for m in models]
