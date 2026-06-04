"""Tests for image-grounded topological navigation.

Like the visual-localization suite, these run entirely on the
deterministic :class:`HashingBackend`: identical input bytes map to an
identical unit vector, so a frame stamped on node *k* localizes back to
node *k* at cosine ~1.0. That lets us drive a whole route-following loop
with plain byte "frames" and no torch / CLIP in the loop.
"""

from __future__ import annotations

import pytest

from semantic_toponav.encoders.backends import HashingBackend
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode
from semantic_toponav.planner.errors import PlanningError
from semantic_toponav.query import (
    NoMatchError,
    RouteProgress,
    VisualRoute,
    VisualRouteFollower,
    plan_visual_route,
)

# A 4-node chain:  bay -- hall -- lab -- dock
FRAMES = {
    "bay": b"frame:bay:loading-dock-doors",
    "hall": b"frame:hall:long-corridor",
    "lab": b"frame:lab:benches-and-screens",
    "dock": b"frame:dock:charging-station",
}
# 'roof' is a place off the planned route — stamped so an unseen frame
# localizes to it, giving the suite a genuine off-route fix to test.
FRAME_ROOF = b"frame:rooftop:open-sky-and-vents"
CHAIN = ["bay", "hall", "lab", "dock"]


def _chain_graph(backend) -> TopologyGraph:
    g = TopologyGraph()
    xs = {"bay": 0.0, "hall": 1.0, "lab": 2.0, "dock": 3.0, "roof": 1.0}
    for key in CHAIN:
        g.add_node(
            TopologyNode(
                id=key,
                label=key.title(),
                type="room",
                pose=Pose2D(xs[key], 0.0),
                properties={"embedding": backend.embed_image(FRAMES[key])},
            )
        )
    # An off-route node hanging off the hallway.
    g.add_node(
        TopologyNode(
            id="roof",
            label="Roof",
            type="room",
            pose=Pose2D(xs["roof"], 1.0),
            properties={"embedding": backend.embed_image(FRAME_ROOF)},
        )
    )
    for a, b in zip(CHAIN, CHAIN[1:], strict=False):
        g.add_edge(
            TopologyEdge(id=f"{a}_{b}", source=a, target=b, type="traversable")
        )
    g.add_edge(
        TopologyEdge(id="hall_roof", source="hall", target="roof", type="traversable")
    )
    return g


# --- plan_visual_route -------------------------------------------------


def test_plan_visual_route_grounds_start_and_plans() -> None:
    backend = HashingBackend(dim=64)
    g = _chain_graph(backend)
    vr = plan_visual_route(g, FRAMES["bay"], "dock", backend)
    assert isinstance(vr, VisualRoute)
    assert vr.start.node.id == "bay"
    assert vr.route == ["bay", "hall", "lab", "dock"]
    assert vr.goal == "dock"
    # Waypoints mirror the route node-for-node.
    assert [w.node_id for w in vr.waypoints] == vr.route


def test_plan_visual_route_start_in_middle() -> None:
    backend = HashingBackend(dim=64)
    g = _chain_graph(backend)
    # Grounding the 'lab' frame should start the plan from lab, not bay.
    vr = plan_visual_route(g, FRAMES["lab"], "dock", backend)
    assert vr.route == ["lab", "dock"]


def test_plan_visual_route_unknown_goal_raises() -> None:
    backend = HashingBackend(dim=64)
    g = _chain_graph(backend)
    with pytest.raises(PlanningError):
        plan_visual_route(g, FRAMES["bay"], "no_such_node", backend)


def test_plan_visual_route_no_embeddings_raises() -> None:
    backend = HashingBackend(dim=64)
    g = TopologyGraph()
    g.add_node(TopologyNode(id="x", label="X", type="room", pose=Pose2D(0, 0)))
    with pytest.raises(NoMatchError):
        plan_visual_route(g, FRAME_ROOF, "x", backend)


# --- VisualRouteFollower ----------------------------------------------


def test_follower_advances_along_route() -> None:
    backend = HashingBackend(dim=64)
    g = _chain_graph(backend)
    follower = VisualRouteFollower(g, CHAIN, backend)
    assert follower.index == 0
    assert not follower.reached_goal

    progresses = [follower.update(FRAMES[k]) for k in CHAIN]
    assert [p.index for p in progresses] == [0, 1, 2, 3]
    assert all(isinstance(p, RouteProgress) for p in progresses)
    # Each on-route hit after the first advances the index.
    assert [p.advanced for p in progresses] == [False, True, True, True]
    assert all(p.on_route for p in progresses)
    assert progresses[-1].reached_goal
    assert follower.reached_goal


def test_follower_progress_is_monotonic() -> None:
    backend = HashingBackend(dim=64)
    g = _chain_graph(backend)
    follower = VisualRouteFollower(g, CHAIN, backend)
    follower.update(FRAMES["bay"])
    follower.update(FRAMES["lab"])  # jump to index 2
    assert follower.index == 2
    # A glance back at the hallway must not rewind progress.
    back = follower.update(FRAMES["hall"])
    assert back.index == 2
    assert back.advanced is False
    assert back.on_route is True
    assert back.remaining == ["dock"]


def test_follower_off_route_frame_holds_index() -> None:
    backend = HashingBackend(dim=64)
    g = _chain_graph(backend)
    follower = VisualRouteFollower(g, CHAIN, backend)
    follower.update(FRAMES["hall"])  # index 1
    off = follower.update(FRAME_ROOF)  # localizes to the off-route 'roof'
    assert off.localized.node.id == "roof"
    assert off.on_route is False
    assert off.advanced is False
    assert off.index == 1


def test_follower_min_score_rejects_weak_fix() -> None:
    backend = HashingBackend(dim=64)
    g = _chain_graph(backend)
    # A floor above the cosine ceiling (1.0) rejects even a perfect
    # on-route match, so progress can never advance.
    follower = VisualRouteFollower(g, CHAIN, backend, min_score=1.01)
    weak = follower.update(FRAMES["hall"])
    assert weak.on_route is False
    assert weak.index == 0


def test_follower_allow_skip_false_steps_one_at_a_time() -> None:
    backend = HashingBackend(dim=64)
    g = _chain_graph(backend)
    follower = VisualRouteFollower(g, CHAIN, backend, allow_skip=False)
    # Jumping straight to 'lab' (two hops) must not leapfrog the hallway.
    jump = follower.update(FRAMES["lab"])
    assert jump.index == 0
    assert jump.advanced is False
    # Stepping through confirms each waypoint.
    assert follower.update(FRAMES["hall"]).index == 1
    assert follower.update(FRAMES["lab"]).index == 2


def test_follower_rejects_empty_route() -> None:
    backend = HashingBackend(dim=64)
    g = _chain_graph(backend)
    with pytest.raises(ValueError):
        VisualRouteFollower(g, [], backend)


def test_follower_rejects_bad_start_index() -> None:
    backend = HashingBackend(dim=64)
    g = _chain_graph(backend)
    with pytest.raises(ValueError):
        VisualRouteFollower(g, CHAIN, backend, start_index=99)
