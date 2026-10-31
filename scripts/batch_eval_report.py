"""Batch evaluation for the judges' "honest evaluation" criterion.

Adds per-run CSV rows (written incrementally) plus a Markdown summary under
``results/``. Every negotiation goes through the project's own runner
(``triad.runner._execute``, the same path ``uv run triad run`` uses); nothing in
the protocol is reimplemented here.

    uv run python scripts/batch_eval_report.py sample              # results/sample_rows.csv
    uv run python scripts/batch_eval_report.py run --impl stub     # 200 stub runs
    uv run python scripts/batch_eval_report.py run --impl llm --no-cache   # 20 LLM runs
    uv run python scripts/batch_eval_report.py redteam             # --red-team, LLM, scenario_c
    uv run python scripts/batch_eval_report.py summarize           # results/eval_summary.md

Baselines (both computed on the run's own generated options, scored with the
stub agents, i.e. ground-truth private data):
  fallback  the project's deterministic solver (``Orchestrator.run(ai_off=True)``):
            cheapest option that passes every hard check.
  FCFS      SIMULATED status quo: among *generator* options (no counter-proposals)
            whose gate equals the originally planned gate (``GroundPrivate.current_gate``),
            not a diversion, and passing every hard check (shared checks + the three
            stub agents' ``check``), take the earliest ``arrival_slot`` (tie: option_id).
            If no such option exists the cell is empty and counted as "FCFS infeasible".
  FCFS-any  the repository's ``triad.baseline.fcfs_resolution`` (earliest safe arrival,
            any gate), reported as a secondary reference.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

RESULTS = ROOT / "results"
SAMPLE_CSV = RESULTS / "sample_rows.csv"
SEED = 2026
N_STUB_PER_TYPE = 100
N_LLM_PER_TYPE = 10

FIELDS = [
    "row", "run_id", "flight", "route", "delay_type", "weather_delay", "late_aircraft_delay",
    "decision_mode", "impl", "outcome", "status", "reason", "turns_used", "chosen_option",
    "chosen_origin", "arrival_delay_min", "total_cost_eur", "cost_atc_eur", "cost_pilot_eur",
    "cost_ground_eur", "failovers", "failover_roles", "safety_blocks", "repairs", "llm_calls",
    "cache_hits", "commit_gate_checks", "commit_gate_blocked", "commit_gate_passed",
    "unsafe_commit", "hard_violations_recheck", "tokens_in", "tokens_out", "wall_s",
    "fallback_option", "fallback_cost_eur", "fallback_arrival_delay_min",
    "fcfs_option", "fcfs_cost_eur", "fcfs_arrival_delay_min",
    "fcfs_any_option", "fcfs_any_cost_eur", "fcfs_any_arrival_delay_min",
    "original_gate", "log_path", "hash_chain_ok", "error",
]


# --------------------------------------------------------------------------- sampling


def cmd_sample(_args: argparse.Namespace) -> None:
    import numpy as np

    from triad.data.loader import load_flights

    df = load_flights()
    w = df["WEATHER_DELAY"].to_numpy(dtype=np.int64)
    late = df["LATE_AIRCRAFT_DELAY"].to_numpy(dtype=np.int64)
    weather_rows = np.flatnonzero(w > 15).tolist()  # mode_for(): AIRBORNE
    late_rows = np.flatnonzero((w <= 15) & (late > 20)).tolist()  # GROUND
    rng = random.Random(SEED)
    stub_w = sorted(rng.sample(weather_rows, N_STUB_PER_TYPE))
    stub_l = sorted(rng.sample(late_rows, N_STUB_PER_TYPE))
    # LLM rows are a subset of the stub rows, so stub vs LLM is paired on identical scenarios.
    llm = set(rng.sample(stub_w, N_LLM_PER_TYPE)) | set(rng.sample(stub_l, N_LLM_PER_TYPE))
    RESULTS.mkdir(exist_ok=True)
    with open(SAMPLE_CSV, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["row", "delay_type", "weather_delay", "late_aircraft_delay", "in_stub", "in_llm"])
        for r in stub_w + stub_l:
            kind = "WEATHER" if w[r] > 15 else "LATE_AIRCRAFT"
            wr.writerow([r, kind, int(w[r]), int(late[r]), 1, int(r in llm)])
    print(f"seed={SEED}: {len(stub_w)} weather + {len(stub_l)} late-aircraft stub rows, {len(llm)} LLM rows -> {SAMPLE_CSV}")


def load_sample(impl: str) -> list[dict[str, str]]:
    with open(SAMPLE_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if r["in_llm" if impl == "llm" else "in_stub"] == "1"]


# --------------------------------------------------------------------------- baselines


def _option_cost(event, option, agents) -> tuple[float, dict[str, float]]:
    from triad.metrics import ROLES

    per = {role.value: round(float(sum(agents[role].cost_eur(event.public, option).values())), 2) for role in ROLES}
    return round(sum(per.values()), 2), per


def _hard_failures(event, option, agents) -> int:
    from triad.baseline import _all_checks
    from triad.agents.base import CheckIdGen

    checks = _all_checks(event, option, agents, CheckIdGen("EVAL"))
    return sum(1 for c in checks if c.hard and not c.passed)


def baselines(row: int, seed: int, event, evaluator, logs_dir: Path) -> dict[str, Any]:
    from triad.baseline import _is_divert, _safe_options, fcfs_resolution
    from triad.options.generator import generate_options
    from triad.runner import run_scenario

    out: dict[str, Any] = {}
    delay = lambda o: int(o.arrival_slot) - int(event.public.original_eta)  # noqa: E731

    # Project fallback solver, via the runner's --ai-off path (stub agents).
    fb, _log = run_scenario(row, seed=seed, ai_off=True, impl="stub", run_dir=logs_dir / "aioff")
    if fb.option is not None:
        out["fallback_option"] = fb.option.option_id
        out["fallback_cost_eur"] = _option_cost(event, fb.option, evaluator)[0]
        out["fallback_arrival_delay_min"] = delay(fb.option)

    options = generate_options(event.public)
    gate0 = event.ground.current_gate
    out["original_gate"] = gate0
    same_gate = [o for o in options if o.gate == gate0 and not _is_divert(o)]
    safe = [o for o, _c in _safe_options(event, evaluator, same_gate) if not _is_divert(o)]
    if safe:
        o = safe[0]  # _safe_options sorts by (divert, arrival_slot, option_id)
        out["fcfs_option"] = o.option_id
        out["fcfs_cost_eur"] = _option_cost(event, o, evaluator)[0]
        out["fcfs_arrival_delay_min"] = delay(o)

    any_res = fcfs_resolution(event, evaluator, options)
    if any_res.option is not None:
        out["fcfs_any_option"] = any_res.option.option_id
        out["fcfs_any_cost_eur"] = _option_cost(event, any_res.option, evaluator)[0]
        out["fcfs_any_arrival_delay_min"] = delay(any_res.option)
    return out


# --------------------------------------------------------------------------- one run


def run_one(row: int, impl: str, use_cache: bool, logs_root: Path, seed: int = 0) -> dict[str, Any]:
    from triad.agents import build_agents
    from triad.data.enrich import build_event
    from triad.data.loader import get_record
    from triad.data.scenario import disruption_type_for, mode_for
    from triad.log.consensus_log import ConsensusLog
    from triad.log.manifest import build_manifest, write_manifest, write_resolution
    from triad.metrics import is_unsafe_commit
    from triad.runner import _execute

    record = get_record(row)
    rec: dict[str, Any] = {
        "row": row,
        "run_id": record.run_id,
        "flight": f"{record.airline}{record.flight_number}",
        "route": f"{record.origin}-{record.destination}",
        "delay_type": disruption_type_for(record).value,
        "weather_delay": record.weather_delay,
        "late_aircraft_delay": record.late_aircraft_delay,
        "decision_mode": mode_for(record).value,
        "impl": impl,
    }
    run_dir = logs_root / impl / record.run_id
    event = build_event(record, seed=seed)
    evaluator = build_agents(event, impl="stub")  # ground-truth yardstick for every mode
    try:
        rec.update(baselines(row, seed, event, evaluator, run_dir))
    except Exception as exc:  # noqa: BLE001
        rec["error"] = f"baseline {type(exc).__name__}: {exc}"

    t0 = time.perf_counter()
    try:
        _record, ev, agents, resolution, log = _execute(
            row, seed=seed, impl=impl, use_cache=use_cache, run_dir=run_dir
        )
    except Exception as exc:  # noqa: BLE001
        rec.update(outcome="ERROR", wall_s=round(time.perf_counter() - t0, 2))
        rec["error"] = (rec.get("error", "") + f" run {type(exc).__name__}: {exc}").strip()[:300]
        return rec
    rec["wall_s"] = round(time.perf_counter() - t0, 2)

    prompt_hashes: dict[str, str] = {}
    if impl == "llm":
        from triad.agents.llm import prompt_hashes as _ph

        prompt_hashes = _ph()
    write_manifest(
        build_manifest(
            run_id=record.run_id, dataset_row=row, seed=seed, mode=ev.public.mode,
            agent_impl={r.value: a.impl for r, a in agents.items()}, prompt_hashes=prompt_hashes,
        ),
        run_dir,
    )
    write_resolution(resolution, run_dir)

    entries = log.entries
    failovers = [e for e in entries if e.event == "AGENT_FAILOVER"]
    roles = sorted({e.payload.get("role") for e in failovers if e.payload.get("role")})
    gates = [e for e in entries if e.event == "COMMIT_GATE"]
    usages = [u for a in agents.values() for u in (getattr(a, "usages", None) or [])]

    if resolution.status == "ESCALATED" or resolution.option is None:
        outcome = "ESCALATED"
    elif resolution.status == "FALLBACK":
        outcome = "FALLBACK"
    else:
        outcome = f"CONSENSUS_T{resolution.turn}"
    if len(roles) >= 3:  # runner's definition: every agent replaced by its rule stub
        outcome = "DEGRADED"

    opt = resolution.option
    rec.update(
        outcome=outcome,
        status=resolution.status,
        reason=resolution.reason,
        turns_used=max((e.turn for e in entries), default=0),
        failovers=len(failovers),
        failover_roles="|".join(roles),
        safety_blocks=sum(1 for e in entries if e.event == "SAFETY_BLOCK"),
        repairs=sum(1 for u in usages if u.get("repaired")),
        llm_calls=len(usages),
        cache_hits=sum(1 for u in usages if u.get("cached")),
        commit_gate_checks=len(gates),
        commit_gate_blocked=sum(1 for e in gates if not e.payload.get("passed")),
        commit_gate_passed=int(any(e.payload.get("passed") for e in gates)),
        unsafe_commit=int(is_unsafe_commit(resolution)),
        tokens_in=sum(int(u.get("prompt_tokens", 0) or 0) for u in usages),
        tokens_out=sum(int(u.get("completion_tokens", 0) or 0) for u in usages),
        log_path=str((run_dir / "log.jsonl").relative_to(ROOT)),
        hash_chain_ok=int(ConsensusLog.verify(run_dir / "log.jsonl")),
    )
    if opt is not None:
        total, per = _option_cost(event, opt, evaluator)
        rec.update(
            chosen_option=opt.option_id,
            chosen_origin=opt.origin,
            arrival_delay_min=int(opt.arrival_slot) - int(event.public.original_eta),
            total_cost_eur=total,
            cost_atc_eur=per["ATC"],
            cost_pilot_eur=per["PILOT"],
            cost_ground_eur=per["GROUND"],
            # independent re-check of the committed plan with ground-truth stub checkers
            hard_violations_recheck=_hard_failures(event, opt, evaluator),
        )
    return rec


def cmd_run(args: argparse.Namespace) -> None:
    out = Path(args.out or RESULTS / f"runs_{args.impl}.csv")
    logs_root = Path(args.logs_dir).resolve() if args.logs_dir else RESULTS / "logs"
    rows = load_sample(args.impl)
    if args.limit:
        rows = rows[: args.limit]
    done: set[str] = set()
    if out.exists():
        with open(out, encoding="utf-8") as f:
            done = {r["row"] for r in csv.DictReader(f)}
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, FIELDS).writeheader()
    streak = 0
    todo = [r for r in rows if r["row"] not in done]
    print(f"{args.impl}: {len(todo)} to run ({len(done)} already in {out})", flush=True)
    for i, r in enumerate(todo, 1):
        rec = run_one(int(r["row"]), args.impl, not args.no_cache, logs_root)
        with open(out, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, FIELDS, extrasaction="ignore").writerow(rec)
        print(
            f"[{i}/{len(todo)}] row {rec['row']} {rec.get('outcome')} {rec.get('chosen_option')} "
            f"cost={rec.get('total_cost_eur')} fcfs={rec.get('fcfs_cost_eur')} fo={rec.get('failovers')} "
            f"sb={rec.get('safety_blocks')} tok={rec.get('tokens_in', 0)}+{rec.get('tokens_out', 0)} "
            f"t={rec.get('wall_s')}s {rec.get('error', '')}",
            flush=True,
        )
        if args.impl == "llm":
            bad = rec.get("outcome") == "ERROR" or int(rec.get("failovers") or 0) > 0
            streak = streak + 1 if bad else 0
            if streak > 3:
                print("STOP: more than 3 LLM runs in a row failed over or errored.", flush=True)
                raise SystemExit(3)


# --------------------------------------------------------------------------- red team


def cmd_redteam(args: argparse.Namespace) -> None:
    out_dir = RESULTS / "logs" / "redteam"
    cmd = ["uv", "run", "triad", "run", "--scenario", args.scenario, "--impl", "llm",
           "--red-team", "--no-cache", "--out", str(out_dir)]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    wall = round(time.perf_counter() - t0, 1)
    (RESULTS / "redteam_stdout.txt").write_text(proc.stdout + "\n--- stderr ---\n" + proc.stderr, encoding="utf-8")
    from triad.log.consensus_log import ConsensusLog

    run_dir = next(iter(sorted(out_dir.glob("*-llm-redteam"))), None)
    summary: dict[str, Any] = {"command": " ".join(cmd), "returncode": proc.returncode, "wall_s": wall}
    if run_dir is not None:
        entries = [json.loads(line) for line in (run_dir / "log.jsonl").read_text().splitlines() if line.strip()]
        res = json.loads((run_dir / "resolution.json").read_text()) if (run_dir / "resolution.json").exists() else {}
        summary.update(
            run_dir=str(run_dir.relative_to(ROOT)),
            safety_blocks=[e["payload"] for e in entries if e["event"] == "SAFETY_BLOCK"],
            failovers=[e["payload"] for e in entries if e["event"] == "AGENT_FAILOVER"],
            injections=sum(1 for e in entries if e["event"] == "INJECTION_DETECTED"),
            commit_gate=[e["payload"] for e in entries if e["event"] == "COMMIT_GATE"],
            status=res.get("status"),
            turn=res.get("turn"),
            reason=res.get("reason"),
            committed=(res.get("option") or {}).get("option_id"),
            costs_eur=res.get("costs_eur"),
            hash_chain_ok=ConsensusLog.verify(run_dir / "log.jsonl"),
        )
    (RESULTS / "redteam.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in {"commit_gate"}}, indent=2, default=str))


# --------------------------------------------------------------------------- summary


def _f(x: str | None) -> float | None:
    try:
        return float(x) if x not in (None, "") else None
    except ValueError:
        return None


def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "-"


def _stats(vals: list[float]) -> str:
    if not vals:
        return "-"
    return f"mean {statistics.mean(vals):+,.0f} / median {statistics.median(vals):+,.0f}"


def _rel(diffs: list[tuple[float, float]]) -> str:
    """Aggregate % change: sum(mode - base) / sum(base) and median of per-row %."""
    if not diffs:
        return "-"
    base = sum(b for _m, b in diffs)
    agg = 100 * sum(m - b for m, b in diffs) / base if base else float("nan")
    per = [100 * (m - b) / b for m, b in diffs if b]
    med = statistics.median(per) if per else float("nan")
    return f"total {agg:+.1f}% / median row {med:+.1f}%"


def summarize_mode(rows: list[dict[str, str]]) -> dict[str, Any]:
    n = len(rows)
    oc = {k: sum(1 for r in rows if r["outcome"] == k) for k in
          ("CONSENSUS_T1", "CONSENSUS_T2", "FALLBACK", "ESCALATED", "DEGRADED", "ERROR")}
    committed = [r for r in rows if r["chosen_option"]]
    vs_fcfs = [(_f(r["total_cost_eur"]), _f(r["fcfs_cost_eur"])) for r in committed if _f(r["fcfs_cost_eur"]) is not None]
    vs_fb = [(_f(r["total_cost_eur"]), _f(r["fallback_cost_eur"])) for r in committed if _f(r["fallback_cost_eur"]) is not None]
    vs_any = [(_f(r["total_cost_eur"]), _f(r["fcfs_any_cost_eur"])) for r in committed if _f(r["fcfs_any_cost_eur"]) is not None]
    d_fcfs = [(_f(r["arrival_delay_min"]), _f(r["fcfs_arrival_delay_min"])) for r in committed if _f(r["fcfs_arrival_delay_min"]) is not None]
    tok = [int(r["tokens_in"] or 0) + int(r["tokens_out"] or 0) for r in rows if r["outcome"] != "ERROR"]
    wall = [_f(r["wall_s"]) for r in rows if _f(r["wall_s"]) is not None]
    return {
        "n": n,
        "outcomes": oc,
        "consensus": oc["CONSENSUS_T1"] + oc["CONSENSUS_T2"],
        "unsafe": sum(int(r["unsafe_commit"] or 0) for r in rows),
        "hard_viol_runs": sum(1 for r in committed if int(r["hard_violations_recheck"] or 0) > 0),
        "n_committed": len(committed),
        "mean_sb": statistics.mean([int(r["safety_blocks"] or 0) for r in rows]) if rows else 0,
        "failover_runs": sum(1 for r in rows if int(r["failovers"] or 0) > 0),
        "repair_runs": sum(1 for r in rows if int(r["repairs"] or 0) > 0),
        "repairs": sum(int(r["repairs"] or 0) for r in rows),
        "llm_calls": sum(int(r["llm_calls"] or 0) for r in rows),
        "chain_ok": sum(int(r["hash_chain_ok"] or 0) for r in rows if r["outcome"] != "ERROR"),
        "fcfs_infeasible": sum(1 for r in rows if not r["fcfs_option"]),
        "vs_fcfs": vs_fcfs,
        "vs_fb": vs_fb,
        "vs_any": vs_any,
        "d_fcfs": d_fcfs,
        "better_than_fcfs": sum(1 for m, b in vs_fcfs if m < b - 0.5),
        "worse_than_fcfs": sum(1 for m, b in vs_fcfs if m > b + 0.5),
        "eq_fb": sum(1 for m, b in vs_fb if abs(m - b) <= 0.5),
        "below_fb": sum(1 for m, b in vs_fb if m < b - 0.5),
        "above_fb": sum(1 for m, b in vs_fb if m > b + 0.5),
        "divert": sum(1 for r in committed if r["chosen_option"] == "OPT-DIV"),
        "counter": sum(1 for r in committed if r["chosen_origin"] == "COUNTER"),
        "delay": [_f(r["arrival_delay_min"]) for r in committed],
        "tokens": tok,
        "wall": wall,
    }


def cmd_summarize(args: argparse.Namespace) -> None:
    modes: dict[str, list[dict[str, str]]] = {}
    for impl in ("stub", "llm"):
        p = Path(args.llm_csv) if impl == "llm" and args.llm_csv else RESULTS / f"runs_{impl}.csv"
        if p.exists():
            with open(p, encoding="utf-8") as f:
                modes[impl] = list(csv.DictReader(f))
    S = {k: summarize_mode(v) for k, v in modes.items()}
    # stub restricted to the 20 LLM rows, for a paired comparison
    if "llm" in modes and "stub" in modes:
        llm_rows = {r["row"] for r in modes["llm"]}
        S["stub@llm-rows"] = summarize_mode([r for r in modes["stub"] if r["row"] in llm_rows])
    cols = list(S)

    def line(label: str, fn) -> str:
        return f"| {label} | " + " | ".join(fn(S[c]) for c in cols) + " |"

    def diff_abs(pairs):
        return _stats([m - b for m, b in pairs])

    L = [
        "# Triad batch evaluation summary",
        "",
        f"Generated by `scripts/batch_eval_report.py`. Rows sampled with seed {SEED} from `datasets/flights.csv` "
        "(stratified: half WEATHER_DELAY>15 -> AIRBORNE, half LATE_AIRCRAFT_DELAY>20 & WEATHER_DELAY<=15 -> GROUND); "
        "the 20 LLM rows are a subset of the 200 stub rows. Scenario seed 0.",
        "",
        "**Synthetic data:** flight identity, route, schedule and delay minutes are real (US DOT 2015). Everything the agents "
        "negotiate over is SYNTHETIC, generated by `triad.data.enrich` from `config/*.yaml`: arrival slots/runways, gates, fuel, "
        "crew duty, connections, next leg, MEL defects, NOTAM/weather text, and the EUR cost weights (`config/costs.yaml`). "
        "All costs below are model costs, not airline figures.",
        "",
        "**Cost yardstick:** every cost is recomputed with the stub agents' `cost_eur` (ground-truth private data), the same function "
        "the fallback solver uses, so stub, LLM and baselines are on one scale. `hard_violations_recheck` re-runs shared + all three "
        "stub checkers on the committed plan, independent of what the (possibly LLM) agents believed.",
        "",
        "**Baselines:** *fallback* = project solver (`--ai-off`), cheapest option passing all hard checks. *FCFS (status quo, SIMULATED)* = "
        "earliest-arrival generator option that keeps the originally planned gate, is not a diversion, uses no counter-proposal, and passes "
        "every hard check. *FCFS-any* = `triad.baseline.fcfs_resolution` (earliest safe arrival, any gate). Negative = cheaper than baseline.",
        "",
        "> The *vs fallback* comparison is not expected to be negative: the fallback already picks the cheapest safe option among generated "
        "options, so negotiation can at best match it (or beat it only through a validated counter-proposal). Its value is showing how "
        "much cost the negotiated consensus gives up, in exchange for agent buy-in.",
        "",
        "| metric | " + " | ".join(cols) + " |",
        "|---|" + "---|" * len(cols),
        line("runs (n)", lambda s: str(s["n"])),
        line("consensus within 2 turns", lambda s: _pct(s["consensus"], s["n"])),
        line("  CONSENSUS turn 1", lambda s: _pct(s["outcomes"]["CONSENSUS_T1"], s["n"])),
        line("  CONSENSUS turn 2", lambda s: _pct(s["outcomes"]["CONSENSUS_T2"], s["n"])),
        line("  FALLBACK", lambda s: _pct(s["outcomes"]["FALLBACK"], s["n"])),
        line("  ESCALATED", lambda s: _pct(s["outcomes"]["ESCALATED"], s["n"])),
        line("  DEGRADED (all 3 agents failed over)", lambda s: _pct(s["outcomes"]["DEGRADED"], s["n"])),
        line("  ERROR", lambda s: _pct(s["outcomes"]["ERROR"], s["n"])),
        line("unsafe commits (must be 0)", lambda s: str(s["unsafe"])),
        line("committed plans with hard violation on ground-truth re-check", lambda s: f"{s['hard_viol_runs']}/{s['n_committed']}"),
        line("avg SAFETY_BLOCK per run", lambda s: f"{s['mean_sb']:.2f}"),
        line("runs with >=1 AGENT_FAILOVER", lambda s: _pct(s["failover_runs"], s["n"])),
        line("runs with >=1 JSON repair (repairs / LLM calls)", lambda s: f"{_pct(s['repair_runs'], s['n'])} ({s['repairs']}/{s['llm_calls']})"),
        line("hash chain OK", lambda s: f"{s['chain_ok']}/{s['n'] - s['outcomes']['ERROR']}"),
        line("FCFS same-gate infeasible (no safe option)", lambda s: _pct(s["fcfs_infeasible"], s["n"])),
        line("cost vs FCFS, EUR (n paired)", lambda s: f"{diff_abs(s['vs_fcfs'])} (n={len(s['vs_fcfs'])})"),
        line("cost vs FCFS, %", lambda s: _rel(s["vs_fcfs"])),
        line("  rows cheaper / dearer than FCFS", lambda s: f"{s['better_than_fcfs']} / {s['worse_than_fcfs']}"),
        line("arrival delay vs FCFS, min", lambda s: f"{diff_abs(s['d_fcfs'])} (n={len(s['d_fcfs'])})"),
        line("cost vs FCFS-any, EUR", lambda s: f"{diff_abs(s['vs_any'])} (n={len(s['vs_any'])})"),
        line("cost vs FCFS-any, %", lambda s: _rel(s["vs_any"])),
        line("cost vs fallback, EUR", lambda s: f"{diff_abs(s['vs_fb'])} (n={len(s['vs_fb'])})"),
        line("cost vs fallback, %", lambda s: _rel(s["vs_fb"])),
        line("  rows cheaper / equal / dearer than fallback", lambda s: f"{s['below_fb']} / {s['eq_fb']} / {s['above_fb']}"),
        line("committed plan is a counter-proposal", lambda s: _pct(s["counter"], s["n_committed"])),
        line("committed plan is a diversion (OPT-DIV)", lambda s: _pct(s["divert"], s["n_committed"])),
        line("mean arrival delay of committed plan, min", lambda s: f"{statistics.mean(s['delay']):.0f}" if s["delay"] else "-"),
        line("mean cost: committed vs fallback (all committed rows), EUR", lambda s: f"{statistics.mean([m for m, _ in s['vs_fb']]):,.0f} vs {statistics.mean([b for _, b in s['vs_fb']]):,.0f}" if s["vs_fb"] else "-"),
        line("mean cost: committed vs FCFS (FCFS-feasible rows), EUR", lambda s: f"{statistics.mean([m for m, _ in s['vs_fcfs']]):,.0f} vs {statistics.mean([b for _, b in s['vs_fcfs']]):,.0f}" if s["vs_fcfs"] else "-"),
        line("avg tokens per run (in+out)", lambda s: f"{statistics.mean(s['tokens']):,.0f}" if s["tokens"] else "-"),
        line("avg wall time per run, s", lambda s: f"{statistics.mean(s['wall']):.2f}" if s["wall"] else "-"),
        line("total tokens (measured)", lambda s: f"{sum(s['tokens']):,}"),
    ]
    rt = RESULTS / "redteam.json"
    if rt.exists():
        r = json.loads(rt.read_text())
        L += [
            "",
            "## Red-team (LLM, `--red-team`, one run)",
            "",
            f"- command: `{r.get('command')}`",
            f"- SAFETY_BLOCK events: {len(r.get('safety_blocks') or [])}; AGENT_FAILOVER: {len(r.get('failovers') or [])}; "
            f"INJECTION_DETECTED: {r.get('injections')}",
            f"- final: {r.get('status')} turn {r.get('turn')}, committed `{r.get('committed')}` ({r.get('reason')}); hash chain OK: {r.get('hash_chain_ok')}",
        ]
    (Path(args.out) if args.out else RESULTS / "eval_summary.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sample")
    r = sub.add_parser("run")
    r.add_argument("--impl", choices=["stub", "llm"], required=True)
    r.add_argument("--no-cache", action="store_true")
    r.add_argument("--limit", type=int, default=None)
    r.add_argument("--out", default=None)
    r.add_argument("--logs-dir", default=None, help="log root (default results/logs); runs go to <root>/<impl>/<run_id>")
    t = sub.add_parser("redteam")
    t.add_argument("--scenario", default="scenario_c")
    m = sub.add_parser("summarize")
    m.add_argument("--llm-csv", default=None, help="LLM runs CSV (default results/runs_llm.csv)")
    m.add_argument("--out", default=None, help="summary path (default results/eval_summary.md)")
    args = p.parse_args()
    {"sample": cmd_sample, "run": cmd_run, "redteam": cmd_redteam, "summarize": cmd_summarize}[args.cmd](args)


if __name__ == "__main__":
    main()
