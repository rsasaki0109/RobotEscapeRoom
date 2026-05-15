"""Tests for plan_fleet_exhaustive — MIS upper bound on grant rate."""

from __future__ import annotations

from datetime import time

import pytest

from semantic_toponav.coordination.branch_and_bound import plan_fleet_bnb
from semantic_toponav.coordination.exhaustive import (
    _build_conflict_graph,
    _resources_on_path,
    _subset_is_independent,
    plan_fleet_exhaustive,
)
from semantic_toponav.coordination.fleet import FleetRequest
from semantic_toponav.coordination.scheduler import SharedScheduler
from semantic_toponav.eval.generators import (
    chain_graph,
    doorway_graph,
)

# ----- helpers ---------------------------------------------------------------


def test_resources_on_path_nodes_only() -> None:
    out = _resources_on_path(["a", "b", "c"], claim_nodes=True, claim_edges=False)
    assert out == {"a", "b", "c"}


def test_resources_on_path_edges_only() -> None:
    out = _resources_on_path(["a", "b", "c"], claim_nodes=False, claim_edges=True)
    # Edges canonicalized so direction doesn't matter.
    assert out == {"edge:a|b", "edge:b|c"}


def test_resources_on_path_both() -> None:
    out = _resources_on_path(["a", "b", "c"], claim_nodes=True, claim_edges=True)
    assert out == {"a", "b", "c", "edge:a|b", "edge:b|c"}


def test_resources_on_path_canonical_edge_order() -> None:
    """An agent going b->a shares the same edge identifier as a->b."""
    ab = _resources_on_path(["a", "b"], claim_nodes=False, claim_edges=True)
    ba = _resources_on_path(["b", "a"], claim_nodes=False, claim_edges=True)
    assert ab == ba == {"edge:a|b"}


# ----- conflict graph --------------------------------------------------------


def test_conflict_graph_two_disjoint_paths_no_edges() -> None:
    adj = _build_conflict_graph(
        {"r1": ["a", "b"], "r2": ["c", "d"]},
        claim_nodes=True, claim_edges=True,
    )
    assert adj["r1"] == set()
    assert adj["r2"] == set()


def test_conflict_graph_paths_sharing_node_conflict() -> None:
    adj = _build_conflict_graph(
        {"r1": ["a", "b"], "r2": ["b", "c"]},
        claim_nodes=True, claim_edges=True,
    )
    assert adj["r1"] == {"r2"}
    assert adj["r2"] == {"r1"}


def test_subset_is_independent_empty_and_singleton() -> None:
    adj = {"r1": {"r2"}, "r2": {"r1"}, "r3": set()}
    assert _subset_is_independent((), adj) is True
    assert _subset_is_independent(("r1",), adj) is True


def test_subset_is_independent_conflicting_pair() -> None:
    adj = {"r1": {"r2"}, "r2": {"r1"}}
    assert _subset_is_independent(("r1", "r2"), adj) is False


def test_subset_is_independent_three_with_one_pair() -> None:
    adj = {"r1": set(), "r2": {"r3"}, "r3": {"r2"}}
    assert _subset_is_independent(("r1", "r2", "r3"), adj) is False
    assert _subset_is_independent(("r1", "r2"), adj) is True


# ----- empty / trivial inputs ------------------------------------------------


def test_exhaustive_empty_returns_empty_result() -> None:
    g = chain_graph(3)
    out = plan_fleet_exhaustive(
        g, [], SharedScheduler(),
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    assert out.granted_agents == ()
    assert out.fleet_result.results == []


def test_exhaustive_single_agent_grants_it() -> None:
    g = chain_graph(3)
    out = plan_fleet_exhaustive(
        g, [FleetRequest("a", "n0", "n2")], SharedScheduler(),
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    assert out.granted_agents == ("a",)
    assert out.stats.n_independent_plans_granted == 1


# ----- n_limit guard --------------------------------------------------------


def test_exhaustive_rejects_oversized_fleet() -> None:
    g = chain_graph(5)
    requests = [FleetRequest(f"r{i}", "n0", "n4") for i in range(5)]
    with pytest.raises(ValueError, match="exceeds n_limit"):
        plan_fleet_exhaustive(
            g, requests, SharedScheduler(),
            hold_start=time(10, 0), hold_end=time(11, 0),
            n_limit=3,
        )


# ----- MIS optimum ----------------------------------------------------------


def test_exhaustive_picks_disjoint_subset_over_conflicting_one() -> None:
    """In a chain a→b→c→d→e, two requests {a→b} and {c→d→e} can both
    grant; one request {a→c} conflicts with both. The exhaustive
    enumerator must keep the disjoint pair, not the conflicting one."""
    g = chain_graph(5)
    requests = [
        FleetRequest("disjoint1", "n0", "n1"),
        FleetRequest("disjoint2", "n3", "n4"),
        FleetRequest("conflicts_both", "n0", "n3"),
    ]
    out = plan_fleet_exhaustive(
        g, requests, SharedScheduler(),
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    assert set(out.granted_agents) == {"disjoint1", "disjoint2"}


def test_exhaustive_grant_count_at_least_bnb_grant_count() -> None:
    """The exhaustive baseline is the upper bound on grants for fixed
    independent paths. BnB respects a sequential admission policy so
    it can grant fewer, never more."""
    g = doorway_graph(n_rooms=3)
    requests = [
        FleetRequest("a", "room0", "room2"),
        FleetRequest("b", "room2", "room0"),
        FleetRequest("c", "room1", "room0"),
    ]
    bnb = plan_fleet_bnb(
        g, requests, SharedScheduler(),
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    exhaustive = plan_fleet_exhaustive(
        g, requests, SharedScheduler(),
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    bnb_grants = sum(1 for r in bnb.fleet_result.results if r.granted)
    exh_grants = sum(1 for r in exhaustive.fleet_result.results if r.granted)
    assert exh_grants >= bnb_grants


# ----- live scheduler mutation ----------------------------------------------


def test_exhaustive_applies_subset_to_live_scheduler() -> None:
    """After the call, the input scheduler has the granted subset's
    holds — the function is not pure with respect to its scheduler
    argument."""
    # 6-node chain: r1 occupies the front half (n0-n2), r2 the back
    # half (n3-n5). They share no nodes/edges so both grant.
    g = chain_graph(6)
    s = SharedScheduler()
    requests = [
        FleetRequest("a", "n0", "n2"),
        FleetRequest("b", "n3", "n5"),
    ]
    out = plan_fleet_exhaustive(
        g, requests, s,
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    assert len(out.granted_agents) == 2
    assert len(s) > 0


def test_exhaustive_does_not_mutate_input_scheduler_during_independent_plan() -> None:
    """The per-agent independent plan step must clone-and-discard;
    the input scheduler should reach the apply step holding only what
    it held *before* the call (plus then the granted subset's holds)."""
    g = chain_graph(3)
    s = SharedScheduler()
    # Pre-load a hold that's unrelated to any agent's path.
    from semantic_toponav.coordination.scheduler import ClaimRequest
    s.claim(
        ClaimRequest(
            agent_id="external", resource_id="far_away_resource",
            start=time(8, 0), end=time(9, 0),
        )
    )
    requests = [FleetRequest("a", "n0", "n2")]
    plan_fleet_exhaustive(
        g, requests, s,
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    # The external claim must still be present.
    external = s.claims_for("external")
    assert len(external) == 1
    assert external[0].resource_id == "far_away_resource"


# ----- stats reporting ------------------------------------------------------


def test_exhaustive_stats_records_subsets_evaluated() -> None:
    g = chain_graph(4)
    requests = [
        FleetRequest("a", "n0", "n1"),
        FleetRequest("b", "n2", "n3"),
        FleetRequest("c", "n0", "n3"),
    ]
    out = plan_fleet_exhaustive(
        g, requests, SharedScheduler(),
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    assert out.stats.n_agents == 3
    assert out.stats.n_independent_plans_granted == 3
    assert out.stats.subsets_evaluated >= 1
    assert out.stats.elapsed_ms >= 0.0


def test_exhaustive_stats_completed_true_on_normal_finish() -> None:
    g = chain_graph(3)
    out = plan_fleet_exhaustive(
        g, [FleetRequest("a", "n0", "n2")], SharedScheduler(),
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    assert out.stats.completed is True


# ----- independent paths exposed ---------------------------------------------


def test_exhaustive_independent_paths_recorded_for_all_agents() -> None:
    """independent_paths maps every input agent_id (granted or not).
    For granted plans, the path is non-empty; otherwise it's empty."""
    g = chain_graph(3)
    requests = [
        FleetRequest("a", "n0", "n2"),
        FleetRequest("b", "n0", "n2"),  # shares every node with a
    ]
    out = plan_fleet_exhaustive(
        g, requests, SharedScheduler(),
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    assert set(out.independent_paths) == {"a", "b"}
    assert out.independent_paths["a"] == ["n0", "n1", "n2"]
    assert out.independent_paths["b"] == ["n0", "n1", "n2"]
    # Only one of the two pairs can be granted (they fully overlap).
    assert len(out.granted_agents) == 1


# ----- cost tie-break --------------------------------------------------------


def test_exhaustive_ties_break_on_total_cost() -> None:
    """When two subsets have equal grant count, the lower-cost one wins."""
    # In a 5-node chain a→b→c→d→e:
    # - {a→b} costs 1
    # - {a→e} costs 4
    # - {c→d} costs 1
    # Both {a→b, c→d} (cost 2) and {a→e} (cost 4) are independent and
    # size 2 vs 1. Size dominates → {a→b, c→d} wins; this is the
    # primary size check. To test cost tie-break, we need two
    # same-size subsets where only the cheaper survives — use two
    # mutually exclusive single-agent options.
    g = chain_graph(5)
    requests = [
        FleetRequest("cheap", "n0", "n1"),
        FleetRequest("expensive", "n0", "n4"),
    ]
    # These two conflict via node n0; only one wins. The cheaper
    # (cost 1) wins over the expensive (cost 4).
    out = plan_fleet_exhaustive(
        g, requests, SharedScheduler(),
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    assert out.granted_agents == ("cheap",)
