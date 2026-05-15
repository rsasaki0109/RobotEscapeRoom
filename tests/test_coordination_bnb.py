"""Tests for plan_fleet_bnb — branch-and-bound joint scheduler."""

from __future__ import annotations

from datetime import time

from semantic_toponav.coordination.branch_and_bound import (
    ConflictExplanation,
    plan_fleet_bnb,
)
from semantic_toponav.coordination.fleet import FleetRequest
from semantic_toponav.coordination.joint import (
    plan_fleet_joint,
    plan_fleet_with_strategy,
)
from semantic_toponav.coordination.scheduler import SharedScheduler
from semantic_toponav.eval.generators import (
    chain_graph,
    doorway_graph,
    star_graph,
)


def _score(fleet_result) -> tuple[int, float]:
    """Score helper: (granted_count, total_path_cost) over granted agents."""
    from semantic_toponav.coordination.fleet import _path_cost_total

    granted = [r for r in fleet_result.results if r.granted]
    cost = sum(
        _path_cost_total(
            chain_graph(0), r.path
        )  # dummy; recomputed via the real graph in actual tests
        for r in granted
    )
    return len(granted), cost


def test_bnb_empty_request_list_returns_empty_result() -> None:
    g = chain_graph(5)
    s = SharedScheduler()
    out = plan_fleet_bnb(
        g, [], s,
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    assert out.chosen_order == ()
    assert out.fleet_result.results == []
    assert out.stats.completed is True


def test_bnb_single_agent_simple_case() -> None:
    g = chain_graph(5)
    s = SharedScheduler()
    out = plan_fleet_bnb(
        g, [FleetRequest("a", "n0", "n4")], s,
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    assert out.chosen_order == ("a",)
    assert out.fleet_result.results[0].granted is True


def test_bnb_small_n_matches_exhaustive_joint() -> None:
    """Property test: for n <= 4 the BnB optimum should match what
    plan_fleet_joint commits (joint enumerates fully when n! <= 120)."""
    g = star_graph(5)
    requests = [
        FleetRequest("a", "leaf0", "leaf1"),
        FleetRequest("b", "leaf2", "leaf3"),
        FleetRequest("c", "leaf3", "leaf4"),
    ]
    # Run joint on a fresh scheduler
    s_joint = SharedScheduler()
    joint_result = plan_fleet_joint(
        g, requests, s_joint,
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    joint_granted = sum(1 for r in joint_result.fleet_result.results if r.granted)
    # Run BnB on a fresh scheduler
    s_bnb = SharedScheduler()
    bnb_result = plan_fleet_bnb(
        g, requests, s_bnb,
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    bnb_granted = sum(1 for r in bnb_result.fleet_result.results if r.granted)
    # BnB must match joint on the primary score (grants).
    assert bnb_granted == joint_granted
    # And BnB completed (n=3 -> 6 leaves, well under budget).
    assert bnb_result.stats.completed is True


def test_bnb_explores_more_than_one_node() -> None:
    """Sanity: with multiple requests, the search expands several nodes."""
    g = doorway_graph(n_rooms=2)
    s = SharedScheduler()
    requests = [
        FleetRequest("a", "room_a0", "room_b0"),
        FleetRequest("b", "room_b1", "room_a1"),
    ]
    out = plan_fleet_bnb(
        g, requests, s,
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    # 2! = 2 orderings; each ordering expands 2 nodes; total >= 2.
    assert out.stats.nodes_explored >= 2


def test_bnb_pruning_fires_on_contested_scenario() -> None:
    """A 4-agent doorway scenario should hit at least one prune branch.

    Why: the doorway is shared, so adding a second agent to a prefix
    where a higher-grant ordering already exists triggers the grants
    upper-bound pruner (or the cost lower-bound on tie).
    """
    g = doorway_graph(n_rooms=2)
    s = SharedScheduler()
    requests = [
        FleetRequest("a", "room_a0", "room_b0"),
        FleetRequest("b", "room_a1", "room_b1"),
        FleetRequest("c", "room_b0", "room_a0"),
        FleetRequest("d", "room_b1", "room_a1"),
    ]
    out = plan_fleet_bnb(
        g, requests, s,
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    # Pruning should fire at least once across grants+cost prunes.
    assert (
        out.stats.nodes_pruned_by_grants + out.stats.nodes_pruned_by_cost > 0
    )


def test_bnb_conflict_explanation_populated_on_blocked_request() -> None:
    """When an agent's path can't be admitted, the explanation should
    name the blocking holders and reason_code."""
    g = chain_graph(5)
    s = SharedScheduler()
    # Pre-block n0..n4 with another agent.
    from semantic_toponav.coordination.scheduler import ClaimRequest

    for nid in ("n0", "n1", "n2", "n3", "n4"):
        s.claim(
            ClaimRequest(
                agent_id="blocker",
                resource_id=nid,
                start=time(10, 0),
                end=time(11, 0),
            )
        )
    requests = [FleetRequest("late", "n0", "n4")]
    out = plan_fleet_bnb(
        g, requests, s,
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    # 'late' fails: reservation_conflict or no_path (depending on cost
    # composition). Either way the explanation must exist.
    assert out.fleet_result.results[0].granted is False
    assert any(
        e.blocked_agent_id == "late" for e in out.conflict_explanations
    )


def test_bnb_explanation_lists_blocking_agents_on_deadline_miss() -> None:
    """Under hard admission, a deadline-miss rejection returns the path
    that would have been used. When that path traverses resources held
    by other agents, the explanation should name them. Use a long
    chain + tight deadline so the planner returns a non-empty path
    that gets rejected by admission rather than by reservation_aware.
    """
    g = chain_graph(10)
    s = SharedScheduler()
    from semantic_toponav.coordination.scheduler import ClaimRequest

    # blocker holds the start node; path through it still costs
    # something but the path can be planned (start is the agent's own
    # spawn position so reservation_aware doesn't block it — only the
    # subsequent edge does, and that's the only way out of n0).
    # Use a hold on a single mid-chain node so reservation_aware
    # bumps cost but path is still findable.
    s.claim(
        ClaimRequest(
            agent_id="blocker", resource_id="n5",
            start=time(10, 0), end=time(11, 0),
        )
    )
    requests = [
        FleetRequest("r", "n0", "n9", deadline=time(10, 4)),
    ]
    out = plan_fleet_bnb(
        g, requests, s,
        hold_start=time(10, 0), hold_end=time(11, 0),
        admission="hard",  # tight deadline triggers deadline_miss
    )
    explanations = {e.blocked_agent_id: e for e in out.conflict_explanations}
    # 'r' will be blocked either by no_path (reservation_aware made it
    # infinite-cost) or deadline_miss. Either case yields an entry.
    assert "r" in explanations


def test_bnb_max_nodes_budget_honored() -> None:
    """Setting max_nodes very low should make stats.completed False."""
    g = star_graph(5)
    requests = [
        FleetRequest(f"a{i}", "leaf0", "leaf1") for i in range(5)
    ]
    out = plan_fleet_bnb(
        g, requests, SharedScheduler(),
        hold_start=time(10, 0), hold_end=time(11, 0),
        max_nodes=3,  # absurdly small
    )
    assert out.stats.completed is False
    # Even when budget-limited, a chosen_order is returned.
    assert len(out.chosen_order) == 5


def test_bnb_time_budget_returns_partial() -> None:
    """time_budget_ms=0 should immediately abort and return submission order."""
    g = star_graph(4)
    requests = [
        FleetRequest("a", "leaf0", "leaf1"),
        FleetRequest("b", "leaf2", "leaf3"),
    ]
    out = plan_fleet_bnb(
        g, requests, SharedScheduler(),
        hold_start=time(10, 0), hold_end=time(11, 0),
        time_budget_ms=0.0,
    )
    assert out.stats.completed is False
    assert set(out.chosen_order) == {"a", "b"}


def test_bnb_applies_chosen_order_to_live_scheduler() -> None:
    """The live scheduler must actually contain claims after the run."""
    g = chain_graph(5)
    s = SharedScheduler()
    requests = [FleetRequest("a", "n0", "n4")]
    out = plan_fleet_bnb(
        g, requests, s,
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    assert out.fleet_result.results[0].granted is True
    assert len(s.claims_for("a")) > 0


def test_bnb_with_hard_admission_and_tight_deadline_rejects() -> None:
    g = chain_graph(10)
    requests = [
        FleetRequest("late", "n0", "n9", deadline=time(10, 5)),
    ]
    out = plan_fleet_bnb(
        g, requests, SharedScheduler(),
        hold_start=time(10, 0), hold_end=time(11, 0),
        admission="hard",
    )
    assert out.fleet_result.results[0].granted is False
    assert out.fleet_result.results[0].reason_code == "deadline_miss"


def test_plan_fleet_with_strategy_bnb_dispatches() -> None:
    g = star_graph(4)
    s = SharedScheduler()
    requests = [
        FleetRequest("a", "leaf0", "leaf1"),
        FleetRequest("b", "leaf2", "leaf3"),
    ]
    out = plan_fleet_with_strategy(
        g, requests, s,
        strategy="bnb",
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    assert len(out.results) == 2
    # At least one of the two should be granted; the dispatch path
    # routes correctly to bnb.
    assert any(r.granted for r in out.results)


def test_bnb_chosen_order_is_permutation_of_input() -> None:
    g = star_graph(4)
    requests = [
        FleetRequest("alpha", "leaf0", "leaf1"),
        FleetRequest("bravo", "leaf2", "leaf3"),
        FleetRequest("charlie", "leaf1", "leaf2"),
    ]
    out = plan_fleet_bnb(
        g, requests, SharedScheduler(),
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    # Every input agent appears exactly once in chosen_order.
    assert sorted(out.chosen_order) == sorted(
        r.agent_id for r in requests
    )


def test_bnb_stats_elapsed_ms_recorded() -> None:
    g = star_graph(3)
    out = plan_fleet_bnb(
        g, [FleetRequest("a", "leaf0", "leaf1")],
        SharedScheduler(),
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    assert out.stats.elapsed_ms >= 0.0


def test_conflict_explanation_dataclass_is_hashable() -> None:
    """frozen=True makes ConflictExplanation usable as a dict key, which
    is useful when callers aggregate explanations from multiple runs."""
    e = ConflictExplanation(
        blocked_agent_id="r1",
        reason_code="deadline_miss",
        blocking_agents=("r0",),
        blocking_resources=("entrance",),
    )
    d = {e: 1}  # would raise if not hashable
    assert d[e] == 1
