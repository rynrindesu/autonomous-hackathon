"""The deterministic orchestrator (PLAN §5).

Receives only ``PublicEvent`` + agent objects.  It never sees a
``DisruptionEvent`` or any private data.  Hard feasibility always comes from
code checkers, never from an agent's (possibly compromised) veto list.

Protocol (organiser rule: one turn = each of the three agents sends one
structured message; consensus within three turns, otherwise the deterministic
non-AI fallback decides and the log says why):

* Turn 1 PROPOSE      - vetoes (from code), ranking, objections, <=1 counter.
                        Fast path: same #1 for all three and no objection on it.
* Turn 2 BALLOT       - APPROVE/DISAPPROVE the Borda shortlist (<=6); each agent may
                        attach <=1 counter based on an option it disapproved.
* Turn 3 FINAL BALLOT - narrowed shortlist (<=4): 2-of-3 approvals, validated T2
                        counters, best-ranked remainder.  No new options.
* FALLBACK            - cheapest option that passes every check (``solver.py``).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any, get_args

from triad.agents.base import CheckIdGen
from triad.coordinator.aggregate import borda, order
from triad.coordinator.safety import UnsafeCommitError, assert_commit_safe
from triad.fallback.solver import solve, solve_explained
from triad.log.consensus_log import ConsensusLog, sha256_json
from triad.schemas import (
    AgentRole,
    BallotMessage,
    CandidateOption,
    ConstraintCheck,
    CounterOption,
    Objection,
    ObjectionCategory,
    ProposalMessage,
    PublicEvent,
    PublicSummary,
    Resolution,
    Vote,
)

TURN_ORDER = (AgentRole.ATC, AgentRole.PILOT, AgentRole.GROUND)
MAX_TURNS = 3  # organiser rule: consensus within three turns; never exceedable
T2_SHORTLIST_MAX = 6
T3_SHORTLIST_MAX = 4
_FORBIDDEN_COUNTER_FIELDS = {"option_id", "origin", "proposed_by", "base_option_id"}
_DIVERT_ID = "OPT-DIV"
_OBJECTION_CATEGORIES = set(get_args(ObjectionCategory))
_SAFETY_BLOCK_REASON = "SAFETY_BLOCK"
_INF = float("inf")


class TurnLimitExceeded(RuntimeError):
    """Raised if anything tries to start a turn beyond the hard cap."""


def _limits_info() -> Any:
    """Workbook limits for the SETUP flags (module may not exist yet)."""
    try:
        from triad.data.limits import limits_info  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        return limits_info()
    except Exception as exc:  # noqa: BLE001 - logging must never break a run
        return {"error": f"{type(exc).__name__}: {exc}"}


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
        max_turns: int = MAX_TURNS,
        failover_factory: Callable[[Any], Any] | None = None,
        run_flags: Mapping[str, Any] | None = None,
    ) -> None:
        if isinstance(max_turns, bool) or not isinstance(max_turns, int) or not 1 <= max_turns <= MAX_TURNS:
            raise ValueError(
                f"max_turns must be an int between 1 and {MAX_TURNS} "
                f"(organiser rule: consensus within {MAX_TURNS} turns), got {max_turns!r}"
            )
        self.max_turns = max_turns
        self.public = public
        self.agents: dict[AgentRole, Any] = dict(agents)
        self.log = log
        self._option_generator = option_generator
        self._shared_checker = shared_checker
        self._failover_factory = failover_factory
        self._next_shared_id = CheckIdGen("SHR")
        self._all_options: list[CandidateOption] = []
        self._run_flags: dict[str, Any] = dict(run_flags or {})
        # audit state for the fallback "why" payload
        self._turns_started = 0
        self._turn_records: list[dict[str, Any]] = []
        self._shared_failed: dict[str, list[str]] = {}
        self._t1_table: dict[tuple[AgentRole, str], list[ConstraintCheck]] = {}
        self._counter_status: dict[tuple[int, AgentRole], dict[str, Any]] = {}

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
        options = self._setup(ai_off=ai_off)
        if ai_off:
            return self._run_ai_off(options)
        return self._run_negotiation(options)

    # ------------------------------------------------------------------ setup (turn 0)
    def _flags(self, ai_off: bool) -> dict[str, Any]:
        impls = {role.value: str(getattr(self.agents[role], "impl", "unknown")) for role in TURN_ORDER}
        models = {
            role.value: str(
                getattr(getattr(self.agents[role], "client", None), "model", None) or impls[role.value]
            )
            for role in TURN_ORDER
        }
        derived_impl = "llm" if any(v.startswith("llm") for v in impls.values()) else (
            impls[AgentRole.ATC.value] if len(set(impls.values())) == 1 else "mixed"
        )
        flags: dict[str, Any] = {
            "impl": derived_impl,
            "red_team": False,
            "ai_off": ai_off,
            "defect_id": None,
            "seed": None,
        }
        flags.update(self._run_flags)
        flags["ai_off"] = ai_off
        flags["models"] = models
        flags["agent_impl"] = impls
        flags["max_turns"] = self.max_turns
        flags["limits"] = _limits_info()
        return flags

    def _setup(self, ai_off: bool = False) -> list[CandidateOption]:
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
                "public": public.model_dump(mode="json"),
                "flags": self._flags(ai_off),
            },
        )
        raw = list(self._generate(public))
        self._all_options = list(raw)
        shared: dict[str, list[ConstraintCheck]] = {}
        for option in raw:
            checks = list(self._shared(option))
            shared[option.option_id] = checks
            failed = _failing(checks)
            if failed:
                self._shared_failed[option.option_id] = _constraint_ids(failed)
            self.log.append(
                0,
                "ORCHESTRATOR",
                "SHARED_CHECKS",
                {
                    "option_id": option.option_id,
                    "passed": not failed,
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
        feasible: list[CandidateOption] = []
        for option in options:
            per_agent: dict[str, Any] = {}
            dumped: list[dict[str, Any]] = []
            for role in TURN_ORDER:
                checks = list(self.agents[role].check(self.public, option))
                failed = _failing(checks)
                per_agent[role.value] = {
                    "passed": not failed,
                    "failed_constraint_ids": _constraint_ids(failed),
                    "failed_check_ids": [c.check_id for c in failed],
                }
                dumped.extend(c.model_dump(mode="json") for c in checks)
            passed = all(item["passed"] for item in per_agent.values())
            self.log.append(
                0,
                "ORCHESTRATOR",
                "AGENT_CHECKS",
                {
                    "option_id": option.option_id,
                    "passed": passed,
                    "agents": per_agent,
                    "checks": dumped,
                },
            )
            if passed:
                feasible.append(option)
        if not feasible:
            return self._escalate(
                turn=0,
                reason="NO_SAFE_OPTION; recommend diversion to " + self._first_alternate(),
            )
        chosen, costs, tie_break = solve_explained(self.public, feasible, self.agents)
        assert chosen is not None
        self.log.append(
            0,
            "FALLBACK",
            "FALLBACK_INVOKED",
            {
                "reason": "AI_OFF",
                "reason_code": "AI_OFF",
                "turns_used": 0,
                "pool": [o.option_id for o in feasible],
                "option_id": chosen.option_id,
                "chosen": chosen.option_id,
                "costs": costs,
                "tie_break": tie_break,
                "summary": (
                    "AI is switched off, so no agent negotiation took place. The deterministic fallback "
                    f"picked {chosen.option_id} because it is the cheapest option that passes every check "
                    f"({_eur(sum(costs[chosen.option_id].values()))})."
                ),
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

        # ================================================================ Turn 1: PROPOSE
        self._turn_start(1, [o.option_id for o in options], "T1 proposals")
        proposals: dict[AgentRole, ProposalMessage] = {}
        turn1_results = self._collect_turn1(options)
        for role in TURN_ORDER:
            agent, _message, _context, perception = turn1_results[role]
            self._log_perception(role, agent, perception)
        for role in TURN_ORDER:
            agent, message, context, _perception = turn1_results[role]
            proposals[role] = message
            payload = message.model_dump(mode="json")
            payload["context"] = {role.value: context["breakdown"]}
            self.log.append(
                1,
                role.value,
                "PROPOSAL",
                payload,
                context_manifest={role.value: context["combined"]},
                usage=self._usage_payload(agent, "turn1"),
            )

        # ---- code truth, never the veto list
        table: dict[tuple[AgentRole, str], list[ConstraintCheck]] = {}
        for role in TURN_ORDER:
            agent = self.agents[role]
            for option in options:
                table[(role, option.option_id)] = list(agent.check(self.public, option))
        self._t1_table = table

        for role in TURN_ORDER:
            message = proposals[role]
            code_failed = {
                o.option_id
                for o in options
                if any(c.hard and not c.passed for c in table[(role, o.option_id)])
            }
            declared = {v.option_id: v for v in message.vetoes}
            for oid in sorted(set(declared) - code_failed):
                self._safety_block(
                    1,
                    role=role.value,
                    option_id=oid,
                    detail="fabricated veto",
                    failing=[],
                    claimed_constraint_id=declared[oid].constraint_id,
                )
            for oid in sorted(code_failed - set(declared)):
                self._safety_block(
                    1,
                    role=role.value,
                    option_id=oid,
                    detail="omitted veto",
                    failing=_failing(table[(role, oid)]),
                )

        feasible = [o for o in options if self._passes_all(o, table)]

        # ---- counters: materialise + code-only validation
        counters = self._validate_counters(proposals, options)
        self._turn_records.append(self._proposal_record(proposals, table, options))

        if not feasible and not counters:
            return self._escalate(
                turn=1,
                reason="NO_SAFE_OPTION; recommend diversion to " + self._first_alternate(),
            )

        # ---- fast path
        tops = {
            role: (proposals[role].ranking[0] if proposals[role].ranking else None) for role in TURN_ORDER
        }
        top_values = set(tops.values())
        if len(top_values) == 1 and None not in top_values:
            top_id = tops[TURN_ORDER[0]]
            top = next((o for o in feasible if o.option_id == top_id), None)
            objectors = [
                f"{role.value} ({obj.category})"
                for role in TURN_ORDER
                for obj in proposals[role].objections
                if obj.option_id == top_id
            ]
            if top is not None and not objectors:
                return self._commit(
                    top,
                    turn=1,
                    status="CONSENSUS",
                    decided_by="AGENTS",
                    reason="UNANIMOUS_FIRST_CHOICE",
                    pool=feasible + counters,
                )
            miss = f"all three ranked {top_id} first but " + (
                "it fails a hard check" if top is None else f"it drew objection(s) from {_join(objectors)}"
            )
        else:
            miss = "first choices differ (" + ", ".join(
                f"{role.value} {tops[role] or '-'}" for role in TURN_ORDER
            ) + ")"

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
        shortlist_ids = shortlist_ids[:T2_SHORTLIST_MAX]
        by_id: dict[str, CandidateOption] = {o.option_id: o for o in list(feasible) + counters}
        shortlist = [by_id[oid] for oid in shortlist_ids if oid in by_id]
        shortlist_ids = [o.option_id for o in shortlist]

        # Shadow of the fallback: tell agents what will happen if they don't agree.
        pool = feasible + counters
        fallback_projection, _fallback_costs = solve(self.public, pool, self.agents)
        fallback_option_id = fallback_projection.option_id if fallback_projection is not None else None

        self.log.append(
            1,
            "ORCHESTRATOR",
            "SHORTLIST",
            {
                "for_turn": 2,
                "option_ids": shortlist_ids,
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
        if self.max_turns < 2:
            return self._fallback(turn=1, pool=pool, reason_code="NO_T1_CONSENSUS", blocking=[])

        summaries = self._summaries(proposals, counters, table, options)

        # ================================================================ Turn 2: BALLOT
        self._turn_start(
            2, shortlist_ids, f"no T1 fast path: {miss}", fallback_option_id=fallback_option_id
        )
        ballots = self._run_ballots(2, shortlist, summaries, fallback_projection)
        t2_counters = self._validate_ballot_counters(ballots, shortlist)
        for counter in t2_counters:
            by_id[counter.option_id] = counter
        pool = feasible + counters + t2_counters

        checks2, safe2 = self._safety_of(shortlist)
        approvals, _discarded = self._honour_approvals(
            2, ballots, shortlist_ids, checks2, safe2, table, counters + t2_counters
        )
        record2 = self._ballot_record(2, shortlist_ids, ballots, approvals)
        self._turn_records.append(record2)

        approved_by_all = [oid for oid in shortlist_ids if all(oid in approvals[r] for r in TURN_ORDER)]
        if approved_by_all:
            chosen = self._best(approved_by_all, ballots, by_id)
            if chosen is not None:
                return self._commit(
                    chosen,
                    turn=2,
                    status="CONSENSUS",
                    decided_by="AGENTS",
                    reason="UNANIMOUS_APPROVAL",
                    pool=pool,
                )

        blocking2 = _blocking(shortlist_ids, approvals, record2)
        if self.max_turns < 3:
            return self._fallback(turn=2, pool=pool, reason_code="NO_UNANIMOUS_APPROVAL", blocking=blocking2)

        # ================================================================ Turn 3: FINAL BALLOT
        t3_ids, approval_counts, scores2 = self._t3_shortlist(
            shortlist_ids, safe2, approvals, ballots, t2_counters, by_id
        )
        t3 = [by_id[oid] for oid in t3_ids]
        fallback3, _costs3 = solve(self.public, pool, self.agents)
        fallback3_id = fallback3.option_id if fallback3 is not None else None
        self.log.append(
            2,
            "ORCHESTRATOR",
            "SHORTLIST",
            {
                "for_turn": 3,
                "option_ids": t3_ids,
                "approvals": approval_counts,
                "scores": scores2,
                "t2_counter_ids": [c.option_id for c in t2_counters],
                "fallback_option_id": fallback3_id,
            },
        )
        if not t3:
            return self._fallback(turn=2, pool=pool, reason_code="NO_UNANIMOUS_APPROVAL", blocking=blocking2)

        summaries3 = self._ballot_summaries(ballots, approvals, checks2, shortlist_ids)
        self._turn_start(
            3,
            t3_ids,
            "no unanimous T2 approval: " + _blocking_text(blocking2),
            fallback_option_id=fallback3_id,
        )
        ballots3 = self._run_ballots(3, t3, summaries3, fallback3)
        checks3, safe3 = self._safety_of(t3)
        approvals3, _discarded3 = self._honour_approvals(
            3, ballots3, t3_ids, checks3, safe3, table, counters + t2_counters
        )
        record3 = self._ballot_record(3, t3_ids, ballots3, approvals3)
        self._turn_records.append(record3)

        approved3 = [oid for oid in t3_ids if all(oid in approvals3[r] for r in TURN_ORDER)]
        if approved3:
            chosen = self._best(approved3, ballots3, by_id)
            if chosen is not None:
                return self._commit(
                    chosen,
                    turn=3,
                    status="CONSENSUS",
                    decided_by="AGENTS",
                    reason="UNANIMOUS_APPROVAL",
                    pool=pool,
                )

        return self._fallback(
            turn=3,
            pool=pool,
            reason_code="NO_UNANIMOUS_APPROVAL",
            blocking=_blocking(t3_ids, approvals3, record3),
        )

    # ------------------------------------------------------------------ turn bookkeeping
    def _turn_start(self, turn: int, shortlist_ids: list[str], reason: str, **extra: Any) -> None:
        if turn > MAX_TURNS or turn > self.max_turns:
            raise TurnLimitExceeded(f"turn {turn} exceeds the {self.max_turns}-turn limit")
        if turn != self._turns_started + 1:
            raise RuntimeError(f"turn {turn} started out of order (last started: {self._turns_started})")
        self._turns_started = turn
        payload: dict[str, Any] = {
            "turn": turn,
            "max_turns": self.max_turns,
            "kind": {1: "PROPOSE", 2: "BALLOT", 3: "FINAL_BALLOT"}[turn],
            "shortlist": list(shortlist_ids),
            "reason": reason,
        }
        payload.update(extra)
        self.log.append(turn, "ORCHESTRATOR", "TURN_START", payload)

    def _proposal_record(
        self,
        proposals: dict[AgentRole, ProposalMessage],
        table: dict[tuple[AgentRole, str], list[ConstraintCheck]],
        options: list[CandidateOption],
    ) -> dict[str, Any]:
        per_agent: dict[str, Any] = {}
        for role in TURN_ORDER:
            message = proposals[role]
            vetoed = [
                {"option_id": o.option_id, "reason": ", ".join(_constraint_ids(_failing(table[(role, o.option_id)])))}
                for o in options
                if _failing(table[(role, o.option_id)])
            ]
            per_agent[role.value] = {
                "top_choice": message.ranking[0] if message.ranking else None,
                "ranking": list(message.ranking),
                "vetoed": vetoed,
                "objections": [
                    {"option_id": obj.option_id, "reason": obj.category} for obj in message.objections
                ],
                "counter": self._counter_status.get((1, role)),
            }
        return {
            "turn": 1,
            "kind": "PROPOSE",
            "options": [o.option_id for o in options],
            "per_agent": per_agent,
        }

    def _ballot_record(
        self,
        turn: int,
        shortlist_ids: list[str],
        ballots: dict[AgentRole, BallotMessage],
        approvals: dict[AgentRole, set[str]],
    ) -> dict[str, Any]:
        per_agent: dict[str, Any] = {}
        for role in TURN_ORDER:
            votes = {v.option_id: v for v in ballots[role].votes}
            disapproved: list[dict[str, str]] = []
            for oid in shortlist_ids:
                if oid in approvals[role]:
                    continue
                vote = votes.get(oid)
                if vote is None:
                    reason = "NO_VOTE"
                elif vote.vote == "APPROVE":
                    reason = _SAFETY_BLOCK_REASON  # approval discarded: the option fails a hard check
                else:
                    reason = (vote.reason or "").strip() or "NO_REASON"
                disapproved.append({"option_id": oid, "reason": reason})
            entry: dict[str, Any] = {
                "approved": [oid for oid in shortlist_ids if oid in approvals[role]],
                "disapproved": disapproved,
            }
            if turn == 2:
                entry["counter"] = self._counter_status.get((2, role))
            per_agent[role.value] = entry
        return {
            "turn": turn,
            "kind": "BALLOT" if turn == 2 else "FINAL_BALLOT",
            "shortlist": list(shortlist_ids),
            "per_agent": per_agent,
        }

    def _t3_shortlist(
        self,
        shortlist_ids: list[str],
        safe_ids: set[str],
        approvals: dict[AgentRole, set[str]],
        ballots: dict[AgentRole, BallotMessage],
        t2_counters: list[CandidateOption],
        by_id: dict[str, CandidateOption],
    ) -> tuple[list[str], dict[str, int], dict[str, float]]:
        """Narrow to <=4: 2-of-3 approvals, then validated T2 counters, then the best remainder."""
        counts = {oid: sum(1 for role in TURN_ORDER if oid in approvals[role]) for oid in shortlist_ids}
        scores = borda({role: ballots[role].ranking for role in TURN_ORDER}, shortlist_ids)
        cost = self._total_costs([by_id[oid] for oid in shortlist_ids if oid in by_id] + t2_counters)

        def key(oid: str) -> tuple[int, float, float, str]:
            return (-counts.get(oid, 0), -scores.get(oid, 0.0), cost.get(oid, _INF), oid)

        eligible = [oid for oid in shortlist_ids if oid in safe_ids and oid in by_id]
        majority = sorted((oid for oid in eligible if counts[oid] >= 2), key=key)
        counter_ids = sorted(
            (c.option_id for c in t2_counters),
            key=lambda oid: (-scores.get(by_id[oid].base_option_id or "", 0.0), cost.get(oid, _INF), oid),
        )
        rest = sorted((oid for oid in eligible if oid not in majority), key=key)
        ordered: list[str] = []
        for oid in majority + counter_ids + rest:
            if oid not in ordered:
                ordered.append(oid)
        return ordered[:T3_SHORTLIST_MAX], counts, scores

    def _best(
        self,
        approved: list[str],
        ballots: dict[AgentRole, BallotMessage],
        by_id: dict[str, CandidateOption],
    ) -> CandidateOption | None:
        """Best unanimously approved option: Borda on this turn's rankings -> first votes -> cost -> id."""
        rankings = {role: ballots[role].ranking for role in TURN_ORDER}
        scores = borda(rankings, approved)
        first = {oid: sum(1 for r in rankings.values() if r and r[0] == oid) for oid in approved}
        cost = self._total_costs([by_id[oid] for oid in approved if oid in by_id])
        return by_id.get(order(scores, first, cost)[0])

    # ------------------------------------------------------------------ fallback (after the last turn)
    def _fallback(
        self,
        *,
        turn: int,
        pool: list[CandidateOption],
        reason_code: str,
        blocking: list[dict[str, Any]],
    ) -> Resolution:
        chosen, costs, tie_break = solve_explained(self.public, pool, self.agents)
        if chosen is None:
            return self._escalate(
                turn=turn,
                reason="NO_SAFE_OPTION; recommend diversion to " + self._first_alternate(),
            )
        totals = {oid: float(sum(per.values())) for oid, per in costs.items()}
        summary = _fallback_summary(turn, blocking, chosen.option_id, totals)
        self.log.append(
            turn,
            "FALLBACK",
            "FALLBACK_INVOKED",
            {
                "reason": reason_code,
                "reason_code": reason_code,
                "turns_used": turn,
                "max_turns": self.max_turns,
                "per_turn": list(self._turn_records),
                "blocking": blocking,
                "vetoed_by_code": self._vetoed_by_code(),
                "pool": [o.option_id for o in pool],
                "chosen": chosen.option_id,
                "option_id": chosen.option_id,
                "costs": costs,
                "totals": totals,
                "tie_break": tie_break,
                "summary": summary,
            },
        )
        return self._commit(
            chosen,
            turn=turn,
            status="FALLBACK",
            decided_by="FALLBACK",
            reason=reason_code,
            pool=pool,
        )

    def _vetoed_by_code(self) -> dict[str, list[dict[str, str]]]:
        out: dict[str, list[dict[str, str]]] = {}
        for oid, cids in self._shared_failed.items():
            out.setdefault(oid, []).extend({"role": "SHARED", "constraint_id": cid} for cid in cids)
        for (role, oid), checks in self._t1_table.items():
            for cid in _constraint_ids(_failing(checks)):
                out.setdefault(oid, []).append({"role": role.value, "constraint_id": cid})
        return {oid: out[oid] for oid in sorted(out)}

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

    def _usage_payload(self, agent: Any, label: str) -> dict[str, Any] | None:
        getter = getattr(agent, "usage_for", None)
        usage = getter(label) if callable(getter) else getattr(agent, "last_usage", None)
        if not usage:
            return None
        return {agent.role.value: dict(usage)}

    def _log_perception(self, role: AgentRole, agent: Any, perception: dict[str, Any]) -> None:
        facts = perception.get("facts") or []
        self.log.append(
            1,
            role.value,
            "PERCEPTION",
            {
                "role": role.value,
                "impl": str(getattr(agent, "impl", "unknown")),
                "failover": bool(perception.get("failover")),
                "n_conservative_defaults": sum(1 for f in facts if f.get("conservative_default")),
                "facts": facts,
            },
            usage=self._usage_payload(agent, "perceive"),
        )
        for finding in perception.get("injections") or []:
            self.log.append(
                1,
                role.value,
                "INJECTION_DETECTED",
                {
                    "role": role.value,
                    "agent": role.value,
                    "kind": finding.get("kind"),
                    "note": finding.get("note"),
                    "phrases": list(finding.get("phrases") or []),
                    "handling": "treated as data; hard constraints are checked in code",
                },
            )

    def _perception_summary(
        self, original: Any, agent: Any, failover: bool
    ) -> dict[str, Any]:
        try:
            facts = list(agent.perceive(self.public) or [])
        except Exception:  # noqa: BLE001 - logging must never break a run
            facts = []
        summary = [
            {
                "key": fact.key,
                "value": fact.value,
                "source": fact.source,
                "confidence": fact.confidence,
                "citation": fact.citation.chunk_id if fact.citation is not None else None,
                "conservative_default": fact.conservative_default,
            }
            for fact in facts
        ]
        injections = list(getattr(original, "injection_findings", None) or [])
        return {"facts": summary, "injections": injections, "failover": failover}

    def _collect_turn1(
        self, options: list[CandidateOption]
    ) -> dict[AgentRole, tuple[Any, ProposalMessage, dict[str, Any], dict[str, Any]]]:
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
        results: dict[AgentRole, tuple[Any, ProposalMessage, dict[str, Any], dict[str, Any]]] = {}
        for role in TURN_ORDER:
            item = raw[role]
            if isinstance(item, Exception):
                agent, message, exc = self.agents[role], None, item
            else:
                agent, message, exc = item
            original = agent
            failed_over = exc is not None or message is None
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
            context = self._context_manifest(
                role, 1, {"kind": "turn1", "options": _dump(options)}, agent
            )
            perception = self._perception_summary(original, agent, failed_over)
            results[role] = (agent, message, context, perception)
        return results

    def _call_ballot(
        self,
        agent: Any,
        turn: int,
        shortlist: list[CandidateOption],
        summaries: list[PublicSummary],
        fallback_option: CandidateOption | None,
    ) -> BallotMessage:
        if turn == 2:
            return agent.turn2(self.public, shortlist, summaries, fallback_option=fallback_option)
        final = getattr(agent, "turn3", None)
        if callable(final):
            return final(self.public, shortlist, summaries, fallback_option=fallback_option)
        message = agent.turn2(self.public, shortlist, summaries, fallback_option=fallback_option)
        return message.model_copy(update={"turn": 3, "counter_option": None})

    def _collect_ballots(
        self,
        turn: int,
        shortlist: list[CandidateOption],
        summaries: list[PublicSummary],
        fallback_option: CandidateOption | None = None,
    ) -> dict[AgentRole, tuple[Any, BallotMessage, dict[str, Any]]]:
        shortlist_ids = [o.option_id for o in shortlist]
        known = set(shortlist_ids) | {o.option_id for o in self._all_options}

        def others(role: AgentRole) -> list[PublicSummary]:
            return [s for s in summaries if s.sender != role]

        def attempt(role: AgentRole) -> tuple[Any, BallotMessage | None, Exception | None]:
            agent = self.agents[role]
            try:
                ballot = self._call_ballot(agent, turn, shortlist, others(role), fallback_option)
                self._validate_ballot(role, ballot, shortlist_ids, known, turn)
                return agent, ballot, None
            except Exception as exc:  # noqa: BLE001
                return agent, None, exc

        raw = self._parallel(attempt)
        results: dict[AgentRole, tuple[Any, BallotMessage, dict[str, Any]]] = {}
        for role in TURN_ORDER:
            item = raw[role]
            if isinstance(item, Exception):
                agent, ballot, exc = self.agents[role], None, item
            else:
                agent, ballot, exc = item
            if exc is not None or ballot is None:
                self.log.append(
                    turn,
                    "ORCHESTRATOR",
                    "AGENT_FAILOVER",
                    {
                        "role": role.value,
                        "turn": turn,
                        "error": f"{type(exc).__name__}: {exc}" if exc else "no ballot",
                    },
                )
                agent = self._failover(agent)
                self.agents[role] = agent
                ballot = self._call_ballot(agent, turn, shortlist, others(role), fallback_option)
                self._validate_ballot(role, ballot, shortlist_ids, known, turn)
            context = self._context_manifest(
                role,
                turn,
                {
                    "kind": f"turn{turn}",
                    "shortlist": _dump(shortlist),
                    "summaries": _dump(others(role)),
                    "fallback_option": (
                        fallback_option.model_dump(mode="json") if fallback_option is not None else None
                    ),
                },
                agent,
            )
            results[role] = (agent, ballot, context)
        return results

    def _collect_turn2(
        self,
        shortlist: list[CandidateOption],
        summaries: list[PublicSummary],
        fallback_option: CandidateOption | None = None,
    ) -> dict[AgentRole, tuple[Any, BallotMessage, dict[str, Any]]]:
        """Backwards-compatible alias for the Turn 2 collection."""
        return self._collect_ballots(2, shortlist, summaries, fallback_option)

    def _run_ballots(
        self,
        turn: int,
        shortlist: list[CandidateOption],
        summaries: list[PublicSummary],
        fallback_option: CandidateOption | None,
    ) -> dict[AgentRole, BallotMessage]:
        """Collect + log one ballot per agent; Turn 3 counters are discarded and logged."""
        ballots: dict[AgentRole, BallotMessage] = {}
        results = self._collect_ballots(turn, shortlist, summaries, fallback_option)
        for role in TURN_ORDER:
            agent, ballot, context = results[role]
            payload = ballot.model_dump(mode="json")
            payload["context"] = {role.value: context["breakdown"]}
            self.log.append(
                turn,
                role.value,
                "BALLOT",
                payload,
                context_manifest={role.value: context["combined"]},
                usage=self._usage_payload(agent, f"turn{turn}"),
            )
            if turn >= 3 and ballot.counter_option is not None:
                self.log.append(
                    turn,
                    "ORCHESTRATOR",
                    "COUNTER_REJECTED",
                    {
                        "role": role.value,
                        "turn": turn,
                        "base_option_id": ballot.counter_option.base_option_id,
                        "changes": ballot.counter_option.changes,
                        "error": "counter-options are not allowed in Turn 3 (final ballot); discarded",
                    },
                )
                ballot = ballot.model_copy(update={"counter_option": None})
            ballots[role] = ballot
        return ballots

    # ------------------------------------------------------------------ ballot guards
    def _safety_of(
        self, shortlist: list[CandidateOption]
    ) -> tuple[dict[str, list[ConstraintCheck]], set[str]]:
        checks = {option.option_id: self._checks_for_all(option) for option in shortlist}
        safe = {oid for oid, items in checks.items() if not _failing(items)}
        return checks, safe

    def _honour_approvals(
        self,
        turn: int,
        ballots: dict[AgentRole, BallotMessage],
        shortlist_ids: list[str],
        shortlist_checks: dict[str, list[ConstraintCheck]],
        safe_ids: set[str],
        table: dict[tuple[AgentRole, str], list[ConstraintCheck]],
        counters: list[CandidateOption],
    ) -> tuple[dict[AgentRole, set[str]], dict[AgentRole, list[str]]]:
        """Honour only shortlisted, code-safe approvals; everything else is a SAFETY_BLOCK."""
        approvals: dict[AgentRole, set[str]] = {}
        discarded: dict[AgentRole, list[str]] = {}
        for role in TURN_ORDER:
            allowed: set[str] = set()
            dropped: list[str] = []
            for vote in ballots[role].votes:
                if vote.option_id not in shortlist_ids:
                    if vote.vote == "APPROVE":
                        dropped.append(vote.option_id)
                        self._safety_block(
                            turn,
                            role=role.value,
                            option_id=vote.option_id,
                            detail="approve outside shortlist",
                            failing=self._known_failures(vote.option_id, table, counters),
                        )
                    continue
                if vote.vote == "APPROVE":
                    if vote.option_id not in safe_ids:
                        dropped.append(vote.option_id)
                        self._safety_block(
                            turn,
                            role=role.value,
                            option_id=vote.option_id,
                            detail="approve of unsafe option",
                            failing=_failing(shortlist_checks[vote.option_id]),
                        )
                        continue
                    allowed.add(vote.option_id)
            approvals[role] = allowed
            discarded[role] = dropped
        return approvals, discarded

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
        turn: int = 2,
    ) -> None:
        if ballot.sender != role:
            raise ValueError(f"wrong sender {ballot.sender} for {role}")
        if ballot.run_id != self.public.run_id:
            raise ValueError(f"wrong run_id {ballot.run_id}")
        if ballot.turn != turn:
            raise ValueError(f"ballot is marked turn {ballot.turn}, expected turn {turn}")
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
        """Turn 1 counters: materialise, then shared checks + all three checkers (code only)."""
        by_base = {o.option_id: o for o in options}
        counters: list[CandidateOption] = []
        for role in TURN_ORDER:
            counter = proposals[role].counter_option
            if counter is None:
                continue
            candidate = self._validate_counter(1, role, counter, by_base)
            if candidate is not None:
                counters.append(candidate)
        return counters

    def _validate_ballot_counters(
        self,
        ballots: dict[AgentRole, BallotMessage],
        shortlist: list[CandidateOption],
    ) -> list[CandidateOption]:
        """Turn 2 counters: must revise an option the sender DISAPPROVED; same code checks as T1."""
        by_base = {o.option_id: o for o in shortlist}
        counters: list[CandidateOption] = []
        for role in TURN_ORDER:
            counter = ballots[role].counter_option
            if counter is None:
                continue
            vote = next((v for v in ballots[role].votes if v.option_id == counter.base_option_id), None)
            if vote is None or vote.vote != "DISAPPROVE":
                error = (
                    f"a Turn 2 counter must be based on a shortlisted option the sender disapproved "
                    f"({counter.base_option_id} was {'not voted on' if vote is None else 'approved'})"
                )
                self._counter_status[(2, role)] = {
                    "base_option_id": counter.base_option_id,
                    "option_id": None,
                    "validated": False,
                    "error": error,
                }
                self.log.append(
                    2,
                    "ORCHESTRATOR",
                    "COUNTER_REJECTED",
                    {
                        "role": role.value,
                        "turn": 2,
                        "base_option_id": counter.base_option_id,
                        "changes": counter.changes,
                        "error": error,
                    },
                )
                continue
            candidate = self._validate_counter(2, role, counter, by_base)
            if candidate is not None:
                counters.append(candidate)
        return counters

    def _validate_counter(
        self,
        turn: int,
        role: AgentRole,
        counter: CounterOption,
        by_base: dict[str, CandidateOption],
    ) -> CandidateOption | None:
        candidate, error = self._materialise(role, counter, by_base, suffix=turn)
        if candidate is None:
            self._counter_status[(turn, role)] = {
                "base_option_id": counter.base_option_id,
                "option_id": None,
                "validated": False,
                "error": error,
            }
            self.log.append(
                turn,
                "ORCHESTRATOR",
                "COUNTER_REJECTED",
                {
                    "role": role.value,
                    "turn": turn,
                    "base_option_id": counter.base_option_id,
                    "changes": counter.changes,
                    "error": error,
                },
            )
            return None
        checks = list(self._shared(candidate))
        for other in TURN_ORDER:
            checks.extend(self.agents[other].check(self.public, candidate))
        failures = _failing(checks)
        if failures:
            self._counter_status[(turn, role)] = {
                "base_option_id": candidate.base_option_id,
                "option_id": candidate.option_id,
                "validated": False,
                "error": "fails " + ", ".join(f"{c.owner}:{c.constraint_id}" for c in failures),
            }
            self.log.append(
                turn,
                "ORCHESTRATOR",
                "COUNTER_REJECTED",
                {
                    "role": role.value,
                    "turn": turn,
                    "option_id": candidate.option_id,
                    "base_option_id": candidate.base_option_id,
                    "changes": counter.changes,
                    "option": candidate.model_dump(mode="json"),
                    "failing_checks": [c.model_dump(mode="json") for c in failures],
                },
            )
            self._safety_block(
                turn,
                role=role.value,
                option_id=candidate.option_id,
                detail="unsafe counter rejected",
                failing=failures,
            )
            return None
        self._counter_status[(turn, role)] = {
            "base_option_id": candidate.base_option_id,
            "option_id": candidate.option_id,
            "validated": True,
        }
        self.log.append(
            turn,
            "ORCHESTRATOR",
            "COUNTER_VALIDATED",
            {
                "role": role.value,
                "turn": turn,
                "option_id": candidate.option_id,
                "base_option_id": candidate.base_option_id,
                "changes": counter.changes,
                "option": candidate.model_dump(mode="json"),
                "checks": [c.model_dump(mode="json") for c in checks],
            },
        )
        return candidate

    def _materialise(
        self,
        role: AgentRole,
        counter: CounterOption,
        by_base: dict[str, CandidateOption],
        suffix: int = 1,
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
            option_id=f"CTR-{role.value}-{suffix}",
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
        blocked: list[str] = []
        for index, option in enumerate(candidates):
            try:
                checks = assert_commit_safe(
                    self.public, option, self.agents, self._shared_call, self._next_shared_id
                )
            except UnsafeCommitError as exc:
                self._commit_gate(turn, option, exc.checks, exc.failed)
                self._safety_block(
                    turn,
                    role=None,
                    option_id=option.option_id,
                    detail="commit re-check failed",
                    failing=exc.failed,
                    error=str(exc),
                )
                blocked.append(f"{option.option_id} ({', '.join(_constraint_ids(exc.failed))})")
                continue
            self._commit_gate(turn, option, checks, [])

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
                    {
                        "option_id": option.option_id,
                        "chosen": option.option_id,
                        "reason": final_reason,
                        "reason_code": "COMMIT_BLOCKED",
                        "turns_used": turn,
                        "summary": (
                            f"The selected option failed the final commit re-check: {'; '.join(blocked)}. "
                            f"The deterministic fallback committed {option.option_id}, the cheapest "
                            "remaining option that passes every check."
                        ),
                    },
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
                    "turn": turn,
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

    def _commit_gate(
        self,
        turn: int,
        option: CandidateOption,
        checks: list[ConstraintCheck],
        failed: list[ConstraintCheck],
    ) -> None:
        self.log.append(
            turn,
            "ORCHESTRATOR",
            "COMMIT_GATE",
            {
                "option_id": option.option_id,
                "passed": not failed,
                "n_checks": len(checks),
                "failed": [
                    {
                        "check_id": c.check_id,
                        "constraint_id": c.constraint_id,
                        "owner": str(c.owner),
                        "detail": c.detail,
                    }
                    for c in failed
                ],
            },
        )

    def _safety_block(
        self,
        turn: int,
        *,
        role: str | None,
        option_id: str,
        detail: str,
        failing: list[ConstraintCheck],
        **extra: Any,
    ) -> None:
        payload: dict[str, Any] = {}
        if role is not None:
            payload["role"] = role
        payload.update(
            {
                "agent": role,
                "option_id": option_id,
                "detail": detail,
                "constraint_ids": _constraint_ids(failing),
                "check_ids": [c.check_id for c in failing],
            }
        )
        payload.update(extra)
        self.log.append(turn, "ORCHESTRATOR", "SAFETY_BLOCK", payload)

    def _known_failures(
        self,
        option_id: str,
        table: dict[tuple[AgentRole, str], list[ConstraintCheck]],
        counters: list[CandidateOption],
    ) -> list[ConstraintCheck]:
        """Failing hard checks of an option outside the shortlist (if it is known)."""
        if all((role, option_id) in table for role in TURN_ORDER):
            return [c for role in TURN_ORDER for c in _failing(table[(role, option_id)])]
        known = {o.option_id: o for o in list(self._all_options) + list(counters)}
        option = known.get(option_id)
        if option is None:
            return []
        return _failing(self._checks_for_all(option))

    # ------------------------------------------------------------------ misc helpers
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
        """Public view of each agent's Turn 1 message (input to Turn 2)."""
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
                    turn=1,
                    top_choice=message.ranking[0] if message.ranking else None,
                    vetoed_option_ids=code_failed,
                    objections=message.objections,
                    counter_option_id=counter_by_role.get(role),
                    rationale=message.rationale,
                )
            )
        return summaries

    def _ballot_summaries(
        self,
        ballots: dict[AgentRole, BallotMessage],
        approvals: dict[AgentRole, set[str]],
        shortlist_checks: dict[str, list[ConstraintCheck]],
        shortlist_ids: list[str],
    ) -> list[PublicSummary]:
        """Public view of each agent's Turn 2 ballot (input to Turn 3): effective votes + reasons."""
        summaries: list[PublicSummary] = []
        for role in TURN_ORDER:
            ballot = ballots[role]
            votes: list[Vote] = []
            for vote in ballot.votes:
                if vote.option_id not in shortlist_ids:
                    continue
                if vote.vote == "APPROVE" and vote.option_id not in approvals[role]:
                    votes.append(Vote(option_id=vote.option_id, vote="DISAPPROVE", reason=_SAFETY_BLOCK_REASON))
                else:
                    votes.append(Vote(option_id=vote.option_id, vote=vote.vote, reason=vote.reason))
            vetoed = sorted(
                oid
                for oid in shortlist_ids
                if any(c.owner == role for c in _failing(shortlist_checks.get(oid, [])))
            )
            objections = [
                Objection(
                    option_id=v.option_id,
                    category=v.reason,  # type: ignore[arg-type]
                    reason=f"Turn 2 disapproval ({v.reason})",
                )
                for v in votes
                if v.vote == "DISAPPROVE" and v.reason in _OBJECTION_CATEGORIES
            ]
            top = next((oid for oid in ballot.ranking if oid in approvals[role]), None)
            status = self._counter_status.get((2, role)) or {}
            summaries.append(
                PublicSummary(
                    sender=role,
                    turn=2,
                    top_choice=top,
                    vetoed_option_ids=vetoed,
                    objections=objections,
                    counter_option_id=status.get("option_id") if status.get("validated") else None,
                    votes=votes,
                    rationale=ballot.rationale,
                )
            )
        return summaries

    def _context_manifest(
        self,
        role: AgentRole,
        turn: int,
        inputs: dict[str, Any],
        agent: Any,
    ) -> dict[str, Any]:
        """Hash exactly what ``role`` saw this turn: public part + its own private part."""
        public_sha = sha256_json({"public": self.public.model_dump(mode="json"), "inputs": inputs})
        private_sha = str(agent.private_fingerprint())
        combined = sha256_json(
            {"role": role.value, "turn": turn, "public_sha": public_sha, "private_sha": private_sha}
        )
        return {
            "combined": combined,
            "breakdown": {"public_sha": public_sha, "private_sha": private_sha},
        }

    def _first_alternate(self) -> str:
        return self.public.alternate_candidates[0] if self.public.alternate_candidates else "nearest suitable airport"


# --------------------------------------------------------------------------- module helpers


def _failing(checks: list[ConstraintCheck]) -> list[ConstraintCheck]:
    return [c for c in checks if c.hard and not c.passed]


def _constraint_ids(checks: list[ConstraintCheck]) -> list[str]:
    out: list[str] = []
    for check in checks:
        if check.constraint_id not in out:
            out.append(check.constraint_id)
    return out


def _dump(models: list[Any]) -> list[dict[str, Any]]:
    return [m.model_dump(mode="json") if hasattr(m, "model_dump") else m for m in models]


def _eur(value: float) -> str:
    return f"€{value:,.0f}"


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _blocking(
    shortlist_ids: list[str],
    approvals: dict[AgentRole, set[str]],
    record: dict[str, Any],
) -> list[dict[str, Any]]:
    """Per shortlisted option: who withheld approval and why (from the turn record)."""
    out: list[dict[str, Any]] = []
    for oid in shortlist_ids:
        by_role: dict[str, str] = {}
        for role in TURN_ORDER:
            if oid in approvals[role]:
                continue
            entries = record["per_agent"][role.value]["disapproved"]
            by_role[role.value] = next((d["reason"] for d in entries if d["option_id"] == oid), "NO_VOTE")
        if not by_role:
            continue
        out.append(
            {
                "option_id": oid,
                "approved_by": [role.value for role in TURN_ORDER if oid in approvals[role]],
                "blocked_by": list(by_role),
                "reasons": [f"{role}: {reason}" for role, reason in by_role.items()],
                "by_role": by_role,
            }
        )
    return out


def _blocking_text(blocking: list[dict[str, Any]]) -> str:
    if not blocking:
        return "no option was approved by all three agents"
    parts = [
        f"{b['option_id']} blocked by "
        + _join([f"{role} ({reason})" for role, reason in b["by_role"].items()])
        for b in blocking
    ]
    return "; ".join(parts)


def _fallback_summary(
    turns_used: int,
    blocking: list[dict[str, Any]],
    chosen_id: str,
    totals: dict[str, float],
) -> str:
    """One plain-English paragraph explaining why the fallback decided."""
    turn_word = "turn" if turns_used == 1 else "turns"
    parts = [f"No option won all three approvals in {turns_used} {turn_word}."]
    if blocking:
        items = [
            f"{b['option_id']} was blocked by "
            + _join([f"{role} ({reason})" for role, reason in b["by_role"].items()])
            for b in blocking
        ]
        label = "In the final ballot" if turns_used == MAX_TURNS else f"In Turn {turns_used}"
        parts.append(f"{label}, " + "; ".join(items) + ".")
    if any(_SAFETY_BLOCK_REASON in b["by_role"].values() for b in blocking):
        parts.append("SAFETY_BLOCK means an approval was discarded because the option fails a hard check.")
    n = len(totals)
    parts.append(
        f"The deterministic fallback picked {chosen_id} because it is the cheapest option that passes "
        f"every check ({_eur(totals.get(chosen_id, 0.0))} total disclosed cost, "
        f"{n} safe candidate{'s' if n != 1 else ''} considered)."
    )
    return " ".join(parts)
