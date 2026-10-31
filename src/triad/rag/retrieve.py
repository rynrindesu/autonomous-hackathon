"""Per-agent BM25 retrieval over the role's own corpus only.

The contract (frozen in ``types.py``) is::

    retrieve(role: AgentRole, query: str, k: int = 4) -> list[RetrievedChunk]

Each role has its own index in ``.cache/rag/<role>.json``. If the cache is
missing or the corpus hash changed, the index is rebuilt from ``corpus/<role>``
before searching. A role with no corpus returns an empty list.

Ordering is deterministic: score descending, then ``chunk_id`` ascending.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from triad.rag import ingest, index
from triad.rag.types import AgentRole, RetrievedChunk


@lru_cache(maxsize=8)
def _load_role(role_name: str) -> tuple[str, list[dict[str, Any]], Any]:
    """Load (and if needed build) one role's chunks + BM25 model."""

    payload = ingest.load_role_index(role_name)
    chunks = payload.get("chunks", [])
    bm25 = index.build_bm25(chunks)
    return str(payload.get("corpus_sha256", "")), chunks, bm25


def retrieve(role: AgentRole, query: str, k: int = 4) -> list[RetrievedChunk]:
    """Search only ``role``'s corpus. Returns ``[]`` when the corpus is empty."""

    if k <= 0:
        return []
    role_name = ingest.role_key(role)
    _sha, chunks, bm25 = _load_role(role_name)
    if not chunks or bm25 is None:
        return []

    query_tokens = index.tokenize(query or "")
    if not query_tokens:
        return []

    scores = bm25.get_scores(query_tokens)
    # A query with no lexical overlap produces all-zero (or all-negative)
    # scores. Returning arbitrary chunks in that case would create misleading
    # citations, so treat it as "no match" instead.
    if max((float(score) for score in scores), default=0.0) <= 0.0:
        return []

    order = sorted(
        range(len(chunks)),
        key=lambda i: (-float(scores[i]), str(chunks[i].get("chunk_id", ""))),
    )

    results: list[RetrievedChunk] = []
    for i in order[:k]:
        chunk = chunks[i]
        if float(scores[i]) <= 0.0:
            continue
        results.append(
            RetrievedChunk(
                chunk_id=str(chunk["chunk_id"]),
                doc=str(chunk.get("doc", "")),
                section=chunk.get("section"),
                text=str(chunk.get("text", "")),
                url=chunk.get("url"),
                synthetic=bool(chunk.get("synthetic", False)),
                score=float(scores[i]),
            )
        )
    return results


def corpus_sha256() -> str:
    """Combined corpus hash for run manifests (all three role corpora)."""

    return ingest.corpus_sha256()


def clear_caches() -> None:
    """Drop the cached role indexes (used by tests after monkeypatching paths)."""

    _load_role.cache_clear()


__all__ = ["clear_caches", "corpus_sha256", "retrieve", "AgentRole"]
