from __future__ import annotations

import pytest

from fakes import (
    FakeAgent,
    make_option,
    make_public,
    make_shared_checker,
)
from triad.agents.base import CheckIdGen
from triad.coordinator.safety import UnsafeCommitError, assert_commit_safe
from triad.schemas import AgentRole


def _agents(**kwargs):
    return {
        AgentRole.ATC: FakeAgent(AgentRole.ATC, **kwargs.get("atc", {})),
        AgentRole.PILOT: FakeAgent(AgentRole.PILOT, **kwargs.get("pilot", {})),
        AgentRole.GROUND: FakeAgent(AgentRole.GROUND, **kwargs.get("ground", {})),
    }


def test_assert_commit_safe_passes_and_returns_every_check():
    public = make_public()
    option = make_option("OPT-01")
    agents = _agents()
    checks = assert_commit_safe(
        public, option, agents, make_shared_checker(), CheckIdGen("SHR")
    )
    assert len(checks) == 4  # shared + three agents
    assert all(c.passed for c in checks)


def test_assert_commit_safe_raises_on_shared_failure():
    public = make_public()
    option = make_option("OPT-01")
    with pytest.raises(UnsafeCommitError) as excinfo:
        assert_commit_safe(
            public,
            option,
            _agents(),
            make_shared_checker({"OPT-01"}),
            CheckIdGen("SHR"),
        )
    assert excinfo.value.failed
    assert excinfo.value.failed[0].constraint_id == "SHR-FAKE-01"


def test_assert_commit_safe_raises_on_agent_failure():
    public = make_public()
    option = make_option("OPT-01")
    agents = _agents(pilot={"fail_map": {"OPT-01": ["PLT-FUEL-01"]}})
    with pytest.raises(UnsafeCommitError) as excinfo:
        assert_commit_safe(public, option, agents, make_shared_checker(), CheckIdGen("SHR"))
    assert any(c.constraint_id == "PLT-FUEL-01" for c in excinfo.value.failed)
