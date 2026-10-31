"""Loader / scenario / determinism tests."""

from __future__ import annotations

import math

from triad.data.enrich import build_event
from triad.data.loader import get_record, hhmm_to_minutes
from triad.data.scenario import disruption_type_for, is_candidate, mode_for
from triad.schemas import DisruptionType, Mode


def test_hhmm_parsing_edge_cases() -> None:
    assert hhmm_to_minutes(0) == 0
    assert hhmm_to_minutes(5) == 5
    assert hhmm_to_minutes(648) == 6 * 60 + 48
    assert hhmm_to_minutes(2359) == 23 * 60 + 59
    assert hhmm_to_minutes(2400) == 1440
    assert hhmm_to_minutes(None) is None
    assert hhmm_to_minutes(float("nan")) is None


def test_get_record_types_and_overnight_adjustment() -> None:
    rec = get_record(0)
    assert rec.row_index == 0
    assert rec.origin == "DFW"
    assert rec.destination == "HNL"
    assert rec.airline == "AA"
    assert rec.scheduled_departure == 13 * 60 + 5
    assert rec.scheduled_arrival == 17 * 60 + 40
    assert rec.weather_delay == 0
    assert rec.late_aircraft_delay == 92

    # HNL->DFW lands the next local day (0510 < 1745).
    overnight = get_record(1)
    assert overnight.scheduled_arrival == 1440 + 5 * 60 + 10


def test_scenario_filter_and_mode() -> None:
    rec = get_record(0)
    assert is_candidate(rec)
    assert mode_for(rec) == Mode.GROUND
    assert disruption_type_for(rec) == DisruptionType.LATE_AIRCRAFT

    class Fake:
        weather_delay = 16
        late_aircraft_delay = 0

    assert is_candidate(Fake())
    assert mode_for(Fake()) == Mode.AIRBORNE
    assert disruption_type_for(Fake()) == DisruptionType.WEATHER


def test_build_event_is_deterministic() -> None:
    rec = get_record(0)
    first = build_event(rec, seed=7).model_dump_json()
    second = build_event(rec, seed=7).model_dump_json()
    assert first == second
    assert math.isfinite(len(first))

    other_seed = build_event(rec, seed=8).model_dump_json()
    assert other_seed != first


def test_build_event_forced_defect_only_ground() -> None:
    ground = build_event(get_record(0), seed=0, defect_id="DEF-HYD-02")
    assert ground.public.mode == Mode.GROUND
    assert ground.ground.defect is not None
    assert ground.ground.defect.defect_id == "DEF-HYD-02"
    assert ground.ground.defect.truth_deferrable is False
