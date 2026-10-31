"""Pure HTML builders for the Triad desk.

Every function takes a RunData and returns a string.  Keeping the builders pure
makes it easy to exercise every sample run without a browser.
"""

from __future__ import annotations

import json
from collections import Counter
from html import escape
from typing import Any

from .data import ROLES, ROLE_LABELS, RunData
from .format import (
    EVENT_LABELS,
    ROLE_NAMES,
    event_label,
    event_summary,
    fmt_counter_option,
    fmt_date,
    fmt_eur,
    fmt_fact_value,
    fmt_hhmm,
    fmt_num,
    fmt_pct,
    human_decided_by,
    human_reason,
    option_hold_absorb,
    pretty_rationale,
    option_next_leg,
    safety_detail_label,
    short_hash,
)


# --------------------------------------------------------------------------- tiny helpers


def h(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)


def badge(text: Any, kind: str = "grey", title: str | None = None) -> str:
    title_attr = f' title="{h(title)}"' if title else ""
    return f'<span class="td-badge td-{h(kind)}"{title_attr}>{h(text)}</span>'


def state_badge(state: str) -> str:
    kind = {
        "committed": "green",
        "shortlisted": "blue",
        "feasible": "grey",
        "vetoed": "red",
        "rejected": "red",
        "proposed": "amber",
    }.get(state, "grey")
    label = {
        "committed": "Committed",
        "shortlisted": "Shortlisted",
        "feasible": "Feasible",
        "vetoed": "Vetoed",
        "rejected": "Counter rejected",
    }.get(state, state.title())
    return badge(label, kind)


def role_class(role: str) -> str:
    return role.lower() if role in ROLES else "ground"


def role_letter(role: str) -> str:
    return {"ATC": "A", "PILOT": "P", "GROUND": "G"}.get(role, "?")


def source_badge(fact: dict[str, Any]) -> str:
    source = str(fact.get("source") or "STUB").upper()
    if fact.get("conservative_default") or source == "DEFAULT":
        return badge("DEFAULT · conservative", "amber", "Perception uncertain; safest reading applied")
    if source == "LLM":
        return badge("LLM", "green", "Perceived by the language model with a cited source")
    return badge(source, "grey", "Deterministic stub perception")


def _chip(text: str, kind: str = "", title: str | None = None) -> str:
    title_attr = f' title="{h(title)}"' if title else ""
    return f'<span class="td-chip {kind}"{title_attr}>{text}</span>'


def _minihead(left: str, right: str = "") -> str:
    return (
        '<div class="td-minihead">'
        f"<span>{h(left)}</span><span>{h(right)}</span>"
        "</div>"
    )


def _section(kicker: str, title: str, aside: str = "") -> str:
    return (
        '<div class="td-section-head">'
        '<div>'
        f'<div class="td-section-kicker">{h(kicker)}</div>'
        f'<div class="td-section-title">{h(title)}</div>'
        "</div>"
        f'<div class="td-section-aside">{h(aside)}</div>'
        "</div>"
    )


def _banner(kind: str, title: str, text: str, mark: str = "") -> str:
    return (
        f'<div class="td-banner td-banner-{h(kind)}">'
        f'<div class="td-banner-mark">{h(mark)}</div>'
        '<div>'
        f'<div class="td-banner-title">{h(title)}</div>'
        f'<div class="td-banner-text">{text}</div>'
        "</div>"
        "</div>"
    )


# --------------------------------------------------------------------------- sidebar


def brand_html() -> str:
    return (
        '<div class="td-brand">'
        '<div class="td-brand-row">'
        '<span class="td-brand-mark">TRIAD</span>'
        '<span class="td-brand-slash">/</span>'
        '<span class="td-brand-sub">Disruption desk</span>'
        "</div>"
        '<div class="td-brand-sub">ATC · PILOT · GROUND<br/>One orchestrator, rules in code</div>'
        "</div>"
    )


def side_meta_html(run: RunData) -> str:
    tags = [run.status]
    if run.scenario_name:
        tags.append(run.scenario_name)
    if run.turn:
        tags.append(f"T{run.turn}")
    tags.extend(run.flags)
    tags.append(run.impl_label)
    return '<div class="td-side-meta">' + "".join(
        f'<span class="td-side-tag">{h(tag)}</span>' for tag in tags
    ) + "</div>"


# --------------------------------------------------------------------------- hero


def _delay_causes(flight: dict[str, Any]) -> str:
    fields = [
        ("Weather", flight.get("weather_delay")),
        ("Late aircraft", flight.get("late_aircraft_delay")),
        ("Carrier", flight.get("airline_delay")),
        ("Air system", flight.get("air_system_delay")),
        ("Security", flight.get("security_delay")),
    ]
    if all(value in (None, 0) for _label, value in fields):
        return ""
    items = "".join(
        f'<span class="td-delay-item"><b>{h(label)}</b> {h(fmt_num(value))}</span>'
        for label, value in fields
    )
    return (
        '<div class="td-delays">'
        '<span class="td-delay-label">DOT delay causes</span>'
        f"{items}"
        "</div>"
    )


def hero_html(run: RunData) -> str:
    flight = run.flight
    aircraft = run.aircraft
    origin = h(flight.get("origin", "???"))
    destination = h(flight.get("destination", "???"))
    airline = h(flight.get("airline", ""))
    number = h(flight.get("flight_number", ""))
    tail = h(flight.get("tail_number", "—"))
    distance = flight.get("distance")
    aircraft_line = " · ".join(
        part
        for part in (
            h(aircraft.get("type_code", "")),
            f"wake {h(aircraft.get('wake', '—'))}",
            f"{fmt_num(aircraft.get('seats'))} seats" if aircraft.get("seats") else "",
        )
        if part
    )
    mode = run.mode or "—"
    scenario = run.scenario_name or (f"row {run.manifest.get('dataset_row')}" if run.manifest.get("dataset_row") is not None else "")
    run_tags = [badge(scenario, "grey", "Saved run")] if scenario else []
    run_tags.append(badge(run.impl_label, "grey"))
    for flag in run.flags:
        run_tags.append(badge(flag, "amber"))

    def metric(label: str, value: str, sub: str, kind: str, title: str) -> str:
        return (
            '<div class="td-hero-metric">'
            f'<div class="td-hero-label"><span>{h(label)}</span>{badge(kind, kind, title)}</div>'
            f'<div class="td-hero-value">{h(value)}</div>'
            f'<div class="td-hero-sub">{h(sub)}</div>'
            "</div>"
        )

    decision = fmt_hhmm(run.decision_time)
    eta = fmt_hhmm(run.expected_eta)
    sched = fmt_hhmm(run.original_eta)
    decision_sub = (
        "60 min before expected arrival"
        if run.mode == "AIRBORNE"
        else "before departure, at the origin"
        if run.mode == "GROUND"
        else "decision point"
    )

    return (
        '<div class="td-hero">'
        '<div class="td-hero-top">'
        "<div>"
        '<div class="td-kicker">Triad / disruption desk</div>'
        f'<div class="td-kicker" style="margin-top:4px;color:#c3d2ce;">RUN {h(run.run_id)}</div>'
        "</div>"
        f'<div class="td-hero-right">{"".join(run_tags)}</div>'
        "</div>"
        '<div class="td-hero-grid">'
        "<div>"
        f'<div class="td-route"><span>{origin}</span><span class="td-route-arrow">→</span><span>{destination}</span></div>'
        '<div class="td-flight-line">'
        f"<b>{airline}{number}</b>"
        f'<span class="td-sep">·</span><span>{h(run.date_label)}</span>'
        f'<span class="td-sep">·</span><span>Tail {tail}</span>'
        f'<span class="td-sep">·</span><span>{fmt_num(distance)} mi</span>'
        f'<span class="td-sep">·</span><span>{aircraft_line} {badge("synthetic", "synth", "Seeded scenario value")}</span>'
        "</div>"
        f'<div class="td-summary">{h(run.disruption_summary)}</div>'
        + _delay_causes(flight)
        + "</div>"
        '<div class="td-hero-metrics">'
        + metric("Decision time", decision, decision_sub, "derived", "Derived from the real delay and the mode")
        + metric("Expected ETA", eta, "before negotiation", "derived", "Expected arrival before the agents negotiate")
        + metric("Scheduled arrival", sched, "from the DOT row", "real", "Real DOT row value")
        + metric("Mode", mode, "decision context", "derived", "AIRBORNE or GROUND, set by the delay rules")
        + "</div>"
        "</div>"
        "</div>"
        '<div class="td-prov">'
        '<span class="td-prov-item"><span class="td-badge td-real">Real</span><b>DOT row</b> route · flight · date · scheduled times · delay causes</span>'
        '<span class="td-prov-item"><span class="td-badge td-derived">Derived</span><b>Expected ETA</b> decision time · mode</span>'
        '<span class="td-prov-item"><span class="td-badge td-synth">Synthetic</span><b>Seeded</b> aircraft type / wake · runways · gates · fuel · crew · NOTAM</span>'
        "</div>"
    )


def status_strip_html(run: RunData) -> str:
    status_class = {
        "CONSENSUS": "td-status-consensus",
        "FALLBACK": "td-status-fallback",
        "ESCALATED": "td-status-escalated",
    }.get(run.status, "")
    turn = run.turn
    if run.status == "ESCALATED" and turn == 0:
        turn_value, turn_sub = "Setup", "escalated before a turn"
    elif turn == 0:
        turn_value, turn_sub = "Setup", "AI off · fallback at setup"
    else:
        turn_value, turn_sub = f"T{turn}", "within the 2-turn cap"
    option = run.committed_option or {}
    if run.committed_id:
        committed_value = run.committed_id
        committed_sub = (
            f"ETA {fmt_hhmm(option.get('arrival_slot'))} · Rwy {option.get('runway', '—')} · "
            f"Gate {option.get('gate', '—')}"
        )
    else:
        committed_value = "—"
        committed_sub = "no option committed"
    safety_n = len(run.safety_blocks)
    safety_sub = "orchestrator guards" if safety_n else "no blocks raised"
    chain_value = "VERIFIED" if run.chain_ok else "BROKEN"
    chain_sub = f"{len(run.raw_entries)} log entries"
    return (
        '<div class="td-status-grid">'
        '<div class="td-stat">'
        '<div class="td-stat-label">Outcome</div>'
        f'<div class="td-stat-value {status_class}">{h(run.status)}</div>'
        f'<div class="td-stat-sub">{h(human_decided_by(run.decided_by))}</div>'
        "</div>"
        '<div class="td-stat">'
        '<div class="td-stat-label">Turn reached</div>'
        f'<div class="td-stat-value">{h(turn_value)}</div>'
        f'<div class="td-stat-sub">{h(turn_sub)}</div>'
        "</div>"
        '<div class="td-stat">'
        '<div class="td-stat-label">Committed option</div>'
        f'<div class="td-stat-value mono">{h(committed_value)}</div>'
        f'<div class="td-stat-sub">{h(committed_sub)}</div>'
        "</div>"
        '<div class="td-stat">'
        '<div class="td-stat-label">Safety blocks</div>'
        f'<div class="td-stat-value {"td-status-unsafe" if safety_n else "td-status-safe"}">{safety_n}</div>'
        f'<div class="td-stat-sub">{h(safety_sub)}</div>'
        "</div>"
        '<div class="td-stat">'
        '<div class="td-stat-label">Hash chain</div>'
        f'<div class="td-stat-value mono {"td-status-safe" if run.chain_ok else "td-status-unsafe"}">{chain_value}</div>'
        f'<div class="td-stat-sub">{h(chain_sub)}</div>'
        "</div>"
        "</div>"
    )


def flow_html(run: RunData) -> str:
    option_count = len(run.options)
    kept = len(run.shared_passed)
    proposals = len(run.proposals)
    ballots = len(run.ballots)
    veto_count = sum(len(p.get("vetoes") or []) for p in run.proposals.values())
    counter_count = len(run.counters)
    if proposals:
        turn1 = f"{proposals} proposals · {veto_count} vetoes"
        turn1_state = "done"
    elif run.flags and "AI off" in run.flags:
        turn1 = "Agents not called"
        turn1_state = "skipped"
    else:
        turn1 = "No proposal recorded"
        turn1_state = "skipped"
    if ballots:
        turn2 = f"{ballots} ballots · {len(run.shortlist)} shortlist"
        turn2_state = "done"
    elif turn1_state == "skipped":
        turn2 = "Not needed"
        turn2_state = "skipped"
    else:
        turn2 = "No ballot recorded"
        turn2_state = "skipped"
    if run.committed_id:
        outcome = run.committed_id
        outcome_state = "done"
    elif run.status == "ESCALATED":
        outcome = "Escalated to human"
        outcome_state = "active"
    else:
        outcome = "No commit"
        outcome_state = "active"
    return (
        '<div class="td-flow">'
        f'<div class="td-flow-step done"><div class="td-flow-label">Setup</div><div class="td-flow-value">{option_count} options · {kept} pass checks</div></div>'
        f'<div class="td-flow-step {turn1_state}"><div class="td-flow-label">Turn 1 · Propose</div><div class="td-flow-value">{h(turn1)}</div></div>'
        f'<div class="td-flow-step {turn2_state}"><div class="td-flow-label">Turn 2 · Ballot</div><div class="td-flow-value">{h(turn2)}</div></div>'
        f'<div class="td-flow-step {outcome_state}"><div class="td-flow-label">Outcome</div><div class="td-flow-value">{h(outcome)}</div></div>'
        "</div>"
    )


# --------------------------------------------------------------------------- negotiation


def topology_html(run: RunData) -> str:
    spokes: list[str] = []
    for role in ROLES:
        impl = str((run.manifest.get("agent_impl") or {}).get(role, "—"))
        proposal = run.proposals.get(role)
        ballot = run.ballots.get(role)
        if proposal:
            ranking = proposal.get("ranking") or []
            top = ranking[0] if ranking else "—"
        else:
            top = "not called"
        if ballot:
            votes = ballot.get("votes") or []
            yes = sum(1 for v in votes if isinstance(v, dict) and v.get("vote") == "APPROVE")
            vote_text = f"{yes}/{len(votes)} approved"
        elif "AI off" in run.flags:
            vote_text = "not called"
        else:
            vote_text = "no ballot"
        spokes.append(
            f'<div class="td-spoke {role_class(role)}">'
            '<div class="td-spoke-top">'
            f'<span class="td-spoke-role">{h(role)}</span>'
            f'<span class="td-spoke-impl">{h(impl)}</span>'
            "</div>"
            f'<div class="td-spoke-meta">T1 top {h(top)}</div>'
            f'<div class="td-spoke-sub">{h(vote_text)}</div>'
            "</div>"
        )
    return (
        '<div class="td-hub-band">'
        '<div class="td-hub-node">'
        '<div class="td-hub-kicker">Orchestrator · rule-based · no AI</div>'
        '<div class="td-hub-title">Hub-and-spoke negotiation</div>'
        '<div class="td-hub-sub">Routes public messages · enforces the 2-turn cap · re-checks every commit</div>'
        "</div>"
        f'<div class="td-spoke-row">{"".join(spokes)}</div>'
        "</div>"
    )


def turn_header_html(number: str, title: str, sub: str) -> str:
    return (
        '<div class="td-turn">'
        f'<div class="td-turn-num">{h(number)}</div>'
        '<div>'
        f'<div class="td-turn-title">{h(title)}</div>'
        f'<div class="td-turn-sub">{h(sub)}</div>'
        "</div>"
        '<div class="td-turn-rule"></div>'
        "</div>"
    )


def _agent_head(role: str, msg_type: str, ghost: bool = False) -> str:
    return (
        f'<div class="td-agent {role_class(role)}{" ghost" if ghost else ""}">'
        '<div class="td-agent-head">'
        '<div class="td-role">'
        f'<div class="td-role-mark">{role_letter(role)}</div>'
        "<div>"
        f'<div class="td-role-name">{h(role)}</div>'
        f'<div class="td-role-sub">{h(ROLE_LABELS.get(role, role))}</div>'
        "</div>"
        "</div>"
        f'<div class="td-msg-type">{h(msg_type)}</div>'
        "</div>"
    )


def proposal_card_html(run: RunData, role: str) -> str:
    proposal = run.proposals.get(role)
    if not proposal:
        reason = "AI off — deterministic fallback only" if "AI off" in run.flags else "No proposal recorded"
        return (
            _agent_head(role, "not called", ghost=True)
            + f'<div class="td-top-choice"><div><div class="td-top-label">Turn 1</div><div class="td-top-value">{h(reason)}</div></div></div>'
            + '<div class="td-empty">The agent was not called for this run.</div>'
            "</div>"
        )

    ranking = proposal.get("ranking") or []
    top = ranking[0] if ranking else "none"
    vetoes = proposal.get("vetoes") or []
    objections = proposal.get("objections") or []
    facts = proposal.get("facts") or []
    citations = proposal.get("citations") or []
    counter = run.counters
    counter_info = next((c for c in counter if c.get("role") == role), None)

    veto_html = "".join(
        _chip(
            f'<b>{h(v.get("option_id", "?"))}</b> {h(v.get("constraint_id", "?"))}',
            "td-chip-veto",
            f'Code veto · check {v.get("check_id", "")}',
        )
        for v in vetoes
    ) or '<span class="td-chip td-chip-empty">none declared</span>'

    grouped: dict[str, list[dict[str, Any]]] = {}
    for objection in objections:
        if not isinstance(objection, dict):
            continue
        grouped.setdefault(str(objection.get("category") or "OTHER"), []).append(objection)
    objection_html = "".join(
        _chip(
            f'<b>{h(category)}</b> ×{len(items)}',
            "td-chip-obj",
            " · ".join(str(i.get("reason") or "") for i in items)[:260],
        )
        for category, items in grouped.items()
    ) or '<span class="td-chip td-chip-empty">none</span>'

    if counter_info:
        option = counter_info.get("option") or {}
        status = counter_info.get("status")
        status_badge = {
            "validated": badge("validated by code", "green"),
            "rejected": badge("rejected by code", "red"),
            "proposed": badge("proposed", "grey"),
        }.get(str(status), badge(str(status), "grey"))
        counter_html = (
            f'<div class="td-minihead"><span>Counter-option</span><span>{status_badge}</span></div>'
            f'<div class="td-chip td-chip-counter"><b>{h(option.get("option_id", "?"))}</b> base {h(counter_info.get("base_option_id", "?"))}</div>'
            f'<div class="td-top-value" style="margin-top:5px;">{h(fmt_counter_option(option))}</div>'
        )
    else:
        counter_html = ""

    if facts:
        fact_rows = []
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            key = str(fact.get("key") or "fact")
            value = fmt_fact_value(key, fact.get("value"))
            confidence = fmt_pct(fact.get("confidence"))
            fact_rows.append(
                f'<tr><td class="k">{h(key)}{source_badge(fact)}</td>'
                f'<td>{h(value)}<div class="td-top-value">confidence {h(confidence)}</div></td></tr>'
            )
        facts_html = _minihead("Perceived facts", f"{len(fact_rows)}") + (
            '<table class="td-facts">' + "".join(fact_rows) + "</table>"
        )
    else:
        facts_html = ""

    if citations:
        cite_html = _minihead("Citations", f"{len(citations)}") + '<div class="td-citations">' + "".join(
            f'<span class="td-cite{" synthetic" if c.get("synthetic") else ""}">'
            f'<b>{h(c.get("doc") or "source")}</b> · {h(c.get("chunk_id") or "")}'
            f'{" " + badge("synthetic", "synth") if c.get("synthetic") else ""}'
            "</span>"
            for c in citations
            if isinstance(c, dict)
        ) + "</div>"
    else:
        cite_html = _minihead("Citations") + '<div class="td-empty">No citations recorded.</div>'

    return (
        _agent_head(role, "Turn 1 · Propose")
        + '<div class="td-top-choice">'
        "<div>"
        '<div class="td-top-label">Top choice</div>'
        f'<div class="td-top-id">{h(top)}</div>'
        f'<div class="td-top-value">ranked 1 of {len(ranking)} feasible options</div>'
        "</div>"
        f'<div class="td-top-rank">{h(role)}<br/>{h(len(vetoes))} veto(es)</div>'
        "</div>"
        + _minihead("Vetoes from code", f"{len(vetoes)}")
        + f'<div>{veto_html}</div>'
        + _minihead("Objections", f"{len(objections)}")
        + f'<div>{objection_html}</div>'
        + counter_html
        + f'<div class="td-rationale">{h(pretty_rationale(proposal.get("rationale")))}</div>'
        + facts_html
        + cite_html
        + "</div>"
    )


def ballot_card_html(run: RunData, role: str) -> str:
    ballot = run.ballots.get(role)
    if not ballot:
        reason = (
            "AI off — no ballot was taken"
            if "AI off" in run.flags
            else "No ballot recorded (committed at Turn 1 or no shortlist)"
        )
        return (
            _agent_head(role, "not called", ghost=True)
            + f'<div class="td-top-choice"><div><div class="td-top-label">Turn 2</div><div class="td-top-value">{h(reason)}</div></div></div>'
            + '<div class="td-empty">Nothing to vote on in this run.</div>'
            "</div>"
        )

    votes = ballot.get("votes") or []
    ranking = ballot.get("ranking") or []
    rows = []
    for vote in votes:
        if not isinstance(vote, dict):
            continue
        yes = vote.get("vote") == "APPROVE"
        reason = vote.get("reason")
        reason_html = ""
        if reason:
            reason_html = f'<div class="td-vote-reason">{h(reason)}</div>'
        rows.append(
            '<div class="td-vote">'
            f'<div><span class="td-vote-id">{h(vote.get("option_id", "?"))}</span>{reason_html}</div>'
            f'<span class="{"td-vote-yes" if yes else "td-vote-no"}">{"APPROVE" if yes else "DISAPPROVE"}</span>'
            "</div>"
        )
    citations = ballot.get("citations") or []
    cite_html = ""
    if citations:
        cite_html = _minihead("Citations", f"{len(citations)}") + "".join(
            f'<span class="td-cite"><b>{h(c.get("doc") or "source")}</b> · {h(c.get("chunk_id") or "")}</span>'
            for c in citations
            if isinstance(c, dict)
        )

    top = ranking[0] if ranking else "no approval"
    return (
        _agent_head(role, "Turn 2 · Ballot")
        + '<div class="td-top-choice">'
        "<div>"
        '<div class="td-top-label">Approved first</div>'
        f'<div class="td-top-id">{h(top)}</div>'
        f'<div class="td-top-value">{len(ranking)} approved · {len(votes)} votes</div>'
        "</div>"
        f'<div class="td-top-rank">{h(role)}<br/>{h(sum(1 for v in votes if isinstance(v, dict) and v.get("vote") == "APPROVE"))}/{h(len(votes))}</div>'
        "</div>"
        + _minihead("Votes", f"{len(votes)}")
        + ('<div>' + "".join(rows) + "</div>" if rows else '<div class="td-empty">No votes recorded.</div>')
        + f'<div class="td-rationale">{h(pretty_rationale(ballot.get("rationale")))}</div>'
        + cite_html
        + "</div>"
    )


def orchestrator_card_html(run: RunData) -> str:
    payload = run.shortlist_payload
    if not payload:
        return ""
    scores_raw = payload.get("scores") or {}
    scores = sorted(
        ((str(k), float(v)) for k, v in scores_raw.items()),
        key=lambda item: (-item[1], item[0]),
    )
    top_scores = scores[:8]
    score_html = "".join(
        f'<span class="td-score{" top" if index < 3 else ""}">{h(oid)} <b>{score:g}</b></span>'
        for index, (oid, score) in enumerate(top_scores)
    )
    shortlist = payload.get("option_ids") or []
    validated = [c for c in run.counters if c.get("status") == "validated"]
    rejected = [c for c in run.counters if c.get("status") == "rejected"]
    first_votes = payload.get("first_votes") or {}
    first_text = ", ".join(
        f"{h(k)} ×{h(v)}" for k, v in sorted(first_votes.items()) if v
    ) or "no first-choice majority"
    shortlist_text = ", ".join(str(v) for v in shortlist)
    validated_text = " ".join(str(c["option"].get("option_id")) for c in validated) or "none"
    rejected_text = " ".join(str(c["option"].get("option_id")) for c in rejected) or "none"
    return (
        '<div class="td-orch-card">'
        "<div>"
        '<div class="td-orch-kicker">Orchestrator · no AI · no vote</div>'
        '<div class="td-orch-title">Borda shortlist</div>'
        '<div class="td-orch-text">Vetoed options are removed before points. All three agents carry equal weight. No new options are allowed in Turn 2.</div>'
        f'<div class="td-scores">{score_html}</div>'
        "</div>"
        + '<div class="td-orch-side">'
        + _minihead("Shortlist", f"{len(shortlist)}")
        + f'<div class="td-orch-line"><span>Options</span><b>{h(shortlist_text)}</b></div>'
        + f'<div class="td-orch-line"><span>First-choice votes</span><b>{first_text}</b></div>'
        + f'<div class="td-orch-line"><span>Counters validated</span><b>{h(validated_text)}</b></div>'
        + f'<div class="td-orch-line"><span>Counters rejected</span><b>{h(rejected_text)}</b></div>'
        + "</div>"
        "</div>"
    )


def safety_banner_html(run: RunData, turn: int | None = None) -> str:
    blocks = [
        e for e in run.safety_blocks
        if turn is None or int(e.get("turn") or 0) == turn
    ]
    if not blocks:
        return ""
    grouped: Counter[str] = Counter(str((e.get("payload") or {}).get("detail") or "safety block") for e in blocks)
    detail = "; ".join(f"{safety_detail_label(k)} ×{v}" for k, v in grouped.items())
    return _banner(
        "red",
        f"{len(blocks)} safety block{'s' if len(blocks) != 1 else ''}",
        h(detail) + ' <span class="td-status-unsafe" style="font-family:var(--td-mono);font-size:9px;">SEE SAFETY TAB</span>',
        "BLOCK",
    )


def fallback_banner_html(run: RunData) -> str:
    payload = run.fallback
    if not payload:
        return ""
    oid = payload.get("option_id") or "—"
    reason = str(payload.get("reason") or "").replace("_", " ").lower()
    if reason == "ai off":
        text = f"AI was off. The deterministic fallback chose <b>{h(oid)}</b> from the safe pool. The same inputs give the same answer."
    else:
        text = f"No option received all three approvals. The non-AI fallback chose <b>{h(oid)}</b> as the cheapest safe option."
    return _banner("amber", "Fallback · no AI", text, "FALLBACK")


# --------------------------------------------------------------------------- options


def options_table_html(run: RunData) -> str:
    mode = run.mode
    rows = []
    for option in run.all_options:
        oid = str(option.get("option_id") or "")
        if not oid:
            continue
        state = run.state(oid)
        row_class = state if state in {"committed", "shortlisted", "vetoed", "rejected"} else "feasible"
        failures = run.code_failures(oid)
        constraint_ids: list[str] = []
        for check in failures:
            cid = str(check.get("constraint_id") or "?")
            if cid not in constraint_ids:
                constraint_ids.append(cid)
        origin = ""
        if option.get("origin") == "COUNTER":
            origin = '<span class="td-opt-origin">CTR</span>'
        elif option.get("divert_to"):
            origin = '<span class="td-opt-origin">DIVERT</span>'
        veto_html = ""
        if constraint_ids:
            veto_html = (
                '<div class="td-opt-veto" title="Vetoed by code: '
                + h(", ".join(constraint_ids))
                + '">'
                + h(" · ".join(constraint_ids))
                + "</div>"
            )
        elif "AI off" in run.flags and state == "vetoed":
            veto_html = '<div class="td-opt-veto">not in safe pool</div>' 
        if mode == "GROUND":
            dep = fmt_hhmm(option.get("departure_slot")) if option.get("departure_slot") is not None else "—"
            arr = fmt_hhmm(option.get("arrival_slot"))
            time_cell = f'<span class="mono">{h(dep)}</span> <span class="td-time-arrow">→</span> <span class="mono">{h(arr)}</span>'
        else:
            time_cell = f'<span class="mono">{h(fmt_hhmm(option.get("arrival_slot")))}</span>'
        speed = f"{fmt_num(option.get('speed_recovery_min'))} min" if option.get("speed_recovery_min") else "—"
        fl = f"FL{option.get('cruise_level')}" if option.get("cruise_level") else "—"
        cells = [
            f'<td><span class="td-opt-id">{h(oid)}</span>{origin}{veto_html}</td>',
            f"<td>{state_badge(state)}</td>",
            f"<td>{time_cell}</td>",
            f'<td class="mono">{h(option.get("runway") or "—")}</td>',
            f'<td class="mono">{h(option_hold_absorb(option))}</td>',
        ]
        if mode == "GROUND":
            cells.append(f'<td class="mono">{h(speed)}</td>')
        cells.extend(
            [
                f'<td class="mono">{h(fl)}</td>',
                f'<td class="mono">{h(option.get("gate") or "—")}</td>',
                f'<td class="mono">{h(option_next_leg(option))}</td>',
            ]
        )
        rows.append(f'<tr class="{row_class}">' + "".join(cells) + "</tr>")

    extra_header = '<th class="num">Recovery</th>' if mode == "GROUND" else ""
    time_header = "Departure → arrival" if mode == "GROUND" else "Arrival"
    table = (
        '<div class="td-table-wrap"><table class="td-table">'
        "<thead><tr>"
        "<th>Option</th><th>State</th>"
        f"<th>{time_header}</th><th>Runway</th><th>Hold / absorb</th>{extra_header}"
        "<th>Flight level</th><th>Gate</th><th>Next leg</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table></div>"
    )
    return table

def options_summary_html(run: RunData) -> str:
    committed = "1 committed" if run.committed_id else "no commit"
    counters = [c for c in run.counters]
    verified = sum(1 for c in counters if c.get("status") == "validated")
    rejected = sum(1 for c in counters if c.get("status") == "rejected")
    legend = (
        '<div class="td-legend">'
        '<span class="td-legend-item"><span class="td-swatch committed"></span>committed</span>'
        '<span class="td-legend-item"><span class="td-swatch shortlisted"></span>shortlisted</span>'
        '<span class="td-legend-item"><span class="td-swatch feasible"></span>feasible</span>'
        '<span class="td-legend-item"><span class="td-swatch vetoed"></span>vetoed by code</span>'
        "</div>"
    )
    safe_text = f"<span><b>{len(run.safe_pool)}</b> in safe pool</span>" if "AI off" in run.flags else ""
    return (
        '<div class="td-check-summary">'
        f"<span><b>{len(run.options)}</b> generated</span>"
        f"<span><b>{len(run.shared_passed)}</b> pass shared checks</span>"
        f"{safe_text}"
        f"<span><b>{len(run.shortlist)}</b> shortlisted</span>"
        f"<span><b>{committed}</b></span>"
        f"<span><b>{verified}</b> counter(s) validated · <b>{rejected}</b> rejected</span>"
        "</div>" + legend
    )


# --------------------------------------------------------------------------- resolution


def resolution_panel_html(run: RunData) -> str:
    status_class = {"FALLBACK": "fallback", "ESCALATED": "escalated"}.get(run.status, "")
    option = run.committed_option or {}
    turn = run.turn
    dots = "".join(
        f'<span class="td-turn-dot{" on" if turn >= n else ""}"></span>' for n in (1, 2)
    )
    if run.status == "ESCALATED" and turn == 0:
        turn_value = "Setup"
    else:
        turn_value = str(turn)
    cap = "Within the 2-turn cap" if 0 <= turn <= 2 else "Outside the cap"
    if run.status == "ESCALATED":
        cap = "No option was committed"
    option_html = ""
    if run.committed_id:
        extra = []
        if option.get("divert_to"):
            extra.append(f'<span class="td-res-option-item">Divert to <b>{h(option["divert_to"])}</b></span>')
        if option.get("cruise_level"):
            extra.append(f'<span class="td-res-option-item">Flight level <b>FL{h(option["cruise_level"])}</b></span>')
        if option.get("holding_min"):
            extra.append(f'<span class="td-res-option-item">Hold <b>{h(option["holding_min"])} min</b></span>')
        if option.get("enroute_absorb_min"):
            extra.append(f'<span class="td-res-option-item">Absorb en route <b>{h(option["enroute_absorb_min"])} min</b></span>')
        if option.get("speed_recovery_min"):
            extra.append(f'<span class="td-res-option-item">Speed recovery <b>{h(option["speed_recovery_min"])} min</b></span>')
        option_html = (
            '<div class="td-res-option">'
            f'<span class="td-res-option-main">Committed <b>{h(run.committed_id)}</b></span>'
            f'<span class="td-res-option-item">Arrival <b>{h(fmt_hhmm(option.get("arrival_slot")))}</b></span>'
            f'<span class="td-res-option-item">Runway <b>{h(option.get("runway") or "—")}</b></span>'
            f'<span class="td-res-option-item">Gate <b>{h(option.get("gate") or "—")}</b></span>'
            f'<span class="td-res-option-item">Next leg <b>{h(option_next_leg(option))}</b></span>'
            + "".join(extra)
            + "</div>"
        )
    costs = run.costs
    cost_html = ""
    if run.committed_id:
        cost_html = (
            '<div class="td-cost-grid">'
            + "".join(
                f'<div class="td-cost"><div class="td-cost-label">{h(role)} disclosed cost</div><div class="td-cost-value">{h(fmt_eur(costs.get(role, 0)))}</div></div>'
                for role in ROLES
            )
            + f'<div class="td-cost td-cost-total"><div class="td-cost-label">Total</div><div class="td-cost-value">{h(fmt_eur(run.total_cost))}</div></div>'
            "</div>"
        )
    return (
        f'<div class="td-resolution {status_class}">'
        '<div class="td-res-top">'
        "<div>"
        '<div class="td-res-label">Resolution</div>'
        f'<div class="td-res-status">{h(run.status)}</div>'
        f'<div class="td-res-reason">{h(human_reason(run.reason))}</div>'
        f'<div class="td-res-reason" style="margin-top:5px;">{badge(human_decided_by(run.decided_by), "green" if run.decided_by == "AGENTS" else "amber")}</div>'
        "</div>"
        '<div class="td-turn-box">'
        '<div class="td-res-label">Turn reached</div>'
        f'<div class="td-turn-count">{h(turn_value)}<small> / 2</small></div>'
        f'<div class="td-turn-dots">{dots}</div>'
        f'<div class="td-turn-cap">{h(cap)}</div>'
        "</div>"
        "</div>"
        + option_html
        + cost_html
        + "</div>"
    )


def checks_table_html(
    run: RunData,
    *,
    only_failures: bool = False,
    max_rows: int | None = None,
) -> str:
    checks = list(run.final_checks)
    if only_failures:
        checks = [c for c in checks if not c.get("passed", True)]
    checks.sort(
        key=lambda c: (
            {"SHARED": 0, "ATC": 1, "PILOT": 2, "GROUND": 3}.get(str(c.get("owner")), 9),
            str(c.get("constraint_id") or ""),
        )
    )
    if max_rows is not None:
        checks = checks[:max_rows]
    if not checks:
        return (
            '<div class="td-empty-state" style="padding:20px;">'
            '<div class="td-note">No checks to show for this view.</div>'
            "</div>"
        )
    rows = []
    for check in checks:
        passed = bool(check.get("passed"))
        facts = check.get("facts_used") or []
        fact_html = "".join(_chip(h(str(f)), "td-chip") for f in facts)
        detail = str(check.get("detail") or "")
        source = str(check.get("source") or "—")
        rows.append(
            "<tr>"
            f'<td><div class="td-check-id">{h(check.get("constraint_id") or "?")}</div>'
            f'<div class="td-check-detail">{h(detail)}</div></td>'
            f'<td class="mono">{h(check.get("owner") or "?")}</td>'
            f'<td><span class="{"td-check-pass" if passed else "td-check-fail"}">{"PASS" if passed else "FAIL"}</span></td>'
            f'<td class="mono">{h(fmt_num(check.get("value")))}</td>'
            f'<td class="mono">{h(fmt_num(check.get("limit")))}</td>'
            f'<td class="td-unit">{h(check.get("unit") or "—")}</td>'
            f'<td class="wrap" style="font-size:9.5px;color:var(--td-muted);">{h(source)}{(" " + fact_html) if fact_html else ""}</td>'
            "</tr>"
        )
    return (
        '<div class="td-table-wrap" style="background:var(--td-surface);"><table class="td-check-table">'
        "<thead><tr><th>Constraint</th><th>Owner</th><th>Result</th><th>Value</th><th>Limit</th><th>Unit</th><th>Source</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table></div>"
    )


def checks_summary_html(run: RunData) -> str:
    checks = run.final_checks
    failures = run.commit_failures
    total = len(checks)
    if run.status == "ESCALATED":
        return (
            '<div class="td-check-summary">'
            + badge("No commit attempted", "grey")
            + "<span>Escalated before the commit gate.</span>"
            "</div>"
        )
    if not checks:
        return '<div class="td-check-summary">' + badge("No final checks recorded", "amber") + "</div>"
    return (
        '<div class="td-check-summary">'
        f'<span class="td-check-badge {"fail" if failures else "pass"}">{"FAIL" if failures else "PASS"}</span>'
        f"<span><b>{total}</b> hard checks re-run on the committed option</span>"
        f"<span><b>{len(failures)}</b> failed</span>"
        f"<span>{badge('assert_commit_safe()', 'grey')}</span>"
        "</div>"
    )


# --------------------------------------------------------------------------- safety


def commit_gate_html(run: RunData) -> str:
    if run.status == "ESCALATED":
        return (
            '<div class="td-gate idle">'
            '<div class="td-gate-title">Commit gate</div>'
            '<div class="td-gate-text">No option was committed. The case was escalated to a human, so there was nothing to re-check.</div>'
            "</div>"
        )
    failures = run.commit_failures
    passed = run.commit_safe
    kind = "fail" if failures or not passed else ""
    title = "Commit gate passed" if passed else "Commit gate failed"
    text = (
        f"assert_commit_safe() re-ran <b>{len(run.final_checks)}</b> hard checks on <b>{h(run.committed_id or '—')}</b> and found "
        f"<b>{len(failures)}</b> failure{'s' if len(failures) != 1 else ''}."
    )
    if failures:
        text += " The unsafe option was not committed."
    return (
        f'<div class="td-gate {kind}">'
        f'<div class="td-gate-title">{h(title)}</div>'
        f'<div class="td-gate-text">{text}</div>'
        '<div class="td-gate-meta">'
        + badge("re-checks every constraint", "grey")
        + badge("cannot be overridden by an agent", "grey")
        + "</div>"
        "</div>"
    )


def _safety_group_details(run: RunData, role: str, option_id: str, detail: str) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    role_checks = run.checks_by_role_option.get((role, option_id), [])
    checks.extend(role_checks)
    checks.extend(run.checks_by_option.get(option_id, []))
    if detail == "unsafe counter rejected":
        checks = run.checks_by_option.get(option_id, [])
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for check in checks:
        if not isinstance(check, dict):
            continue
        if check.get("passed", True):
            continue
        key = str(check.get("check_id") or f"{check.get('constraint_id')}:{option_id}")
        if key in seen:
            continue
        seen.add(key)
        out.append(check)
    return out


def safety_cards_html(run: RunData) -> str:
    if not run.safety_blocks:
        return (
            '<div class="td-gate">'
            '<div class="td-gate-title">No safety blocks</div>'
            '<div class="td-gate-text">No agent tried to approve an option outside the code checks. The guard is still active: every approval is filtered and every commit is re-checked.</div>'
            "</div>"
        )
    groups: dict[tuple[int, str, str], list[str]] = {}
    for entry in run.safety_blocks:
        payload_value = entry.get("payload")
        payload = payload_value if isinstance(payload_value, dict) else {}
        key = (
            int(entry.get("turn") or 0),
            str(payload.get("role") or "ORCHESTRATOR"),
            str(payload.get("detail") or "safety block"),
        )
        oid = str(payload.get("option_id") or "")
        groups.setdefault(key, []).append(oid)

    cards = []
    for (turn, role, detail), option_ids in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1], item[0][2])):
        unique_ids = [oid for oid in dict.fromkeys(option_ids) if oid]
        checks: list[dict[str, Any]] = []
        for oid in unique_ids:
            checks.extend(_safety_group_details(run, role, oid, detail))
        check_chips = []
        seen_checks: set[str] = set()
        for check in checks:
            cid = str(check.get("constraint_id") or "?")
            if cid in seen_checks:
                continue
            seen_checks.add(cid)
            check_chips.append(
                _chip(
                    f"<b>{h(cid)}</b> {h(check.get('detail') or '')}",
                    "td-chip-veto",
                    f"{check.get('source', '')} · value {check.get('value')} limit {check.get('limit')} {check.get('unit', '')}",
                )
            )
        option_html = " ".join(
            f'<span class="td-safety-option">{h(oid)}</span>' for oid in unique_ids[:10]
        )
        if len(unique_ids) > 10:
            option_html += f' <span class="td-safety-meta">+{len(unique_ids) - 10} more</span>'
        if detail == "omitted veto":
            title = "Code veto added by the orchestrator"
        elif detail == "fabricated veto":
            title = "Unsupported veto discarded"
        elif detail == "unsafe counter rejected":
            title = "Unsafe counter rejected"
        elif detail == "approve outside shortlist":
            title = "Out-of-scope approval discarded"
        elif detail == "approve of unsafe option":
            title = "Unsafe approval discarded"
        elif detail == "commit re-check failed":
            title = "Commit re-check failed"
        else:
            title = detail.replace("_", " ").title()
        cards.append(
            '<div class="td-safety-card">'
            '<div class="td-safety-head">'
            f'<div class="td-safety-title">{h(title)}</div>'
            f'<div class="td-safety-meta">Turn {h(turn)} · {h(role)} · {len(unique_ids)} option(s)</div>'
            "</div>"
            f'<div class="td-safety-text">{h(safety_detail_label(detail))}</div>'
            f'<div class="td-safety-facts">{option_html}{"".join(check_chips)}</div>'
            "</div>"
        )
    return "".join(cards)


# --------------------------------------------------------------------------- audit


def chain_panel_html(run: RunData) -> str:
    last_hash = str(run.raw_entries[-1].get("payload_sha256") if run.raw_entries else "")
    first_seq = run.raw_entries[0].get("seq") if run.raw_entries else "—"
    last_seq = run.raw_entries[-1].get("seq") if run.raw_entries else "—"
    return (
        f'<div class="td-chain{" broken" if not run.chain_ok else ""}">'
        "<div>"
        f'<div class="td-chain-title">{"Chain verified" if run.chain_ok else "Chain broken"}</div>'
        f'<div class="td-chain-meta">{len(run.raw_entries)} entries · seq {h(first_seq)}–{h(last_seq)} · payload digest + link checked</div>'
        "</div>"
        '<div style="text-align:right;">'
        f'<div class="td-chain-meta">log.jsonl sha256</div>'
        f'<div class="td-chain-hash">{h(short_hash(run.log_sha, 20))}</div>'
        f'<div class="td-chain-meta" style="margin-top:5px;">tip {h(short_hash(last_hash, 16))}</div>'
        "</div>"
        "</div>"
    )


def timeline_html(run: RunData) -> str:
    rows = []
    for entry in run.raw_entries:
        event = str(entry.get("event") or "")
        actor = str(entry.get("actor") or "")
        turn = entry.get("turn")
        row_class = "safety" if event == "SAFETY_BLOCK" else "commit" if event in ("COMMIT", "CONSENSUS_REACHED") else ""
        rows.append(
            f'<tr class="{row_class}">'
            f'<td class="td-seq">{h(entry.get("seq", "—"))}</td>'
            f'<td class="td-seq">{h("setup" if turn == 0 else f"T{turn}")}</td>'
            f'<td class="td-actor td-actor-{h(actor)}">{h(actor)}</td>'
            f'<td class="td-event">{h(event_label(event))}</td>'
            f'<td class="td-event-summary">{h(event_summary(entry))}</td>'
            f'<td class="td-seq">{h(short_hash(entry.get("payload_sha256"), 10))}</td>'
            "</tr>"
        )
    return (
        '<div class="td-table-wrap"><table class="td-timeline">'
        "<thead><tr><th>Seq</th><th>Turn</th><th>Actor</th><th>Event</th><th>What happened</th><th>Digest</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table></div>"
    )


def context_table_html(run: RunData) -> str:
    turns = run.context_turns
    if not turns:
        return (
            '<div class="td-gate idle">'
            '<div class="td-gate-title">No agent context</div>'
            '<div class="td-gate-text">The agents were not called in this run (AI off). There are no context hashes to compare.</div>'
            "</div>"
        )
    rows = []
    for turn in turns:
        hashes = [run.context_hash(turn, role) or "" for role in ROLES]
        distinct = len(set(hashes))
        cells = "".join(
            f'<td><span class="td-hash" title="{h(digest)}">{h(short_hash(digest, 14))}</span></td>'
            for digest in hashes
        )
        rows.append(
            f"<tr><td class=\"mono\">Turn {h(turn)}</td>{cells}<td class=\"mono\">{distinct}/{len(ROLES)} distinct</td></tr>"
        )
    return (
        '<div class="td-table-wrap"><table class="td-context-table">'
        "<thead><tr><th>Turn</th><th>ATC</th><th>Pilot</th><th>Ground</th><th>Independence</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table></div>"
        '<div class="td-table-note">Each hash covers the public event, the agent\'s own inputs and a private-data fingerprint. Different hashes mean the three agents saw different private inputs; the orchestrator only routed public messages.</div>'
    )


def usage_table_html(run: RunData) -> str:
    rows = run.usage_rows
    if not rows:
        return (
            '<div class="td-note">No model calls recorded. Stub agents and the fallback run entirely in code.</div>'
        )
    body = []
    for row in rows:
        cached = "yes" if row.get("cached") else "no"
        ms = row.get("ms")
        try:
            ms_text = f"{float(ms):,.0f} ms"
        except Exception:
            ms_text = "—"
        body.append(
            "<tr>"
            f'<td class="td-seq">{h(row.get("seq"))}</td>'
            f'<td class="td-seq">T{h(row.get("turn"))}</td>'
            f'<td class="td-actor td-actor-{h(row.get("role"))}">{h(row.get("role"))}</td>'
            f'<td class="mono">{h(row.get("model") or "—")}</td>'
            f'<td class="mono">{h(fmt_num(row.get("prompt_tokens")))}</td>'
            f'<td class="mono">{h(fmt_num(row.get("completion_tokens")))}</td>'
            f'<td class="mono">{h(ms_text)}</td>'
            f'<td class="mono">{h(cached)}</td>'
            "</tr>"
        )
    return (
        '<div class="td-table-wrap"><table class="td-timeline">'
        "<thead><tr><th>Seq</th><th>Turn</th><th>Agent</th><th>Model</th><th>Prompt tokens</th><th>Completion tokens</th><th>Time</th><th>Cached</th></tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table></div>"
    )


def manifest_html(run: RunData) -> str:
    manifest = run.manifest
    impls = manifest.get("agent_impl") or {}
    impl_text = " · ".join(f"{h(role)} {h(impls.get(role, '—'))}" for role in ROLES)
    prompt_hashes = manifest.get("prompt_hashes") or {}
    cells = [
        ("Run record", run.run_id, True),
        ("Dataset row", fmt_num(manifest.get("dataset_row")), False),
        ("Seed", fmt_num(manifest.get("seed")), False),
        ("Mode", run.mode or "—", False),
        ("Agents", impl_text, False),
        ("Config sha256", short_hash(manifest.get("config_sha256"), 18), False),
        ("Code version", manifest.get("code_version") or "—", False),
        ("Created", manifest.get("created") or "—", False),
        ("Prompt hashes", f"{len(prompt_hashes)} recorded" if prompt_hashes else "none recorded", False),
    ]
    remainder = (4 - len(cells) % 4) % 4
    return (
        '<div class="td-manifest-grid">'
        + "".join(
            f'<div class="td-manifest-cell"><div class="td-manifest-label">{h(label)}</div><div class="td-manifest-value{" big" if big else ""}">{value}</div></div>'
            for label, value, big in cells
        )
        + '<div class="td-manifest-cell"></div>' * remainder
        + "</div>"
    )


# --------------------------------------------------------------------------- generic


def empty_state_html() -> str:
    return (
        '<div class="td-empty-state">'
        "<h3>No saved run</h3>"
        "<p>Choose a replay from the sidebar, or run a negotiation. Every view is built from the run's log, resolution and manifest.</p>"
        "</div>"
    )


def ready_state_html() -> str:
    return (
        '<div class="td-empty-state">'
        '<div class="td-kicker" style="color:var(--td-muted);margin-bottom:8px;">New negotiation</div>'
        "<h3>Ready to run</h3>"
        "<p>Pick a demo scenario or a DOT row in the sidebar, then run the negotiation. "
        "The desk will show the three agent views, every constraint check, the safety blocks and the hash-chained log.</p>"
        "</div>"
    )


def footer_html(run: RunData) -> str:
    return (
        '<div class="td-footer">'
        f"<span>Triad · one orchestrator + three subagents · run {h(run.run_id)}</span>"
        "<span>Times local · ICAO wake categories · synthetic values seeded and labelled</span>"
        "</div>"
    )


def raw_event_choices(run: RunData) -> list[tuple[str, int]]:
    labels: list[tuple[str, int]] = []
    for entry in run.raw_entries:
        labels.append(
            (
                f"{entry.get('seq')} · T{entry.get('turn')} · {entry.get('actor')} · {event_label(str(entry.get('event')))}",
                int(entry.get("seq") or 0),
            )
        )
    return labels


def raw_event_payload(run: RunData, seq: int) -> dict[str, Any] | None:
    for entry in run.raw_entries:
        if int(entry.get("seq") or 0) == int(seq):
            return entry
    return None


# Public aliases used by the Streamlit shell.
section_html = _section
banner_html = _banner
