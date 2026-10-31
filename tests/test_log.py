from __future__ import annotations

import json

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
