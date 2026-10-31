"""Pure helpers behind the live negotiation view (app/components/live.py)."""

from __future__ import annotations

from typing import Any

from app.components import live


def _status(phase: str = "waiting", turn: int = 0, proposals=(), ballots=(), done=False, outcome=None) -> dict[str, Any]:
    return {
        "phase": phase,
        "turn": turn,
        "proposals_received": list(proposals),
        "ballots_received": list(ballots),
        "done": done,
        "outcome": outcome,
        "entries": 0,
    }


def _states(steps: list[dict[str, str]]) -> list[str]:
    return [step["state"] for step in steps]


def test_waiting_marks_setup_active_and_rest_pending() -> None:
    steps = live.phase_steps(_status())
    assert [s["key"] for s in steps] == ["setup", "turn1", "turn2", "turn3", "outcome"]
    assert _states(steps) == ["active", "pending", "pending", "pending", "pending"]
    assert steps[-1]["label"] == "Commit or fallback"


def test_turn1_partial_counts_proposals() -> None:
    steps = live.phase_steps(_status("turn1", 1, ["ATC", "PILOT"]), options=12, passed=9)
    assert _states(steps) == ["done", "active", "pending", "pending", "pending"]
    assert steps[0]["value"] == "12 options · 9 pass checks"
    assert steps[1]["value"] == "2 of 3 received"


def test_turn3_marks_earlier_turns_done() -> None:
    steps = live.phase_steps(_status("turn3", 3, ["ATC", "PILOT", "GROUND"], ["GROUND"]))
    assert _states(steps) == ["done", "done", "done", "active", "pending"]
    assert steps[2]["value"] == "3 of 3 received"
    assert steps[3]["value"] == "1 of 3 received"


def test_turn1_commit_skips_later_turns() -> None:
    status = _status("done", 1, ["ATC", "PILOT", "GROUND"], done=True, outcome="committed")
    steps = live.phase_steps(status, option_id="O3")
    assert _states(steps) == ["done", "done", "skipped", "skipped", "done"]
    assert steps[2]["value"] == "Not needed"
    assert steps[-1]["label"] == "Commit"
    assert steps[-1]["value"] == "O3 committed"


def test_fallback_in_progress_and_done() -> None:
    running = live.phase_steps(_status("fallback", 2, ["ATC", "PILOT", "GROUND"], ["ATC", "PILOT", "GROUND"]))
    assert running[-1]["label"] == "Fallback"
    assert running[-1]["state"] == "active"
    assert running[2]["state"] == "done"
    assert running[3]["state"] == "skipped"
    done = live.phase_steps(
        _status("done", 2, ["ATC", "PILOT", "GROUND"], ["ATC"], done=True, outcome="fallback"), option_id="O2"
    )
    assert done[-1]["value"] == "Chose O2"
    assert done[3]["value"] == "Not reached"


def test_escalated_is_stopped() -> None:
    steps = live.phase_steps(_status("done", 0, done=True, outcome="escalated"))
    assert steps[-1]["state"] == "stopped"
    assert steps[1]["state"] == "skipped"


def test_ai_off_skips_agent_turns() -> None:
    steps = live.phase_steps(_status("setup"), ai_off=True)
    assert steps[0]["value"] == "Running code checks"
    assert _states(steps)[1:4] == ["skipped", "skipped", "skipped"]
    assert {s["value"] for s in steps[1:4]} == {"Agents not called"}


def test_status_line_waiting_variants() -> None:
    assert live.status_line(_status(), impl="stub") == ("Setup · building the agents", "active")
    assert "one model call" in live.status_line(_status(), impl="llm")[0]
    assert live.status_line(_status(), ai_off=True)[0] == "Setup · loading the flight data"


def test_status_line_turn1_progress() -> None:
    assert (
        live.status_line(_status("turn1", 1))[0]
        == "Turn 1 · waiting for proposals from ATC, Pilot and Ground"
    )
    assert (
        live.status_line(_status("turn1", 1, ["ATC"]))[0]
        == "Turn 1 · waiting for proposals from Pilot and Ground (1 of 3 received)"
    )
    assert (
        live.status_line(_status("turn1", 1, ["ATC", "PILOT"]))[0]
        == "Turn 1 · waiting for Ground's proposal (2 of 3 received)"
    )
    assert live.status_line(_status("turn1", 1, ["ATC", "PILOT", "GROUND"]))[0].startswith(
        "Turn 1 · all 3 proposals in."
    )


def test_status_line_ballots_and_turn3() -> None:
    line = live.status_line(_status("turn2", 2, ["ATC", "PILOT", "GROUND"], ["ATC", "GROUND"]))[0]
    assert line == "Turn 2 · waiting for Pilot's ballot (2 of 3 received)"
    line = live.status_line(_status("turn3", 3, ["ATC", "PILOT", "GROUND"], []))[0]
    assert line == "Turn 3 · final ballot · waiting for ballots from ATC, Pilot and Ground"


def test_status_line_terminal_states() -> None:
    assert live.status_line(_status("commit", 2))[0].startswith("Commit ·")
    assert live.status_line(_status("fallback", 2))[0].startswith("Fallback · no option")
    assert live.status_line(_status("fallback"), ai_off=True)[0].startswith("Fallback · AI is off")
    text, tone = live.status_line(_status("done", 2, done=True, outcome="committed"), option_id="O1")
    assert text == "Committed O1 at Turn 2. Saving the run files."
    assert tone == "done"
    text, tone = live.status_line(_status("done", 0, done=True, outcome="escalated"))
    assert tone == "stopped"


def test_messages_by_turn_and_shortlist() -> None:
    entries = [
        {"event": "BALLOT", "turn": 2, "actor": "ATC", "payload": {"sender": "ATC", "v": 1}},
        {"event": "SHORTLIST", "turn": 1, "payload": {"for_turn": 2, "option_ids": ["O1", "O2"]}},
        {"event": "BALLOT", "turn": 2, "actor": "PILOT", "payload": {"sender": "PILOT"}},
        {"event": "SHORTLIST", "turn": 2, "payload": {"for_turn": 3, "option_ids": ["O1"]}},
        {"event": "BALLOT", "turn": 3, "actor": "ATC", "payload": {"sender": "ATC", "v": 3}},
        {"event": "PROPOSAL", "turn": 1, "actor": "GROUND", "payload": None},
    ]
    by_turn = live.messages_by_turn(entries, "BALLOT")
    assert set(by_turn[2]) == {"ATC", "PILOT"}
    assert by_turn[3]["ATC"]["v"] == 3
    assert live.messages_by_turn(entries, "PROPOSAL") == {1: {"GROUND": {}}}
    assert live.shortlist_payload_for(entries, 2)["option_ids"] == ["O1", "O2"]
    assert live.shortlist_payload_for(entries, 3)["option_ids"] == ["O1"]
    assert live.shortlist_payload_for([], 2) == {}


def test_html_builders_and_safe_html() -> None:
    strip = live.strip_html(live.phase_steps(_status("turn1", 1, ["ATC"])))
    assert strip.count('class="td-flow-step') == 5
    assert "td-live-dot" in strip
    card = live.pending_card_html("PILOT", 2, started=True)
    assert "Waiting for Pilot&#x27;s ballot" in card
    assert card.count("<div") == card.count("</div>")
    assert "Elapsed 1:05 min" in live.status_html("x", "active", 65.4)

    def boom(*_args: Any) -> str:
        raise KeyError("ranking")

    held = live.safe_html("proposal_card_html(ATC)", boom, object(), "ATC")
    assert "Still negotiating" in held
    assert "proposal_card_html(ATC) failed" in held
    assert "KeyError" in held
    assert live.safe_html("ok", lambda: "<b>fine</b>") == "<b>fine</b>"
