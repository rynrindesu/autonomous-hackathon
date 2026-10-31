"""Challenge #2 workbook limits: import round-trip, lookups and their use in the world/checks."""

from __future__ import annotations

import hashlib
from collections import Counter

import pytest
from fakes import make_disruption_event, make_option

from triad.agents.base import CheckIdGen
from triad.agents.scoring import cost_eur
from triad.config import CONFIG_DIR, ROOT
from triad.constraints.crew import check_crew
from triad.constraints.fuel import check_fuel
from triad.constraints.gate import check_gates
from triad.constraints.runway import check_runway
from triad.constraints.wake import check_wake
from triad.constraints.weather import check_duty
from triad.data import limits
from triad.data.enrich import build_event
from triad.data.loader import get_record, load_flights
from triad.schemas import AgentRole, ArrivalSlot, AtcPrivate, CrewShift, Gate, SizeClass, WakeCat

XLSX = ROOT / "challenge-2-operational-constraints.xlsx"
AIRBORNE_ROW = 293614  # ORD -> LAX, weather (demo scenario_a)
GROUND_ROW = 18896  # MCO -> IAH, late aircraft (demo scenario_b)


# --------------------------------------------------------------------------- workbook import


def test_yaml_matches_xlsx_for_ord_atl_and_a_small_airport() -> None:
    openpyxl = pytest.importorskip("openpyxl")
    if not XLSX.exists():
        pytest.skip("workbook not present")

    info = limits.limits_info()
    assert info["workbook"] == XLSX.name
    assert info["workbook_sha256"] == hashlib.sha256(XLSX.read_bytes()).hexdigest()

    wb = openpyxl.load_workbook(XLSX, data_only=True, read_only=True)
    rows = list(wb["airport_capacity"].iter_rows(min_row=3, values_only=True))
    header = [str(h) for h in rows[0]]
    by_code = {str(r[0]): dict(zip(header, r)) for r in rows[1:] if r[0]}
    for code in ("ORD", "ATL", "ITH"):
        xl = by_code[code]
        ours = limits.airport_limits(code)
        assert ours.airport == xl["AIRPORT"]
        assert ours.size_class == xl["size_class"]
        assert ours.active_runways == xl["active_runways"]
        assert ours.gates == xl["gates"]
        assert ours.max_runway_ops_per_hour == xl["max_runway_ops_per_hour"]
        assert ours.min_turnaround_min == xl["min_turnaround_min"]
        assert ours.spare_gates_at_any_time == xl["spare_gates_at_any_time"]
        assert ours.delayed_departures_in_flights_csv == xl["delayed_departures_in_flights_csv"]
    assert limits.airport_limits("ITH").size_class == "Non-hub"
    assert len(limits.airport_codes()) == len(by_code)

    wake_rows = list(wb["wake_separation"].iter_rows(min_row=4, values_only=True))
    cls = {"Super": "J", "Heavy": "H", "Large": "M", "Small": "L"}
    for leader, follower, nm, _secs in wake_rows:
        if leader is None:
            continue
        if str(leader).startswith("Any other"):
            assert limits.wake_default_nm() == nm
            continue
        assert limits.wake_min_nm(cls[leader.split()[0]], cls[follower.split()[0]]) == nm

    fc_text = {r[0]: r[1] for r in wb["fuel_and_crew"].iter_rows(min_row=2, values_only=True) if r[0]}
    assert fc_text["Final fuel reserve"].startswith("30 minutes")
    assert fc_text["Holding fuel burn (narrowbody)"].startswith("2,400")
    assert fc_text["Holding fuel burn (widebody)"].startswith("6,500")
    wb.close()


def test_limits_info_shape_and_hashes() -> None:
    info = limits.limits_info()
    assert set(info) == {"workbook", "workbook_sha256", "limits_yaml_sha256", "deviations"}
    assert len(info["workbook_sha256"]) == 64
    expected = hashlib.sha256((CONFIG_DIR / "operational_limits.yaml").read_bytes()).hexdigest()
    assert info["limits_yaml_sha256"] == expected
    assert isinstance(info["deviations"], list)
    for dev in info["deviations"]:
        assert {"limit", "workbook_value", "our_value", "reason", "citation"} <= set(dev)


def test_every_dataset_airport_has_workbook_limits() -> None:
    df = load_flights()
    codes = set(df["ORIGIN_AIRPORT"].unique()) | set(df["DESTINATION_AIRPORT"].unique())
    known = set(limits.airport_codes())
    assert codes <= known, sorted(codes - known)[:10]
    for code in codes:
        assert limits.airport_limits(code).gates > 0
    with pytest.raises(KeyError):
        limits.airport_limits("ZZZ")


# --------------------------------------------------------------------------- wake


def test_wake_table_values() -> None:
    w = limits.wake_min_nm
    assert w("J", "J") == 3  # not listed -> any other pair
    assert (w("J", "H"), w("J", "M"), w("J", "L")) == (6, 7, 8)
    assert (w("H", "H"), w("H", "M"), w("H", "L")) == (4, 5, 6)
    assert w("M", "L") == 4
    assert w("M", "M") == 3 and w("L", "J") == 3 and w(WakeCat.H, WakeCat.J) == 3


def test_wake_check_uses_workbook_minimum() -> None:
    event = make_disruption_event()
    public = event.public  # follower is a B738 (M)
    option = make_option("OPT-01", arrival_slot=600, runway="17C")

    def gap_check(leader: WakeCat, gap: float):
        slot = ArrivalSlot(slot_time=600, runway="17C", leader_type="X", leader_wake=leader, gap_nm=gap)
        atc = event.atc.model_copy(update={"slots": [slot]})
        return check_wake(public, atc, {}, option, CheckIdGen("W"))[0]

    assert gap_check(WakeCat.M, 3.0).passed is True  # M -> M: any other pair 3 NM
    heavy = gap_check(WakeCat.H, 4.9)
    assert heavy.passed is False and heavy.limit == 5.0
    assert heavy.source == "challenge-2 workbook: wake_separation"


# --------------------------------------------------------------------------- fuel


def test_fuel_crew_values() -> None:
    fc = limits.fuel_crew()
    assert fc.final_reserve_holding_min == 30
    assert fc.spare_fuel_holding_min == 45
    assert fc.contingency_frac == pytest.approx(0.05)
    assert fc.holding_burn_kg_min(SizeClass.NARROW) == pytest.approx(40.0)
    assert fc.holding_burn_kg_min(SizeClass.REGIONAL) == pytest.approx(40.0)
    assert fc.holding_burn_kg_min(SizeClass.WIDE) == pytest.approx(6500 / 60)
    assert fc.flight_crew_max_duty_min == 780
    assert fc.ground_shift_min == 480 and fc.ground_overtime_multiplier == 1.5
    assert fc.gate_change_notice_min == 20


def test_built_event_fuel_is_reserve_plus_45_min_spare() -> None:
    event = build_event(get_record(AIRBORNE_ROW), seed=0)
    hold = event.public.aircraft.holding_burn_kg_min
    assert hold == pytest.approx(40.0)  # narrowbody
    p = event.pilot
    assert p.final_reserve_kg == pytest.approx(30 * hold, abs=0.1)
    assert p.contingency_kg == pytest.approx(0.05 * p.fuel_to_destination_kg, abs=0.1)
    spare = p.fuel_on_board_kg - p.fuel_to_destination_kg - p.contingency_kg - p.final_reserve_kg
    assert spare == pytest.approx(45 * hold, abs=0.5)

    # PLT-FUEL-02: ~45 min (+ contingency) of holding fits; just beyond does not.
    max_hold = 45 + p.contingency_kg / hold
    ok = make_option("OPT-01", arrival_slot=event.public.expected_eta + 45, holding_min=45)
    checks = check_fuel(event.public, p, {}, ok, CheckIdGen("F"))
    assert all(c.passed for c in checks)
    assert checks[0].limit == pytest.approx(p.final_reserve_kg)
    assert checks[1].limit == pytest.approx(max_hold, abs=0.1)
    too_long = int(max_hold) + 1
    bad = make_option("OPT-02", arrival_slot=event.public.expected_eta + too_long, holding_min=too_long)
    bad_checks = check_fuel(event.public, p, {}, bad, CheckIdGen("F"))
    assert not bad_checks[0].passed and not bad_checks[1].passed
    assert {c.source for c in bad_checks} == {"challenge-2 workbook: fuel_and_crew"}


def test_widebody_uses_workbook_widebody_burn() -> None:
    event = build_event(get_record(0), seed=0)  # DFW -> HNL long haul
    assert event.public.aircraft.size_class == SizeClass.WIDE
    assert event.public.aircraft.holding_burn_kg_min == pytest.approx(6500 / 60, abs=1e-3)
    assert event.pilot.final_reserve_kg == pytest.approx(3250.0, abs=0.1)


# --------------------------------------------------------------------------- flight crew duty


def test_duty_is_13_hours_from_report() -> None:
    for row in (AIRBORNE_ROW, GROUND_ROW):
        event = build_event(get_record(row), seed=0)
        p = event.pilot
        assert p.crew_max_duty_min == 780
        assert p.crew_report_time is not None
        assert p.crew_duty_remaining_min == p.crew_report_time + 780 - event.public.decision_time

    event = make_disruption_event()  # report 60 -> duty ends 840
    at_limit = make_option("OPT-01", arrival_slot=840)
    over = make_option("OPT-02", arrival_slot=845)
    ok = check_duty(event.public, event.pilot, {}, at_limit, CheckIdGen("D"))[0]
    bad = check_duty(event.public, event.pilot, {}, over, CheckIdGen("D"))[0]
    assert ok.passed and ok.value == 780 and ok.limit == 780
    assert not bad.passed and bad.value == 785
    assert bad.source == "challenge-2 workbook: fuel_and_crew"


# --------------------------------------------------------------------------- ground crew overtime


def test_overtime_costs_1_5x_and_never_vetoes() -> None:
    event = make_disruption_event()
    shift = CrewShift(
        shift_id="S", start=240, end=720, hard_limit_end=720,
        overtime_eur_per_min=6.0, base_eur_per_min=4.0, overtime_multiplier=1.5,
    )
    ground = event.ground.model_copy(update={"shifts": [shift], "min_turnaround_min": 45, "next_leg": None})
    # arrival 705 + 45 min turnaround = 750 -> 30 min beyond the 720 shift end
    option = make_option("OPT-01", arrival_slot=705, gate=ground.current_gate)
    crew = check_crew(event.public, ground, {}, option, CheckIdGen("C"))[0]
    assert crew.constraint_id == "GND-CREW-01"
    assert crew.hard is False and crew.passed is True
    assert crew.value == 30
    costs = cost_eur(AgentRole.GROUND, event.public, ground, {}, option)
    assert costs["overtime"] == pytest.approx(30 * 4.0 * 1.5)

    # Even far beyond any former +120 min limit: still no hard failure.
    late = make_option("OPT-02", arrival_slot=715 + 200, gate=ground.current_gate)
    assert all(c.passed or not c.hard for c in check_crew(event.public, ground, {}, late, CheckIdGen("C")))


def test_built_event_shifts_and_gates_follow_workbook() -> None:
    event = build_event(get_record(AIRBORNE_ROW), seed=0)
    g = event.ground
    dest = limits.airport_limits(event.public.flight.destination)
    assert {s.end - s.start for s in g.shifts} == {480}
    assert all(s.overtime_eur_per_min == pytest.approx(s.base_eur_per_min * 1.5) for s in g.shifts)
    assert g.min_turnaround_min == dest.min_turnaround_min
    assert g.total_gates == dest.gates and len(g.gates) <= dest.gates
    assert g.spare_gates_at_any_time == dest.spare_gates_at_any_time
    assert g.gate_change_notice_min == 20

    eta = event.public.expected_eta
    lo, hi = eta - 10, eta + g.min_turnaround_min + 10
    free_others = [
        gate for gate in g.gates
        if gate.gate_id != g.current_gate and not any(lo < e and s < hi for s, e in gate.occupied)
    ]
    assert len(free_others) >= g.spare_gates_at_any_time


# --------------------------------------------------------------------------- gate change notice


def test_gate_change_notice_gnd_gate_04() -> None:
    event = make_disruption_event()  # decision 540, planned gate A1
    ground = event.ground.model_copy(
        update={"gates": [Gate(gate_id="A1", max_size=SizeClass.NARROW, carrier="AA"),
                          Gate(gate_id="B14", max_size=SizeClass.NARROW, carrier=None)]}
    )

    def gate04(gate: str, arrival: int):
        option = make_option("OPT-01", arrival_slot=arrival, gate=gate)
        checks = check_gates(event.public, ground, {}, option, CheckIdGen("G"))
        return next(c for c in checks if c.constraint_id == "GND-GATE-04")

    short = gate04("B14", 555)
    assert short.passed is False and short.hard is True
    assert short.value == 15 and short.limit == 20
    assert short.source == "challenge-2 workbook: fuel_and_crew"
    assert gate04("B14", 560).passed is True
    assert gate04("A1", 545).passed is True  # no change, no notice needed


# --------------------------------------------------------------------------- runway hourly capacity


def _atc(slots: list[ArrivalSlot], cap: int) -> AtcPrivate:
    return AtcPrivate(aar_normal=cap, aar_reduced=cap, max_runway_ops_per_hour=2 * cap,
                      active_runways=2, slots=slots, notam_text=[])


def test_runway_hourly_cap_atc_rwy_01() -> None:
    event = make_disruption_event()
    taken = [ArrivalSlot(slot_time=t, runway="17C", gap_nm=6.0, taken=True) for t in (600, 605, 610)]
    free = ArrivalSlot(slot_time=630, runway="17L", gap_nm=6.0)
    option = make_option("OPT-01", arrival_slot=630, runway="17L")

    full = check_runway(event.public, _atc(taken + [free], cap=3), {}, option, CheckIdGen("R"))[0]
    assert full.passed is False and full.value == 4 and full.limit == 3
    assert "at capacity" in full.detail
    assert full.source == "challenge-2 workbook: airport_capacity"

    room = check_runway(event.public, _atc(taken[:2] + [free], cap=3), {}, option, CheckIdGen("R"))[0]
    assert room.passed is True and room.value == 3 and room.limit == 3

    # A slot in the next clock hour is not affected by this hour's traffic.
    next_hour = ArrivalSlot(slot_time=660, runway="17L", gap_nm=6.0)
    later = make_option("OPT-02", arrival_slot=660, runway="17L")
    assert check_runway(event.public, _atc(taken + [next_hour], cap=3), {}, later, CheckIdGen("R"))[0].passed

    # A taken slot fails even below the hourly cap.
    busy = make_option("OPT-03", arrival_slot=600, runway="17C")
    assert not check_runway(event.public, _atc(taken[:1], cap=3), {}, busy, CheckIdGen("R"))[0].passed


def test_built_event_runways_and_slots_respect_capacity() -> None:
    for row in (AIRBORNE_ROW, GROUND_ROW):
        event = build_event(get_record(row), seed=0)
        dest = limits.airport_limits(event.public.flight.destination)
        atc = event.atc
        assert atc.max_runway_ops_per_hour == dest.max_runway_ops_per_hour
        assert atc.active_runways == dest.active_runways
        assert 1 <= len(event.public.destination_runways) <= dest.active_runways
        assert atc.aar_normal == round(0.5 * dest.max_runway_ops_per_hour)
        assert atc.aar_reduced <= atc.aar_normal

        per_hour: dict[int, list[ArrivalSlot]] = {}
        for slot in atc.slots:
            per_hour.setdefault(slot.slot_time // 60, []).append(slot)
        for hour, slots in per_hour.items():
            n_taken = Counter(s.taken for s in slots)[True]
            # Either the hour is at capacity (every slot taken) or below the reduced rate.
            assert n_taken == len(slots) or n_taken < atc.aar_reduced, (row, hour)
