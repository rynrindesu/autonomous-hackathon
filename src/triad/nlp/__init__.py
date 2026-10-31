"""NLP layer: free-text intake and per-role briefings (PLAN §10)."""

from triad.nlp.briefing import make_llm_polisher, render_briefings
from triad.nlp.intake import (
    IntakeResult,
    confirm_intake,
    intake_defect_text,
    to_defect_report,
)

__all__ = [
    "IntakeResult",
    "confirm_intake",
    "intake_defect_text",
    "make_llm_polisher",
    "render_briefings",
    "to_defect_report",
]
