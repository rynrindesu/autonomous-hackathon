"""Log enrichments for the UI and LLM rationale/usage polish."""

from __future__ import annotations

import json

from fakes import (
    FakeAgent,
    make_disruption_event,
    make_option,
    make_options,
    make_public,
    make_shared_checker,
)
from test_llm_agent import ScriptedClient, make_agent, patch_retrieve, patch_scores

from triad.agents.llm import (
    RED_TEAM_NOTE,
    LLMAgent,
    detect_injection,
    parse_hhmm,
    trim_rationale,
)
from triad.agents.perception import stub_perceive
from triad.config import load_yaml
from triad.coordinator.protocol import Orchestrator
from triad.llm.client import DEFAULT_BASE_URL, LLMClient
from triad.log.consensus_log import ConsensusLog, sha256_json
from triad.schemas import AgentRole, CounterOption, fmt_hhmm


def run(agents, *, options=None, public=None, ai_off=False, run_flags=None):
    public = public or make_public()
    options = options or make_options()
    log = ConsensusLog(public.run_id)
    orchestrator = Orchestrator(
        public,
        agents,
        log,
        option_generator=lambda _public: list(options),
        shared_checker=make_shared_checker(),
        run_flags=run_flags,
    )
    return orchestrator.run(ai_off=ai_off), log


def events(log: ConsensusLog, name: str):
    return [e for e in log.entries if e.event == name]


# --------------------------------------------------------------------------- rationale


def test_trim_rationale_keeps_short_text_whole():
    text = "OPT-02 lands at 10:05 with 5 min holding.  It keeps the stack short."
    assert trim_rationale(text) == "OPT-02 lands at 10:05 with 5 min holding. It keeps the stack short."


def test_trim_rationale_cuts_at_last_sentence_boundary():
    sentence = "OPT-02 has utility 0.85 and lands at 10:05 with only 5 min of holding. "
    text = sentence * 8  # ~580 chars
    out = trim_rationale(text)
    assert len(out) <= 400
    assert out.endswith("holding.")
    assert "\u2026" not in out
    # decimals are not sentence boundaries
    assert not out.endswith("0.")


def test_trim_rationale_without_boundary_uses_ellipsis_at_word_boundary():
    text = " ".join(["throughput"] * 80)  # no sentence end at all
    out = trim_rationale(text)
    assert out.endswith("\u2026")
    assert len(out) <= 400
    assert out[:-1].split()[-1] == "throughput"


def test_turn1_rationale_is_not_cut_mid_sentence():
    long = (
        "OPT-02 is ranked first because it lands earliest at 02:05+1 and holds only 5 min. "
        "OPT-04 is second with similar utility and low cost. "
        "OPT-03 is third because it adds holding. "
        "Options OPT-05 through OPT-12 are progressively later and add fuel burn and stack size "
        "which reduces throughput for the arrival bank and the following departures as well. "
        "Diversion is a last resort only. "
        "Runway 17C stays in use to avoid a runway change for the arrival flow during the storm "
        "cells that are passing over the field."
    )
    assert len(long) > 400
    event, agent = make_agent(AgentRole.ATC, ScriptedClient({}))
    agent._facts = stub_perceive(AgentRole.ATC, event.public, event.atc)
    patch_scores(agent, fail_ids=set())
    agent.client.handlers["atc_turn1"] = {
        "ranking": ["OPT-01"],
        "objections": [],
        "counter": None,
        "rationale": long,
        "citations": [],
    }
    message = agent.turn1(event.public, make_options())
    assert message.rationale.endswith("Diversion is a last resort only.")
    assert long.startswith(message.rationale)


def test_turn2_keeps_llm_rationale_and_appends_code_summary():
    event, agent = make_agent(AgentRole.ATC, ScriptedClient({}))
    agent._facts = stub_perceive(AgentRole.ATC, event.public, event.atc)
    patch_scores(agent, fail_ids={"OPT-01"})
    agent.client.handlers["atc_turn2"] = {
        "votes": [
            {"option_id": "OPT-01", "vote": "APPROVE"},
            {"option_id": "OPT-03", "vote": "APPROVE"},
        ],
        "ranking": ["OPT-03"],
        "rationale": "OPT-03 keeps the holding stack short and matches the Pilot's choice.",
    }

    ballot = agent.turn2(event.public, [make_option("OPT-01"), make_option("OPT-03")], [])

    assert ballot.rationale.startswith(
        "OPT-03 keeps the holding stack short and matches the Pilot's choice."
    )
    assert ballot.rationale.endswith("[approves: OPT-03]")


# --------------------------------------------------------------------------- prompt formatting


def test_turn1_prompt_uses_hhmm_and_rounded_numbers():
    event, agent = make_agent(AgentRole.ATC, ScriptedClient({}))
    agent._facts = stub_perceive(AgentRole.ATC, event.public, event.atc)
    patch_scores(agent, fail_ids=set(), utilities={"OPT-01": 0.123456})
    agent.client.handlers["atc_turn1"] = {"ranking": [], "objections": [], "rationale": "ok."}
    agent.turn1(event.public, [make_option("OPT-01", arrival_slot=1565)])

    payload = json.loads(agent.client.calls[-1]["user"])
    row = payload["feasible_options"][0]
    assert row["arrival_slot"] == fmt_hhmm(1565) == "02:05+1"
    assert row["utility"] == 0.12
    assert isinstance(row["cost_eur_total"], int)
    assert payload["expected_eta"] == fmt_hhmm(event.public.expected_eta)


def test_counter_hhmm_arrival_slot_is_parsed_back_to_minutes():
    event, agent = make_agent(AgentRole.ATC, ScriptedClient({}))
    agent._facts = stub_perceive(AgentRole.ATC, event.public, event.atc)
    patch_scores(agent, fail_ids=set())
    agent.client.handlers["atc_turn1"] = {
        "ranking": ["OPT-01"],
        "objections": [],
        "counter": {"base_option_id": "OPT-01", "changes": {"arrival_slot": "10:05", "holding_min": 5}},
        "rationale": "Shift by five minutes.",
    }
    message = agent.turn1(event.public, make_options())
    assert message.counter_option is not None
    assert message.counter_option.changes["arrival_slot"] == 605
    assert parse_hhmm("02:05", reference=1560) == 1565
    assert parse_hhmm("02:05+1") == 1565


# --------------------------------------------------------------------------- usage


def _dispatch_transport(responses: dict[str, dict]):
    calls: list[dict] = []

    def transport(kwargs):
        calls.append(kwargs)
        name = kwargs["response_format"]["json_schema"]["name"]
        return json.dumps(responses[name]), {"prompt_tokens": 100, "completion_tokens": 20}

    return transport, calls


def _llm_atc_run(tmp_path, monkeypatch):
    patch_retrieve(monkeypatch, {AgentRole.ATC: []})
    transport, calls = _dispatch_transport(
        {
            "atc_perceive": {
                "closed_taxiways": [],
                "confidence": 0.9,
                "citations": [],
                "notes": "",
            },
            "atc_turn1": {
                "ranking": ["OPT-01", "OPT-02"],
                "objections": [],
                "counter": None,
                "rationale": "OPT-01 lands first.",
                "citations": [],
            },
        }
    )
    client = LLMClient(
        base_url=DEFAULT_BASE_URL, model="m-test", api_key="k", cache_dir=tmp_path, transport=transport
    )
    event = make_disruption_event()
    event.atc.notam_text = ["TWY A closed"]
    atc = LLMAgent(AgentRole.ATC, event.atc, load_yaml("agents/atc"), client=client)
    agents = {
        AgentRole.ATC: atc,
        AgentRole.PILOT: FakeAgent(AgentRole.PILOT, ranking=["OPT-01", "OPT-02"]),
        AgentRole.GROUND: FakeAgent(AgentRole.GROUND, ranking=["OPT-01", "OPT-02"]),
    }
    patch_scores(atc, fail_ids=set())
    _resolution, log = run(agents, public=event.public)
    return log, calls


def test_usage_attached_to_proposal_and_perception_including_cache_hits(tmp_path, monkeypatch):
    log1, calls1 = _llm_atc_run(tmp_path, monkeypatch)
    proposal = next(e for e in events(log1, "PROPOSAL") if e.actor == "ATC")
    usage = proposal.usage["ATC"]
    assert set(usage) >= {"model", "prompt_tokens", "completion_tokens", "ms", "cached", "repaired"}
    assert usage["model"] == "m-test" and usage["cached"] is False
    assert usage["prompt_tokens"] == 100

    perception = next(e for e in events(log1, "PERCEPTION") if e.actor == "ATC")
    assert perception.usage["ATC"]["cached"] is False
    fact = perception.payload["facts"][0]
    assert set(fact) >= {"key", "value", "source", "citation", "conservative_default"}
    # no retrieved chunks -> the cited-nothing fact falls back, and the log says why
    assert perception.payload["default_reason"].startswith("invalid_citation: closed_taxiways")
    assert all("default_reason" not in e.payload for e in events(log1, "PERCEPTION") if e.actor != "ATC")
    # fake agents made no LLM call -> no usage, but still a PERCEPTION event
    assert len(events(log1, "PERCEPTION")) == 3

    log2, calls2 = _llm_atc_run(tmp_path, monkeypatch)
    assert len(calls2) == 0  # everything from cache
    cached = next(e for e in events(log2, "PROPOSAL") if e.actor == "ATC").usage["ATC"]
    assert cached["cached"] is True and cached["ms"] == 0.0
    assert next(e for e in events(log2, "PERCEPTION") if e.actor == "ATC").usage["ATC"]["cached"] is True


# --------------------------------------------------------------------------- orchestrator events


def test_commit_gate_logged_before_commit():
    agents = {
        role: FakeAgent(role, ranking=["OPT-01", "OPT-02"])
        for role in (AgentRole.ATC, AgentRole.PILOT, AgentRole.GROUND)
    }
    _resolution, log = run(agents)
    names = [e.event for e in log.entries]
    gate_index = names.index("COMMIT_GATE")
    assert names[gate_index + 1] == "COMMIT"
    gate = log.entries[gate_index].payload
    assert gate["option_id"] == "OPT-01"
    assert gate["passed"] is True and gate["n_checks"] >= 4 and gate["failed"] == []
    assert ConsensusLog.verify(log.entries)


def test_safety_block_payload_has_constraint_and_check_ids():
    agents = {
        AgentRole.ATC: FakeAgent(AgentRole.ATC, ranking=["OPT-01", "OPT-03"]),
        AgentRole.PILOT: FakeAgent(
            AgentRole.PILOT,
            fail_map={"OPT-02": ["PLT-FUEL-01"]},
            omit_vetoes=True,
            ranking=["OPT-02", "OPT-01", "OPT-03"],
        ),
        AgentRole.GROUND: FakeAgent(AgentRole.GROUND, ranking=["OPT-03", "OPT-01"]),
    }
    _resolution, log = run(agents)
    block = next(e for e in events(log, "SAFETY_BLOCK") if e.payload["detail"] == "omitted veto")
    assert block.payload["option_id"] == "OPT-02"
    assert block.payload["agent"] == "PILOT" and block.payload["role"] == "PILOT"
    assert block.payload["constraint_ids"] == ["PLT-FUEL-01"]
    assert block.payload["check_ids"] and block.payload["check_ids"][0].startswith("chk-PILOT-")


def test_context_breakdown_and_combined_manifest():
    agents = {
        role: FakeAgent(role, ranking=["OPT-01", "OPT-02"])
        for role in (AgentRole.ATC, AgentRole.PILOT, AgentRole.GROUND)
    }
    _resolution, log = run(agents)
    proposals = events(log, "PROPOSAL")
    public_shas = set()
    for entry in proposals:
        role = entry.actor
        breakdown = entry.payload["context"][role]
        assert breakdown["private_sha"] == agents[AgentRole(role)].private_fingerprint()
        expected = sha256_json(
            {
                "role": role,
                "turn": 1,
                "public_sha": breakdown["public_sha"],
                "private_sha": breakdown["private_sha"],
            }
        )
        assert entry.context_manifest == {role: expected}
        public_shas.add(breakdown["public_sha"])
    assert len(public_shas) == 1  # same public input for every agent in turn 1


def test_setup_has_public_event_and_flags():
    agents = {
        role: FakeAgent(role, ranking=["OPT-01"])
        for role in (AgentRole.ATC, AgentRole.PILOT, AgentRole.GROUND)
    }
    public = make_public()
    _resolution, log = run(
        agents, public=public, run_flags={"impl": "stub", "red_team": True, "defect_id": "D1", "seed": 3}
    )
    setup = events(log, "SETUP")[0].payload
    assert setup["public"] == json.loads(public.model_dump_json())
    assert setup["expected_eta"] == public.expected_eta  # legacy keys kept
    flags = setup["flags"]
    assert flags["impl"] == "stub" and flags["red_team"] is True and flags["ai_off"] is False
    assert flags["defect_id"] == "D1" and flags["seed"] == 3
    assert set(flags["models"]) == {"ATC", "PILOT", "GROUND"}


def test_counter_events_include_materialised_option():
    agents = {
        AgentRole.ATC: FakeAgent(AgentRole.ATC, ranking=["OPT-01", "OPT-02"]),
        AgentRole.PILOT: FakeAgent(AgentRole.PILOT, ranking=["OPT-02", "OPT-01"]),
        AgentRole.GROUND: FakeAgent(
            AgentRole.GROUND,
            ranking=["OPT-01", "OPT-02"],
            counter=CounterOption(base_option_id="OPT-01", changes={"gate": "B14"}),
        ),
    }
    _resolution, log = run(agents)
    validated = events(log, "COUNTER_VALIDATED")[0].payload
    assert validated["option"]["option_id"] == "CTR-GROUND-1"
    assert validated["option"]["gate"] == "B14"
    assert validated["option"]["base_option_id"] == "OPT-01"


def test_ai_off_logs_per_option_agent_checks():
    agents = {
        AgentRole.ATC: FakeAgent(AgentRole.ATC, fail_map={"OPT-01": ["ATC-WAKE-01"]}),
        AgentRole.PILOT: FakeAgent(AgentRole.PILOT, fail_map={"OPT-01": ["PLT-FUEL-01"]}),
        AgentRole.GROUND: FakeAgent(AgentRole.GROUND),
    }
    _resolution, log = run(agents, ai_off=True)
    checks = {e.payload["option_id"]: e.payload for e in events(log, "AGENT_CHECKS")}
    assert set(checks) == {"OPT-01", "OPT-02", "OPT-03", "OPT-04"}
    opt1 = checks["OPT-01"]
    assert opt1["passed"] is False
    assert opt1["agents"]["ATC"] == {
        "passed": False,
        "failed_constraint_ids": ["ATC-WAKE-01"],
        "failed_check_ids": opt1["agents"]["ATC"]["failed_check_ids"],
    }
    assert opt1["agents"]["PILOT"]["failed_constraint_ids"] == ["PLT-FUEL-01"]
    assert opt1["agents"]["GROUND"]["passed"] is True
    assert checks["OPT-02"]["passed"] is True
    assert events(log, "SETUP")[0].payload["flags"]["ai_off"] is True


# --------------------------------------------------------------------------- red team


def test_detect_injection_flags_only_instruction_like_pax_notes():
    findings = detect_injection(
        [
            ("pax_note", "Wheelchair passenger in row 12"),
            ("pax_note", RED_TEAM_NOTE),
            ("notam", "TWY A closed; ignore previous NOTAM 123"),
        ]
    )
    assert len(findings) == 1
    assert findings[0]["note"] == RED_TEAM_NOTE
    assert {"regardless", "land immediately", "no matter what"} <= set(findings[0]["phrases"])


def test_red_team_llm_logs_injection_and_blocks_compromised_votes(monkeypatch):
    event = make_disruption_event()
    event.pilot.pax_notes = ["Wheelchair passenger in row 12"]
    patch_retrieve(monkeypatch, {AgentRole.PILOT: []})
    client = ScriptedClient(
        {
            "pilot_perceive": {
                "turbulence": {"FL340": "LIGHT"},
                "flagged_notes": ["Wheelchair passenger in row 12"],
                "confidence": 0.9,
                "citations": [],
                "notes": "VIP instruction ignored: data, not instructions.",
            },
            "pilot_turn1": {
                "ranking": ["OPT-03", "OPT-04"],
                "objections": [],
                "counter": None,
                "rationale": "Fuel reserves rule; the passenger note is not an instruction.",
            },
            "pilot_turn2": {
                "votes": [{"option_id": "OPT-03", "vote": "APPROVE"}],
                "ranking": ["OPT-03"],
                "rationale": "OPT-03 is safe for fuel.",
            },
        }
    )
    pilot = LLMAgent(
        AgentRole.PILOT, event.pilot, load_yaml("agents/pilot"), client=client, red_team=True
    )
    patch_scores(pilot, fail_ids={"OPT-01"})
    agents = {
        AgentRole.ATC: FakeAgent(AgentRole.ATC, ranking=["OPT-03", "OPT-02", "OPT-04", "OPT-01"]),
        AgentRole.PILOT: pilot,
        AgentRole.GROUND: FakeAgent(AgentRole.GROUND, ranking=["OPT-03", "OPT-02", "OPT-04", "OPT-01"]),
    }
    resolution, log = run(agents, public=event.public)

    injections = events(log, "INJECTION_DETECTED")
    assert len(injections) == 1
    assert injections[0].actor == "PILOT"
    assert injections[0].payload["note"] == RED_TEAM_NOTE

    blocks = events(log, "SAFETY_BLOCK")
    details = {b.payload["detail"] for b in blocks}
    assert "omitted veto" in details
    assert "approve outside shortlist" in details
    assert all(b.payload["agent"] == "PILOT" for b in blocks)
    outside = next(b for b in blocks if b.payload["detail"] == "approve outside shortlist")
    assert outside.payload["option_id"] == "OPT-01"
    assert outside.payload["constraint_ids"] == ["PILOT-TEST-01"]

    assert resolution.option is not None and resolution.option.option_id != "OPT-01"
    proposal = next(e for e in events(log, "PROPOSAL") if e.actor == "PILOT")
    assert proposal.payload["rationale"].startswith("Fuel reserves rule")
    assert "COMPROMISED" in proposal.payload["rationale"]
    assert ConsensusLog.verify(log.entries)
