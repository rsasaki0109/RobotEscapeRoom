"""Synthetic evaluation suite for ``semantic-toponav``.

The rest of the package is functional-tested but not measured —
``coordination`` strategies are picked one at a time, ``reservation_aware``
and ``time_aware`` are exercised in isolation, and the LLM / VLM layers
have parsing tests but no end-to-end quality numbers. This subpackage
adds the measurement substrate that lets later PRs answer "did this
change actually help, and on which scenarios?".

The public surface is intentionally small:

* :mod:`semantic_toponav.eval.generators` — deterministic, seed-driven
  graph and request generators (chain, star, doorway, multi-floor).
  Every input is reproducible from ``(scenario_name, seed)``.
* :mod:`semantic_toponav.eval.metrics` — quality and runtime numbers
  computed from a :class:`~semantic_toponav.coordination.FleetPlanResult`
  plus the timing the runner captured: grant rate, total path cost,
  approximate makespan, mean / max wait, Jain's fairness index,
  planning-latency p50 / p95, conflict count.
* :mod:`semantic_toponav.eval.runner` — :class:`Scenario` /
  :class:`TrialResult` containers plus :func:`run_scenario` /
  :func:`run_sweep`, which materialize a fresh
  :class:`~semantic_toponav.coordination.SharedScheduler` per
  ``(scenario, strategy)`` pair so trials never share state.
* :mod:`semantic_toponav.eval.report` — JSONL round-trip and a
  ``rows = scenario × cols = strategy`` markdown table.

The CLI side (`semantic-toponav eval-synthetic` / `eval-report`) is
wired in :mod:`semantic_toponav.cli.eval_cli`.
"""

from semantic_toponav.eval.generators import (
    chain_graph,
    doorway_graph,
    generate_fleet_requests,
    generate_static_reservations,
    multi_floor_office,
    star_graph,
)
from semantic_toponav.eval.metrics import (
    LatencyStats,
    TrialMetrics,
    compute_metrics,
    jain_fairness,
)
from semantic_toponav.eval.report import (
    jsonl_to_trials,
    summarize_sweep,
    trials_to_jsonl,
    trials_to_markdown_table,
)
from semantic_toponav.eval.runner import (
    Scenario,
    TrialResult,
    run_scenario,
    run_sweep,
)

__all__ = [
    "LatencyStats",
    "Scenario",
    "TrialMetrics",
    "TrialResult",
    "chain_graph",
    "compute_metrics",
    "doorway_graph",
    "generate_fleet_requests",
    "generate_static_reservations",
    "jain_fairness",
    "jsonl_to_trials",
    "multi_floor_office",
    "run_scenario",
    "run_sweep",
    "star_graph",
    "summarize_sweep",
    "trials_to_jsonl",
    "trials_to_markdown_table",
]
