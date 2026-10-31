"""Ground MEL / defect check (GND-MEL-01)."""

from __future__ import annotations

from typing import Callable

from triad.constraints.shared import earliest_departure_min, is_divert, make_check
from triad.schemas import CandidateOption, ConstraintCheck, GroundPrivate, Mode, PerceivedFact, PublicEvent


def check_mel(
    public: PublicEvent,
    private: GroundPrivate,
    facts: dict[str, PerceivedFact],
    option: CandidateOption,
    next_id: Callable[[], str],
) -> list[ConstraintCheck]:
    if public.mode != Mode.GROUND or private.defect is None or is_divert(option):
        return [
            make_check(
                constraint_id="GND-MEL-01",
                owner="GROUND",
                option=option,
                next_id=next_id,
                passed=True,
                value="no defect" if private.defect is None else "not departing",
                limit="n/a",
                unit="min",
                detail=(
                    "divert: aircraft does not depart on the planned next leg"
                    if is_divert(option)
                    else "no MEL action required for this option"
                ),
                facts_used=["defect"],
            )
        ]

    fact = facts.get("defect")
    defect = fact.value if fact is not None and isinstance(fact.value, dict) else None
    if not defect:  # no perceived defect -> nothing to defer
        return [
            make_check(
                constraint_id="GND-MEL-01",
                owner="GROUND",
                option=option,
                next_id=next_id,
                passed=True,
                value="no defect",
                limit="n/a",
                unit="min",
                detail="perception reports no defect",
                facts_used=["defect"],
            )
        ]

    deferrable = bool(defect.get("deferrable"))
    repair_min = int(defect.get("repair_min") or 60)

    if deferrable:
        return [
            make_check(
                constraint_id="GND-MEL-01",
                owner="GROUND",
                option=option,
                next_id=next_id,
                passed=True,
                value="deferrable",
                limit="n/a",
                unit="min",
                detail=(
                    f"MEL item {defect.get('mel_item')} category "
                    f"{defect.get('mel_category')} may be deferred"
                ),
                facts_used=["defect"],
            )
        ]

    departure = option.departure_slot
    required = earliest_departure_min(public.flight) + repair_min
    passed = departure is not None and departure >= required
    return [
        make_check(
            constraint_id="GND-MEL-01",
            owner="GROUND",
            option=option,
            next_id=next_id,
            passed=passed,
            value=departure if departure is not None else "missing",
            limit=required,
            unit="min",
            detail=(
                f"non-deferrable MEL item {defect.get('mel_item')} needs {repair_min} min repair; "
                f"earliest departure {earliest_departure_min(public.flight)}"
            ),
            facts_used=["defect"],
        )
    ]
