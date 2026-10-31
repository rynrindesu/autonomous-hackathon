"""Deterministic option generator.

This module sees **only** ``PublicEvent``: no slots, fuel, gates or crew data.
The 5-minute slot grid is shared by the ATC scenario builder so generated times
land on real slots; role checkers discover whether a slot is taken or a fuel
plan is safe.
"""

from __future__ import annotations

from triad.config import load_yaml
from triad.constraints.runway import slot_grid_start
from triad.schemas import CandidateOption, Mode, PublicEvent


def _scheduled_time(flight) -> int:
    if flight.scheduled_time is not None and flight.scheduled_time > 0:
        return int(flight.scheduled_time)
    diff = int(flight.scheduled_arrival) - int(flight.scheduled_departure)
    return diff if diff > 0 else max(1, diff + 1440)


def _public_gates(public: PublicEvent) -> list[str]:
    # Current gate first (by enrich convention) plus a handful of alternates.
    return list(public.public_gate_ids)[:5] or ["A1"]


def _min_turnaround(public: PublicEvent) -> int:
    ground_cfg = load_yaml("synthetic")["ground"]
    return int(ground_cfg["min_turnaround_min"][public.aircraft.size_class.value])


def _propagated_delay(arrival: int, public: PublicEvent) -> int:
    """Public-only heuristic: pass the arrival delay on to the next leg (rounded up to 5 min).
    The Ground agent refines this with its private next-leg data via a counter-option."""
    late = max(0, arrival - int(public.original_eta))
    return max(5, -(-late // 5) * 5)


def _airborne(public: PublicEvent) -> list[CandidateOption]:
    cfg = load_yaml("synthetic")["fuel"]
    expected = int(public.expected_eta)
    base = slot_grid_start(expected, 5)
    max_absorb = max(
        0, int(cfg["enroute_absorb_max_frac"] * max(0, expected - public.decision_time))
    )
    runways = list(public.destination_runways) or ["09"]
    gates = _public_gates(public)
    levels = list(cfg["cruise_levels"])

    offsets = [0, 5, 10, 15, 20, 30, 40, 50, 60, 70, 80, 90]
    options: list[CandidateOption] = []
    for i, offset in enumerate(offsets):
        arrival = base + offset
        total_delay = arrival - expected
        # Alternate between holding-only and fully-absorbed variants.
        absorb = min(total_delay, max_absorb) if i % 2 == 1 else 0
        holding = total_delay - absorb
        runway = runways[i % len(runways)]
        gate = gates[i % len(gates)]
        level = None if i % 4 == 0 else levels[(i // 2) % len(levels)]
        if total_delay >= 30 and i % 7 == 4:
            action = "SWAP_AIRCRAFT"
            delay_min = 0
        elif i % 3 == 2 and total_delay >= 25:
            action = "DELAY"
            delay_min = _propagated_delay(arrival, public)
        else:
            action = "KEEP"
            delay_min = 0
        options.append(
            CandidateOption(
                option_id=f"OPT-{len(options) + 1:02d}",
                mode=Mode.AIRBORNE,
                arrival_slot=arrival,
                runway=runway,
                holding_min=holding,
                enroute_absorb_min=absorb,
                cruise_level=level,
                gate=gate,
                next_leg_action=action,  # type: ignore[arg-type]
                next_leg_delay_min=delay_min,
            )
        )
    return options


def _ground(public: PublicEvent) -> list[CandidateOption]:
    cfg = load_yaml("synthetic")["fuel"]
    flight = public.flight
    earliest = int(flight.scheduled_departure) + int(flight.late_aircraft_delay)
    base = slot_grid_start(earliest, 5)
    sched_time = _scheduled_time(flight)
    max_recovery = (max(0, int(cfg["speed_recovery_max_frac"] * sched_time)) // 5) * 5
    runways = list(public.destination_runways) or ["09"]
    gates = _public_gates(public)
    levels = list(cfg["cruise_levels"])

    offsets = [0, 5, 10, 15, 20, 30, 45, 60, 75, 90, 105, 120]
    options: list[CandidateOption] = []
    for i, offset in enumerate(offsets):
        departure = base + offset
        recovery = max_recovery if i % 3 == 2 else 0
        arrival = departure + sched_time - recovery
        runway = runways[i % len(runways)]
        gate = gates[i % len(gates)]
        level = None if i % 4 == 0 else levels[(i // 2) % len(levels)]
        if offset >= 30 and i % 7 == 4:
            action = "SWAP_AIRCRAFT"
            delay_min = 0
        elif i % 2 == 0 and offset >= 30:
            action = "DELAY"
            delay_min = _propagated_delay(arrival, public)
        else:
            action = "KEEP"
            delay_min = 0
        options.append(
            CandidateOption(
                option_id=f"OPT-{len(options) + 1:02d}",
                mode=Mode.GROUND,
                departure_slot=departure,
                arrival_slot=arrival,
                runway=runway,
                speed_recovery_min=recovery,
                cruise_level=level,
                gate=gate,
                next_leg_action=action,  # type: ignore[arg-type]
                next_leg_delay_min=delay_min,
            )
        )
    return options


def _divert(public: PublicEvent) -> CandidateOption:
    return CandidateOption(
        option_id="OPT-DIV",
        mode=public.mode,
        departure_slot=(
            int(public.flight.scheduled_departure) + int(public.flight.late_aircraft_delay)
            if public.mode == Mode.GROUND
            else None
        ),
        arrival_slot=int(public.expected_eta) + 45,
        runway=(public.destination_runways or ["09"])[0],
        gate=(_public_gates(public))[0],
        divert_to=(
            public.alternate_candidates[0]
            if public.alternate_candidates
            else public.flight.destination
        ),
        next_leg_action="KEEP",
    )


def generate_options(public: PublicEvent) -> list[CandidateOption]:
    """6-12 numbered options plus one last-resort divert, deterministic order."""

    if public.mode == Mode.AIRBORNE:
        options = _airborne(public)
    else:
        options = _ground(public)
    options.append(_divert(public))
    return options
