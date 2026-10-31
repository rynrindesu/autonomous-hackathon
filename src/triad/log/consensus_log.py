"""Hash-chained consensus log.

Chain definition
----------------
Let ``payload_sha256`` be ``sha256(canonical_json(payload))`` and let ``chain`` be
the value carried forward to the next entry::

    chain_0 = "0" * 64
    chain_i = sha256(chain_{i-1} + payload_sha256_i)

``LogEntry.prev_sha256`` stores ``chain_{i-1}``.  ``verify`` recomputes both the
payload digest and the chain, so tampering with either the payload or the chain
link is detected.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from triad.schemas import LogEntry

ZERO_CHAIN = "0" * 64


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def sha256_json(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def chain_hash(prev: str, payload_sha256: str) -> str:
    return hashlib.sha256(f"{prev}{payload_sha256}".encode("utf-8")).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class ConsensusLog:
    """Append-only, hash-chained JSONL log. Optionally persists to ``run_dir/log.jsonl``."""

    def __init__(
        self,
        run_id: str,
        run_dir: Path | None = None,
        *,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self.run_id = run_id
        self.run_dir = Path(run_dir) if run_dir is not None else None
        self.entries: list[LogEntry] = []
        self._clock = clock or utc_now_iso
        self._chain = ZERO_CHAIN
        if self.run_dir is not None:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            # Start a fresh log for this run.
            (self.run_dir / "log.jsonl").write_text("", encoding="utf-8")

    @classmethod
    def resume(cls, run_dir: Path | str, *, clock: Callable[[], str] | None = None) -> "ConsensusLog":
        """Reopen an existing ``run_dir/log.jsonl`` for appending, continuing its hash chain."""
        run_dir = Path(run_dir)
        entries = _load_entries(run_dir / "log.jsonl")
        if not cls.verify(entries):
            raise ValueError(f"refusing to extend a log that fails verify(): {run_dir}")
        log = cls(entries[0].run_id if entries else run_dir.name, clock=clock)
        log.run_dir = run_dir  # set after __init__ so the existing file is not truncated
        log.entries = entries
        for entry in entries:
            log._chain = chain_hash(log._chain, entry.payload_sha256)
        return log

    # ------------------------------------------------------------------ append
    def append(
        self,
        turn: int,
        actor: str,
        event: str,
        payload: dict[str, Any],
        context_manifest: dict[str, str] | None = None,
        usage: dict[str, Any] | None = None,
    ) -> LogEntry:
        # Normalise to JSON-native types so the hash recomputed from disk matches.
        payload = json.loads(canonical_json(payload))
        payload_sha = sha256_json(payload)
        prev = self._chain
        entry = LogEntry(
            seq=len(self.entries) + 1,
            ts=self._clock(),
            run_id=self.run_id,
            turn=turn,
            actor=actor,  # validated by LogEntry
            event=event,
            payload=payload,
            payload_sha256=payload_sha,
            prev_sha256=prev,
            context_manifest=context_manifest,
            usage=usage,
        )
        self.entries.append(entry)
        self._chain = chain_hash(prev, payload_sha)
        if self.run_dir is not None:
            with open(self.run_dir / "log.jsonl", "a", encoding="utf-8") as f:
                f.write(entry.model_dump_json() + "\n")
        return entry

    # ------------------------------------------------------------------ verify
    @staticmethod
    def verify(entries_or_path: "Sequence[LogEntry | dict[str, Any]] | Path | str") -> bool:
        try:
            entries = _load_entries(entries_or_path)
            expected_prev = ZERO_CHAIN
            for entry in entries:
                if entry.prev_sha256 != expected_prev:
                    return False
                payload_sha = sha256_json(entry.payload)
                if payload_sha != entry.payload_sha256:
                    return False
                expected_prev = chain_hash(expected_prev, payload_sha)
            return True
        except Exception:
            return False


def _load_entries(source: "Sequence[LogEntry | dict[str, Any]] | Path | str") -> list[LogEntry]:
    if isinstance(source, (str, Path)):
        path = Path(source)
        entries: list[LogEntry] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    entries.append(LogEntry.model_validate(json.loads(line)))
        return entries
    out: list[LogEntry] = []
    for item in source:
        out.append(item if isinstance(item, LogEntry) else LogEntry.model_validate(item))
    return out
