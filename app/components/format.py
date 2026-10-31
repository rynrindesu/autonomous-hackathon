"""Presentation helpers: clock times, values, event labels and plain wording."""

from __future__ import annotations

import json
from typing import Any

ROLE_NAMES = {"ATC": "ATC", "PILOT": "Pilot", "GROUND": "Ground"}

EVENT_LABELS = {
    "SETUP": "Setup",
    "PERCEPTION": "Perception",
    "INJECTION_DETECTED": "Injection resisted",
    "AGENT_CHECKS": "Agent checks",
    "COMMIT_GATE": "Commit gate",
    "OPTIONS_GENERATED": "Options generated",
    "SHARED_CHECKS": "Shared checks",
    "PROPOSAL": "Turn 1 proposal",
    "COUNTER_VALIDATED": "Counter validated",
    "COUNTER_REJECTED": "Counter rejected",
    "SHORTLIST": "Shortlist",
    "BALLOT": "Turn 2 ballot",
    "SAFETY_BLOCK": "Safety block",
    "AGENT_FAILOVER": "Agent failover",
    "CONSENSUS_REACHED": "Consensus reached",
    "FALLBACK_INVOKED": "Fallback invoked",
    "COMMIT": "Commit",
    "ESCALATED": "Escalated",
}

SAFETY_DETAILS = {
    "omitted veto": "A code veto was missing from the agent's message. The orchestrator added it from the checker.",
    "fabricated veto": "The agent claimed a veto that its code checker did not support. The claim was discarded.",
    "unsafe counter rejected": "A counter-option failed a hard check, so it never reached the vote.",
    "approve outside shortlist": "The agent approved an option that was not on the Turn-2 shortlist. The vote was discarded.",
    "approve of unsafe option": "The agent approved an option that failed a hard check. The vote was discarded.",
    "commit re-check failed": "The final commit check failed. The option was not committed.",
}

_TAG_RE = None


def split_rationale(text: Any) -> dict[str, Any]:
    """Split an agent rationale into prose and the machine-added suffix tags.

    Handles ``[approves: A, B]``, ``[LLM approved: A]``, ``[COMPROMISED AGENT: ...]``
    and a trailing ``| free-text reasons: ...``. Unknown ``[Label: ...]`` tags are kept
    as generic notes so nothing is silently dropped.
    """
    import re

    global _TAG_RE
    if _TAG_RE is None:
        _TAG_RE = re.compile(r"\[([A-Za-z][A-Za-z \-]{1,40}):\s*([^\]]*)\]")
    raw = str(text or "").strip()
    reasons = ""
    marker = "| free-text reasons:"
    if marker in raw:
        raw, reasons = raw.split(marker, 1)
        reasons = reasons.strip()
    out: dict[str, Any] = {
        "body": "",
        "approves": [],
        "llm_approved": [],
        "compromised": [],
        "notes": [],
        "reasons": reasons,
    }
    for label, value in _TAG_RE.findall(raw):
        key = label.strip().lower()
        ids = [v.strip() for v in value.split(",") if v.strip()]
        if key == "approves":
            out["approves"].extend(ids)
        elif key == "llm approved":
            out["llm_approved"].extend(ids)
        elif key.startswith("compromised"):
            out["compromised"].append(value.strip())
        else:
            out["notes"].append(f"{label.strip()}: {value.strip()}")
    out["body"] = _TAG_RE.sub("", raw).strip()
    return out

REASONS = {
    "UNANIMOUS_FIRST_CHOICE": "All three agents ranked the same option first, with no objection on it.",
    "UNANIMOUS_APPROVAL": "All three agents approved this option in the Turn-2 ballot.",
    "NO_UNANIMOUS_APPROVAL": "No option received all three approvals. The non-AI fallback chose the cheapest safe option.",
    "AI_OFF": "AI was switched off. The deterministic fallback chose the cheapest safe option.",
    "NO_SAFE_OPTION": "No option passed every hard check. The case was escalated to a human.",
}

STATE_LABEL = {
    "committed": "Committed",
    "shortlisted": "Shortlisted",
    "feasible": "Feasible",
    "vetoed": "Vetoed",
    "rejected": "Counter rejected",
    "proposed": "Proposed",
}


def fmt_hhmm(minutes: Any) -> str:
    if minutes is None or minutes == "":
        return "—"
    try:
        value = int(minutes)
    except Exception:
        return str(minutes)
    day, minute = divmod(value, 1440)
    clock = f"{minute // 60:02d}:{minute % 60:02d}"
    return clock + (f"+{day}" if day else "")


def fmt_date(flight: dict[str, Any]) -> str:
    try:
        from datetime import date

        return date(
            int(flight["year"]), int(flight["month"]), int(flight["day"])
        ).strftime("%d %b %Y")
    except Exception:
        return "—"


def fmt_num(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if abs(value - round(value)) < 1e-6:
            return f"{int(round(value)):,}"
        if abs(value) >= 100:
            return f"{value:,.1f}"
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return str(value)


def fmt_eur(value: Any) -> str:
    try:
        return f"€{float(value):,.0f}"
    except Exception:
        return "—"


def fmt_minutes(value: Any) -> str:
    if value is None:
        return "—"
    try:
        minutes = int(value)
    except Exception:
        return str(value)
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h {rest:02d}"


def fmt_pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.0f}%"
    except Exception:
        return "—"


def short_hash(value: Any, length: int = 12) -> str:
    text = str(value or "")
    return text[:length] + ("…" if len(text) > length else "") if text else "—"


def fmt_fact_value(key: str, value: Any) -> str:
    if value is None:
        return "none"
    if key == "defect" and isinstance(value, dict):
        parts: list[str] = []
        if value.get("ata_chapter") is not None:
            parts.append(f"ATA {value['ata_chapter']}")
        if value.get("mel_item"):
            parts.append(str(value["mel_item"]))
        if value.get("mel_category"):
            parts.append(f"MEL {value['mel_category']}")
        if value.get("deferrable") is not None:
            parts.append("deferrable" if value["deferrable"] else "not deferrable")
        if value.get("repair_min") is not None:
            parts.append(f"repair {value['repair_min']} min")
        return " · ".join(parts) if parts else "defect read"
    if key == "turbulence" and isinstance(value, dict):
        short = {"MODERATE": "MOD", "LIGHT": "LGT", "SEVERE": "SEV", "NONE": "NONE"}
        return " · ".join(
            f"{level if str(level).upper().startswith('FL') else 'FL' + str(level)} {short.get(str(report).upper(), report)}"
            for level, report in value.items()
        ) or "no reports"
    if isinstance(value, list):
        if not value:
            return "none listed"
        if all(isinstance(v, (str, int, float)) for v in value):
            return "; ".join(str(v) for v in value)
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        return " · ".join(f"{k}: {v}" for k, v in value.items())
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def pretty_rationale(text: Any) -> str:
    """Light presentation cleanup for deterministic stub wording. LLM text is left alone."""
    raw = str(text or "").strip()
    if not raw:
        return "No rationale recorded."
    import re

    text_out = raw.replace(" stub ranks ", " ranks ").replace(" stub approves ", " approves ")
    text_out = text_out.replace(" stub vetoed ", " vetoed ").replace("veto(es)", "vetoes")
    text_out = text_out.replace("objection(s)", "objections")
    text_out = re.sub(
        r"Counter (\S+) with \[([^\]]+)\]\.",
        lambda m: "Counter-option on "
        + m.group(1)
        + ": "
        + ", ".join(
            {
                "arrival_slot": "arrival",
                "departure_slot": "departure",
                "holding_min": "holding",
                "enroute_absorb_min": "en route absorb",
                "speed_recovery_min": "speed recovery",
                "cruise_level": "flight level",
                "next_leg_action": "next-leg action",
                "next_leg_delay_min": "next-leg delay",
            }.get(part.strip().strip("'\""), part.strip().strip("'\"").replace("_", " "))
            for part in m.group(2).split(",")
        )
        + ".",
        text_out,
    )
    text_out = re.sub(r"\((\d+)/(\d+) approved\)", r"(\1 of \2 shortlisted)", text_out)
    return text_out


def fmt_counter_option(option: dict[str, Any]) -> str:
    parts: list[str] = []
    if option.get("arrival_slot") is not None:
        parts.append(f"arrive {fmt_hhmm(option['arrival_slot'])}")
    if option.get("departure_slot") is not None:
        parts.append(f"depart {fmt_hhmm(option['departure_slot'])}")
    if option.get("holding_min"):
        parts.append(f"hold {option['holding_min']} min")
    if option.get("enroute_absorb_min"):
        parts.append(f"absorb {option['enroute_absorb_min']} min")
    if option.get("speed_recovery_min"):
        parts.append(f"recover {option['speed_recovery_min']} min")
    if option.get("cruise_level"):
        parts.append(f"FL{option['cruise_level']}")
    if option.get("gate"):
        parts.append(f"gate {option['gate']}")
    if option.get("runway"):
        parts.append(f"runway {option['runway']}")
    action = option.get("next_leg_action")
    if action and action != "KEEP":
        parts.append(f"next leg {str(action).replace('_', ' ').lower()}")
    return " · ".join(parts) or "no field changes"


def option_next_leg(option: dict[str, Any]) -> str:
    action = str(option.get("next_leg_action") or "KEEP").replace("_", " ").title()
    delay = option.get("next_leg_delay_min")
    if delay:
        return f"{action} +{delay} min"
    return action


def option_hold_absorb(option: dict[str, Any]) -> str:
    hold = int(option.get("holding_min") or 0)
    absorb = int(option.get("enroute_absorb_min") or 0)
    return f"{hold} / {absorb}"


def human_reason(reason: str) -> str:
    text = str(reason or "")
    if text in REASONS:
        return REASONS[text]
    if text.startswith("COMMIT_BLOCKED"):
        return "The chosen option failed the final commit re-check. The fallback chose the next cheapest safe option."
    if text.startswith("NO_SAFE_OPTION"):
        return "No option passed every hard check. The case was escalated to a human."
    return text.replace("_", " ").capitalize() if text else "No reason recorded."


def human_decided_by(decided_by: str) -> str:
    return {
        "AGENTS": "Agreed by all three agents",
        "FALLBACK": "Chosen by the non-AI fallback",
        "HUMAN_ESCALATION": "Escalated to a human",
    }.get(decided_by, decided_by.replace("_", " ").title())


def safety_detail_label(detail: str) -> str:
    detail = str(detail or "")
    if detail in SAFETY_DETAILS:
        return SAFETY_DETAILS[detail]
    return detail.replace("_", " ")


def event_label(event: str) -> str:
    return EVENT_LABELS.get(event, str(event).replace("_", " ").title())


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def event_summary(entry: dict[str, Any]) -> str:
    event = str(entry.get("event") or "")
    payload = _as_dict(entry.get("payload"))
    if event == "SETUP":
        return f"{payload.get('mode', '?')} · decision {fmt_hhmm(payload.get('decision_time'))} · ETA {fmt_hhmm(payload.get('expected_eta'))}"
    if event == "SHARED_CHECKS":
        checks = payload.get("checks") or []
        failed = [
            c.get("constraint_id")
            for c in checks
            if isinstance(c, dict) and c.get("hard", True) and not c.get("passed", True)
        ]
        state = "pass" if payload.get("passed") else "fail"
        return f"{payload.get('option_id', '?')} · {state}" + (f" · {', '.join(str(v) for v in failed)}" if failed else "")
    if event == "OPTIONS_GENERATED":
        ids = payload.get("option_ids") or []
        kept = payload.get("shared_passed") or []
        return f"{len(ids)} options · {len(kept)} pass shared checks"
    if event == "PROPOSAL":
        ranking = payload.get("ranking") or []
        vetoes = payload.get("vetoes") or []
        counter = payload.get("counter_option")
        text = f"top {ranking[0] if ranking else '—'} · {len(vetoes)} veto{'es' if len(vetoes) != 1 else ''}"
        if isinstance(counter, dict):
            text += f" · counter on {counter.get('base_option_id', '?')}"
        return text
    if event == "COUNTER_VALIDATED":
        return f"{payload.get('option_id', '?')} · base {payload.get('base_option_id', '?')} · all checks pass"
    if event == "COUNTER_REJECTED":
        failures = payload.get("failing_checks") or []
        ids = [str(c.get("constraint_id")) for c in failures if isinstance(c, dict)]
        return f"{payload.get('option_id') or 'counter'} · rejected" + (f" · {', '.join(ids)}" if ids else "")
    if event == "SHORTLIST":
        return ", ".join(str(v) for v in payload.get("option_ids") or []) or "empty"
    if event == "BALLOT":
        votes = payload.get("votes") or []
        approve = sum(1 for v in votes if isinstance(v, dict) and v.get("vote") == "APPROVE")
        disapprove = sum(1 for v in votes if isinstance(v, dict) and v.get("vote") == "DISAPPROVE")
        return f"{approve} approve · {disapprove} disapprove"
    if event == "SAFETY_BLOCK":
        ids = payload.get("constraint_ids") or []
        who = payload.get("agent") or payload.get("role")
        text = f"{payload.get('detail', '?')} · {payload.get('option_id', '?')}"
        if who:
            text = f"{who} · " + text
        if ids:
            text += " · " + ", ".join(str(i) for i in ids)
        return text
    if event == "AGENT_FAILOVER":
        error = str(payload.get("error") or "")
        return f"{payload.get('role', '?')} · {error[:80]}"
    if event == "FALLBACK_INVOKED":
        return f"{payload.get('option_id', '?')} · {str(payload.get('reason', '')).replace('_', ' ').lower()}"
    if event == "COMMIT":
        return f"{payload.get('option_id', '?')} · {payload.get('status', '')} · {str(payload.get('reason', '')).replace('_', ' ').lower()}"
    if event == "ESCALATED":
        return str(payload.get("reason", "")).replace("_", " ").lower()
    if event == "CONSENSUS_REACHED":
        return str(payload.get("option_id", ""))
    if event == "PERCEPTION":
        facts = payload.get("facts") or []
        defaults = payload.get("n_conservative_defaults") or 0
        sources = sorted({str(f.get("source")) for f in facts if isinstance(f, dict) and f.get("source")})
        text = f"{len(facts)} fact{'s' if len(facts) != 1 else ''} · {'/'.join(sources) or '—'}"
        if defaults:
            text += f" · {defaults} conservative default{'s' if defaults != 1 else ''}"
        if payload.get("failover"):
            text += " · failover"
        return text
    if event == "INJECTION_DETECTED":
        phrases = payload.get("phrases") or []
        return f"{payload.get('kind') or 'input'} · {', '.join(str(p) for p in phrases[:4])} · treated as data"
    if event == "AGENT_CHECKS":
        agents = payload.get("agents") or {}
        failed = [
            f"{role} {', '.join(item.get('failed_constraint_ids') or [])}"
            for role, item in agents.items()
            if isinstance(item, dict) and not item.get("passed", True)
        ]
        state = "pass" if payload.get("passed") else "fail"
        return f"{payload.get('option_id', '?')} · {state}" + (f" · {'; '.join(failed)}" if failed else "")
    if event == "COMMIT_GATE":
        state = "passed" if payload.get("passed") else "FAILED"
        failed = payload.get("failed") or []
        text = f"{payload.get('option_id', '?')} · {state} · {payload.get('n_checks', '?')} checks"
        if failed:
            text += " · " + ", ".join(str(f.get("constraint_id")) for f in failed if isinstance(f, dict))
        return text
    return ""
