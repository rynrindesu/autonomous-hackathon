"""Test doubles: no dependency on the WORLD lane."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from triad.agents.base import BaseAgent
from triad.schemas import (
    AgentRole,
    AircraftInfo,
    ArrivalSlot,
    AtcPrivate,
    BallotMessage,
    CandidateOption,
    Connection,
    ConstraintCheck,
    CounterOption,
    CrewShift,
    DefectReport,
    DisruptionEvent,
    DisruptionType,
    FlightRecord,
    Gate,
    GroundPrivate,
    Mode,
    NextLeg,
    Objection,
    PerceivedFact,
    PilotPrivate,
    ProposalMessage,
    PublicEvent,
    PublicSummary,
    SizeClass,
    Vote,
    WakeCat,
)

DEFAULT_CFG: dict[str, Any] = {
    "weights": {},
    "accept_tolerance": 0.25,
    "objection_threshold": 1.01,
}


class FakePrivate(BaseModel):
    tag: str = ""


class FakeAgent(BaseAgent):
    """Dict-driven agent: every check/objective/cost is scripted by the test."""

    impl = "fake"

    def __init__(
        self,
        role: AgentRole,
        *,
        cfg: dict[str, Any] | None = None,
        private: BaseModel | None = None,
        fail_map: dict[str, list[str]] | None = None,
        objectives_map: dict[str, dict[str, float]] | None = None,
        util_map: dict[str, float] | None = None,
        cost_map: dict[str, dict[str, float]] | None = None,
        ranking: list[str] | None = None,
        objections: list[Objection] | None = None,
        counter: CounterOption | None = None,
        omit_vetoes: bool = False,
        raise_turn1: bool = False,
        raise_turn2: bool = False,
        turn2_votes: dict[str, tuple[str, str | None]] | None = None,
        extra_votes: list[Vote] | None = None,
        facts: list[PerceivedFact] | None = None,
    ) -> None:
        super().__init__(role, private or FakePrivate(tag=role.value), dict(cfg or DEFAULT_CFG))
        self.fail_map = {k: list(v) for k, v in (fail_map or {}).items()}
        self.objectives_map = objectives_map or {}
        self.util_map = util_map or {}
        self.cost_map = cost_map or {}
        self.ranking_override = ranking
        self.objections = objections or []
        self.counter_value = counter
        self.omit_vetoes = omit_vetoes
        self.raise_turn1 = raise_turn1
        self.raise_turn2 = raise_turn2
        self.turn2_votes = turn2_votes or {}
        self.extra_votes = extra_votes or []
        self.facts = facts or []
        self.last_fallback_option = None

    # ---------------------------------------------------------------- code-only API
    def perceive(self, public: PublicEvent) -> list[PerceivedFact]:
        return self.facts

    def check(self, public: PublicEvent, option: CandidateOption) -> list[ConstraintCheck]:
        fails = self.fail_map.get(option.option_id, [])
        if not fails:
            return [
                ConstraintCheck(
                    check_id=self._next_check_id(),
                    constraint_id=f"{self.role.value}-OK-01",
                    owner=self.role,
                    option_id=option.option_id,
                    passed=True,
                    source="fake",
                )
            ]
        return [
            ConstraintCheck(
                check_id=self._next_check_id(),
                constraint_id=cid,
                owner=self.role,
                option_id=option.option_id,
                passed=False,
                source="fake",
            )
            for cid in fails
        ]

    def objectives(self, public: PublicEvent, option: CandidateOption) -> dict[str, float]:
        return self.objectives_map.get(option.option_id, {})

    def utility(self, public: PublicEvent, option: CandidateOption) -> float:
        return float(self.util_map.get(option.option_id, 0.0))

    def cost_eur(self, public: PublicEvent, option: CandidateOption) -> dict[str, float]:
        return dict(self.cost_map.get(option.option_id, {"TOTAL": 0.0}))

    # ---------------------------------------------------------------- decide
    def turn1(self, public: PublicEvent, options: list[CandidateOption]) -> ProposalMessage:
        if self.raise_turn1:
            raise RuntimeError("scripted turn1 failure")
        checks_by_option = {option.option_id: self.check(public, option) for option in options}
        failed_ids: list[str] = []
        vetoes = []
        for option in options:
            failing = [c for c in checks_by_option[option.option_id] if c.hard and not c.passed]
            if failing:
                failed_ids.append(option.option_id)
                vetoes.append(
                    {
                        "option_id": option.option_id,
                        "constraint_id": failing[0].constraint_id,
                        "check_id": failing[0].check_id,
                    }
                )
        if self.ranking_override is not None:
            ranking = list(self.ranking_override)
        else:
            ranking = sorted(
                (o.option_id for o in options if o.option_id not in failed_ids),
                key=lambda oid: (-self.util_map.get(oid, 0.0), oid),
            )
        return ProposalMessage(
            run_id=public.run_id,
            sender=self.role,
            vetoes=[] if self.omit_vetoes else vetoes,  # type: ignore[arg-type]
            ranking=ranking,
            objections=list(self.objections),
            counter_option=self.counter_value,
            citations=[],
            rationale=f"{self.role.value} fake proposal",
            facts=list(self.facts),
            checks=[c for checks in checks_by_option.values() for c in checks],
        )

    def turn2(
        self,
        public: PublicEvent,
        shortlist: list[CandidateOption],
        summaries: list[PublicSummary],
        *,
        fallback_option: CandidateOption | None = None,
    ) -> BallotMessage:
        if self.raise_turn2:
            raise RuntimeError("scripted turn2 failure")
        self.last_fallback_option = fallback_option
        best = max((self.util_map.get(o.option_id, 0.0) for o in shortlist), default=0.0)
        fallback_utility = (
            self.util_map.get(fallback_option.option_id, 0.0)
            if fallback_option is not None
            else float("-inf")
        )
        votes: list[Vote] = []
        for option in shortlist:
            oid = option.option_id
            failing = [c for c in self.check(public, option) if c.hard and not c.passed]
            if oid in self.turn2_votes:
                vote, reason = self.turn2_votes[oid]
                votes.append(Vote(option_id=oid, vote=vote, reason=reason))  # type: ignore[arg-type]
            elif failing:
                votes.append(Vote(option_id=oid, vote="DISAPPROVE", reason=failing[0].constraint_id))
            elif self.util_map.get(oid, 0.0) >= best - float(self.cfg.get("accept_tolerance", 0.25)) or (
                fallback_option is not None
                and self.util_map.get(oid, 0.0) >= fallback_utility
            ):
                votes.append(Vote(option_id=oid, vote="APPROVE"))
            else:
                votes.append(Vote(option_id=oid, vote="DISAPPROVE", reason="OTHER"))
        votes.extend(self.extra_votes)
        approved = [v.option_id for v in votes if v.vote == "APPROVE"]
        in_shortlist = {o.option_id for o in shortlist}
        ranking = sorted(
            (oid for oid in approved if oid in in_shortlist),
            key=lambda oid: (-self.util_map.get(oid, 0.0), oid),
        )
        return BallotMessage(
            run_id=public.run_id,
            sender=self.role,
            votes=votes,
            ranking=ranking,
            citations=[],
            rationale=f"{self.role.value} fake ballot",
        )


# --------------------------------------------------------------------------- world fixtures


def make_option(option_id: str, **overrides: Any) -> CandidateOption:
    data: dict[str, Any] = {
        "option_id": option_id,
        "mode": Mode.AIRBORNE,
        "arrival_slot": 600,
        "runway": "17C",
        "holding_min": 0,
        "enroute_absorb_min": 0,
        "gate": "A1",
        "next_leg_action": "KEEP",
        "next_leg_delay_min": 0,
    }
    data.update(overrides)
    return CandidateOption(**data)


def make_options() -> list[CandidateOption]:
    return [make_option(f"OPT-{i:02d}") for i in range(1, 5)]


def make_public(**overrides: Any) -> PublicEvent:
    flight = FlightRecord(
        row_index=0,
        year=2015,
        month=1,
        day=1,
        day_of_week=4,
        airline="AA",
        flight_number=1344,
        tail_number="N123AA",
        origin="DEN",
        destination="DFW",
        scheduled_departure=480,
        distance=641,
        scheduled_arrival=600,
        weather_delay=35,
        late_aircraft_delay=40,
    )
    aircraft = AircraftInfo(
        type_code="B738",
        wake=WakeCat.M,
        size_class=SizeClass.NARROW,
        seats=162,
        approach_speed_kt=140,
        cruise_burn_kg_min=38.0,
        holding_burn_kg_min=40.0,
    )
    data: dict[str, Any] = {
        "run_id": flight.run_id,
        "mode": Mode.AIRBORNE,
        "disruption_type": DisruptionType.WEATHER,
        "disruption_summary": "Thunderstorms cutting arrival rate at DFW",
        "flight": flight,
        "aircraft": aircraft,
        "decision_time": 540,
        "original_eta": 600,
        "expected_eta": 635,
        "destination_runways": ["17C", "17L", "13R"],
        "public_gate_ids": ["A1", "A2", "B14"],
        "alternate_candidates": ["OKC", "AUS"],
        "synthetic_fields": ["aircraft", "gates"],
    }
    data.update(overrides)
    return PublicEvent(**data)


def make_shared_checker(fail_ids: set[str] | None = None):
    failing = set(fail_ids or set())

    def checker(public: PublicEvent, option: CandidateOption, next_id) -> list[ConstraintCheck]:
        if option.option_id in failing:
            return [
                ConstraintCheck(
                    check_id=next_id(),
                    constraint_id="SHR-FAKE-01",
                    owner="SHARED",
                    option_id=option.option_id,
                    passed=False,
                    source="fake",
                )
            ]
        return [
            ConstraintCheck(
                check_id=next_id(),
                constraint_id="SHR-OK-01",
                owner="SHARED",
                option_id=option.option_id,
                passed=True,
                source="fake",
            )
        ]

    return checker


def make_disruption_event() -> DisruptionEvent:
    public = make_public()
    return DisruptionEvent(
        public=public,
        atc=AtcPrivate(
            aar_normal=40,
            aar_reduced=25,
            slots=[ArrivalSlot(slot_time=600, runway="17C", gap_nm=6.0)],
            notam_text=[],
        ),
        pilot=PilotPrivate(
            fuel_on_board_kg=5000,
            fuel_to_destination_kg=3000,
            alternate="OKC",
            alternate_distance_nm=180,
            fuel_to_alternate_kg=1200,
            reserve_45_kg=1700,
            max_extra_fuel_kg=2000,
            cruise_levels=[320, 340, 360],
            turbulence_text=[],
            connections=[
                Connection(
                    airline="AA",
                    flight_number=2000,
                    destination="LAX",
                    scheduled_departure=720,
                    pax=12,
                    mct_min=40,
                    real=True,
                )
            ],
            crew_duty_remaining_min=300,
        ),
        ground=GroundPrivate(
            gates=[
                Gate(gate_id="A1", max_size=SizeClass.NARROW, carrier="AA"),
                Gate(gate_id="B14", max_size=SizeClass.NARROW, carrier=None),
            ],
            current_gate="A1",
            shifts=[
                CrewShift(
                    shift_id="S1",
                    start=360,
                    end=720,
                    hard_limit_end=780,
                    overtime_eur_per_min=5.0,
                )
            ],
            min_turnaround_min=45,
            next_leg=NextLeg(
                flight_number=1345,
                destination="LAX",
                scheduled_departure=700,
                real=True,
            ),
            defect=DefectReport(defect_id="D1", text="hyd low press"),
            spare_aircraft_available=False,
            gate_change_eur=400.0,
        ),
    )


def default_agents(**overrides: Any) -> dict[AgentRole, FakeAgent]:
    return {
        AgentRole.ATC: FakeAgent(AgentRole.ATC, **overrides.get("atc", {})),
        AgentRole.PILOT: FakeAgent(AgentRole.PILOT, **overrides.get("pilot", {})),
        AgentRole.GROUND: FakeAgent(AgentRole.GROUND, **overrides.get("ground", {})),
    }
