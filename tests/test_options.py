"""Option-generator tests on real scenario rows."""

from __future__ import annotations

from triad.agents.base import CheckIdGen
from triad.constraints.shared import shared_checks
from triad.data.enrich import build_event
from triad.data.loader import get_record
from triad.options.generator import generate_options
from triad.schemas import Mode


def _event(mode: Mode):
    if mode == Mode.AIRBORNE:
        return build_event(get_record(293614), seed=0)
    return build_event(get_record(275440), seed=0, defect_id="DEF-HYD-02")


def test_airborne_options_shape_and_shared_checks() -> None:
    event = _event(Mode.AIRBORNE)
    options = generate_options(event.public)

    numbered = [o for o in options if o.option_id.startswith("OPT-") and o.option_id != "OPT-DIV"]
    assert 6 <= len(numbered) <= 12
    assert options[-1].option_id == "OPT-DIV"
    assert options[-1].divert_to in event.public.alternate_candidates
    assert [o.option_id for o in numbered] == [
        f"OPT-{i:02d}" for i in range(1, len(numbered) + 1)
    ]

    next_id = CheckIdGen("OPT")
    for option in options:
        checks = shared_checks(event.public, option, next_id)
        assert all(c.passed for c in checks), (option.option_id, [c.detail for c in checks])

    # Real trade-offs: both holding-only and absorb variants exist.
    assert any(o.holding_min > 0 for o in numbered)
    assert any(o.enroute_absorb_min > 0 for o in numbered)


def test_ground_options_shape_and_shared_checks() -> None:
    event = _event(Mode.GROUND)
    options = generate_options(event.public)
    numbered = [o for o in options if o.option_id != "OPT-DIV"]
    assert 6 <= len(numbered) <= 12
    assert all(o.mode == Mode.GROUND for o in numbered)
    assert all(o.departure_slot is not None for o in numbered)

    next_id = CheckIdGen("OPT")
    for option in options:
        checks = shared_checks(event.public, option, next_id)
        assert all(c.passed for c in checks), (option.option_id, [c.detail for c in checks])


def test_generator_is_deterministic() -> None:
    event = _event(Mode.AIRBORNE)
    first = [o.model_dump_json() for o in generate_options(event.public)]
    second = [o.model_dump_json() for o in generate_options(event.public)]
    assert first == second
