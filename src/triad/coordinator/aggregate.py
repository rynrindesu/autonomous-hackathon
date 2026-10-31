"""Borda count + deterministic ordering (PLAN §5)."""

from __future__ import annotations

from collections.abc import Mapping

from triad.schemas import AgentRole


def borda(
    rankings: Mapping[AgentRole, list[str]],
    candidates: list[str],
) -> dict[str, float]:
    """Equal-weight Borda count.

    Each agent's ballot is filtered to ``candidates``; any candidate it did not
    rank is appended in ``option_id`` order, so every candidate receives points
    (``n-1`` for first ... ``0`` for last).  Partial ballots are therefore safe.
    """
    ids = list(candidates)
    n = len(ids)
    scores = {cid: 0.0 for cid in ids}
    if n == 0:
        return scores
    candidate_set = set(ids)
    for ranking in rankings.values():
        seen: list[str] = []
        used: set[str] = set()
        for cid in ranking:
            if cid in candidate_set and cid not in used:
                seen.append(cid)
                used.add(cid)
        for cid in sorted(candidate_set - used):
            seen.append(cid)
        for index, cid in enumerate(seen):
            scores[cid] += float(n - 1 - index)
    return scores


def order(
    scores: Mapping[str, float],
    first_votes: Mapping[str, int],
    tie_cost: Mapping[str, float],
) -> list[str]:
    """Order options: score desc -> first-choice votes desc -> cost asc -> id asc."""
    return sorted(
        scores,
        key=lambda cid: (
            -float(scores.get(cid, 0.0)),
            -int(first_votes.get(cid, 0)),
            float(tie_cost.get(cid, float("inf"))),
            cid,
        ),
    )
