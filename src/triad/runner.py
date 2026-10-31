"""CLI runner: build the event, run the protocol, persist log + manifest + resolution."""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path
from typing import Any

import yaml

from triad.config import CONFIG_DIR, RUNS_DIR
from triad.log.consensus_log import ConsensusLog
from triad.log.manifest import build_manifest, write_manifest, write_resolution
from triad.schemas import Resolution, fmt_hhmm

_DEMO_SCENARIOS = CONFIG_DIR / "demo_scenarios.yaml"


def _resolve_scenario(name: str) -> tuple[int, int, str | None] | None:
    """Look up a named demo scenario; tolerate the file not existing yet."""
    if not _DEMO_SCENARIOS.exists():
        return None
    data = yaml.safe_load(_DEMO_SCENARIOS.read_text(encoding="utf-8")) or {}
    item: Any = None
    if isinstance(data, dict):
        if isinstance(data.get(name), dict):
            item = data[name]
        else:
            scenarios = data.get("scenarios", data)
            if isinstance(scenarios, dict):
                item = scenarios.get(name)
            elif isinstance(scenarios, list):
                item = next(
                    (
                        s
                        for s in scenarios
                        if isinstance(s, dict) and name in (s.get("name"), s.get("id"))
                    ),
                    None,
                )
    elif isinstance(data, list):
        item = next(
            (s for s in data if isinstance(s, dict) and name in (s.get("name"), s.get("id"))),
            None,
        )
    if not isinstance(item, dict) or item.get("row") is None:
        return None
    return int(item["row"]), int(item.get("seed", 0)), item.get("defect")


def _prepare(
    row_index: int,
    *,
    seed: int = 0,
    defect_id: str | None = None,
    red_team: bool = False,
    impl: str = "stub",
    use_cache: bool = True,
):
    from triad.agents import build_agents
    from triad.data.enrich import build_event
    from triad.data.loader import get_record

    record = get_record(row_index)
    event = build_event(record, seed=seed, defect_id=defect_id)
    agents = build_agents(event, impl=impl, red_team=red_team, use_cache=use_cache)
    return record, event, agents


def _prefetch_perception(agents, public) -> None:
    """Run all three agents' (cached) perception calls concurrently."""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="triad-perceive") as pool:
        futures = [pool.submit(agent.perceive, public) for agent in agents.values()]
        for future in futures:
            try:
                future.result()
            except Exception:  # noqa: BLE001 - turn 1 will retry/fail over
                pass


def _execute(
    row_index: int,
    *,
    seed: int = 0,
    defect_id: str | None = None,
    ai_off: bool = False,
    red_team: bool = False,
    run_dir: Path | None = None,
    impl: str = "stub",
    use_cache: bool = True,
):
    from triad.coordinator.protocol import Orchestrator

    record, event, agents = _prepare(
        row_index,
        seed=seed,
        defect_id=defect_id,
        red_team=red_team,
        impl=impl,
        use_cache=use_cache,
    )
    if not ai_off:
        _prefetch_perception(agents, event.public)
    log = ConsensusLog(record.run_id, run_dir)
    run_flags = {"impl": impl, "red_team": red_team, "defect_id": defect_id, "seed": seed}
    orchestrator = Orchestrator(event.public, agents, log, run_flags=run_flags)
    resolution = orchestrator.run(ai_off=ai_off)
    return record, event, agents, resolution, log


def run_scenario(
    row_index: int,
    *,
    seed: int = 0,
    defect_id: str | None = None,
    ai_off: bool = False,
    red_team: bool = False,
    run_dir: Path | None = None,
    impl: str = "stub",
    use_cache: bool = True,
) -> tuple[Resolution, ConsensusLog]:
    """Programmatic entry point for the UI/tests."""
    _record, _event, _agents, resolution, log = _execute(
        row_index,
        seed=seed,
        defect_id=defect_id,
        ai_off=ai_off,
        red_team=red_team,
        run_dir=run_dir,
        impl=impl,
        use_cache=use_cache,
    )
    return resolution, log


def run_main(args: Any) -> None:
    row_index = args.row
    seed = int(getattr(args, "seed", 0))
    defect_id = getattr(args, "defect", None)
    scenario = getattr(args, "scenario", None)
    ai_off = bool(getattr(args, "ai_off", False))
    red_team = bool(getattr(args, "red_team", False))
    impl = str(getattr(args, "impl", "stub") or "stub")
    use_cache = not bool(getattr(args, "no_cache", False))
    quiet = bool(getattr(args, "quiet", False))

    if row_index is None and scenario:
        resolved = _resolve_scenario(scenario)
        if resolved is None:
            print(
                f"error: scenario {scenario!r} not found (config/demo_scenarios.yaml missing or incomplete).",
                file=sys.stderr,
            )
            raise SystemExit(2)
        row_index, seed, scenario_defect = resolved
        defect_id = defect_id or scenario_defect

    if row_index is None:
        print("error: pass --row <n> or --scenario <name>.", file=sys.stderr)
        raise SystemExit(2)

    try:
        from triad.data.loader import get_record
        from triad.data.scenario import is_candidate

        record = get_record(row_index)
        if not is_candidate(record):
            print(
                "error: row "
                f"{row_index} is not a candidate (WEATHER_DELAY > 15 or LATE_AIRCRAFT_DELAY > 20 required; "
                f"got weather={record.weather_delay}, late_aircraft={record.late_aircraft_delay}).",
                file=sys.stderr,
            )
            raise SystemExit(2)
    except SystemExit:
        raise
    except ImportError as exc:
        print(f"error: dataset modules unavailable: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    suffix = ("-llm" if impl == "llm" else "") + ("-redteam" if red_team else "") + ("-aioff" if ai_off else "")
    base = Path(args.out) if getattr(args, "out", None) else RUNS_DIR
    run_dir = base / f"{record.run_id}{suffix}"

    try:
        record, event, agents, resolution, log = _execute(
            row_index,
            seed=seed,
            defect_id=defect_id,
            ai_off=ai_off,
            red_team=red_team,
            run_dir=run_dir,
            impl=impl,
            use_cache=use_cache,
        )
    except ImportError as exc:
        print(f"error: WORLD lane modules unavailable: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    prompt_hashes: dict[str, str] = {}
    if impl == "llm":
        from triad.agents.llm import prompt_hashes as _prompt_hashes

        prompt_hashes = _prompt_hashes()
    manifest = build_manifest(
        run_id=record.run_id,
        dataset_row=row_index,
        seed=seed,
        mode=event.public.mode,
        agent_impl={role.value: agent.impl for role, agent in agents.items()},
        prompt_hashes=prompt_hashes,
    )
    write_manifest(manifest, run_dir)
    write_resolution(resolution, run_dir)

    if not quiet:
        _print_summary(record, event, resolution, log, agents)


# --------------------------------------------------------------------------- console


def _print_summary(record, event, resolution: Resolution, log: ConsensusLog, agents=None) -> None:
    public = event.public
    flight = public.flight
    print()
    print(f"Run {resolution.run_id}  ({resolution.status}, turn {resolution.turn})")
    print(
        f"  Flight {flight.airline}{flight.flight_number}  {flight.origin} -> {flight.destination}"
        f"  {flight.year}-{flight.month:02d}-{flight.day:02d}  mode={public.mode.value}"
    )
    print(
        f"  Scheduled arrival {fmt_hhmm(flight.scheduled_arrival)}"
        f"  expected ETA {fmt_hhmm(public.expected_eta)}"
        f"  delays: weather={flight.weather_delay} late_aircraft={flight.late_aircraft_delay}"
    )

    options = _options_from_log(log)
    if options:
        print()
        print("  Options")
        print("  id        dep    arr    rwy  hold/absorb  FL   gate   next leg")
        for o in options:
            dep = fmt_hhmm(o.get("departure_slot")) if o.get("departure_slot") is not None else "  -  "
            next_leg = o.get("next_leg_action") or "KEEP"
            delay = int(o.get("next_leg_delay_min") or 0)
            if delay:
                next_leg += f"+{delay}"
            print(
                f"  {o.get('option_id', '?'):<8}  {dep:<5}  {fmt_hhmm(o.get('arrival_slot')):<5}"
                f"  {str(o.get('runway', '-')):<4} {int(o.get('holding_min') or 0):>3}/{int(o.get('enroute_absorb_min') or 0):<3}"
                f"     {str(o.get('cruise_level') or '-'):<4} {str(o.get('gate', '-')):<6} {next_leg}"
            )

    _print_turns(log)
    _print_fallback_why(log)

    _print_perception(log)
    _print_llm_usage(log, agents)
    _print_red_team(log)

    gates = [e for e in log.entries if e.event == "COMMIT_GATE"]
    if gates:
        print()
        print("  Commit gate (assert_commit_safe re-runs every check)")
        for entry in gates:
            p = entry.payload
            failed = ", ".join(f.get("constraint_id", "?") for f in p.get("failed", [])) or "-"
            verdict = "PASS" if p.get("passed") else f"BLOCKED [{failed}]"
            print(f"    {p.get('option_id', '-')}: {verdict} ({p.get('n_checks', 0)} checks)")

    print()
    if resolution.option is None:
        print(f"  RESULT {resolution.status}: {resolution.reason}")
        return
    option = resolution.option
    costs = ", ".join(f"{role}=€{value:,.0f}" for role, value in resolution.costs_eur.items())
    print(
        f"  RESULT {resolution.status} at turn {resolution.turn}: {option.option_id}"
        f"  runway {option.runway}  arrival {fmt_hhmm(option.arrival_slot)}"
        f"  gate {option.gate}  next-leg {option.next_leg_action}"
    )
    print(f"  Reason: {resolution.reason}")
    if costs:
        print(f"  Cost: {costs}")
    print(f"  Log: {len(log.entries)} entries, chain {'OK' if ConsensusLog.verify(log.entries) else 'BROKEN'}")


_TURN_KINDS = {1: "PROPOSE", 2: "BALLOT", 3: "FINAL BALLOT"}


def _print_turns(log: ConsensusLog) -> None:
    """Turn 1/2/3 lines: proposals, ballots, counters (validated/rejected) per turn."""
    print()
    print("  Turns")
    for entry in log.entries:
        payload = entry.payload
        if entry.event == "TURN_START":
            turn = int(payload.get("turn", entry.turn))
            kind = _TURN_KINDS.get(turn, "?")
            print(f"  Turn {turn}/{payload.get('max_turns', 3)} {kind}: {payload.get('reason', '')}")
            shortlist = payload.get("shortlist") or []
            label = "options" if turn == 1 else "shortlist"
            fallback = payload.get("fallback_option_id")
            print(
                f"    {label}: {', '.join(shortlist) or '-'}"
                + (f"   (fallback if no agreement: {fallback})" if fallback else "")
            )
        elif entry.event == "PROPOSAL":
            vetoes = ", ".join(v.get("option_id", "?") for v in payload.get("vetoes", [])) or "-"
            objections = ", ".join(
                f"{o.get('option_id')}:{o.get('category')}" for o in payload.get("objections", [])
            ) or "-"
            ranking = payload.get("ranking", [])
            counter = payload.get("counter_option")
            counter_txt = f" counter={counter.get('base_option_id')}" if counter else ""
            print(
                f"    T{entry.turn} {entry.actor:<7} top={ranking[0] if ranking else '-':<8}"
                f" vetoes=[{vetoes}] objections=[{objections}]{counter_txt}"
            )
            if payload.get("rationale"):
                print(f"      rationale: {payload['rationale']}")
        elif entry.event == "BALLOT":
            votes = ", ".join(
                f"{v.get('option_id')}:{v.get('vote', '?')[0]}"
                + (f"({v.get('reason')})" if v.get("vote") == "DISAPPROVE" and v.get("reason") else "")
                for v in payload.get("votes", [])
            )
            counter = payload.get("counter_option")
            counter_txt = ""
            if counter:
                changes = ", ".join(f"{k}={v}" for k, v in sorted((counter.get("changes") or {}).items()))
                counter_txt = f" counter={counter.get('base_option_id')}[{changes}]"
            print(f"    T{entry.turn} {entry.actor:<7} votes=[{votes}]{counter_txt}")
            if payload.get("rationale"):
                print(f"      rationale: {payload['rationale']}")
        elif entry.event in ("COUNTER_VALIDATED", "COUNTER_REJECTED"):
            who = payload.get("role", "?")
            oid = payload.get("option_id") or f"counter on {payload.get('base_option_id', '?')}"
            if entry.event == "COUNTER_VALIDATED":
                verdict = "VALIDATED (passes shared + all three checkers)"
            else:
                failing = ", ".join(
                    f"{c.get('owner')}:{c.get('constraint_id')}" for c in payload.get("failing_checks") or []
                )
                verdict = "REJECTED: " + (payload.get("error") or (f"fails {failing}" if failing else "invalid"))
            print(f"    T{entry.turn} counter {oid} ({who}, base {payload.get('base_option_id', '-')}): {verdict}")


def _print_fallback_why(log: ConsensusLog) -> None:
    entry = next(
        (e for e in log.entries if e.event == "FALLBACK_INVOKED" and e.payload.get("summary")),
        None,
    )
    if entry is None:
        return
    payload = entry.payload
    print()
    summary = str(payload["summary"])
    if summary.startswith("No "):
        summary = "n" + summary[1:]
    text = f"Fallback because {summary}"
    print(textwrap.fill(text, width=110, initial_indent="  ", subsequent_indent="    "))
    if payload.get("tie_break"):
        print(textwrap.fill(f"Tie-break: {payload['tie_break']}", width=110, initial_indent="    ", subsequent_indent="      "))


_ROLE_NAMES = {"ATC": "ATC", "PILOT": "Pilot", "GROUND": "Ground"}


def _print_perception(log: ConsensusLog) -> None:
    entries = [e for e in log.entries if e.event == "PERCEPTION"]
    if entries:
        facts = [(e.actor, f) for e in entries for f in e.payload.get("facts", [])]
    else:
        entries = [e for e in log.entries if e.event == "PROPOSAL"]
        facts = [(e.actor, f) for e in entries for f in e.payload.get("facts", [])]
    if not facts:
        return
    print()
    print("  Perceived facts")
    for actor, fact in facts:
        citation = fact.get("citation")
        if isinstance(citation, dict):
            citation = citation.get("chunk_id")
        value = json.dumps(fact.get("value"), sort_keys=True, default=str)
        if len(value) > 72:
            value = value[:69] + "..."
        default = " CONSERVATIVE_DEFAULT" if fact.get("conservative_default") else ""
        print(
            f"    {actor:<6} {fact.get('key', '?'):<16} {value:<74}"
            f" [{fact.get('source', '?')}] cite={citation or '-'}{default}"
        )


def _print_red_team(log: ConsensusLog) -> None:
    injections = [e for e in log.entries if e.event == "INJECTION_DETECTED"]
    blocks = [e for e in log.entries if e.event == "SAFETY_BLOCK"]
    setup = next((e for e in log.entries if e.event == "SETUP"), None)
    red_team = bool(((setup.payload.get("flags") or {}) if setup else {}).get("red_team"))
    if not (injections or blocks or red_team):
        return

    print()
    print("  [1] Text injection (untrusted free text reaching an agent's perception)")
    if injections:
        for entry in injections:
            p = entry.payload
            who = _ROLE_NAMES.get(str(p.get("role") or entry.actor), entry.actor)
            print(f"    Injection attempt in {who} input — treated as data")
            print(f"      note: {p.get('note', '')!r}")
            print(f"      trigger phrases: {', '.join(p.get('phrases', [])) or '-'}")
    else:
        print("    none detected")

    print("  [2] Compromised agent output (blocked by the orchestrator's code checks)")
    if blocks:
        for entry in blocks:
            p = entry.payload
            who = p.get("agent") or p.get("role") or "commit"
            ids = ", ".join(p.get("constraint_ids") or []) or "no failing check"
            print(
                f"    SAFETY_BLOCK turn {entry.turn} {who}: {p.get('detail', '?')}"
                f" ({p.get('option_id', '-')}) [{ids}]"
            )
    else:
        print("    none")


def _print_llm_usage(log: ConsensusLog, agents) -> None:
    usages: list[tuple[str, dict[str, Any]]] = []
    for role, agent in (agents or {}).items():
        for usage in getattr(agent, "usages", []) or []:
            usages.append((role.value, usage))
    if not usages:
        for entry in log.entries:
            if not entry.usage:
                continue
            for role, usage in entry.usage.items():
                if isinstance(usage, dict):
                    usages.append((role, usage))
    if not usages:
        return
    prompt = sum(int(u.get("prompt_tokens", 0) or 0) for _r, u in usages)
    completion = sum(int(u.get("completion_tokens", 0) or 0) for _r, u in usages)
    ms = sum(float(u.get("ms", 0.0) or 0.0) for _r, u in usages)
    cached = sum(1 for _r, u in usages if u.get("cached"))
    repaired = sum(1 for _r, u in usages if u.get("repaired"))
    models = sorted({str(u.get("model")) for _r, u in usages if u.get("model")})
    print()
    print(
        f"  LLM: {ms / 1000.0:.2f}s, {prompt + completion} tokens "
        f"({prompt} in / {completion} out), cache hits {cached}, repairs {repaired}"
        + (f", model {', '.join(models)}" if models else "")
    )
    by_role: dict[str, float] = {}
    for role, usage in usages:
        by_role[role] = by_role.get(role, 0.0) + float(usage.get("ms", 0.0) or 0.0)
    if by_role:
        print("    time by agent: " + ", ".join(f"{r}={v / 1000.0:.2f}s" for r, v in sorted(by_role.items())))


def _options_from_log(log: ConsensusLog) -> list[dict[str, Any]]:
    for entry in log.entries:
        if entry.event == "OPTIONS_GENERATED":
            return list(entry.payload.get("options", []))
    return []
