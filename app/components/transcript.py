"""Negotiation transcript: the run's log.jsonl retold as a chat, in seq order.

Deterministic and read-only: every sentence is built from log payloads with
fixed templates (no LLM calls, no access to the protocol). Agent rationales are
quoted verbatim, never rewritten.

    build_transcript(entries)   -> list of {speaker, turn, kind, text, alert, rationale}
    to_markdown(messages)       -> str (for slides; see scripts/transcript.py)
    render(messages)            -> Streamlit chat view
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SPEAKERS = {"ORCHESTRATOR": "Orchestrator", "ATC": "ATC", "PILOT": "Pilot", "GROUND": "Ground", "GATE": "Commit gate"}
AVATARS = {"Orchestrator": "🧭", "ATC": "🗼", "Pilot": "✈️", "Ground": "🧰", "Commit gate": "🔒", "Duty manager": "🧑‍✈️"}
ALERT_KINDS = {"conservative_default", "failover", "safety_block", "injection", "counter_rejected", "escalated", "gate_blocked"}

# Plain-English meaning of each hard constraint (source and detail come from the check itself).
CONSTRAINT_TEXT = {
    "ATC-RWY-01": "arrival slot already taken",
    "ATC-TWY-01": "taxi route blocked by a closed taxiway",
    "ATC-WAKE-01": "wake-turbulence separation too small",
    "GND-GATE-01": "gate too small for the aircraft",
    "GND-GATE-02": "gate occupied at that time",
    "GND-MEL-01": "defect not deferrable and repair not finished",
    "GND-TURN-01": "next-leg turnaround too short",
    "PLT-FDP-01": "crew duty time would be exceeded",
    "PLT-FUEL-01": "fuel below alternate + 45-min reserve",
    "PLT-FUEL-02": "more holding than the fuel allows",
    "PLT-WX-01": "severe turbulence at the cruise level",
}

SAFETY_TEXT = {
    "omitted veto": "left out a veto its own code checker requires; the orchestrator re-added it",
    "fabricated veto": "claimed a veto its code checker does not support; the claim was discarded",
    "unsafe counter rejected": "proposed a counter-option that fails a hard check; it never reaches the vote",
    "approve outside shortlist": "approved an option that is not on the shortlist; the vote was discarded",
    "approve of unsafe option": "approved an option that fails a hard check; the vote was discarded",
    "commit re-check failed": "the final re-check failed, so this option was not committed",
}

REASON_TEXT = {
    "UNANIMOUS_FIRST_CHOICE": "all three agents ranked it first",
    "UNANIMOUS_APPROVAL": "all three agents approved it",
    "NO_UNANIMOUS_APPROVAL": "no option got all three approvals, so the non-AI fallback picked the cheapest safe option",
    "AI_OFF": "AI is off, so the non-AI fallback picked the cheapest safe option",
}


# --------------------------------------------------------------------------- formatting helpers


def _hhmm(minutes: Any) -> str:
    if minutes is None:
        return "--:--"
    m = int(minutes) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def _eur(value: Any) -> str:
    return f"€{float(value or 0):,.0f}"


def _role(name: Any) -> str:
    return SPEAKERS.get(str(name or "").upper(), str(name or "?").title())


def _ids(ids: list[str], limit: int = 6) -> str:
    ids = list(dict.fromkeys(i for i in ids if i))
    return ", ".join(ids) if len(ids) <= limit else ", ".join(ids[:limit]) + f" +{len(ids) - limit} more"


def _first_sentence(text: Any) -> str:
    raw = re.sub(r"\s*\[approves:[^\]]*\].*$", "", str(text or "")).strip()
    match = re.match(r"(.+?[.!?])(\s|$)", raw)
    return (match.group(1) if match else raw)[:240]


def _option_label(option: dict[str, Any] | None) -> str:
    if not option:
        return ""
    if option.get("divert_to"):
        return f"divert to {option['divert_to']}"
    parts = []
    if option.get("departure_slot") is not None and option.get("mode") == "GROUND":
        parts.append(f"depart {_hhmm(option['departure_slot'])}")
    parts.append(f"land {_hhmm(option.get('arrival_slot'))} on {option.get('runway', '?')}")
    if int(option.get("holding_min") or 0):
        parts.append(f"{int(option['holding_min'])} min holding")
    if int(option.get("enroute_absorb_min") or 0):
        parts.append(f"{int(option['enroute_absorb_min'])} min absorbed en route")
    if int(option.get("speed_recovery_min") or 0):
        parts.append(f"{int(option['speed_recovery_min'])} min speed recovery")
    if option.get("next_leg_action") and option["next_leg_action"] != "KEEP":
        delay = int(option.get("next_leg_delay_min") or 0)
        parts.append(f"next leg {option['next_leg_action'].lower().replace('_', ' ')}" + (f" +{delay} min" if delay else ""))
    return ", ".join(parts)


def _default_why(reason: str | None) -> str:
    """'failed validation (<reason>)' from the PERCEPTION payload's default_reason (absent in older logs)."""
    if not reason:
        return "did not pass validation"
    return "failed validation (" + reason.replace("low_confidence: ", "").replace("invalid_citation: ", "no valid citation: ") + ")"


def _fact_sentence(fact: dict[str, Any], reason: str | None = None) -> str:
    key = fact.get("key")
    value = fact.get("value")
    why = _default_why(reason)
    default = bool(fact.get("conservative_default"))
    if key == "closed_taxiways":
        twy = ", ".join(value or []) or "none"
        if default:
            return f"My NOTAM reading {why}, so I assume taxiway {twy} is closed (conservative default)."
        return f"From the NOTAM: closed taxiways {twy}."
    if key == "turbulence":
        levels = ", ".join(f"{fl} {str(lvl).lower()}" for fl, lvl in (value or {}).items()) or "no reports"
        if default:
            return f"My PIREP reading {why}, so I assume: {levels} (conservative default)."
        return f"From the PIREPs: {levels}."
    if key == "pax_notes":
        notes = "; ".join(value or []) or "none"
        return f"Passenger notes: {notes}."
    if key == "defect":
        if not value:
            return "No open aircraft defect."
        v = value if isinstance(value, dict) else {}
        text = (
            f"Defect: MEL {v.get('mel_item', '?')} (cat {v.get('mel_category', '?')}), "
            f"{'deferrable' if v.get('deferrable') else 'NOT deferrable'}, repair {v.get('repair_min', '?')} min"
        )
        if default:
            return f"My defect reading {why}, so I assume the worst case. {text} (conservative default)."
        return text + "."
    return f"{key}: {json.dumps(value, default=str)}" + (f" (conservative default: reading {why})." if default else ".")


def _fact_source(fact: dict[str, Any]) -> str:
    cite = fact.get("citation")
    if isinstance(cite, dict):
        cite = cite.get("chunk_id")
    src = {"LLM": "read by LLM", "STUB": "rule-based reader", "DEFAULT": "default"}.get(str(fact.get("source")), str(fact.get("source")))
    bits = [src]
    # A DEFAULT fact's confidence is a stamped constant, not the model's: don't show it.
    if fact.get("confidence") is not None and fact.get("source") == "LLM":
        bits.append(f"confidence {fact['confidence']}")
    if cite:
        bits.append(f"cite {cite}")
    return " · ".join(bits)


def _veto_lines(payload: dict[str, Any], options: dict[str, dict[str, Any]]) -> list[str]:
    """Group the code vetoes by constraint: 'OPT-07, OPT-08: fuel below ... [PLT-FUEL-01 · 14 CFR 121.639]'."""
    checks = {c.get("check_id"): c for c in payload.get("checks", []) or []}
    groups: dict[str, dict[str, Any]] = {}
    for veto in payload.get("vetoes", []) or []:
        check = checks.get(veto.get("check_id"), {})
        cid = veto.get("constraint_id") or check.get("constraint_id") or "?"
        g = groups.setdefault(cid, {"ids": [], "source": check.get("source"), "detail": check.get("detail")})
        g["ids"].append(veto.get("option_id"))
    lines = []
    for cid, g in groups.items():
        what = CONSTRAINT_TEXT.get(cid) or g["detail"] or "hard check failed"
        ids = g["ids"]
        target = f"{ids[0]} ({_option_label(options.get(ids[0]))})" if len(ids) == 1 else _ids(ids)
        source = f" · {g['source']}" if g["source"] else ""
        lines.append(f"{target}: {what} [{cid}{source}]")
    return lines


def _ballot_reasons(rationale: str) -> dict[str, str]:
    """Free-text disapproval reasons the LLM agent appends as 'OPT-03: THROUGHPUT: text; OPT-06: ...'."""
    out: dict[str, str] = {}
    if "free-text reasons:" not in rationale:
        return out
    tail = rationale.split("free-text reasons:", 1)[1]
    for match in re.finditer(r"(OPT-\w+|CTR-[\w-]+):\s*([A-Z_]+):\s*(.+?)(?=;\s*(?:OPT-|CTR-)|$)", tail):
        out[match.group(1)] = match.group(3).strip().rstrip(".")
    return out


# --------------------------------------------------------------------------- build


def _msg(speaker: str, turn: int, kind: str, text: str, rationale: str | None = None) -> dict[str, Any]:
    return {
        "speaker": speaker,
        "turn": int(turn or 0),
        "kind": kind,
        "text": text,
        "alert": kind in ALERT_KINDS,
        "rationale": rationale,
    }


def load_entries(path: str | Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def build_transcript(log_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries = sorted((e if isinstance(e, dict) else e.model_dump() for e in log_entries), key=lambda e: e.get("seq", 0))
    options: dict[str, dict[str, Any]] = {}
    out: list[dict[str, Any]] = []
    shared_failed: list[str] = []
    mode = ""

    for e in entries:
        ev, p, turn = e.get("event"), e.get("payload") or {}, e.get("turn", 0)
        actor = _role(e.get("actor"))

        if ev == "SETUP":
            public = p.get("public") or {}
            f = public.get("flight") or {}
            mode = p.get("mode", "")
            dtype = p.get("disruption_type", "")
            late = f.get("weather_delay") if dtype == "WEATHER" else f.get("late_aircraft_delay")
            where = "airborne" if mode == "AIRBORNE" else "still at the origin"
            out.append(_msg("Orchestrator", turn, "setup",
                f"{f.get('airline', '')}{f.get('flight_number', '')} {f.get('origin', '?')}→{f.get('destination', '?')} "
                f"is {late} min late ({str(dtype).lower().replace('_', ' ')}); decision at {_hhmm(p.get('decision_time'))}, "
                f"aircraft {where}. {_first_sentence(public.get('disruption_summary', ''))}".strip()))
            flags = p.get("flags") or {}
            if flags.get("red_team"):
                out.append(_msg("Orchestrator", turn, "injection", "Red-team mode is ON: the Pilot agent has been told to approve unsafe options."))
            if flags.get("ai_off"):
                out.append(_msg("Orchestrator", turn, "info", "AI is OFF for this run: no agent negotiation, deterministic fallback only."))

        elif ev == "SHARED_CHECKS":
            if not p.get("passed", True):
                shared_failed.append(p.get("option_id"))

        elif ev == "OPTIONS_GENERATED":
            for o in p.get("options", []) or []:
                options[o.get("option_id")] = o
            n_div = sum(1 for o in options.values() if o.get("divert_to"))
            kind = "landing" if mode == "AIRBORNE" else "departure"
            text = f"I generated {len(options) - n_div} {kind} options + {n_div} diversion."
            text += f" {len(p.get('shared_passed', []) or [])} pass the shared checks (runway, gate map, timing)."
            if shared_failed:
                text += f" Failed shared checks: {_ids(shared_failed)}."
            out.append(_msg("Orchestrator", turn, "options", text))

        elif ev == "AGENT_CHECKS":
            # Consecutive per-option checks (AI-off path) collapse into one message.
            failed = [_role(r) for r, v in (p.get("agents") or {}).items() if not v.get("passed", True)]
            if not (out and out[-1]["kind"] == "agent_checks"):
                out.append(_msg("Orchestrator", turn, "agent_checks", ""))
                out[-1]["_ok"], out[-1]["_bad"] = [], []
            last = out[-1]
            if failed:
                last["_bad"].append(f"{p.get('option_id')} ({'/'.join(failed)})")
            else:
                last["_ok"].append(p.get("option_id"))
            last["text"] = (
                f"Ran every agent's code checks on {len(last['_ok']) + len(last['_bad'])} options. "
                f"Pass all: {', '.join(last['_ok']) or 'none'}. Fail: {', '.join(last['_bad']) or 'none'}."
            )

        elif ev == "PERCEPTION":
            speaker = _role(p.get("role") or e.get("actor"))
            if p.get("failover"):
                text = "My LLM replies failed validation, so my rule-based stub took over; the facts below come from the rule-based reader."
                if p.get("default_reason"):
                    text += f" (My LLM perception had already fallen back: {p['default_reason']}.)"
                out.append(_msg(speaker, turn, "failover", text))
            for fact in p.get("facts", []) or []:
                kind = "conservative_default" if fact.get("conservative_default") else "perception"
                out.append(_msg(speaker, turn, kind, f"{_fact_sentence(fact, p.get('default_reason'))} ({_fact_source(fact)})"))

        elif ev == "INJECTION_DETECTED":
            who = _role(p.get("role") or e.get("actor"))
            out.append(_msg("Orchestrator", turn, "injection",
                f"Injection attempt in {who}'s input, {p.get('handling', 'treated as data')}: “{p.get('note', '')}” "
                f"(trigger phrases: {', '.join(p.get('phrases', []) or []) or '-'})."))

        elif ev == "PROPOSAL":
            ranking = p.get("ranking", []) or []
            top = ranking[0] if ranking else None
            parts = [f"I want {top} ({_option_label(options.get(top))})." if top else "I have no acceptable option."]
            vetoes = _veto_lines(p, options)
            if vetoes:
                parts.append("My code checks veto " + "; ".join(vetoes) + ".")
            objections = p.get("objections", []) or []
            if objections:
                parts.append("I object to " + ", ".join(
                    f"{o.get('option_id')} ({str(o.get('category', '')).lower().replace('_', ' ')})" for o in objections) + ".")
            counter = p.get("counter_option")
            if counter:
                changes = ", ".join(
                    f"{k.replace('_min', '').replace('_', ' ')} → {_hhmm(v) if k.endswith('_slot') else v}"
                    for k, v in (counter.get("changes") or {}).items()
                )
                parts.append(f"Counter-proposal: take {counter.get('base_option_id')} but change {changes or 'nothing'}.")
            if p.get("rationale"):
                parts.append(f"Why: {_first_sentence(p['rationale'])}")
            out.append(_msg(actor, turn, "proposal", " ".join(parts), p.get("rationale")))

        elif ev == "COUNTER_VALIDATED":
            opt = p.get("option") or {}
            if opt:
                options[opt.get("option_id")] = opt
            out.append(_msg("Orchestrator", turn, "counter",
                f"{_role(p.get('role'))}'s counter-option {p.get('option_id')} ({_option_label(opt) or 'based on ' + str(p.get('base_option_id'))}) "
                f"passed all {len(p.get('checks', []) or [])} hard checks and joins the vote."))

        elif ev == "COUNTER_REJECTED":
            fails = [f"{c.get('constraint_id')} ({c.get('detail')})" for c in p.get("failing_checks", []) or []]
            out.append(_msg("Orchestrator", turn, "counter_rejected",
                f"Rejected {_role(p.get('role'))}'s counter-option {p.get('option_id')}: " + ("; ".join(fails) or p.get("reason", "invalid")) + "."))

        elif ev == "SHORTLIST":
            scores = p.get("scores", {}) or {}
            ids = p.get("option_ids", []) or []
            text = "Shortlist by Borda score: " + ", ".join(f"{i} ({scores.get(i, 0):g})" for i in ids) + "."
            if p.get("fallback_option_id"):
                text += f" If nobody agrees, the fallback is {p['fallback_option_id']}."
            out.append(_msg("Orchestrator", turn, "shortlist", text))

        elif ev == "BALLOT":
            rationale = p.get("rationale", "") or ""
            reasons = _ballot_reasons(rationale)
            votes = p.get("votes", []) or []
            ok = [v["option_id"] for v in votes if v.get("vote") == "APPROVE"]
            no = [v for v in votes if v.get("vote") != "APPROVE"]
            parts = []
            if ok:
                parts.append(f"I approve {', '.join(ok)}.")
            for v in no:
                category = str(v.get("reason") or "no reason given").lower().replace("_", " ")
                why = reasons.get(v["option_id"])
                parts.append(f"I reject {v['option_id']} ({category})" + (f": {why}." if why else "."))
            if rationale:
                parts.append(f"Why: {_first_sentence(rationale)}")
            out.append(_msg(actor, turn, "ballot", " ".join(parts) or "No votes.", rationale))

        elif ev == "AGENT_FAILOVER":
            out.append(_msg("Orchestrator", turn, "failover",
                f"{_role(p.get('role'))}'s LLM reply failed in turn {p.get('turn', turn)} ({' '.join(str(p.get('error', '')).split())[:160]}). "
                f"Replaced by its rule-based stub for the rest of the run."))

        elif ev == "SAFETY_BLOCK":
            detail = str(p.get("detail", ""))
            who = _role(p.get("agent") or p.get("role")) if (p.get("agent") or p.get("role")) else "Commit"
            cids = ", ".join(p.get("constraint_ids", []) or []) or "no failing check"
            speaker = "Commit gate" if detail == "commit re-check failed" else "Orchestrator"
            out.append(_msg(speaker, turn, "safety_block",
                f"SAFETY_BLOCK on {p.get('option_id', '-')}: {who} {SAFETY_TEXT.get(detail, detail)} [{cids}]."))

        elif ev == "FALLBACK_INVOKED":
            reason = str(p.get("reason", ""))
            costs = (p.get("costs") or {}).get(p.get("option_id"), {})
            total = sum(float(v) for v in costs.values()) if costs else None
            text = f"Fallback: {REASON_TEXT.get(reason, reason.lower().replace('_', ' '))}."
            if p.get("pool") is not None:
                text += f" Safe pool: {_ids(p.get('pool') or [])}."
            text += f" Pick: {p.get('option_id')}" + (f" ({_eur(total)} total)." if total is not None else ".")
            out.append(_msg("Orchestrator", turn, "fallback", text))

        elif ev == "COMMIT_GATE":
            if p.get("passed"):
                out.append(_msg("Commit gate", turn, "gate", f"Re-ran {p.get('n_checks', 0)} hard checks on {p.get('option_id')}: all passed."))
            else:
                failed = ", ".join(f"{c.get('constraint_id')} ({c.get('detail')})" for c in p.get("failed", []) or [])
                out.append(_msg("Commit gate", turn, "gate_blocked",
                    f"Re-ran {p.get('n_checks', 0)} hard checks on {p.get('option_id')}: BLOCKED by {failed}."))

        elif ev == "COMMIT":
            opt = options.get(p.get("option_id")) or {}
            costs = p.get("costs_eur") or {}
            order = ["ATC", "PILOT", "GROUND"]
            cost_txt = ", ".join(
                f"{_role(r)} {_eur(costs[r])}" for r in sorted(costs, key=lambda r: order.index(r) if r in order else 9)
            )
            text = (f"Committed {p.get('option_id')} ({p.get('status')}): {_option_label(opt)}"
                    + (f", gate {opt['gate']}" if opt.get("gate") and not opt.get("divert_to") else "")
                    + f". Cost {cost_txt}. Reason: {REASON_TEXT.get(str(p.get('reason')), p.get('reason'))}.")
            if out and out[-1]["kind"] == "gate" and p.get("option_id") in out[-1]["text"]:
                out[-1]["text"] += " " + text
            else:
                out.append(_msg("Commit gate", turn, "commit", text))

        elif ev == "ESCALATED":
            out.append(_msg("Orchestrator", turn, "escalated",
                f"No option passed every hard check. Escalated to a human ({p.get('reason', '')})"
                + (f"; suggested alternate {p['alternate']}." if p.get("alternate") else ".")))

        elif ev == "CONSENSUS_REACHED":
            out.append(_msg("Orchestrator", turn, "info", f"Consensus reached on {p.get('option_id', '?')}."))

        elif ev == "HUMAN_DECISION":
            verdict = "Approved" if p.get("decision") == "approve" else "Rejected"
            text = f"{verdict}" + (f" {p['option_id']}" if p.get("option_id") else "") + f" at {p.get('timestamp', '?')}."
            if p.get("reason"):
                text += f" Reason: {p['reason']}"
            out.append(_msg("Duty manager", turn, "human_decision", text))

    for m in out:
        m.pop("_ok", None)
        m.pop("_bad", None)
    return out


# --------------------------------------------------------------------------- outputs


def _turn_label(turn: int) -> str:
    return "Setup" if turn == 0 else f"Turn {turn}"


def to_markdown(messages: list[dict[str, Any]], *, title: str | None = None, rationale: bool = False) -> str:
    lines = [f"### {title}", ""] if title else []
    for m in messages:
        flag = "⚠️ " if m["alert"] else ""
        lines.append(f"- {flag}**{m['speaker']}** · _{_turn_label(m['turn'])}_: {m['text']}")
        if rationale and m.get("rationale"):
            lines.append(f"  > {m['rationale']}")
    return "\n".join(lines) + "\n"


def render(messages: list[dict[str, Any]]) -> None:
    """Streamlit chat view. Imported lazily so the CLI does not need Streamlit."""
    import streamlit as st

    if not messages:
        st.info("This run's log has no negotiation messages.")
        return
    last_turn = None
    for m in messages:
        if m["turn"] != last_turn:
            st.caption(_turn_label(m["turn"]))
            last_turn = m["turn"]
        with st.chat_message(m["speaker"], avatar=AVATARS.get(m["speaker"])):
            st.markdown(f"**{m['speaker']}**")
            if m["kind"] in {"safety_block", "injection", "gate_blocked", "escalated", "counter_rejected"}:
                st.error(m["text"])
            elif m["alert"]:
                st.warning(m["text"])
            else:
                st.markdown(m["text"])
            if m.get("rationale"):
                with st.expander("Full rationale (verbatim)"):
                    st.text(m["rationale"])


__all__ = ["build_transcript", "load_entries", "render", "to_markdown"]
