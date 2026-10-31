from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from triad.llm.client import DEFAULT_BASE_URL, LLMClient, LLMError


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
    def transport(kwargs):
        transport.calls += 1
        if kwargs["response_format"]["type"] == "json_schema":
            raise ValueError("response_format json_schema is unsupported")
        return json.dumps({"answer": 3}), {"prompt_tokens": 1, "completion_tokens": 1}

    transport.calls = 0  # type: ignore[attr-defined]
    client = LLMClient(
        base_url=DEFAULT_BASE_URL, model="m", api_key="k", cache_dir=tmp_path, transport=transport
    )

    result, _usage = client.complete_json("sys", "user", Answer, name="answer")

    assert result.answer == 3
    assert transport.calls == 2  # type: ignore[attr-defined]


def test_anthropic_endpoint_sends_plain_request_and_strips_code_fence(tmp_path):
    transport, calls = scripted([('```json\n{"answer": 4}\n```', {"prompt_tokens": 1, "completion_tokens": 1})])
    client = LLMClient(
        base_url="https://api.anthropic.com/v1/",
        model="m",
        api_key="k",
        cache_dir=tmp_path,
        transport=transport,
    )

    result, _usage = client.complete_json("sys", "user", Answer, name="answer")

    assert result.answer == 4
    assert len(calls) == 1
    for key in ("response_format", "temperature", "seed"):
        assert key not in calls[0]
