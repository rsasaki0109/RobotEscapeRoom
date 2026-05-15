"""Quality + runtime metrics over a :class:`FleetPlanResult`.

The runner captures three pieces per trial: the
:class:`~semantic_toponav.coordination.FleetPlanResult` from running
one strategy on one scenario, the per-strategy wall-clock latency, and
the scenario configuration (so the metrics can normalize per-agent
quantities). This module turns those into the dict that gets dumped to
JSONL and printed in the markdown report.

Some of the metrics here are *approximations* for the simple
in-memory scheduler:

* "makespan" treats the held window as the agent's time-of-occupation
  rather than simulating real motion — the scheduler only knows
  ``[hold_start, hold_end)``, not the actual second-by-second progress
  of the agent. The metric is therefore the *coordination makespan*,
  not the physical one.
* "wait time" is approximated as the difference (in minutes) between
  the agent's claim start and the earliest claim start across the
  granted fleet. With a flat hold window this is always zero, so the
  metric becomes informative once strategies that stagger ``hold_start``
  are introduced (a planned extension; today it stays as the agreed
  upper-bound placeholder).

For grant rate, total path cost, conflict count, and Jain's fairness,
the numbers are exact given the input.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from semantic_toponav.coordination.joint import _path_total_cost

if TYPE_CHECKING:
    from semantic_toponav.coordination.fleet import (
        FleetPlanResult,
        PlanWithSchedulerResult,
    )
    from semantic_toponav.graph.topology_graph import TopologyGraph


@dataclass
class LatencyStats:
    """Wall-clock latency aggregation across multiple trials.

    p50 and p95 are computed when there are at least two samples;
    single-sample runs use the sample as both quantiles to avoid
    raising on smoke tests.
    """

    samples_ms: list[float] = field(default_factory=list)

    @property
    def p50(self) -> float:
        if not self.samples_ms:
            return 0.0
        return statistics.median(self.samples_ms)

    @property
    def p95(self) -> float:
        if not self.samples_ms:
            return 0.0
        if len(self.samples_ms) < 2:
            return self.samples_ms[0]
        # statistics.quantiles needs n >= 2; ask for the 95th percentile.
        return statistics.quantiles(self.samples_ms, n=20)[18]

    @property
    def mean(self) -> float:
        if not self.samples_ms:
            return 0.0
        return statistics.fmean(self.samples_ms)


@dataclass
class TrialMetrics:
    """Numerical summary of one ``(scenario, strategy)`` trial.

    Fields are flat floats / ints so the JSONL row stays trivially
    serializable. The :meth:`to_dict` method emits the dict that gets
    written to disk; the corresponding :meth:`from_dict` reverses it.

    ``deadline_miss_count`` is the number of agents whose result
    carried ``reason_code == "deadline_miss"``. With ``admission="soft"``
    it stays zero (deadline is only a sort hint). With
    ``admission="hard"`` it counts the agents the planner refused to
    admit because their projected arrival would exceed their
    deadline.
    """

    granted_count: int
    grant_rate: float
    total_path_cost: float
    coord_makespan_minutes: float
    mean_wait_minutes: float
    max_wait_minutes: float
    jain_fairness: float
    conflict_count: int
    latency_ms: float
    deadline_miss_count: int = 0

    def to_dict(self) -> dict[str, float | int]:
        return {
            "granted_count": self.granted_count,
            "grant_rate": self.grant_rate,
            "total_path_cost": self.total_path_cost,
            "coord_makespan_minutes": self.coord_makespan_minutes,
            "mean_wait_minutes": self.mean_wait_minutes,
            "max_wait_minutes": self.max_wait_minutes,
            "jain_fairness": self.jain_fairness,
            "conflict_count": self.conflict_count,
            "latency_ms": self.latency_ms,
            "deadline_miss_count": self.deadline_miss_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TrialMetrics:
        return cls(
            granted_count=int(d["granted_count"]),
            grant_rate=float(d["grant_rate"]),
            total_path_cost=float(d["total_path_cost"]),
            coord_makespan_minutes=float(d["coord_makespan_minutes"]),
            mean_wait_minutes=float(d["mean_wait_minutes"]),
            max_wait_minutes=float(d["max_wait_minutes"]),
            jain_fairness=float(d["jain_fairness"]),
            conflict_count=int(d["conflict_count"]),
            latency_ms=float(d["latency_ms"]),
            # Default 0 for back-compat with JSONLs written pre-PR-37.
            deadline_miss_count=int(d.get("deadline_miss_count", 0)),
        )


def jain_fairness(values: list[float]) -> float:
    """Jain's fairness index over a list of non-negative values.

    Returns ``1.0`` when all values are equal (perfect fairness) and
    ``1/n`` when one value carries all the mass. Returns ``1.0`` for
    an empty or all-zero list — there's nothing to be unfair about.
    """
    if not values:
        return 1.0
    total = sum(values)
    if total == 0.0:
        return 1.0
    num = total * total
    denom = len(values) * sum(v * v for v in values)
    if denom == 0.0:
        return 1.0
    return num / denom


def _path_makespan_proxy(
    graph: TopologyGraph, results: list[PlanWithSchedulerResult]
) -> float:
    """Approximate makespan as the max single-agent path cost.

    The scheduler doesn't simulate continuous motion so we use each
    granted agent's path cost as a proxy for "time to finish". Taking
    the max over all granted agents gives a strategy-comparable
    upper bound.
    """
    granted_costs = [
        _path_total_cost(graph, r.path) for r in results if r.granted
    ]
    return max(granted_costs) if granted_costs else 0.0


def _wait_times_minutes(results: list[PlanWithSchedulerResult]) -> list[float]:
    """Per-granted-agent wait time, approximated as ``claim.start`` delta
    from the earliest claim start.

    With a single shared hold window this is zero across the board.
    The function still computes the delta so future strategies that
    stagger ``hold_start`` per agent get free fairness numbers.
    """
    starts: list[float] = []
    for r in results:
        if not r.granted or not r.claims:
            continue
        earliest = min(c.start for c in r.claims)
        starts.append(earliest.hour * 60.0 + earliest.minute)
    if not starts:
        return []
    base = min(starts)
    return [s - base for s in starts]


def compute_metrics(
    graph: TopologyGraph,
    fleet_result: FleetPlanResult,
    *,
    latency_ms: float,
) -> TrialMetrics:
    """Compute the full :class:`TrialMetrics` for one trial.

    Parameters
    ----------
    graph:
        The graph the trial ran on. Needed for path-cost computation.
    fleet_result:
        The runner's per-strategy
        :class:`~semantic_toponav.coordination.FleetPlanResult`.
    latency_ms:
        Wall-clock time the strategy took to produce ``fleet_result``,
        in milliseconds. The runner measures this with
        :func:`time.perf_counter`.
    """
    results = list(fleet_result.results)
    total = len(results)
    granted = [r for r in results if r.granted]
    grant_rate = (len(granted) / total) if total else 0.0
    total_cost = sum(_path_total_cost(graph, r.path) for r in granted)
    makespan = _path_makespan_proxy(graph, results)
    waits = _wait_times_minutes(results)
    mean_wait = statistics.fmean(waits) if waits else 0.0
    max_wait = max(waits) if waits else 0.0
    fairness = jain_fairness(waits) if waits else 1.0
    conflicts = sum(len(r.conflicts) for r in results)
    deadline_misses = sum(
        1 for r in results if getattr(r, "reason_code", "ok") == "deadline_miss"
    )
    return TrialMetrics(
        granted_count=len(granted),
        grant_rate=grant_rate,
        total_path_cost=total_cost,
        coord_makespan_minutes=makespan,
        mean_wait_minutes=mean_wait,
        max_wait_minutes=max_wait,
        jain_fairness=fairness,
        conflict_count=conflicts,
        latency_ms=latency_ms,
        deadline_miss_count=deadline_misses,
    )
