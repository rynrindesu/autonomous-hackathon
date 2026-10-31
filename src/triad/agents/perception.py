"""Stub perception: a perfect reader of the synthetic unstructured inputs.

The interface is identical to the future LLM+RAG implementation: role, public
event, private payload -> ``PerceivedFact`` list with citations.  The
``conservative_facts`` fallback applies the plan's fail-safe defaults when
perception is unavailable.
"""

from __future__ import annotations

from typing import Any

from triad.config import load_yaml
from triad.schemas import (
    AgentRole,
    AtcPrivate,
    Citation,
    GroundPrivate,
    PerceivedFact,
    PilotPrivate,
    PublicEvent,
)


def _citation(doc: str, chunk_id: str, *, synthetic: bool = True) -> Citation:
    return Citation(doc=doc, chunk_id=chunk_id, synthetic=synthetic)


def _defect_value(private: GroundPrivate, *, force_non_deferrable: bool = False) -> dict[str, Any] | None:
    if private.defect is None:
        return None
    defect = private.defect
    repair = defect.truth_repair_min if defect.truth_repair_min is not None else 60
    deferrable = defect.truth_deferrable
    if force_non_deferrable:
        deferrable = False
        repair = max(60, int(repair))
    return {
        "ata_chapter": defect.truth_ata_chapter,
        "mel_item": defect.truth_mel_item,
        "mel_category": defect.truth_mel_category,
        "deferrable": bool(deferrable) if deferrable is not None else False,
        "repair_min": int(repair),
    }


def stub_perceive(
    role: AgentRole, public: PublicEvent, private: Any
) -> list[PerceivedFact]:
    """Deterministic perfect perception of the synthetic inputs (source STUB)."""

    run_id = public.run_id

    if role == AgentRole.ATC:
        assert isinstance(private, AtcPrivate)
        closed = list(private.truth_closed_taxiways)
        return [
            PerceivedFact(
                key="closed_taxiways",
                value=closed,
                confidence=1.0,
                citation=_citation("Synthetic NOTAM", f"notam-{run_id}-closed"),
                source="STUB",
            )
        ]

    if role == AgentRole.PILOT:
        assert isinstance(private, PilotPrivate)
        return [
            PerceivedFact(
                key="turbulence",
                value=dict(private.truth_turbulence),
                confidence=1.0,
                citation=_citation(
                    "AIM §7-1-21 (synthetic PIREP extract)", f"pirep-{run_id}"
                ),
                source="STUB",
            ),
            PerceivedFact(
                key="pax_notes",
                value=list(private.pax_notes),
                confidence=1.0,
                citation=_citation(
                    "Synthetic passenger service notes", f"pax-{run_id}"
                ),
                source="STUB",
            ),
        ]

    if role == AgentRole.GROUND:
        assert isinstance(private, GroundPrivate)
        value = _defect_value(private)
        defect = private.defect
        citation = (
            _citation(
                "Boeing B737 MMEL Rev 63 (synthetic excerpt)",
                f"mmel-{defect.defect_id}",
            )
            if defect is not None
            else None
        )
        return [
            PerceivedFact(
                key="defect",
                value=value,
                confidence=1.0,
                citation=citation,
                source="STUB",
            )
        ]

    raise ValueError(f"unknown role {role!r}")


def conservative_facts(
    role: AgentRole, public: PublicEvent, private: Any
) -> list[PerceivedFact]:
    """Fail-safe perception defaults (source DEFAULT, conservative_default=True)."""

    run_id = public.run_id
    default_citation = _citation(
        "Conservative perception default", f"default-{run_id}-{role.value.lower()}"
    )

    if role == AgentRole.ATC:
        assert isinstance(private, AtcPrivate)
        # Every taxiway named in the NOTAM is treated as closed.
        known = set(load_yaml("synthetic")["ground"]["taxiways"])
        named: set[str] = set(private.truth_closed_taxiways)
        for line in private.notam_text:
            tokens = line.replace(",", " ").split()
            for i, token in enumerate(tokens):
                if token.upper() == "TWY":
                    named.update(
                        t for t in tokens[i + 1 :] if t.isalpha() and t.upper() in known
                    )
        return [
            PerceivedFact(
                key="closed_taxiways",
                value=sorted(named),
                confidence=0.6,
                citation=default_citation,
                conservative_default=True,
                source="DEFAULT",
            )
        ]

    if role == AgentRole.PILOT:
        assert isinstance(private, PilotPrivate)
        keys = list(private.truth_turbulence) or [f"FL{lv}" for lv in private.cruise_levels]
        levels = {
            key: ("SEVERE" if private.truth_turbulence.get(key) == "SEVERE" else "MODERATE")
            for key in keys
        }
        return [
            PerceivedFact(
                key="turbulence",
                value=levels,
                confidence=0.6,
                citation=default_citation,
                conservative_default=True,
                source="DEFAULT",
            ),
            PerceivedFact(
                key="pax_notes",
                value=list(private.pax_notes),
                confidence=0.6,
                citation=default_citation,
                conservative_default=True,
                source="DEFAULT",
            ),
        ]

    if role == AgentRole.GROUND:
        assert isinstance(private, GroundPrivate)
        value = _defect_value(private, force_non_deferrable=True)
        return [
            PerceivedFact(
                key="defect",
                value=value,
                confidence=0.6,
                citation=default_citation,
                conservative_default=True,
                source="DEFAULT",
            )
        ]

    raise ValueError(f"unknown role {role!r}")
