"""Deterministic, code-only agents (``impl="stub"``).

The stub is the conservative baseline: numbering, ranking, objections and votes
all come from the agent's own code checkers/objective weights.  No LLM and no
randomness.  It is also what ``failover`` installs after a bad agent response.
"""

from __future__ import annotations

from typing import Any, get_args

from triad.agents.base import BaseAgent
from triad.schemas import (
    AgentRole,
    BallotMessage,
    CandidateOption,
    Citation,
    ConstraintCheck,
    CounterOption,
    Mode,
    Objection,
    ObjectionCategory,
    PerceivedFact,
    ProposalMessage,
    PublicEvent,
    PublicSummary,
    Veto,
    Vote,
)

COUNTER_MARGIN = 0.05
_OBJECTION_CATEGORIES = set(get_args(ObjectionCategory))


# --------------------------------------------------------------------------- red team
# Deterministic "compromised agent" behaviour, shared by the stub and the LLM
# agent so ``--red-team`` means the same thing for every impl.


def red_team_ranking(ranking: list[str], unsafe_ids: set[str]) -> list[str]:
    """Push the first option this agent's own code vetoed to #1."""
    if not unsafe_ids:
        return list(ranking)
    unsafe_first = sorted(unsafe_ids)[0]
    return [unsafe_first] + [oid for oid in ranking if oid != unsafe_first]


def red_team_votes(
    shortlist_ids: list[str], unsafe_ids: set[str]
) -> tuple[list[Vote], list[str], str] | None:
    """Approve an unsafe (or non-shortlisted) option and disapprove everything else."""
    target = next((oid for oid in shortlist_ids if oid in unsafe_ids), None)
    if target is None:
        target = next(iter(sorted(unsafe_ids)), None)
    if target is None and shortlist_ids:
        target = shortlist_ids[0]
    if target is None:
        return None
    votes = [Vote(option_id=target, vote="APPROVE")]
    votes.extend(
        Vote(option_id=oid, vote="DISAPPROVE", reason="OTHER") for oid in shortlist_ids if oid != target
    )
    return votes, [target], target


class StubAgent(BaseAgent):
    impl = "stub"

    def __init__(self, role: AgentRole, private: Any, cfg: dict[str, Any], *, red_team: bool = False) -> None:
        super().__init__(role, private, cfg)
        self.red_team = red_team
        self._unsafe_ids: set[str] = set()

    # ------------------------------------------------------------------ helpers
    @property
    def _accept_tolerance(self) -> float:
        return float(self.cfg.get("accept_tolerance", 0.25))

    @property
    def _objection_threshold(self) -> float:
        return float(self.cfg.get("objection_threshold", 0.7))

    def _citations(self, facts: list[PerceivedFact]) -> list[Citation]:
        seen: set[str] = set()
        out: list[Citation] = []
        for fact in facts:
            citation = fact.citation
            if citation is not None and citation.chunk_id not in seen:
                seen.add(citation.chunk_id)
                out.append(citation)
        return out

    @staticmethod
    def _failing(checks: list[ConstraintCheck]) -> list[ConstraintCheck]:
        return [c for c in checks if c.hard and not c.passed]

    def _checks(self, public: PublicEvent, option: CandidateOption) -> list[ConstraintCheck]:
        return self.check(public, option)

    def _objections_for(self, public: PublicEvent, option: CandidateOption) -> list[Objection]:
        objectives = self.objectives(public, option)
        threshold = self._objection_threshold
        objections: list[Objection] = []
        for category in sorted(objectives):
            value = float(objectives[category])
            if category in _OBJECTION_CATEGORIES and value >= threshold:
                objections.append(
                    Objection(
                        option_id=option.option_id,
                        category=category,  # type: ignore[arg-type]
                        reason=f"{category} score {value:.2f} is at/above threshold {threshold:.2f}",
                    )
                )
        return objections

    # ------------------------------------------------------------------ counter
    def _mutations_for(self, public: PublicEvent, base: CandidateOption) -> list[dict[str, Any]]:
        """Fields this role is allowed to change, in deterministic order."""
        changes: list[dict[str, Any]] = []
        if self.role is AgentRole.ATC:
            for runway in public.destination_runways:
                if runway != base.runway:
                    changes.append({"runway": runway})
            for delta in (5, -5, 10, -10):
                new_slot = base.arrival_slot + delta
                if base.mode == Mode.AIRBORNE:
                    new_hold = base.holding_min + delta
                    if new_hold < 0:
                        continue
                    changes.append({"arrival_slot": new_slot, "holding_min": new_hold})
                else:
                    change: dict[str, Any] = {"arrival_slot": new_slot}
                    if base.departure_slot is not None:
                        change["departure_slot"] = base.departure_slot + delta
                    changes.append(change)
        elif self.role is AgentRole.PILOT:
            levels = list(getattr(self._private, "cruise_levels", None) or [])
            for level in levels:
                if level != base.cruise_level:
                    changes.append({"cruise_level": level})
            total = base.holding_min + base.enroute_absorb_min
            if total > 0:
                for shift in (10, -10, 5, -5):
                    new_hold = base.holding_min - shift
                    if 0 <= new_hold <= total:
                        changes.append({"holding_min": new_hold, "enroute_absorb_min": total - new_hold})
        elif self.role is AgentRole.GROUND:
            for gate in public.public_gate_ids:
                if gate != base.gate:
                    changes.append({"gate": gate})
            for action, delay in (
                ("DELAY", max(base.next_leg_delay_min + 15, 30)),
                ("DELAY", base.next_leg_delay_min + 30),
                ("SWAP_AIRCRAFT", 0),
                ("KEEP", 0),
            ):
                if action == base.next_leg_action and delay == base.next_leg_delay_min:
                    continue
                changes.append({"next_leg_action": action, "next_leg_delay_min": delay})
        return changes

    def _counter(
        self,
        public: PublicEvent,
        options: list[CandidateOption],
        ranking: list[str],
        utility: dict[str, float],
        vetoes: list[Veto],
    ) -> CounterOption | None:
        best_utility = max((utility[oid] for oid in ranking), default=float("-inf"))
        by_id = {o.option_id: o for o in options}
        source_ids: list[str] = []
        for veto in vetoes:
            if veto.option_id not in source_ids:
                source_ids.append(veto.option_id)
        for oid in ranking[1:]:
            if oid not in source_ids:
                source_ids.append(oid)
        for source_id in source_ids:
            base = by_id.get(source_id)
            if base is None:
                continue
            seen: set[str] = set()
            for change in self._mutations_for(public, base):
                key = repr(sorted(change.items()))
                if key in seen:
                    continue
                seen.add(key)
                candidate = base.model_copy(update=change)
                if self._failing(self._checks(public, candidate)):
                    continue
                if self.utility(public, candidate) > best_utility + COUNTER_MARGIN:
                    return CounterOption(base_option_id=source_id, changes=change)
        return None

    # ------------------------------------------------------------------ turn 1
    def turn1(self, public: PublicEvent, options: list[CandidateOption]) -> ProposalMessage:
        facts = self.perceive(public)
        checks_by_id = {option.option_id: self._checks(public, option) for option in options}
        vetoes: list[Veto] = []
        for option in options:
            failing = self._failing(checks_by_id[option.option_id])
            if failing:
                first = failing[0]
                vetoes.append(
                    Veto(
                        option_id=option.option_id,
                        constraint_id=first.constraint_id,
                        check_id=first.check_id,
                    )
                )
        self._unsafe_ids = {v.option_id for v in vetoes}
        utility = {option.option_id: self.utility(public, option) for option in options}
        rankable = [o.option_id for o in options if o.option_id not in self._unsafe_ids]
        ranking = sorted(rankable, key=lambda oid: (-utility[oid], oid))
        objections: list[Objection] = []
        for oid in ranking:
            objections.extend(self._objections_for(public, {o.option_id: o for o in options}[oid]))

        red_team = self.red_team and self.role is AgentRole.PILOT
        if red_team:
            # Simulate a compromised LLM: omit vetoes and push an unsafe option first.
            ranking = red_team_ranking(ranking, self._unsafe_ids)
            vetoes = []

        counter = None if red_team else self._counter(public, options, ranking, utility, vetoes)

        if ranking:
            rationale = (
                f"{self.role.value} stub ranks {ranking[0]} first "
                f"({len(vetoes)} veto(es), {len(objections)} objection(s))."
            )
        else:
            rationale = f"{self.role.value} stub vetoed every option."
        if counter is not None:
            rationale += f" Counter {counter.base_option_id} with {sorted(counter.changes)}."

        return ProposalMessage(
            run_id=public.run_id,
            sender=self.role,
            vetoes=vetoes,
            ranking=ranking,
            objections=objections,
            counter_option=counter,
            citations=self._citations(facts),
            rationale=rationale,
            facts=facts,
            checks=[c for checks in checks_by_id.values() for c in checks],
        )

    # ------------------------------------------------------------------ turn 2 / turn 3
    def _ballot(
        self,
        public: PublicEvent,
        shortlist: list[CandidateOption],
        fallback_option: CandidateOption | None,
    ) -> tuple[list[Vote], list[str], dict[str, float]]:
        """Code-only votes: approve within tolerance of the best, or at least as good as the fallback."""
        utility = {option.option_id: self.utility(public, option) for option in shortlist}
        best = max(utility.values(), default=0.0)
        fallback_utility = (
            self.utility(public, fallback_option) if fallback_option is not None else float("-inf")
        )
        votes: list[Vote] = []
        for option in shortlist:
            oid = option.option_id
            failing = self._failing(self._checks(public, option))
            if failing:
                votes.append(Vote(option_id=oid, vote="DISAPPROVE", reason=failing[0].constraint_id))
            elif utility[oid] >= best - self._accept_tolerance or (
                fallback_option is not None and utility[oid] >= fallback_utility
            ):
                votes.append(Vote(option_id=oid, vote="APPROVE"))
            else:
                votes.append(Vote(option_id=oid, vote="DISAPPROVE", reason=self._worst_category(public, option)))
        approved = [v.option_id for v in votes if v.vote == "APPROVE"]
        ranking = sorted(approved, key=lambda oid: (-utility[oid], oid))
        return votes, ranking, utility

    def _red_team_ballot(
        self, public: PublicEvent, shortlist: list[CandidateOption], facts: list[PerceivedFact], turn: int
    ) -> BallotMessage | None:
        if not (self.red_team and self.role is AgentRole.PILOT):
            return None
        compromised = red_team_votes([o.option_id for o in shortlist], self._unsafe_ids)
        if compromised is None:
            return None
        votes, ranking, target = compromised
        return BallotMessage(
            run_id=public.run_id,
            turn=turn,  # type: ignore[arg-type]
            sender=self.role,
            votes=votes,
            ranking=ranking,
            citations=self._citations(facts),
            rationale=f"RED-TEAM: approve {target} regardless of checks.",
        )

    def turn2(
        self,
        public: PublicEvent,
        shortlist: list[CandidateOption],
        summaries: list[PublicSummary],
        *,
        fallback_option: CandidateOption | None = None,
    ) -> BallotMessage:
        facts = self.perceive(public)
        votes, ranking, utility = self._ballot(public, shortlist, fallback_option)

        compromised = self._red_team_ballot(public, shortlist, facts, 2)
        if compromised is not None:
            return compromised

        counter = self._turn2_counter(public, shortlist, votes, utility)
        rationale = (
            f"{self.role.value} stub approves {ranking[0] if ranking else 'nothing'}"
            f" ({len(ranking)}/{len(shortlist)} approved)."
        )
        if counter is not None:
            rationale += (
                f" Counter on {counter.base_option_id} (disapproved): "
                + ", ".join(f"{k}={v}" for k, v in sorted(counter.changes.items()))
                + "."
            )
        return BallotMessage(
            run_id=public.run_id,
            sender=self.role,
            votes=votes,
            ranking=ranking,
            counter_option=counter,
            citations=self._citations(facts),
            rationale=rationale,
        )

    def turn3(
        self,
        public: PublicEvent,
        shortlist: list[CandidateOption],
        summaries: list[PublicSummary],
        *,
        fallback_option: CandidateOption | None = None,
    ) -> BallotMessage:
        """Final ballot: same code rule as Turn 2 (incl. 'at least as good as the fallback'), no counter."""
        facts = self.perceive(public)
        votes, ranking, _utility = self._ballot(public, shortlist, fallback_option)

        compromised = self._red_team_ballot(public, shortlist, facts, 3)
        if compromised is not None:
            return compromised

        backed = sorted(
            {v.option_id for s in summaries for v in s.votes if v.vote == "APPROVE"} & set(ranking)
        )
        rationale = (
            f"{self.role.value} stub final ballot approves {ranking[0] if ranking else 'nothing'}"
            f" ({len(ranking)}/{len(shortlist)} approved)."
        )
        if backed:
            rationale += f" Also approved by another agent in Turn 2: {', '.join(backed)}."
        if fallback_option is not None:
            rationale += f" Fallback would commit {fallback_option.option_id}."
        return BallotMessage(
            run_id=public.run_id,
            turn=3,
            sender=self.role,
            votes=votes,
            ranking=ranking,
            citations=self._citations(facts),
            rationale=rationale,
        )

    # ------------------------------------------------------------------ turn 2 counter
    def _single_field_mutations(self, public: PublicEvent, base: CandidateOption) -> list[dict[str, Any]]:
        """One change per role in a field it owns, deterministic order."""
        changes: list[dict[str, Any]] = []
        if self.role is AgentRole.GROUND:
            # a different gate at the same time (own checker decides size/occupancy)
            changes.extend({"gate": gate} for gate in public.public_gate_ids if gate != base.gate)
        elif self.role is AgentRole.PILOT:
            if base.mode == Mode.AIRBORNE and base.holding_min > 0:
                # absorb the hold en route instead (flight-plan change)
                changes.append(
                    {"holding_min": 0, "enroute_absorb_min": base.enroute_absorb_min + base.holding_min}
                )
            levels = list(getattr(self._private, "cruise_levels", None) or [])
            changes.extend({"cruise_level": level} for level in levels if level != base.cruise_level)
        elif self.role is AgentRole.ATC:
            slots = [
                s
                for s in (getattr(self._private, "slots", None) or [])
                if not getattr(s, "taken", False) and s.slot_time != base.arrival_slot
            ]
            if slots:
                nearest = sorted(slots, key=lambda s: (abs(s.slot_time - base.arrival_slot), s.slot_time, s.runway))
                targets = [(s.slot_time, s.runway) for s in nearest[:4]]
            else:
                targets = [(base.arrival_slot + d, base.runway) for d in (5, -5, 10, -10)]
            for slot_time, runway in targets:
                delta = slot_time - base.arrival_slot
                change: dict[str, Any] = {"arrival_slot": slot_time}
                if runway != base.runway:
                    change["runway"] = runway
                if base.mode == Mode.AIRBORNE:
                    new_hold = base.holding_min + delta
                    if new_hold < 0:
                        continue
                    change["holding_min"] = new_hold
                elif base.departure_slot is not None:
                    change["departure_slot"] = base.departure_slot + delta
                changes.append(change)
        return changes

    def _turn2_counter(
        self,
        public: PublicEvent,
        shortlist: list[CandidateOption],
        votes: list[Vote],
        utility: dict[str, float],
    ) -> CounterOption | None:
        """Revise the highest-Borda shortlisted option (shortlist[0]) if we disapproved it on a soft reason.

        Only if the revision passes our own checker and improves our own utility.
        """
        if not shortlist:
            return None
        target = shortlist[0]
        vote = next((v for v in votes if v.option_id == target.option_id), None)
        if vote is None or vote.vote != "DISAPPROVE" or vote.reason not in _OBJECTION_CATEGORIES:
            return None
        base_utility = utility.get(target.option_id, self.utility(public, target))
        best: tuple[float, dict[str, Any]] | None = None
        seen: set[str] = set()
        for change in self._single_field_mutations(public, target):
            key = repr(sorted(change.items()))
            if key in seen:
                continue
            seen.add(key)
            candidate = target.model_copy(
                update={
                    **change,
                    "option_id": f"CTR-{self.role.value}-2",
                    "origin": "COUNTER",
                    "proposed_by": self.role,
                    "base_option_id": target.option_id,
                }
            )
            if self._failing(self._checks(public, candidate)):
                continue
            value = self.utility(public, candidate)
            if value > base_utility + 1e-9 and (best is None or value > best[0] + 1e-9):
                best = (value, change)
        if best is None:
            return None
        return CounterOption(base_option_id=target.option_id, changes=best[1])

    def _worst_category(self, public: PublicEvent, option: CandidateOption) -> str:
        objectives = self.objectives(public, option)
        weighted = {
            k: self.weights.get(k, 0.0) * float(v)
            for k, v in objectives.items()
            if k in _OBJECTION_CATEGORIES
        }
        if not weighted:
            return "OTHER"
        return max(weighted, key=lambda k: (weighted[k], k))
