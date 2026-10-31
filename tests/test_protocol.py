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
from triad.coordinator.protocol import MAX_TURNS, Orchestrator, TurnLimitExceeded
from triad.log.consensus_log import ConsensusLog
from triad.schemas import AgentRole, ConstraintCheck, CounterOption, PublicSummary, Vote


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
    assert resolution.turn == 3  # fallback only after the final ballot
    assert resolution.decided_by == "FALLBACK"
    assert resolution.reason == "NO_UNANIMOUS_APPROVAL"
    assert resolution.option is not None and resolution.option.option_id == "OPT-02"
    assert len(events(log, "FALLBACK_INVOKED")) == 1
    assert [e.turn for e in events(log, "BALLOT")] == [2, 2, 2, 3, 3, 3]


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
    assert resolution.turn <= 3


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
    assert resolution.turn <= 3


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


def test_turn_limit_is_three_and_can_never_be_exceeded():
    assert MAX_TURNS == 3
    for bad in (0, 4, 10, True):
        with pytest.raises(ValueError):
            Orchestrator(make_public(), {}, ConsensusLog("x"), max_turns=bad)
    orchestrator = Orchestrator(make_public(), {}, ConsensusLog("x"))
    assert orchestrator.max_turns == 3
    with pytest.raises(TurnLimitExceeded):
        orchestrator._turn_start(4, [], "never")
    # a run that never agrees still stops at turn 3
    resolution, log = run(_split_agents())
    assert resolution.turn == 3
    assert max(e.turn for e in log.entries) == 3
    assert [e.payload["turn"] for e in events(log, "TURN_START")] == [1, 2, 3]


@pytest.mark.parametrize(
    "scenario",
    ["fast", "turn2", "fallback", "redteam", "ai_off"],
)
def test_every_run_ends_by_turn_three_and_committed_option_is_safe(scenario):
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
    assert resolution.turn <= 3
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
    assert resolution.turn <= 3


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


# --------------------------------------------------------------------------- three-turn protocol

A = ("APPROVE", None)


def D(reason: str = "OTHER"):
    return ("DISAPPROVE", reason)


_COSTS = {
    "OPT-01": {"TOTAL": 50.0},
    "OPT-02": {"TOTAL": 10.0},
    "OPT-03": {"TOTAL": 40.0},
    "OPT-04": {"TOTAL": 60.0},
}


def _split_agents(**extra):
    """Each agent approves only its own favourite in every ballot -> no agreement."""
    votes = {
        AgentRole.ATC: {"OPT-01": A, "OPT-02": D("THROUGHPUT"), "OPT-03": D("HOLDING_STACK")},
        AgentRole.PILOT: {"OPT-01": D("FUEL"), "OPT-02": A, "OPT-03": D("PAX_CONNECTIONS")},
        AgentRole.GROUND: {"OPT-01": D("OVERTIME"), "OPT-02": D("GATE_CHANGE"), "OPT-03": A},
    }
    rankings = {
        AgentRole.ATC: ["OPT-01", "OPT-03", "OPT-02"],
        AgentRole.PILOT: ["OPT-02", "OPT-01", "OPT-03"],
        AgentRole.GROUND: ["OPT-03", "OPT-02", "OPT-01"],
    }
    return {
        role: FakeAgent(
            role,
            ranking=rankings[role],
            turn2_votes=votes[role],
            cost_map=_COSTS,
            **extra.get(role, {}),
        )
        for role in (AgentRole.ATC, AgentRole.PILOT, AgentRole.GROUND)
    }


def test_turn_start_events_for_each_turn():
    _resolution, log = run(_split_agents())
    starts = events(log, "TURN_START")
    assert [(e.turn, e.payload["turn"]) for e in starts] == [(1, 1), (2, 2), (3, 3)]
    assert starts[0].payload["reason"] == "T1 proposals"
    assert starts[0].payload["shortlist"] == ["OPT-01", "OPT-02", "OPT-03", "OPT-04"]
    assert starts[1].payload["reason"].startswith("no T1 fast path: first choices differ")
    assert starts[2].payload["reason"].startswith("no unanimous T2 approval: ")
    assert "PILOT (FUEL)" in starts[2].payload["reason"]
    assert 1 <= len(starts[2].payload["shortlist"]) <= 4
    # TURN_START precedes that turn's agent messages
    seqs = {e.event: e.seq for e in log.entries if e.turn == 3 and e.event in {"TURN_START", "BALLOT"}}
    assert seqs["TURN_START"] < seqs["BALLOT"]


def test_unanimity_at_turn_three_commits_at_turn_three():
    agents = {
        AgentRole.ATC: FakeAgent(
            AgentRole.ATC,
            ranking=["OPT-01", "OPT-02", "OPT-03"],
            turn2_votes={"OPT-01": A, "OPT-02": D(), "OPT-03": D()},
        ),
        AgentRole.PILOT: FakeAgent(
            AgentRole.PILOT,
            ranking=["OPT-02", "OPT-01", "OPT-03"],
            turn2_votes={"OPT-01": A, "OPT-02": A, "OPT-03": D()},
        ),
        AgentRole.GROUND: FakeAgent(
            AgentRole.GROUND,
            ranking=["OPT-03", "OPT-02", "OPT-01"],
            turn2_votes={"OPT-01": D("OVERTIME"), "OPT-02": A, "OPT-03": A},
            turn3_votes={"OPT-01": A, "OPT-02": A, "OPT-03": A},
        ),
    }
    resolution, log = run(agents)
    assert resolution.status == "CONSENSUS"
    assert resolution.decided_by == "AGENTS"
    assert resolution.turn == 3
    assert resolution.option is not None and resolution.option.option_id == "OPT-01"
    assert events(log, "COMMIT")[0].turn == 3
    assert not events(log, "FALLBACK_INVOKED")
    # narrowed shortlist: the two 2-of-3 options come first
    t3 = events(log, "SHORTLIST")[1].payload
    assert t3["for_turn"] == 3
    assert set(t3["option_ids"][:2]) == {"OPT-01", "OPT-02"}
    assert len(t3["option_ids"]) <= 4


def test_turn3_agents_see_only_the_others_turn2_votes():
    agents = _split_agents()
    run(agents)
    for role, agent in agents.items():
        assert len(agent.turn3_calls) == 1
        summaries = agent.turn3_calls[0]["summaries"]
        assert {s.sender for s in summaries} == {r for r in agents if r is not role}
        assert all(isinstance(s, PublicSummary) and s.turn == 2 and s.votes for s in summaries)
    pilot_view = {s.sender: s for s in agents[AgentRole.ATC].turn3_calls[0]["summaries"]}
    votes = {v.option_id: v for v in pilot_view[AgentRole.PILOT].votes}
    assert votes["OPT-01"].vote == "DISAPPROVE" and votes["OPT-01"].reason == "FUEL"


def _t2_counter_agents(*, ground_counter, pilot_fail=None, ground_t2=None):
    return {
        AgentRole.ATC: FakeAgent(
            AgentRole.ATC,
            ranking=["OPT-01", "OPT-02", "OPT-03"],
            turn2_votes={"OPT-01": A, "OPT-02": D(), "OPT-03": D()},
            turn3_votes={"OPT-01": A, "CTR-GROUND-2": A, "OPT-02": D(), "OPT-03": D()},
        ),
        AgentRole.PILOT: FakeAgent(
            AgentRole.PILOT,
            ranking=["OPT-01", "OPT-03", "OPT-02"],
            turn2_votes={"OPT-01": A, "OPT-02": D(), "OPT-03": D()},
            turn3_votes={"OPT-01": A, "CTR-GROUND-2": A, "OPT-02": D(), "OPT-03": D()},
            fail_map=pilot_fail or {},
        ),
        AgentRole.GROUND: FakeAgent(
            AgentRole.GROUND,
            ranking=["OPT-02", "OPT-03", "OPT-01"],
            turn2_votes=ground_t2 or {"OPT-01": D("GATE_CHANGE"), "OPT-02": D(), "OPT-03": D()},
            turn3_votes={"OPT-01": D("GATE_CHANGE"), "CTR-GROUND-2": A, "OPT-02": D(), "OPT-03": D()},
            turn2_counter=ground_counter,
        ),
    }


def test_turn2_counter_is_validated_and_committed_in_turn_three():
    counter = CounterOption(base_option_id="OPT-01", changes={"gate": "B14"})
    resolution, log = run(_t2_counter_agents(ground_counter=counter))
    validated = [e for e in events(log, "COUNTER_VALIDATED") if e.turn == 2]
    assert len(validated) == 1
    payload = validated[0].payload
    assert payload["option_id"] == "CTR-GROUND-2" and payload["turn"] == 2
    assert payload["option"]["gate"] == "B14" and payload["option"]["base_option_id"] == "OPT-01"
    assert payload["option"]["origin"] == "COUNTER" and payload["option"]["proposed_by"] == "GROUND"
    assert {c["owner"] for c in payload["checks"]} == {"SHARED", "ATC", "PILOT", "GROUND"}
    t3_start = events(log, "TURN_START")[2].payload
    assert "CTR-GROUND-2" in t3_start["shortlist"]
    assert resolution.status == "CONSENSUS" and resolution.turn == 3
    assert resolution.option is not None and resolution.option.option_id == "CTR-GROUND-2"
    assert resolution.option.gate == "B14"


def test_invalid_turn2_counter_is_rejected():
    counter = CounterOption(base_option_id="OPT-01", changes={"gate": "B14"})
    resolution, log = run(
        _t2_counter_agents(ground_counter=counter, pilot_fail={"CTR-GROUND-2": ["PLT-FUEL-01"]})
    )
    rejected = [e for e in events(log, "COUNTER_REJECTED") if e.turn == 2]
    assert len(rejected) == 1
    assert rejected[0].payload["option_id"] == "CTR-GROUND-2"
    assert rejected[0].payload["option"]["gate"] == "B14"
    assert [c["constraint_id"] for c in rejected[0].payload["failing_checks"]] == ["PLT-FUEL-01"]
    assert any(
        e.payload.get("detail") == "unsafe counter rejected" and e.turn == 2 for e in events(log, "SAFETY_BLOCK")
    )
    assert "CTR-GROUND-2" not in events(log, "TURN_START")[2].payload["shortlist"]
    assert resolution.option is None or resolution.option.option_id != "CTR-GROUND-2"


def test_turn2_counter_must_revise_a_disapproved_option():
    counter = CounterOption(base_option_id="OPT-01", changes={"gate": "B14"})
    _resolution, log = run(
        _t2_counter_agents(
            ground_counter=counter,
            ground_t2={"OPT-01": A, "OPT-02": D(), "OPT-03": D("OVERTIME")},
        )
    )
    rejected = [e for e in events(log, "COUNTER_REJECTED") if e.turn == 2]
    assert len(rejected) == 1
    assert "disapproved" in rejected[0].payload["error"]
    assert not [e for e in events(log, "COUNTER_VALIDATED") if e.turn == 2]


def test_counter_in_turn_three_is_discarded_and_logged():
    agents = _split_agents(
        **{AgentRole.ATC: {"turn3_counter": CounterOption(base_option_id="OPT-01", changes={"runway": "17L"})}}
    )
    resolution, log = run(agents)
    rejected = [e for e in events(log, "COUNTER_REJECTED") if e.turn == 3]
    assert len(rejected) == 1
    assert rejected[0].payload["role"] == "ATC"
    assert "not allowed in Turn 3" in rejected[0].payload["error"]
    assert not [e for e in events(log, "COUNTER_VALIDATED") if e.turn == 3]
    assert all(not str(oid).startswith("CTR-ATC") for oid in events(log, "FALLBACK_INVOKED")[0].payload["pool"])
    assert resolution.turn == 3


def test_fallback_after_turn_three_explains_why():
    agents = _split_agents(**{AgentRole.ATC: {"fail_map": {"OPT-04": ["ATC-RWY-01"]}}})
    resolution, log = run(agents)
    assert resolution.status == "FALLBACK" and resolution.turn == 3
    assert resolution.option is not None and resolution.option.option_id == "OPT-02"
    fallback = events(log, "FALLBACK_INVOKED")
    assert len(fallback) == 1 and fallback[0].turn == 3
    why = fallback[0].payload
    assert why["reason_code"] == "NO_UNANIMOUS_APPROVAL"
    assert why["turns_used"] == 3
    assert [t["turn"] for t in why["per_turn"]] == [1, 2, 3]
    t2 = why["per_turn"][1]["per_agent"]
    assert t2["PILOT"]["approved"] == ["OPT-02"]
    assert {"option_id": "OPT-01", "reason": "FUEL"} in t2["PILOT"]["disapproved"]
    blocking = {b["option_id"]: b for b in why["blocking"]}
    assert "PILOT" in blocking["OPT-01"]["blocked_by"]
    assert "PILOT: FUEL" in blocking["OPT-01"]["reasons"]
    assert blocking["OPT-01"]["approved_by"] == ["ATC"]
    assert why["vetoed_by_code"]["OPT-04"] == [{"role": "ATC", "constraint_id": "ATC-RWY-01"}]
    assert set(why["pool"]) == {"OPT-01", "OPT-02", "OPT-03"}
    assert why["chosen"] == "OPT-02" == why["option_id"]
    assert "OPT-02" in why["tie_break"] and "lowest total" in why["tie_break"]
    summary = why["summary"]
    assert "No option won all three approvals in 3 turns" in summary
    assert "OPT-01 was blocked by" in summary and "PILOT (FUEL)" in summary
    assert "picked OPT-02" in summary and "cheapest option that passes every check" in summary
    assert ConsensusLog.verify(log.entries)


def test_setup_flags_record_turn_limit_and_limits_key():
    _resolution, log = run(_split_agents())
    flags = events(log, "SETUP")[0].payload["flags"]
    assert flags["max_turns"] == 3
    assert "limits" in flags


def test_unanimity_at_each_turn_commits_at_the_right_turn():
    fast = {
        role: FakeAgent(role, ranking=["OPT-01", "OPT-02"])
        for role in (AgentRole.ATC, AgentRole.PILOT, AgentRole.GROUND)
    }
    assert run(fast)[0].turn == 1
    t2 = {
        AgentRole.ATC: FakeAgent(AgentRole.ATC, ranking=["OPT-01", "OPT-02", "OPT-03"]),
        AgentRole.PILOT: FakeAgent(AgentRole.PILOT, ranking=["OPT-02", "OPT-01", "OPT-03"]),
        AgentRole.GROUND: FakeAgent(AgentRole.GROUND, ranking=["OPT-03", "OPT-01", "OPT-02"]),
    }
    resolution, log = run(t2)
    assert resolution.turn == 2 and resolution.status == "CONSENSUS"
    assert [e.payload["turn"] for e in events(log, "TURN_START")] == [1, 2]
    agents = _split_agents(
        **{role: {"turn3_votes": {"OPT-01": A, "OPT-02": A, "OPT-03": A}} for role in (AgentRole.ATC, AgentRole.PILOT, AgentRole.GROUND)}
    )
    resolution, _log = run(agents)
    assert resolution.turn == 3 and resolution.status == "CONSENSUS"


def test_stub_turn2_counter_is_deterministic_and_only_on_soft_disapproval():
    public = make_public()
    cfg = {"weights": {"GATE_CHANGE": 1.0}, "accept_tolerance": 0.25, "objection_threshold": 1.1}

    def build():
        agent = StubAgent(AgentRole.GROUND, FakePrivate(), cfg)
        agent.perceive = lambda _public: []
        agent.objectives = lambda _public, _option: {"GATE_CHANGE": 0.9}

        def utility(_public, option):
            if option.gate == "B14":
                return 0.8
            return {"OPT-01": 0.2, "OPT-02": 0.9}.get(option.option_id, 0.1)

        agent.utility = utility

        def check(_public, option):
            return [
                ConstraintCheck(
                    check_id=agent._next_check_id(),
                    constraint_id="GND-GATE-01",
                    owner=AgentRole.GROUND,
                    option_id=option.option_id,
                    passed=option.gate != "A2",
                    source="test",
                )
            ]

        agent.check = check
        return agent

    shortlist = [make_option("OPT-01"), make_option("OPT-02")]
    first = build().turn2(public, shortlist, [])
    second = build().turn2(public, shortlist, [])
    assert first.counter_option is not None
    assert first.counter_option == second.counter_option
    assert first.counter_option.base_option_id == "OPT-01"
    assert first.counter_option.changes == {"gate": "B14"}
    assert {v.option_id: v.reason for v in first.votes if v.vote == "DISAPPROVE"} == {"OPT-01": "GATE_CHANGE"}

    # highest-Borda option approved -> no counter
    no_counter = build().turn2(public, [make_option("OPT-02"), make_option("OPT-01")], [])
    assert no_counter.counter_option is None

    # final ballot never carries a counter
    final = build().turn3(public, shortlist, [])
    assert final.turn == 3 and final.counter_option is None
