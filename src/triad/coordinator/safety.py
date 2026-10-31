"""The last line of defence: re-run every check before any commit."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from triad.schemas import AgentRole, CandidateOption, ConstraintCheck, PublicEvent


class UnsafeCommitError(Exception):
    """Raised when a commit would violate a hard constraint."""

    def __init__(self, message: str, failed: list[ConstraintCheck] | None = None) -> None:
        super().__init__(message)
        self.failed = failed or []


def assert_commit_safe(
    public: PublicEvent,
    option: CandidateOption,
    agents: Mapping[AgentRole, object],
    shared_checker: Callable[[PublicEvent, CandidateOption, Callable[[], str]], list[ConstraintCheck]],
    next_id: Callable[[], str],
) -> list[ConstraintCheck]:
    """Run shared checks + every agent's own checker; raise if anything hard fails."""
    checks: list[ConstraintCheck] = list(shared_checker(public, option, next_id))
    for role in (AgentRole.ATC, AgentRole.PILOT, AgentRole.GROUND):
        agent = agents[role]
        checks.extend(agent.check(public, option))  # type: ignore[attr-defined]
    failed = [c for c in checks if c.hard and not c.passed]
    if failed:
        ids = ", ".join(f"{c.owner}:{c.constraint_id}({c.option_id})" for c in failed)
        raise UnsafeCommitError(f"unsafe commit for {option.option_id}: {ids}", failed)
    return checks
