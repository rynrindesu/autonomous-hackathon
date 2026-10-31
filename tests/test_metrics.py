"""Metrics, FCFS baseline and batch evaluation. Offline, stub agents only."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from triad.agents import build_agents
from triad.agents.base import CheckIdGen
from triad.baseline import FCFS_REASON, fcfs_resolution, run_fcfs
from triad.constraints.shared import shared_checks
from triad.data.enrich import build_event
from triad.data.loader import get_record
from triad.metrics import RunMetrics, aggregate, negotiation_delta, outcome_of, run_metrics, veto_counts
from triad.options.generator import generate_options
from triad.runner import run_scenario
from triad.schemas import AgentRole, CandidateOption, ConstraintCheck, Mode, Resolution

ROOT = Path(__file__).resolve().parents[1]
DEMO_ROW = 293614  # config/demo_scenarios.yaml scenario_a


@pytest.fixture(scope="module")
def demo():
    event = build_event(get_record(DEMO_ROW), seed=0)
    agents = build_agents(event, impl="stub")
    resolution, log = run_scenario(DEMO_ROW, seed=0, impl="stub")
    return event, agents, resolution, log


def _metrics(run_id: str, outcome: str, option_id: str | None = "OPT-01", cost: float | None = 100.0, **kw):
    return RunMetrics(
        run_id=run_id,
        outcome=outcome,
        status={"TURN1": "CONSENSUS", "TURN2": "CONSENSUS", "TURN3": "CONSENSUS"}.get(outcome, outcome),
        turn={"TURN2": 2, "TURN3": 3, "FALLBACK": 3}.get(outcome, 1),
        option_id=option_id,
        total_cost_eur=cost,
        **kw,
    )


def test_run_metrics_on_real_stub_run(demo):
    event, agents, resolution, log = demo
    m = run_metrics(resolution, log, event=event, agents=agents, label="stub")

    assert resolution.option is not None
    expected_outcome = {1: "TURN1", 2: "TURN2", 3: "TURN3"}[resolution.turn]
    assert m.outcome == (expected_outcome if resolution.status == "CONSENSUS" else "FALLBACK")
    assert m.unsafe_commit is False
    assert m.option_id == resolution.option.option_id
    assert m.holding_min == resolution.option.holding_min
    assert m.arrival_delay_min == resolution.option.arrival_slot - event.public.original_eta
    assert m.fuel_kg is not None and m.co2_kg == pytest.approx(m.fuel_kg * 3.16, abs=0.2)
    assert m.missed_connections is not None and m.overtime_min is not None
    assert m.next_leg_delay_min is not None
    # same cost function as the fallback solver: matches the disclosed costs at commit
    assert m.total_cost_eur == pytest.approx(sum(resolution.costs_eur.values()), abs=0.05)
    assert m.n_feasible is not None and m.n_feasible >= 2
    total, yielded = veto_counts(log)
    assert (m.vetoes_total, m.veto_yield) == (total, yielded)
    assert 0 <= m.veto_yield <= m.vetoes_total

    # log-only call still derives outcome, delay and disclosed cost
    bare = run_metrics(resolution, log)
    assert bare.outcome == m.outcome and bare.arrival_delay_min == m.arrival_delay_min
    assert bare.total_cost_eur == pytest.approx(m.total_cost_eur, abs=0.05)
    assert bare.fuel_kg is None


def test_veto_yield_counts_only_fact_dependent_checks():
    class Log:
        entries: list = []

    from triad.schemas import LogEntry

    def entry(payload):
        return LogEntry(
            seq=1, ts="t", run_id="r", turn=1, actor="ATC", event="PROPOSAL",
            payload=payload, payload_sha256="x", prev_sha256="y",
        )

    Log.entries = [
        entry(
            {
                "vetoes": [
                    {"option_id": "OPT-01", "constraint_id": "ATC-TWY-01", "check_id": "c1"},
                    {"option_id": "OPT-02", "constraint_id": "ATC-WAKE-01", "check_id": "c2"},
                ],
                "checks": [
                    {"check_id": "c1", "facts_used": ["closed_taxiways"]},
                    {"check_id": "c2", "facts_used": []},
                ],
            }
        )
    ]
    assert veto_counts(Log) == (2, 1)


def test_aggregate_histogram_and_safety():
    runs = [
        _metrics("a", "TURN1"),
        _metrics("b", "TURN2", n_feasible=3),
        _metrics("c", "TURN2", n_feasible=1),
        _metrics("d", "FALLBACK", cost=300.0),
        _metrics("e", "ESCALATED", option_id=None, cost=None, n_feasible=0),
        _metrics("f", "TURN3", cost=0.0),
    ]
    report = aggregate(runs, label="x")
    assert report.n_runs == 6
    assert report.outcomes == {"TURN1": 1, "TURN2": 2, "TURN3": 1, "FALLBACK": 1, "ESCALATED": 1}
    assert report.turns_histogram == {"1": 2, "2": 2, "3": 2}
    assert report.unsafe_commits == 0
    assert report.feasible_ge2_rate == pytest.approx(1 / 3, abs=1e-3)
    assert report.mean_total_cost_eur == pytest.approx(120.0)


def test_outcome_label_for_each_turn():
    option = CandidateOption(option_id="OPT-01", mode=Mode.AIRBORNE, arrival_slot=600, runway="17C", gate="A1")
    base = Resolution(run_id="r", status="CONSENSUS", turn=1, decided_by="AGENTS", option=option, reason="x")
    assert outcome_of(base) == "TURN1"
    assert outcome_of(base.model_copy(update={"turn": 2})) == "TURN2"
    assert outcome_of(base.model_copy(update={"turn": 3})) == "TURN3"
    fallback = base.model_copy(update={"turn": 3, "status": "FALLBACK", "decided_by": "FALLBACK"})
    assert outcome_of(fallback) == "FALLBACK"


def test_negotiation_delta_identical_is_zero():
    runs = [_metrics("a", "TURN1"), _metrics("b", "TURN2", option_id="OPT-02", cost=50.0)]
    delta = negotiation_delta(runs, [r.model_copy() for r in runs])
    assert delta.n_rows == 2
    assert delta.changed_rate == 0
    assert delta.mean_cost_diff_eur == 0

    other = [_metrics("a", "TURN1", option_id="OPT-03", cost=160.0), runs[1]]
    delta = negotiation_delta(runs, other)
    assert delta.changed_rate == 0.5
    assert delta.mean_cost_diff_eur == pytest.approx(30.0)


def test_fcfs_picks_earliest_safe_arrival(demo):
    event, agents, _resolution, _log = demo
    options = generate_options(event.public)

    resolution, m = run_fcfs(event, agents, options)

    next_id = CheckIdGen("T")
    safe = []
    for o in options:
        if o.divert_to:
            continue
        checks = list(shared_checks(event.public, o, next_id))
        for role in (AgentRole.ATC, AgentRole.PILOT, AgentRole.GROUND):
            checks.extend(agents[role].check(event.public, o))
        if all(c.passed for c in checks if c.hard):
            safe.append(o)
    assert safe
    earliest = min(safe, key=lambda o: (o.arrival_slot, o.option_id))
    assert resolution.option == earliest
    assert resolution.reason == FCFS_REASON
    assert m.simulated is True and m.label == "fcfs"
    assert m.unsafe_commit is False
    assert m.n_feasible == len(safe)
    assert m.total_cost_eur == pytest.approx(sum(resolution.costs_eur.values()), abs=0.05)


def test_fcfs_escalates_when_nothing_is_safe(demo):
    event, agents, _resolution, _log = demo
    bad = CandidateOption(
        option_id="OPT-99", mode=Mode.AIRBORNE, arrival_slot=event.public.expected_eta,
        runway="NOT-A-RUNWAY", gate="NOWHERE",
    )
    resolution = fcfs_resolution(event, agents, [bad])
    assert resolution.status == "ESCALATED" and resolution.option is None
    assert run_metrics(resolution).outcome == "ESCALATED"


def test_escalated_and_unsafe_hand_built_resolutions():
    escalated = Resolution(
        run_id="r1", status="ESCALATED", turn=0, decided_by="HUMAN_ESCALATION",
        option=None, reason="NO_SAFE_OPTION; recommend diversion to OKC",
    )
    m = run_metrics(escalated)
    assert m.outcome == "ESCALATED"
    assert (m.fallback_reason or "").startswith("NO_SAFE_OPTION")
    assert m.unsafe_commit is False
    assert m.option_id is None and m.total_cost_eur is None and m.holding_min is None

    option = CandidateOption(option_id="OPT-01", mode=Mode.AIRBORNE, arrival_slot=600, runway="17C", gate="A1")
    failed = ConstraintCheck(
        check_id="c", constraint_id="PLT-FUEL-01", owner="PILOT", option_id="OPT-01",
        passed=False, source="test",
    )
    unsafe = Resolution(
        run_id="r2", status="CONSENSUS", turn=1, decided_by="AGENTS",
        option=option, reason="x", checks=[failed],
    )
    unchecked = unsafe.model_copy(update={"run_id": "r3", "checks": []})
    report = aggregate([m, run_metrics(unsafe), run_metrics(unchecked)])
    assert report.unsafe_commits == 2
    assert report.outcomes["ESCALATED"] == 1 and report.outcomes["TURN1"] == 2


def test_batch_main_tiny(tmp_path):
    spec = importlib.util.spec_from_file_location("batch_eval", ROOT / "scripts" / "batch_eval.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    out = tmp_path / "batch.json"
    report = module.main(["--n", "3", "--modes", "stub,ai-off,fcfs", "--out", str(out), "--quiet"])

    assert out.exists()
    saved = json.loads(out.read_text())
    assert saved["n_rows"] == 3 and len(saved["rows"]) == 3
    assert module.sample_rows(3, 0) == saved["rows"]  # deterministic sampling
    for mode in ("stub", "ai-off", "fcfs"):
        r = report["reports"][mode]
        assert r["n_runs"] + report["error_counts"].get(mode, 0) == 3
        assert r["unsafe_commits"] == 0
    assert set(report["deltas"]) == {"ai-off", "fcfs"}
    assert (tmp_path / "batch").is_dir()  # per-run logs next to the report
