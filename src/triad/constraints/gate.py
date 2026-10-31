"""Ground gate checks: size, occupancy overlap (with buffer), carrier rights and
gate-change notice (GND-GATE-04, workbook fuel_and_crew: a gate change must be
notified at least 20 min before arrival)."""

from __future__ import annotations

from typing import Callable

from triad.config import load_yaml
from triad.constraints.shared import is_divert, make_check
from triad.schemas import CandidateOption, ConstraintCheck, Gate, GroundPrivate, PerceivedFact, PublicEvent, SizeClass

_SIZE_RANK = {SizeClass.REGIONAL: 0, SizeClass.NARROW: 1, SizeClass.WIDE: 2}


def _find_gate(private: GroundPrivate, gate_id: str) -> Gate | None:
    for gate in private.gates:
        if gate.gate_id == gate_id:
            return gate
    return None


def _overlaps(gate: Gate, start: int, end: int, buffer_min: int) -> list[tuple[int, int]]:
    lo, hi = start - buffer_min, end + buffer_min
    hits: list[tuple[int, int]] = []
    for occ_start, occ_end in gate.occupied:
        if lo < occ_end and occ_start < hi:
            hits.append((int(occ_start), int(occ_end)))
    return hits


def _gate_notice_check(
    public: PublicEvent,
    private: GroundPrivate,
    option: CandidateOption,
    next_id: Callable[[], str],
) -> ConstraintCheck:
    """GND-GATE-04: if the option changes the planned gate, the change is notified
    at the decision time, which must be >= ``gate_change_notice_min`` before arrival."""

    notice_min = int(private.gate_change_notice_min)
    if is_divert(option):
        return make_check(
            constraint_id="GND-GATE-04",
            owner="GROUND",
            option=option,
            next_id=next_id,
            passed=True,
            value="divert",
            limit=notice_min,
            unit="min notice",
            detail="aircraft diverts to alternate; no destination gate change",
        )
    if option.gate == private.current_gate:
        return make_check(
            constraint_id="GND-GATE-04",
            owner="GROUND",
            option=option,
            next_id=next_id,
            passed=True,
            value="no change",
            limit=notice_min,
            unit="min notice",
            detail=f"planned gate {private.current_gate} kept; no notice needed",
        )
    notice = int(option.arrival_slot) - int(public.decision_time)
    return make_check(
        constraint_id="GND-GATE-04",
        owner="GROUND",
        option=option,
        next_id=next_id,
        passed=notice >= notice_min,
        value=notice,
        limit=notice_min,
        unit="min notice",
        detail=(
            f"gate change {private.current_gate} -> {option.gate} notified at "
            f"{public.decision_time}, {notice} min before arrival {option.arrival_slot} "
            f"(minimum {notice_min})"
        ),
    )


def check_gates(
    public: PublicEvent,
    private: GroundPrivate,
    facts: dict[str, PerceivedFact],
    option: CandidateOption,
    next_id: Callable[[], str],
) -> list[ConstraintCheck]:
    buffer_min = int(load_yaml("constraints").get("gate_buffer_min", 10))

    if is_divert(option):
        return [
            make_check(
                constraint_id="GND-GATE-01",
                owner="GROUND",
                option=option,
                next_id=next_id,
                passed=True,
                value="divert",
                limit="n/a",
                unit="size",
                detail="aircraft diverts to alternate; destination gate not used",
            ),
            make_check(
                constraint_id="GND-GATE-02",
                owner="GROUND",
                option=option,
                next_id=next_id,
                passed=True,
                value="divert",
                limit=0,
                unit="conflicts",
                detail="aircraft diverts to alternate; destination gate not used",
            ),
            make_check(
                constraint_id="GND-GATE-03",
                owner="GROUND",
                option=option,
                next_id=next_id,
                passed=True,
                value="divert",
                limit=public.flight.airline,
                unit="carrier",
                detail="aircraft diverts to alternate; destination gate not used",
            ),
            _gate_notice_check(public, private, option, next_id),
        ]

    gate = _find_gate(private, option.gate)
    checks: list[ConstraintCheck] = []

    if gate is None:
        for cid, detail in (
            ("GND-GATE-01", f"gate {option.gate} not in carrier/common-use inventory"),
            ("GND-GATE-02", f"gate {option.gate} not in carrier/common-use inventory"),
            ("GND-GATE-03", f"gate {option.gate} not in carrier/common-use inventory"),
        ):
            checks.append(
                make_check(
                    constraint_id=cid,
                    owner="GROUND",
                    option=option,
                    next_id=next_id,
                    passed=False,
                    value=option.gate,
                    limit="known gate",
                    unit="gate",
                    detail=detail,
                )
            )
        checks.append(_gate_notice_check(public, private, option, next_id))
        return checks

    aircraft_rank = _SIZE_RANK[public.aircraft.size_class]
    gate_rank = _SIZE_RANK[gate.max_size]
    checks.append(
        make_check(
            constraint_id="GND-GATE-01",
            owner="GROUND",
            option=option,
            next_id=next_id,
            passed=aircraft_rank <= gate_rank,
            value=public.aircraft.size_class.value,
            limit=gate.max_size.value,
            unit="size",
            detail=f"{public.aircraft.type_code} ({public.aircraft.size_class.value}) at {gate.gate_id} ({gate.max_size.value})",
        )
    )

    start = option.arrival_slot
    end = option.arrival_slot + private.min_turnaround_min
    conflicts = _overlaps(gate, start, end, buffer_min)
    checks.append(
        make_check(
            constraint_id="GND-GATE-02",
            owner="GROUND",
            option=option,
            next_id=next_id,
            passed=not conflicts,
            value=len(conflicts),
            limit=0,
            unit="conflicts",
            detail=(
                f"{gate.gate_id} occupied {conflicts} during [{start}, {end}) +-{buffer_min} min buffer"
                if conflicts
                else f"{gate.gate_id} free during [{start}, {end}) +-{buffer_min} min buffer"
            ),
        )
    )

    carrier_ok = gate.carrier is None or gate.carrier == public.flight.airline
    checks.append(
        make_check(
            constraint_id="GND-GATE-03",
            owner="GROUND",
            option=option,
            next_id=next_id,
            passed=carrier_ok,
            value=gate.carrier or "COMMON",
            limit=public.flight.airline,
            unit="carrier",
            detail=(
                f"{gate.gate_id} is common-use"
                if gate.carrier is None
                else f"{gate.gate_id} leased to {gate.carrier}"
            ),
        )
    )
    checks.append(_gate_notice_check(public, private, option, next_id))
    return checks
