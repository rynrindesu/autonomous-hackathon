"""Ground gate checks: size, occupancy overlap (with buffer) and carrier rights."""

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
    return checks
