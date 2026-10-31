"""OpenAI-compatible JSON client with response cache and one repair retry.

Environment (.env, then process env):
  LLM_BASE_URL   default https://soclaas-api.comp.nus.edu.sg/v1
  LLM_MODEL      default x-test-2
  LLM_API_KEY    falls back to SOCLAAS_API_KEY
  LLM_TIMEOUT_S  default 90
  LLM_MAX_TOKENS default 1500 (caps runaway generations; 0 disables)
  LLM_CACHE      "0"/"false" disables the cache

API keys are never logged or written to the cache.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from triad.config import CACHE_DIR, ROOT

DEFAULT_BASE_URL = "https://soclaas-api.comp.nus.edu.sg/v1"
DEFAULT_MODEL = "qwen3.6:35b"
DEFAULT_TIMEOUT_S = 90.0
DEFAULT_MAX_TOKENS = 1500


class LLMError(RuntimeError):
    """Raised when the model cannot produce valid JSON after one repair retry."""


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - dependency is declared
        return
    load_dotenv(ROOT / ".env", override=False)


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


Transport = Callable[[dict[str, Any]], tuple[str, dict[str, Any]]]

_BOUND_KEYS = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum")
_SUBSCHEMA_MAPS = ("properties", "$defs", "definitions")
_SUBSCHEMA_LISTS = ("anyOf", "oneOf", "allOf", "prefixItems")


def _fmt_bound(value: Any) -> str:
    return f"{value:g}" if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value)


def _bounds_text(bounds: dict[str, Any]) -> str:
    parts = []
    for key, label in (
        ("minimum", ">="),
        ("exclusiveMinimum", ">"),
        ("maximum", "<="),
        ("exclusiveMaximum", "<"),
    ):
        if key in bounds:
            parts.append(f"{label} {_fmt_bound(bounds[key])}")
    return "Range: " + ", ".join(parts) + "."


def _bounds_already_described(description: str, bounds: dict[str, Any]) -> bool:
    lo = bounds.get("minimum", bounds.get("exclusiveMinimum"))
    hi = bounds.get("maximum", bounds.get("exclusiveMaximum"))
    if lo is not None and hi is not None:
        return f"{_fmt_bound(lo)}..{_fmt_bound(hi)}" in description
    return False


def _sanitize_node(node: Any) -> None:
    if isinstance(node, list):
        for item in node:
            _sanitize_node(item)
        return
    if not isinstance(node, dict):
        return

    bounds = {key: node.pop(key) for key in _BOUND_KEYS if key in node}
    if bounds:
        description = str(node.get("description") or "")
        if not _bounds_already_described(description, bounds):
            text = _bounds_text(bounds)
            node["description"] = f"{description} {text}".strip() if description else text

    if node.get("type") == "object" or "properties" in node:
        # Strict providers reject open objects and map schemas
        # (``additionalProperties: {...}``); every object is closed.
        node["additionalProperties"] = False

    for key in _SUBSCHEMA_MAPS:
        children = node.get(key)
        if isinstance(children, dict):
            for child in children.values():
                _sanitize_node(child)
    for key in _SUBSCHEMA_LISTS:
        _sanitize_node(node.get(key))
    if "items" in node:
        _sanitize_node(node["items"])


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a deep copy of ``schema`` that strict ``json_schema`` providers accept.

    Anthropic's OpenAI-compatible endpoint (and other strict structured-output
    backends) require ``strict: true``, ``additionalProperties: false`` on every
    object, and reject numeric ``minimum``/``maximum`` keywords.  This only
    rewrites the *transmitted* schema: Pydantic still enforces ``ge``/``le`` when
    the response is parsed, and a removed bound is restated in ``description``.
    Map-typed fields (``dict[str, X]``) cannot be expressed and are closed to
    ``{}``; output models must use lists of objects instead.
    """
    copied = copy.deepcopy(schema)
    _sanitize_node(copied)
    return copied


class LLMClient:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        cache: bool = True,
        cache_dir: Path | str = CACHE_DIR / "llm",
        transport: Transport | None = None,
    ) -> None:
        _load_env()
        self.base_url = base_url or os.getenv("LLM_BASE_URL") or DEFAULT_BASE_URL
        self.model = model or os.getenv("LLM_MODEL") or DEFAULT_MODEL
        self.api_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("SOCLAAS_API_KEY") or ""
        raw_timeout = os.getenv("LLM_TIMEOUT_S")
        self.timeout = float(timeout if timeout is not None else (raw_timeout or DEFAULT_TIMEOUT_S))
        raw_max = os.getenv("LLM_MAX_TOKENS")
        self.max_tokens = int(raw_max) if raw_max not in (None, "") else DEFAULT_MAX_TOKENS
        self.cache = bool(cache) and _env_bool("LLM_CACHE", True)
        self.cache_dir = Path(cache_dir)
        self._transport = transport
        if self.cache:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ public
    def complete_json(
        self,
        system: str,
        user: str,
        out: type[BaseModel],
        *,
        name: str,
    ) -> tuple[BaseModel, dict[str, Any]]:
        schema_json = _canonical(out.model_json_schema())
        key = hashlib.sha256(
            f"{self.model}|{system}|{user}|{schema_json}".encode("utf-8")
        ).hexdigest()
        cache_path = self.cache_dir / f"{key}.json"

        if self.cache and cache_path.exists():
            cached = self._read_cache(cache_path, out)
            if cached is not None:
                model, usage = cached
                usage = {**usage, "cached": True, "ms": 0.0}
                return model, usage

        response_format = self._json_schema_format(out, name)
        prompt_tokens = 0
        completion_tokens = 0
        total_ms = 0.0
        repaired = False
        current_user = user
        last_error: Exception | None = None

        # initial try + exactly one repair retry
        for attempt in range(2):
            try:
                content, raw_usage, ms = self._request(
                    system, current_user, response_format
                )
            except Exception as exc:  # noqa: BLE001 - transport/network/server failure
                raise LLMError(f"{name}: LLM request failed: {type(exc).__name__}: {exc}") from exc

            prompt_tokens += int(raw_usage.get("prompt_tokens", 0) or 0)
            completion_tokens += int(raw_usage.get("completion_tokens", 0) or 0)
            total_ms += ms

            try:
                payload = json.loads(content)
                model = out.model_validate(payload)
            except (json.JSONDecodeError, ValidationError, TypeError) as exc:
                last_error = exc
                if attempt == 0:
                    repaired = True
                    current_user = (
                        f"{user}\n\n"
                        "Your previous response was not valid JSON for the required schema.\n"
                        f"Validation error: {exc}\n"
                        "Return only corrected JSON that matches the schema exactly."
                    )
                    continue
                break

            usage = {
                "model": self.model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "ms": round(total_ms, 1),
                "cached": False,
                "repaired": repaired,
            }
            if self.cache:
                self._write_cache(cache_path, model, usage)
            return model, usage

        raise LLMError(f"{name}: invalid JSON after repair retry: {last_error}")

    # ------------------------------------------------------------------ request
    def _request(
        self, system: str, user: str, json_schema_format: dict[str, Any]
    ) -> tuple[str, dict[str, Any], float]:
        """Call the transport, falling back to plain json_object on schema rejection.

        Some providers (e.g. Anthropic's OpenAI-compatible endpoint) accept only
        ``json_schema``; when the json_object fallback is rejected too, the
        original schema error is re-raised so the real cause surfaces.
        """
        attempts = [
            json_schema_format,
            {"type": "json_object"},
        ]
        first_exc: Exception | None = None
        for index, response_format in enumerate(attempts):
            kwargs = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
                "seed": 7,
                "response_format": response_format,
            }
            if self.max_tokens > 0:
                kwargs["max_tokens"] = self.max_tokens
            started = time.perf_counter()
            try:
                content, usage = self._invoke(kwargs)
            except Exception as exc:  # noqa: BLE001
                if index == 0 and self._is_schema_rejection(exc):
                    first_exc = exc
                    continue
                if first_exc is not None:
                    raise first_exc from exc
                raise
            ms = (time.perf_counter() - started) * 1000.0
            return content, usage, ms
        raise first_exc or LLMError("LLM request failed")

    def _invoke(self, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if self._transport is not None:
            result = self._transport(kwargs)
        else:
            result = self._openai_transport(kwargs)
        if isinstance(result, str):
            return result, {}
        content, usage = result
        return content, dict(usage or {})

    def _openai_transport(self, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        if not self.api_key:
            raise LLMError("LLM_API_KEY (or SOCLAAS_API_KEY) is not set")
        from openai import OpenAI

        client = OpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            timeout=self.timeout,
            max_retries=0,
        )
        response = client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""
        usage = getattr(response, "usage", None)
        return content, {
            "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        }

    @staticmethod
    def _json_schema_format(out: type[BaseModel], name: str) -> dict[str, Any]:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": name,
                "schema": strict_schema(out.model_json_schema()),
                "strict": True,
            },
        }

    @staticmethod
    def _is_schema_rejection(exc: Exception) -> bool:
        text = f"{type(exc).__name__}: {exc}".lower()
        markers = (
            "response_format",
            "json_schema",
            "json schema",
            "schema",
            "unsupported",
            "not supported",
        )
        return any(marker in text for marker in markers)

    # ------------------------------------------------------------------ cache
    def _read_cache(
        self, path: Path, out: type[BaseModel]
    ) -> tuple[BaseModel, dict[str, Any]] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            model = out.model_validate(data["result"])
            usage = dict(data.get("usage") or {})
            return model, usage
        except Exception:  # noqa: BLE001 - corrupt/old cache is a miss
            return None

    def _write_cache(self, path: Path, model: BaseModel, usage: dict[str, Any]) -> None:
        try:
            path.write_text(
                json.dumps(
                    {"result": model.model_dump(mode="json"), "usage": usage},
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass


__all__ = ["LLMClient", "LLMError", "Transport", "strict_schema"]
