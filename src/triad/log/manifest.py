"""Run record (manifest) helpers."""

from __future__ import annotations

import json
from pathlib import Path

from triad.config import code_version, config_sha256
from triad.log.consensus_log import utc_now_iso
from triad.schemas import Mode, Resolution, RunManifest


def build_manifest(
    run_id: str,
    dataset_row: int,
    seed: int,
    mode: Mode,
    agent_impl: dict[str, str],
    prompt_hashes: dict[str, str] | None = None,
    created: str | None = None,
) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        dataset_row=dataset_row,
        seed=seed,
        mode=mode,
        agent_impl=agent_impl,
        prompt_hashes=prompt_hashes or {},
        config_sha256=config_sha256(),
        code_version=code_version(),
        created=created or utc_now_iso(),
    )


def write_manifest(manifest: RunManifest, run_dir: Path | str) -> Path:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "manifest.json"
    path.write_text(json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True), encoding="utf-8")
    return path


def read_manifest(run_dir: Path | str) -> RunManifest:
    return RunManifest.model_validate_json((Path(run_dir) / "manifest.json").read_text(encoding="utf-8"))


def write_resolution(resolution: Resolution, run_dir: Path | str, name: str = "resolution.json") -> Path:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / name
    path.write_text(json.dumps(resolution.model_dump(mode="json"), indent=2, sort_keys=True), encoding="utf-8")
    return path
