from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from triad.llm.client import LLMClient, LLMError


class Answer(BaseModel):
    answer: int
    note: str = ""


def scripted(responses):
    calls: list[dict] = []

    def transport(kwargs):
        calls.append(kwargs)
        index = min(len(calls) - 1, len(responses) - 1)
        item = responses[index]
        if isinstance(item, Exception):
            raise item
        return item

    return transport, calls


def test_cache_hit_skips_transport_and_marks_cached(tmp_path):
    transport, calls = scripted([(json.dumps({"answer": 1}), {"prompt_tokens": 10, "completion_tokens": 2})])
    client = LLMClient(model="m", api_key="k", cache_dir=tmp_path, transport=transport)

    first, usage1 = client.complete_json("sys", "user", Answer, name="answer")
    second, usage2 = client.complete_json("sys", "user", Answer, name="answer")

    assert isinstance(first, Answer) and first.answer == 1
    assert second == first
    assert usage1["cached"] is False
    assert usage2["cached"] is True
    assert usage2["ms"] == 0.0
    assert len(calls) == 1
    # no API key in the cache file
    contents = " ".join(p.read_text() for p in tmp_path.glob("*.json"))
    assert '"k"' not in contents and "api_key" not in contents


def test_repair_retry_appends_validation_error(tmp_path):
    transport, calls = scripted(
        [
            ("not json", {"prompt_tokens": 5, "completion_tokens": 1}),
            (json.dumps({"answer": 2}), {"prompt_tokens": 6, "completion_tokens": 2}),
        ]
    )
    client = LLMClient(model="m", api_key="k", cache_dir=tmp_path, transport=transport)

    result, usage = client.complete_json("sys", "user", Answer, name="answer")

    assert result.answer == 2
    assert usage["repaired"] is True
    assert usage["prompt_tokens"] == 11
    assert len(calls) == 2
    assert "previous response was not valid" in calls[1]["messages"][1]["content"]


def test_llm_error_after_two_bad_responses(tmp_path):
    transport, calls = scripted([("nope", {}), ("still nope", {})])
    client = LLMClient(model="m", api_key="k", cache_dir=tmp_path, transport=transport)

    with pytest.raises(LLMError):
        client.complete_json("sys", "user", Answer, name="answer")
    assert len(calls) == 2


def test_falls_back_to_json_object_when_schema_is_rejected(tmp_path):
    """Providers without json_schema support still work via json_object."""

    def transport(kwargs):
        transport.calls += 1
        if kwargs["response_format"]["type"] == "json_schema":
            assert kwargs["response_format"]["json_schema"]["strict"] is True
            raise ValueError("response_format json_schema is unsupported")
        return json.dumps({"answer": 3}), {"prompt_tokens": 1, "completion_tokens": 1}

    transport.calls = 0  # type: ignore[attr-defined]
    client = LLMClient(model="m", api_key="k", cache_dir=tmp_path, transport=transport)

    result, _usage = client.complete_json("sys", "user", Answer, name="answer")

    assert result.answer == 3
    assert transport.calls == 2  # type: ignore[attr-defined]


def test_schema_error_surfaces_when_json_object_is_also_rejected(tmp_path):
    """json_schema-only providers (Anthropic): report the schema error, not the fallback's."""
    schema_error = ValueError(
        "Error code: 400 - response_format.json_schema.strict: Input should be True"
    )

    def transport(kwargs):
        transport.calls += 1
        if kwargs["response_format"]["type"] == "json_schema":
            raise schema_error
        raise ValueError("response_format.type: Input should be 'json_schema'")

    transport.calls = 0  # type: ignore[attr-defined]
    client = LLMClient(model="m", api_key="k", cache_dir=tmp_path, transport=transport)

    with pytest.raises(LLMError) as info:
        client.complete_json("sys", "user", Answer, name="answer")

    assert "strict: Input should be True" in str(info.value)
    assert transport.calls == 2  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "message",
    [
        "response_format.json_schema.strict: Input should be True",
        "For 'object' type, 'additionalProperties: true' is not supported",
        "For 'number' type, properties maximum, minimum are not supported",
        "additionalProperties: object is not supported",
    ],
)
def test_strict_schema_errors_count_as_schema_rejection(message):
    assert LLMClient._is_schema_rejection(ValueError(message)) is True
