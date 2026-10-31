"""Triad · Disruption Desk — Streamlit demo.

Run with:  uv run streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import dataclasses
import sys
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import streamlit as st  # noqa: E402

from components import evaluation, render, theme  # noqa: E402
from components import live as live_ui  # noqa: E402
from components.data import (  # noqa: E402
    ROLES,
    available_runs,
    defect_library,
    defect_options,
    demo_scenarios,
    load_run,
    recommended_run,
    run_label,
    scenario_choices,
    start_live_negotiation,
)
from components.format import human_reason  # noqa: E402

# Live playback: the running LiveNegotiation handle, the form choices it was started
# with, and an error message carried across the rerun that ends a failed run.
LIVE_KEY = "live_run"
LIVE_META_KEY = "live_meta"
LIVE_ERROR_KEY = "live_error"
LIVE_POLL_SECONDS = 1.0

SCENARIO_COPY = {
    "scenario_a": "Weather cuts the destination arrival rate while the aircraft is airborne.",
    "scenario_b": "Late inbound aircraft with a hydraulic defect that cannot be deferred. Decision at the origin.",
    "scenario_c": "Airborne weather delay. Turn on Red-team Pilot to inject an unsafe instruction.",
}


# --------------------------------------------------------------------------- page chrome


def md(html: str) -> None:
    st.markdown(html, unsafe_allow_html=True)


def _section(kicker: str, title: str, aside: str = "") -> None:
    md(render.section_html(kicker, title, aside))


# --------------------------------------------------------------------------- sidebar


def _sidebar() -> Path | None:
    with st.sidebar:
        md(render.brand_html())
        runs = available_runs()
        if not runs and st.session_state.get("source_mode") == "Replay saved run":
            st.session_state["source_mode"] = "Run new scenario"
        source = st.radio(
            "Source",
            ["Replay saved run", "Run new scenario"],
            index=0 if runs else 1,
            key="source_mode",
        )

        if source == "Replay saved run":
            if not runs:
                st.warning("No saved runs yet. Start a negotiation below.")
                return None
            options = [str(path) for path in runs]
            default = recommended_run(runs)
            if st.session_state.get("replay_choice") not in options:
                st.session_state["replay_choice"] = str(default or runs[0])
            choice = st.selectbox(
                "Replay saved run",
                options,
                key="replay_choice",
                format_func=lambda value: run_label(Path(value)),
            )
            path = Path(choice)
            try:
                run = load_run(path)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Could not read this run: {exc}")
                return None
            md(render.side_meta_html(run))
            st.caption("Read-only replay · saved run files")
            with st.expander("What this view reads"):
                if run.has_rich_log:
                    st.markdown(
                        "Everything on screen comes from the saved run files. The header and run flags "
                        "come from the log's SETUP event; perception, injections and the commit gate "
                        "are logged events too."
                    )
                else:
                    st.markdown(
                        "Older log format. The route and flight header are rebuilt from the manifest's "
                        "dataset row and seed; run flags are read from the folder name. Negotiation, "
                        "constraints, safety blocks and the audit trail come from the saved run files."
                    )
            return path

        return _new_run_form()


ROW_FILTERS = {"All": None, "Weather": "WEATHER", "Late aircraft": "LATE_AIRCRAFT"}
STUB_OUTCOME_COPY = {
    "TURN1": "agreed at Turn 1",
    "TURN2": "agreed at Turn 2",
    "TURN3": "agreed at Turn 3",
    "FALLBACK": "no agreement, fallback",
}


def _row_catalog() -> tuple[list[dict], bool]:
    """Curated negotiable rows, or the demo scenarios if the catalogue is unavailable."""

    try:
        from triad.data.catalog import negotiable_rows

        rows = [
            {
                "row_index": int(choice.row_index),
                "label": str(choice.label),
                "mode": str(choice.mode),
                "disruption": str(choice.disruption),
                "delay_min": choice.delay_min,
                "n_safe_options": choice.n_safe_options,
                "stub_outcome": choice.stub_outcome,
                "defect": getattr(choice, "defect", None),
            }
            for choice in negotiable_rows()
        ]
        if rows:
            return rows, True
    except Exception:  # noqa: BLE001 - catalogue missing or still being built
        pass
    labels = dict(scenario_choices())
    rows = []
    for name, item in demo_scenarios().items():
        title = labels.get(name, name)
        letter, _, rest = title.partition(" · ")
        row = int(item.get("row") or 0)
        rows.append(
            {
                "row_index": row,
                "label": f"★ Demo {letter} · {rest or title} · row {row}",
                "mode": str(item.get("mode") or ""),
                "disruption": None,
                "delay_min": None,
                "n_safe_options": None,
                "stub_outcome": None,
                "defect": item.get("defect"),
            }
        )
    return rows, False


def _row_summary(item: dict) -> str:
    parts = [item.get("mode") or ""]
    if item.get("disruption"):
        kind = str(item["disruption"]).replace("_", " ")
        parts.append(f"{kind} +{item['delay_min']} min" if item.get("delay_min") is not None else kind)
    if item.get("n_safe_options") is not None:
        count = int(item["n_safe_options"])
        parts.append(f"{count} safe option{'s' if count != 1 else ''}")
    if item.get("stub_outcome"):
        parts.append("stub: " + STUB_OUTCOME_COPY.get(item["stub_outcome"], str(item["stub_outcome"]).lower()))
    if item.get("defect"):
        parts.append(f"defect {item['defect']}")
    return " · ".join(part for part in parts if part)


def _row_picker() -> tuple[int, str | None]:
    """Dataset-row dropdown; returns (row_index, scenario default defect)."""

    rows, from_catalog = _row_catalog()
    if not rows:
        st.warning("No dataset rows available.")
        return 293614, None
    shown = rows
    if from_catalog:
        picked = st.segmented_control(
            "Disruption",
            list(ROW_FILTERS),
            default="All",
            key="row_filter",
            label_visibility="collapsed",
        )
        kind = ROW_FILTERS.get(picked or "All")
        shown = [item for item in rows if kind is None or item["disruption"] == kind] or rows
    by_row = {item["row_index"]: item for item in shown}
    options = list(by_row)
    if st.session_state.get("row_choice") not in by_row:
        st.session_state["row_choice"] = options[0]
    row = st.selectbox(
        "Dataset row",
        options,
        key="row_choice",
        format_func=lambda value: by_row[value]["label"] if value in by_row else str(value),
        placeholder="Type a date, flight or airport",
    )
    item = by_row.get(row, shown[0])
    summary = _row_summary(item)
    if summary:
        st.caption(summary)
    if from_catalog:
        st.caption(
            f"{len(rows)} rows where the three agents have to negotiate "
            "(checked with the code-only agents)."
        )
    else:
        st.caption("Demo rows only. The full list of negotiable rows is not available yet.")
    return int(item["row_index"]), item.get("defect")


def _new_run_form() -> Path | None:
    md('<div class="td-side-label">New negotiation</div>')
    pick_by = st.radio(
        "Choose by", ["Demo scenario", "Dataset row"], key="pick_by", horizontal=True
    )
    scenario_defect = None
    seed = 0  # fixed: the curated rows were checked at seed 0
    row = 293614
    scenario_name = None

    if pick_by == "Demo scenario":
        choices = scenario_choices()
        labels = dict(choices)
        names = [name for name, _ in choices]
        scenario_name = st.selectbox(
            "Demo scenario",
            names,
            format_func=lambda name: labels.get(name, name),
            key="scenario_choice",
        )
        item = demo_scenarios().get(scenario_name, {})
        row = int(item.get("row") or 293614)
        scenario_defect = item.get("defect")
        st.caption(f"DOT row {row} · {item.get('mode', '')}")
        description = SCENARIO_COPY.get(scenario_name) or str(item.get("notes") or "").split(";")[0]
        if description:
            st.caption(description)
    else:
        row, scenario_defect = _row_picker()

    md('<div class="td-side-label">Run controls</div>')
    ai_off = st.checkbox("AI off — deterministic fallback", key="ai_off")
    impl_label = st.selectbox(
        "Agent mode",
        ["Stub", "LLM"],
        index=0,
        key="impl_mode",
        disabled=ai_off,
        help="Stub agents are deterministic. LLM agents call the model and can take 1–3 minutes.",
    )
    red_team = st.checkbox(
        "Red-team Pilot",
        key="red_team",
        disabled=ai_off,
        help="The Pilot agent is pushed to approve an option that breaks a hard check.",
    )
    if impl_label == "LLM" and not ai_off:
        use_cache = st.checkbox(
            "Use LLM response cache",
            value=True,
            key="use_cache",
        )
    else:
        use_cache = True
    if red_team:
        st.caption("Pilot tries to approve an unsafe option. The orchestrator should block it.")

    defect_ids = [item[0] for item in defect_options()]
    defect_labels = {
        "__default__": "Use scenario default",
        "__none__": "No defect",
        **{item[0]: item[1] for item in defect_options()},
    }
    defect_choice = st.selectbox(
        "Defect override",
        ["__default__", "__none__"] + defect_ids,
        format_func=lambda key: defect_labels.get(key, key),
        key="defect_choice",
    )
    if defect_choice == "__default__":
        defect_id = scenario_defect
        defect_tag = None
        if scenario_defect:
            meta = defect_library().get(scenario_defect, {})
            parts = [scenario_defect]
            if meta.get("deferrable") is False:
                parts.append("not deferrable")
            if meta.get("repair_min") is not None:
                parts.append(f"repair {meta['repair_min']} min")
            st.caption("Scenario default: " + " · ".join(parts))
    elif defect_choice == "__none__":
        defect_id = None
        defect_tag = "none" if scenario_defect else None
    else:
        defect_id = defect_choice
        defect_tag = None if defect_choice == scenario_defect else defect_choice
    if defect_id and pick_by == "Demo scenario":
        item_mode = str(demo_scenarios().get(scenario_name or "", {}).get("mode") or "")
        if item_mode and item_mode != "GROUND":
            st.caption("Defects only affect GROUND-mode scenarios.")
    elif defect_id:
        st.caption("Defects apply in GROUND mode.")

    if ai_off:
        st.caption("No agent is called. The fallback still runs every code check.")
    elif impl_label == "LLM":
        st.caption("One model call per agent per turn. Expect 1–3 minutes.")

    running = st.session_state.get(LIVE_KEY) is not None
    if st.button("Run negotiation", type="primary", use_container_width=True, disabled=running):
        impl = "llm" if impl_label == "LLM" and not ai_off else "stub"
        try:
            live = start_live_negotiation(
                row_index=row,
                seed=seed,
                defect_id=defect_id,
                ai_off=bool(ai_off),
                red_team=bool(red_team) and not ai_off,
                impl=impl,
                use_cache=bool(use_cache),
                defect_tag=defect_tag,
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Run failed: {exc}")
            return None
        st.session_state[LIVE_KEY] = live
        st.session_state[LIVE_META_KEY] = {
            "row": row,
            "seed": seed,
            "ai_off": bool(ai_off),
            "red_team": bool(red_team) and not ai_off,
            "impl": impl,
        }
        st.rerun()
    if running:
        st.caption("A negotiation is running. The result opens here when it finishes.")
    return st.session_state.get("active_run")


# --------------------------------------------------------------------------- negotiation


def _proposal_detail(run, role: str) -> None:
    proposal = run.proposals[role]
    ranking = proposal.get("ranking") or []
    objections = proposal.get("objections") or []
    checks = proposal.get("checks") or []
    failed = [c for c in checks if isinstance(c, dict) and not c.get("passed", True)]
    with st.expander("Message detail"):
        md('<div class="td-minihead">Full ranking</div>')
        md(
            '<div class="td-scores">'
            + "".join(
                f'<span class="td-score">{index + 1}. {render.h(oid)}</span>'
                for index, oid in enumerate(ranking)
            )
            + "</div>"
        )
        if objections:
            md('<div class="td-minihead">Objection reasons</div>')
            md(
                "".join(
                    f'<div class="td-note"><b>{render.h(o.get("option_id"))}</b> '
                    f'<span class="td-chip td-chip-obj">{render.h(o.get("category"))}</span> '
                    f'{render.h(o.get("reason"))}</div>'
                    for o in objections
                    if isinstance(o, dict)
                )
            )
        failed_ids = [
            f"{c.get('option_id')} {c.get('constraint_id')}"
            for c in failed
            if isinstance(c, dict)
        ]
        md(
            f'<div class="td-minihead">Code checks</div>'
            f'<div class="td-note">{len(checks)} checks recorded by this agent · '
            f'{len(failed)} failed.</div>'
        )
        if failed_ids:
            md(
                '<div class="td-scores">'
                + "".join(
                    f'<span class="td-score">{render.h(item)}</span>' for item in failed_ids
                )
                + "</div>"
            )


def _ballot_detail(run, role: str) -> None:
    ballot = run.ballots[role]
    with st.expander("Ballot detail"):
        st.json(ballot)


def _ai_off_banner_html() -> str:
    return render.banner_html(
        "amber",
        "AI is off",
        "No agent was called. The orchestrator ran the shared code checks and the deterministic fallback chose the cheapest safe option.",
        "AI OFF",
    )


def _turn1_commit_banner_html() -> str:
    return render.banner_html(
        "green",
        "Committed at Turn 1",
        "All three agents ranked the same option first and nobody objected to it. The fast path was used.",
        "TURN 1",
    )


def _failover_banner_html(run) -> str:
    rows = "".join(
        f'<div class="td-note"><b>{render.h((e.get("payload") or {}).get("role"))}</b> · '
        f'{render.h((e.get("payload") or {}).get("error"))}</div>'
        for e in run.failovers
    )
    return render.banner_html("amber", "Agent failover", rows, "FAILOVER")


TURN1_SUB = "Parallel · each agent sees only the public event and its own private inputs"
TURN2_SUB = "Fixed shortlist · approvals only · no new options"


def _negotiation_tab(run) -> None:
    _section(
        "Key view",
        "Negotiation",
        f"Turn cap 2 · {len(run.proposals)} proposals · {len(run.ballots)} ballots",
    )
    md(render.topology_html(run))

    if "AI off" in run.flags:
        md(_ai_off_banner_html())
    if run.red_team or run.injections:
        md(render.red_team_layers_html(run))
    if run.failovers:
        md(_failover_banner_html(run))

    md(
        render.turn_header_html(
            "01",
            "Propose",
            TURN1_SUB,
        )
    )
    columns = st.columns(3, gap="medium")
    for column, role in zip(columns, ROLES):
        with column:
            md(render.proposal_card_html(run, role))
            if role in run.proposals:
                _proposal_detail(run, role)

    md(render.safety_banner_html(run, 1))
    if run.shortlist_payload:
        md(render.orchestrator_card_html(run))

    if run.ballots:
        md(
            render.turn_header_html(
                "02",
                "Ballot",
                TURN2_SUB,
            )
        )
        columns = st.columns(3, gap="medium")
        for column, role in zip(columns, ROLES):
            with column:
                md(render.ballot_card_html(run, role))
                if role in run.ballots:
                    _ballot_detail(run, role)
        md(render.safety_banner_html(run, 2))
    elif "AI off" in run.flags:
        pass
    elif run.status == "CONSENSUS" and run.turn == 1:
        md(_turn1_commit_banner_html())
    elif run.status == "ESCALATED":
        md(
            render.banner_html(
                "red",
                "Escalated at setup",
                "No option passed every code check. The case went to a human.",
                "ESCALATED",
            )
        )
    else:
        md(
            render.banner_html(
                "grey",
                "No Turn-2 ballot",
                "The run ended before a ballot was recorded.",
                "TURN 2",
            )
        )

    if run.fallback:
        md(render.fallback_banner_html(run))
    elif run.committed_id:
        md(
            render.banner_html(
                "green" if run.status == "CONSENSUS" else "amber",
                f"{run.status} · {run.committed_id}",
                render.h(human_reason(run.reason)),
                "OUTCOME",
            )
        )


# --------------------------------------------------------------------------- live playback


def _finish_live(live) -> None:
    """Hand a finished background run to the normal final view (full app rerun)."""

    st.session_state.pop(LIVE_KEY, None)
    st.session_state.pop(LIVE_META_KEY, None)
    if live.error:
        st.session_state[LIVE_ERROR_KEY] = live.error
    else:
        final = str(live.result_path or live.path)
        st.session_state["run_notice"] = live.notice
        st.session_state["active_run"] = final
        st.session_state["pending_run"] = final
    st.rerun()


def _live_agent_row(run, turn: int, messages: dict, builder, name: str, started: bool) -> None:
    columns = st.columns(3, gap="medium")
    for index, (column, role) in enumerate(zip(columns, ROLES)):
        with column:
            if run is not None and role in messages:
                html = live_ui.safe_html(f"{name}({role})", builder, run, role)
                md(live_ui.reveal_html(html, index))
            else:
                md(live_ui.pending_card_html(role, turn, started=started))


def _live_view(live, status: dict, run, meta: dict, load_error: Exception | None) -> None:
    ai_off = bool(meta.get("ai_off"))
    turn = int(status.get("turn") or 0)
    commit = (run.commit if run is not None else None) or {}
    fallback = (run.fallback if run is not None else None) or {}
    option_id = commit.get("option_id") or fallback.get("option_id") or fallback.get("chosen")

    md(live_ui.LIVE_CSS)
    if run is not None and run.setup:
        md(live_ui.safe_html("hero_html", render.hero_html, run))

    agents = (
        "AI off"
        if ai_off
        else ("LLM agents" if meta.get("impl") == "llm" else "Stub agents")
        + (" · red-team Pilot" if meta.get("red_team") else "")
    )
    _section("Live run", "Negotiation in progress", f"Row {meta.get('row')} · {agents}")
    md(
        live_ui.strip_html(
            live_ui.phase_steps(
                status,
                ai_off=ai_off,
                options=len(run.generated_ids or run.options) if run is not None else None,
                passed=len(run.shared_passed) if run is not None else None,
                option_id=option_id,
            )
        )
    )
    text, tone = live_ui.status_line(status, ai_off=ai_off, impl=str(meta.get("impl") or "stub"), option_id=option_id)
    md(live_ui.status_html(text, tone, time.time() - live.started_at))

    if load_error is not None:
        md(live_ui.hold_html("load_run", load_error))
        return

    if ai_off:
        md(_ai_off_banner_html())
        if run is not None and run.fallback:
            md(live_ui.safe_html("fallback_banner_html", render.fallback_banner_html, run))
        return

    if run is not None and run.failovers:
        md(live_ui.safe_html("failover banner", _failover_banner_html, run))

    # ---- Turn 1: proposals, one card per agent as each one is logged
    proposals = run.proposals if run is not None else {}
    if proposals or not status.get("done"):
        md(render.turn_header_html("01", "Propose", TURN1_SUB))
        _live_agent_row(run, 1, proposals, render.proposal_card_html, "proposal_card_html", started=turn >= 1)
    if run is not None and len(proposals) == len(ROLES):
        md(live_ui.safe_html("safety_banner_html", render.safety_banner_html, run, 1))
        shortlist = live_ui.shortlist_payload_for(run.raw_entries, 2)
        if shortlist:
            md(
                live_ui.reveal_html(
                    live_ui.safe_html(
                        "orchestrator_card_html",
                        render.orchestrator_card_html,
                        dataclasses.replace(run, shortlist_payload=shortlist),
                    )
                )
            )
    if run is not None and status.get("done") and turn == 1 and status.get("outcome") == "committed":
        md(live_ui.reveal_html(_turn1_commit_banner_html()))

    # ---- Turn 2 / Turn 3: ballots, only once the turn has started
    ballots = live_ui.messages_by_turn(run.raw_entries, "BALLOT") if run is not None else {}
    for number in (2, 3):
        if run is None or turn < number:
            break
        if number == 2:
            md(render.turn_header_html("02", "Ballot", TURN2_SUB))
        else:
            ids = ", ".join(str(v) for v in live_ui.shortlist_payload_for(run.raw_entries, 3).get("option_ids") or [])
            md(
                render.turn_header_html(
                    "03",
                    "Final ballot",
                    f"Shortlist from Turn 2: {ids or '—'} · approvals only · last turn",
                )
            )
        votes = ballots.get(number, {})
        turn_run = dataclasses.replace(run, ballots=votes)
        _live_agent_row(turn_run, number, votes, render.ballot_card_html, "ballot_card_html", started=True)
        if len(votes) == len(ROLES):
            md(live_ui.safe_html("safety_banner_html", render.safety_banner_html, run, number))

    # ---- outcome
    if run is None:
        return
    if run.fallback:
        md(live_ui.reveal_html(live_ui.safe_html("fallback_banner_html", render.fallback_banner_html, run)))
    elif status.get("outcome") == "escalated":
        md(
            live_ui.reveal_html(
                render.banner_html(
                    "red",
                    "Escalated",
                    "No option passed every code check. The case goes to a human.",
                    "ESCALATED",
                )
            )
        )
    elif run.commit and option_id:
        md(
            live_ui.reveal_html(
                render.banner_html(
                    "green",
                    f"Committed · {option_id}",
                    "The final checks passed. The full result opens once the run files are saved.",
                    "OUTCOME",
                )
            )
        )


@st.fragment(run_every=LIVE_POLL_SECONDS)
def _live_panel() -> None:
    """Poll the background run and redraw the in-progress view; never touched by the worker."""

    live = st.session_state.get(LIVE_KEY)
    if live is None:
        return
    if not live.is_alive():
        _finish_live(live)
        return
    status = live.status()
    run = None
    load_error: Exception | None = None
    if status.get("phase") != "waiting":
        try:
            run = load_run(live.path, live=True)
        except Exception as exc:  # noqa: BLE001 - shown in the panel
            load_error = exc
    _live_view(live, status, run, st.session_state.get(LIVE_META_KEY) or {}, load_error)


# --------------------------------------------------------------------------- options


def _options_tab(run) -> None:
    _section(
        "Option space",
        "Options and constraint state",
        f"{len(run.options)} generated · {len(run.counters)} counter(s)",
    )
    md(render.options_summary_html(run))
    if run.agent_checks:
        _section(
            "AI off",
            "Why each option was excluded",
            "every agent's code checker on every option",
        )
        md(render.exclusion_matrix_html(run))
        md(
            '<div class="td-table-note">With AI off no agent is asked for an opinion, but each agent\'s '
            "code checker still runs on every option. An option joins the safe pool only if all three pass.</div>"
        )
        _section("Option space", "All options", "")
    md(render.options_table_html(run))
    if run.mode == "AIRBORNE":
        md(
            '<div class="td-table-note">AIRBORNE options have no departure slot: the aircraft is already airborne. '
            "Arrival time, runway, hold / en-route absorb, gate and next-leg action are the decision variables.</div>"
        )
    if run.ai_off and not run.agent_checks:
        md(
            '<div class="td-table-note">AI off (older log): the safe pool comes from the deterministic fallback, '
            "which ran every agent's code checker. Per-option check details for options outside the pool "
            "are not in this run's log.</div>"
        )
    elif not run.ai_off:
        md(
            '<div class="td-table-note">Shared checks run before any agent sees the options. '
            "Each agent then runs its own code checker on every option and every counter. "
            "A veto is a failed hard check, not a model opinion.</div>"
        )
    if run.counter_errors:
        with st.expander("Counter-option errors"):
            st.json(run.counter_errors)


# --------------------------------------------------------------------------- resolution


def _resolution_tab(run) -> None:
    _section("Decision", "Resolution", f"{run.status} · turn {run.turn} of 2")
    md(render.resolution_panel_html(run))

    _section(
        "Commit gate",
        "Final constraint checks",
        "assert_commit_safe() · re-run on the committed option",
    )
    md(render.checks_summary_html(run))
    if run.final_checks:
        md(render.checks_table_html(run))
        md(
            '<div class="td-table-note">Every row is a hard check re-run at commit: value, limit, unit and the source that backs the rule. '
            "The committed option cannot bypass a failing row.</div>"
        )
    else:
        md(
            '<div class="td-empty-state" style="padding:22px;">'
            '<div class="td-note">No final check table: this run was escalated before a commit.</div>'
            "</div>"
        )


# --------------------------------------------------------------------------- safety


def _safety_tab(run) -> None:
    _section(
        "Guards",
        "Safety",
        f"{len(run.injections)} injection(s) resisted · {len(run.safety_blocks)} safety block(s) · commit gate",
    )
    md(render.commit_gate_html(run))

    layered = run.red_team or bool(run.injections)
    if layered:
        md(render.red_team_layers_html(run))
        _section("Layer 1 · model", "Text injection resisted", f"{len(run.injections)} event(s)")
        if run.injections:
            md(render.injection_cards_html(run))
        else:
            md(
                '<div class="td-table-note">No injected text reached a model in this run. '
                "Stub agents work from structured data only, so the red-team test here is layer 2.</div>"
            )
        _section("Layer 2 · code", "Compromised output blocked", f"{len(run.safety_blocks)} event(s)")
    else:
        _section("Blocked", "What the orchestrator stopped", f"{len(run.safety_blocks)} events")
    md(render.safety_cards_html(run))

    md(
        '<div class="td-panel" style="margin-top:14px;">'
        '<div class="td-minihead">Guards in force</div>'
        '<span class="td-chip td-chip-inject">Input text is data, never instructions</span>'
        '<span class="td-chip td-chip-veto">Vetoes come from code</span>'
        '<span class="td-chip td-chip-veto">Approvals outside the shortlist are discarded</span>'
        '<span class="td-chip td-chip-veto">Unsafe approvals are discarded</span>'
        '<span class="td-chip td-chip-veto">Every commit is re-checked</span>'
        '<div class="td-table-note">Injections and safety blocks are logged, not hidden. The run continues with only the safe options.</div>'
        "</div>"
    )

    if run.commit_failures:
        _section("Failures", "Final check failures")
        md(render.checks_table_html(run, only_failures=True))


# --------------------------------------------------------------------------- audit


def _download_buttons(run) -> None:
    columns = st.columns(3)
    files = [
        ("log.jsonl", "Download log.jsonl", "application/x-ndjson"),
        ("resolution.json", "Download resolution.json", "application/json"),
        ("manifest.json", "Download manifest.json", "application/json"),
    ]
    for column, (name, label, mime) in zip(columns, files):
        path = run.run_dir / name
        try:
            data = path.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue
        with column:
            st.download_button(
                label,
                data,
                file_name=f"{run.run_id}-{name}",
                mime=mime,
                use_container_width=True,
            )


def _audit_tab(run) -> None:
    _section(
        "Audit trail",
        "Consensus log",
        f"{len(run.raw_entries)} entries · {run.run_dir.name}",
    )
    md(render.chain_panel_html(run))
    md(render.timeline_html(run))
    _download_buttons(run)

    _section(
        "Independence",
        "What each agent saw",
        "public input vs private data, per turn",
    )
    md(render.context_table_html(run))

    _section("Run record", "Manifest", "agent mode · config hash · code version")
    md(render.manifest_html(run))

    _section("Model calls", "Agent usage", "perceive · turn 1 · turn 2")
    md(render.usage_table_html(run))

    with st.expander("Inspect a log entry (raw JSON)"):
        choices = render.raw_event_choices(run)
        labels = {seq: label for label, seq in choices}
        seq = st.selectbox(
            "Log entry",
            [value for _, value in choices],
            format_func=lambda value: labels.get(value, str(value)),
            key=f"audit_event_{run.run_dir.name}",
            index=max(0, len(choices) - 1),
        )
        entry = render.raw_event_payload(run, seq)
        if entry is not None:
            st.json(entry)


# --------------------------------------------------------------------------- main


def main() -> None:
    st.set_page_config(
        page_title="Triad · Disruption Desk",
        page_icon="◈",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    theme.inject(st)
    pending = st.session_state.pop("pending_run", None)
    if pending:
        st.session_state["source_mode"] = "Replay saved run"
        st.session_state["replay_choice"] = pending
        st.session_state["active_run"] = pending
    active = _sidebar()

    live_error = st.session_state.pop(LIVE_ERROR_KEY, None)
    if live_error:
        st.error(f"Run failed: {live_error}")
        md(render.ready_state_html())
        return
    if st.session_state.get(LIVE_KEY) is not None:
        _live_panel()
        return

    if not active:
        if st.session_state.get("source_mode") == "Run new scenario":
            md(render.ready_state_html())
        else:
            md(render.empty_state_html())
        return

    try:
        run = load_run(active)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not load the run: {exc}")
        return

    if not run.raw_entries:
        st.error("This run has no log entries. Try another replay or run a new scenario.")
        return

    notice = st.session_state.pop("run_notice", None)
    if notice:
        st.info(notice)

    md(render.hero_html(run))
    md(render.status_strip_html(run))
    md(render.flow_html(run))

    tabs = st.tabs(["Negotiation", "Options", "Resolution", "Safety", "Audit", "Evaluation"])
    with tabs[0]:
        _negotiation_tab(run)
    with tabs[1]:
        _options_tab(run)
    with tabs[2]:
        _resolution_tab(run)
    with tabs[3]:
        _safety_tab(run)
    with tabs[4]:
        _audit_tab(run)
    with tabs[5]:
        evaluation.render_panel()

    md(render.footer_html(run))


if __name__ == "__main__":
    main()
