"""Strict json_schema compatibility (Anthropic OpenAI-compatible endpoint).

The endpoint requires ``strict: true``, ``additionalProperties: false`` on every
object, and rejects ``minimum``/``maximum`` and map (dict) schemas.
"""

from __future__ import annotations

from typing import Any

import pytest
from fakes import make_option
from pydantic import ValidationError
from test_llm_agent import ScriptedClient, make_agent, patch_retrieve, patch_scores

from triad.agents.llm_schemas import (
    AtcPerception,
    ChangeOut,
    CounterOut,
    GroundPerception,
    ObjectionOut,
    PilotPerception,
    TurbulenceOut,
    Turn1Decision,
    Turn2Decision,
    Turn3Decision,
    VoteOut,
)
from triad.agents.perception import stub_perceive
from triad.llm.client import LLMClient, strict_schema
from triad.rag.types import RetrievedChunk
from triad.schemas import AgentRole

LLM_OUTPUT_MODELS = [
    Turn1Decision,
    Turn2Decision,
    Turn3Decision,
    VoteOut,
    ObjectionOut,
    CounterOut,
    AtcPerception,
    PilotPerception,
    GroundPerception,
    TurbulenceOut,
    ChangeOut,
]
_BOUNDS = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"}


def _schema_nodes(node: Any):
    """Yield every schema node (not property-name maps)."""
    if isinstance(node, list):
        for item in node:
            yield from _schema_nodes(item)
        return
    if not isinstance(node, dict):
        return
    yield node
    for key in ("properties", "$defs"):
        for child in (node.get(key) or {}).values():
            yield from _schema_nodes(child)
    for key in ("anyOf", "oneOf", "allOf"):
        yield from _schema_nodes(node.get(key))
    if "items" in node:
        yield from _schema_nodes(node["items"])
    if isinstance(node.get("additionalProperties"), dict):
        yield from _schema_nodes(node["additionalProperties"])


@pytest.mark.parametrize("model", LLM_OUTPUT_MODELS, ids=lambda m: m.__name__)
def test_llm_output_models_satisfy_strict_schema_rules(model):
    raw = model.model_json_schema()
    # no map-typed fields in the source models either
    for node in _schema_nodes(raw):
        assert not isinstance(node.get("additionalProperties"), dict), model.__name__

    fmt = LLMClient._json_schema_format(model, model.__name__)
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    schema = fmt["json_schema"]["schema"]
    assert schema == strict_schema(raw)

    objects = 0
    for node in _schema_nodes(schema):
        assert not (_BOUNDS & set(node)), (model.__name__, node)
        if node.get("type") == "object" or "properties" in node:
            objects += 1
            assert node.get("additionalProperties") is False, (model.__name__, node)
    assert objects >= 1


def test_strict_schema_moves_bounds_into_description_and_keeps_pydantic_bounds():
    schema = strict_schema(AtcPerception.model_json_schema())
    confidence = schema["properties"]["confidence"]
    assert "0..1" in confidence["description"]  # already described: not repeated
    assert "Range" not in confidence["description"]
    with pytest.raises(ValidationError):
        AtcPerception.model_validate({"confidence": 1.5, "citations": []})

    bare = strict_schema(
        {"type": "object", "properties": {"x": {"type": "number", "minimum": 2, "maximum": 5}}}
    )
    assert bare["properties"]["x"] == {"type": "number", "description": "Range: >= 2, <= 5."}
    assert bare["additionalProperties"] is False


def test_strict_schema_does_not_mutate_input():
    raw = PilotPerception.model_json_schema()
    before = repr(raw)
    strict_schema(raw)
    assert repr(raw) == before


# --------------------------------------------------------------------------- round trips


def test_pilot_perception_list_shape_round_trips_to_turbulence_fact(monkeypatch):
    chunks = [RetrievedChunk(chunk_id="turb-1", doc="PIREP", text="FL340 light chop")]
    patch_retrieve(monkeypatch, {AgentRole.PILOT: chunks})
    payload = {
        "turbulence": [
            {"flight_level": "FL340", "level": "LIGHT"},
            {"flight_level": "FL360", "level": "SEVERE"},
        ],
        "flagged_notes": [],
        "confidence": 0.9,
        "citations": ["turb-1"],
        "notes": "",
    }
    perception = PilotPerception.model_validate(payload)
    assert perception.turbulence_map() == {"FL340": "LIGHT", "FL360": "SEVERE"}
    # legacy object shape still parses to the same thing
    legacy = PilotPerception.model_validate(
        {**payload, "turbulence": {"FL340": "LIGHT", "FL360": "SEVERE"}}
    )
    assert legacy.turbulence_map() == perception.turbulence_map()

    event, agent = make_agent(AgentRole.PILOT, ScriptedClient({"pilot_perceive": payload}))
    fact = next(f for f in agent.perceive(event.public) if f.key == "turbulence")
    assert fact.source == "LLM"
    assert fact.value == {"FL340": "LIGHT", "FL360": "SEVERE"}


def _turn2_counter(changes: Any):
    event, agent = make_agent(AgentRole.ATC, ScriptedClient({}))
    agent._facts = stub_perceive(AgentRole.ATC, event.public, event.atc)
    patch_scores(agent, fail_ids=set())
    agent.client.handlers["atc_turn2"] = {
        "votes": [
            {"option_id": "OPT-01", "vote": "DISAPPROVE", "reason": "THROUGHPUT: slot too late"},
            {"option_id": "OPT-03", "vote": "APPROVE"},
        ],
        "ranking": ["OPT-03"],
        "counter": {"base_option_id": "OPT-01", "changes": changes},
        "rationale": "OPT-01 works on the parallel runway.",
    }
    ballot = agent.turn2(event.public, [make_option("OPT-01"), make_option("OPT-03")], [])
    return ballot.counter_option


def test_counter_list_shape_changes_match_legacy_dict_changes():
    listed = _turn2_counter(
        [
            {"key": "runway", "value": "17L"},
            {"key": "arrival_slot", "value": "09:55"},
            {"key": "holding_min", "value": "5"},
        ]
    )
    legacy = _turn2_counter({"runway": "17L", "arrival_slot": "09:55", "holding_min": 5})

    assert listed is not None and legacy is not None
    assert listed.changes == legacy.changes == {
        "runway": "17L",
        "arrival_slot": 595,
        "holding_min": 5,
    }
    assert isinstance(listed.changes["holding_min"], int)


def test_counter_out_changes_dict_maps_null_text_to_none():
    counter = CounterOut.model_validate(
        {"base_option_id": "OPT-01", "changes": [{"key": "cruise_level", "value": "null"}]}
    )
    assert counter.changes_dict() == {"cruise_level": None}
