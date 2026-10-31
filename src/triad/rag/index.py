"""Tokenisation + BM25 helpers for the per-agent RAG indexes.

Aviation text is full of codes that must survive tokenisation as single terms:
``29-11-01``, ``FL340``, ``121.639``, ``TWY``, ``CLSD``, ``B737``, ``ATA-29``.
We lowercase, keep ``.`` and ``-`` inside a token, and split on everything else.
Only a light stop-word list is removed so numbers and short codes stay searchable.
"""

from __future__ import annotations

import re
from typing import Iterable

from rank_bm25 import BM25Okapi

# Letters/digits joined by dots or hyphens (`29-11-01`, `121.639`, `ata-29`).
# A trailing dot/hyphen is not consumed because every segment needs 1+ chars.
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*", re.IGNORECASE)

# Light list: only common English function words. Deliberately keeps "no", "not",
# "mod", "sev", "lgt", "hvy", etc. because those carry operational meaning.
STOPWORDS: frozenset[str] = frozenset(
    """
    a about after all also an and any are as at be because been before being
    between both but by can could did do does during each either for from had
    has have having he her here his how if in into is it its may might more
    most must of on one only or other our out over same shall she should so
    some such than that the their them then there these they this those
    through to under until up us use used using was we were what when where
    which while who why will with within would you your
    """.split()
)


def tokenize(text: str) -> list[str]:
    """Lowercase and split ``text`` while keeping aviation codes intact."""

    if not text:
        return []
    return [tok for tok in (m.group(0).lower() for m in _TOKEN_RE.finditer(text)) if tok not in STOPWORDS]


def indexable_text(chunk: dict) -> str:
    """Text used for BM25: doc title + section heading + body (heading boost)."""

    parts: Iterable[str | None] = (chunk.get("doc"), chunk.get("section"), chunk.get("text"))
    return "\n".join(p for p in parts if p)


def build_bm25(chunks: list[dict]) -> BM25Okapi | None:
    """Build BM25 over ``chunks``; return ``None`` when there is nothing to index."""

    if not chunks:
        return None
    tokenised = [tokenize(indexable_text(chunk)) for chunk in chunks]
    if not any(tokenised):
        return None
    return BM25Okapi(tokenised)


__all__ = ["STOPWORDS", "build_bm25", "indexable_text", "tokenize"]
