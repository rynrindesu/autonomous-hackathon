"""Candidate filtering and decision-mode assignment for DOT flight rows."""

from __future__ import annotations

from triad.schemas import DisruptionType, FlightRecord, Mode


def is_candidate(rec: FlightRecord) -> bool:
    """The brief's filter: weather delay > 15 or late-aircraft delay > 20 minutes."""

    return rec.weather_delay > 15 or rec.late_aircraft_delay > 20


def mode_for(rec: FlightRecord) -> Mode:
    """Weather-driven disruption -> already airborne; otherwise pre-departure."""

    return Mode.AIRBORNE if rec.weather_delay > 15 else Mode.GROUND


def disruption_type_for(rec: FlightRecord) -> DisruptionType:
    return (
        DisruptionType.WEATHER
        if rec.weather_delay > 15
        else DisruptionType.LATE_AIRCRAFT
    )
