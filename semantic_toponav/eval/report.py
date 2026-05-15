"""JSONL persistence + markdown table formatting for eval trials.

Two flows:

* **Run-then-report** — the same process produces :class:`TrialResult`
  objects and pipes them through :func:`trials_to_markdown_table`.
  No disk round-trip needed.
* **Run-now-report-later** — :func:`trials_to_jsonl` writes one
  record per ``(scenario, strategy)`` trial to a JSONL file. A later
  invocation reloads it with :func:`jsonl_to_trials` and feeds the
  same table formatter. This is how the CLI lets users persist sweep
  results to disk and then re-render the summary without re-running
  the planner.

The JSONL row is intentionally lean: only the scenario name,
strategy, metrics dict, and the agent-level outcome list. The full
:class:`FleetPlanResult` (paths and reservation objects) is not
serialized — if you need that, run the sweep in-process.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Iterable
from pathlib import Path

from semantic_toponav.coordination.fleet import (
    FleetPlanResult,
    PlanWithSchedulerResult,
)
from semantic_toponav.eval.metrics import TrialMetrics
from semantic_toponav.eval.runner import TrialResult

# Strategy order used by both the JSONL writer and the markdown
# pivot so the table columns are stable across runs.
_COLUMN_ORDER: tuple[str, ...] = ("greedy", "priority", "deadline", "joint")

# Metrics that show up in the pivoted markdown table. Listed in
# display order; (key, label, format-spec) tuples.
_REPORT_COLUMNS = (
    ("granted_count", "grants", "d"),
    ("grant_rate", "rate", ".2f"),
    ("total_path_cost", "cost", ".1f"),
    ("coord_makespan_minutes", "makespan", ".1f"),
    ("max_wait_minutes", "max_wait", ".1f"),
    ("jain_fairness", "fairness", ".2f"),
    ("conflict_count", "conflicts", "d"),
    ("latency_ms", "latency_ms", ".1f"),
)


def _trial_to_row(trial: TrialResult) -> dict:
    """Flatten a :class:`TrialResult` into a JSON-friendly dict."""
    return {
        "scenario": trial.scenario_name,
        "strategy": trial.strategy,
        "metrics": trial.metrics.to_dict(),
        "metadata": dict(trial.metadata),
        "agents": [
            {
                "agent_id": r.agent_id,
                "granted": r.granted,
                "path_len": len(r.path),
                "failure_reason": r.failure_reason,
            }
            for r in trial.fleet_result.results
        ],
    }


def _row_to_trial(row: dict) -> TrialResult:
    """Rebuild a :class:`TrialResult` from a JSONL row.

    The :class:`FleetPlanResult` is reconstructed in a degraded form
    (claims and conflicts are dropped) because the round-trip only
    has to preserve what the markdown table consumes.
    """
    metrics = TrialMetrics.from_dict(row["metrics"])
    agents = row.get("agents", [])
    fleet_result = FleetPlanResult(
        results=[
            PlanWithSchedulerResult(
                agent_id=a["agent_id"],
                granted=bool(a["granted"]),
                # Path is reconstructed with placeholder ids only — the
                # table doesn't need the actual node sequence.
                path=["?"] * int(a.get("path_len", 0)),
                failure_reason=a.get("failure_reason"),
            )
            for a in agents
        ]
    )
    return TrialResult(
        scenario_name=row["scenario"],
        strategy=row["strategy"],
        metrics=metrics,
        fleet_result=fleet_result,
        metadata=row.get("metadata", {}),
    )


def trials_to_jsonl(trials: Iterable[TrialResult], path: str | Path) -> int:
    """Write one row per trial. Returns the number of rows written."""
    p = Path(path)
    count = 0
    with p.open("w", encoding="utf-8") as fh:
        for trial in trials:
            fh.write(json.dumps(_trial_to_row(trial), ensure_ascii=False))
            fh.write("\n")
            count += 1
    return count


def jsonl_to_trials(path: str | Path) -> list[TrialResult]:
    """Reverse of :func:`trials_to_jsonl`. Empty lines are skipped."""
    p = Path(path)
    out: list[TrialResult] = []
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            out.append(_row_to_trial(json.loads(line)))
    return out


def _format_cell(value: float | int, fmt: str) -> str:
    if isinstance(value, float):
        return f"{value:{fmt}}"
    return f"{value:{fmt}}" if fmt else str(value)


def trials_to_markdown_table(trials: list[TrialResult]) -> str:
    """Pivoted ``scenario × strategy`` markdown table.

    For each metric in :data:`_REPORT_COLUMNS` one block is emitted —
    rows are scenarios, columns are strategies (in the canonical
    ``greedy / priority / deadline / joint`` order, but only the
    strategies actually present in ``trials`` appear). Empty cells
    show ``—``.
    """
    if not trials:
        return "_(no trials)_\n"
    # Preserve scenario submission order while deduping.
    scenarios: list[str] = []
    seen_scenarios: set[str] = set()
    seen_strategies: set[str] = set()
    by_key: dict[tuple[str, str], TrialResult] = {}
    for t in trials:
        if t.scenario_name not in seen_scenarios:
            seen_scenarios.add(t.scenario_name)
            scenarios.append(t.scenario_name)
        seen_strategies.add(t.strategy)
        by_key[(t.scenario_name, t.strategy)] = t
    strategies = [s for s in _COLUMN_ORDER if s in seen_strategies]
    # Any custom strategies the user passed in get appended on the end.
    for s in seen_strategies:
        if s not in strategies:
            strategies.append(s)

    parts: list[str] = []
    for metric_key, label, fmt in _REPORT_COLUMNS:
        parts.append(f"### {label}\n")
        parts.append("| scenario | " + " | ".join(strategies) + " |")
        parts.append("|---" + "|---" * len(strategies) + "|")
        for scen in scenarios:
            cells: list[str] = []
            for s in strategies:
                trial = by_key.get((scen, s))
                if trial is None:
                    cells.append("—")
                    continue
                value = getattr(trial.metrics, metric_key)
                cells.append(_format_cell(value, fmt))
            parts.append(f"| {scen} | " + " | ".join(cells) + " |")
        parts.append("")  # blank line between metric blocks
    return "\n".join(parts).rstrip() + "\n"


def summarize_sweep(trials: list[TrialResult]) -> dict[str, dict[str, float]]:
    """Aggregate stats per strategy across all scenarios.

    Useful for one-line "joint averaged X% more grants than greedy"
    style claims. Per-strategy stats: mean grant rate, mean total
    path cost, mean latency_ms, max latency_ms.
    """
    by_strategy: dict[str, list[TrialResult]] = {}
    for t in trials:
        by_strategy.setdefault(t.strategy, []).append(t)
    summary: dict[str, dict[str, float]] = {}
    for s, ts in by_strategy.items():
        summary[s] = {
            "trials": float(len(ts)),
            "mean_grant_rate": statistics.fmean(
                [t.metrics.grant_rate for t in ts]
            ),
            "mean_total_cost": statistics.fmean(
                [t.metrics.total_path_cost for t in ts]
            ),
            "mean_latency_ms": statistics.fmean(
                [t.metrics.latency_ms for t in ts]
            ),
            "max_latency_ms": max(t.metrics.latency_ms for t in ts),
        }
    return summary
