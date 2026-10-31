"""Seeded scenario builder: real DOT data + labelled synthetic context.

Operational limits (runways, arrival capacity, gates, turnaround, fuel, flight
and ground crew) come from the organisers' Challenge #2 workbook via
``triad.data.limits`` (config/operational_limits.yaml).

Everything here is deterministic for ``(row, seed)``.  The same inputs always
produce an identical ``DisruptionEvent`` JSON.  Synthetic values are seeded from
a SHA-256 of the config salt, the row's run id and the caller's seed -- never
Python's process-randomised ``hash()``.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections import Counter
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd

from triad.config import load_yaml
from triad.constraints.runway import slot_grid_start, taxi_route_for
from triad.data.limits import AirportLimits, airport_limits, fuel_crew
from triad.data.loader import airport_coords, load_flights
from triad.data.scenario import disruption_type_for, mode_for
from triad.schemas import (
    AircraftInfo,
    ArrivalSlot,
    AtcPrivate,
    CandidateOption,
    Connection,
    CrewShift,
    DefectReport,
    DisruptionEvent,
    FlightRecord,
    Gate,
    GroundPrivate,
    Mode,
    NextLeg,
    PilotPrivate,
    PublicEvent,
    SizeClass,
    WakeCat,
)


# --------------------------------------------------------------------------- seeded RNG


def _rng(rec: FlightRecord, seed: int, stream: str = "") -> random.Random:
    """Seeded RNG; a named ``stream`` gives an independent sub-stream so that, e.g.,
    the traffic model can change without reshuffling every other synthetic draw."""

    salt = str(load_yaml("synthetic").get("seed_salt", "triad-v1"))
    payload = f"{salt}|{rec.run_id}|{seed}" + (f"|{stream}" if stream else "")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return random.Random(int(digest, 16))


def _date_key(rec: FlightRecord) -> int:
    return rec.year * 10000 + rec.month * 100 + rec.day


def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r_nm = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r_nm * math.asin(min(1.0, math.sqrt(a)))


# --------------------------------------------------------------------------- cached real-data indexes


@lru_cache(maxsize=1)
def _index() -> dict[str, Any]:
    """One-time vectorised indexes over the 358k-row flights table."""

    df = load_flights()
    n = len(df)

    year = df["YEAR"].to_numpy(dtype=np.int64)
    month = df["MONTH"].to_numpy(dtype=np.int64)
    day = df["DAY"].to_numpy(dtype=np.int64)
    date = year * 10000 + month * 100 + day

    sdep_raw = df["SCHEDULED_DEPARTURE"].to_numpy(dtype=np.int64)
    sarr_raw = df["SCHEDULED_ARRIVAL"].to_numpy(dtype=np.int64)
    sdep = (sdep_raw // 100) * 60 + sdep_raw % 100
    sarr = (sarr_raw // 100) * 60 + sarr_raw % 100
    sarr_adj = np.where(sarr < sdep, sarr + 1440, sarr)

    airline = df["AIRLINE"].to_numpy()
    tail = df["TAIL_NUMBER"].to_numpy()
    origin = df["ORIGIN_AIRPORT"].to_numpy()
    dest = df["DESTINATION_AIRPORT"].to_numpy()
    flight_number = df["FLIGHT_NUMBER"].to_numpy(dtype=np.int64)

    positions = pd.Series(np.arange(n))

    next_groups = positions.groupby([tail, date], sort=False).indices
    arr_groups = positions.groupby([airline, dest, date], sort=False).indices
    dep_groups = positions.groupby([airline, origin, date], sort=False).indices
    dest_groups = positions.groupby([dest, date], sort=False).indices

    # Carrier service counts (arrival + departure movements).
    out_counts = df.groupby(["AIRLINE", "DESTINATION_AIRPORT"]).size()
    in_counts = df.groupby(["AIRLINE", "ORIGIN_AIRPORT"]).size()
    out_counts.index.names = ["airline", "airport"]
    in_counts.index.names = ["airline", "airport"]
    combined = out_counts.add(in_counts, fill_value=0)

    carrier_counts: dict[tuple[str, str], int] = {
        (str(a), str(ap)): int(v) for (a, ap), v in combined.items()
    }
    airline_airports: dict[str, list[str]] = {}
    for (a, ap), _ in sorted(carrier_counts.items()):
        airline_airports.setdefault(a, []).append(ap)

    return {
        "date": date,
        "sdep": sdep,
        "sarr": sarr_adj,
        "tail": tail,
        "origin": origin,
        "dest": dest,
        "airline": airline,
        "flight_number": flight_number,
        "next_groups": next_groups,
        "arr_groups": arr_groups,
        "dep_groups": dep_groups,
        "dest_groups": dest_groups,
        "carrier_counts": carrier_counts,
        "airline_airports": airline_airports,
    }


# --------------------------------------------------------------------------- helpers


def _scheduled_time(rec: FlightRecord) -> int:
    if rec.scheduled_time is not None and rec.scheduled_time > 0:
        return int(rec.scheduled_time)
    diff = rec.scheduled_arrival - rec.scheduled_departure
    return diff if diff > 0 else max(1, diff + 1440)


def _aircraft(rec: FlightRecord, rng: random.Random, cfg: dict[str, Any]) -> AircraftInfo:
    specs = cfg["aircraft_types"]
    if rec.distance > int(cfg["long_haul"]["distance_mi"]):
        long_haul = cfg["long_haul"]["types"]
        code = long_haul.get(rec.airline, long_haul["default"])
    else:
        choices = cfg["airline_types"].get(rec.airline) or ["B738"]
        code = rng.choice(choices)
    spec = specs[code]
    size = SizeClass(spec["size"])
    return AircraftInfo(
        type_code=code,
        wake=WakeCat(spec["wake"]),
        size_class=size,
        seats=int(spec["seats"]),
        approach_speed_kt=int(spec["vapp_kt"]),
        cruise_burn_kg_min=float(spec["cruise_kg_min"]),
        # Workbook fuel_and_crew: narrowbody 2,400 kg/h (REGIONAL+NARROW), widebody 6,500 kg/h.
        holding_burn_kg_min=round(fuel_crew().holding_burn_kg_min(size), 4),
    )


def _active_runways(
    destination: str,
    rng: random.Random,
    runway_cfg: dict[str, Any],
    limits: AirportLimits,
) -> list[str]:
    """Active arrival runway ends: workbook ``active_runways`` (mixed-mode), bounded
    by the runways listed for the airport in config/runways.yaml."""

    pairs = runway_cfg.get("airports", {}).get(destination, runway_cfg.get("default", ["09/27"]))
    pairs = list(pairs)
    count = max(1, min(int(limits.active_runways), len(pairs)))
    selected = rng.sample(pairs, count)
    active: list[str] = []
    for pair in selected:
        ends = [e.strip() for e in str(pair).split("/") if e.strip()]
        if not ends:
            continue
        end = rng.choice(ends)
        if end not in active:
            active.append(end)
    return active or ["09"]


def _delays(mode: Mode, rec: FlightRecord, cfg: dict[str, Any]) -> tuple[int, int, int]:
    """Return (decision_time, expected_eta, expected_delay_min)."""

    lead = cfg["decision"]
    sched_time = _scheduled_time(rec)
    if mode == Mode.AIRBORNE:
        delay = int(min(max(rec.weather_delay, 10), 180))
        expected_eta = rec.scheduled_arrival + delay
        decision_time = max(0, expected_eta - int(lead["airborne_lead_min"]))
        return decision_time, expected_eta, delay

    earliest_departure = rec.scheduled_departure + rec.late_aircraft_delay
    expected_eta = earliest_departure + sched_time
    decision_time = max(0, earliest_departure - int(lead["ground_lead_min"]))
    return decision_time, expected_eta, expected_eta - rec.scheduled_arrival


def _notam_text(destination: str, rec: FlightRecord, closed: list[str], rng: random.Random) -> list[str]:
    if not closed:
        return [
            f"!{destination} {rec.month:02d}/{rng.randint(100, 999):03d} {destination} APRON "
            f"CONSTRUCTION WI TWY {'/'.join(closed) if closed else 'D'} AVOID LGTD BARRICADES"
        ]

    def stamp(minutes: int) -> str:
        day_offset, minute = divmod(int(minutes), 1440)
        day = rec.day + day_offset
        return f"15{rec.month:02d}{day:02d}{minute // 60:02d}{minute % 60:02d}"

    start = max(0, rec.scheduled_arrival - 60)
    end = start + 300
    return [
        f"!{destination} {rec.month:02d}/{rng.randint(100, 999):03d} {destination} TWY "
        f"{' AND '.join(closed)} CLSD {stamp(start)}-{stamp(end)}",
        f"!{destination} {rec.month:02d}/{rng.randint(100, 999):03d} {destination} TWY "
        f"{'/'.join(closed)} BTN TWY A AND TWY K CLSD",
    ]


def _real_arrivals_by_hour(rec: FlightRecord) -> Counter[int]:
    """Real same-airport arrivals (all carriers) in flights.csv per clock hour."""

    idx = _index()
    positions = idx["dest_groups"].get((rec.destination, _date_key(rec)))
    if positions is None:
        return Counter()
    positions = np.asarray(positions)
    positions = positions[positions != rec.row_index]
    return Counter(int(t) // 60 for t in idx["sarr"][positions])


def _slots(
    rec: FlightRecord,
    active: list[str],
    expected_eta: int,
    aar_reduced: int,
    cfg: dict[str, Any],
    rng: random.Random,
    specs: dict[str, Any],
    *,
    grid_start: int | None = None,
    span_min: int | None = None,
) -> list[ArrivalSlot]:
    """5-minute arrival slots over whole clock hours, with seeded background traffic.

    Per clock hour the background traffic is ``max(real same-airport arrivals in
    flights.csv, (U(background_util_range) - decay x hours after the ETA hour) x
    aar_reduced)``.  If it reaches the
    (reduced) arrival rate the hour is AT CAPACITY and every slot in it is taken;
    otherwise that many slots are allocated at seeded positions.  ATC-RWY-01 enforces the hourly cap on top of ``taken``.
    """

    atc_cfg = cfg["atc"]
    base = slot_grid_start(expected_eta, 5) if grid_start is None else int(grid_start)
    horizon = int(atc_cfg["slot_horizon_min"]) if span_min is None else int(span_min)
    phase = base % 5  # GROUND grids follow departure grid + block time (not always :00/:05)
    first_hour = base // 60
    last_hour = (base + horizon) // 60
    util_lo, util_hi = (float(x) for x in atc_cfg["background_util_range"])
    decay = float(atc_cfg.get("background_decay_per_hour", 0.0))
    eta_hour = int(expected_eta) // 60
    mix = cfg["leader_type_mix"]
    codes = [str(item[0]) for item in mix]
    weights = [float(item[1]) for item in mix]
    real_by_hour = _real_arrivals_by_hour(rec)

    slots: list[ArrivalSlot] = []
    for hour in range(first_hour, last_hour + 1):
        times = list(range(hour * 60 + phase, hour * 60 + 60, 5))
        hour_slots: list[ArrivalSlot] = []
        for runway in active:
            for slot_time in times:
                leader = rng.choices(codes, weights=weights, k=1)[0]
                spec = specs[leader]
                hour_slots.append(
                    ArrivalSlot(
                        slot_time=slot_time,
                        runway=runway,
                        leader_type=leader,
                        leader_wake=WakeCat(spec["wake"]),
                        gap_nm=round(rng.uniform(3.0, 9.0), 1),
                        taken=False,
                    )
                )

        real = int(real_by_hour.get(hour, 0))
        # Demand is highest around the ETA and eases in later hours (traffic metered).
        util = rng.uniform(util_lo, util_hi) - decay * max(0, hour - eta_hour)
        background = max(real, int(round(max(0.0, util) * aar_reduced)))
        if background >= aar_reduced:
            for sl in hour_slots:  # hour at capacity
                sl.taken = True
        else:
            # Seeded placement of the hour's background arrivals (real + fill).
            for pick in rng.sample(range(len(hour_slots)), min(background, len(hour_slots))):
                hour_slots[pick].taken = True
        slots.extend(hour_slots)
    slots.sort(key=lambda sl: (active.index(sl.runway), sl.slot_time))
    return slots


def _turbulence(
    levels: list[int], cfg: dict[str, Any], rng: random.Random
) -> tuple[list[str], dict[str, str]]:
    probs: dict[str, float] = cfg["turbulence"]["probs"]
    names = list(probs)
    weights = [float(probs[n]) for n in names]
    truth: dict[str, str] = {}
    text: list[str] = []
    for level in levels:
        observed = rng.choices(names, weights=weights, k=1)[0]
        truth[f"FL{level}"] = observed
        if observed != "NONE":
            label = {"LIGHT": "LGT", "MODERATE": "MOD", "SEVERE": "SEV"}[observed]
            text.append(f"PIREP UA{level} {label} TURB FL{level}-FL{level + 20}")
    if not text:
        text.append(f"PIREP SKYWAY NO TURB REPORTED FL{levels[0] if levels else 340}")
    return text, truth


def _alternates(
    rec: FlightRecord, rng: random.Random, cfg: dict[str, Any]
) -> list[str]:
    alternate_cfg = cfg["alternates"]
    max_nm = float(alternate_cfg["max_distance_nm"])
    min_flights = int(alternate_cfg["min_carrier_flights"])
    max_candidates = int(alternate_cfg["max_candidates"])
    idx = _index()
    counts: dict[tuple[str, str], int] = idx["carrier_counts"]
    coords = airport_coords()
    if rec.destination not in coords:
        return [rec.destination]
    lat0, lon0 = coords[rec.destination]

    served: list[tuple[float, str]] = []
    nearby: list[tuple[float, str]] = []
    for code, (lat, lon) in coords.items():
        if code == rec.destination:
            continue
        distance = _haversine_nm(lat0, lon0, lat, lon)
        if distance > max_nm:
            continue
        nearby.append((distance, code))
        if counts.get((rec.airline, code), 0) >= min_flights:
            served.append((distance, code))

    served.sort()
    nearby.sort()
    chosen = [code for _, code in served[:max_candidates]]
    if not chosen:
        chosen = [code for _, code in nearby[:max_candidates]]
    if not chosen:
        # Last resort: nearest airport anywhere in the table.
        every = sorted(
            (_haversine_nm(lat0, lon0, lat, lon), code)
            for code, (lat, lon) in coords.items()
            if code != rec.destination
        )
        chosen = [every[0][1]]
    return chosen


def _alternate_distance(rec: FlightRecord, alternate: str) -> float:
    coords = airport_coords()
    if rec.destination not in coords or alternate not in coords:
        return 120.0
    lat0, lon0 = coords[rec.destination]
    lat1, lon1 = coords[alternate]
    return _haversine_nm(lat0, lon0, lat1, lon1)


def _connections(rec: FlightRecord, cfg: dict[str, Any], rng: random.Random) -> list[Connection]:
    idx = _index()
    if rec.airline not in idx["airline"]:  # pragma: no cover - defensive
        return []
    window_lo, window_hi = cfg["connections"]["window_min"]
    max_connections = int(cfg["connections"]["max_connections"])
    pax_lo, pax_hi = cfg["connections"]["pax_range"]
    mct_map = cfg["mct_min"]
    mct = int(mct_map.get(rec.destination, mct_map["default"]))

    arrival_ref = rec.scheduled_arrival if rec.scheduled_arrival < 1440 else rec.scheduled_arrival - 1440
    start = arrival_ref + int(window_lo)
    end = arrival_ref + int(window_hi)

    group = (rec.airline, rec.destination, _date_key(rec))
    positions = idx["arr_groups"].get(group)
    if positions is None:
        return []
    positions = np.asarray(positions)
    deps = idx["sdep"][positions]
    mask = (deps >= start) & (deps <= end) & (positions != rec.row_index)
    selected = positions[mask]
    if len(selected) == 0:
        return []

    order = np.argsort(idx["sdep"][selected])
    selected = selected[order][:max_connections]
    connections: list[Connection] = []
    for pos in selected:
        connections.append(
            Connection(
                airline=str(idx["airline"][pos]),
                flight_number=int(idx["flight_number"][pos]),
                destination=str(idx["dest"][pos]),
                scheduled_departure=int(idx["sdep"][pos]),
                pax=int(rng.randint(int(pax_lo), int(pax_hi))),
                mct_min=mct,
                real=True,
            )
        )
    return connections


def _next_leg(
    rec: FlightRecord, expected_eta: int, cfg: dict[str, Any], rng: random.Random
) -> NextLeg | None:
    idx = _index()
    group = (rec.tail_number, _date_key(rec))
    positions = idx["next_groups"].get(group)
    if positions is not None and len(positions):
        positions = np.asarray(positions)
        mask = (idx["origin"][positions] == rec.destination) & (
            idx["sdep"][positions] > rec.scheduled_departure
        )
        candidates = positions[mask]
        if len(candidates):
            best = candidates[np.argmin(idx["sdep"][candidates])]
            return NextLeg(
                flight_number=int(idx["flight_number"][best]),
                destination=str(idx["dest"][best]),
                scheduled_departure=int(idx["sdep"][best]),
                real=True,
            )

    options = [ap for ap in idx["airline_airports"].get(rec.airline, []) if ap != rec.destination]
    destination = rng.choice(options) if options else rec.destination
    return NextLeg(
        flight_number=int(rng.randint(100, 9999)),
        destination=destination,
        scheduled_departure=int(expected_eta + rng.randint(45, 180)),
        real=False,
    )


def _gates(
    rec: FlightRecord,
    aircraft: AircraftInfo,
    expected_eta: int,
    cfg: dict[str, Any],
    rng: random.Random,
    limits: AirportLimits,
) -> tuple[list[Gate], str, list[str]]:
    """Modelled gate subset (carrier + common-use) of the workbook ``gates`` total.

    At least workbook ``spare_gates_at_any_time`` modelled gates are kept free over
    the planned turnaround window ``[eta, eta + min_turnaround]`` (+ buffer), in
    addition to the planned gate.
    """

    ground_cfg = cfg["ground"]
    modelled = max(
        2,
        min(
            int(limits.gates),
            int(ground_cfg["gates_per_carrier"]) + int(ground_cfg["common_use_gates"]),
        ),
    )
    n_carrier = min(int(ground_cfg["gates_per_carrier"]), modelled - 1)
    n_common = modelled - n_carrier
    terminal = "ABCDE"[hashlib.sha256(rec.destination.encode()).digest()[0] % 5]

    sizes: list[SizeClass] = []
    for i in range(n_carrier + n_common):
        sizes.append(
            SizeClass.WIDE
            if i % 4 in (0, 3)
            else (SizeClass.NARROW if i % 4 == 1 else SizeClass.REGIONAL)
        )

    gate_ids = [f"{terminal}{10 + i}" for i in range(n_carrier + n_common)]
    carrier_specs = [(gate_ids[i], sizes[i], rec.airline) for i in range(n_carrier)]
    common_specs = [(gate_ids[i], sizes[i], None) for i in range(n_carrier, n_carrier + n_common)]

    rank = {SizeClass.REGIONAL: 0, SizeClass.NARROW: 1, SizeClass.WIDE: 2}
    need = rank[aircraft.size_class]
    fitting = [gid for gid, size, _ in carrier_specs if rank[size] >= need]
    current = rng.choice(fitting) if fitting else max(carrier_specs, key=lambda x: rank[x[1]])[0]

    gates: list[Gate] = []
    for gid, size, carrier in carrier_specs + common_specs:
        gates.append(
            Gate(
                gate_id=gid,
                max_size=size,
                carrier=carrier,
                occupied=[],
                taxi_route=taxi_route_for(rec.destination, gid),
            )
        )

    # Occupancy: partly real same-carrier movements around the arrival period,
    # partly seeded synthetic windows.  This is what creates gate pressure.
    real_windows: list[tuple[int, int]] = []
    idx = _index()
    date = _date_key(rec)
    arr_group = (rec.airline, rec.destination, date)
    dep_group = (rec.airline, rec.destination, date)
    lo, hi = expected_eta - 120, expected_eta + 150

    for group, kind in ((arr_group, "arr"), (dep_group, "dep")):
        positions = idx["arr_groups"].get(group) if kind == "arr" else idx["dep_groups"].get(group)
        if positions is None:
            continue
        positions = np.asarray(positions)
        times = idx["sarr"][positions] if kind == "arr" else idx["sdep"][positions]
        mask = (times >= lo) & (times <= hi) & (positions != rec.row_index)
        selected = positions[mask]
        if len(selected) > 6:
            selected = selected[:6]
        for pos in selected:
            t = int(times[np.where(positions == pos)[0][0]])
            if kind == "arr":
                real_windows.append((t, t + 45))
            else:
                real_windows.append((t - 45, t))

    rng.shuffle(real_windows)
    real_marks: set[tuple[str, int, int]] = set()
    for i, window in enumerate(real_windows[:5]):
        gid = gate_ids[i % len(gate_ids)]
        gate = next(g for g in gates if g.gate_id == gid)
        gate.occupied.append(window)
        real_marks.add((gid, int(window[0]), int(window[1])))

    occupancy_frac = float(ground_cfg["gate_occupancy_frac"])
    for gate in gates:
        if rng.random() < occupancy_frac:
            start = expected_eta + rng.randint(-60, 60)
            duration = rng.randint(35, 120)
            gate.occupied.append((start, start + duration))

    # The originally planned gate should normally be usable at the current
    # estimate; blocks elsewhere create the gate-change trade-off.
    current_gate = next(g for g in gates if g.gate_id == current)
    protected_lo, protected_hi = expected_eta - 30, expected_eta + 60
    current_gate.occupied = [
        (s, e)
        for (s, e) in current_gate.occupied
        if not (protected_lo < e and s < protected_hi)
    ]

    # Workbook airport_capacity: spare_gates_at_any_time free over the turnaround
    # window.  Clear synthetic blocks first, real same-carrier windows only if needed.
    buffer_min = int(ground_cfg.get("gate_buffer_min", 10))
    w_lo = expected_eta - buffer_min
    w_hi = expected_eta + int(limits.min_turnaround_min) + buffer_min

    def overlapping(gate: Gate) -> list[tuple[int, int]]:
        return [(a, b) for (a, b) in gate.occupied if w_lo < b and a < w_hi]

    def is_free(gate: Gate) -> bool:
        return not overlapping(gate)

    # Spare = free gates OTHER than the planned gate (which is held for this flight).
    needed = int(limits.spare_gates_at_any_time)
    others = [g for g in gates if g.gate_id != current]
    for allow_real in (False, True):
        for gate in others:
            if sum(1 for g in others if is_free(g)) >= needed:
                break
            blocks = overlapping(gate)
            if not blocks:
                continue
            if not allow_real and any((gate.gate_id, a, b) in real_marks for a, b in blocks):
                continue
            gate.occupied = [w for w in gate.occupied if w not in blocks]

    for gate in gates:
        gate.occupied.sort()

    # Public gates: current gate first, then the largest gates.  The generator
    # only sees ids (not sizes or occupancy), so this ordering gives it a
    # sensible shortlist that still contains real trade-offs.
    ordered = sorted(
        gates,
        key=lambda g: (0 if g.gate_id == current else 1, -rank[g.max_size]),
    )
    public_ids = [g.gate_id for g in ordered]
    return gates, current, public_ids


def _shifts(cfg: dict[str, Any], costs: dict[str, Any]) -> list[CrewShift]:
    """Ramp-crew shifts: workbook 8 h shift, overtime at base x 1.5 (cost only).

    The workbook sets no hard labour limit, so ``hard_limit_end`` equals the
    normal shift end (kept for schema compatibility; GND-CREW-01 never vetoes).
    """

    limits = fuel_crew()
    length = int(limits.ground_shift_min)
    multiplier = float(limits.ground_overtime_multiplier)
    base = float(costs["ground_crew_base_eur_per_min"])
    shifts: list[CrewShift] = []
    for t in cfg["ground"]["shift_templates"]:
        start = int(t["start"])
        end = start + length
        shifts.append(
            CrewShift(
                shift_id=str(t["shift_id"]),
                start=start,
                end=end,
                hard_limit_end=end,
                overtime_eur_per_min=round(base * multiplier, 4),
                base_eur_per_min=base,
                overtime_multiplier=multiplier,
            )
        )
    return shifts


def _defect(
    mode: Mode, defect_id: str | None, cfg: dict[str, Any], rng: random.Random
) -> DefectReport | None:
    if mode != Mode.GROUND:
        return None
    ground_cfg = cfg["ground"]
    library = load_yaml("defects").get("defects", {})
    if defect_id is not None:
        if defect_id not in library:
            raise ValueError(f"unknown defect id {defect_id!r}")
        chosen_id = defect_id
    elif rng.random() < float(ground_cfg["defect_prob_ground_mode"]):
        chosen_id = rng.choice(sorted(library))
    else:
        return None

    item = library[chosen_id]
    return DefectReport(
        defect_id=chosen_id,
        text=str(item["text"]),
        fault_code=item.get("fault_code"),
        truth_ata_chapter=item.get("ata_chapter"),
        truth_mel_item=item.get("mel_item"),
        truth_mel_category=item.get("mel_category"),
        truth_deferrable=item.get("deferrable"),
        truth_repair_min=item.get("repair_min"),
    )


def _pax_notes(rng: random.Random) -> list[str]:
    pool = [
        "2 unaccompanied minors on board",
        "Mobility assistance requested at the gate",
        "Company priority passenger in seat 2A",
    ]
    rng.shuffle(pool)
    return pool[: rng.randint(0, len(pool))]


# --------------------------------------------------------------------------- public builder


def build_event(
    rec: FlightRecord, *, seed: int = 0, defect_id: str | None = None
) -> DisruptionEvent:
    cfg = load_yaml("synthetic")
    costs = load_yaml("costs")
    runway_cfg = load_yaml("runways")
    rng = _rng(rec, seed)
    dest_limits = airport_limits(rec.destination)  # workbook airport_capacity
    fc_limits = fuel_crew()  # workbook fuel_and_crew

    mode = mode_for(rec)
    disruption_type = disruption_type_for(rec)
    aircraft = _aircraft(rec, rng, cfg)
    active_runways = _active_runways(
        rec.destination, _rng(rec, seed, "runways"), runway_cfg, dest_limits
    )
    decision_time, expected_eta, _delay = _delays(mode, rec, cfg)

    # ---------------------------------------------------------------- ATC private
    # Normal arrival rate = modelled arrival share of the workbook runway ops/hour.
    aar_normal = max(
        1,
        int(
            round(
                float(cfg["atc"]["arrival_share_of_runway_ops"])
                * dest_limits.max_runway_ops_per_hour
            )
        ),
    )
    weather_fraction = 0.0
    if mode == Mode.AIRBORNE:
        for upper, fraction in cfg["atc"]["weather_reduction"]:
            if rec.weather_delay <= int(upper):
                weather_fraction = float(fraction)
                break
    aar_reduced = max(1, int(round(aar_normal * (1.0 - weather_fraction))))

    closed: list[str] = []
    if rng.random() < float(cfg["atc"]["closed_taxiway_prob"]):
        n_closed = 1 + (1 if rng.random() < 0.3 else 0)
        closed = rng.sample(list(cfg["ground"]["taxiways"]), n_closed)

    grid_start: int | None = None
    span_min: int | None = None
    if mode == Mode.GROUND:
        earliest = rec.scheduled_departure + rec.late_aircraft_delay
        departure_grid = slot_grid_start(earliest, 5)
        block_min = _scheduled_time(rec)
        max_recovery = (int(cfg["fuel"]["speed_recovery_max_frac"] * block_min) // 5) * 5
        grid_start = departure_grid + block_min - max_recovery
        span_min = max_recovery + int(cfg["atc"]["slot_horizon_min"]) + 15
    slots = _slots(
        rec,
        active_runways,
        expected_eta,
        aar_reduced,
        cfg,
        _rng(rec, seed, "traffic"),
        cfg["aircraft_types"],
        grid_start=grid_start,
        span_min=span_min,
    )
    atc_private = AtcPrivate(
        aar_normal=aar_normal,
        aar_reduced=aar_reduced,
        max_runway_ops_per_hour=dest_limits.max_runway_ops_per_hour,
        active_runways=dest_limits.active_runways,
        slots=slots,
        notam_text=_notam_text(rec.destination, rec, closed, rng),
        truth_closed_taxiways=closed,
    )

    # ---------------------------------------------------------------- Pilot private
    fuel_cfg = cfg["fuel"]
    sched_time = _scheduled_time(rec)
    if mode == Mode.AIRBORNE:
        trip_min = max(20, expected_eta - decision_time)
    else:
        trip_min = sched_time
    burn = aircraft.cruise_burn_kg_min
    hold_burn = aircraft.holding_burn_kg_min

    fuel_to_destination = trip_min * burn
    alternate_candidates = _alternates(rec, rng, cfg)
    alternate = alternate_candidates[0]
    alternate_distance = _alternate_distance(rec, alternate)
    fuel_to_alternate = (
        alternate_distance / float(fuel_cfg["alternate_speed_kt"]) * 60.0 * burn
    )
    # Workbook fuel_and_crew: final reserve 30 min holding; contingency 5% of trip
    # fuel; assumed spare on arrival 45 min holding ON TOP of the final reserve.
    # Alternate fuel is not part of the arrival requirement (the workbook has none);
    # fuel_to_alternate is only used to check a divert option.
    final_reserve = fc_limits.final_reserve_holding_min * hold_burn
    contingency = fc_limits.contingency_frac * fuel_to_destination
    spare = fc_limits.spare_fuel_holding_min * hold_burn
    fuel_on_board = fuel_to_destination + contingency + final_reserve + spare
    if mode == Mode.AIRBORNE:
        max_extra_fuel = 0.0
    else:
        max_extra_fuel = rng.uniform(*fuel_cfg["max_extra_uplift_kg_range"])

    chosen_levels = sorted(int(level) for level in fuel_cfg["cruise_levels"])
    turbulence_text, turbulence_truth = _turbulence(chosen_levels, cfg, rng)
    # The aircraft is currently cruising at the first level: keep a workable
    # level first, but still expose severe levels elsewhere so avoidance matters.
    chosen_levels = sorted(
        chosen_levels, key=lambda lv: (turbulence_truth.get(f"FL{lv}") == "SEVERE", lv)
    )

    # Flight crew: workbook max duty 13 h from report.  Seeded multi-leg day: the crew
    # reported 60 min before this leg, or earlier (prior legs) so that `margin` minutes
    # of duty remain at the scheduled arrival.  Times are on the option timeline:
    # GROUND = origin clock (departure + block), AIRBORNE = destination clock.
    pilot_cfg = cfg["pilot"]
    max_duty = int(fc_limits.flight_crew_max_duty_min)
    margin = _rng(rec, seed, "crew").randint(
        *(int(x) for x in pilot_cfg["duty_margin_at_sched_arrival_range"])
    )
    if mode == Mode.GROUND:
        leg_dep = rec.scheduled_departure
        leg_arr = rec.scheduled_departure + sched_time
    else:
        leg_arr = rec.scheduled_arrival
        leg_dep = rec.scheduled_arrival - sched_time
    crew_report = min(
        leg_dep - int(pilot_cfg["report_before_departure_min"]),
        leg_arr + margin - max_duty,
    )

    pilot_private = PilotPrivate(
        fuel_on_board_kg=round(fuel_on_board, 1),
        fuel_to_destination_kg=round(fuel_to_destination, 1),
        alternate=alternate,
        alternate_distance_nm=round(alternate_distance, 1),
        fuel_to_alternate_kg=round(fuel_to_alternate, 1),
        final_reserve_kg=round(final_reserve, 1),
        contingency_kg=round(contingency, 1),
        max_extra_fuel_kg=round(max_extra_fuel, 1),
        cruise_levels=chosen_levels,
        turbulence_text=turbulence_text,
        truth_turbulence=turbulence_truth,
        connections=_connections(rec, cfg, rng),
        pax_notes=_pax_notes(rng),
        crew_duty_remaining_min=int(crew_report + max_duty - decision_time),
        crew_report_time=int(crew_report),
        crew_max_duty_min=max_duty,
    )

    # ---------------------------------------------------------------- Ground private
    gates, current_gate, public_gate_ids = _gates(
        rec, aircraft, expected_eta, cfg, rng, dest_limits
    )
    min_turn = int(dest_limits.min_turnaround_min)  # workbook, destination airport
    defect = _defect(mode, defect_id, cfg, rng)

    ground_private = GroundPrivate(
        gates=gates,
        current_gate=current_gate,
        shifts=_shifts(cfg, costs),
        min_turnaround_min=min_turn,
        next_leg=_next_leg(rec, expected_eta, cfg, rng),
        defect=defect,
        spare_aircraft_available=bool(
            rng.random() < float(cfg["ground"]["spare_aircraft_prob"])
        ),
        gate_change_eur=float(costs["gate_change_eur"]),
        gate_change_notice_min=int(fc_limits.gate_change_notice_min),
        total_gates=int(dest_limits.gates),
        spare_gates_at_any_time=int(dest_limits.spare_gates_at_any_time),
    )

    # ---------------------------------------------------------------- public
    if mode == Mode.AIRBORNE:
        summary = (
            f"Weather at {rec.destination}: arrival rate cut from {aar_normal} to "
            f"{aar_reduced}/h. Inbound {rec.airline}{rec.flight_number} is "
            f"{rec.weather_delay} min weather-delayed."
        )
    else:
        summary = (
            f"Late inbound aircraft at {rec.origin}: departure {rec.late_aircraft_delay} "
            f"min late, destination {rec.destination}."
        )

    synthetic_fields = [
        "aircraft.type_code",
        "aircraft.wake",
        "aircraft.cruise_burn_kg_min",
        "destination_runways",
        "atc.slots",
        "atc.background_traffic",
        "atc.notam_text",
        "pilot.fuel_on_board_kg",
        "pilot.crew_report_time",
        "pilot.alternate",
        "pilot.turbulence",
        "pilot.connections.pax",
        "ground.gates",
        "ground.shifts",
        "ground.defect",
        "ground.spare_aircraft_available",
    ]

    public = PublicEvent(
        run_id=rec.run_id,
        mode=mode,
        disruption_type=disruption_type,
        disruption_summary=summary,
        flight=rec,
        aircraft=aircraft,
        decision_time=decision_time,
        original_eta=rec.scheduled_arrival,
        expected_eta=expected_eta,
        destination_runways=active_runways,
        public_gate_ids=public_gate_ids,
        alternate_candidates=alternate_candidates,
        synthetic_fields=synthetic_fields,
    )

    return DisruptionEvent(
        public=public,
        atc=atc_private,
        pilot=pilot_private,
        ground=ground_private,
    )


__all__ = ["build_event"]
