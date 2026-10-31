"""Config + path helpers (shared, frozen)."""

from __future__ import annotations

import hashlib
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATASETS_DIR = ROOT / "datasets"
RUNS_DIR = ROOT / "runs"
CACHE_DIR = ROOT / ".cache"


@lru_cache(maxsize=None)
def load_yaml(name: str) -> dict[str, Any]:
    """load_yaml("synthetic") -> config/synthetic.yaml ; load_yaml("agents/pilot")."""
    with open(CONFIG_DIR / f"{name}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def config_sha256() -> str:
    h = hashlib.sha256()
    for p in sorted(CONFIG_DIR.rglob("*.yaml")):
        if p.name == "demo_scenarios.yaml":
            continue
        h.update(p.relative_to(CONFIG_DIR).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def code_version() -> str:
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "src", "config"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        return sha + ("-dirty" if dirty else "")
    except Exception:
        return "unknown"
