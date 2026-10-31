"""Run metrics, batch aggregation and negotiation delta (PLAN §13).

Sources of each number
----------------------
* Outcome, fallback reason, turn, committed option, final checks and disclosed
  costs come from the ``Resolution``.
* Token / latency usage, feasible-option count and veto-yield come from the
  ``ConsensusLog``.
* Physical quantities that need private data (extra fuel, missed connections,
  overtime, next-leg delay) and the per-component cost breakdown need the
  ``DisruptionEvent`` and agents. Pass them as ``event=`` / ``agents=``; without
  them those fields stay ``None`` / empty. Costs use exactly the fallback
  solver's function: the sum of ``agent.cost_eur(public, option)`` over the three
  agents (``config/costs.yaml`` weights).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from statistics import mean
from typing import Any, Literal

from pydantic import BaseModel

from triad.config import load_yaml
from triad.schemas import AgentRole, CandidateOption, DisruptionEvent, LogEntry, Resolution

Outcome = Literal["TURN1", "TURN2", "TURN3", "FALLBACK", "ESCALATED"]
ROLES = (AgentRole.ATC, AgentRole.PILOT, AgentRole.GROUND)
DIVERT_ID = "OPT-DIV"


class RunMetrics(BaseModel):
    run_id: str
    label: str = ""  # comparison mode, e.g. "stub", "ai-off", "fcfs"
    simulated: bool = False  # True for the FCFS baseline
    outcome: Outcome
    status: str
    turn: int
    reason: str = ""
    fallback_reason: str | None = None
    option_id: str | None = None
    unsafe_commit: bool = False
    n_feasible: int | None = None  # non-divert generated options passing shared + every agent check
    vetoes_total: int = 0
    veto_yield: int = 0
    tokens_by_agent: dict[str, int] = {}
    ms_by_agent: dict[str, float] = {}
    # committed option
    holding_min: int | None = None
    arrival_delay_min: int | None = None  # arrival slot - scheduled arrival (original_eta)
    fuel_kg: float | None = None  # extra fuel burned vs the planned trip (holding / absorb / speed-up)
    co2_kg: float | None = None
    missed_connections: int | None = None  # passengers
    overtime_min: int | None = None
    next_leg_delay_min: int | None = None
    cost_components_eur: dict[str, float] = {}
    total_cost_eur: float | None = None


class BatchReport(BaseModel):
    label: str = ""
    n_runs: int
    outcomes: dict[str, int]
    turns_histogram: dict[str, int] = {}  # turn at which the run ended (1-3), consensus or fallback
    unsafe_commits: int
    feasible_ge2_rate: float | None  # over runs that report n_feasible
    veto_yield: int
    vetoes_total: int
    mean_cost_components_eur: dict[str, float]
    mean_total_cost_eur: float | None
    mean_holding_min: float | None
    mean_fuel_kg: float | None
    mean_co2_kg: float | None
    mean_arrival_delay_min: float | None
    mean_missed_connections: float | None
    mean_overtime_min: float | None
    mean_next_leg_delay_min: float | None
    total_tokens: int


class NegotiationDelta(BaseModel):
    n_rows: int
    changed_rate: float | None
    mean_cost_diff_eur: float | None  # mean(b.total - a.total) over rows where both committed


# --------------------------------------------------------------------------- log helpers


def _entries(log: Any) -> list[LogEntry]:
    if log is None:
        return []
    return list(getattr(log, "entries", log))


def _usage_by_agent(entries: list[LogEntry]) -> tuple[dict[str, int], dict[str, float]]:
    tokens: dict[str, int] = {}
    ms: dict[str, float] = {}
    for entry in entries:
        for role, usage in (entry.usage or {}).items():
            if not isinstance(usage, dict):
                continue
            tokens[role] = tokens.get(role, 0) + int(usage.get("prompt_tokens", 0) or 0) + int(
                usage.get("completion_tokens", 0) or 0
            )
            ms[role] = round(ms.get(role, 0.0) + float(usage.get("ms", 0.0) or 0.0), 1)
    return tokens, ms


def veto_counts(log: Any) -> tuple[int, int]:
    """Return ``(vetoes_total, veto_yield)`` from the Turn 1 PROPOSAL entries.

    Rule: a veto counts towards *veto-yield* when the ``ConstraintCheck`` it
    references (``veto.check_id`` looked up in the same proposal's ``checks``)
    has a non-empty ``facts_used`` list, i.e. its verdict depends on a
    ``PerceivedFact`` (NOTAM closure, MEL deferrability, turbulence...). Vetoes
    whose check is missing from the payload count in the total only.
    """
    total = 0
    yielded = 0
    for entry in _entries(log):
        if entry.event != "PROPOSAL":
            continue
        checks = {c.get("check_id"): c for c in entry.payload.get("checks", []) or []}
        for veto in entry.payload.get("vetoes", []) or []:
            total += 1
            check = checks.get(veto.get("check_id"))
            if check and check.get("facts_used"):
                yielded += 1
    return total, yielded


def feasible_count(log: Any) -> int | None:
    """Non-divert generated options that pass shared checks and no agent vetoed.

    Uses the Turn 1 vetoes; for AI-off runs (no proposals) the fallback pool.
    Returns ``None`` if the log carries neither.
    """
    entries = _entries(log)
    generated = next((e for e in entries if e.event == "OPTIONS_GENERATED"), None)
    if generated is None:
        return None
    shared_ok = [o for o in generated.payload.get("shared_passed", []) if o != DIVERT_ID]
    proposals = [e for e in entries if e.event == "PROPOSAL"]
    if proposals:
        vetoed = {
            v.get("option_id") for e in proposals for v in e.payload.get("vetoes", []) or []
        }
        return sum(1 for o in shared_ok if o not in vetoed)
    pool = next(
        (e.payload.get("pool") for e in entries if e.event == "FALLBACK_INVOKED" and "pool" in e.payload),
        None,
    )
    if pool is not None:
        return sum(1 for o in pool if o != DIVERT_ID)
    if any(e.event == "ESCALATED" for e in entries):
        return 0
    return None


# --------------------------------------------------------------------------- option metrics


def outcome_of(resolution: Resolution) -> Outcome:
    if resolution.status == "ESCALATED" or resolution.option is None:
        return "ESCALATED"
    if resolution.status == "FALLBACK":
        return "FALLBACK"
    if resolution.turn <= 1:
        return "TURN1"
    return "TURN2" if resolution.turn == 2 else "TURN3"


def is_unsafe_commit(resolution: Resolution) -> bool:
    """A committed option is unsafe if its final re-check is missing or any hard check failed."""
    if resolution.option is None:
        return False
    if not resolution.checks:
        return True
    return any(c.hard and not c.passed for c in resolution.checks)


def cost_breakdown(
    event: DisruptionEvent, option: CandidateOption, agents: Mapping[AgentRole, Any]
) -> dict[str, float]:
    """Per-component EUR cost, summed over agents with the fallback solver's ``cost_eur``."""
    out: dict[str, float] = {}
    for role in ROLES:
        for key, value in agents[role].cost_eur(event.public, option).items():
            out[key] = round(out.get(key, 0.0) + float(value), 2)
    return out


def physical_metrics(event: DisruptionEvent, option: CandidateOption) -> dict[str, Any]:
    from triad.agents.scoring import _missed_connection_pax
    from triad.constraints import crew, fuel, turnaround

    co2 = float(load_yaml("costs")["co2_kg_per_kg_fuel"])
    extra = fuel.extra_burn_kg(event.public, event.pilot, option)
    return {
        "fuel_kg": round(extra, 1),
        "co2_kg": round(extra * co2, 1),
        "missed_connections": int(_missed_connection_pax(event.pilot, option)),
        "overtime_min": int(crew.overtime_min(event.ground, option.arrival_slot)),
        "next_leg_delay_min": int(turnaround.next_leg_delay_min(event.public, event.ground, option)),
    }


def run_metrics(
    resolution: Resolution,
    log: Any = None,
    *,
    event: DisruptionEvent | None = None,
    agents: Mapping[AgentRole, Any] | None = None,
    label: str = "",
    simulated: bool = False,
) -> RunMetrics:
    entries = _entries(log)
    tokens, ms = _usage_by_agent(entries)
    vetoes_total, yielded = veto_counts(entries)
    outcome = outcome_of(resolution)
    data: dict[str, Any] = {
        "run_id": resolution.run_id,
        "label": label,
        "simulated": simulated,
        "outcome": outcome,
        "status": resolution.status,
        "turn": resolution.turn,
        "reason": resolution.reason,
        "fallback_reason": resolution.reason if outcome in {"FALLBACK", "ESCALATED"} else None,
        "unsafe_commit": is_unsafe_commit(resolution),
        "n_feasible": feasible_count(entries),
        "vetoes_total": vetoes_total,
        "veto_yield": yielded,
        "tokens_by_agent": tokens,
        "ms_by_agent": ms,
    }
    option = resolution.option
    if option is not None:
        data["option_id"] = option.option_id
        data["holding_min"] = int(option.holding_min)
        scheduled = event.public.original_eta if event is not None else _setup_value(entries, "original_eta")
        if scheduled is not None:
            data["arrival_delay_min"] = int(option.arrival_slot) - int(scheduled)
        if event is not None:
            data.update(physical_metrics(event, option))
        if event is not None and agents is not None:
            components = cost_breakdown(event, option, agents)
            data["cost_components_eur"] = components
            data["total_cost_eur"] = round(sum(components.values()), 2)
        elif resolution.costs_eur:
            data["total_cost_eur"] = round(sum(resolution.costs_eur.values()), 2)
    return RunMetrics(**data)


def _setup_value(entries: list[LogEntry], key: str) -> Any:
    setup = next((e for e in entries if e.event == "SETUP"), None)
    return setup.payload.get(key) if setup is not None else None


# --------------------------------------------------------------------------- aggregation


def _mean(values: Iterable[float | int | None]) -> float | None:
    present = [float(v) for v in values if v is not None]
    return round(mean(present), 2) if present else None


def aggregate(runs: list[RunMetrics], label: str = "") -> BatchReport:
    outcomes = Counter({k: 0 for k in ("TURN1", "TURN2", "TURN3", "FALLBACK", "ESCALATED")})
    outcomes.update(r.outcome for r in runs)
    turns = Counter({str(t): 0 for t in (1, 2, 3)})
    turns.update(str(r.turn) for r in runs if 1 <= r.turn <= 3)
    feasible = [r.n_feasible for r in runs if r.n_feasible is not None]
    committed = [r for r in runs if r.option_id is not None]
    component_keys = sorted({k for r in committed for k in r.cost_components_eur})
    with_components = [r for r in committed if r.cost_components_eur]
    return BatchReport(
        label=label or (runs[0].label if runs else ""),
        n_runs=len(runs),
        outcomes=dict(outcomes),
        turns_histogram=dict(turns),
        unsafe_commits=sum(1 for r in runs if r.unsafe_commit),
        feasible_ge2_rate=(round(sum(1 for n in feasible if n >= 2) / len(feasible), 3) if feasible else None),
        veto_yield=sum(r.veto_yield for r in runs),
        vetoes_total=sum(r.vetoes_total for r in runs),
        mean_cost_components_eur={
            k: _mean(r.cost_components_eur.get(k, 0.0) for r in with_components) or 0.0
            for k in component_keys
        },
        mean_total_cost_eur=_mean(r.total_cost_eur for r in committed),
        mean_holding_min=_mean(r.holding_min for r in committed),
        mean_fuel_kg=_mean(r.fuel_kg for r in committed),
        mean_co2_kg=_mean(r.co2_kg for r in committed),
        mean_arrival_delay_min=_mean(r.arrival_delay_min for r in committed),
        mean_missed_connections=_mean(r.missed_connections for r in committed),
        mean_overtime_min=_mean(r.overtime_min for r in committed),
        mean_next_leg_delay_min=_mean(r.next_leg_delay_min for r in committed),
        total_tokens=sum(sum(r.tokens_by_agent.values()) for r in runs),
    )


def negotiation_delta(a: list[RunMetrics], b: list[RunMetrics]) -> NegotiationDelta:
    """Compare two modes on the same rows (matched by ``run_id``).

    ``changed_rate``: share of matched rows whose committed option id differs
    (an escalation counts as option ``None``). ``mean_cost_diff_eur``: mean of
    ``b.total_cost_eur - a.total_cost_eur`` over rows where both have a cost.
    """
    b_by_id = {r.run_id: r for r in b}
    pairs = [(x, b_by_id[x.run_id]) for x in a if x.run_id in b_by_id]
    if not pairs:
        return NegotiationDelta(n_rows=0, changed_rate=None, mean_cost_diff_eur=None)
    changed = sum(1 for x, y in pairs if x.option_id != y.option_id)
    diffs = [
        y.total_cost_eur - x.total_cost_eur
        for x, y in pairs
        if x.total_cost_eur is not None and y.total_cost_eur is not None
    ]
    return NegotiationDelta(
        n_rows=len(pairs),
        changed_rate=round(changed / len(pairs), 3),
        mean_cost_diff_eur=round(mean(diffs), 2) if diffs else None,
    )


__all__ = [
    "BatchReport",
    "NegotiationDelta",
    "RunMetrics",
    "aggregate",
    "cost_breakdown",
    "feasible_count",
    "is_unsafe_commit",
    "negotiation_delta",
    "outcome_of",
    "physical_metrics",
    "run_metrics",
    "veto_counts",
]
