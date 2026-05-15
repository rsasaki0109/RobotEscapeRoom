"""Tests for plan_with_scheduler + plan_fleet."""

from __future__ import annotations

from pathlib import Path

from semantic_toponav.coordination.fleet import (
    FleetRequest,
    plan_fleet,
    plan_with_scheduler,
)
from semantic_toponav.coordination.policies import priority_based
from semantic_toponav.coordination.scheduler import (
    ClaimRequest,
    SharedScheduler,
)
from semantic_toponav.graph.serialization import load_graph

EXAMPLE_YAML = Path(__file__).resolve().parents[1] / "examples" / "indoor_office.yaml"


def test_plan_with_scheduler_succeeds_against_empty_scheduler() -> None:
    g = load_graph(EXAMPLE_YAML)
    s = SharedScheduler()
    result = plan_with_scheduler(
        g,
        agent_id="r1",
        start="entrance",
        goal="kitchen",
        scheduler=s,
        hold_start="10:00",
        hold_end="11:00",
    )
    assert result.granted is True
    assert result.path[0] == "entrance"
    assert result.path[-1] == "kitchen"
    # Should hold every node on the path and every traversed edge.
    held = {c.resource_id for c in result.claims}
    assert "entrance" in held
    assert "kitchen" in held
    # At least one edge id should be reserved too.
    assert any("corridor" in rid or "kitchen" in rid for rid in held)


def test_plan_with_scheduler_routes_around_other_agents_claims() -> None:
    g = load_graph(EXAMPLE_YAML)
    s = SharedScheduler()
    # r1 grabs the meeting room directly.
    first = plan_with_scheduler(
        g,
        agent_id="r1",
        start="entrance",
        goal="meeting_room",
        scheduler=s,
        hold_start="10:00",
        hold_end="11:00",
    )
    assert first.granted
    # r2 wants the kitchen at the same time. The claims on lobby_intersection
    # / corridor_main should force r2 down a different route.
    second = plan_with_scheduler(
        g,
        agent_id="r2",
        start="entrance",
        goal="kitchen",
        scheduler=s,
        hold_start="10:00",
        hold_end="11:00",
    )
    # Either r2 finds a different route or it fails honestly with a
    # claim-conflict reason — both are acceptable. What we don't want
    # is a silent success that double-books r1's claims.
    if second.granted:
        r1_ids = {c.resource_id for c in first.claims}
        r2_ids = {c.resource_id for c in second.claims}
        assert r1_ids.isdisjoint(r2_ids)
    else:
        assert second.failure_reason is not None


def test_plan_with_scheduler_no_path_returns_failure() -> None:
    g = load_graph(EXAMPLE_YAML)
    s = SharedScheduler()
    # Pre-claim the entire entrance + corridor + lobby so no path can exist.
    for rid in ("entrance", "corridor_main", "lobby_intersection"):
        s.claim(
            ClaimRequest(
                agent_id="blocker",
                resource_id=rid,
                start=__import__("datetime").time(10, 0),
                end=__import__("datetime").time(11, 0),
            )
        )
    result = plan_with_scheduler(
        g,
        agent_id="r1",
        start="entrance",
        goal="meeting_room",
        scheduler=s,
        hold_start="10:00",
        hold_end="11:00",
    )
    assert result.granted is False
    assert result.failure_reason is not None


def test_plan_with_scheduler_release_resets_state() -> None:
    g = load_graph(EXAMPLE_YAML)
    s = SharedScheduler()
    first = plan_with_scheduler(
        g,
        agent_id="r1",
        start="entrance",
        goal="kitchen",
        scheduler=s,
        hold_start="10:00",
        hold_end="11:00",
    )
    assert first.granted
    s.release_all("r1")
    assert s.claims_for("r1") == []
    # Same plan should work again for r2.
    second = plan_with_scheduler(
        g,
        agent_id="r2",
        start="entrance",
        goal="kitchen",
        scheduler=s,
        hold_start="10:00",
        hold_end="11:00",
    )
    assert second.granted


def test_plan_with_scheduler_claim_edges_only() -> None:
    g = load_graph(EXAMPLE_YAML)
    s = SharedScheduler()
    result = plan_with_scheduler(
        g,
        agent_id="r1",
        start="entrance",
        goal="kitchen",
        scheduler=s,
        hold_start="10:00",
        hold_end="11:00",
        claim_nodes=False,
        claim_edges=True,
    )
    assert result.granted
    held = {c.resource_id for c in result.claims}
    # No node ids should be in the held set.
    assert "entrance" not in held
    assert "kitchen" not in held


def test_plan_fleet_sequential_three_agents() -> None:
    g = load_graph(EXAMPLE_YAML)
    s = SharedScheduler()
    requests = [
        FleetRequest("r1", "entrance", "kitchen"),
        FleetRequest("r2", "entrance", "lab"),
        FleetRequest("r3", "entrance", "office_2f"),
    ]
    result = plan_fleet(
        g,
        requests,
        s,
        hold_start="10:00",
        hold_end="11:00",
    )
    # The kitchen and lab are reachable on different branches of the
    # ground floor; office_2f is on the second floor. All three should
    # find paths even with shared traversal points like 'entrance', as
    # long as we recognise that the scheduler will keep 'entrance'
    # reserved for r1 and so r2 / r3 will report a conflict.
    granted = [r for r in result.results if r.granted]
    failed = [r for r in result.results if not r.granted]
    # r1 always succeeds.
    assert result.results[0].granted
    # The other two either succeed via alternative routes or fail
    # cleanly — but the *first* one always wins, and the scheduler
    # never duplicates a hold.
    all_held_resources: list[str] = []
    for r in granted:
        all_held_resources.extend(c.resource_id for c in r.claims)
    assert len(all_held_resources) == len(set(all_held_resources)), (
        f"resource double-booked across fleet members: {all_held_resources}"
    )
    if failed:
        for r in failed:
            assert r.failure_reason is not None


def test_plan_fleet_priority_lets_high_priority_preempt() -> None:
    g = load_graph(EXAMPLE_YAML)
    s = SharedScheduler(policy=priority_based)
    requests = [
        # r1 (default priority 0) goes first and grabs the kitchen path.
        FleetRequest("r1", "entrance", "kitchen", priority=0),
        # r2 wants the same goal at higher priority -> preempts r1.
        FleetRequest("r2", "entrance", "kitchen", priority=5),
    ]
    result = plan_fleet(
        g,
        requests,
        s,
        hold_start="10:00",
        hold_end="11:00",
    )
    by_agent = result.by_agent()
    assert by_agent["r1"].granted
    assert by_agent["r2"].granted
    # r1's claims got preempted; r2 holds the path now.
    assert s.claims_for("r1") == []
    assert len(s.claims_for("r2")) > 0


def test_plan_fleet_rollback_on_failure_releases_everything() -> None:
    g = load_graph(EXAMPLE_YAML)
    s = SharedScheduler()
    # Pre-block every entrance route so any second agent reaching for
    # a goal that needs 'entrance' will fail.
    requests = [
        FleetRequest("r1", "entrance", "kitchen"),
        # r2 goal is identical to r1's start -> will conflict on entrance
        FleetRequest("r2", "entrance", "lab"),
        # r3 won't even be planned because rollback aborts the loop.
        FleetRequest("r3", "entrance", "meeting_room"),
    ]
    result = plan_fleet(
        g,
        requests,
        s,
        hold_start="10:00",
        hold_end="11:00",
        rollback_on_failure=True,
    )
    # At least one of r1 / r2 fails; on first failure, rollback wipes
    # the scheduler.
    failed_idx = next(
        (i for i, r in enumerate(result.results) if not r.granted), None
    )
    if failed_idx is not None:
        # Everything is released after rollback.
        assert s.reservations() == []
        # r3 never ran.
        assert len(result.results) == failed_idx + 1


def test_plan_fleet_all_granted_property() -> None:
    g = load_graph(EXAMPLE_YAML)
    s = SharedScheduler()
    # One trivial request that always succeeds.
    out = plan_fleet(
        g,
        [FleetRequest("r1", "entrance", "kitchen")],
        s,
        hold_start="10:00",
        hold_end="11:00",
    )
    assert out.all_granted is True


def test_plan_fleet_empty_request_list_returns_empty() -> None:
    g = load_graph(EXAMPLE_YAML)
    s = SharedScheduler()
    out = plan_fleet(
        g,
        [],
        s,
        hold_start="10:00",
        hold_end="11:00",
    )
    assert out.results == []
    assert out.all_granted is False  # empty fleet is not "all granted"
