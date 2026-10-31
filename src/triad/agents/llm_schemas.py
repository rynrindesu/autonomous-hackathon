"""Pydantic I/O models for the LLM agents.

These are deliberately lenient (extra keys ignored, defaults everywhere) so a
chatty model can still be validated; safety is enforced in code afterwards, not
by trusting the model's JSON shape.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from triad.schemas import ObjectionCategory

TurbulenceLevel = Literal["NONE", "LIGHT", "MODERATE", "SEVERE"]
MelCategory = Literal["A", "B", "C", "D"]


class LLMModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


# --------------------------------------------------------------------------- perception


class AtcPerception(LLMModel):
    closed_taxiways: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    citations: list[str] = Field(
        default_factory=list,
        description=(
            "Chunk ids from the <source> blocks. If you report any non-empty fact, "
            "this MUST contain at least one valid chunk id; leave it empty only when "
            "the report contains no relevant fact."
        ),
    )
    notes: str = ""


class PilotPerception(LLMModel):
    turbulence: dict[str, TurbulenceLevel] = Field(default_factory=dict)
    flagged_notes: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    citations: list[str] = Field(
        default_factory=list,
        description=(
            "Chunk ids from the <source> blocks. If you report any non-empty fact, "
            "this MUST contain at least one valid chunk id; leave it empty only when "
            "the report contains no relevant fact."
        ),
    )
    notes: str = ""


class GroundPerception(LLMModel):
    ata_chapter: int | None = None
    mel_item: str | None = None
    mel_category: MelCategory | None = None
    deferrable: bool | None = None
    repair_min: int | None = None
    confidence: float = 0.0
    citations: list[str] = Field(
        default_factory=list,
        description=(
            "Chunk ids from the <source> blocks. If you report any non-empty fact, "
            "this MUST contain at least one valid chunk id; leave it empty only when "
            "the report contains no relevant fact."
        ),
    )
    notes: str = ""


# --------------------------------------------------------------------------- decide


class ObjectionOut(LLMModel):
    option_id: str
    category: ObjectionCategory
    reason: str


class CounterOut(LLMModel):
    base_option_id: str
    changes: dict[str, Any] = Field(default_factory=dict)


class Turn1Decision(LLMModel):
    ranking: list[str] = Field(default_factory=list)
    objections: list[ObjectionOut] = Field(default_factory=list)
    counter: CounterOut | None = None
    rationale: str = ""
    citations: list[str] = Field(default_factory=list)


class VoteOut(LLMModel):
    option_id: str
    vote: Literal["APPROVE", "DISAPPROVE"]
    reason: str | None = None


class Turn2Decision(LLMModel):
    votes: list[VoteOut] = Field(default_factory=list)
    ranking: list[str] = Field(default_factory=list)
    rationale: str = ""
    citations: list[str] = Field(default_factory=list)


PERCEPTION_SCHEMAS = {
    "ATC": AtcPerception,
    "PILOT": PilotPerception,
    "GROUND": GroundPerception,
}

__all__ = [
    "AtcPerception",
    "PilotPerception",
    "GroundPerception",
    "ObjectionOut",
    "CounterOut",
    "Turn1Decision",
    "VoteOut",
    "Turn2Decision",
    "PERCEPTION_SCHEMAS",
    "TurbulenceLevel",
    "MelCategory",
]
