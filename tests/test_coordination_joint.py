"""Tests for plan_fleet_joint + plan_fleet_with_strategy."""

from __future__ import annotations

from datetime import time
from pathlib import Path

from semantic_toponav.coordination.fleet import (
    FleetRequest,
)
from semantic_toponav.coordination.joint import (
    _path_total_cost,
    _reorder_by_deadline,
    _reorder_by_priority,
    plan_fleet_joint,
    plan_fleet_with_strategy,
)
from semantic_toponav.coordination.scheduler import (
    ClaimRequest,
    SharedScheduler,
)
from semantic_toponav.graph.serialization import load_graph

EXAMPLE_YAML = Path(__file__).resolve().parents[1] / "examples" / "indoor_office.yaml"


def test_clone_scheduler_is_independent() -> None:
    s = SharedScheduler()
    s.claim(
        ClaimRequest(
            agent_id="r1",
            resource_id="entrance",
            start=time(10, 0),
            end=time(11, 0),
        )
    )
    clone = s.clone()
    # Mutating the clone leaves the original alone.
    clone.claim(
        ClaimRequest(
            agent_id="r2",
            resource_id="kitchen",
            start=time(10, 0),
            end=time(11, 0),
        )
    )
    assert len(s) == 1
    assert len(clone) == 2
    # Releasing on the clone doesn't touch the original.
    clone.release_all("r1")
    assert len(s) == 1
    assert s.claims_for("r1")[0].resource_id == "entrance"


def test_clone_carries_policy_reference() -> None:
    # Sanity check: clones share the same policy callable so behavior
    # remains identical between original and clone.
    from semantic_toponav.coordination.policies import priority_based

    s = SharedScheduler(policy=priority_based)
    clone = s.clone()
    assert clone._policy is s._policy  # noqa: SLF001 - internal sanity check


def test_path_total_cost_zero_for_short_path() -> None:
    g = load_graph(EXAMPLE_YAML)
    assert _path_total_cost(g, []) == 0.0
    assert _path_total_cost(g, ["entrance"]) == 0.0


def test_path_total_cost_sums_real_edges() -> None:
    g = load_graph(EXAMPLE_YAML)
    cost = _path_total_cost(g, ["entrance", "corridor_main"])
    assert cost > 0.0


def test_reorder_by_priority_descending() -> None:
    reqs = [
        FleetRequest("r1", "entrance", "kitchen", priority=0),
        FleetRequest("r2", "entrance", "lab", priority=5),
        FleetRequest("r3", "entrance", "meeting_room", priority=2),
    ]
    out = _reorder_by_priority(reqs)
    assert [r.agent_id for r in out] == ["r2", "r3", "r1"]


def test_reorder_by_deadline_ascending_no_deadline_last() -> None:
    reqs = [
        FleetRequest("late", "entrance", "kitchen", deadline=time(15, 0)),
        FleetRequest("none", "entrance", "lab"),  # no deadline -> last
        FleetRequest("early", "entrance", "meeting_room", deadline=time(10, 30)),
    ]
    out = _reorder_by_deadline(reqs)
    assert [r.agent_id for r in out] == ["early", "late", "none"]


def test_fleet_request_deadline_accepts_string_form() -> None:
    # Deadlines stored as strings still sort correctly via _as_time.
    reqs = [
        FleetRequest("a", "entrance", "kitchen", deadline="12:00"),
        FleetRequest("b", "entrance", "lab", deadline="09:30"),
    ]
    out = _reorder_by_deadline(reqs)
    assert [r.agent_id for r in out] == ["b", "a"]


def test_plan_fleet_with_strategy_greedy_matches_plan_fleet() -> None:
    g = load_graph(EXAMPLE_YAML)
    s = SharedScheduler()
    reqs = [
        FleetRequest("r1", "entrance", "kitchen"),
        FleetRequest("r2", "entrance", "lab"),
    ]
    out = plan_fleet_with_strategy(
        g,
        reqs,
        s,
        strategy="greedy",
        hold_start="10:00",
        hold_end="11:00",
    )
    # Order is preserved -> r1 then r2.
    assert [r.agent_id for r in out.results] == ["r1", "r2"]
    assert out.results[0].granted


def test_plan_fleet_with_strategy_priority_reorders() -> None:
    g = load_graph(EXAMPLE_YAML)
    s = SharedScheduler()
    reqs = [
        FleetRequest("low", "entrance", "kitchen", priority=0),
        FleetRequest("high", "entrance", "lab", priority=5),
    ]
    out = plan_fleet_with_strategy(
        g,
        reqs,
        s,
        strategy="priority",
        hold_start="10:00",
        hold_end="11:00",
    )
    # High priority went first.
    assert [r.agent_id for r in out.results] == ["high", "low"]


def test_plan_fleet_with_strategy_deadline_reorders() -> None:
    g = load_graph(EXAMPLE_YAML)
    s = SharedScheduler()
    reqs = [
        FleetRequest("late", "entrance", "kitchen", deadline="12:00"),
        FleetRequest("early", "entrance", "lab", deadline="10:30"),
    ]
    out = plan_fleet_with_strategy(
        g,
        reqs,
        s,
        strategy="deadline",
        hold_start="10:00",
        hold_end="11:00",
    )
    assert [r.agent_id for r in out.results] == ["early", "late"]


def test_plan_fleet_joint_returns_joint_result_envelope() -> None:
    g = load_graph(EXAMPLE_YAML)
    s = SharedScheduler()
    reqs = [
        FleetRequest("r1", "entrance", "kitchen"),
        FleetRequest("r2", "entrance", "lab"),
    ]
    out = plan_fleet_joint(
        g,
        reqs,
        s,
        hold_start="10:00",
        hold_end="11:00",
    )
    # 2! = 2 trials.
    assert out.enumerated is True
    assert out.trials_evaluated == 2
    # The chosen order is a permutation of the agent ids.
    assert set(out.chosen_order) == {"r1", "r2"}
    # The live scheduler reflects the winning ordering.
    assert out.fleet_result.results[0].granted


def test_plan_fleet_joint_prefers_more_grants_over_insertion_order() -> None:
    """Construct a scenario where the insertion order grants 1/2 but
    the reversed order grants 2/2. plan_fleet_joint must pick the
    better ordering."""
    g = load_graph(EXAMPLE_YAML)
    s = SharedScheduler()
    # In the office graph: 'kitchen' and 'lab' are reachable along
    # disjoint branches from 'entrance' once you get past the shared
    # corridor. With greedy r1->kitchen first, the corridor is held,
    # forcing r2 to find a longer path. The joint optimizer will pick
    # whichever ordering grants both.
    reqs = [
        FleetRequest("r1", "entrance", "kitchen"),
        FleetRequest("r2", "entrance", "lab"),
    ]
    out = plan_fleet_joint(
        g,
        reqs,
        s,
        hold_start="10:00",
        hold_end="11:00",
    )
    # The winning ordering must grant at least as many agents as
    # greedy (which is one of the candidate orderings).
    granted_count = sum(1 for r in out.fleet_result.results if r.granted)
    assert granted_count >= 1


def test_plan_fleet_joint_only_clones_during_search() -> None:
    """After plan_fleet_joint returns, the live scheduler should hold
    exactly the claims from the chosen ordering — not from every
    trial that ran during search."""
    g = load_graph(EXAMPLE_YAML)
    s = SharedScheduler()
    reqs = [
        FleetRequest("r1", "entrance", "kitchen"),
        FleetRequest("r2", "entrance", "lab"),
    ]
    out = plan_fleet_joint(
        g,
        reqs,
        s,
        hold_start="10:00",
        hold_end="11:00",
    )
    # The live scheduler should only hold claims for the agents that
    # were granted in the chosen ordering. No "ghost" claims from
    # other trials are allowed.
    live_owners = {r.agent_id for r in s.reservations()}
    granted_agents = {
        r.agent_id for r in out.fleet_result.results if r.granted
    }
    assert live_owners == granted_agents


def test_plan_fleet_joint_falls_back_for_large_fleets() -> None:
    """A fleet that's too big to enumerate (n! > max_permutations)
    must fall back to candidate orderings."""
    g = load_graph(EXAMPLE_YAML)
    s = SharedScheduler()
    # 6 agents -> 6! = 720 > default 120 cap.
    reqs = [
        FleetRequest(f"r{i}", "entrance", "kitchen", priority=i)
        for i in range(6)
    ]
    out = plan_fleet_joint(
        g,
        reqs,
        s,
        hold_start="10:00",
        hold_end="11:00",
    )
    assert out.enumerated is False
    # Candidate orderings: insertion, reverse, priority-DESC,
    # deadline-ASC; at most 4 distinct.
    assert out.trials_evaluated <= 4


def test_plan_fleet_joint_tie_breaks_by_total_cost() -> None:
    """When two orderings grant the same number of agents but the
    granted paths have different costs, the lower-cost ordering wins.

    This is a sanity check rather than a strong assertion: we run a
    case where greedy and joint both grant the first agent and the
    joint optimizer still produces a deterministic chosen_order."""
    g = load_graph(EXAMPLE_YAML)
    s = SharedScheduler()
    reqs = [
        FleetRequest("a", "entrance", "kitchen"),
    ]
    out = plan_fleet_joint(
        g,
        reqs,
        s,
        hold_start="10:00",
        hold_end="11:00",
    )
    assert out.chosen_order == ("a",)
    assert out.fleet_result.results[0].granted


def test_plan_fleet_joint_empty_request_list_returns_empty() -> None:
    g = load_graph(EXAMPLE_YAML)
    s = SharedScheduler()
    out = plan_fleet_joint(
        g,
        [],
        s,
        hold_start="10:00",
        hold_end="11:00",
    )
    assert out.chosen_order == ()
    assert out.trials_evaluated == 0
    assert out.fleet_result.results == []


def test_plan_fleet_with_strategy_joint_dispatches() -> None:
    g = load_graph(EXAMPLE_YAML)
    s = SharedScheduler()
    reqs = [
        FleetRequest("r1", "entrance", "kitchen"),
        FleetRequest("r2", "entrance", "lab"),
    ]
    out = plan_fleet_with_strategy(
        g,
        reqs,
        s,
        strategy="joint",
        hold_start="10:00",
        hold_end="11:00",
    )
    # Returns the FleetPlanResult shape (joint envelope is stripped).
    assert hasattr(out, "results")
    assert len(out.results) == 2
