from __future__ import annotations

import pytest

from fakes import (
    FakeAgent,
    FakePrivate,
    make_option,
    make_options,
    make_public,
    make_shared_checker,
)
from triad.agents.stub import StubAgent
from triad.coordinator.protocol import Orchestrator
from triad.log.consensus_log import ConsensusLog
from triad.schemas import AgentRole, ConstraintCheck, CounterOption, Vote


def run(agents, *, options=None, shared_fail=None, public=None, ai_off=False, failover_factory=None):
    public = public or make_public()
    options = options or make_options()
    log = ConsensusLog(public.run_id)
    orchestrator = Orchestrator(
        public,
        agents,
        log,
        option_generator=lambda _public: list(options),
        shared_checker=make_shared_checker(shared_fail),
        failover_factory=failover_factory,
    )
    return orchestrator.run(ai_off=ai_off), log


def events(log: ConsensusLog, name: str):
    return [e for e in log.entries if e.event == name]


def test_fast_path_commits_at_turn_one():
    agents = {
        AgentRole.ATC: FakeAgent(AgentRole.ATC, ranking=["OPT-01", "OPT-02"]),
        AgentRole.PILOT: FakeAgent(AgentRole.PILOT, ranking=["OPT-01", "OPT-02"]),
        AgentRole.GROUND: FakeAgent(AgentRole.GROUND, ranking=["OPT-01", "OPT-02"]),
    }
    resolution, log = run(agents)
    assert resolution.status == "CONSENSUS"
    assert resolution.turn == 1
    assert resolution.decided_by == "AGENTS"
    assert resolution.option is not None and resolution.option.option_id == "OPT-01"
    assert len(events(log, "PROPOSAL")) == 3
    assert len(events(log, "BALLOT")) == 0
    assert len(events(log, "COMMIT")) == 1
    assert ConsensusLog.verify(log.entries)


def test_turn_two_unanimous_approval():
    agents = {
        AgentRole.ATC: FakeAgent(
            AgentRole.ATC,
            ranking=["OPT-01", "OPT-02", "OPT-03"],
            util_map={"OPT-01": 1.0, "OPT-02": 0.9, "OPT-03": 0.8},
        ),
        AgentRole.PILOT: FakeAgent(
            AgentRole.PILOT,
            ranking=["OPT-02", "OPT-01", "OPT-03"],
            util_map={"OPT-02": 1.0, "OPT-01": 0.9, "OPT-03": 0.85},
        ),
        AgentRole.GROUND: FakeAgent(
            AgentRole.GROUND,
            ranking=["OPT-03", "OPT-01", "OPT-02"],
            util_map={"OPT-03": 1.0, "OPT-01": 0.9, "OPT-02": 0.85},
        ),
    }
    resolution, log = run(agents)
    assert resolution.status == "CONSENSUS"
    assert resolution.turn == 2
    assert len(events(log, "BALLOT")) == 3
    assert len(events(log, "SHORTLIST")) == 1


def test_no_unanimous_approval_falls_back_to_cheapest_safe():
    approve_x = {"OPT-01": ("APPROVE", None), "OPT-02": ("DISAPPROVE", "OTHER"), "OPT-03": ("DISAPPROVE", "OTHER")}
    approve_y = {"OPT-01": ("DISAPPROVE", "OTHER"), "OPT-02": ("APPROVE", None), "OPT-03": ("DISAPPROVE", "OTHER")}
    approve_z = {"OPT-01": ("DISAPPROVE", "OTHER"), "OPT-02": ("DISAPPROVE", "OTHER"), "OPT-03": ("APPROVE", None)}
    cheap = {"OPT-01": {"TOTAL": 50.0}, "OPT-02": {"TOTAL": 10.0}, "OPT-03": {"TOTAL": 40.0}, "OPT-04": {"TOTAL": 60.0}}
    agents = {
        AgentRole.ATC: FakeAgent(
            AgentRole.ATC,
            ranking=["OPT-01", "OPT-03", "OPT-02"],
            turn2_votes=approve_x,
            cost_map=cheap,
        ),
        AgentRole.PILOT: FakeAgent(
            AgentRole.PILOT,
            ranking=["OPT-02", "OPT-01", "OPT-03"],
            turn2_votes=approve_y,
            cost_map=cheap,
        ),
        AgentRole.GROUND: FakeAgent(
            AgentRole.GROUND,
            ranking=["OPT-03", "OPT-02", "OPT-01"],
            turn2_votes=approve_z,
            cost_map=cheap,
        ),
    }
    resolution, log = run(agents)
    assert resolution.status == "FALLBACK"
    assert resolution.turn == 2
    assert resolution.decided_by == "FALLBACK"
    assert resolution.reason == "NO_UNANIMOUS_APPROVAL"
    assert resolution.option is not None and resolution.option.option_id == "OPT-02"
    assert len(events(log, "FALLBACK_INVOKED")) == 1


def test_valid_counter_is_shortlisted_and_attributed():
    agents = {
        AgentRole.ATC: FakeAgent(AgentRole.ATC, ranking=["OPT-01", "OPT-02", "OPT-03"]),
        AgentRole.PILOT: FakeAgent(AgentRole.PILOT, ranking=["OPT-02", "OPT-01", "OPT-03"]),
        AgentRole.GROUND: FakeAgent(
            AgentRole.GROUND,
            ranking=["OPT-03", "OPT-01", "OPT-02"],
            counter=CounterOption(base_option_id="OPT-03", changes={"gate": "B14"}),
        ),
    }
    resolution, log = run(agents)
    validated = events(log, "COUNTER_VALIDATED")
    assert len(validated) == 1
    assert validated[0].payload["option_id"] == "CTR-GROUND-1"
    shortlist = events(log, "SHORTLIST")[0].payload["option_ids"]
    assert "CTR-GROUND-1" in shortlist
    assert resolution.turn <= 2


def test_counter_rejected_when_any_agent_check_fails():
    agents = {
        AgentRole.ATC: FakeAgent(AgentRole.ATC, ranking=["OPT-01", "OPT-02", "OPT-03"]),
        AgentRole.PILOT: FakeAgent(
            AgentRole.PILOT,
            ranking=["OPT-02", "OPT-01", "OPT-03"],
            fail_map={"CTR-GROUND-1": ["GND-GATE-02"]},
        ),
        AgentRole.GROUND: FakeAgent(
            AgentRole.GROUND,
            ranking=["OPT-03", "OPT-01", "OPT-02"],
            counter=CounterOption(base_option_id="OPT-03", changes={"gate": "B14"}),
        ),
    }
    _resolution, log = run(agents)
    rejected = events(log, "COUNTER_REJECTED")
    assert len(rejected) == 1
    assert rejected[0].payload["option_id"] == "CTR-GROUND-1"
    assert any(
        e.payload.get("detail") == "unsafe counter rejected" for e in events(log, "SAFETY_BLOCK")
    )
    assert "CTR-GROUND-1" not in events(log, "SHORTLIST")[0].payload["option_ids"]


def test_counter_rejecting_illegal_field():
    agents = {
        AgentRole.ATC: FakeAgent(AgentRole.ATC, ranking=["OPT-01", "OPT-02"]),
        AgentRole.PILOT: FakeAgent(AgentRole.PILOT, ranking=["OPT-01", "OPT-02"]),
        AgentRole.GROUND: FakeAgent(
            AgentRole.GROUND,
            ranking=["OPT-01", "OPT-02"],
            counter=CounterOption(base_option_id="OPT-01", changes={"option_id": "HACK"}),
        ),
    }
    _resolution, log = run(agents)
    rejected = events(log, "COUNTER_REJECTED")
    assert len(rejected) == 1
    assert "illegal counter field" in rejected[0].payload["error"]


def test_agent_exception_triggers_logged_failover():
    bad = FakeAgent(AgentRole.ATC, raise_turn1=True)
    replacement = FakeAgent(AgentRole.ATC, ranking=["OPT-01", "OPT-02"])
    agents = {
        AgentRole.ATC: bad,
        AgentRole.PILOT: FakeAgent(AgentRole.PILOT, ranking=["OPT-01", "OPT-02"]),
        AgentRole.GROUND: FakeAgent(AgentRole.GROUND, ranking=["OPT-01", "OPT-02"]),
    }
    resolution, log = run(agents, failover_factory=lambda agent: replacement)
    failovers = events(log, "AGENT_FAILOVER")
    assert len(failovers) == 1
    assert failovers[0].payload["role"] == "ATC"
    assert failovers[0].payload["turn"] == 1
    assert resolution.status == "CONSENSUS"


def test_omitted_veto_is_safety_block_and_unsafe_option_never_commits():
    agents = {
        AgentRole.ATC: FakeAgent(AgentRole.ATC, ranking=["OPT-02", "OPT-01", "OPT-03", "OPT-04"]),
        AgentRole.PILOT: FakeAgent(
            AgentRole.PILOT,
            ranking=["OPT-02", "OPT-01", "OPT-03", "OPT-04"],
            fail_map={"OPT-02": ["PLT-FUEL-01"]},
            omit_vetoes=True,
        ),
        AgentRole.GROUND: FakeAgent(AgentRole.GROUND, ranking=["OPT-02", "OPT-01", "OPT-03", "OPT-04"]),
    }
    resolution, log = run(agents)
    blocks = events(log, "SAFETY_BLOCK")
    assert any(b.payload.get("detail") == "omitted veto" and b.payload.get("option_id") == "OPT-02" for b in blocks)
    shortlist = events(log, "SHORTLIST")[0].payload["option_ids"]
    assert "OPT-02" not in shortlist
    assert resolution.option is not None and resolution.option.option_id != "OPT-02"


def test_approve_outside_shortlist_is_discarded_and_blocked():
    agents = {
        AgentRole.ATC: FakeAgent(
            AgentRole.ATC,
            ranking=["OPT-01", "OPT-02", "OPT-03"],
            util_map={"OPT-01": 1.0, "OPT-02": 0.9, "OPT-03": 0.8},
            extra_votes=[Vote(option_id="OPT-04", vote="APPROVE")],
        ),
        AgentRole.PILOT: FakeAgent(
            AgentRole.PILOT,
            ranking=["OPT-02", "OPT-01", "OPT-03"],
            util_map={"OPT-02": 1.0, "OPT-01": 0.9, "OPT-03": 0.85},
        ),
        AgentRole.GROUND: FakeAgent(
            AgentRole.GROUND,
            ranking=["OPT-03", "OPT-01", "OPT-02"],
            util_map={"OPT-03": 1.0, "OPT-01": 0.9, "OPT-02": 0.85},
        ),
    }
    resolution, log = run(agents)
    blocks = events(log, "SAFETY_BLOCK")
    assert any(b.payload.get("detail") == "approve outside shortlist" for b in blocks)
    assert resolution.option is not None and resolution.option.option_id != "OPT-04"


def test_ai_off_path_uses_fallback_without_agent_turns():
    costs = {
        "OPT-01": {"TOTAL": 40.0},
        "OPT-02": {"TOTAL": 5.0},
        "OPT-03": {"TOTAL": 30.0},
        "OPT-04": {"TOTAL": 90.0},
    }
    agents = {
        AgentRole.ATC: FakeAgent(AgentRole.ATC, cost_map=costs, ranking=["OPT-01"]),
        AgentRole.PILOT: FakeAgent(AgentRole.PILOT, cost_map=costs, ranking=["OPT-01"]),
        AgentRole.GROUND: FakeAgent(AgentRole.GROUND, cost_map=costs, ranking=["OPT-01"]),
    }
    resolution, log = run(agents, ai_off=True)
    assert resolution.status == "FALLBACK"
    assert resolution.turn == 0
    assert resolution.decided_by == "FALLBACK"
    assert resolution.reason == "AI_OFF"
    assert resolution.option is not None and resolution.option.option_id == "OPT-02"
    assert len(events(log, "PROPOSAL")) == 0
    assert len(events(log, "COMMIT")) == 1


def test_no_safe_option_escalates():
    agents = {
        AgentRole.ATC: FakeAgent(AgentRole.ATC, fail_map={f"OPT-{i:02d}": ["ATC-RWY-01"] for i in range(1, 5)}),
        AgentRole.PILOT: FakeAgent(AgentRole.PILOT, ranking=["OPT-01"]),
        AgentRole.GROUND: FakeAgent(AgentRole.GROUND, ranking=["OPT-01"]),
    }
    resolution, log = run(agents)
    assert resolution.status == "ESCALATED"
    assert resolution.decided_by == "HUMAN_ESCALATION"
    assert resolution.option is None
    assert "NO_SAFE_OPTION" in resolution.reason
    assert "OKC" in resolution.reason
    assert resolution.turn <= 2


def test_divert_excluded_unless_only_feasible():
    options = make_options() + [make_option("OPT-DIV", divert_to="OKC")]
    agents = {
        AgentRole.ATC: FakeAgent(AgentRole.ATC, ranking=["OPT-DIV", "OPT-01", "OPT-02", "OPT-03", "OPT-04"]),
        AgentRole.PILOT: FakeAgent(AgentRole.PILOT, ranking=["OPT-01", "OPT-02", "OPT-03"]),
        AgentRole.GROUND: FakeAgent(AgentRole.GROUND, ranking=["OPT-01", "OPT-02", "OPT-03"]),
    }
    _resolution, log = run(agents, options=options)
    shortlist = events(log, "SHORTLIST")[0].payload["option_ids"]
    assert "OPT-DIV" not in shortlist


def test_max_turns_is_fixed_at_two():
    with pytest.raises(AssertionError):
        Orchestrator(make_public(), {}, ConsensusLog("x"), max_turns=3)


@pytest.mark.parametrize(
    "scenario",
    ["fast", "turn2", "fallback", "redteam", "ai_off"],
)
def test_every_run_ends_by_turn_two_and_committed_option_is_safe(scenario):
    options = make_options()
    if scenario == "fast":
        agents = {
            AgentRole.ATC: FakeAgent(AgentRole.ATC, ranking=["OPT-01", "OPT-02"]),
            AgentRole.PILOT: FakeAgent(AgentRole.PILOT, ranking=["OPT-01", "OPT-02"]),
            AgentRole.GROUND: FakeAgent(AgentRole.GROUND, ranking=["OPT-01", "OPT-02"]),
        }
        ai_off = False
    elif scenario == "turn2":
        agents = {
            AgentRole.ATC: FakeAgent(AgentRole.ATC, ranking=["OPT-01", "OPT-02", "OPT-03"]),
            AgentRole.PILOT: FakeAgent(AgentRole.PILOT, ranking=["OPT-02", "OPT-01", "OPT-03"]),
            AgentRole.GROUND: FakeAgent(AgentRole.GROUND, ranking=["OPT-03", "OPT-01", "OPT-02"]),
        }
        ai_off = False
    elif scenario == "fallback":
        agents = {
            AgentRole.ATC: FakeAgent(
                AgentRole.ATC,
                ranking=["OPT-01", "OPT-02", "OPT-03"],
                turn2_votes={
                    "OPT-01": ("APPROVE", None),
                    "OPT-02": ("DISAPPROVE", "OTHER"),
                    "OPT-03": ("DISAPPROVE", "OTHER"),
                },
            ),
            AgentRole.PILOT: FakeAgent(
                AgentRole.PILOT,
                ranking=["OPT-02", "OPT-01", "OPT-03"],
                turn2_votes={
                    "OPT-01": ("DISAPPROVE", "OTHER"),
                    "OPT-02": ("APPROVE", None),
                    "OPT-03": ("DISAPPROVE", "OTHER"),
                },
            ),
            AgentRole.GROUND: FakeAgent(
                AgentRole.GROUND,
                ranking=["OPT-03", "OPT-01", "OPT-02"],
                turn2_votes={
                    "OPT-01": ("DISAPPROVE", "OTHER"),
                    "OPT-02": ("DISAPPROVE", "OTHER"),
                    "OPT-03": ("APPROVE", None),
                },
            ),
        }
        ai_off = False
    elif scenario == "redteam":
        agents = {
            AgentRole.ATC: FakeAgent(AgentRole.ATC, ranking=["OPT-02", "OPT-01", "OPT-03"]),
            AgentRole.PILOT: FakeAgent(
                AgentRole.PILOT,
                ranking=["OPT-02", "OPT-01", "OPT-03"],
                fail_map={"OPT-02": ["PLT-FUEL-01"], "OPT-03": ["PLT-FUEL-02"]},
                omit_vetoes=True,
            ),
            AgentRole.GROUND: FakeAgent(AgentRole.GROUND, ranking=["OPT-02", "OPT-01", "OPT-03"]),
        }
        ai_off = False
    else:
        agents = {
            AgentRole.ATC: FakeAgent(AgentRole.ATC, cost_map={"OPT-01": {"TOTAL": 5.0}}),
            AgentRole.PILOT: FakeAgent(AgentRole.PILOT, cost_map={"OPT-01": {"TOTAL": 5.0}}),
            AgentRole.GROUND: FakeAgent(AgentRole.GROUND, cost_map={"OPT-01": {"TOTAL": 5.0}}),
        }
        ai_off = True

    resolution, log = run(agents, options=options, ai_off=ai_off)
    assert resolution.turn <= 2
    assert ConsensusLog.verify(log.entries)
    if resolution.option is None:
        assert resolution.status == "ESCALATED"
        return
    for agent in agents.values():
        assert all(c.passed for c in agent.check(make_public(), resolution.option) if c.hard)


def test_shortlist_logs_fallback_projection_and_passes_it_to_turn2():
    costs = {"OPT-01": {"TOTAL": 80.0}, "OPT-02": {"TOTAL": 10.0}, "OPT-03": {"TOTAL": 40.0}, "OPT-04": {"TOTAL": 60.0}}
    agents = {
        AgentRole.ATC: FakeAgent(AgentRole.ATC, ranking=["OPT-01", "OPT-02", "OPT-03"], cost_map=costs),
        AgentRole.PILOT: FakeAgent(AgentRole.PILOT, ranking=["OPT-03", "OPT-01", "OPT-02"], cost_map=costs),
        AgentRole.GROUND: FakeAgent(AgentRole.GROUND, ranking=["OPT-04", "OPT-01", "OPT-02"], cost_map=costs),
    }
    resolution, log = run(agents)
    shortlist = events(log, "SHORTLIST")[0].payload
    assert shortlist["fallback_option_id"] == "OPT-02"
    for agent in agents.values():
        assert agent.last_fallback_option is not None
        assert agent.last_fallback_option.option_id == "OPT-02"
    assert resolution.turn <= 2


def test_stub_turn2_approves_an_option_at_least_as_good_as_the_fallback():
    public = make_public()
    cfg = {"weights": {}, "accept_tolerance": 0.1, "objection_threshold": 1.1}
    agent = StubAgent(AgentRole.ATC, FakePrivate(), cfg)
    agent.perceive = lambda _public: []
    agent.objectives = lambda _public, _option: {"THROUGHPUT": 0.5}
    agent.utility = lambda _public, option: {"OPT-01": 1.0, "OPT-02": 0.5}.get(option.option_id, 0.0)

    def check(_public, option):
        return [
            ConstraintCheck(
                check_id=agent._next_check_id(),
                constraint_id="ATC-OK-01",
                owner=AgentRole.ATC,
                option_id=option.option_id,
                passed=True,
                source="test",
            )
        ]

    agent.check = check
    shortlist = [make_option("OPT-01"), make_option("OPT-02")]

    with_fallback = agent.turn2(
        public, shortlist, [], fallback_option=make_option("OPT-02")
    )
    votes = {vote.option_id: vote for vote in with_fallback.votes}
    assert votes["OPT-02"].vote == "APPROVE"  # 0.5 >= fallback 0.5 despite 0.1 tolerance

    without_fallback = agent.turn2(public, shortlist, [])
    votes = {vote.option_id: vote for vote in without_fallback.votes}
    assert votes["OPT-02"].vote == "DISAPPROVE"
