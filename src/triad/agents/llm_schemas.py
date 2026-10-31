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
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="0..1. Use >= 0.6 when the extraction is grounded in the report or a source.",
    )
    citations: list[str] = Field(
        description=(
            "Chunk ids from the <source> blocks. If you report any non-empty fact, "
            "this MUST contain at least one valid chunk id; use [] only when the report "
            "contains no relevant fact."
        )
    )
    notes: str = ""


class PilotPerception(LLMModel):
    turbulence: dict[str, TurbulenceLevel] = Field(default_factory=dict)
    flagged_notes: list[str] = Field(default_factory=list)
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="0..1. Use >= 0.6 when the extraction is grounded in the report or a source.",
    )
    citations: list[str] = Field(
        description=(
            "Chunk ids from the <source> blocks. If you report any non-empty fact, "
            "this MUST contain at least one valid chunk id; use [] only when the report "
            "contains no relevant fact."
        )
    )
    notes: str = ""


class GroundPerception(LLMModel):
    ata_chapter: int | None = None
    mel_item: str | None = None
    mel_category: MelCategory | None = None
    deferrable: bool | None = None
    repair_min: int | None = None
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="0..1. Use >= 0.6 when the extraction is grounded in the report or a source.",
    )
    citations: list[str] = Field(
        description=(
            "Chunk ids from the <source> blocks. If you report any non-empty fact, "
            "this MUST contain at least one valid chunk id; use [] only when the report "
            "contains no relevant fact."
        )
    )
    notes: str = ""


# --------------------------------------------------------------------------- decide


# ``maxLength`` lives only in the JSON schema sent to the provider: guided decoding
# then cannot run away inside a free-text field (observed with qwen3.6), while
# Pydantic stays lenient and code trims the text at a sentence boundary.
_TEXT_LIMIT = {"maxLength": 600}
_REASON_LIMIT = {"maxLength": 300}


class ObjectionOut(LLMModel):
    option_id: str
    category: ObjectionCategory
    reason: str = Field(json_schema_extra=_REASON_LIMIT)


class CounterOut(LLMModel):
    base_option_id: str
    changes: dict[str, Any] = Field(default_factory=dict)


RATIONALE_DESCRIPTION = (
    "Final public summary of your decision, written AFTER deciding: at most 60 words "
    "(2-3 complete sentences). Quote clock times as HH:MM exactly as given, money as "
    "whole EUR, utilities to 2 decimals; keep option ids. No deliberation here."
)


ANALYSIS_DESCRIPTION = (
    "Private working notes written BEFORE deciding: compare the options briefly "
    "(at most 80 words). Not shown to other agents."
)


class Turn1Decision(LLMModel):
    analysis: str = Field(default="", description=ANALYSIS_DESCRIPTION, json_schema_extra=_TEXT_LIMIT)
    ranking: list[str] = Field(default_factory=list)
    objections: list[ObjectionOut] = Field(default_factory=list)
    counter: CounterOut | None = None
    rationale: str = Field(description=RATIONALE_DESCRIPTION, json_schema_extra=_TEXT_LIMIT)
    citations: list[str] = Field(default_factory=list)


class VoteOut(LLMModel):
    option_id: str
    vote: Literal["APPROVE", "DISAPPROVE"]
    reason: str | None = Field(default=None, json_schema_extra=_REASON_LIMIT)


TURN2_COUNTER_DESCRIPTION = (
    "Optional: at most one revised option, based on a shortlisted option you DISAPPROVE in this "
    "ballot, changing only your controllable fields. Use null for no counter."
)


class Turn2Decision(LLMModel):
    analysis: str = Field(default="", description=ANALYSIS_DESCRIPTION, json_schema_extra=_TEXT_LIMIT)
    votes: list[VoteOut] = Field(default_factory=list)
    ranking: list[str] = Field(default_factory=list)
    counter: CounterOut | None = Field(default=None, description=TURN2_COUNTER_DESCRIPTION)
    rationale: str = Field(description=RATIONALE_DESCRIPTION, json_schema_extra=_TEXT_LIMIT)
    citations: list[str] = Field(default_factory=list)


class Turn3Decision(LLMModel):
    """Final ballot: votes + ranking only; no counter-options, no new options."""

    analysis: str = Field(default="", description=ANALYSIS_DESCRIPTION, json_schema_extra=_TEXT_LIMIT)
    votes: list[VoteOut] = Field(default_factory=list)
    ranking: list[str] = Field(default_factory=list)
    rationale: str = Field(description=RATIONALE_DESCRIPTION, json_schema_extra=_TEXT_LIMIT)
    citations: list[str] = Field(default_factory=list)


PERCEPTION_SCHEMAS = {
    "ATC": AtcPerception,
    "PILOT": PilotPerception,
    "GROUND": GroundPerception,
}

__all__ = [
    "ANALYSIS_DESCRIPTION",
    "RATIONALE_DESCRIPTION",
    "AtcPerception",
    "PilotPerception",
    "GroundPerception",
    "ObjectionOut",
    "CounterOut",
    "Turn1Decision",
    "VoteOut",
    "Turn2Decision",
    "Turn3Decision",
    "TURN2_COUNTER_DESCRIPTION",
    "PERCEPTION_SCHEMAS",
    "TurbulenceLevel",
    "MelCategory",
]
