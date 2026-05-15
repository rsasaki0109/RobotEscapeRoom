"""Tests for the BnB ``objective`` knob — minimax_cost / max_fairness."""

from __future__ import annotations

from datetime import time

import pytest

from semantic_toponav.coordination.branch_and_bound import (
    _jain_index,
    plan_fleet_bnb,
)
from semantic_toponav.coordination.fleet import (
    FleetRequest,
    _path_cost_total,
)
from semantic_toponav.coordination.joint import plan_fleet_with_strategy
from semantic_toponav.coordination.scheduler import SharedScheduler
from semantic_toponav.eval.generators import chain_graph, star_graph


def _granted_costs(graph, fleet_result) -> list[float]:
    return [
        _path_cost_total(graph, r.path)
        for r in fleet_result.results
        if r.granted
    ]


# ----- jain index helper -----------------------------------------------------


def test_jain_empty_is_one() -> None:
    assert _jain_index([]) == 1.0


def test_jain_all_zero_is_one() -> None:
    assert _jain_index([0.0, 0.0, 0.0]) == 1.0


def test_jain_equal_values_is_one() -> None:
    assert _jain_index([2.5, 2.5, 2.5]) == pytest.approx(1.0)


def test_jain_single_dominant_value_drops_to_one_over_n() -> None:
    # One agent carries everything: Jain = 1/n.
    assert _jain_index([0.0, 0.0, 6.0]) == pytest.approx(1.0 / 3.0)


# ----- BnB plumbing ----------------------------------------------------------


def test_bnb_default_objective_is_min_cost() -> None:
    g = chain_graph(5)
    out = plan_fleet_bnb(
        g, [FleetRequest("a", "n0", "n4")], SharedScheduler(),
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    assert out.stats.objective == "min_cost"


def test_bnb_records_per_agent_costs_on_grant() -> None:
    g = chain_graph(5)
    out = plan_fleet_bnb(
        g, [FleetRequest("a", "n0", "n4")], SharedScheduler(),
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    # Single granted agent — per_agent_costs has exactly that agent.
    assert set(out.per_agent_costs) == {"a"}
    assert out.per_agent_costs["a"] >= 0.0


def test_bnb_per_agent_costs_omits_denied_agents() -> None:
    """An agent that fails admission contributes no entry to per_agent_costs."""
    g = chain_graph(3)
    s = SharedScheduler()
    # First a long hold blocking the chain, then a tight-deadline agent
    # that cannot meet its arrival window — pure denial setup.
    requests = [
        FleetRequest("ok", "n0", "n2"),
        FleetRequest("slow", "n0", "n2", deadline=time(10, 1)),
    ]
    out = plan_fleet_bnb(
        g, requests, s,
        hold_start=time(10, 0), hold_end=time(11, 0),
        admission="hard",
        minutes_per_cost_unit=60.0,  # 1 cost = 1 hour, easy to miss deadline
    )
    granted_agents = {r.agent_id for r in out.fleet_result.results if r.granted}
    # slow should be denied; per_agent_costs must not contain it.
    assert "slow" not in out.per_agent_costs
    assert set(out.per_agent_costs).issubset(granted_agents)


# ----- objective: minimax_cost -----------------------------------------------


def test_bnb_minimax_objective_runs_and_records_objective() -> None:
    g = star_graph(4)
    requests = [
        FleetRequest("a", "leaf0", "leaf1"),
        FleetRequest("b", "leaf1", "leaf2"),
        FleetRequest("c", "leaf2", "leaf3"),
    ]
    out = plan_fleet_bnb(
        g, requests, SharedScheduler(),
        hold_start=time(10, 0), hold_end=time(11, 0),
        objective="minimax_cost",
    )
    assert out.stats.objective == "minimax_cost"
    assert set(out.chosen_order) == {"a", "b", "c"}


def test_bnb_minimax_does_not_drop_grants_vs_min_cost() -> None:
    """Whatever objective is picked, the optimum grants count must be the
    same — both objectives respect the primary key (granted DESC). Only
    the tie-break changes."""
    g = chain_graph(5)
    requests = [
        FleetRequest("a", "n0", "n4"),
        FleetRequest("b", "n1", "n3"),
        FleetRequest("c", "n2", "n4"),
    ]
    base = plan_fleet_bnb(
        g, requests, SharedScheduler(),
        hold_start=time(10, 0), hold_end=time(11, 0),
        objective="min_cost",
    )
    mm = plan_fleet_bnb(
        g, requests, SharedScheduler(),
        hold_start=time(10, 0), hold_end=time(11, 0),
        objective="minimax_cost",
    )
    base_granted = sum(1 for r in base.fleet_result.results if r.granted)
    mm_granted = sum(1 for r in mm.fleet_result.results if r.granted)
    assert mm_granted == base_granted


# ----- objective: max_fairness -----------------------------------------------


def test_bnb_fairness_objective_runs_and_records_objective() -> None:
    g = star_graph(4)
    requests = [
        FleetRequest("a", "leaf0", "leaf1"),
        FleetRequest("b", "leaf2", "leaf3"),
    ]
    out = plan_fleet_bnb(
        g, requests, SharedScheduler(),
        hold_start=time(10, 0), hold_end=time(11, 0),
        objective="max_fairness",
    )
    assert out.stats.objective == "max_fairness"


def test_bnb_fairness_does_not_drop_grants_vs_min_cost() -> None:
    g = chain_graph(5)
    requests = [
        FleetRequest("a", "n0", "n2"),
        FleetRequest("b", "n2", "n4"),
    ]
    base = plan_fleet_bnb(
        g, requests, SharedScheduler(),
        hold_start=time(10, 0), hold_end=time(11, 0),
        objective="min_cost",
    )
    fair = plan_fleet_bnb(
        g, requests, SharedScheduler(),
        hold_start=time(10, 0), hold_end=time(11, 0),
        objective="max_fairness",
    )
    base_granted = sum(1 for r in base.fleet_result.results if r.granted)
    fair_granted = sum(1 for r in fair.fleet_result.results if r.granted)
    assert fair_granted == base_granted


def test_bnb_fairness_disables_cost_prune() -> None:
    """With max_fairness, the cost-prune branch must never fire (the
    bound is unsound for non-monotone fairness). Grants prune may
    still fire."""
    g = chain_graph(5)
    requests = [
        FleetRequest("a", "n0", "n4"),
        FleetRequest("b", "n1", "n3"),
        FleetRequest("c", "n2", "n4"),
    ]
    out = plan_fleet_bnb(
        g, requests, SharedScheduler(),
        hold_start=time(10, 0), hold_end=time(11, 0),
        objective="max_fairness",
    )
    assert out.stats.nodes_pruned_by_cost == 0


# ----- joint dispatcher integration ------------------------------------------


def test_plan_fleet_with_strategy_threads_bnb_objective() -> None:
    g = star_graph(4)
    requests = [
        FleetRequest("a", "leaf0", "leaf1"),
        FleetRequest("b", "leaf1", "leaf2"),
    ]
    out = plan_fleet_with_strategy(
        g, requests, SharedScheduler(),
        strategy="bnb",
        hold_start=time(10, 0), hold_end=time(11, 0),
        bnb_objective="minimax_cost",
    )
    assert {r.agent_id for r in out.results} == {"a", "b"}


def test_plan_fleet_with_strategy_bnb_default_unchanged() -> None:
    """If bnb_objective is not provided, behavior must match the prior
    PR #38 default — min_cost — so existing callers are unaffected."""
    g = chain_graph(5)
    requests = [
        FleetRequest("a", "n0", "n4"),
        FleetRequest("b", "n2", "n3"),
    ]
    out = plan_fleet_with_strategy(
        g, requests, SharedScheduler(),
        strategy="bnb",
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    assert sum(1 for r in out.results if r.granted) >= 1


# ----- unknown objective rejected on the boundary ----------------------------


def test_bnb_unknown_objective_rejected() -> None:
    g = chain_graph(3)
    with pytest.raises(ValueError, match="unknown objective"):
        plan_fleet_bnb(
            g, [FleetRequest("a", "n0", "n2")], SharedScheduler(),
            hold_start=time(10, 0), hold_end=time(11, 0),
            objective="weird",  # type: ignore[arg-type]
        )
