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

from semantic_toponav.eval.abstention import (
    AbstentionCase,
    AbstentionOutcome,
    AbstentionReport,
    CategoryMetrics,
    TranscriptBackend,
    abstention_comparison_markdown,
    abstention_report_markdown,
    load_abstention_corpus,
    load_abstention_transcript,
    run_abstention_benchmark,
)
from semantic_toponav.eval.generators import (
    chain_graph,
    doorway_graph,
    generate_fleet_requests,
    generate_static_reservations,
    multi_floor_office,
    star_graph,
)
from semantic_toponav.eval.grounding import (
    DescriberSafetyCase,
    DescriberSafetyEvaluation,
    DescriberSafetyMetrics,
    GroundingCase,
    GroundingCorpus,
    GroundingMetrics,
    ResolverEvaluation,
    VisualGroundingCase,
    VisualGroundingCorpus,
    VisualGroundingMetrics,
    VisualLocalizerEvaluation,
    evaluate_describer_safety,
    evaluate_resolver,
    evaluate_visual_localizer,
    grounding_report_markdown,
    load_grounding_corpus,
    load_visual_grounding_corpus,
    visual_grounding_report_markdown,
)
from semantic_toponav.eval.metrics import (
    LatencyStats,
    TrialMetrics,
    compute_metrics,
    jain_fairness,
)
from semantic_toponav.eval.no_invent import (
    NoInventReport,
    NoInventVerdict,
    no_invent_audit_markdown,
    run_no_invent_audit,
    run_no_invent_conformance,
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
from semantic_toponav.eval.visual_benchmark import (
    NeighborRerankAblation,
    VectorTableBackend,
    aliasing_visual_corpus,
    neighbor_rerank_ablation,
    neighbor_rerank_ablation_markdown,
)

__all__ = [
    "AbstentionCase",
    "AbstentionOutcome",
    "AbstentionReport",
    "CategoryMetrics",
    "DescriberSafetyCase",
    "DescriberSafetyEvaluation",
    "DescriberSafetyMetrics",
    "GroundingCase",
    "GroundingCorpus",
    "GroundingMetrics",
    "LatencyStats",
    "NeighborRerankAblation",
    "NoInventReport",
    "NoInventVerdict",
    "ResolverEvaluation",
    "Scenario",
    "TranscriptBackend",
    "TrialMetrics",
    "TrialResult",
    "VectorTableBackend",
    "VisualGroundingCase",
    "VisualGroundingCorpus",
    "VisualGroundingMetrics",
    "VisualLocalizerEvaluation",
    "abstention_comparison_markdown",
    "abstention_report_markdown",
    "aliasing_visual_corpus",
    "chain_graph",
    "compute_metrics",
    "doorway_graph",
    "evaluate_describer_safety",
    "evaluate_resolver",
    "evaluate_visual_localizer",
    "generate_fleet_requests",
    "generate_static_reservations",
    "grounding_report_markdown",
    "jain_fairness",
    "jsonl_to_trials",
    "load_abstention_corpus",
    "load_abstention_transcript",
    "load_grounding_corpus",
    "load_visual_grounding_corpus",
    "multi_floor_office",
    "neighbor_rerank_ablation",
    "neighbor_rerank_ablation_markdown",
    "no_invent_audit_markdown",
    "run_abstention_benchmark",
    "run_no_invent_audit",
    "run_no_invent_conformance",
    "run_scenario",
    "run_sweep",
    "star_graph",
    "summarize_sweep",
    "trials_to_jsonl",
    "trials_to_markdown_table",
    "visual_grounding_report_markdown",
]
