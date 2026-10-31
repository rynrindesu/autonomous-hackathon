"""Negotiable-row catalogue (config/negotiable_rows.yaml) for the UI picker."""

from __future__ import annotations

import random

from triad.config import load_yaml
from triad.data.catalog import catalog_header, evaluate_row_choice, negotiable_rows, row_choice
from triad.data.loader import get_record
from triad.data.scenario import disruption_type_for, is_candidate, mode_for


def test_catalog_loads_with_header() -> None:
    rows = negotiable_rows()
    assert len(rows) >= 100
    header = catalog_header()
    assert header["counts"]["rows"] == len(rows)
    assert len(header["workbook_sha256"]) == 64
    assert header["criteria"]


def test_every_row_is_a_candidate_and_consistent() -> None:
    for choice in negotiable_rows():
        rec = get_record(choice.row_index)
        assert is_candidate(rec), choice.row_index
        assert choice.run_id == rec.run_id
        assert choice.mode == mode_for(rec).value
        assert choice.disruption == disruption_type_for(rec).value
        assert row_choice(choice.row_index) == choice
    assert row_choice(-1) is None


def test_demo_rows_first_and_labels_unique() -> None:
    rows = negotiable_rows()
    scenarios = load_yaml("demo_scenarios")["scenarios"]
    demo_rows = [int(scenarios[name]["row"]) for name in ("scenario_a", "scenario_b", "scenario_c")]
    assert [c.row_index for c in rows[:3]] == demo_rows
    assert [c.demo for c in rows[:3]] == ["A", "B", "C"]
    assert all(c.label.startswith(f"★ Demo {c.demo} · ") for c in rows[:3])
    assert all(c.demo is None and not c.label.startswith("★") for c in rows[3:])
    assert rows[3:] == sorted(rows[3:], key=lambda c: (c.date, c.row_index))

    labels = [c.label for c in rows]
    assert len(labels) == len(set(labels))
    sample = rows[3]
    kind = "Weather" if sample.disruption == "WEATHER" else "Late aircraft"
    assert sample.label == (
        f"{sample.date} · {sample.airline}{sample.flight_number} "
        f"{sample.origin}→{sample.destination} · {kind} +{sample.delay_min} min"
    )


def test_random_catalogue_rows_still_negotiate() -> None:
    rows = negotiable_rows()[3:]
    for choice in random.Random(7).sample(rows, 3):
        fresh, info = evaluate_row_choice(choice.row_index)
        assert info["meets_criteria"], (choice.row_index, info)
        assert fresh.stub_outcome == choice.stub_outcome
        assert fresh.stub_option_id == choice.stub_option_id
        assert fresh.n_safe_options == choice.n_safe_options
        assert fresh.has_valid_counter == choice.has_valid_counter
