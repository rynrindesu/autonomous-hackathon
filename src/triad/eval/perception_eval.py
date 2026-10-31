"""Perception evaluation for LLM agents (offline label set + optional live model).

`uv run triad eval-perception --model x-test-4 [--limit N]`
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from triad.agents.llm import LLMAgent
from triad.config import ROOT, RUNS_DIR, load_yaml
from triad.llm.client import LLMClient
from triad.schemas import (
    AgentRole,
    AircraftInfo,
    AtcPrivate,
    DefectReport,
    DisruptionType,
    FlightRecord,
    GroundPrivate,
    Mode,
    PilotPrivate,
    PublicEvent,
    SizeClass,
    WakeCat,
)

EVAL_PATH = ROOT / "corpus" / "eval" / "perception.yaml"
ROLES = (AgentRole.ATC, AgentRole.PILOT, AgentRole.GROUND)


def _public() -> PublicEvent:
    flight = FlightRecord(
        row_index=0,
        year=2015,
        month=1,
        day=1,
        day_of_week=4,
        airline="AA",
        flight_number=1,
        tail_number="N000AA",
        origin="DEN",
        destination="DEN",
        scheduled_departure=480,
        distance=0,
        scheduled_arrival=600,
    )
    aircraft = AircraftInfo(
        type_code="B738",
        wake=WakeCat.M,
        size_class=SizeClass.NARROW,
        seats=162,
        approach_speed_kt=140,
        cruise_burn_kg_min=38.0,
        holding_burn_kg_min=40.0,
    )
    return PublicEvent(
        run_id="eval-perception",
        mode=Mode.GROUND,
        disruption_type=DisruptionType.LATE_AIRCRAFT,
        disruption_summary="perception eval",
        flight=flight,
        aircraft=aircraft,
        decision_time=540,
        original_eta=600,
        expected_eta=600,
        destination_runways=["16L", "16R"],
        public_gate_ids=["A1"],
        alternate_candidates=["COS"],
    )


def _atc_private(text: str) -> AtcPrivate:
    return AtcPrivate(aar_normal=40, aar_reduced=30, slots=[], notam_text=[text])


def _pilot_private(text: str) -> PilotPrivate:
    return PilotPrivate(
        # Workbook fuel_and_crew at 40 kg/min holding: trip + 5% + 30 min reserve + 45 min spare.
        fuel_on_board_kg=6150,
        fuel_to_destination_kg=3000,
        alternate="COS",
        alternate_distance_nm=80,
        fuel_to_alternate_kg=800,
        final_reserve_kg=1200,
        contingency_kg=150,
        max_extra_fuel_kg=1000,
        cruise_levels=[320, 340, 360],
        turbulence_text=[text],
        connections=[],
        pax_notes=[],
        crew_duty_remaining_min=300,
        crew_report_time=60,
    )


def _ground_private(text: str, defect_id: str | None) -> GroundPrivate:
    return GroundPrivate(
        gates=[],
        current_gate="A1",
        shifts=[],
        min_turnaround_min=45,
        next_leg=None,
        defect=DefectReport(defect_id=defect_id or "EVAL", text=text),
        spare_aircraft_available=False,
        gate_change_eur=400.0,
    )


def _load_items(limit: int | None) -> list[dict[str, Any]]:
    raw = yaml.safe_load(EVAL_PATH.read_text(encoding="utf-8")) or {}
    items: list[dict[str, Any]] = []
    for entry in raw.get("atc_notams", []):
        items.append(
            {
                "role": AgentRole.ATC,
                "id": entry["id"],
                "input": entry["input"],
                "expected": entry.get("expected", {}),
                "private": _atc_private(entry["input"]),
            }
        )
    for entry in raw.get("pireps", []):
        items.append(
            {
                "role": AgentRole.PILOT,
                "id": entry["id"],
                "input": entry["input"],
                "expected": entry.get("expected", {}),
                "private": _pilot_private(entry["input"]),
            }
        )
    for entry in raw.get("defects", []):
        items.append(
            {
                "role": AgentRole.GROUND,
                "id": entry["id"],
                "input": entry["input"],
                "expected": entry.get("expected", {}),
                "defect_id": entry.get("defect_id"),
                "private": _ground_private(entry["input"], entry.get("defect_id")),
            }
        )
    return items[:limit] if limit else items


def _safety_fact(role: AgentRole, facts):
    key = {
        AgentRole.ATC: "closed_taxiways",
        AgentRole.PILOT: "turbulence",
        AgentRole.GROUND: "defect",
    }[role]
    return next((fact for fact in facts if fact.key == key), None)


def _correct(role: AgentRole, predicted: Any, expected: dict[str, Any]) -> bool:
    if role is AgentRole.ATC:
        return set(predicted or []) == set(expected.get("closed_taxiways", []))
    if role is AgentRole.PILOT:
        observed = predicted if isinstance(predicted, dict) else {}
        return all(observed.get(level) == value for level, value in expected.items())
    observed = predicted if isinstance(predicted, dict) else {}
    return all(observed.get(key) == value for key, value in expected.items())


def _safe_model_name(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", model)


def evaluate_model(model: str, *, limit: int | None = None) -> dict[str, Any]:
    public = _public()
    client = LLMClient(model=model)
    items = _load_items(limit)
    per_role: dict[str, list[dict[str, Any]]] = {role.value: [] for role in ROLES}

    for item in items:
        role = item["role"]
        agent = LLMAgent(role, item["private"], load_yaml(f"agents/{role.value.lower()}"), client)
        facts = agent.perceive(public)
        fact = _safety_fact(role, facts)
        predicted = fact.value if fact is not None else None
        valid_ids = {chunk.chunk_id for chunk in agent._retrieved_chunks}  # noqa: SLF001
        citation = fact.citation if fact is not None else None
        citation_valid = bool(citation is not None and citation.chunk_id in valid_ids)
        usage = [u for u in agent.usages if u.get("label") == "perceive"]
        per_role[role.value].append(
            {
                "id": item["id"],
                "expected": item["expected"],
                "predicted": predicted,
                "correct": _correct(role, predicted, item["expected"]),
                "source": fact.source if fact is not None else None,
                "conservative_default": fact.conservative_default if fact is not None else None,
                "citation": citation.chunk_id if citation is not None else None,
                "citation_valid": citation_valid,
                "latency_ms": round(sum(float(u.get("ms", 0.0) or 0.0) for u in usage), 1),
                "prompt_tokens": sum(int(u.get("prompt_tokens", 0) or 0) for u in usage),
                "completion_tokens": sum(int(u.get("completion_tokens", 0) or 0) for u in usage),
                "citations_reported": getattr(fact, "key", None) and bool(citation),
            }
        )

    summary: dict[str, Any] = {}
    for role_name, rows in per_role.items():
        total = len(rows)
        correct = sum(1 for row in rows if row["correct"])
        citation_ok = sum(1 for row in rows if row["citation_valid"])
        summary[role_name] = {
            "items": total,
            "correct": correct,
            "accuracy": round(correct / total, 4) if total else 0.0,
            "citation_valid": citation_ok,
            "citation_rate": round(citation_ok / total, 4) if total else 0.0,
            "avg_latency_ms": round(
                sum(row["latency_ms"] for row in rows) / total, 1
            )
            if total
            else 0.0,
            "prompt_tokens": sum(row["prompt_tokens"] for row in rows),
            "completion_tokens": sum(row["completion_tokens"] for row in rows),
            "sources": {
                source: sum(1 for row in rows if row["source"] == source)
                for source in sorted({row["source"] for row in rows})
            },
        }

    result = {
        "model": model,
        "eval_set": str(EVAL_PATH.relative_to(ROOT)),
        "items": per_role,
        "summary": summary,
        "overall": {
            "items": sum(s["items"] for s in summary.values()),
            "correct": sum(s["correct"] for s in summary.values()),
            "accuracy": round(
                sum(s["correct"] for s in summary.values())
                / max(1, sum(s["items"] for s in summary.values())),
                4,
            ),
            "citation_rate": round(
                sum(s["citation_valid"] for s in summary.values())
                / max(1, sum(s["items"] for s in summary.values())),
                4,
            ),
            "avg_latency_ms": round(
                sum(s["avg_latency_ms"] * s["items"] for s in summary.values())
                / max(1, sum(s["items"] for s in summary.values())),
                1,
            ),
            "prompt_tokens": sum(s["prompt_tokens"] for s in summary.values()),
            "completion_tokens": sum(s["completion_tokens"] for s in summary.values()),
        },
    }
    return result


def _print_result(result: dict[str, Any]) -> None:
    print()
    print(f"Perception eval: {result['model']}  ({result['eval_set']})")
    print("  role    items  accuracy  citations  avg_s   tokens (in/out)  sources")
    for role, row in result["summary"].items():
        sources = ", ".join(f"{k}={v}" for k, v in row["sources"].items())
        print(
            f"  {role:<7} {row['items']:>5}  {row['accuracy']:>8.2f}  {row['citation_rate']:>8.2f}"
            f"  {row['avg_latency_ms'] / 1000.0:>6.2f}  {row['prompt_tokens']:>6}/{row['completion_tokens']:<7}"
            f"  {sources}"
        )
    overall = result["overall"]
    print(
        f"  overall {overall['correct']}/{overall['items']} = {overall['accuracy']:.2f}, "
        f"citations {overall['citation_rate']:.2f}, "
        f"{overall['prompt_tokens'] + overall['completion_tokens']} tokens"
    )


def write_result(result: dict[str, Any]) -> Path:
    out_dir = RUNS_DIR / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"perception-{_safe_model_name(result['model'])}.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return path


def eval_main(args: Any) -> None:
    model = getattr(args, "model", None)
    if not model:
        raise SystemExit("error: --model is required")
    limit = getattr(args, "limit", None)
    result = evaluate_model(model, limit=limit)
    _print_result(result)
    path = write_result(result)
    print(f"  wrote {path}")


__all__ = ["eval_main", "evaluate_model", "write_result"]
