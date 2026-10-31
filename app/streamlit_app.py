"""Triad · Disruption Desk — Streamlit demo.

Run with:  uv run streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import streamlit as st  # noqa: E402

from components import render, theme  # noqa: E402
from components.data import (  # noqa: E402
    ROLES,
    available_runs,
    defect_library,
    defect_options,
    demo_scenarios,
    load_run,
    recommended_run,
    run_label,
    run_negotiation,
    scenario_choices,
)
from components.format import human_reason  # noqa: E402

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
                st.markdown(
                    "The route and flight header are rebuilt from the manifest's dataset row and seed. "
                    "Negotiation messages, constraints, safety blocks and the audit trail come only from the saved run files."
                )
            return path

        return _new_run_form()


def _new_run_form() -> Path | None:
    md('<div class="td-side-label">New negotiation</div>')
    pick_by = st.radio(
        "Choose by", ["Demo scenario", "Dataset row"], key="pick_by", horizontal=True
    )
    scenario_defect = None
    seed = 0
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
        seed = int(item.get("seed") or 0)
        scenario_defect = item.get("defect")
        st.caption(f"DOT row {row} · seed {seed} · {item.get('mode', '')}")
        description = SCENARIO_COPY.get(scenario_name) or str(item.get("notes") or "").split(";")[0]
        if description:
            st.caption(description)
    else:
        row = int(
            st.number_input(
                "Dataset row",
                min_value=0,
                value=293614,
                step=1,
                key="row_input",
                help="Any row with WEATHER_DELAY > 15 or LATE_AIRCRAFT_DELAY > 20.",
            )
        )
        seed = int(
            st.number_input("Seed", min_value=0, value=0, step=1, key="seed_input")
        )
        st.caption("Candidate rows need WEATHER_DELAY > 15 or LATE_AIRCRAFT_DELAY > 20.")

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

    if st.button("Run negotiation", type="primary", use_container_width=True):
        spinner = (
            "Negotiating with LLM agents. This can take 1–3 minutes."
            if impl_label == "LLM" and not ai_off
            else "Running the negotiation."
        )
        with st.spinner(spinner):
            try:
                path, notice = run_negotiation(
                    row_index=row,
                    seed=seed,
                    defect_id=defect_id,
                    ai_off=bool(ai_off),
                    red_team=bool(red_team) and not ai_off,
                    impl="llm" if impl_label == "LLM" and not ai_off else "stub",
                    use_cache=bool(use_cache),
                    defect_tag=defect_tag,
                )
            except Exception as exc:  # noqa: BLE001
                st.error(f"Run failed: {exc}")
                return None
        st.session_state["run_notice"] = notice
        st.session_state["active_run"] = str(path)
        st.session_state["pending_run"] = str(path)
        st.rerun()
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


def _negotiation_tab(run) -> None:
    _section(
        "Key view",
        "Negotiation",
        f"Turn cap 2 · {len(run.proposals)} proposals · {len(run.ballots)} ballots",
    )
    md(render.topology_html(run))

    if "AI off" in run.flags:
        md(
            render.banner_html(
                "amber",
                "AI is off",
                "No agent was called. The orchestrator ran the shared code checks and the deterministic fallback chose the cheapest safe option.",
                "AI OFF",
            )
        )
    if "Red-team" in run.flags:
        md(
            render.banner_html(
                "amber",
                "Red-team run",
                "The Pilot agent was pushed to approve an option regardless of its checks. Watch for SAFETY_BLOCK entries.",
                "RED TEAM",
            )
        )
    if run.failovers:
        rows = "".join(
            f'<div class="td-note"><b>{render.h((e.get("payload") or {}).get("role"))}</b> · '
            f'{render.h((e.get("payload") or {}).get("error"))}</div>'
            for e in run.failovers
        )
        md(render.banner_html("amber", "Agent failover", rows, "FAILOVER"))

    md(
        render.turn_header_html(
            "01",
            "Propose",
            "Parallel · each agent sees only the public event and its own private inputs",
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
                "Fixed shortlist · approvals only · no new options",
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
        md(
            render.banner_html(
                "green",
                "Committed at Turn 1",
                "All three agents ranked the same option first and nobody objected to it. The fast path was used.",
                "TURN 1",
            )
        )
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


# --------------------------------------------------------------------------- options


def _options_tab(run) -> None:
    _section(
        "Option space",
        "Options and constraint state",
        f"{len(run.options)} generated · {len(run.counters)} counter(s)",
    )
    md(render.options_summary_html(run))
    md(render.options_table_html(run))
    if run.mode == "AIRBORNE":
        md(
            '<div class="td-table-note">AIRBORNE options have no departure slot: the aircraft is already airborne. '
            "Arrival time, runway, hold / en-route absorb, gate and next-leg action are the decision variables.</div>"
        )
    if "AI off" in run.flags:
        md(
            '<div class="td-table-note">AI off: the safe pool comes from the deterministic fallback, '
            "which ran every agent's code checker. Per-option check details for options outside the pool "
            "are not in this run's log.</div>"
        )
    else:
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
        f"{len(run.safety_blocks)} safety block(s) · commit gate",
    )
    md(render.commit_gate_html(run))
    if "Red-team" in run.flags:
        md(
            render.banner_html(
                "amber",
                "Red-team run",
                "The Pilot agent was pushed to approve an option regardless of its checks. "
                "The blocks below come from the orchestrator and the code checkers.",
                "RED TEAM",
            )
        )
    _section("Blocked", "What the orchestrator stopped", f"{len(run.safety_blocks)} events")
    md(render.safety_cards_html(run))

    md(
        '<div class="td-panel" style="margin-top:14px;">'
        '<div class="td-minihead">Guards in force</div>'
        '<span class="td-chip td-chip-veto">Vetoes come from code</span>'
        '<span class="td-chip td-chip-veto">Approvals outside the shortlist are discarded</span>'
        '<span class="td-chip td-chip-veto">Unsafe approvals are discarded</span>'
        '<span class="td-chip td-chip-veto">Every commit is re-checked</span>'
        '<div class="td-table-note">A safety block is logged, not hidden. The run continues with only the safe options.</div>'
        "</div>"
    )

    if run.commit_failures:
        _section("Failures", "Final check failures")
        md(render.checks_table_html(run, only_failures=True))
    elif run.final_checks:
        md(
            render.banner_html(
                "green",
                "No failed final checks",
                f"All {len(run.final_checks)} hard checks on {render.h(run.committed_id or 'the committed option')} passed at commit.",
                "PASS",
            )
        )


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
        "Per-agent context manifests",
        "what each agent saw, per turn",
    )
    md(render.context_table_html(run))

    _section("Run record", "Manifest", "agent mode · config hash · code version")
    md(render.manifest_html(run))

    _section("Model calls", "Agent usage", "tokens and latency, when the LLM was used")
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

    tabs = st.tabs(["Negotiation", "Options", "Resolution", "Safety", "Audit"])
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

    md(render.footer_html(run))


if __name__ == "__main__":
    main()
