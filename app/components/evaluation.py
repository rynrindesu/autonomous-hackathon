"""Evaluation panel (PLAN §13, demo step 5).

Reads ``runs/eval/batch-*.json`` written by ``scripts/batch_eval.py`` and
renders it in the desk's visual language. The JSON is parsed directly; nothing
from the protocol code is imported, so the panel keeps working while the
agents and coordinator change underneath it.

Field meanings follow ``triad.metrics`` (BatchReport, RunMetrics,
NegotiationDelta). ``deltas[mode]`` compares ``mode`` against ``stub`` on the
same rows: ``changed_rate`` is the share of rows that commit a different
option, ``mean_cost_diff_eur`` is ``mode - stub`` (positive = mode costs more).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from .data import RUNS_DIR
from .format import fmt_eur, fmt_pct
from .render import badge, h

EVAL_DIR = RUNS_DIR / "eval"
RUN_COMMAND = "uv run python scripts/batch_eval.py --n 50 --modes stub,ai-off,fcfs"

OUTCOMES: list[tuple[str, str, str]] = [
    ("TURN1", "Agreed at Turn 1", "t1"),
    ("TURN2", "Agreed at Turn 2", "t2"),
    ("FALLBACK", "Fallback", "fb"),
    ("ESCALATED", "Escalated", "esc"),
]

MODE_NAMES = {
    "stub": "Stub negotiation",
    "llm": "LLM negotiation",
    "ai-off": "AI off",
    "fcfs": "First come, first served",
}
MODE_SUBS = {
    "stub": "three agents negotiate · code-only stubs",
    "llm": "three agents negotiate · language model",
    "ai-off": "no agents · deterministic fallback solver",
    "fcfs": "earliest safe slot · ignores costs",
}

# (report key, label, unit, digits). Lower is better for every row.
COST_ROWS: list[tuple[str, str, str, int]] = [
    ("mean_total_cost_eur", "Total cost", "EUR", 0),
    ("mean_holding_min", "Holding", "min", 1),
    ("mean_fuel_kg", "Extra fuel", "kg", 1),
    ("mean_co2_kg", "CO₂", "kg", 1),
    ("mean_arrival_delay_min", "Arrival delay", "min", 1),
    ("mean_missed_connections", "Missed connections", "pax", 1),
    ("mean_overtime_min", "Crew overtime", "min", 1),
    ("mean_next_leg_delay_min", "Next-leg delay", "min", 1),
]

COMPONENT_LABELS = {
    "arrival_delay": "Arrival delay",
    "divert": "Diversion",
    "fuel": "Fuel",
    "gate_change": "Gate change",
    "holding_stack": "Holding stack",
    "missed_connections": "Missed connections",
    "next_leg_delay": "Next-leg delay",
    "overtime": "Crew overtime",
    "runway_change": "Runway change",
    "swap": "Aircraft swap",
    "turbulence": "Turbulence",
}

CSS = r"""
<style>
.td-eval-meta {
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px 18px;
  margin: -4px 0 14px; padding: 8px 12px;
  border: 1px solid var(--td-line); background: rgba(251,250,246,.66);
  font-size: 10.5px; color: var(--td-muted);
}
.td-eval-meta b { font-family: var(--td-mono); font-weight: 500; color: var(--td-ink-2); }
.td-eval-meta .td-badge { margin-left: 4px; }

.td-eval-split { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(300px, 1fr); gap: 16px; align-items: stretch; }
.td-eval-split.even { grid-template-columns: repeat(2, minmax(0, 1fr)); }

.td-eval-card { background: var(--td-surface); border: 1px solid var(--td-line); border-radius: 2px; padding: 14px 16px 13px; }
.td-eval-card-title { font-family: var(--td-display); font-size: 19px; letter-spacing: .05em; text-transform: uppercase; color: var(--td-ink); }
.td-eval-card-sub { margin-top: 2px; font-size: 11px; line-height: 1.5; color: var(--td-muted); }

.td-eval-modes { margin-top: 12px; display: grid; gap: 10px; }
.td-eval-mode-row { display: grid; grid-template-columns: 200px minmax(0, 1fr) 54px; gap: 12px; align-items: center; }
.td-eval-mode-name { font-family: var(--td-display); font-size: 16px; letter-spacing: .04em; line-height: 1.05; color: var(--td-ink); display: flex; flex-wrap: wrap; align-items: center; gap: 5px; }
.td-eval-mode-sub { margin-top: 2px; font-family: var(--td-mono); font-size: 8.5px; letter-spacing: .03em; color: var(--td-muted); }
.td-eval-n { font-family: var(--td-mono); font-size: 10px; color: var(--td-muted); text-align: right; }

.td-eval-stack { display: flex; height: 30px; background: var(--td-paper-2); border: 1px solid var(--td-line); overflow: hidden; }
.td-eval-seg {
  display: flex; align-items: center; justify-content: center; min-width: 0;
  font-family: var(--td-mono); font-size: 11px; font-weight: 500; color: #fffdf6;
  border-right: 1px solid rgba(255,255,255,.45);
  transform-origin: left center; animation: td-eval-grow .6s cubic-bezier(.2,.7,.2,1) both;
}
.td-eval-seg:last-child { border-right: none; }
.td-eval-seg.t1 { background: var(--td-green); }
.td-eval-seg.t2 { background: var(--td-teal); background-image: repeating-linear-gradient(135deg, rgba(255,255,255,.09) 0 5px, transparent 5px 10px); }
.td-eval-seg.fb { background: var(--td-amber); }
.td-eval-seg.esc { background: var(--td-red); }
.td-eval-seg.sim { opacity: .82; background-image: repeating-linear-gradient(135deg, rgba(255,255,255,.16) 0 4px, transparent 4px 9px); }
.td-eval-swatch { width: 11px; height: 11px; display: inline-block; border: none; }
.td-eval-swatch.t1 { background: var(--td-green); }
.td-eval-swatch.t2 { background: var(--td-teal); }
.td-eval-swatch.fb { background: var(--td-amber); }
.td-eval-swatch.esc { background: var(--td-red); }

.td-eval-guarantee {
  position: relative; overflow: hidden; height: 100%; box-sizing: border-box;
  border: 1px solid #b9d5c6; border-left: 5px solid var(--td-green);
  background: linear-gradient(135deg, #eef7f1 0%, #fbfaf6 70%);
  padding: 14px 18px 14px; border-radius: 2px;
}
.td-eval-guarantee.fail { border-color: #ddb3ad; border-left-color: var(--td-red); background: linear-gradient(135deg, #fcf0ee 0%, #fbfaf6 70%); }
.td-eval-g-top { display: flex; align-items: flex-start; gap: 16px; }
.td-eval-g-num { font-family: var(--td-display); font-weight: 600; font-size: 86px; line-height: .78; color: var(--td-green); letter-spacing: -.01em; }
.td-eval-guarantee.fail .td-eval-g-num { color: var(--td-red); }
.td-eval-g-title { font-family: var(--td-display); font-size: 22px; line-height: 1.02; letter-spacing: .05em; text-transform: uppercase; color: var(--td-ink); }
.td-eval-g-text { margin-top: 9px; font-size: 11.5px; line-height: 1.55; color: var(--td-ink-2); }
.td-eval-g-text code { font-size: 10.5px; background: rgba(25,106,77,.08); padding: 0 3px; }
.td-eval-g-modes { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 4px; }
.td-eval-g-flow { margin-top: 12px; display: flex; flex-wrap: wrap; align-items: center; gap: 5px; }
.td-eval-g-step { font-family: var(--td-mono); font-size: 9px; letter-spacing: .04em; padding: 3px 7px; border: 1px solid #a9cbbb; background: rgba(255,255,255,.6); color: #155c42; }
.td-eval-g-step.end { background: var(--td-green); border-color: var(--td-green); color: #fffdf6; }
.td-eval-guarantee.fail .td-eval-g-step { border-color: #d7a8a2; color: #922b27; }
.td-eval-guarantee.fail .td-eval-g-step.end { background: var(--td-red); border-color: var(--td-red); color: #fffdf6; }
.td-eval-g-plus { font-family: var(--td-mono); font-size: 10px; color: var(--td-muted); }

.td-eval-bars { margin-top: 12px; display: grid; gap: 9px; }
.td-eval-bar-row { display: grid; grid-template-columns: 200px minmax(0, 1fr) 150px; gap: 12px; align-items: center; }
.td-eval-track { position: relative; height: 22px; background: var(--td-paper-2); border: 1px solid var(--td-line-2); }
.td-eval-fill {
  position: absolute; inset: 0 auto 0 0; background: var(--td-deep-2);
  transform-origin: left center; animation: td-eval-grow .7s cubic-bezier(.2,.7,.2,1) both;
}
.td-eval-fill.ref { background: var(--td-teal); }
.td-eval-fill.sim { background: #6d7f80; background-image: repeating-linear-gradient(135deg, rgba(255,255,255,.18) 0 4px, transparent 4px 9px); }
.td-eval-fill.amber { background: var(--td-amber); }
.td-eval-fill.violet { background: var(--td-violet); }
.td-eval-fill-label { position: absolute; left: 8px; top: 50%; transform: translateY(-50%); font-family: var(--td-mono); font-size: 11px; font-weight: 500; color: #fffdf6; white-space: nowrap; mix-blend-mode: normal; }
.td-eval-fill-label.out { color: var(--td-ink-2); }
.td-eval-bar-side { font-family: var(--td-mono); font-size: 10.5px; text-align: right; white-space: nowrap; }

.td-eval-delta { display: block; margin-top: 2px; font-family: var(--td-mono); font-size: 9.5px; letter-spacing: .01em; }
.td-eval-delta.worse { color: var(--td-red); }
.td-eval-delta.better { color: var(--td-green); }
.td-eval-delta.same, .td-eval-delta.ref { color: var(--td-muted-2); }
.td-eval-inline.worse { color: var(--td-red); }
.td-eval-inline.better { color: var(--td-green); }
.td-eval-inline.same, .td-eval-inline.ref { color: var(--td-muted); }

table.td-eval-table { min-width: 620px; }
.td-eval-table th.num, .td-eval-table td.num { text-align: right; }
.td-eval-table th.mode-col { min-width: 140px; }
.td-eval-table tr.total td { background: #f3f1e9; font-weight: 500; }
.td-eval-table tr.total td.num { font-size: 12.5px; color: var(--td-ink); }

.td-eval-stat { display: flex; align-items: baseline; gap: 10px; margin-top: 12px; }
.td-eval-stat-big { font-family: var(--td-display); font-weight: 600; font-size: 44px; line-height: .9; color: var(--td-ink); letter-spacing: .01em; }
.td-eval-stat-text { font-size: 11.5px; line-height: 1.45; color: var(--td-ink-2); }
.td-eval-list { margin-top: 12px; display: grid; gap: 9px; }
.td-eval-list-row { display: grid; grid-template-columns: 170px minmax(0, 1fr) 140px; gap: 10px; align-items: center; }
.td-eval-list-row .td-eval-track { height: 16px; }
.td-eval-foot { margin-top: 14px; padding-top: 9px; border-top: 1px solid var(--td-line); font-size: 10.5px; line-height: 1.55; color: var(--td-muted); }
.td-eval-foot b { color: var(--td-ink-2); font-weight: 500; }
.td-eval-empty code { display: inline-block; margin-top: 12px; padding: 8px 12px; background: var(--td-deep); color: #f0ead9; font-size: 12px; border-radius: 2px; }

@keyframes td-eval-grow { from { transform: scaleX(0); } to { transform: scaleX(1); } }
@media (prefers-reduced-motion: reduce) { .td-eval-seg, .td-eval-fill { animation: none; } }
@media (max-width: 1180px) {
  .td-eval-split, .td-eval-split.even { grid-template-columns: 1fr; }
}
@media (max-width: 820px) {
  .td-eval-mode-row, .td-eval-bar-row, .td-eval-list-row { grid-template-columns: 1fr; gap: 4px; }
  .td-eval-n, .td-eval-bar-side { text-align: left; }
}
</style>
"""


# --------------------------------------------------------------------------- data


@dataclass
class EvalBatch:
    path: Path
    n_rows: int
    seed: Any
    impl: str
    modes: list[str]
    reports: dict[str, dict[str, Any]]
    deltas: dict[str, dict[str, Any]]
    error_counts: dict[str, int]
    simulated: set[str] = field(default_factory=set)

    @property
    def ref(self) -> str:
        """Reference mode for deltas: batch_eval compares every mode with ``stub``."""
        if "stub" in self.reports:
            return "stub"
        return self.modes[0] if self.modes else ""

    @property
    def total_runs(self) -> int:
        return sum(int(r.get("n_runs") or 0) for r in self.reports.values())

    @property
    def unsafe_total(self) -> int:
        return sum(int(r.get("unsafe_commits") or 0) for r in self.reports.values())


def batch_files() -> list[Path]:
    """Batch reports, newest first."""
    if not EVAL_DIR.exists():
        return []
    files = [p for p in EVAL_DIR.glob("batch-*.json") if p.is_file()]
    return sorted(files, key=lambda p: (p.stat().st_mtime, p.name), reverse=True)


@lru_cache(maxsize=16)
def _load(path_str: str, mtime: float) -> EvalBatch:  # mtime busts the cache on rewrite
    raw = json.loads(Path(path_str).read_text(encoding="utf-8"))
    reports = {str(k): v for k, v in (raw.get("reports") or {}).items() if isinstance(v, dict)}
    modes = [str(m) for m in (raw.get("modes") or reports.keys()) if str(m) in reports]
    simulated = {m for m in modes if m == "fcfs"}
    for mode, runs in (raw.get("runs") or {}).items():
        if isinstance(runs, list) and any(isinstance(r, dict) and r.get("simulated") for r in runs):
            simulated.add(str(mode))
    return EvalBatch(
        path=Path(path_str),
        n_rows=int(raw.get("n_rows") or 0),
        seed=raw.get("seed"),
        impl=str(raw.get("impl") or ""),
        modes=modes,
        reports=reports,
        deltas={str(k): v for k, v in (raw.get("deltas") or {}).items() if isinstance(v, dict)},
        error_counts={str(k): int(v) for k, v in (raw.get("error_counts") or {}).items()},
        simulated=simulated,
    )


def load_batch(path: Path) -> EvalBatch:
    return _load(str(path), path.stat().st_mtime)


def batch_label(path: Path) -> str:
    try:
        stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%d %b %H:%M")
    except OSError:
        stamp = ""
    return f"{path.name} · {stamp}" if stamp else path.name


# --------------------------------------------------------------------------- formatting


def _num(value: Any, digits: int = 1) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number:,.{digits}f}"


def _signed(value: float, digits: int, unit: str) -> str:
    if unit == "EUR":
        sign = "+" if value > 0 else "−" if value < 0 else "±"
        return f"{sign}€{abs(value):,.0f}"
    sign = "+" if value > 0 else "−" if value < 0 else "±"
    return f"{sign}{abs(value):,.{digits}f}"


def _tone(diff: float | None) -> str:
    """Lower is better for every evaluation metric."""
    if diff is None:
        return "same"
    if abs(diff) < 1e-9:
        return "same"
    return "worse" if diff > 0 else "better"


def _mode_label_html(batch: EvalBatch, mode: str) -> str:
    sim = (
        badge("Simulated", "amber", "Simulated baseline, not a real procedure")
        if mode in batch.simulated
        else ""
    )
    ref = (
        badge("Reference", "blue", "Deltas are measured against this mode")
        if mode == batch.ref and len(batch.modes) > 1
        else ""
    )
    sub = " · ".join(part for part in (mode, MODE_SUBS.get(mode, "")) if part)
    return (
        "<div>"
        f'<div class="td-eval-mode-name">{h(MODE_NAMES.get(mode, mode))}{sim}{ref}</div>'
        f'<div class="td-eval-mode-sub">{h(sub)}</div>'
        "</div>"
    )


# --------------------------------------------------------------------------- HTML builders


def empty_html() -> str:
    return (
        '<div class="td-empty-state td-eval-empty">'
        '<div class="td-kicker" style="color:var(--td-muted);margin-bottom:8px;">Evaluation</div>'
        "<h3>No batch report yet</h3>"
        "<p>Run the batch evaluation from the repository root. It writes a report to "
        "<span style=\"font-family:var(--td-mono)\">runs/eval/</span> and this view picks it up.</p>"
        f"<code>{h(RUN_COMMAND)}</code>"
        "</div>"
    )


def meta_html(batch: EvalBatch) -> str:
    mode_bits = []
    for mode in batch.modes:
        sim = badge("Simulated", "amber") if mode in batch.simulated else ""
        mode_bits.append(f"<b>{h(mode)}</b>{sim}")
    errors = sum(batch.error_counts.values())
    err = (
        f'<span class="td-prov-item">Errors <b style="color:var(--td-red)">{errors}</b></span>'
        if errors
        else '<span class="td-prov-item">Errors <b>0</b></span>'
    )
    return (
        '<div class="td-eval-meta">'
        f'<span class="td-prov-item">Sample <b>{batch.n_rows} DOT rows</b></span>'
        f'<span class="td-prov-item">Seed <b>{h(batch.seed)}</b></span>'
        f'<span class="td-prov-item">Agents <b>{h(batch.impl or "—")}</b></span>'
        f'<span class="td-prov-item">Modes {" · ".join(mode_bits)}</span>'
        f"{err}"
        f'<span class="td-prov-item" style="margin-left:auto;">File <b>{h(batch.path.name)}</b></span>'
        "</div>"
    )


def strip_html(batch: EvalBatch) -> str:
    ref = batch.reports.get(batch.ref, {})
    n_ref = int(ref.get("n_runs") or 0)
    outcomes = ref.get("outcomes") or {}
    t1, t2 = int(outcomes.get("TURN1") or 0), int(outcomes.get("TURN2") or 0)
    agreed = (t1 + t2) / n_ref if n_ref else None
    feas = ref.get("feasible_ge2_rate")
    feas_sub = f"{fmt_pct(feas)} have ≥ 2 safe options" if feas is not None else "same rows in every mode"

    unsafe = batch.unsafe_total
    unsafe_cls = "td-status-unsafe" if unsafe else "td-status-safe"

    # Cost gap vs the deterministic fallback (prefer ai-off, else first compared mode).
    cmp_mode = "ai-off" if "ai-off" in batch.deltas else next(iter(batch.deltas), "")
    delta = batch.deltas.get(cmp_mode, {})
    diff = delta.get("mean_cost_diff_eur")
    cmp_name = MODE_NAMES.get(cmp_mode, cmp_mode)
    if diff is None:
        gap_label, gap_value, gap_sub = "Cost vs fallback", "—", "no comparison in this batch"
    else:
        ref_name = MODE_NAMES.get(batch.ref, batch.ref)
        gap_label = f"{ref_name} saves" if diff >= 0 else f"{ref_name} costs extra"
        gap_value = fmt_eur(abs(diff))
        gap_sub = f"per row vs {cmp_name} · {fmt_pct(delta.get('changed_rate'))} of rows differ"

    vt, vy = int(ref.get("vetoes_total") or 0), int(ref.get("veto_yield") or 0)
    veto_value = f"{vy} / {vt}" if vt else "—"
    veto_sub = f"{fmt_pct(vy / vt)} of vetoes need a perceived fact" if vt else "no agent vetoes recorded"

    def cell(label: str, value: str, sub: str, cls: str = "") -> str:
        return (
            '<div class="td-stat">'
            f'<div class="td-stat-label">{h(label)}</div>'
            f'<div class="td-stat-value {cls}">{value}</div>'
            f'<div class="td-stat-sub">{h(sub)}</div>'
            "</div>"
        )

    return (
        '<div class="td-status-grid" style="margin-top:0;">'
        + cell("Rows evaluated", h(batch.n_rows), feas_sub)
        + cell(
            f"Agreed · {MODE_NAMES.get(batch.ref, batch.ref)}",
            h(fmt_pct(agreed)) if agreed is not None else "—",
            f"{t1} at Turn 1 · {t2} at Turn 2",
            "td-status-consensus" if agreed else "",
        )
        + cell("Unsafe commits", h(unsafe), f"of {batch.total_runs} runs · blocked by design", unsafe_cls)
        + cell(gap_label, h(gap_value), gap_sub, "mono" if diff is None else "")
        + cell("Veto-yield", h(veto_value), veto_sub)
        + "</div>"
    )


def outcomes_html(batch: EvalBatch) -> str:
    rows = []
    for mode in batch.modes:
        report = batch.reports[mode]
        n = int(report.get("n_runs") or 0)
        counts = report.get("outcomes") or {}
        segs = []
        for index, (key, label, cls) in enumerate(OUTCOMES):
            count = int(counts.get(key) or 0)
            if not count or not n:
                continue
            share = count / n * 100
            text = str(count) if share >= 5 else ""
            sim = " sim" if mode in batch.simulated else ""
            segs.append(
                f'<div class="td-eval-seg {cls}{sim}" style="flex:0 0 {share:.3f}%;animation-delay:{index * 0.08:.2f}s" '
                f'title="{h(label)}: {count} of {n}">{text}</div>'
            )
        if not segs:
            segs.append('<div class="td-eval-seg" style="flex:1;color:var(--td-muted)">no runs</div>')
        rows.append(
            '<div class="td-eval-mode-row">'
            f"{_mode_label_html(batch, mode)}"
            f'<div class="td-eval-stack">{"".join(segs)}</div>'
            f'<div class="td-eval-n">n={n}</div>'
            "</div>"
        )
    legend = "".join(
        f'<span class="td-legend-item"><span class="td-eval-swatch {cls}"></span>{h(label)}</span>'
        for _, label, cls in OUTCOMES
    )
    return (
        '<div class="td-eval-card">'
        '<div class="td-eval-card-title">How each run ended</div>'
        '<div class="td-eval-card-sub">Same rows in every mode. Negotiation has two turns; '
        "a fallback means the code solver picked the cheapest safe option.</div>"
        f'<div class="td-eval-modes">{"".join(rows)}</div>'
        f'<div class="td-legend" style="margin-top:12px;">{legend}</div>'
        "</div>"
    )


def guarantee_html(batch: EvalBatch) -> str:
    unsafe = batch.unsafe_total
    chips = "".join(
        badge(
            f"{mode} {int(batch.reports[mode].get('unsafe_commits') or 0)}/{int(batch.reports[mode].get('n_runs') or 0)}",
            "red" if batch.reports[mode].get("unsafe_commits") else "green",
        )
        for mode in batch.modes
    )
    if unsafe:
        title = "Unsafe commit recorded"
        text = (
            f"{unsafe} committed option(s) in this batch failed a hard check at commit. "
            "That should be impossible: inspect the run logs before using these numbers."
        )
        cls = "td-eval-guarantee fail"
    else:
        title = "Unsafe commits · built-in guarantee"
        text = (
            "Before anything is committed, <code>assert_commit_safe()</code> re-runs the shared checks "
            "and all three agents' hard checks on the chosen option. If any check fails, the commit is "
            "refused. The number is zero by construction; the batch confirms it in "
            f"<b>{batch.total_runs}</b> runs across {len(batch.modes)} modes."
        )
        cls = "td-eval-guarantee"
    steps = ["Shared checks", "ATC checks", "Pilot checks", "Ground checks"]
    pipeline = (
        '<div class="td-eval-g-flow">'
        + "".join(f'<span class="td-eval-g-step">{h(s)}</span><span class="td-eval-g-plus">+</span>' for s in steps[:-1])
        + f'<span class="td-eval-g-step">{h(steps[-1])}</span>'
        + '<span class="td-eval-g-plus">→</span><span class="td-eval-g-step end">Commit</span>'
        + "</div>"
    )
    return (
        f'<div class="{cls}">'
        '<div class="td-eval-g-top">'
        f'<div class="td-eval-g-num">{unsafe}</div>'
        f'<div><div class="td-section-kicker">Commit gate</div><div class="td-eval-g-title">{h(title)}</div></div>'
        "</div>"
        f'<div class="td-eval-g-text">{text}</div>'
        f"{pipeline}"
        '<div class="td-minihead" style="margin-top:12px;">Measured per mode · unsafe / runs</div>'
        f'<div class="td-eval-g-modes" style="margin-top:0;">{chips}</div>'
        "</div>"
    )


def cost_bars_html(batch: EvalBatch) -> str:
    totals = {m: batch.reports[m].get("mean_total_cost_eur") for m in batch.modes}
    present = [float(v) for v in totals.values() if v is not None]
    top = max(present) if present else 0.0
    ref_cost = totals.get(batch.ref)
    rows = []
    for index, mode in enumerate(batch.modes):
        value = totals[mode]
        width = (float(value) / top * 100) if value is not None and top else 0
        fill_cls = "ref" if mode == batch.ref else ("sim" if mode in batch.simulated else "")
        if mode == batch.ref:
            side = '<span class="td-eval-inline ref">reference</span>'
        elif value is not None and ref_cost is not None:
            diff = float(value) - float(ref_cost)
            pct = f" ({diff / float(ref_cost) * 100:+.0f}%)" if ref_cost else ""
            side = f'<span class="td-eval-inline {_tone(diff)}">{_signed(diff, 0, "EUR")}{pct}</span>'
        else:
            side = '<span class="td-eval-inline same">—</span>'
        rows.append(
            '<div class="td-eval-bar-row">'
            f"{_mode_label_html(batch, mode)}"
            '<div class="td-eval-track">'
            f'<div class="td-eval-fill {fill_cls}" style="width:{width:.2f}%;animation-delay:{index * 0.08:.2f}s"></div>'
            f'<div class="td-eval-fill-label{" out" if width < 22 else ""}">{h(fmt_eur(value)) if value is not None else "—"}</div>'
            "</div>"
            f'<div class="td-eval-bar-side">{side}</div>'
            "</div>"
        )
    return f'<div class="td-eval-bars">{"".join(rows)}</div>'


def cost_table_html(batch: EvalBatch) -> str:
    ref = batch.reports.get(batch.ref, {})
    head = "".join(
        f'<th class="num mode-col">{h(mode)}'
        + (" · simulated" if mode in batch.simulated else "")
        + ("" if mode != batch.ref or len(batch.modes) == 1 else " · ref")
        + "</th>"
        for mode in batch.modes
    )
    body = []
    for key, label, unit, digits in COST_ROWS:
        cells = []
        for mode in batch.modes:
            value = batch.reports[mode].get(key)
            shown = fmt_eur(value) if unit == "EUR" and value is not None else _num(value, digits)
            if mode == batch.ref or len(batch.modes) == 1:
                delta = ""
            elif value is not None and ref.get(key) is not None:
                diff = float(value) - float(ref[key])
                delta = f'<span class="td-eval-delta {_tone(diff)}">{_signed(diff, digits, unit)} vs {h(batch.ref)}</span>'
            else:
                delta = '<span class="td-eval-delta same">—</span>'
            cells.append(f'<td class="num">{h(shown)}{delta}</td>')
        cls = ' class="total"' if key == "mean_total_cost_eur" else ""
        body.append(
            f"<tr{cls}><td>{h(label)}</td><td class='mono muted'>{h(unit)}</td>{''.join(cells)}</tr>"
        )
    return (
        '<div class="td-table-wrap">'
        '<table class="td-table td-eval-table">'
        f"<thead><tr><th>Mean per row</th><th>Unit</th>{head}</tr></thead>"
        f"<tbody>{''.join(body)}</tbody>"
        "</table></div>"
        '<div class="td-table-note">Means over runs that committed an option. Lower is better on every row. '
        "Green: lower than the reference; red: higher.</div>"
    )


def components_table_html(batch: EvalBatch) -> str:
    keys: list[str] = sorted(
        {k for m in batch.modes for k in (batch.reports[m].get("mean_cost_components_eur") or {})},
        key=lambda k: -float((batch.reports.get(batch.ref, {}).get("mean_cost_components_eur") or {}).get(k, 0) or 0),
    )
    if not keys:
        return '<div class="td-note">This batch has no cost breakdown.</div>'
    ref_comp = batch.reports.get(batch.ref, {}).get("mean_cost_components_eur") or {}
    head = "".join(f'<th class="num mode-col">{h(m)}</th>' for m in batch.modes)
    rows = []
    for key in keys:
        cells = []
        for mode in batch.modes:
            comp = batch.reports[mode].get("mean_cost_components_eur") or {}
            value = comp.get(key)
            delta = ""
            if mode != batch.ref and value is not None and key in ref_comp:
                diff = float(value) - float(ref_comp[key])
                if abs(diff) >= 0.5:
                    delta = f'<span class="td-eval-delta {_tone(diff)}">{_signed(diff, 0, "EUR")}</span>'
            cells.append(f'<td class="num">{h(fmt_eur(value)) if value is not None else "—"}{delta}</td>')
        rows.append(f"<tr><td>{h(COMPONENT_LABELS.get(key, key.replace('_', ' ')))}</td>{''.join(cells)}</tr>")
    return (
        '<div class="td-table-wrap">'
        '<table class="td-table td-eval-table">'
        f"<thead><tr><th>Cost component</th>{head}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table></div>"
        '<div class="td-table-note">EUR per row, summed over the three agents with the weights in config/costs.yaml. '
        "Components add up to the total.</div>"
    )


def delta_card_html(batch: EvalBatch) -> str:
    compared = [m for m in batch.modes if m in batch.deltas]
    if not compared:
        return (
            '<div class="td-eval-card"><div class="td-eval-card-title">Negotiation-delta</div>'
            f'<div class="td-eval-card-sub">No comparison: this batch has no {h(batch.ref)} mode to compare against.</div></div>'
        )
    lead = "ai-off" if "ai-off" in compared else compared[0]
    lead_d = batch.deltas[lead]
    rows = []
    for index, mode in enumerate(compared):
        d = batch.deltas[mode]
        rate = d.get("changed_rate")
        diff = d.get("mean_cost_diff_eur")
        width = float(rate) * 100 if rate is not None else 0
        side = (
            f'<span class="td-eval-inline {_tone(diff)}">{_signed(float(diff), 0, "EUR")} / row</span>'
            if diff is not None
            else '<span class="td-eval-inline same">—</span>'
        )
        rows.append(
            '<div class="td-eval-list-row">'
            f"{_mode_label_html(batch, mode)}"
            '<div class="td-eval-track">'
            f'<div class="td-eval-fill {"sim" if mode in batch.simulated else "amber"}" '
            f'style="width:{width:.2f}%;animation-delay:{index * 0.08:.2f}s"></div>'
            f'<div class="td-eval-fill-label out" style="left:calc({min(width, 80):.2f}% + 6px)">{h(fmt_pct(rate))}</div>'
            "</div>"
            f'<div class="td-eval-bar-side">{side}</div>'
            "</div>"
        )
    lead_diff = lead_d.get("mean_cost_diff_eur")
    if lead_diff is None:
        sentence = "of rows commit a different option."
    else:
        more_less = "more" if lead_diff >= 0 else "less"
        sentence = (
            "of rows commit a different option without negotiation. "
            f"Across all matched rows, that costs <b>{h(fmt_eur(abs(lead_diff)))}</b> {more_less} per row on average."
        )
    return (
        '<div class="td-eval-card">'
        '<div class="td-eval-card-title">Negotiation-delta</div>'
        f'<div class="td-eval-card-sub">Same rows, compared with {h(MODE_NAMES.get(batch.ref, batch.ref).lower())}: '
        "how often the committed option differs, and the mean cost difference (mode minus reference).</div>"
        '<div class="td-eval-stat">'
        f'<div class="td-eval-stat-big">{h(fmt_pct(lead_d.get("changed_rate")))}</div>'
        f'<div class="td-eval-stat-text">{sentence}<br><span style="color:var(--td-muted)">'
        f"{h(MODE_NAMES.get(lead, lead))} vs {h(batch.ref)} · {int(lead_d.get('n_rows') or 0)} matched rows</span></div>"
        "</div>"
        f'<div class="td-eval-list">{"".join(rows)}</div>'
        "</div>"
    )


def veto_card_html(batch: EvalBatch) -> str:
    with_vetoes = [m for m in batch.modes if int(batch.reports[m].get("vetoes_total") or 0) > 0]
    without = [m for m in batch.modes if m not in with_vetoes]
    if not with_vetoes:
        return (
            '<div class="td-eval-card"><div class="td-eval-card-title">Veto-yield</div>'
            '<div class="td-eval-card-sub">No agent vetoes in this batch. Vetoes only come from the agents, '
            "so modes without agents have none.</div></div>"
        )
    lead = batch.ref if batch.ref in with_vetoes else with_vetoes[0]
    lr = batch.reports[lead]
    lt, ly = int(lr.get("vetoes_total") or 0), int(lr.get("veto_yield") or 0)
    rows = []
    for index, mode in enumerate(with_vetoes):
        r = batch.reports[mode]
        vt, vy = int(r.get("vetoes_total") or 0), int(r.get("veto_yield") or 0)
        width = vy / vt * 100 if vt else 0
        rows.append(
            '<div class="td-eval-list-row">'
            f"{_mode_label_html(batch, mode)}"
            '<div class="td-eval-track">'
            f'<div class="td-eval-fill violet" style="width:{width:.2f}%;animation-delay:{index * 0.08:.2f}s"></div>'
            f'<div class="td-eval-fill-label out" style="left:calc({min(width, 80):.2f}% + 6px)">{h(fmt_pct(vy / vt if vt else None))}</div>'
            "</div>"
            f'<div class="td-eval-bar-side">{vy} of {vt} vetoes</div>'
            "</div>"
        )
    note = (
        f'<div class="td-table-note">{h(", ".join(without))}: no vetoes, because no agents run in '
        f'{"that mode" if len(without) == 1 else "those modes"}.</div>'
        if without
        else ""
    )
    return (
        '<div class="td-eval-card">'
        '<div class="td-eval-card-title">Veto-yield</div>'
        '<div class="td-eval-card-sub">Vetoes whose failing check depends on a perceived fact: a NOTAM closure, '
        "an MEL item that can't be deferred, a turbulence report. Structured data alone would not raise them.</div>"
        '<div class="td-eval-stat">'
        f'<div class="td-eval-stat-big">{ly}<span style="font-size:.5em;color:var(--td-muted)"> / {lt}</span></div>'
        f'<div class="td-eval-stat-text">Turn 1 vetoes in {h(MODE_NAMES.get(lead, lead).lower())} '
        f"that need a perceived fact ({h(fmt_pct(ly / lt if lt else None))}).</div>"
        "</div>"
        f'<div class="td-eval-list">{"".join(rows)}</div>'
        f"{note}"
        "</div>"
    )


def footnote_html(batch: EvalBatch) -> str:
    sim = ", ".join(sorted(batch.simulated))
    sim_text = (
        f"<b>{h(sim)}</b> is a <b>simulated</b> first-come-first-served baseline: it commits the earliest "
        "safe arrival slot and ignores costs and agent priorities. It does not model a real ATC procedure. "
        if sim
        else ""
    )
    return (
        '<div class="td-eval-foot">'
        f"{sim_text}"
        f"Sample: {batch.n_rows} DOT rows with WEATHER_DELAY &gt; 15 or LATE_AIRCRAFT_DELAY &gt; 20, "
        f"seed {h(batch.seed)}, agent implementation <b>{h(batch.impl or '—')}</b>. "
        f"Source: <span style=\"font-family:var(--td-mono)\">runs/eval/{h(batch.path.name)}</span>."
        "</div>"
    )


# --------------------------------------------------------------------------- Streamlit entry point


def render_panel() -> None:
    """Render the Evaluation view. Call inside a tab or container."""
    import streamlit as st

    from .render import _section

    def md(html: str) -> None:
        st.markdown(html, unsafe_allow_html=True)

    md(CSS)
    files = batch_files()
    if not files:
        md(_section("Evidence", "Evaluation", "batch report"))
        md(empty_html())
        return

    head = st.container()  # filled once the batch is known, so the title sits above the picker
    path = files[0]
    if len(files) > 1:
        options = [str(p) for p in files]
        if st.session_state.get("eval_batch") not in options:
            st.session_state["eval_batch"] = options[0]
        pick, _ = st.columns([2, 3])
        with pick:
            choice = st.selectbox(
                "Batch report",
                options,
                key="eval_batch",
                format_func=lambda value: batch_label(Path(value)),
                help="Newest first. Written by scripts/batch_eval.py.",
            )
        path = Path(choice)

    try:
        batch = load_batch(path)
    except Exception as exc:  # noqa: BLE001
        with head:
            md(_section("Evidence", "Evaluation", path.name))
        st.error(f"Could not read {path.name}: {exc}")
        return
    if not batch.modes:
        with head:
            md(_section("Evidence", "Evaluation", path.name))
        md(empty_html())
        return

    sim_aside = f" · {', '.join(sorted(batch.simulated))} simulated" if batch.simulated else ""
    with head:
        md(_section("Evidence", "Evaluation", f"n = {batch.n_rows} rows · seed {batch.seed}{sim_aside}"))
    md(meta_html(batch))
    md(strip_html(batch))

    errors = sum(batch.error_counts.values())
    if errors:
        md(
            '<div class="td-banner td-banner-amber"><div class="td-banner-mark">ERRORS</div><div>'
            '<div class="td-banner-title">Some runs failed</div>'
            f'<div class="td-banner-text">{errors} run(s) raised an error and are not counted: '
            + h(", ".join(f"{k} {v}" for k, v in batch.error_counts.items()))
            + "</div></div></div>"
        )

    md(_section("Outcomes", "Turn histogram", "agreed at Turn 1 / Turn 2 · fallback · escalated"))
    md(f'<div class="td-eval-split">{outcomes_html(batch)}{guarantee_html(batch)}</div>')

    md(_section("Cost", "Cost per resolution", f"mean per row · delta vs {batch.ref}"))
    md(
        '<div class="td-eval-card" style="margin-bottom:12px;">'
        '<div class="td-eval-card-title">Mean total cost</div>'
        '<div class="td-eval-card-sub">EUR per row for the committed option, all three agents\' costs summed.</div>'
        f"{cost_bars_html(batch)}"
        "</div>"
    )
    md(cost_table_html(batch))
    with st.expander("Cost by component"):
        md(components_table_html(batch))

    md(_section("Value of negotiation", "Negotiation-delta and veto-yield", f"vs {batch.ref}"))
    md(f'<div class="td-eval-split even">{delta_card_html(batch)}{veto_card_html(batch)}</div>')

    md(footnote_html(batch))
