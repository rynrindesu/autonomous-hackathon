"""Dataset loader: typed flights/airports, Parquet cache and HHMM parsing.

The 2015 DOT subset stores clock times as HHMM integers in *local* time.  Leading
zeros are lost (``648`` means 06:48) and ``2400`` appears for midnight.  All
public timestamps in Triad are ``int`` minutes since local midnight; values
``>= 1440`` mean "next day".
"""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from triad.config import CACHE_DIR, DATASETS_DIR
from triad.schemas import FlightRecord

# Strings must stay strings: a handful of airport codes are numeric-looking.
_STR_COLS = ["AIRLINE", "TAIL_NUMBER", "ORIGIN_AIRPORT", "DESTINATION_AIRPORT"]

_REQUIRED_INT = [
    "YEAR",
    "MONTH",
    "DAY",
    "DAY_OF_WEEK",
    "FLIGHT_NUMBER",
    "SCHEDULED_DEPARTURE",
    "DISTANCE",
    "SCHEDULED_ARRIVAL",
]

_OPTIONAL_INT = [
    "DEPARTURE_TIME",
    "DEPARTURE_DELAY",
    "TAXI_OUT",
    "SCHEDULED_TIME",
    "ELAPSED_TIME",
    "AIR_TIME",
    "ARRIVAL_TIME",
    "ARRIVAL_DELAY",
]

# The five cause columns: missing -> 0 (a missing cause means "no contribution").
_DELAY_COLS = [
    "AIR_SYSTEM_DELAY",
    "SECURITY_DELAY",
    "AIRLINE_DELAY",
    "LATE_AIRCRAFT_DELAY",
    "WEATHER_DELAY",
]

_SENTINEL = -999_999


def hhmm_to_minutes(value: Any) -> int | None:
    """Convert an HHMM integer (e.g. 648, 2400) to minutes of day.

    Missing values (``None``/NaN) return ``None``.  ``2400`` naturally maps to
    1440 with the same formula.
    """

    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        iv = int(value)
    except (TypeError, ValueError):
        return None
    if iv == _SENTINEL:
        return None
    hours, minutes = divmod(iv, 100)
    return hours * 60 + minutes


def _vec_hhmm(values: Any) -> "pd.Series":
    """Vectorised HHMM -> minutes (used only for cached frame construction)."""

    s = pd.to_numeric(values, errors="coerce").fillna(0).astype("int64")
    return (s // 100) * 60 + (s % 100)


def _parquet_path() -> Path:
    return CACHE_DIR / "flights.parquet"


def _build_flights() -> pd.DataFrame:
    csv_path = DATASETS_DIR / "flights.csv"
    raw = pd.read_csv(csv_path, dtype={c: str for c in _STR_COLS})

    for col in _REQUIRED_INT:
        raw[col] = pd.to_numeric(raw[col], errors="coerce").fillna(0).astype("int64")
    for col in _OPTIONAL_INT:
        raw[col] = (
            pd.to_numeric(raw[col], errors="coerce").fillna(_SENTINEL).astype("int64")
        )
    for col in _DELAY_COLS:
        raw[col] = pd.to_numeric(raw[col], errors="coerce").fillna(0).astype("int64")

    for col in _STR_COLS:
        raw[col] = raw[col].fillna("").astype(str)

    if "CANCELLATION_REASON" in raw.columns:
        raw["CANCELLATION_REASON"] = raw["CANCELLATION_REASON"].fillna("").astype(str)

    # row_index is the 0-based data row position (the identity key used by the CLI).
    raw = raw.reset_index(drop=True)
    raw.insert(0, "row_index", range(len(raw)))
    return raw


@lru_cache(maxsize=1)
def load_flights() -> pd.DataFrame:
    """Read ``datasets/flights.csv`` once, cached as Parquet in ``.cache/``."""

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    parquet = _parquet_path()
    csv_path = DATASETS_DIR / "flights.csv"

    df: pd.DataFrame | None = None
    if parquet.exists() and parquet.stat().st_mtime >= csv_path.stat().st_mtime:
        try:
            df = pd.read_parquet(parquet)
        except Exception:
            df = None

    if df is None:
        df = _build_flights()
        try:
            df.to_parquet(parquet, index=False)
        except Exception:
            pass  # a read-only/odd cache directory must not break the run

    if "row_index" not in df.columns:
        df = df.reset_index(drop=True)
        df.insert(0, "row_index", range(len(df)))
    else:
        df = df.set_index("row_index", drop=False)
    return df


@lru_cache(maxsize=1)
def load_airports() -> pd.DataFrame:
    """Airport reference table (IATA code, name, city, lat/lon)."""

    return pd.read_csv(
        DATASETS_DIR / "airports.csv",
        dtype={"IATA_CODE": str, "STATE": str, "COUNTRY": str},
    )


@lru_cache(maxsize=1)
def airport_coords() -> dict[str, tuple[float, float]]:
    df = load_airports()
    return {
        str(code): (float(lat), float(lon))
        for code, lat, lon in zip(df["IATA_CODE"], df["LATITUDE"], df["LONGITUDE"])
    }


def _opt(value: int) -> int | None:
    value = int(value)
    return None if value == _SENTINEL else value


def get_record(row_index: int) -> FlightRecord:
    """Parse one flights.csv row into a :class:`FlightRecord`."""

    df = load_flights()
    try:
        row = df.loc[int(row_index)]
    except KeyError as exc:  # pragma: no cover - defensive
        raise IndexError(f"unknown flight row_index {row_index}") from exc

    sched_dep = hhmm_to_minutes(int(row["SCHEDULED_DEPARTURE"])) or 0
    sched_arr = hhmm_to_minutes(int(row["SCHEDULED_ARRIVAL"])) or 0
    if sched_arr < sched_dep:  # overnight arrival
        sched_arr += 1440

    return FlightRecord(
        row_index=int(row["row_index"]),
        year=int(row["YEAR"]),
        month=int(row["MONTH"]),
        day=int(row["DAY"]),
        day_of_week=int(row["DAY_OF_WEEK"]),
        airline=str(row["AIRLINE"]),
        flight_number=int(row["FLIGHT_NUMBER"]),
        tail_number=str(row["TAIL_NUMBER"]),
        origin=str(row["ORIGIN_AIRPORT"]),
        destination=str(row["DESTINATION_AIRPORT"]),
        scheduled_departure=sched_dep,
        departure_time=hhmm_to_minutes(_opt(row["DEPARTURE_TIME"])),
        departure_delay=_opt(row["DEPARTURE_DELAY"]),
        taxi_out=_opt(row["TAXI_OUT"]),
        scheduled_time=_opt(row["SCHEDULED_TIME"]),
        elapsed_time=_opt(row["ELAPSED_TIME"]),
        air_time=_opt(row["AIR_TIME"]),
        distance=int(row["DISTANCE"]),
        scheduled_arrival=sched_arr,
        arrival_time=hhmm_to_minutes(_opt(row["ARRIVAL_TIME"])),
        arrival_delay=_opt(row["ARRIVAL_DELAY"]),
        air_system_delay=int(row["AIR_SYSTEM_DELAY"]),
        security_delay=int(row["SECURITY_DELAY"]),
        airline_delay=int(row["AIRLINE_DELAY"]),
        late_aircraft_delay=int(row["LATE_AIRCRAFT_DELAY"]),
        weather_delay=int(row["WEATHER_DELAY"]),
    )


def row_count() -> int:
    return len(load_flights())
