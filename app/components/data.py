"""Read-only data helpers for the Triad Streamlit desk.

Everything the screen shows is derived from a saved run:

    runs/<run_id>/log.jsonl
    runs/<run_id>/resolution.json
    runs/<run_id>/manifest.json

The flight header is the one exception: the current log's SETUP event carries
the clock but not the route.  We rebuild the deterministic public event from the
manifest's ``dataset_row`` + ``seed`` so replay stays faithful.  If the scenario
builder is unavailable, the view degrades to the log-only fields.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = ROOT / "runs"
CONFIG_DIR = ROOT / "config"

ROLES = ("ATC", "PILOT", "GROUND")
ROLE_LABELS = {
    "ATC": "Air traffic control",
    "PILOT": "Flight crew",
    "GROUND": "Ground operations",
}
ROLE_SHORT = {"ATC": "ATC", "PILOT": "PILOT", "GROUND": "GROUND"}

EVENT_ORDER = (
    "SETUP",
    "OPTIONS_GENERATED",
    "SHARED_CHECKS",
    "PROPOSAL",
    "COUNTER_VALIDATED",
    "COUNTER_REJECTED",
    "SHORTLIST",
    "BALLOT",
    "SAFETY_BLOCK",
    "AGENT_FAILOVER",
    "CONSENSUS_REACHED",
    "FALLBACK_INVOKED",
    "COMMIT",
    "ESCALATED",
)

STATE_LABELS = {
    "committed": "Committed",
    "shortlisted": "Shortlisted",
    "feasible": "Feasible",
    "vetoed": "Vetoed",
    "rejected": "Counter rejected",
}


# --------------------------------------------------------------------------- small utilities


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def _chain_verify_fallback(path: Path) -> bool:
    prev = "0" * 64
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                entry = json.loads(line)
                payload_sha = hashlib.sha256(_canonical(entry["payload"]).encode()).hexdigest()
                if entry["prev_sha256"] != prev or entry["payload_sha256"] != payload_sha:
                    return False
                prev = hashlib.sha256(f"{prev}{payload_sha}".encode()).hexdigest()
        return True
    except Exception:
        return False


def verify_chain(path: Path) -> bool:
    try:
        from triad.log.consensus_log import ConsensusLog

        return bool(ConsensusLog.verify(path))
    except Exception:
        return _chain_verify_fallback(path)


def log_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return ""


@lru_cache(maxsize=1)
def demo_scenarios() -> dict[str, dict[str, Any]]:
    data = _read_yaml(CONFIG_DIR / "demo_scenarios.yaml")
    raw = data.get("scenarios", data)
    scenarios: dict[str, dict[str, Any]] = {}
    if isinstance(raw, dict):
        for name, item in raw.items():
            if isinstance(item, dict):
                scenarios[str(name)] = item
    elif isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("id")
            if name:
                scenarios[str(name)] = item
    return scenarios


def scenario_for_row(row: int | None) -> tuple[str, dict[str, Any]] | None:
    if row is None:
        return None
    for name, item in demo_scenarios().items():
        try:
            if item.get("row") is not None and int(item["row"]) == int(row):
                return name, item
        except Exception:
            continue
    return None


@lru_cache(maxsize=1)
def defect_library() -> dict[str, dict[str, Any]]:
    data = _read_yaml(CONFIG_DIR / "defects.yaml")
    items = data.get("defects", {})
    return {str(k): v for k, v in items.items() if isinstance(v, dict)} if isinstance(items, dict) else {}


def defect_options() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for defect_id, item in sorted(defect_library().items()):
        text = str(item.get("text", "")).strip()
        out.append((defect_id, f"{defect_id} · {text[:54]}{'…' if len(text) > 54 else ''}"))
    return out


@lru_cache(maxsize=64)
def _record_dict(row: int) -> dict[str, Any] | None:
    try:
        from triad.data.loader import get_record

        record = get_record(int(row))
        return record.model_dump(mode="json") if hasattr(record, "model_dump") else dict(record)
    except Exception:
        return None


@lru_cache(maxsize=64)
def _public_event(row: int, seed: int) -> dict[str, Any] | None:
    try:
        from triad.data.enrich import build_event
        from triad.data.loader import get_record

        record = get_record(int(row))
        match = scenario_for_row(int(row))
        defect = match[1].get("defect") if match else None
        event = build_event(record, seed=int(seed), defect_id=defect)
        return event.public.model_dump(mode="json")
    except Exception:
        return None


# --------------------------------------------------------------------------- run model


@dataclass
class RunData:
    run_dir: Path
    raw_entries: list[dict[str, Any]] = field(default_factory=list)
    resolution: dict[str, Any] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)

    setup: dict[str, Any] = field(default_factory=dict)
    options: list[dict[str, Any]] = field(default_factory=list)
    generated_ids: list[str] = field(default_factory=list)
    shared_passed: list[str] = field(default_factory=list)
    shared_checks: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    proposals: dict[str, dict[str, Any]] = field(default_factory=dict)
    ballots: dict[str, dict[str, Any]] = field(default_factory=dict)
    shortlist: list[str] = field(default_factory=list)
    shortlist_payload: dict[str, Any] = field(default_factory=dict)
    counters: list[dict[str, Any]] = field(default_factory=list)
    counter_errors: list[dict[str, Any]] = field(default_factory=list)
    rejected_counter_ids: set[str] = field(default_factory=set)
    validated_counter_ids: set[str] = field(default_factory=set)
    safety_blocks: list[dict[str, Any]] = field(default_factory=list)
    failovers: list[dict[str, Any]] = field(default_factory=list)
    fallback: dict[str, Any] | None = None
    commit: dict[str, Any] | None = None
    context_manifests: dict[str, str] = field(default_factory=dict)
    chain_ok: bool = False
    log_sha: str = ""
    public: dict[str, Any] | None = None
    record: dict[str, Any] | None = None
    checks_by_option: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    checks_by_role_option: dict[tuple[str, str], list[dict[str, Any]]] = field(default_factory=dict)

    # ------------------------------------------------------------------ basics
    @property
    def run_id(self) -> str:
        return str(
            self.manifest.get("run_id")
            or self.resolution.get("run_id")
            or self.setup.get("run_id")
            or self.run_dir.name
        )

    @property
    def mode(self) -> str:
        return str(self.setup.get("mode") or self.manifest.get("mode") or "")

    @property
    def status(self) -> str:
        return str(self.resolution.get("status") or "UNKNOWN")

    @property
    def turn(self) -> int:
        try:
            return int(self.resolution.get("turn") or 0)
        except Exception:
            return 0

    @property
    def decided_by(self) -> str:
        return str(self.resolution.get("decided_by") or "")

    @property
    def reason(self) -> str:
        return str(self.resolution.get("reason") or "")

    @property
    def committed_option(self) -> dict[str, Any] | None:
        option = self.resolution.get("option")
        return option if isinstance(option, dict) else None

    @property
    def committed_id(self) -> str | None:
        option = self.committed_option
        return str(option.get("option_id")) if option and option.get("option_id") else None

    @property
    def flight(self) -> dict[str, Any]:
        if self.public and isinstance(self.public.get("flight"), dict):
            return self.public["flight"]
        return self.record or {}

    @property
    def aircraft(self) -> dict[str, Any]:
        return self.public.get("aircraft", {}) if self.public else {}

    @property
    def synthetic_fields(self) -> list[str]:
        return list(self.public.get("synthetic_fields", [])) if self.public else []

    @property
    def disruption_summary(self) -> str:
        if self.public and self.public.get("disruption_summary"):
            return str(self.public["disruption_summary"])
        flight = self.flight
        if self.mode == "AIRBORNE":
            return f"Weather delay of {flight.get('weather_delay', 0)} min on arrival."
        return f"Late aircraft delay of {flight.get('late_aircraft_delay', 0)} min at departure."

    @property
    def decision_time(self) -> int | None:
        value = self.setup.get("decision_time")
        return int(value) if value is not None else None

    @property
    def expected_eta(self) -> int | None:
        value = self.setup.get("expected_eta")
        return int(value) if value is not None else None

    @property
    def original_eta(self) -> int | None:
        if self.setup.get("original_eta") is not None:
            return int(self.setup["original_eta"])
        value = self.flight.get("scheduled_arrival")
        return int(value) if value is not None else None

    @property
    def scenario(self) -> tuple[str, dict[str, Any]] | None:
        try:
            row = self.manifest.get("dataset_row")
            return scenario_for_row(int(row)) if row is not None else None
        except Exception:
            return None

    @property
    def scenario_name(self) -> str | None:
        return self.scenario[0] if self.scenario else None

    @property
    def flags(self) -> list[str]:
        name = self.run_dir.name.lower()
        flags: list[str] = []
        if "-redteam" in name or "redteam" in name:
            flags.append("Red-team")
        if "-aioff" in name or "aioff" in name:
            flags.append("AI off")
        return flags

    @property
    def impl_label(self) -> str:
        impls = list(dict.fromkeys(str(v) for v in self.manifest.get("agent_impl", {}).values()))
        if not impls:
            return "unknown"
        if len(impls) == 1:
            value = impls[0]
            if value == "stub":
                return "Stub agents"
            if value.startswith("llm:"):
                return f"LLM · {value.split(':', 1)[1]}"
            return value
        return " / ".join(impls)

    @property
    def flight_label(self) -> str:
        flight = self.flight
        airline = flight.get("airline", "")
        number = flight.get("flight_number", "")
        if airline or number:
            return f"{airline}{number}"
        return self.run_id

    @property
    def route_label(self) -> str:
        flight = self.flight
        return f"{flight.get('origin', '???')} → {flight.get('destination', '???')}"

    @property
    def date_label(self) -> str:
        flight = self.flight
        try:
            from datetime import date

            return date(int(flight["year"]), int(flight["month"]), int(flight["day"])).strftime(
                "%d %b %Y"
            )
        except Exception:
            return ""

    # ------------------------------------------------------------------ option views
    @property
    def option_by_id(self) -> dict[str, dict[str, Any]]:
        return {str(o.get("option_id")): o for o in self.all_options if o.get("option_id")}

    @property
    def all_options(self) -> list[dict[str, Any]]:
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for option in self.options:
            oid = str(option.get("option_id"))
            if oid and oid not in seen:
                seen.add(oid)
                out.append(option)
        for counter in self.counters:
            option = counter.get("option")
            if isinstance(option, dict):
                oid = str(option.get("option_id"))
                if oid and oid not in seen:
                    seen.add(oid)
                    out.append(option)
        return out

    @property
    def shortlist_ids(self) -> set[str]:
        return set(self.shortlist)

    @property
    def safe_pool(self) -> list[str]:
        payload = self.fallback or {}
        return [str(value) for value in (payload.get("pool") or [])]

    @property
    def first_choices(self) -> dict[str, str | None]:
        return {
            role: (payload.get("ranking") or [None])[0]
            for role, payload in self.proposals.items()
        }

    def code_failures(self, option_id: str) -> list[dict[str, Any]]:
        failures: list[dict[str, Any]] = []
        seen: set[str] = set()
        for check in self.checks_by_option.get(option_id, []):
            if not check.get("hard", True) or check.get("passed", True):
                continue
            key = str(check.get("check_id") or f"{check.get('constraint_id')}:{check.get('option_id')}")
            if key in seen:
                continue
            seen.add(key)
            failures.append(check)
        return failures

    def state(self, option_id: str) -> str:
        if option_id == self.committed_id:
            return "committed"
        if "AI off" in self.flags and self.safe_pool:
            return "feasible" if option_id in self.safe_pool else "vetoed"
        if option_id in self.rejected_counter_ids:
            return "rejected"
        if option_id in self.shortlist_ids:
            return "shortlisted"
        if self.code_failures(option_id):
            return "vetoed"
        return "feasible"

    def state_label(self, option_id: str) -> str:
        return STATE_LABELS.get(self.state(option_id), self.state(option_id).title())

    @property
    def feasible_count(self) -> int:
        return sum(1 for o in self.all_options if self.state(str(o.get("option_id"))) == "feasible")

    @property
    def vetoed_count(self) -> int:
        return sum(1 for o in self.options if self.code_failures(str(o.get("option_id"))))

    def option_context(self, option_id: str) -> dict[str, Any]:
        option = self.option_by_id.get(option_id, {})
        changes = []
        if option.get("departure_slot") is not None:
            changes.append(("departure", option.get("departure_slot")))
        if option.get("arrival_slot") is not None:
            changes.append(("arrival", option.get("arrival_slot")))
        if option.get("holding_min"):
            changes.append(("holding", option.get("holding_min")))
        if option.get("enroute_absorb_min"):
            changes.append(("en route", option.get("enroute_absorb_min")))
        if option.get("speed_recovery_min"):
            changes.append(("recovery", option.get("speed_recovery_min")))
        if option.get("cruise_level"):
            changes.append(("FL", option.get("cruise_level")))
        if option.get("gate"):
            changes.append(("gate", option.get("gate")))
        if option.get("next_leg_action") and option.get("next_leg_action") != "KEEP":
            changes.append(("next leg", option.get("next_leg_action")))
        return {"option": option, "changes": changes}

    # ------------------------------------------------------------------ checks / costs
    @property
    def final_checks(self) -> list[dict[str, Any]]:
        checks = self.resolution.get("checks") or []
        return [c for c in checks if isinstance(c, dict)]

    @property
    def commit_safe(self) -> bool:
        if self.status == "ESCALATED":
            return False
        checks = self.final_checks
        return bool(checks) and all(c.get("passed", True) for c in checks if c.get("hard", True))

    @property
    def commit_failures(self) -> list[dict[str, Any]]:
        return [c for c in self.final_checks if not c.get("passed", True)]

    @property
    def costs(self) -> dict[str, float]:
        raw = self.resolution.get("costs_eur") or {}
        out: dict[str, float] = {}
        for role in ROLES:
            try:
                out[role] = float(raw.get(role, 0.0))
            except Exception:
                out[role] = 0.0
        return out

    @property
    def total_cost(self) -> float:
        return sum(self.costs.values())

    @property
    def context_turns(self) -> list[int]:
        turns: set[int] = set()
        for key in self.context_manifests:
            try:
                turns.add(int(key.split(":", 1)[0]))
            except Exception:
                continue
        return sorted(turns)

    def context_hash(self, turn: int, role: str) -> str | None:
        return self.context_manifests.get(f"{turn}:{role}")

    @property
    def usage_rows(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for entry in self.raw_entries:
            usage = entry.get("usage")
            if not isinstance(usage, dict):
                continue
            for role, data in usage.items():
                if not isinstance(data, dict):
                    continue
                rows.append(
                    {
                        "seq": entry.get("seq"),
                        "turn": entry.get("turn"),
                        "role": role,
                        **data,
                    }
                )
        return rows

    @property
    def integration_entries(self) -> list[dict[str, Any]]:
        return [e for e in self.raw_entries if e.get("event") in ("PROPOSAL", "BALLOT")]

    def event(self, name: str) -> list[dict[str, Any]]:
        return [e for e in self.raw_entries if e.get("event") == name]


# --------------------------------------------------------------------------- loading


def _collect_checks(run: RunData) -> None:
    run.checks_by_option = {}
    run.checks_by_role_option = {}

    def add(option_id: str, checks: list[dict[str, Any]], role: str | None = None) -> None:
        if not option_id:
            return
        run.checks_by_option.setdefault(option_id, []).extend(c for c in checks if isinstance(c, dict))
        if role:
            run.checks_by_role_option.setdefault((role, option_id), []).extend(
                c for c in checks if isinstance(c, dict)
            )

    for option_id, checks in run.shared_checks.items():
        add(option_id, checks)

    for role, proposal in run.proposals.items():
        checks = proposal.get("checks") or []
        by_option: dict[str, list[dict[str, Any]]] = {}
        for check in checks:
            if isinstance(check, dict):
                by_option.setdefault(str(check.get("option_id")), []).append(check)
        for option_id, items in by_option.items():
            add(option_id, items, role)

    for entry in run.raw_entries:
        if entry.get("event") == "COUNTER_VALIDATED":
            payload = entry.get("payload") or {}
            add(str(payload.get("option_id")), payload.get("checks") or [])
        elif entry.get("event") == "COUNTER_REJECTED":
            payload = entry.get("payload") or {}
            add(str(payload.get("option_id")), payload.get("failing_checks") or [])

    if run.committed_id:
        add(run.committed_id, run.final_checks)


def _build_counters(run: RunData, by_option: dict[str, dict[str, Any]]) -> None:
    validated: dict[str, dict[str, Any]] = {}
    rejected: dict[str, dict[str, Any]] = {}
    for entry in run.raw_entries:
        payload = entry.get("payload") or {}
        oid = payload.get("option_id")
        if not oid:
            continue
        if entry.get("event") == "COUNTER_VALIDATED":
            validated[str(oid)] = payload
        elif entry.get("event") == "COUNTER_REJECTED":
            rejected[str(oid)] = payload

    for role, proposal in run.proposals.items():
        counter = proposal.get("counter_option")
        if not isinstance(counter, dict):
            continue
        base_id = str(counter.get("base_option_id") or "")
        base = by_option.get(base_id)
        if base is None:
            run.counter_errors.append(
                {"role": role, "option_id": None, "error": f"base option {base_id or '?'} is not in the log"}
            )
            continue
        changes = _as_dict(counter.get("changes"))
        option = dict(base)
        for key, value in changes.items():
            option[key] = value
        option_id = next(
            (oid for oid, payload in {**validated, **rejected}.items() if payload.get("role") == role),
            f"CTR-{role}-1",
        )
        option.update(
            {
                "option_id": option_id,
                "origin": "COUNTER",
                "proposed_by": role,
                "base_option_id": base_id,
            }
        )
        status = "validated" if option_id in validated else "rejected" if option_id in rejected else "proposed"
        run.counters.append(
            {
                "role": role,
                "option": option,
                "base_option_id": base_id,
                "changes": changes,
                "status": status,
                "event": validated.get(option_id) or rejected.get(option_id) or {},
            }
        )

    for entry in run.raw_entries:
        if entry.get("event") == "COUNTER_REJECTED":
            payload = entry.get("payload") or {}
            if not payload.get("option_id"):
                run.counter_errors.append(payload)

    run.validated_counter_ids = set(validated)
    run.rejected_counter_ids = set(rejected)


def _collect(srun: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = srun.get(key)
    return value if isinstance(value, list) else []


def load_run(run_dir: str | Path) -> RunData:
    path = Path(run_dir)
    entries: list[dict[str, Any]] = []
    try:
        with (path / "log.jsonl").open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    entries.append(json.loads(line))
    except Exception:
        entries = []

    resolution = _read_json(path / "resolution.json", {})
    manifest = _read_json(path / "manifest.json", {})
    if not isinstance(resolution, dict):
        resolution = {}
    if not isinstance(manifest, dict):
        manifest = {}

    setup: dict[str, Any] = {}
    options: list[dict[str, Any]] = []
    generated_ids: list[str] = []
    shared_passed: list[str] = []
    shared_checks: dict[str, list[dict[str, Any]]] = {}
    proposals: dict[str, dict[str, Any]] = {}
    ballots: dict[str, dict[str, Any]] = {}
    shortlist: list[str] = []
    shortlist_payload: dict[str, Any] = {}
    safety_blocks: list[dict[str, Any]] = []
    failovers: list[dict[str, Any]] = []
    fallback: dict[str, Any] | None = None
    commit: dict[str, Any] | None = None
    context_manifests: dict[str, str] = {}

    for entry in entries:
        event = entry.get("event")
        payload = _as_dict(entry.get("payload"))
        if event == "SETUP":
            setup = payload
        elif event == "OPTIONS_GENERATED":
            options = _collect(payload, "options")
            generated_ids = [str(v) for v in _collect(payload, "option_ids")]
            shared_passed = [str(v) for v in _collect(payload, "shared_passed")]
        elif event == "SHARED_CHECKS":
            oid = str(payload.get("option_id") or "")
            if oid:
                shared_checks.setdefault(oid, []).extend(_collect(payload, "checks"))
        elif event == "PROPOSAL":
            role = str(payload.get("sender") or entry.get("actor") or "")
            if role:
                proposals[role] = payload
        elif event == "BALLOT":
            role = str(payload.get("sender") or entry.get("actor") or "")
            if role:
                ballots[role] = payload
        elif event == "SHORTLIST":
            shortlist_payload = payload
            shortlist = [str(v) for v in _collect(payload, "option_ids")]
        elif event == "SAFETY_BLOCK":
            safety_blocks.append(entry)
        elif event == "AGENT_FAILOVER":
            failovers.append(entry)
        elif event == "FALLBACK_INVOKED":
            fallback = payload
        elif event == "COMMIT":
            commit = payload

        manifest_hashes = _as_dict(entry.get("context_manifest"))
        if manifest_hashes:
            for role, digest in manifest_hashes.items():
                context_manifests[f"{entry.get('turn', 0)}:{role}"] = str(digest)

    row = manifest.get("dataset_row")
    seed = manifest.get("seed", 0)
    public = _public_event(int(row), int(seed)) if row is not None else None
    record = _record_dict(int(row)) if row is not None else None

    run = RunData(
        run_dir=path,
        raw_entries=entries,
        resolution=resolution,
        manifest=manifest,
        setup=setup,
        options=options,
        generated_ids=generated_ids,
        shared_passed=shared_passed,
        shared_checks=shared_checks,
        proposals=proposals,
        ballots=ballots,
        shortlist=shortlist,
        shortlist_payload=shortlist_payload,
        safety_blocks=safety_blocks,
        failovers=failovers,
        fallback=fallback,
        commit=commit,
        context_manifests=context_manifests,
        public=public,
        record=record,
        chain_ok=verify_chain(path / "log.jsonl"),
        log_sha=log_sha256(path / "log.jsonl"),
    )

    _build_counters(run, {str(o.get("option_id")): o for o in options})
    _collect_checks(run)
    return run


# --------------------------------------------------------------------------- run listing


def available_runs() -> list[Path]:
    if not RUNS_DIR.exists():
        return []
    runs = [
        p
        for p in RUNS_DIR.iterdir()
        if p.is_dir() and (p / "log.jsonl").exists() and (p / "resolution.json").exists()
    ]
    return sorted(runs, key=lambda p: (p / "log.jsonl").stat().st_mtime, reverse=True)


def _peek(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        _read_json(path / "manifest.json", {}),
        _read_json(path / "resolution.json", {}),
    )


def run_label(path: Path) -> str:
    manifest, resolution = _peek(path)
    row = manifest.get("dataset_row")
    scenario = scenario_for_row(int(row)) if row is not None else None
    name = scenario[0] if scenario else (f"row {row}" if row is not None else path.name)
    match = re.match(r"^\d{4}-\d{2}-\d{2}-([A-Z0-9]+)-r\d+", path.name)
    flight = match.group(1) if match else ""
    status = str(resolution.get("status") or "?")
    turn = resolution.get("turn", "?")
    flags: list[str] = []
    lowered = path.name.lower()
    if "redteam" in lowered:
        flags.append("red-team")
    if "aioff" in lowered:
        flags.append("AI off")
    impl_values = " ".join(str(v).lower() for v in (manifest.get("agent_impl") or {}).values())
    if "llm" in impl_values or "-llm" in lowered:
        flags.append("LLM")
    parts = [name]
    if flight:
        parts.append(flight)
    parts.append(f"{status} T{turn}")
    if flags:
        parts.append(" / ".join(flags))
    return " · ".join(parts)


def recommended_run(paths: list[Path]) -> Path | None:
    if not paths:
        return None
    for path in paths:
        manifest, resolution = _peek(path)
        row = manifest.get("dataset_row")
        scenario = scenario_for_row(int(row)) if row is not None else None
        lowered = path.name.lower()
        if (
            scenario
            and scenario[0] == "scenario_a"
            and "redteam" not in lowered
            and "aioff" not in lowered
            and "-llm" not in lowered
            and resolution.get("status") == "CONSENSUS"
        ):
            return path
    for path in paths:
        lowered = path.name.lower()
        if "redteam" not in lowered and "aioff" not in lowered and "-llm" not in lowered:
            return path
    return paths[0]


# --------------------------------------------------------------------------- new runs


def scenario_choices() -> list[tuple[str, str]]:
    labels = {
        "scenario_a": "A · Weather, airborne",
        "scenario_b": "B · Late aircraft + defect",
        "scenario_c": "C · Fuel reserve / red-team",
    }
    return [(name, labels.get(name, name.replace("_", " ").title())) for name in demo_scenarios()]


def _suffix(*, ai_off: bool, red_team: bool, impl: str, defect_tag: str | None) -> str:
    suffix = ""
    if impl == "llm":
        suffix += "-llm"
    if red_team:
        suffix += "-redteam"
    if ai_off:
        suffix += "-aioff"
    if defect_tag:
        suffix += f"-defect-{re.sub(r'[^A-Za-z0-9]+', '-', defect_tag).strip('-').lower()}"
    return suffix


def run_negotiation(
    *,
    row_index: int,
    seed: int = 0,
    defect_id: str | None = None,
    ai_off: bool = False,
    red_team: bool = False,
    impl: str = "stub",
    use_cache: bool = True,
    defect_tag: str | None = None,
) -> tuple[Path, str | None]:
    """Run one negotiation through the normal runner and persist all three files."""

    from triad.data.loader import get_record
    from triad.data.scenario import is_candidate
    from triad.log.manifest import build_manifest, write_manifest, write_resolution
    from triad.runner import run_scenario
    from triad.schemas import Mode

    record = get_record(int(row_index))
    if not is_candidate(record):
        raise ValueError(
            f"Row {row_index} is not a demo candidate. It needs WEATHER_DELAY > 15 "
            "or LATE_AIRCRAFT_DELAY > 20."
        )

    signature = inspect.signature(run_scenario)
    accepted = set(signature.parameters)
    actual_impl = impl if "impl" in accepted else "stub"
    notice: str | None = None
    if impl != "stub" and "impl" not in accepted:
        notice = "This runner build does not expose the LLM implementation yet. Ran the stub agents instead."
    notices: list[str] = []

    def _execute(current_impl: str) -> tuple[Any, Any, Path, str]:
        suffix = _suffix(
            ai_off=ai_off, red_team=red_team, impl=current_impl, defect_tag=defect_tag
        )
        target = RUNS_DIR / f"{record.run_id}{suffix}"
        kwargs: dict[str, Any] = {
            "seed": int(seed),
            "defect_id": defect_id,
            "ai_off": bool(ai_off),
            "red_team": bool(red_team),
            "run_dir": target,
        }
        if "impl" in accepted:
            kwargs["impl"] = current_impl
        if "use_cache" in accepted:
            kwargs["use_cache"] = bool(use_cache)
        try:
            resolution, log = run_scenario(int(row_index), **kwargs)
        except NotImplementedError as exc:
            if current_impl == "stub":
                raise
            notices.append(f"LLM agents failed in this build ({exc}). Ran the stub agents instead.")
            suffix = _suffix(ai_off=ai_off, red_team=red_team, impl="stub", defect_tag=defect_tag)
            target = RUNS_DIR / f"{record.run_id}{suffix}"
            kwargs["run_dir"] = target
            if "impl" in accepted:
                kwargs["impl"] = "stub"
            resolution, log = run_scenario(int(row_index), **kwargs)
            return resolution, log, target, "stub"
        return resolution, log, target, current_impl

    resolution, log, run_dir, used_impl = _execute(actual_impl)
    if notices:
        notice = notices[-1]
    if getattr(log, "run_dir", None) is not None:
        run_dir = Path(log.run_dir)
    actual_impl = used_impl

    setup = {}
    try:
        setup = next((e.payload for e in log.entries if e.event == "SETUP"), {})
    except Exception:
        setup = {}
    mode_value = str(setup.get("mode") or "AIRBORNE")
    try:
        mode = Mode(mode_value)
    except Exception:
        mode = Mode.AIRBORNE

    role_impl = "stub"
    prompt_hashes: dict[str, str] = {}
    if actual_impl == "llm":
        try:
            from triad.agents.llm import prompt_hashes as _prompt_hashes

            prompt_hashes = _prompt_hashes()
        except Exception:
            prompt_hashes = {}
        try:
            from triad.llm.client import LLMClient

            role_impl = f"llm:{LLMClient().model}"
        except Exception:
            role_impl = "llm"

    manifest = build_manifest(
        run_id=str(resolution.run_id),
        dataset_row=int(row_index),
        seed=int(seed),
        mode=mode,
        agent_impl={role: role_impl for role in ROLES},
        prompt_hashes=prompt_hashes,
    )
    write_manifest(manifest, run_dir)
    write_resolution(resolution, run_dir)
    return run_dir, notice
