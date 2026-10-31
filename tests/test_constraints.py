"""Unit tests for the individual hard constraints and the fail-safe defaults."""

from __future__ import annotations

from typing import Any

from triad.agents.base import CheckIdGen
from triad.agents.perception import conservative_facts, stub_perceive
from triad.constraints.crew import check_crew
from triad.constraints.fuel import check_fuel
from triad.constraints.gate import check_gates
from triad.constraints.mel import check_mel
from triad.constraints.turnaround import check_turnaround
from triad.constraints.wake import check_wake
from triad.schemas import (
    AgentRole,
    AircraftInfo,
    ArrivalSlot,
    AtcPrivate,
    CandidateOption,
    CrewShift,
    DefectReport,
    FlightRecord,
    Gate,
    GroundPrivate,
    Mode,
    NextLeg,
    PerceivedFact,
    PilotPrivate,
    PublicEvent,
    SizeClass,
    WakeCat,
)


def _flight(**overrides: Any) -> FlightRecord:
    data: dict[str, Any] = {
        "row_index": 1,
        "year": 2015,
        "month": 1,
        "day": 1,
        "day_of_week": 4,
        "airline": "AA",
        "flight_number": 1344,
        "tail_number": "N123AA",
        "origin": "DEN",
        "destination": "DFW",
        "scheduled_departure": 600,
        "distance": 700,
        "scheduled_arrival": 760,
        "scheduled_time": 160,
    }
    data.update(overrides)
    return FlightRecord(**data)


def _aircraft(wake: str = "M", size: str = "NARROW", cruise: float = 40, hold: float = 35) -> AircraftInfo:
    return AircraftInfo(
        type_code="B738",
        wake=WakeCat(wake),
        size_class=SizeClass(size),
        seats=162,
        approach_speed_kt=145,
        cruise_burn_kg_min=cruise,
        holding_burn_kg_min=hold,
    )


def _public(**overrides: Any) -> PublicEvent:
    flight = overrides.pop("flight", _flight())
    aircraft = overrides.pop("aircraft", _aircraft())
    data: dict[str, Any] = {
        "run_id": "test-run",
        "mode": Mode.AIRBORNE,
        "disruption_type": "WEATHER",
        "disruption_summary": "test",
        "flight": flight,
        "aircraft": aircraft,
        "decision_time": 940,
        "original_eta": 760,
        "expected_eta": 1000,
        "destination_runways": ["17C"],
        "public_gate_ids": ["B1"],
        "alternate_candidates": ["OKC"],
        "synthetic_fields": [],
    }
    data.update(overrides)
    return PublicEvent(**data)


def _option(**overrides: Any) -> CandidateOption:
    data: dict[str, Any] = {
        "option_id": "OPT-01",
        "mode": Mode.AIRBORNE,
        "arrival_slot": 1000,
        "runway": "17C",
        "gate": "B1",
    }
    data.update(overrides)
    return CandidateOption(**data)


def _fact(key: str, value: Any) -> PerceivedFact:
    return PerceivedFact(key=key, value=value, confidence=1.0)


# --------------------------------------------------------------------------- wake


def test_wake_heavy_to_medium_fails_at_four_point_five_nm() -> None:
    public = _public(aircraft=_aircraft(wake="M"))
    slot = ArrivalSlot(
        slot_time=1000,
        runway="17C",
        leader_type="B763",
        leader_wake=WakeCat.H,
        gap_nm=4.5,
        taken=False,
    )
    private = AtcPrivate(aar_normal=60, aar_reduced=40, slots=[slot], notam_text=[])
    option = _option(arrival_slot=1000)
    checks = check_wake(public, private, {}, option, CheckIdGen("W"))
    assert len(checks) == 1
    assert checks[0].constraint_id == "ATC-WAKE-01"
    assert checks[0].passed is False
    assert checks[0].value == 4.5
    assert checks[0].limit == 5

    ok_slot = slot.model_copy(update={"gap_nm": 5.0})
    ok_private = AtcPrivate(aar_normal=60, aar_reduced=40, slots=[ok_slot], notam_text=[])
    assert check_wake(public, ok_private, {}, option, CheckIdGen("W"))[0].passed is True


# --------------------------------------------------------------------------- fuel


def _pilot_private() -> PilotPrivate:
    return PilotPrivate(
        fuel_on_board_kg=5300.0,
        fuel_to_destination_kg=2400.0,
        alternate="OKC",
        alternate_distance_nm=100.0,
        fuel_to_alternate_kg=400.0,
        reserve_45_kg=1800.0,
        max_extra_fuel_kg=0.0,
        cruise_levels=[340],
        turbulence_text=[],
        truth_turbulence={"FL340": "NONE"},
        connections=[],
        pax_notes=[],
        crew_duty_remaining_min=180,
    )


def test_fuel_boundary_pass_and_fail() -> None:
    public = _public(mode=Mode.AIRBORNE, expected_eta=1000, decision_time=940)
    private = _pilot_private()

    pass_option = _option(arrival_slot=1010, holding_min=10)
    passing = check_fuel(public, private, {}, pass_option, CheckIdGen("F"))
    assert all(c.passed for c in passing)
    assert passing[0].constraint_id == "PLT-FUEL-01"
    assert passing[1].constraint_id == "PLT-FUEL-02"
    assert passing[1].limit == 20.0

    fail_option = _option(arrival_slot=1025, holding_min=25)
    failing = check_fuel(public, private, {}, fail_option, CheckIdGen("F"))
    assert failing[0].passed is False
    assert failing[1].passed is False


# --------------------------------------------------------------------------- gate


def _ground_private(**overrides: Any) -> GroundPrivate:
    data: dict[str, Any] = {
        "gates": [
            Gate(
                gate_id="B1",
                max_size=SizeClass.NARROW,
                carrier="AA",
                occupied=[(1000, 1050)],
                taxi_route=["A", "B"],
            )
        ],
        "current_gate": "B1",
        "shifts": [CrewShift(shift_id="DAY", start=0, end=1200, hard_limit_end=1320, overtime_eur_per_min=6)],
        "min_turnaround_min": 40,
        "next_leg": None,
        "defect": None,
        "spare_aircraft_available": False,
        "gate_change_eur": 400.0,
    }
    data.update(overrides)
    return GroundPrivate(**data)


def test_gate_overlap_with_buffer() -> None:
    public = _public(mode=Mode.GROUND, flight=_flight(airline="AA"))
    private = _ground_private()

    conflict = check_gates(
        public, private, {}, _option(mode=Mode.GROUND, arrival_slot=1055), CheckIdGen("G")
    )
    gate02 = next(c for c in conflict if c.constraint_id == "GND-GATE-02")
    assert gate02.passed is False

    clear = check_gates(
        public, private, {}, _option(mode=Mode.GROUND, arrival_slot=1070), CheckIdGen("G")
    )
    gate02 = next(c for c in clear if c.constraint_id == "GND-GATE-02")
    assert gate02.passed is True


# --------------------------------------------------------------------------- MEL


def test_mel_deferrable_and_non_deferrable() -> None:
    flight = _flight(scheduled_departure=600, late_aircraft_delay=30)
    public = _public(mode=Mode.GROUND, flight=flight)
    defect = DefectReport(
        defect_id="DEF-HYD-02",
        text="hyd leak",
        truth_ata_chapter=29,
        truth_mel_item="29-11-01",
        truth_deferrable=False,
        truth_repair_min=45,
    )
    private = _ground_private(defect=defect)
    facts = {
        "defect": _fact(
            "defect",
            {
                "ata_chapter": 29,
                "mel_item": "29-11-01",
                "mel_category": None,
                "deferrable": False,
                "repair_min": 45,
            },
        )
    }

    early = _option(mode=Mode.GROUND, departure_slot=640, arrival_slot=800)
    assert check_mel(public, private, facts, early, CheckIdGen("M"))[0].passed is False

    repaired = _option(mode=Mode.GROUND, departure_slot=680, arrival_slot=840)
    assert check_mel(public, private, facts, repaired, CheckIdGen("M"))[0].passed is True

    deferrable_facts = {
        "defect": _fact("defect", {**facts["defect"].value, "deferrable": True})
    }
    assert check_mel(public, private, deferrable_facts, early, CheckIdGen("M"))[0].passed is True


# --------------------------------------------------------------------------- turnaround


def test_turnaround_keep_delay_and_swap() -> None:
    public = _public(mode=Mode.GROUND)
    leg = NextLeg(flight_number=99, destination="ORD", scheduled_departure=700, real=True)
    private = _ground_private(next_leg=leg, min_turnaround_min=40)

    keep = _option(mode=Mode.GROUND, arrival_slot=680, next_leg_action="KEEP")
    assert check_turnaround(public, private, {}, keep, CheckIdGen("T"))[0].passed is False

    delay = _option(
        mode=Mode.GROUND,
        arrival_slot=680,
        next_leg_action="DELAY",
        next_leg_delay_min=20,
    )
    assert check_turnaround(public, private, {}, delay, CheckIdGen("T"))[0].passed is True

    swap = _option(mode=Mode.GROUND, arrival_slot=680, next_leg_action="SWAP_AIRCRAFT")
    assert check_turnaround(public, private, {}, swap, CheckIdGen("T"))[0].passed is False

    spare = _ground_private(next_leg=leg, min_turnaround_min=40, spare_aircraft_available=True)
    assert check_turnaround(public, spare, {}, swap, CheckIdGen("T"))[0].passed is True


# --------------------------------------------------------------------------- conservative defaults


def test_conservative_perception_is_failsafe() -> None:
    public = _public(mode=Mode.GROUND)
    defect = DefectReport(
        defect_id="DEF-PACK-01",
        text="pack trip",
        truth_ata_chapter=21,
        truth_mel_item="21-51-01",
        truth_mel_category="C",
        truth_deferrable=True,
        truth_repair_min=10,
    )
    ground = _ground_private(defect=defect)
    facts = conservative_facts(AgentRole.GROUND, public, ground)
    value = facts[0].value
    assert value["deferrable"] is False
    assert value["repair_min"] >= 60
    assert facts[0].conservative_default is True
    assert facts[0].source == "DEFAULT"

    pilot = _pilot_private().model_copy(
        update={"truth_turbulence": {"FL340": "SEVERE", "FL360": "NONE"}}
    )
    turbulence = conservative_facts(AgentRole.PILOT, public, pilot)[0].value
    assert turbulence["FL340"] == "SEVERE"
    assert turbulence["FL360"] == "MODERATE"

    atc = AtcPrivate(
        aar_normal=60,
        aar_reduced=40,
        slots=[],
        notam_text=["!DFW 10/123 DFW TWY K CLSD 1510301400-1510302000"],
        truth_closed_taxiways=["K"],
    )
    closed = conservative_facts(AgentRole.ATC, public, atc)[0].value
    assert "K" in closed


def test_stub_perception_reads_truth() -> None:
    public = _public(mode=Mode.GROUND)
    defect = DefectReport(
        defect_id="DEF-PACK-01",
        text="pack trip",
        truth_ata_chapter=21,
        truth_mel_item="21-51-01",
        truth_mel_category="C",
        truth_deferrable=True,
        truth_repair_min=10,
    )
    ground = _ground_private(defect=defect)
    facts = stub_perceive(AgentRole.GROUND, public, ground)
    assert facts[0].key == "defect"
    assert facts[0].value["deferrable"] is True
    assert facts[0].citation is not None
