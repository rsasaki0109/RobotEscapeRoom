"""Trial-driver for the synthetic evaluation suite.

A :class:`Scenario` bundles a graph, a fleet of requests, a hold
window, and the optional pre-existing reservations the scheduler
starts with. :func:`run_scenario` runs each requested strategy against
a *fresh* :class:`~semantic_toponav.coordination.SharedScheduler`
(so trials never share state), times the call, and records a
:class:`TrialResult` per strategy. :func:`run_sweep` is the obvious
generalization across many scenarios.

The runner deliberately does not own a parameter sweep — the eval
suite is wired so that calling code (the CLI, tests, notebooks)
constructs whatever scenario list it wants and hands it in. Keeping
the parameter-sweep policy outside the runner means the runner stays
trivially testable without mocking.
"""

from __future__ import annotations

import time as _time_mod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import time
from typing import Literal

from semantic_toponav.coordination.fleet import (
    FleetPlanResult,
    FleetRequest,
)
from semantic_toponav.coordination.joint import (
    Strategy,
    plan_fleet_with_strategy,
)
from semantic_toponav.coordination.scheduler import (
    ClaimRequest,
    SharedScheduler,
)
from semantic_toponav.eval.generators import apply_reservations
from semantic_toponav.eval.metrics import TrialMetrics, compute_metrics
from semantic_toponav.graph.topology_graph import TopologyGraph

DEFAULT_STRATEGIES: tuple[Strategy, ...] = ("greedy", "priority", "deadline", "joint")


@dataclass
class Scenario:
    """One reproducible eval setup.

    Attributes
    ----------
    name:
        Short identifier used as a row label in the report.
    graph:
        The :class:`TopologyGraph` the trial plans against.
    requests:
        Fleet request list (in their natural / submission order).
    hold_start, hold_end:
        Time-of-day window every strategy holds claims over.
    reservations:
        Optional pre-existing :class:`ClaimRequest` entries dropped on
        the scheduler before the strategy runs. Useful for the
        "rooms already booked" condition.
    metadata:
        Free-form annotation that propagates to every
        :class:`TrialResult` so reports can group by (e.g.) seed or
        contention density without re-deriving it.
    """

    name: str
    graph: TopologyGraph
    requests: list[FleetRequest]
    hold_start: time = time(10, 0)
    hold_end: time = time(11, 0)
    reservations: list[ClaimRequest] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class TrialResult:
    """Outcome of one ``(scenario, strategy)`` run.

    Carries the raw :class:`FleetPlanResult` (so tests can introspect
    paths and claims) plus the :class:`TrialMetrics` numbers used by
    the report.
    """

    scenario_name: str
    strategy: Strategy
    metrics: TrialMetrics
    fleet_result: FleetPlanResult
    metadata: dict[str, str] = field(default_factory=dict)


def _build_scheduler(scenario: Scenario) -> SharedScheduler:
    """Construct a fresh scheduler and preload the scenario reservations."""
    s = SharedScheduler()
    if scenario.reservations:
        apply_reservations(s, scenario.reservations)
    return s


def run_scenario(
    scenario: Scenario,
    strategies: Sequence[Strategy] = DEFAULT_STRATEGIES,
    *,
    algorithm: Literal["astar", "dijkstra"] = "astar",
    admission: Literal["soft", "hard"] = "soft",
    minutes_per_cost_unit: float = 1.0,
) -> list[TrialResult]:
    """Run each strategy once against ``scenario`` on a fresh scheduler.

    The scheduler is rebuilt per strategy so the trials are
    independent — strategy A's grants never leak into strategy B's
    starting state. ``algorithm``, ``admission``, and
    ``minutes_per_cost_unit`` are forwarded to
    :func:`plan_fleet_with_strategy`.
    """
    out: list[TrialResult] = []
    for strategy in strategies:
        scheduler = _build_scheduler(scenario)
        t0 = _time_mod.perf_counter()
        fleet_result = plan_fleet_with_strategy(
            scenario.graph,
            scenario.requests,
            scheduler,
            strategy=strategy,
            hold_start=scenario.hold_start,
            hold_end=scenario.hold_end,
            algorithm=algorithm,
            admission=admission,
            minutes_per_cost_unit=minutes_per_cost_unit,
        )
        latency_ms = (_time_mod.perf_counter() - t0) * 1000.0
        metrics = compute_metrics(scenario.graph, fleet_result, latency_ms=latency_ms)
        out.append(
            TrialResult(
                scenario_name=scenario.name,
                strategy=strategy,
                metrics=metrics,
                fleet_result=fleet_result,
                metadata=dict(scenario.metadata),
            )
        )
    return out


def run_sweep(
    scenarios: Sequence[Scenario],
    strategies: Sequence[Strategy] = DEFAULT_STRATEGIES,
    *,
    algorithm: Literal["astar", "dijkstra"] = "astar",
    admission: Literal["soft", "hard"] = "soft",
    minutes_per_cost_unit: float = 1.0,
) -> list[TrialResult]:
    """Run :func:`run_scenario` on every scenario in order.

    Returns a flat list of :class:`TrialResult` — one per
    ``(scenario, strategy)`` pair, in the order ``scenarios`` was
    given. Callers that want a pivoted view use
    :func:`semantic_toponav.eval.report.trials_to_markdown_table`.
    """
    results: list[TrialResult] = []
    for scenario in scenarios:
        results.extend(
            run_scenario(
                scenario,
                strategies,
                algorithm=algorithm,
                admission=admission,
                minutes_per_cost_unit=minutes_per_cost_unit,
            )
        )
    return results
