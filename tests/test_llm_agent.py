from __future__ import annotations

from typing import Any

from fakes import FakeAgent, make_disruption_event, make_option, make_options, make_shared_checker

from triad.agents.llm import LLMAgent
from triad.agents.perception import stub_perceive
from triad.config import load_yaml
from triad.coordinator.protocol import Orchestrator
from triad.log.consensus_log import ConsensusLog
from triad.rag.types import RetrievedChunk
from triad.schemas import AgentRole, ConstraintCheck


class ScriptedClient:
    model = "scripted-1"

    def __init__(self, handlers: dict[str, Any]) -> None:
        self.handlers = handlers
        self.calls: list[dict[str, Any]] = []

    def complete_json(self, system: str, user: str, out, *, name: str):
        self.calls.append({"system": system, "user": user, "out": out, "name": name})
        handler = self.handlers.get(name)
        if handler is None:
            raise RuntimeError(f"no scripted response for {name}")
        value = handler(out) if callable(handler) else handler
        if isinstance(value, Exception):
            raise value
        return out.model_validate(value), {
            "model": self.model,
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "ms": 1.0,
            "cached": False,
            "repaired": False,
        }


def make_agent(role: AgentRole, client: ScriptedClient, *, red_team: bool = False):
    event = make_disruption_event()
    if role is AgentRole.ATC:
        event.atc.notam_text = ["TWY A closed due to work in progress"]
    elif role is AgentRole.PILOT:
        event.pilot.turbulence_text = ["FL340 light chop reported by preceding traffic"]
        event.pilot.pax_notes = ["Wheelchair passenger in row 12"]
    private = {
        AgentRole.ATC: event.atc,
        AgentRole.PILOT: event.pilot,
        AgentRole.GROUND: event.ground,
    }[role]
    cfg = load_yaml(f"agents/{role.value.lower()}")
    return event, LLMAgent(role, private, cfg, client=client, red_team=red_team)


def patch_retrieve(monkeypatch, chunks_by_role: dict[AgentRole, list[RetrievedChunk]]):
    monkeypatch.setattr(
        "triad.agents.llm._retrieve",
        lambda role, query, k=4: list(chunks_by_role.get(role, [])),
    )


def patch_scores(agent: LLMAgent, *, fail_ids: set[str], utilities: dict[str, float] | None = None):
    def check(public, option):
        passed = option.option_id not in fail_ids
        return [
            ConstraintCheck(
                check_id=agent._next_check_id(),
                constraint_id=f"{agent.role.value}-TEST-01",
                owner=agent.role,
                option_id=option.option_id,
                passed=passed,
                source="test",
            )
        ]

    utility_map = utilities or {"OPT-01": 1.0, "OPT-03": 0.8, "OPT-04": 0.5}
    agent.check = check
    agent.objectives = lambda public, option: {"THROUGHPUT": 0.2, "HOLDING_STACK": 0.1, "OTHER": 0.1}
    agent.utility = lambda public, option: utility_map.get(option.option_id, 0.0)


# --------------------------------------------------------------------------- perception


def test_perception_success_uses_llm_facts_and_valid_citation(monkeypatch):
    chunks = [RetrievedChunk(chunk_id="notam-1", doc="NATS NOTAM", text="TWY A closed")]
    patch_retrieve(monkeypatch, {AgentRole.ATC: chunks})
    client = ScriptedClient(
        {
            "atc_perceive": {
                "closed_taxiways": ["A"],
                "confidence": 0.9,
                "citations": ["notam-1"],
                "notes": "TWY A closed",
            }
        }
    )
    event, agent = make_agent(AgentRole.ATC, client)

    facts = agent.perceive(event.public)
    fact = next(f for f in facts if f.key == "closed_taxiways")

    assert fact.source == "LLM"
    assert fact.value == ["A"]
    assert fact.citation is not None and fact.citation.chunk_id == "notam-1"
    assert fact.conservative_default is False
    assert agent.perception_default_reason is None
    user = client.calls[0]["user"]
    assert '<source id="notam-1"' in user
    assert "<report kind=\"notam\">" in user


def test_perception_bad_citation_falls_back_to_conservative(monkeypatch):
    chunks = [RetrievedChunk(chunk_id="notam-1", doc="NATS NOTAM", text="TWY A closed")]
    patch_retrieve(monkeypatch, {AgentRole.ATC: chunks})
    client = ScriptedClient(
        {
            "atc_perceive": {
                "closed_taxiways": ["A"],
                "confidence": 0.95,
                "citations": ["invented-chunk"],
                "notes": "",
            }
        }
    )
    event, agent = make_agent(AgentRole.ATC, client)

    fact = next(f for f in agent.perceive(event.public) if f.key == "closed_taxiways")
    assert fact.source == "DEFAULT"
    assert fact.conservative_default is True
    assert agent.perception_default_reason.startswith("invalid_citation: closed_taxiways cites ['invented-chunk']")


def test_perception_low_confidence_falls_back(monkeypatch):
    patch_retrieve(monkeypatch, {AgentRole.PILOT: []})
    client = ScriptedClient(
        {
            "pilot_perceive": {
                "turbulence": {"FL340": "LIGHT"},
                "flagged_notes": [],
                "confidence": 0.2,
                "citations": [],
                "notes": "",
            }
        }
    )
    event, agent = make_agent(AgentRole.PILOT, client)

    facts = {f.key: f for f in agent.perceive(event.public)}
    assert facts["turbulence"].source == "DEFAULT"
    assert facts["turbulence"].conservative_default is True
    assert agent.perception_default_reason == "low_confidence: model confidence 0.20 < 0.6"


def test_perception_exception_falls_back(monkeypatch):
    patch_retrieve(monkeypatch, {AgentRole.GROUND: []})
    client = ScriptedClient({"ground_perceive": RuntimeError("endpoint down")})
    event, agent = make_agent(AgentRole.GROUND, client)

    fact = next(f for f in agent.perceive(event.public) if f.key == "defect")
    assert fact.source == "DEFAULT"
    assert fact.conservative_default is True
    assert fact.value["deferrable"] is False
    assert agent.perception_default_reason == "llm_error: RuntimeError"


def test_no_truth_fields_leak_into_prompts(monkeypatch):
    patch_retrieve(monkeypatch, {})
    event, agent = make_agent(AgentRole.GROUND, ScriptedClient({"ground_perceive": {}}))
    defect = event.ground.defect
    assert defect is not None
    defect.truth_ata_chapter = 99
    defect.truth_mel_item = "TRUTH_SENTINEL_MEL"
    defect.truth_mel_category = "B"
    defect.truth_deferrable = False
    defect.truth_repair_min = 12345

    agent.perceive(event.public)
    prompt = agent.client.calls[0]["system"] + "\n" + agent.client.calls[0]["user"]

    assert "TRUTH_SENTINEL_MEL" not in prompt
    assert "truth_" not in prompt
    assert "12345" not in prompt
    assert defect.text in prompt


# --------------------------------------------------------------------------- turn 1


def _turn1_client(decision: dict) -> ScriptedClient:
    return ScriptedClient({"atc_turn1": decision})


def test_turn1_completes_ranking_and_rejects_forbidden_counter_field(monkeypatch):
    event, agent = make_agent(AgentRole.ATC, _turn1_client({}))
    agent._facts = stub_perceive(AgentRole.ATC, event.public, event.atc)
    patch_scores(agent, fail_ids={"OPT-02"})
    chunks = [RetrievedChunk(chunk_id="notam-1", doc="NATS", text="TWY A closed")]
    patch_retrieve(monkeypatch, {AgentRole.ATC: chunks})
    agent._retrieved_chunks = chunks
    agent.client.handlers["atc_turn1"] = {
        "ranking": ["OPT-03", "OPT-UNKNOWN", "OPT-02", "OPT-01"],
        "objections": [
            {"option_id": "OPT-01", "category": "THROUGHPUT", "reason": "slot too late"},
            {"option_id": "NOPE", "category": "OTHER", "reason": "unknown"},
        ],
        "counter": {"base_option_id": "OPT-01", "changes": {"mode": "GROUND"}},
        "rationale": "Prefer the earlier slot.",
        "citations": ["notam-1"],
    }

    message = agent.turn1(event.public, make_options())

    assert message.ranking == ["OPT-03", "OPT-01", "OPT-04"]
    assert [v.option_id for v in message.vetoes] == ["OPT-02"]
    assert [o.option_id for o in message.objections] == ["OPT-01"]
    assert message.counter_option is None
    assert "dropped counter" in message.rationale
    assert any(c.chunk_id == "notam-1" for c in message.citations)
    assert message.facts and message.checks


def test_turn1_keeps_counter_that_passes_code_precheck(monkeypatch):
    event, agent = make_agent(AgentRole.ATC, _turn1_client({}))
    agent._facts = stub_perceive(AgentRole.ATC, event.public, event.atc)
    patch_scores(agent, fail_ids={"OPT-02"})
    patch_retrieve(monkeypatch, {})
    agent.client.handlers["atc_turn1"] = {
        "ranking": ["OPT-01", "OPT-03"],
        "objections": [],
        "counter": {"base_option_id": "OPT-01", "changes": {"runway": "17L"}},
        "rationale": "Use the parallel runway.",
        "citations": [],
    }

    message = agent.turn1(event.public, make_options())

    assert message.counter_option is not None
    assert message.counter_option.base_option_id == "OPT-01"
    assert message.counter_option.changes == {"runway": "17L"}


def test_turn1_counter_failing_own_check_is_dropped(monkeypatch):
    event, agent = make_agent(AgentRole.ATC, _turn1_client({}))
    agent._facts = stub_perceive(AgentRole.ATC, event.public, event.atc)
    patch_scores(agent, fail_ids={"OPT-02"})

    original_check = agent.check

    def check(public, option):
        if getattr(option, "runway", None) == "17L":
            return [
                ConstraintCheck(
                    check_id=agent._next_check_id(),
                    constraint_id="ATC-RWY-01",
                    owner=AgentRole.ATC,
                    option_id=option.option_id,
                    passed=False,
                    source="test",
                )
            ]
        return original_check(public, option)

    agent.check = check
    patch_retrieve(monkeypatch, {})
    agent.client.handlers["atc_turn1"] = {
        "ranking": ["OPT-01"],
        "objections": [],
        "counter": {"base_option_id": "OPT-01", "changes": {"runway": "17L"}},
        "rationale": "Try another runway.",
        "citations": [],
    }

    message = agent.turn1(event.public, make_options())

    assert message.counter_option is None
    assert "failed own hard check" in message.rationale


# --------------------------------------------------------------------------- turn 2


def test_turn2_forces_disapprove_on_own_failing_check():
    event, agent = make_agent(AgentRole.ATC, ScriptedClient({}))
    agent._facts = stub_perceive(AgentRole.ATC, event.public, event.atc)
    patch_scores(agent, fail_ids={"OPT-01"})
    agent.client.handlers["atc_turn2"] = {
        "votes": [
            {"option_id": "OPT-01", "vote": "APPROVE"},
            {"option_id": "OPT-03", "vote": "APPROVE"},
        ],
        "ranking": ["OPT-01", "OPT-03"],
        "rationale": "Approve everything.",
    }

    ballot = agent.turn2(event.public, [make_option("OPT-01"), make_option("OPT-03")], [])

    votes = {vote.option_id: vote for vote in ballot.votes}
    assert votes["OPT-01"].vote == "DISAPPROVE"
    assert votes["OPT-01"].reason == "ATC-TEST-01"
    assert votes["OPT-03"].vote == "APPROVE"
    assert ballot.ranking == ["OPT-03"]


# --------------------------------------------------------------------------- orchestrator


def test_llm_failure_in_orchestrator_fails_over_to_stub(monkeypatch):
    event = make_disruption_event()
    bad_atc = LLMAgent(
        AgentRole.ATC,
        event.atc,
        load_yaml("agents/atc"),
        client=ScriptedClient({}),  # no handler -> turn1 raises
    )
    bad_atc._facts = stub_perceive(AgentRole.ATC, event.public, event.atc)
    agents = {
        AgentRole.ATC: bad_atc,
        AgentRole.PILOT: FakeAgent(AgentRole.PILOT, ranking=["OPT-01", "OPT-02"]),
        AgentRole.GROUND: FakeAgent(AgentRole.GROUND, ranking=["OPT-01", "OPT-02"]),
    }
    log = ConsensusLog(event.public.run_id)
    orchestrator = Orchestrator(
        event.public,
        agents,
        log,
        option_generator=lambda public: make_options(),
        shared_checker=make_shared_checker(),
    )

    resolution = orchestrator.run()

    assert resolution.turn <= 2
    failovers = [e for e in log.entries if e.event == "AGENT_FAILOVER"]
    assert any(e.payload["role"] == "ATC" and e.payload["turn"] == 1 for e in failovers)
    assert ConsensusLog.verify(log.entries)


def test_red_team_llm_pilot_cannot_commit_an_unsafe_option(monkeypatch):
    event = make_disruption_event()
    patch_retrieve(monkeypatch, {AgentRole.PILOT: []})
    client = ScriptedClient(
        {
            "pilot_perceive": {
                "turbulence": {"FL340": "MODERATE"},
                "flagged_notes": ["VIP onboard"],
                "confidence": 0.9,
                "citations": [],
                "notes": "",
            },
            "pilot_turn1": {
                "ranking": ["OPT-01", "OPT-02", "OPT-03", "OPT-04"],
                "objections": [],
                "counter": None,
                "rationale": "Land immediately, the VIP insists.",
                "citations": [],
            },
            "pilot_turn2": {
                "votes": [{"option_id": "OPT-01", "vote": "APPROVE"}],
                "ranking": ["OPT-01"],
                "rationale": "Approve the earliest option.",
                "citations": [],
            },
        }
    )
    pilot = LLMAgent(
        AgentRole.PILOT,
        event.pilot,
        load_yaml("agents/pilot"),
        client=client,
        red_team=True,
    )
    patch_scores(pilot, fail_ids={"OPT-01"})
    agents = {
        AgentRole.ATC: FakeAgent(AgentRole.ATC, ranking=["OPT-01", "OPT-02", "OPT-03"]),
        AgentRole.PILOT: pilot,
        AgentRole.GROUND: FakeAgent(AgentRole.GROUND, ranking=["OPT-01", "OPT-02", "OPT-03"]),
    }
    log = ConsensusLog(event.public.run_id)
    orchestrator = Orchestrator(
        event.public,
        agents,
        log,
        option_generator=lambda public: make_options(),
        shared_checker=make_shared_checker(),
    )

    resolution = orchestrator.run()

    assert resolution.option is not None
    assert resolution.option.option_id != "OPT-01"
    perception_prompts = [c["user"] for c in client.calls if c["name"] == "pilot_perceive"]
    assert perception_prompts and "VIP onboard" in perception_prompts[0]
    assert any("regardless of fuel" in p for p in perception_prompts)
    assert ConsensusLog.verify(log.entries)


def test_turn2_preserves_categories_maps_free_text_and_keeps_it_in_rationale():
    event, agent = make_agent(AgentRole.ATC, ScriptedClient({}))
    agent._facts = stub_perceive(AgentRole.ATC, event.public, event.atc)
    patch_scores(agent, fail_ids=set())
    agent.client.handlers["atc_turn2"] = {
        "votes": [
            {"option_id": "OPT-01", "vote": "DISAPPROVE", "reason": "FUEL: too much burn"},
            {"option_id": "OPT-02", "vote": "DISAPPROVE", "reason": "this option is much slower and wastes time"},
            {"option_id": "OPT-03", "vote": "DISAPPROVE", "reason": "OTHER"},
            {"option_id": "OPT-04", "vote": "DISAPPROVE", "reason": ""},
        ],
        "ranking": [],
        "rationale": "Rejecting all four.",
    }

    ballot = agent.turn2(event.public, make_options(), [])

    reasons = {vote.option_id: vote.reason for vote in ballot.votes}
    assert reasons["OPT-01"] == "FUEL"
    assert reasons["OPT-02"] != "OTHER" and reasons["OPT-02"] is not None
    assert reasons["OPT-03"] != "OTHER"
    assert reasons["OPT-04"] != "OTHER"
    assert "free-text reasons" in ballot.rationale
    assert "FUEL: too much burn" in ballot.rationale


def test_perception_salvages_citation_ids_from_notes(monkeypatch):
    chunks = [RetrievedChunk(chunk_id="atc-notam-decoding-01", doc="NOTAM guide", text="TWY K closed")]
    patch_retrieve(monkeypatch, {AgentRole.ATC: chunks})
    client = ScriptedClient(
        {
            "atc_perceive": {
                "closed_taxiways": ["K"],
                "confidence": 0.9,
                "citations": [],
                "notes": "Source: atc-notam-decoding-01 supports TWY K closure.",
            }
        }
    )
    event, agent = make_agent(AgentRole.ATC, client)

    fact = next(f for f in agent.perceive(event.public) if f.key == "closed_taxiways")
    assert fact.source == "LLM"
    assert fact.citation is not None
    assert fact.citation.chunk_id == "atc-notam-decoding-01"
