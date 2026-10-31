"""Shared (orchestrator-owned) checks and small helpers for role checkers."""

from __future__ import annotations

from typing import Any, Callable

from triad.config import load_yaml
from triad.schemas import (
    AgentRole,
    CandidateOption,
    ConstraintCheck,
    DisruptionEvent,
    FlightRecord,
    Mode,
    PublicEvent,
)


CheckIdFactory = Callable[[], str]


def constraint_meta(constraint_id: str) -> dict[str, Any]:
    return load_yaml("constraints").get("constraints", {}).get(constraint_id, {})


def constraint_source(constraint_id: str) -> str:
    return str(constraint_meta(constraint_id).get("source") or constraint_id)


def make_check(
    *,
    constraint_id: str,
    owner: AgentRole | str,
    option: CandidateOption,
    next_id: CheckIdFactory,
    passed: bool,
    value: float | str | None,
    limit: float | str | None,
    unit: str | None,
    detail: str = "",
    facts_used: list[str] | None = None,
    hard: bool = True,
) -> ConstraintCheck:
    return ConstraintCheck(
        check_id=next_id(),
        constraint_id=constraint_id,
        owner=owner,  # type: ignore[arg-type]
        option_id=option.option_id,
        passed=bool(passed),
        hard=hard,
        value=value,
        limit=limit,
        unit=unit,
        source=constraint_source(constraint_id),
        detail=detail,
        facts_used=list(facts_used or []),
    )


def is_divert(option: CandidateOption) -> bool:
    return bool(option.divert_to)


def scheduled_time_min(flight: FlightRecord) -> int:
    """Scheduled block time in minutes (never zero for valid data)."""

    if flight.scheduled_time is not None and flight.scheduled_time > 0:
        return int(flight.scheduled_time)
    diff = int(flight.scheduled_arrival) - int(flight.scheduled_departure)
    return diff if diff > 0 else max(1, diff + 1440)


def earliest_departure_min(flight: FlightRecord) -> int:
    """GROUND mode earliest departure before any MEL repair."""

    return int(flight.scheduled_departure) + int(flight.late_aircraft_delay)


# --------------------------------------------------------------------------- shared checks


def shared_checks(
    public: PublicEvent, option: CandidateOption, next_id: CheckIdFactory
) -> list[ConstraintCheck]:
    """Checks every party can run: the option is physically usable and consistent."""

    checks: list[ConstraintCheck] = []

    # SHR-RWY-01 -- runway exists / is active at the destination.
    runway_ok = option.runway in public.destination_runways
    checks.append(
        make_check(
            constraint_id="SHR-RWY-01",
            owner="SHARED",
            option=option,
            next_id=next_id,
            passed=runway_ok,
            value=option.runway,
            limit=", ".join(public.destination_runways),
            unit="runway",
            detail="runway active" if runway_ok else "runway is not an active destination end",
        )
    )

    # SHR-GATE-00 -- gate is a real public gate at the destination.
    gate_ok = option.gate in public.public_gate_ids
    checks.append(
        make_check(
            constraint_id="SHR-GATE-00",
            owner="SHARED",
            option=option,
            next_id=next_id,
            passed=gate_ok,
            value=option.gate,
            limit=", ".join(public.public_gate_ids),
            unit="gate",
            detail="gate exists on the public map" if gate_ok else "unknown gate id",
        )
    )

    # SHR-TIME-01 -- kinematics of the arrival-slot / delay split.
    if is_divert(option):
        checks.append(
            make_check(
                constraint_id="SHR-TIME-01",
                owner="SHARED",
                option=option,
                next_id=next_id,
                passed=True,
                value=option.arrival_slot,
                limit="divert",
                unit="min",
                detail="divert routing: slot equations do not apply",
            )
        )
        return checks

    cfg = load_yaml("synthetic")
    fuel_cfg = cfg["fuel"]

    if public.mode == Mode.AIRBORNE:
        max_absorb = fuel_cfg["enroute_absorb_max_frac"] * (
            public.expected_eta - public.decision_time
        )
        expected_arrival = (
            public.expected_eta + option.enroute_absorb_min + option.holding_min
        )
        absorb_ok = 0 <= option.enroute_absorb_min <= max_absorb + 1e-6
        holding_ok = option.holding_min >= 0
        time_ok = option.arrival_slot == expected_arrival
        passed = absorb_ok and holding_ok and time_ok
        detail = (
            f"arrival {option.arrival_slot} == ETA {public.expected_eta} + absorb "
            f"{option.enroute_absorb_min} + hold {option.holding_min}"
        )
        checks.append(
            make_check(
                constraint_id="SHR-TIME-01",
                owner="SHARED",
                option=option,
                next_id=next_id,
                passed=passed,
                value=option.arrival_slot,
                limit=expected_arrival,
                unit="min",
                detail=detail,
            )
        )
    else:
        sched_min = scheduled_time_min(public.flight)
        max_recovery = fuel_cfg["speed_recovery_max_frac"] * sched_min
        earliest = earliest_departure_min(public.flight)
        departure = option.departure_slot
        dep_ok = departure is not None and departure >= earliest
        recovery_ok = 0 <= option.speed_recovery_min <= max_recovery + 1e-6
        expected_arrival = (
            (departure if departure is not None else earliest)
            + sched_min
            - option.speed_recovery_min
        )
        time_ok = option.arrival_slot == expected_arrival
        passed = dep_ok and recovery_ok and time_ok
        checks.append(
            make_check(
                constraint_id="SHR-TIME-01",
                owner="SHARED",
                option=option,
                next_id=next_id,
                passed=passed,
                value=departure if departure is not None else "missing",
                limit=earliest,
                unit="min",
                detail=(
                    f"departure {departure} >= earliest {earliest}; arrival "
                    f"{option.arrival_slot} == departure + block {sched_min} - recovery "
                    f"{option.speed_recovery_min}"
                ),
            )
        )

    return checks


# --------------------------------------------------------------------------- utility for pickers


def all_shared_pass(event: DisruptionEvent, option: CandidateOption, next_id: CheckIdFactory) -> bool:
    return all(c.passed for c in shared_checks(event.public, option, next_id) if c.hard)
