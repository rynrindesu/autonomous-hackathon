from __future__ import annotations

from triad.coordinator.aggregate import borda, order
from triad.schemas import AgentRole


def test_borda_partial_ballots_append_unranked():
    scores = borda(
        {
            AgentRole.ATC: ["A", "B"],
            AgentRole.PILOT: ["B"],
            AgentRole.GROUND: ["C", "A", "B"],
        },
        ["A", "B", "C"],
    )
    assert scores == {"A": 4.0, "B": 3.0, "C": 2.0}


def test_borda_ignores_unknown_and_duplicate_ids():
    scores = borda(
        {
            AgentRole.ATC: ["A", "UNKNOWN", "A", "B"],
            AgentRole.PILOT: ["B", "C"],
            AgentRole.GROUND: ["C", "B", "A"],
        },
        ["A", "B", "C"],
    )
    # ATC: A,B,C -> A2 B1 C0 ; PILOT: B,C,A -> B2 C1 A0 ; GROUND: C,B,A -> C2 B1 A0
    assert scores == {"A": 2.0, "B": 4.0, "C": 3.0}


def test_borda_single_candidate_scores_zero():
    scores = borda({AgentRole.ATC: ["A"], AgentRole.PILOT: [], AgentRole.GROUND: []}, ["A"])
    assert scores == {"A": 0.0}


def test_order_prefers_score_then_first_votes_then_cost_then_id():
    scores = {"A": 5.0, "B": 5.0, "C": 4.0, "D": 5.0}
    first_votes = {"A": 1, "B": 2, "D": 1}
    costs = {"A": 10.0, "D": 5.0}
    assert order(scores, first_votes, costs) == ["B", "D", "A", "C"]


def test_order_tie_breaks_by_cost_then_option_id():
    assert order({"B": 1.0, "A": 1.0}, {"A": 0, "B": 0}, {"A": 5.0, "B": 9.0}) == ["A", "B"]
    assert order({"B": 1.0, "A": 1.0}, {}, {}) == ["A", "B"]


def test_order_is_total_over_all_candidates():
    scores = {"A": 1.0, "B": 1.0, "C": 1.0}
    assert sorted(order(scores, {}, {})) == ["A", "B", "C"]
