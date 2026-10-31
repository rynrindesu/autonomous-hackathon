"""Operational limits from the organisers' Challenge #2 workbook.

``config/operational_limits.yaml`` is generated from
``challenge-2-operational-constraints.xlsx`` by
``scripts/import_constraints_workbook.py`` (the xlsx SHA-256 is recorded in its
header).  This module is the single runtime source of every airport capacity,
wake-separation, fuel and crew limit.  Deliberate departures from the workbook
are listed in ``config/limits_deviations.yaml`` and exposed by
:func:`limits_info` (surfaced in the SETUP log payload).

Workbook wake classes map to ICAO categories: Super=J, Heavy=H, Large=M, Small=L.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import yaml

from triad.config import CONFIG_DIR
from triad.schemas import SizeClass, WakeCat

LIMITS_FILE = CONFIG_DIR / "operational_limits.yaml"
DEVIATIONS_FILE = CONFIG_DIR / "limits_deviations.yaml"

SRC_AIRPORT = "challenge-2 workbook: airport_capacity"
SRC_WAKE = "challenge-2 workbook: wake_separation"
SRC_FUEL_CREW = "challenge-2 workbook: fuel_and_crew"


@dataclass(frozen=True)
class AirportLimits:
    iata: str
    airport: str
    city: str
    state: str
    size_class: str
    active_runways: int
    gates: int
    max_runway_ops_per_hour: int
    min_turnaround_min: int
    spare_gates_at_any_time: int
    delayed_departures_in_flights_csv: int


@dataclass(frozen=True)
class FuelCrewLimits:
    final_reserve_holding_min: float  # never plan below this
    contingency_frac: float  # of trip fuel
    holding_burn_narrow_kg_h: float  # A320/737 class (we also apply it to REGIONAL jets)
    holding_burn_wide_kg_h: float  # A330/777 class (all WIDE types)
    spare_fuel_holding_min: float  # assumed spare on arrival, ON TOP of the final reserve
    flight_crew_max_duty_min: int  # from report time
    ground_shift_min: int
    ground_overtime_multiplier: float
    gate_change_notice_min: int

    def holding_burn_kg_min(self, size: SizeClass | str) -> float:
        """Workbook holding burn per minute: WIDE -> widebody, else narrowbody."""

        wide = SizeClass(size) == SizeClass.WIDE
        per_hour = self.holding_burn_wide_kg_h if wide else self.holding_burn_narrow_kg_h
        return per_hour / 60.0


def _sha256(path: Any) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def _raw() -> dict[str, Any]:
    with open(LIMITS_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache(maxsize=1)
def _airports() -> dict[str, AirportLimits]:
    out: dict[str, AirportLimits] = {}
    for code, row in _raw()["airport_capacity"]["airports"].items():
        out[str(code)] = AirportLimits(
            iata=str(code),
            airport=str(row["AIRPORT"]),
            city=str(row["CITY"]),
            state=str(row["STATE"]),
            size_class=str(row["size_class"]),
            active_runways=int(row["active_runways"]),
            gates=int(row["gates"]),
            max_runway_ops_per_hour=int(row["max_runway_ops_per_hour"]),
            min_turnaround_min=int(row["min_turnaround_min"]),
            spare_gates_at_any_time=int(row["spare_gates_at_any_time"]),
            delayed_departures_in_flights_csv=int(row["delayed_departures_in_flights_csv"]),
        )
    return out


def airport_codes() -> list[str]:
    return list(_airports())


def airport_limits(iata: str) -> AirportLimits:
    """Workbook ``airport_capacity`` row.  Raises ``KeyError`` for unknown airports
    (every ORIGIN/DESTINATION in flights.csv is covered by the workbook)."""

    try:
        return _airports()[str(iata)]
    except KeyError:
        raise KeyError(
            f"airport {iata!r} not in the challenge-2 workbook airport_capacity sheet"
        ) from None


@lru_cache(maxsize=1)
def wake_table() -> dict[tuple[str, str], float]:
    """(leader, follower) ICAO wake categories -> minimum separation in NM."""

    return {
        (str(p["leader_cat"]), str(p["follower_cat"])): float(p["min_separation_nm"])
        for p in _raw()["wake_separation"]["pairs"]
    }


def wake_default_nm() -> float:
    return float(_raw()["wake_separation"]["any_other_pair"]["min_separation_nm"])


def wake_min_nm(leader: WakeCat | str, follower: WakeCat | str) -> float:
    """Workbook wake minimum for the pair; "any other pair" (3 NM) otherwise."""

    key = (WakeCat(leader).value, WakeCat(follower).value)
    return wake_table().get(key, wake_default_nm())


@lru_cache(maxsize=1)
def fuel_crew() -> FuelCrewLimits:
    fc = _raw()["fuel_and_crew"]
    return FuelCrewLimits(
        final_reserve_holding_min=float(fc["final_reserve"]["holding_min"]),
        contingency_frac=float(fc["contingency"]["fraction_of_trip_fuel"]),
        holding_burn_narrow_kg_h=float(fc["holding_burn_narrowbody"]["kg_per_hour"]),
        holding_burn_wide_kg_h=float(fc["holding_burn_widebody"]["kg_per_hour"]),
        spare_fuel_holding_min=float(fc["spare_fuel_on_arrival"]["holding_min"]),
        flight_crew_max_duty_min=int(fc["flight_crew_max_duty"]["minutes"]),
        ground_shift_min=int(fc["ground_crew_shift"]["minutes"]),
        ground_overtime_multiplier=float(fc["ground_crew_shift"]["overtime_multiplier"]),
        gate_change_notice_min=int(fc["gate_change_notice"]["min_before_arrival_min"]),
    )


def rules_of_play() -> dict[str, str]:
    return dict(_raw().get("rules_of_play", {}))


@lru_cache(maxsize=1)
def _deviations() -> tuple[dict[str, Any], ...]:
    if not DEVIATIONS_FILE.exists():
        return ()
    with open(DEVIATIONS_FILE, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return tuple(dict(d) for d in (data.get("deviations") or []))


def deviations() -> list[dict[str, Any]]:
    """Every deliberate deviation: {limit, workbook_value, our_value, reason, citation}."""

    return [dict(d) for d in _deviations()]


@lru_cache(maxsize=1)
def _info() -> tuple[str, str, str]:
    source = _raw().get("source", {})
    return (
        str(source.get("workbook", "challenge-2-operational-constraints.xlsx")),
        str(source.get("workbook_sha256", "")),
        _sha256(LIMITS_FILE),
    )


def limits_info() -> dict[str, Any]:
    """Provenance for the run log: workbook file + hashes + deviations list."""

    workbook, workbook_sha, yaml_sha = _info()
    return {
        "workbook": workbook,
        "workbook_sha256": workbook_sha,
        "limits_yaml_sha256": yaml_sha,
        "deviations": deviations(),
    }


__all__ = [
    "AirportLimits",
    "FuelCrewLimits",
    "SRC_AIRPORT",
    "SRC_FUEL_CREW",
    "SRC_WAKE",
    "airport_codes",
    "airport_limits",
    "deviations",
    "fuel_crew",
    "limits_info",
    "rules_of_play",
    "wake_min_nm",
    "wake_table",
]
