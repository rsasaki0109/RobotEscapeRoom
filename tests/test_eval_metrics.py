"""Tests for eval/metrics.py."""

from __future__ import annotations

from datetime import time

from semantic_toponav.coordination.fleet import FleetPlanResult, plan_fleet
from semantic_toponav.coordination.scheduler import SharedScheduler
from semantic_toponav.eval.generators import chain_graph, generate_fleet_requests
from semantic_toponav.eval.metrics import (
    LatencyStats,
    TrialMetrics,
    compute_metrics,
    jain_fairness,
)


def test_jain_fairness_perfect_equality() -> None:
    assert jain_fairness([5.0, 5.0, 5.0]) == 1.0


def test_jain_fairness_single_value_carries_all() -> None:
    # 1 of 3 carrying all mass -> 1/3.
    assert abs(jain_fairness([0.0, 0.0, 9.0]) - (9.0 ** 2) / (3 * 81.0)) < 1e-9


def test_jain_fairness_empty_list_is_one() -> None:
    assert jain_fairness([]) == 1.0


def test_jain_fairness_all_zero_is_one() -> None:
    # No mass to be unfair about.
    assert jain_fairness([0.0, 0.0, 0.0]) == 1.0


def test_latency_stats_empty() -> None:
    s = LatencyStats(samples_ms=[])
    assert s.p50 == 0.0
    assert s.p95 == 0.0
    assert s.mean == 0.0


def test_latency_stats_single_sample() -> None:
    s = LatencyStats(samples_ms=[12.5])
    assert s.p50 == 12.5
    assert s.p95 == 12.5
    assert s.mean == 12.5


def test_latency_stats_multi_sample_quantiles_sensible() -> None:
    s = LatencyStats(samples_ms=list(range(1, 21)))  # 1..20
    assert s.p50 == 10.5
    # 95th of 1..20 is somewhere in the high teens.
    assert 16.0 <= s.p95 <= 20.0


def test_trial_metrics_roundtrip() -> None:
    m = TrialMetrics(
        granted_count=3,
        grant_rate=0.75,
        total_path_cost=12.5,
        coord_makespan_minutes=4.0,
        mean_wait_minutes=0.5,
        max_wait_minutes=2.0,
        jain_fairness=0.9,
        conflict_count=1,
        latency_ms=42.0,
    )
    d = m.to_dict()
    m2 = TrialMetrics.from_dict(d)
    assert m == m2


def test_compute_metrics_on_real_fleet_result() -> None:
    g = chain_graph(6)
    s = SharedScheduler()
    reqs = generate_fleet_requests(g, 2, seed=0)
    fleet_result = plan_fleet(
        g, reqs, s,
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    metrics = compute_metrics(g, fleet_result, latency_ms=5.0)
    assert metrics.granted_count >= 0
    assert 0.0 <= metrics.grant_rate <= 1.0
    assert metrics.total_path_cost >= 0.0
    assert metrics.latency_ms == 5.0


def test_compute_metrics_empty_fleet_result() -> None:
    g = chain_graph(4)
    metrics = compute_metrics(
        g, FleetPlanResult(results=[]), latency_ms=0.0
    )
    assert metrics.granted_count == 0
    assert metrics.grant_rate == 0.0
    assert metrics.jain_fairness == 1.0  # nothing to be unfair about
