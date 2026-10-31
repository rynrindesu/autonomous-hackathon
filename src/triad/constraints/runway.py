"""Runway/airport geometry helpers shared by enrich and the ATC checker.

The gate-to-taxiway route is intentionally derived from the gate id alone.  The
ATC agent must not receive Ground's gate inventory, so both the scenario builder
(filling ``Gate.taxi_route``) and ``ATC-TWY-01`` call the same deterministic
helper.
"""

from __future__ import annotations

import hashlib

from triad.config import load_yaml
from triad.schemas import (
    ArrivalSlot,
    AtcPrivate,
    CandidateOption,
    ConstraintCheck,
    PublicEvent,
)


def _taxiways() -> list[str]:
    return list(load_yaml("synthetic")["ground"]["taxiways"])


def taxi_route_for(airport: str, gate_id: str) -> list[str]:
    """Deterministic taxiway sequence from the arrival side to ``gate_id``."""

    taxiways = _taxiways()
    if not taxiways:
        return []
    digest = hashlib.sha256(f"{airport}|{gate_id}|taxi-route".encode()).digest()
    n = 2 + digest[0] % 2  # 2 or 3 taxiways
    step = 1 + digest[1] % 3
    start = digest[2] % len(taxiways)
    route: list[str] = []
    for i in range(n):
        twy = taxiways[(start + i * step) % len(taxiways)]
        if twy not in route:
            route.append(twy)
    return route


def runway_ends(airport: str) -> list[str]:
    """All runway ends configured for an airport (both directions)."""

    cfg = load_yaml("runways")
    pairs = cfg.get("airports", {}).get(airport, cfg.get("default", ["09/27", "18/36"]))
    ends: list[str] = []
    for pair in pairs:
        for end in str(pair).split("/"):
            end = end.strip()
            if end and end not in ends:
                ends.append(end)
    return ends


def slot_grid_start(expected_eta: int, grid_min: int = 5) -> int:
    """First slot grid point at or after ``expected_eta``."""

    return ((int(expected_eta) + grid_min - 1) // grid_min) * grid_min


def find_slot(slots: list[ArrivalSlot], runway: str, slot_time: int) -> ArrivalSlot | None:
    for slot in slots:
        if slot.runway == runway and slot.slot_time == slot_time:
            return slot
    return None


def active_runways_from_slots(slots: list[ArrivalSlot]) -> list[str]:
    seen: list[str] = []
    for slot in slots:
        if slot.runway not in seen:
            seen.append(slot.runway)
    return seen


def reachable_route(route: list[str], closed: set[str]) -> tuple[bool, list[str]]:
    blockers = [twy for twy in route if twy in closed]
    return (not blockers, blockers)


def public_runway_default(public: PublicEvent) -> str | None:
    return public.destination_runways[0] if public.destination_runways else None


# --------------------------------------------------------------------------- ATC checks


def clock_hour(slot_time: int) -> int:
    """Clock-hour bucket of a slot time (minutes since midnight; >=1440 = next day)."""

    return int(slot_time) // 60


def booked_in_hour(slots: list[ArrivalSlot], slot_time: int) -> int:
    """Arrival slots already allocated to other traffic in ``slot_time``'s clock hour
    (all active runways)."""

    hour = clock_hour(slot_time)
    return sum(1 for s in slots if s.taken and clock_hour(s.slot_time) == hour)


def check_runway(
    public: PublicEvent,
    private: AtcPrivate,
    facts: dict,
    option: CandidateOption,
    next_id,
) -> list[ConstraintCheck]:
    """ATC-RWY-01: the slot exists, is not allocated, and its clock hour is below the
    (weather-reduced) arrival rate derived from the workbook max_runway_ops_per_hour."""

    from triad.constraints.shared import is_divert, make_check

    if is_divert(option):
        return [
            make_check(
                constraint_id="ATC-RWY-01",
                owner="ATC",
                option=option,
                next_id=next_id,
                passed=True,
                value="divert",
                limit="n/a",
                unit="arrivals/h",
                detail="divert to alternate: destination slot not used",
            )
        ]

    cap = int(private.aar_reduced)
    hour = clock_hour(option.arrival_slot)
    hh = f"{hour % 24:02d}:00"
    slot = find_slot(private.slots, option.runway, option.arrival_slot)
    booked = booked_in_hour(private.slots, option.arrival_slot)
    ops = (
        f" (from workbook {private.max_runway_ops_per_hour} runway ops/h)"
        if private.max_runway_ops_per_hour
        else ""
    )
    if slot is None:
        passed = False
        detail = f"no slot at {option.arrival_slot} on {option.runway}"
    elif booked >= cap:
        passed = False
        detail = (
            f"hour {hh} at capacity: {booked} slots already allocated, reduced arrival "
            f"rate {cap}/h{ops}"
        )
    elif slot.taken:
        passed = False
        detail = f"slot {option.arrival_slot} on {option.runway} already allocated to other traffic"
    else:
        passed = True
        detail = (
            f"slot {option.arrival_slot} on {option.runway} free; hour {hh} would have "
            f"{booked + 1} of {cap} arrivals/h{ops}"
        )
    return [
        make_check(
            constraint_id="ATC-RWY-01",
            owner="ATC",
            option=option,
            next_id=next_id,
            passed=passed,
            value=booked + 1,
            limit=cap,
            unit="arrivals/h",
            detail=detail,
        )
    ]


def check_taxiway(
    public: PublicEvent,
    private: AtcPrivate,
    facts: dict,
    option: CandidateOption,
    next_id,
) -> list[ConstraintCheck]:
    """ATC-TWY-01: gate reachable using only open taxiways."""

    from triad.constraints.shared import is_divert, make_check

    fact = facts.get("closed_taxiways")
    closed = set(fact.value or []) if fact is not None else set()
    used = ["closed_taxiways"] if fact is not None else []

    if is_divert(option):
        return [
            make_check(
                constraint_id="ATC-TWY-01",
                owner="ATC",
                option=option,
                next_id=next_id,
                passed=True,
                value="divert",
                limit="n/a",
                unit="taxiway",
                detail="divert to alternate: destination taxi route not used",
                facts_used=used,
            )
        ]

    route = taxi_route_for(public.flight.destination, option.gate)
    ok, blockers = reachable_route(route, closed)
    return [
        make_check(
            constraint_id="ATC-TWY-01",
            owner="ATC",
            option=option,
            next_id=next_id,
            passed=ok,
            value=", ".join(route) or "none",
            limit="open taxiways",
            unit="taxiway",
            detail=(
                f"route {' -> '.join(route)} blocked by {', '.join(blockers)}"
                if blockers
                else f"route {' -> '.join(route)} is clear"
            ),
            facts_used=used,
        )
    ]
