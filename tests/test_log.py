from __future__ import annotations

import json

import pytest

from triad.log.consensus_log import ZERO_CHAIN, ConsensusLog
from triad.log.manifest import build_manifest, read_manifest, write_manifest, write_resolution
from triad.schemas import Mode, Resolution


def test_hash_chain_and_frozen_clock(tmp_path):
    log = ConsensusLog("RUN-1", tmp_path / "run", clock=lambda: "2026-01-01T00:00:00Z")
    first = log.append(0, "ORCHESTRATOR", "SETUP", {"a": 1})
    second = log.append(1, "ATC", "PROPOSAL", {"b": [1, 2, 3]})

    assert first.seq == 1 and first.prev_sha256 == ZERO_CHAIN
    assert second.seq == 2 and second.prev_sha256 != ZERO_CHAIN
    assert first.ts == "2026-01-01T00:00:00Z"
    assert ConsensusLog.verify(log.entries)
    assert ConsensusLog.verify(tmp_path / "run" / "log.jsonl")

    lines = (tmp_path / "run" / "log.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["event"] == "PROPOSAL"


def test_hash_chain_detects_payload_tampering():
    log = ConsensusLog("RUN-1")
    log.append(0, "ORCHESTRATOR", "SETUP", {"a": 1})
    log.append(1, "ATC", "PROPOSAL", {"b": 2})
    assert ConsensusLog.verify(log.entries)

    tampered = list(log.entries)
    tampered[0] = tampered[0].model_copy(update={"payload": {"a": 999}})
    assert not ConsensusLog.verify(tampered)


def test_hash_chain_detects_chain_tampering():
    log = ConsensusLog("RUN-1")
    log.append(0, "ORCHESTRATOR", "SETUP", {"a": 1})
    log.append(1, "ATC", "PROPOSAL", {"b": 2})

    tampered = list(log.entries)
    tampered[1] = tampered[1].model_copy(update={"prev_sha256": ZERO_CHAIN})
    assert not ConsensusLog.verify(tampered)


def test_manifest_and_resolution_written(tmp_path):
    manifest = build_manifest(
        run_id="RUN-1",
        dataset_row=0,
        seed=0,
        mode=Mode.AIRBORNE,
        agent_impl={"ATC": "stub", "PILOT": "stub", "GROUND": "stub"},
        created="2026-01-01T00:00:00Z",
    )
    path = write_manifest(manifest, tmp_path)
    assert path.exists()
    assert read_manifest(tmp_path).run_id == "RUN-1"
    assert manifest.config_sha256 and manifest.code_version

    resolution = Resolution(
        run_id="RUN-1",
        status="FALLBACK",
        turn=2,
        decided_by="FALLBACK",
        option=None,
        reason="NO_UNANIMOUS_APPROVAL",
    )
    res_path = write_resolution(resolution, tmp_path)
    assert res_path.exists()
    assert json.loads(res_path.read_text())["status"] == "FALLBACK"


def test_resume_appends_human_decision_and_chain_still_verifies(tmp_path):
    import sys
    from pathlib import Path as _P

    sys.path.insert(0, str(_P(__file__).resolve().parents[1] / "app"))
    from components.transcript import build_transcript, load_entries

    log = ConsensusLog("run-x", tmp_path)
    log.append(0, "ORCHESTRATOR", "SETUP", {"a": 1})
    log.append(2, "ORCHESTRATOR", "COMMIT", {"option_id": "OPT-1", "status": "CONSENSUS"})

    resumed = ConsensusLog.resume(tmp_path)
    entry = resumed.append(2, "HUMAN", "HUMAN_DECISION", {
        "decision": "approve", "reason": "ok", "user": "duty_manager",
        "timestamp": "2026-10-31T10:00:00Z", "option_id": "OPT-1",
    })
    assert entry.seq == 3
    assert ConsensusLog.verify(tmp_path / "log.jsonl")
    msgs = build_transcript(load_entries(tmp_path / "log.jsonl"))
    assert msgs[-1]["speaker"] == "Duty manager" and "Approved OPT-1" in msgs[-1]["text"]


def test_resume_refuses_tampered_log(tmp_path):
    log = ConsensusLog("run-y", tmp_path)
    log.append(0, "ORCHESTRATOR", "SETUP", {"a": 1})
    path = tmp_path / "log.jsonl"
    path.write_text(path.read_text().replace('"a":1', '"a":2'))
    with pytest.raises(ValueError):
        ConsensusLog.resume(tmp_path)
