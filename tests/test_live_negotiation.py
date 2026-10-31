"""Live negotiation playback helpers (app/components/data.py). No network, no LLM."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.components import data


def _entry(seq: int, turn: int, actor: str, event: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "seq": seq,
        "ts": "2026-10-31T00:00:00Z",
        "run_id": "RUN",
        "turn": turn,
        "actor": actor,
        "event": event,
        "payload": payload or {},
        "payload_sha256": "0" * 64,
        "prev_sha256": "0" * 64,
    }


SETUP = [
    (0, "ORCHESTRATOR", "SETUP", {"run_id": "RUN", "mode": "AIRBORNE", "flags": {"ai_off": False}}),
    (0, "ORCHESTRATOR", "SHARED_CHECKS", {"option_id": "O1", "passed": True, "checks": []}),
    (0, "ORCHESTRATOR", "OPTIONS_GENERATED", {"option_ids": ["O1", "O2"], "shared_passed": ["O1", "O2"], "options": []}),
]
TURN1 = [
    (1, "ORCHESTRATOR", "TURN_START", {"turn": 1, "kind": "PROPOSE", "shortlist": ["O1", "O2"]}),
    (1, "ATC", "PERCEPTION", {"role": "ATC"}),
    (1, "ATC", "PROPOSAL", {"sender": "ATC", "ranking": ["O1", "O2"]}),
    (1, "PILOT", "PROPOSAL", {"sender": "PILOT", "ranking": ["O2", "O1"]}),
]
TURN1_REST = [
    (1, "GROUND", "PROPOSAL", {"sender": "GROUND", "ranking": ["O1"]}),
    (1, "ORCHESTRATOR", "SHORTLIST", {"for_turn": 2, "option_ids": ["O1", "O2"]}),
]
TURN2 = [
    (2, "ORCHESTRATOR", "TURN_START", {"turn": 2, "kind": "BALLOT", "shortlist": ["O1", "O2"]}),
    (2, "ATC", "BALLOT", {"sender": "ATC", "votes": []}),
    (2, "GROUND", "BALLOT", {"sender": "GROUND", "votes": []}),
]
COMMIT = [
    (2, "PILOT", "BALLOT", {"sender": "PILOT", "votes": []}),
    (2, "ORCHESTRATOR", "COMMIT_GATE", {"option_id": "O1", "passed": True}),
    (2, "ORCHESTRATOR", "COMMIT", {"option_id": "O1", "status": "CONSENSUS", "turn": 2}),
]
FALLBACK = [
    (2, "PILOT", "BALLOT", {"sender": "PILOT", "votes": []}),
    (2, "FALLBACK", "FALLBACK_INVOKED", {"reason_code": "NO_UNANIMOUS_APPROVAL", "chosen": "O2"}),
    (2, "ORCHESTRATOR", "COMMIT_GATE", {"option_id": "O2", "passed": True}),
    (2, "ORCHESTRATOR", "COMMIT", {"option_id": "O2", "status": "FALLBACK", "turn": 2}),
]


def _write_log(folder: Path, rows: list[tuple[int, str, str, dict[str, Any]]], tail: str = "") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(_entry(i + 1, *row)) + "\n" for i, row in enumerate(rows)]
    (folder / "log.jsonl").write_text("".join(lines) + tail, encoding="utf-8")
    return folder


def test_missing_and_empty_log_is_waiting(tmp_path: Path) -> None:
    assert data.live_status(tmp_path / "nope")["phase"] == "waiting"
    folder = _write_log(tmp_path / "run", [])
    status = data.live_status(folder)
    assert status["phase"] == "waiting"
    assert status["entries"] == 0
    assert status["done"] is False
    assert status["outcome"] is None


def test_setup_only(tmp_path: Path) -> None:
    status = data.live_status(_write_log(tmp_path / "run", SETUP))
    assert status["phase"] == "setup"
    assert status["turn"] == 0
    assert status["entries"] == 3
    assert status["proposals_received"] == []


def test_turn1_partial_proposals(tmp_path: Path) -> None:
    status = data.live_status(_write_log(tmp_path / "run", SETUP + TURN1))
    assert status["phase"] == "turn1"
    assert status["turn"] == 1
    assert status["proposals_received"] == ["ATC", "PILOT"]
    assert status["ballots_received"] == []
    assert status["done"] is False


def test_turn2_partial_ballots(tmp_path: Path) -> None:
    status = data.live_status(_write_log(tmp_path / "run", SETUP + TURN1 + TURN1_REST + TURN2))
    assert status["phase"] == "turn2"
    assert status["turn"] == 2
    assert status["proposals_received"] == ["ATC", "PILOT", "GROUND"]
    assert status["ballots_received"] == ["ATC", "GROUND"]
    assert status["done"] is False
    assert status["outcome"] is None


def test_commit_is_done_committed(tmp_path: Path) -> None:
    status = data.live_status(_write_log(tmp_path / "run", SETUP + TURN1 + TURN1_REST + TURN2 + COMMIT))
    assert status["phase"] == "done"
    assert status["done"] is True
    assert status["outcome"] == "committed"
    assert status["ballots_received"] == ["ATC", "GROUND", "PILOT"]


def test_fallback_is_done_fallback(tmp_path: Path) -> None:
    rows = SETUP + TURN1 + TURN1_REST + TURN2 + FALLBACK
    assert data.live_status(_write_log(tmp_path / "a", rows[:-2]))["phase"] == "fallback"
    assert data.live_status(_write_log(tmp_path / "a", rows[:-2]))["done"] is False
    status = data.live_status(_write_log(tmp_path / "b", rows))
    assert status["done"] is True
    assert status["outcome"] == "fallback"


def test_truncated_last_line_is_ignored(tmp_path: Path) -> None:
    folder = _write_log(tmp_path / "run", SETUP + TURN1, tail='{"seq": 99, "event": "PROPOS')
    status = data.live_status(folder)
    assert status["entries"] == len(SETUP + TURN1)
    assert status["proposals_received"] == ["ATC", "PILOT"]
    run = data.load_run(folder, live=True)
    assert len(run.raw_entries) == len(SETUP + TURN1)


def test_stale_log_before_since_is_waiting(tmp_path: Path) -> None:
    folder = _write_log(tmp_path / "run", SETUP + TURN1 + TURN1_REST + TURN2 + COMMIT)
    old = time.time() - 60
    os.utime(folder / "log.jsonl", (old, old))
    assert data.live_status(folder, since=time.time())["phase"] == "waiting"
    assert data.live_status(folder, since=old - 1)["done"] is True


def test_load_run_on_log_only_folder(tmp_path: Path) -> None:
    folder = _write_log(tmp_path / "run", SETUP + TURN1)
    run = data.load_run(folder)
    assert run.status == "UNKNOWN"
    assert run.turn == 0
    assert run.committed_option is None
    assert set(run.proposals) == {"ATC", "PILOT"}


def test_load_run_live_ignores_stale_resolution(tmp_path: Path) -> None:
    folder = _write_log(tmp_path / "run", SETUP)
    (folder / "resolution.json").write_text(json.dumps({"status": "CONSENSUS", "turn": 1}), encoding="utf-8")
    assert data.load_run(folder).status == "CONSENSUS"
    assert data.load_run(folder, live=True).status == "UNKNOWN"


@pytest.mark.parametrize(
    ("ai_off", "red_team", "impl", "defect_tag"),
    [(False, False, "stub", None), (False, True, "llm", "Hydraulic Leak"), (True, False, "stub", None)],
)
def test_live_path_matches_run_negotiation_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ai_off: bool, red_team: bool, impl: str, defect_tag: str | None
) -> None:
    import triad.data.loader as loader
    import triad.data.scenario as scenario
    import triad.runner as runner

    captured: dict[str, Path] = {}

    class _Stop(RuntimeError):
        pass

    def fake_run_scenario(
        row_index: int,
        *,
        seed: int = 0,
        defect_id: str | None = None,
        ai_off: bool = False,
        red_team: bool = False,
        run_dir: Path | None = None,
        impl: str = "stub",
        use_cache: bool = True,
    ) -> Any:
        assert run_dir is not None
        captured["run_dir"] = run_dir
        raise _Stop("stop after capture")

    monkeypatch.setattr(data, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(loader, "get_record", lambda row: SimpleNamespace(run_id="2026-01-01-XX1-r7"))
    monkeypatch.setattr(scenario, "is_candidate", lambda record: True)
    monkeypatch.setattr(runner, "run_scenario", fake_run_scenario)

    expected = data._primary_run_dir(7, ai_off, red_team, impl, defect_tag)
    live = data.start_live_negotiation(
        row_index=7, seed=0, defect_id=None, ai_off=ai_off, red_team=red_team,
        impl=impl, use_cache=True, defect_tag=defect_tag,
    )
    assert live.thread is not None
    live.thread.join(timeout=10)
    assert not live.is_alive()
    assert live.path == expected
    assert captured["run_dir"] == expected
    assert live.error == "stop after capture"
    assert live.result_path is None
    assert expected.parent == tmp_path
    assert expected.name.startswith("2026-01-01-XX1-r7")
