"""World smoke test: 20 real candidate rows build, generate and check cleanly."""

from __future__ import annotations

from triad.agents.base import CheckIdGen
from triad.agents.perception import conservative_facts, stub_perceive
from triad.agents.scoring import cost_eur, objectives
from triad.constraints.registry import check_owned
from triad.constraints.shared import shared_checks
from triad.data.enrich import build_event
from triad.data.loader import get_record
from triad.options.generator import generate_options
from triad.picker import _candidate_rows
from triad.schemas import AgentRole


def test_twenty_candidate_rows_run_cleanly() -> None:
    rows = _candidate_rows(20, seed=42)
    assert len(rows) == 20

    for row in rows:
        rec = get_record(row)
        event = build_event(rec, seed=0)
        options = generate_options(event.public)
        assert 7 <= len(options) <= 13

        for option in options:
            shared = shared_checks(event.public, option, CheckIdGen("SMOKE-SHARED"))
            assert {c.owner for c in shared} == {"SHARED"}

        for role, private in (
            (AgentRole.ATC, event.atc),
            (AgentRole.PILOT, event.pilot),
            (AgentRole.GROUND, event.ground),
        ):
            facts = {f.key: f for f in stub_perceive(role, event.public, private)}
            next_id = CheckIdGen(f"SMOKE-{role.value}")
            for option in options:
                checks = check_owned(role, event.public, private, facts, option, next_id)
                assert checks, (row, role, option.option_id)
                for check in checks:
                    assert check.option_id == option.option_id
                    assert check.source
                    assert check.value is not None or check.limit is not None
                objectives(role, event.public, private, facts, option)
                cost_eur(role, event.public, private, facts, option)

            conservative = {f.key: f for f in conservative_facts(role, event.public, private)}
            assert conservative
            for option in options[:3]:
                check_owned(role, event.public, private, conservative, option, next_id)
