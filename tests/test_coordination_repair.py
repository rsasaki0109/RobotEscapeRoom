"""Tests for plan_fleet_insert — insertion-based fleet repair planner."""

from __future__ import annotations

from datetime import time

import pytest

from semantic_toponav.coordination import plan_fleet_insert
from semantic_toponav.coordination.branch_and_bound import (
    BnBPlanResult,
    plan_fleet_bnb,
)
from semantic_toponav.coordination.fleet import FleetRequest
from semantic_toponav.coordination.scheduler import SharedScheduler
from semantic_toponav.eval.generators import (
    chain_graph,
    star_graph,
)


def _granted(result: BnBPlanResult) -> set[str]:
    return {r.agent_id for r in result.fleet_result.results if r.granted}


def test_insert_empty_new_requests_runs_committed_unchanged() -> None:
    g = chain_graph(5)
    s = SharedScheduler()
    committed = [FleetRequest("a", "n0", "n4")]
    out = plan_fleet_insert(
        g,
        committed=committed,
        new_requests=[],
        scheduler=s,
        hold_start=time(10, 0),
        hold_end=time(11, 0),
    )
    assert out.chosen_order == ("a",)
    assert _granted(out) == {"a"}
    # Live scheduler reflects the committed agent's claims.
    assert len(s) > 0
    assert s.claims_for("a")


def test_insert_into_empty_committed_yields_new_only() -> None:
    g = chain_graph(5)
    s = SharedScheduler()
    out = plan_fleet_insert(
        g,
        committed=[],
        new_requests=[FleetRequest("x", "n0", "n4")],
        scheduler=s,
        hold_start=time(10, 0),
        hold_end=time(11, 0),
    )
    assert out.chosen_order == ("x",)
    assert _granted(out) == {"x"}


def test_insert_single_new_request_finds_compatible_position() -> None:
    """On star_graph the hub is contended, so insertion order matters."""
    g = star_graph(5)
    s = SharedScheduler()
    committed = [
        FleetRequest("a", "leaf0", "leaf1"),
        FleetRequest("b", "leaf2", "leaf3"),
    ]
    out = plan_fleet_insert(
        g,
        committed=committed,
        new_requests=[FleetRequest("c", "leaf3", "leaf4")],
        scheduler=s,
        hold_start=time(10, 0),
        hold_end=time(11, 0),
    )
    # The new agent appears in the merged ordering.
    assert "c" in out.chosen_order
    # All three committed-or-new entries appear exactly once.
    assert set(out.chosen_order) == {"a", "b", "c"}
    assert len(out.chosen_order) == 3


def test_insert_explores_every_position_for_each_new_request() -> None:
    """nodes_explored == sum of (len(current)+1) across insertions."""
    g = chain_graph(5)
    s = SharedScheduler()
    committed = [FleetRequest("a", "n0", "n1"), FleetRequest("b", "n3", "n4")]
    out = plan_fleet_insert(
        g,
        committed=committed,
        new_requests=[
            FleetRequest("c", "n0", "n2"),
            FleetRequest("d", "n2", "n4"),
        ],
        scheduler=s,
        hold_start=time(10, 0),
        hold_end=time(11, 0),
    )
    # First insertion: 3 positions (committed has 2 entries). Second
    # insertion runs against a length-3 ordering: 4 positions.
    assert out.stats.nodes_explored == 3 + 4
    assert out.stats.completed is True


def test_insert_duplicate_agent_id_raises() -> None:
    g = chain_graph(5)
    s = SharedScheduler()
    committed = [FleetRequest("a", "n0", "n4")]
    with pytest.raises(ValueError, match="appears in both"):
        plan_fleet_insert(
            g,
            committed=committed,
            new_requests=[FleetRequest("a", "n1", "n3")],
            scheduler=s,
            hold_start=time(10, 0),
            hold_end=time(11, 0),
        )


def test_insert_result_is_bnb_compatible() -> None:
    """plan_fleet_insert returns a BnBPlanResult drop-in."""
    g = chain_graph(5)
    s = SharedScheduler()
    out = plan_fleet_insert(
        g,
        committed=[FleetRequest("a", "n0", "n4")],
        new_requests=[FleetRequest("b", "n1", "n3")],
        scheduler=s,
        hold_start=time(10, 0),
        hold_end=time(11, 0),
    )
    assert isinstance(out, BnBPlanResult)
    # Drop-in fields are populated.
    assert isinstance(out.chosen_order, tuple)
    assert out.fleet_result is not None
    assert isinstance(out.per_agent_costs, dict)
    # Repair does not produce conflict explanations — the BnB inner
    # loop is not run.
    assert out.conflict_explanations == []


def test_insert_finds_at_least_as_many_grants_as_naive_appending() -> None:
    """Property: insertion search must match or beat the trivial
    last-position fallback (append the new request after the committed
    list)."""
    g = star_graph(6)
    s_insert = SharedScheduler()
    s_append = SharedScheduler()
    committed = [
        FleetRequest("a", "leaf0", "leaf1"),
        FleetRequest("b", "leaf2", "leaf3"),
    ]
    new = FleetRequest("c", "leaf4", "leaf5")
    insert_out = plan_fleet_insert(
        g, committed=committed, new_requests=[new], scheduler=s_insert,
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    from semantic_toponav.coordination.fleet import plan_fleet

    append_result = plan_fleet(
        g, [*committed, new], s_append,
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    appended_grants = sum(1 for r in append_result.results if r.granted)
    insert_grants = len(_granted(insert_out))
    assert insert_grants >= appended_grants


def test_insert_live_scheduler_reflects_final_ordering() -> None:
    g = chain_graph(6)
    s = SharedScheduler()
    out = plan_fleet_insert(
        g,
        committed=[FleetRequest("a", "n0", "n2"), FleetRequest("b", "n3", "n5")],
        new_requests=[FleetRequest("c", "n2", "n4")],
        scheduler=s,
        hold_start=time(10, 0),
        hold_end=time(11, 0),
    )
    # Granted agents have claims on the live scheduler.
    for aid in out.fleet_result.results:
        if aid.granted:
            assert s.claims_for(aid.agent_id), (
                f"granted agent {aid.agent_id} has no live claims"
            )


def test_insert_under_hard_admission_with_deadline() -> None:
    """Non-overlapping paths must both pass hard admission."""
    g = chain_graph(10)
    s = SharedScheduler()
    out = plan_fleet_insert(
        g,
        committed=[FleetRequest("a", "n0", "n3", deadline=time(11, 0))],
        new_requests=[FleetRequest("b", "n5", "n9", deadline=time(11, 0))],
        scheduler=s,
        hold_start=time(10, 0),
        hold_end=time(11, 0),
        admission="hard",
        minutes_per_cost_unit=1.0,
    )
    assert _granted(out) == {"a", "b"}


def test_insert_objective_minimax_changes_ordering_when_helpful() -> None:
    """A min_cost insertion and a minimax_cost insertion may pick
    different positions when the cost spread differs across orderings.
    We just verify both run without error and return valid orderings."""
    g = chain_graph(8)
    committed = [
        FleetRequest("a", "n0", "n1"),
        FleetRequest("b", "n6", "n7"),
    ]
    new = [FleetRequest("c", "n3", "n4")]
    s1, s2 = SharedScheduler(), SharedScheduler()
    out_min = plan_fleet_insert(
        g, committed=committed, new_requests=new, scheduler=s1,
        hold_start=time(10, 0), hold_end=time(11, 0), objective="min_cost",
    )
    out_max = plan_fleet_insert(
        g, committed=committed, new_requests=new, scheduler=s2,
        hold_start=time(10, 0), hold_end=time(11, 0), objective="minimax_cost",
    )
    # Both run cleanly and produce 3-agent orderings.
    assert set(out_min.chosen_order) == {"a", "b", "c"}
    assert set(out_max.chosen_order) == {"a", "b", "c"}


def test_insert_matches_bnb_when_committed_is_empty_and_new_is_small() -> None:
    """Insertion-from-empty over a 2-agent set should match BnB's optimum
    on that same set (insertion exhaustively explores both positions of
    the second request)."""
    g = chain_graph(5)
    requests = [
        FleetRequest("a", "n0", "n4"),
        FleetRequest("b", "n1", "n3"),
    ]
    s_insert = SharedScheduler()
    s_bnb = SharedScheduler()
    insert_out = plan_fleet_insert(
        g, committed=[], new_requests=requests, scheduler=s_insert,
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    bnb_out = plan_fleet_bnb(
        g, requests, s_bnb,
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    insert_grants = len(_granted(insert_out))
    bnb_grants = sum(1 for r in bnb_out.fleet_result.results if r.granted)
    assert insert_grants == bnb_grants
