"""Tests for eval/runner.py — Scenario / TrialResult / run_scenario / run_sweep."""

from __future__ import annotations

from datetime import time

from semantic_toponav.eval.generators import (
    chain_graph,
    doorway_graph,
    generate_fleet_requests,
)
from semantic_toponav.eval.runner import (
    DEFAULT_STRATEGIES,
    Scenario,
    run_scenario,
    run_sweep,
)


def _make_scenario(name: str, n_nodes: int = 6, n_agents: int = 3, seed: int = 0) -> Scenario:
    g = chain_graph(n_nodes, seed=seed)
    reqs = generate_fleet_requests(g, n_agents, seed=seed)
    return Scenario(
        name=name,
        graph=g,
        requests=reqs,
        hold_start=time(10, 0),
        hold_end=time(11, 0),
    )


def test_run_scenario_produces_one_trial_per_strategy() -> None:
    scenario = _make_scenario("chain_test")
    trials = run_scenario(scenario)
    assert [t.strategy for t in trials] == list(DEFAULT_STRATEGIES)
    assert all(t.scenario_name == "chain_test" for t in trials)


def test_run_scenario_with_explicit_strategy_subset() -> None:
    scenario = _make_scenario("chain_subset")
    trials = run_scenario(scenario, strategies=("greedy", "joint"))
    assert [t.strategy for t in trials] == ["greedy", "joint"]


def test_run_scenario_each_trial_carries_metrics() -> None:
    scenario = _make_scenario("chain_metrics")
    trials = run_scenario(scenario, strategies=("greedy",))
    assert trials[0].metrics.latency_ms >= 0.0
    assert 0.0 <= trials[0].metrics.grant_rate <= 1.0


def test_run_scenario_metadata_propagates() -> None:
    g = chain_graph(5)
    reqs = generate_fleet_requests(g, 2, seed=0)
    scenario = Scenario(
        name="metaprop",
        graph=g,
        requests=reqs,
        hold_start=time(10, 0),
        hold_end=time(11, 0),
        metadata={"seed": "42", "tag": "smoke"},
    )
    trials = run_scenario(scenario, strategies=("greedy",))
    assert trials[0].metadata == {"seed": "42", "tag": "smoke"}


def test_run_scenario_trials_are_independent() -> None:
    """Each strategy must see a fresh scheduler. If the runner reused
    the same scheduler across strategies, the second strategy would
    inherit the first one's holds and look artificially conflicted."""
    scenario = _make_scenario("chain_indep", n_agents=2)
    trials = run_scenario(scenario, strategies=("greedy", "greedy"))
    # Two back-to-back greedy runs on the same input should produce
    # identical metrics — they don't share scheduler state.
    a, b = trials
    assert a.metrics.granted_count == b.metrics.granted_count
    assert a.metrics.total_path_cost == b.metrics.total_path_cost


def test_run_sweep_flattens_scenarios_and_strategies() -> None:
    s1 = _make_scenario("a")
    s2 = _make_scenario("b")
    trials = run_sweep([s1, s2], strategies=("greedy", "joint"))
    assert len(trials) == 4
    names = {t.scenario_name for t in trials}
    assert names == {"a", "b"}


def test_run_sweep_on_doorway_scenario() -> None:
    g = doorway_graph(n_rooms=2)
    reqs = generate_fleet_requests(g, 3, seed=1)
    scenario = Scenario(
        name="doorway",
        graph=g,
        requests=reqs,
        hold_start=time(10, 0),
        hold_end=time(11, 0),
    )
    trials = run_sweep([scenario], strategies=("greedy", "joint"))
    # Both strategies produced a result; numbers don't have to match
    # but both must be non-negative.
    for t in trials:
        assert t.metrics.granted_count >= 0
        assert t.metrics.total_path_cost >= 0.0
