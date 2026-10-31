"""Live negotiation playback: pure helpers for the in-progress view.

Everything here works on the dict returned by ``data.live_status`` (or on a partial
RunData's raw log entries) and returns plain values or HTML strings, so it can be
unit-tested without Streamlit. The Streamlit fragment lives in ``streamlit_app.py``.
"""

from __future__ import annotations

from typing import Any, Callable

from .data import ROLES
from .format import ROLE_NAMES
from .render import _agent_head, h

TERMINAL_PHASES = ("commit", "fallback", "done")
TURN_KINDS = {1: "proposal", 2: "ballot", 3: "ballot"}
TURN_TITLES = {1: "Turn 1 · Propose", 2: "Turn 2 · Ballot", 3: "Turn 3 · Final ballot"}


# --------------------------------------------------------------------------- copy helpers


def role_name(role: str) -> str:
    return ROLE_NAMES.get(role, role.title())


def join_names(roles: list[str] | tuple[str, ...]) -> str:
    names = [role_name(r) for r in roles]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def fmt_elapsed(seconds: float) -> str:
    total = max(0, int(seconds))
    if total < 60:
        return f"{total} s"
    return f"{total // 60}:{total % 60:02d} min"


def _received(status: dict[str, Any], turn: int) -> list[str]:
    if turn == 1:
        return list(status.get("proposals_received") or [])
    return list(status.get("ballots_received") or [])


def _missing(received: list[str]) -> list[str]:
    return [role for role in ROLES if role not in received]


def _is_terminal(status: dict[str, Any]) -> bool:
    return bool(status.get("done")) or status.get("phase") in TERMINAL_PHASES


# --------------------------------------------------------------------------- phase strip model


def phase_steps(
    status: dict[str, Any],
    *,
    ai_off: bool = False,
    options: int | None = None,
    passed: int | None = None,
    option_id: str | None = None,
) -> list[dict[str, str]]:
    """Five steps: Setup, Turn 1, Turn 2, Turn 3, Outcome.

    ``state`` is one of ``done``, ``active``, ``pending``, ``skipped``, ``stopped``
    (the last one for an escalation). ``options``/``passed``/``option_id`` come
    from the partial run when known and only enrich the copy.
    """

    phase = str(status.get("phase") or "waiting")
    turn = int(status.get("turn") or 0)
    outcome = status.get("outcome")
    terminal = _is_terminal(status)
    skip_text = "Not needed" if outcome == "committed" else "Not reached"
    steps: list[dict[str, str]] = []

    # ---- setup
    if phase == "waiting":
        setup = ("active", "Loading the flight" if ai_off else "Preparing the agents")
    elif phase == "setup" and not ai_off:
        setup = ("active", "Generating options")
    elif phase == "setup":
        setup = ("active", "Running code checks")
    elif options:
        setup = ("done", f"{options} options · {passed or 0} pass checks")
    else:
        setup = ("done", "Done")
    steps.append({"key": "setup", "label": "Setup", "state": setup[0], "value": setup[1]})

    # ---- turns
    for number, label, pending_text in (
        (1, "Turn 1 · Proposals", "Starts after setup"),
        (2, "Turn 2 · Ballots", "Only if Turn 1 does not agree"),
        (3, "Turn 3 · Final ballot", "Only if Turn 2 does not agree"),
    ):
        key = f"turn{number}"
        if ai_off:
            state, value = "skipped", "Agents not called"
        elif turn > number:
            state, value = "done", "3 of 3 received"
        elif turn == number and phase == key:
            state, value = "active", f"{len(_received(status, number))} of 3 received"
        elif turn == number:
            state, value = "done", f"{len(_received(status, number))} of 3 received"
        elif terminal:
            state, value = "skipped", skip_text
        else:
            state, value = "pending", pending_text
        steps.append({"key": key, "label": label, "state": state, "value": value})

    # ---- outcome
    if outcome == "escalated":
        outcome_step = ("Escalated", "stopped", "Sent to a human")
    elif outcome == "fallback":
        outcome_step = ("Fallback", "done", f"Chose {option_id}" if option_id else "Option chosen")
    elif outcome == "committed":
        outcome_step = ("Commit", "done", f"{option_id} committed" if option_id else "Committed")
    elif phase == "fallback":
        outcome_step = ("Fallback", "active", "Picking the cheapest safe option")
    elif phase == "commit":
        outcome_step = ("Commit", "active", "Running final checks")
    else:
        outcome_step = ("Commit or fallback", "pending", "Not started")
    steps.append(
        {"key": "outcome", "label": outcome_step[0], "state": outcome_step[1], "value": outcome_step[2]}
    )
    return steps


# --------------------------------------------------------------------------- status line


def status_line(
    status: dict[str, Any],
    *,
    ai_off: bool = False,
    impl: str = "stub",
    option_id: str | None = None,
) -> tuple[str, str]:
    """One plain sentence about what is happening now, plus a tone for styling.

    Tone is ``active``, ``done`` or ``stopped``.
    """

    phase = str(status.get("phase") or "waiting")
    turn = int(status.get("turn") or 0)
    outcome = status.get("outcome")

    if status.get("done"):
        chosen = f" {option_id}" if option_id else ""
        if outcome == "escalated":
            return "Escalated · no option passed every check. Saving the run files.", "stopped"
        if outcome == "fallback":
            return f"Fallback committed{chosen}. Saving the run files.", "done"
        where = f" at Turn {turn}" if turn else ""
        return f"Committed{chosen}{where}. Saving the run files.", "done"

    if phase == "waiting":
        if ai_off:
            return "Setup · loading the flight data", "active"
        if impl == "llm":
            return "Setup · building the agents. Each agent reads its inputs with one model call.", "active"
        return "Setup · building the agents", "active"
    if phase == "setup":
        if ai_off:
            return "Setup · running every agent's code checks on every option", "active"
        return "Setup · generating options and running shared checks", "active"
    if phase == "commit":
        return "Commit · re-running every hard check on the chosen option", "active"
    if phase == "fallback":
        if ai_off:
            return "Fallback · AI is off. Picking the cheapest option that passes every check.", "active"
        return "Fallback · no option was approved by all three agents. Picking the cheapest safe option.", "active"

    number = turn if turn in TURN_KINDS else 1
    kind = TURN_KINDS[number]
    prefix = "Turn 3 · final ballot" if number == 3 else f"Turn {number}"
    received = _received(status, number)
    missing = _missing(received)
    if not missing:
        if number == 1:
            return (
                f"{prefix} · all 3 proposals in. The orchestrator is checking vetoes and building the shortlist.",
                "active",
            )
        return f"{prefix} · all 3 ballots in. The orchestrator is counting approvals.", "active"
    if not received:
        return f"{prefix} · waiting for {kind}s from {join_names(missing)}", "active"
    if len(missing) == 1:
        return (
            f"{prefix} · waiting for {role_name(missing[0])}'s {kind} ({len(received)} of 3 received)",
            "active",
        )
    return (
        f"{prefix} · waiting for {kind}s from {join_names(missing)} ({len(received)} of 3 received)",
        "active",
    )


# --------------------------------------------------------------------------- partial log views


def messages_by_turn(raw_entries: list[dict[str, Any]], event: str) -> dict[int, dict[str, dict[str, Any]]]:
    """{turn: {role: payload}} for PROPOSAL or BALLOT entries, latest per role and turn."""

    out: dict[int, dict[str, dict[str, Any]]] = {}
    for entry in raw_entries:
        if entry.get("event") != event:
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        role = str(payload.get("sender") or entry.get("actor") or "")
        try:
            turn = int(entry.get("turn") or 0)
        except (TypeError, ValueError):
            turn = 0
        if role:
            out.setdefault(turn, {})[role] = payload
    return out


def shortlist_payload_for(raw_entries: list[dict[str, Any]], for_turn: int) -> dict[str, Any]:
    """The SHORTLIST payload built for ``for_turn`` (2 or 3), or {}."""

    found: dict[str, Any] = {}
    for entry in raw_entries:
        if entry.get("event") != "SHORTLIST":
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        try:
            target = int(payload.get("for_turn") or 2)
        except (TypeError, ValueError):
            target = 2
        if target == for_turn:
            found = payload
    return found


# --------------------------------------------------------------------------- html


LIVE_CSS = """
<style>
.td-flow.td-live-flow { grid-template-columns: repeat(5, minmax(0, 1fr)); margin-top: 6px; }
.td-flow-step.pending { opacity: .55; }
.td-flow-step.stopped { border-top-color: var(--td-red); }
.td-flow-step.active .td-flow-label { color: var(--td-amber); }
.td-live-dot {
  display: inline-block; width: 6px; height: 6px; margin-right: 6px; border-radius: 50%;
  background: var(--td-amber); vertical-align: 1px; animation: td-live-pulse 1.4s ease-in-out infinite;
}
.td-live-status {
  display: flex; justify-content: space-between; align-items: baseline; gap: 16px;
  margin: 12px 0 4px; padding: 10px 14px;
  background: var(--td-surface); border: 1px solid var(--td-line); border-left: 4px solid var(--td-amber);
  border-radius: 2px; font-size: 12.5px; line-height: 1.45; color: var(--td-ink);
}
.td-live-status.done { border-left-color: var(--td-green); }
.td-live-status.stopped { border-left-color: var(--td-red); }
.td-live-status.done .td-live-dot { background: var(--td-green); animation: none; }
.td-live-status.stopped .td-live-dot { background: var(--td-red); animation: none; }
.td-live-elapsed {
  font-family: var(--td-mono); font-size: 9.5px; letter-spacing: .08em; color: var(--td-muted); white-space: nowrap;
}
.td-live-reveal { animation: td-rise .42s ease-out both; height: 100%; }
.td-live-pending .td-agent { min-height: 168px; }
.td-live-pending .td-msg-type { color: var(--td-amber); border-color: #dec49a; }
.td-live-hold { border: 1px dashed var(--td-line-strong); padding: 10px 12px; margin: 8px 0; }
.td-live-hold-fn { margin-top: 4px; font-family: var(--td-mono); font-size: 9.5px; color: var(--td-muted); word-break: break-word; }
@keyframes td-live-pulse { 0%, 100% { opacity: .25; } 50% { opacity: 1; } }
@media (prefers-reduced-motion: reduce) {
  .td-live-dot, .td-live-reveal { animation: none; }
}
@media (max-width: 820px) {
  .td-flow.td-live-flow { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>
"""


def strip_html(steps: list[dict[str, str]]) -> str:
    cells = []
    for step in steps:
        dot = '<span class="td-live-dot"></span>' if step["state"] == "active" else ""
        cells.append(
            f'<div class="td-flow-step {h(step["state"])}">'
            f'<div class="td-flow-label">{dot}{h(step["label"])}</div>'
            f'<div class="td-flow-value">{h(step["value"])}</div>'
            "</div>"
        )
    return '<div class="td-flow td-live-flow">' + "".join(cells) + "</div>"


def status_html(text: str, tone: str, elapsed: float) -> str:
    return (
        f'<div class="td-live-status {h(tone)}">'
        f'<div><span class="td-live-dot"></span>{h(text)}</div>'
        f'<div class="td-live-elapsed">Elapsed {h(fmt_elapsed(elapsed))}</div>'
        "</div>"
    )


def pending_card_html(role: str, turn: int, *, started: bool) -> str:
    """Placeholder card in the agent's colours until its message is logged."""

    kind = TURN_KINDS.get(turn, "message")
    if started:
        head, value = "Waiting", f"Waiting for {role_name(role)}'s {kind}"
        note = "The card fills in when the message is logged."
    else:
        head, value = "Not started", "Starts after setup" if turn == 1 else "Not started"
        note = "Nothing logged yet."
    return (
        '<div class="td-live-pending">'
        + _agent_head(role, head, ghost=True)
        + '<div class="td-top-choice"><div>'
        f'<div class="td-top-label">{h(TURN_TITLES.get(turn, f"Turn {turn}"))}</div>'
        f'<div class="td-top-value">{h(value)}</div>'
        "</div></div>"
        f'<div class="td-empty">{h(note)}</div>'
        "</div></div>"
    )


def reveal_html(inner: str, index: int = 0) -> str:
    """Wrap a card so it rises in once; ``index`` staggers cards that land together."""

    return f'<div class="td-live-reveal" style="animation-delay:{index * 110}ms">{inner}</div>'


def hold_html(name: str, exc: BaseException) -> str:
    detail = f"{type(exc).__name__}: {exc}"
    return (
        '<div class="td-live-hold">'
        '<div class="td-note">Still negotiating. This part appears once the log has what it needs.</div>'
        f'<div class="td-live-hold-fn">{h(name)} failed on the partial run · {h(detail[:240])}</div>'
        "</div>"
    )


def safe_html(name: str, builder: Callable[..., str], *args: Any) -> str:
    """Call a render builder on a partial run; on failure return a calm placeholder naming it."""

    try:
        return builder(*args)
    except Exception as exc:  # noqa: BLE001 - partial runs can miss fields; shown, not hidden
        return hold_html(name, exc)
