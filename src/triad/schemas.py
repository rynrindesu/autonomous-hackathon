"""Shared contract for Triad. FROZEN for Day 0-2: change only with team agreement.

Conventions
-----------
* All clock times are ``int`` minutes since local midnight of the flight date
  (values >= 1440 mean "next day"). Use ``fmt_hhmm`` for display.
* Information hiding: ``DisruptionEvent`` bundles the public part and three private
  parts. Only the scenario builder and ``agents.build_agents`` may touch the private
  parts. The orchestrator receives ``PublicEvent`` + agent objects only.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- enums


class AgentRole(StrEnum):
    ATC = "ATC"
    PILOT = "PILOT"
    GROUND = "GROUND"


class Mode(StrEnum):
    AIRBORNE = "AIRBORNE"  # WEATHER_DELAY > 15 rows: decision ~60 min before arrival
    GROUND = "GROUND"  # LATE_AIRCRAFT_DELAY > 20 rows (no weather): decision at origin pre-departure


class DisruptionType(StrEnum):
    WEATHER = "WEATHER"
    LATE_AIRCRAFT = "LATE_AIRCRAFT"


class WakeCat(StrEnum):
    """ICAO wake turbulence categories (ICAO only; do not mix with FAA CWT groups)."""

    L = "L"
    M = "M"
    H = "H"
    J = "J"  # Super (A380)


class SizeClass(StrEnum):
    REGIONAL = "REGIONAL"
    NARROW = "NARROW"
    WIDE = "WIDE"


def fmt_hhmm(minutes: int | None) -> str:
    if minutes is None:
        return "--:--"
    day, m = divmod(int(minutes), 1440)
    s = f"{m // 60:02d}:{m % 60:02d}"
    return s + (f"+{day}" if day else "")


# --------------------------------------------------------------------------- source data


class FlightRecord(Model):
    """One parsed row of datasets/flights.csv. Times converted to minutes of day."""

    row_index: int
    year: int
    month: int
    day: int
    day_of_week: int
    airline: str
    flight_number: int
    tail_number: str
    origin: str
    destination: str
    scheduled_departure: int
    departure_time: int | None = None
    departure_delay: int | None = None
    taxi_out: int | None = None
    scheduled_time: int | None = None
    elapsed_time: int | None = None
    air_time: int | None = None
    distance: int
    scheduled_arrival: int  # may be >= 1440 if it lands after midnight
    arrival_time: int | None = None
    arrival_delay: int | None = None
    air_system_delay: int = 0
    security_delay: int = 0
    airline_delay: int = 0
    late_aircraft_delay: int = 0
    weather_delay: int = 0

    @property
    def run_id(self) -> str:
        return f"{self.year}-{self.month:02d}-{self.day:02d}-{self.airline}{self.flight_number}-r{self.row_index}"


class Citation(Model):
    doc: str
    chunk_id: str
    section: str | None = None
    url: str | None = None
    synthetic: bool = False


class PerceivedFact(Model):
    """Structured fact an agent extracted from unstructured input (stub or LLM+RAG)."""

    key: str  # e.g. "closed_taxiways", "turbulence_FL340", "mel_deferrable", "repair_min"
    value: Any
    confidence: float = Field(ge=0.0, le=1.0)
    citation: Citation | None = None
    conservative_default: bool = False  # True => perception failed/uncertain, safest reading applied
    source: Literal["STUB", "LLM", "DEFAULT"] = "STUB"


# --------------------------------------------------------------------------- synthetic world


class AircraftInfo(Model):
    type_code: str  # ICAO type designator, e.g. "B738"
    wake: WakeCat
    size_class: SizeClass
    seats: int
    approach_speed_kt: int
    cruise_burn_kg_min: float
    holding_burn_kg_min: float


class ArrivalSlot(Model):
    slot_time: int
    runway: str
    leader_type: str | None = None
    leader_wake: WakeCat | None = None
    gap_nm: float  # spacing available behind the leader if we take this slot
    taken: bool = False  # already allocated to other traffic


class Connection(Model):
    airline: str
    flight_number: int
    destination: str
    scheduled_departure: int
    pax: int
    mct_min: int
    real: bool  # True if derived from flights.csv


class NextLeg(Model):
    flight_number: int
    destination: str
    scheduled_departure: int
    real: bool


class Gate(Model):
    gate_id: str
    max_size: SizeClass
    carrier: str | None  # None => common-use
    occupied: list[tuple[int, int]] = []  # [start, end) windows in minutes of day
    taxi_route: list[str] = []  # taxiways needed to reach it from the arrival runway side


class CrewShift(Model):
    shift_id: str
    start: int
    end: int  # normal end; work beyond => overtime
    hard_limit_end: int  # company/labour hard limit
    overtime_eur_per_min: float  # = base_eur_per_min * overtime_multiplier
    base_eur_per_min: float = 0.0  # normal-time rate
    overtime_multiplier: float = 1.5  # workbook fuel_and_crew: overtime costs 1.5x after 8 h


class DefectReport(Model):
    defect_id: str
    text: str  # crew chief free text (perceived by Ground agent)
    fault_code: str | None = None
    # ground truth for stub perception / perception evaluation (LLM must NOT see these)
    truth_ata_chapter: int | None = None
    truth_mel_item: str | None = None
    truth_mel_category: Literal["A", "B", "C", "D"] | None = None
    truth_deferrable: bool | None = None
    truth_repair_min: int | None = None


class PublicEvent(Model):
    """Everything every party (and the orchestrator) may see."""

    run_id: str
    mode: Mode
    disruption_type: DisruptionType
    disruption_summary: str
    flight: FlightRecord
    aircraft: AircraftInfo
    decision_time: int
    original_eta: int  # scheduled arrival
    expected_eta: int  # best estimate before negotiation (includes known delay)
    destination_runways: list[str]  # ACTIVE arrival runway ends (ATIS-public), e.g. ["17C", "17L", "13R"]
    public_gate_ids: list[str]  # airport map info: carrier + common-use gate ids (no occupancy)
    alternate_candidates: list[str]  # nearby airports served by the carrier (public)
    synthetic_fields: list[str] = []  # names of fields that are synthetic (UI labelling)


class AtcPrivate(Model):
    aar_normal: int  # arrivals/hour in normal conditions (workbook: max_runway_ops_per_hour baseline)
    aar_reduced: int  # arrivals/hour after the disruption (e.g. weather-reduced)
    max_runway_ops_per_hour: int | None = None  # workbook airport_capacity (all runways, arr+dep)
    active_runways: int | None = None  # workbook airport_capacity
    slots: list[ArrivalSlot]
    notam_text: list[str]
    truth_closed_taxiways: list[str] = []  # stub perception / eval only


class PilotPrivate(Model):
    fuel_on_board_kg: float  # at decision time (AIRBORNE) or planned ramp fuel (GROUND)
    fuel_to_destination_kg: float  # from decision point at planned speed, no holding
    alternate: str
    alternate_distance_nm: float
    fuel_to_alternate_kg: float
    final_reserve_kg: float  # workbook fuel_and_crew: 30 min of holding fuel; never plan below this
    contingency_kg: float = 0.0  # workbook fuel_and_crew: 5% of trip fuel
    max_extra_fuel_kg: float  # GROUND mode: tank/MTOW headroom for extra uplift
    cruise_levels: list[int]  # candidate flight levels, e.g. [320, 340, 360]
    turbulence_text: list[str]
    truth_turbulence: dict[str, Literal["NONE", "LIGHT", "MODERATE", "SEVERE"]] = {}  # "FL340" -> level
    connections: list[Connection]
    pax_notes: list[str] = []
    crew_duty_remaining_min: int  # derived: report_time + max_duty - decision_time
    crew_report_time: int | None = None  # minutes of day the flight crew reported
    crew_max_duty_min: int = 780  # workbook fuel_and_crew: 13 h from report (simplified Part 117)


class GroundPrivate(Model):
    gates: list[Gate]
    current_gate: str  # originally planned destination gate
    shifts: list[CrewShift]
    min_turnaround_min: int  # workbook airport_capacity (destination airport)
    next_leg: NextLeg | None
    defect: DefectReport | None = None
    spare_aircraft_available: bool = False
    gate_change_eur: float
    gate_change_notice_min: int = 20  # workbook fuel_and_crew: gate change notice >= 20 min before arrival
    total_gates: int | None = None  # workbook airport_capacity
    spare_gates_at_any_time: int = 0  # workbook airport_capacity


class DisruptionEvent(Model):
    public: PublicEvent
    atc: AtcPrivate
    pilot: PilotPrivate
    ground: GroundPrivate


# --------------------------------------------------------------------------- options


NextLegAction = Literal["KEEP", "DELAY", "SWAP_AIRCRAFT"]


class CandidateOption(Model):
    option_id: str  # "OPT-01".. ; counters: "CTR-<ROLE>-1"; divert: "OPT-DIV"
    mode: Mode
    departure_slot: int | None = None  # GROUND mode only
    arrival_slot: int
    runway: str
    holding_min: int = 0  # AIRBORNE: delay absorbed in a hold
    enroute_absorb_min: int = 0  # AIRBORNE: delay absorbed by slowing down en route (flight-plan change)
    speed_recovery_min: int = 0  # GROUND: minutes recovered by flying faster (fuel cost)
    cruise_level: int | None = None  # flight-plan change: chosen FL
    gate: str
    next_leg_action: NextLegAction = "KEEP"
    next_leg_delay_min: int = 0
    divert_to: str | None = None
    origin: Literal["GENERATOR", "COUNTER"] = "GENERATOR"
    proposed_by: AgentRole | None = None  # for counters
    base_option_id: str | None = None  # for counters


class CounterOption(Model):
    base_option_id: str
    changes: dict[str, Any]  # subset of CandidateOption fields (not option_id/origin/mode)


# --------------------------------------------------------------------------- checks


class ConstraintCheck(Model):
    check_id: str  # unique per run, e.g. "chk-PILOT-0007"
    constraint_id: str  # e.g. "PLT-FUEL-01"; shared checks use "SHR-*"
    owner: AgentRole | Literal["SHARED"]
    option_id: str
    passed: bool
    hard: bool = True
    value: float | str | None = None
    limit: float | str | None = None
    unit: str | None = None
    source: str  # citation text, e.g. "14 CFR 121.639"
    detail: str = ""
    facts_used: list[str] = []  # PerceivedFact keys


# --------------------------------------------------------------------------- messages

ObjectionCategory = Literal[
    "FUEL", "DELAY", "PAX_CONNECTIONS", "TURBULENCE", "THROUGHPUT", "HOLDING_STACK",
    "OVERTIME", "GATE_CHANGE", "NEXT_LEG", "COST", "OTHER",
]


class Veto(Model):
    option_id: str
    constraint_id: str
    check_id: str  # must reference a failed ConstraintCheck produced this turn by the agent's checker


class Objection(Model):
    option_id: str
    category: ObjectionCategory
    reason: str


class ProposalMessage(Model):
    run_id: str
    turn: Literal[1] = 1
    sender: AgentRole
    type: Literal["PROPOSE"] = "PROPOSE"
    vetoes: list[Veto]
    ranking: list[str]  # ALL non-vetoed option ids, best first
    objections: list[Objection] = []
    counter_option: CounterOption | None = None
    citations: list[Citation] = []
    rationale: str
    facts: list[PerceivedFact] = []  # audit only; never forwarded to other agents
    checks: list[ConstraintCheck] = []  # audit only; never forwarded to other agents


class Vote(Model):
    option_id: str
    vote: Literal["APPROVE", "DISAPPROVE"]
    reason: str | None = None  # required for DISAPPROVE: constraint_id or objection category


class BallotMessage(Model):
    """Turn 2 (BALLOT) and Turn 3 (FINAL BALLOT).

    Turn 2 may carry at most one counter-option, based on an option the sender DISAPPROVED
    (validated in code by shared checks + all three checkers before it can enter Turn 3).
    Turn 3 must not carry a counter-option.
    """

    run_id: str
    turn: Literal[2, 3] = 2
    sender: AgentRole
    type: Literal["BALLOT"] = "BALLOT"
    votes: list[Vote]  # exactly one per shortlisted option
    ranking: list[str]  # approved option ids, best first
    counter_option: CounterOption | None = None  # Turn 2 only
    citations: list[Citation] = []
    rationale: str


class PublicSummary(Model):
    """What other agents may learn from an agent's previous-turn message (no private values)."""

    sender: AgentRole
    turn: int = 1  # turn the summary describes
    top_choice: str | None
    vetoed_option_ids: list[str]
    objections: list[Objection]
    counter_option_id: str | None = None
    votes: list[Vote] = []  # Turn 2 summaries: the sender's public votes + reasons
    rationale: str


class Resolution(Model):
    run_id: str
    status: Literal["CONSENSUS", "FALLBACK", "ESCALATED"]
    turn: int  # 1, 2 or 3 (0 if escalated at setup)
    decided_by: Literal["AGENTS", "FALLBACK", "HUMAN_ESCALATION"]
    option: CandidateOption | None
    reason: str
    checks: list[ConstraintCheck] = []  # final re-check of the committed option (assert_commit_safe)
    costs_eur: dict[str, float] = {}  # per-agent disclosed cost of the committed option
    briefings: dict[str, str] = {}  # filled by nlp layer later


# --------------------------------------------------------------------------- audit


class LogEntry(Model):
    seq: int
    ts: str
    run_id: str
    turn: int  # 0 = setup
    actor: Literal["ORCHESTRATOR", "ATC", "PILOT", "GROUND", "FALLBACK"]
    event: str  # SETUP, OPTIONS_GENERATED, TURN_START, PERCEPTION, PROPOSAL, COUNTER_VALIDATED,
    #           COUNTER_REJECTED, SHORTLIST, BALLOT, CONSENSUS_REACHED, FALLBACK_INVOKED, SAFETY_BLOCK,
    #           AGENT_FAILOVER, ESCALATED, COMMIT_GATE, COMMIT
    payload: dict[str, Any]
    payload_sha256: str
    prev_sha256: str
    context_manifest: dict[str, str] | None = None  # role -> sha256 of exactly what that agent saw
    usage: dict[str, Any] | None = None


class RunManifest(Model):
    run_id: str
    dataset_row: int
    seed: int
    mode: Mode
    agent_impl: dict[str, str]  # role -> "stub" | "llm:<model>"
    prompt_hashes: dict[str, str] = {}
    config_sha256: str  # hash of config/*.yaml contents
    code_version: str  # git sha or "dirty"
    created: str
