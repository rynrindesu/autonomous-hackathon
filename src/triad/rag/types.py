"""RAG contract (frozen). Implemented in triad.rag.retrieve; consumed by LLM agents."""

from __future__ import annotations

from pydantic import BaseModel

from triad.schemas import AgentRole, Citation


class RetrievedChunk(BaseModel):
    chunk_id: str
    doc: str
    section: str | None = None
    text: str
    url: str | None = None
    synthetic: bool = False
    score: float = 0.0

    def citation(self) -> Citation:
        return Citation(doc=self.doc, chunk_id=self.chunk_id, section=self.section, url=self.url, synthetic=self.synthetic)


# Implemented in triad/rag/retrieve.py:
#   def retrieve(role: AgentRole, query: str, k: int = 4) -> list[RetrievedChunk]
#       Per-agent BM25 index only (ATC never sees Pilot/Ground docs). Returns [] if the index is missing.
__all__ = ["RetrievedChunk", "AgentRole"]
