"""Tests for the occupancy + trajectory fusion pipeline."""

from __future__ import annotations

import pytest

from semantic_toponav.conversion import (
    AnnotationResult,
    annotate_graph_with_trajectories,
    promote_unmapped_transitions,
    prune_low_traversal_edges,
)
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode


def _three_node_chain() -> TopologyGraph:
    """A -- B -- C along the x-axis at x in {0, 1, 2}."""
    g = TopologyGraph()
    for nid, x in [("a", 0.0), ("b", 1.0), ("c", 2.0)]:
        g.add_node(
            TopologyNode(
                id=nid, label=nid, type="waypoint", pose=Pose2D(x=x, y=0.0)
            )
        )
    g.add_edge(TopologyEdge(id="e_ab", source="a", target="b", type="corridor"))
    g.add_edge(TopologyEdge(id="e_bc", source="b", target="c", type="corridor"))
    return g


def _line(p0: tuple[float, float], p1: tuple[float, float], n: int = 21):
    x0, y0 = p0
    x1, y1 = p1
    return [
        (x0 + (x1 - x0) * t / (n - 1), y0 + (y1 - y0) * t / (n - 1)) for t in range(n)
    ]


def test_returns_annotation_result_type() -> None:
    g = _three_node_chain()
    result = annotate_graph_with_trajectories(g, [_line((0.0, 0.0), (2.0, 0.0))])
    assert isinstance(result, AnnotationResult)


def test_linear_trajectory_annotates_edges_and_nodes() -> None:
    g = _three_node_chain()
    traj = _line((0.0, 0.0), (2.0, 0.0), n=21)
    result = annotate_graph_with_trajectories(g, [traj])

    assert g.get_edge("e_ab").properties["traversal_count"] == 1
    assert g.get_edge("e_bc").properties["traversal_count"] == 1
    assert g.get_node("a").properties["visit_count"] == 1
    assert g.get_node("b").properties["visit_count"] == 1
    assert g.get_node("c").properties["visit_count"] == 1
    assert result.nodes_visited == 3
    assert result.transitions_recorded == 2
    assert result.transitions_mapped == 2
    assert result.unmapped_transitions == {}


def test_repeated_trajectories_accumulate_counts() -> None:
    g = _three_node_chain()
    traj = _line((0.0, 0.0), (2.0, 0.0), n=11)
    annotate_graph_with_trajectories(g, [traj, traj, traj])
    assert g.get_edge("e_ab").properties["traversal_count"] == 3
    assert g.get_edge("e_bc").properties["traversal_count"] == 3
    assert g.get_node("b").properties["visit_count"] == 3


def test_consecutive_duplicate_snaps_are_collapsed() -> None:
    g = _three_node_chain()
    # Many points near node "a" should still count as one visit (not many).
    traj = [(0.0, 0.0)] * 30 + _line((0.0, 0.0), (2.0, 0.0), n=11)
    result = annotate_graph_with_trajectories(g, [traj])
    assert g.get_node("a").properties["visit_count"] == 1
    # Only 2 transitions: a->b->c.
    assert result.transitions_recorded == 2


def test_unmapped_transitions_are_reported() -> None:
    # Build a graph where the edge a-c is *missing* but the trajectory
    # jumps straight from a to c.
    g = TopologyGraph()
    g.add_node(
        TopologyNode(id="a", label="a", type="x", pose=Pose2D(x=0.0, y=0.0))
    )
    g.add_node(
        TopologyNode(id="c", label="c", type="x", pose=Pose2D(x=10.0, y=0.0))
    )
    # No edge.
    result = annotate_graph_with_trajectories(
        g, [[(0.0, 0.0), (10.0, 0.0)]]
    )
    assert result.transitions_mapped == 0
    assert result.unmapped_transitions == {("a", "c"): 1}


def test_max_snap_distance_skips_far_points() -> None:
    g = _three_node_chain()
    # Point at (5, 5) is far from any node.
    traj = [(0.0, 0.0), (5.0, 5.0), (2.0, 0.0)]
    result = annotate_graph_with_trajectories(
        g, [traj], max_snap_distance=0.6
    )
    assert result.points_skipped == 1
    assert result.points_snapped == 2
    # Without an intermediate "b" snap, the a->c transition has no edge.
    assert result.unmapped_transitions == {("a", "c"): 1}


def test_empty_trajectory_yields_empty_result() -> None:
    g = _three_node_chain()
    result = annotate_graph_with_trajectories(g, [])
    assert result.points_snapped == 0
    assert result.transitions_recorded == 0
    assert result.nodes_visited == 0


def test_unposed_nodes_are_ignored_during_snapping() -> None:
    g = TopologyGraph()
    g.add_node(
        TopologyNode(id="a", label="a", type="x", pose=Pose2D(x=0.0, y=0.0))
    )
    g.add_node(TopologyNode(id="floating", label="f", type="x", pose=None))
    g.add_node(
        TopologyNode(id="b", label="b", type="x", pose=Pose2D(x=2.0, y=0.0))
    )
    g.add_edge(TopologyEdge(id="e_ab", source="a", target="b", type="corridor"))
    result = annotate_graph_with_trajectories(
        g, [_line((0.0, 0.0), (2.0, 0.0), n=11)]
    )
    assert g.get_edge("e_ab").properties["traversal_count"] == 1
    assert "visit_count" not in g.get_node("floating").properties
    assert result.nodes_visited == 2


def test_graph_with_no_posed_nodes_skips_all_points() -> None:
    g = TopologyGraph()
    g.add_node(TopologyNode(id="a", label="a", type="x", pose=None))
    result = annotate_graph_with_trajectories(g, [[(0.0, 0.0), (1.0, 1.0)]])
    assert result.points_snapped == 0
    assert result.points_skipped == 2


def test_one_way_edge_only_counted_in_forward_direction() -> None:
    g = TopologyGraph()
    g.add_node(
        TopologyNode(id="a", label="a", type="x", pose=Pose2D(x=0.0, y=0.0))
    )
    g.add_node(
        TopologyNode(id="b", label="b", type="x", pose=Pose2D(x=2.0, y=0.0))
    )
    # One-way a -> b only.
    g.add_edge(
        TopologyEdge(
            id="e_ab",
            source="a",
            target="b",
            type="corridor",
            bidirectional=False,
        )
    )
    # Forward traversal: counts.
    annotate_graph_with_trajectories(g, [_line((0.0, 0.0), (2.0, 0.0), n=5)])
    assert g.get_edge("e_ab").properties["traversal_count"] == 1
    # Backward traversal: no edge in that direction, becomes unmapped.
    result = annotate_graph_with_trajectories(
        g, [_line((2.0, 0.0), (0.0, 0.0), n=5)]
    )
    # Still 1: backward traversal did not increment the forward edge.
    assert g.get_edge("e_ab").properties["traversal_count"] == 1
    assert result.unmapped_transitions == {("a", "b"): 1}


def test_existing_properties_are_incremented_not_overwritten() -> None:
    g = _three_node_chain()
    g.get_edge("e_ab").properties["traversal_count"] = 5
    g.get_node("a").properties["visit_count"] = 7
    annotate_graph_with_trajectories(g, [_line((0.0, 0.0), (1.0, 0.0), n=5)])
    assert g.get_edge("e_ab").properties["traversal_count"] == 6
    assert g.get_node("a").properties["visit_count"] == 8


def test_custom_property_keys() -> None:
    g = _three_node_chain()
    annotate_graph_with_trajectories(
        g,
        [_line((0.0, 0.0), (2.0, 0.0), n=11)],
        visit_count_key="seen",
        traversal_count_key="used",
    )
    assert g.get_node("a").properties["seen"] == 1
    assert g.get_edge("e_ab").properties["used"] == 1
    assert "visit_count" not in g.get_node("a").properties
    assert "traversal_count" not in g.get_edge("e_ab").properties


# --------------------------- prune_low_traversal_edges ---------------------------


def test_prune_removes_zero_traversal_edges() -> None:
    g = _three_node_chain()
    g.get_edge("e_ab").properties["traversal_count"] = 3
    # e_bc has no traversal_count, treated as 0.
    removed = prune_low_traversal_edges(g, min_traversals=1)
    assert removed == ["e_bc"]
    assert g.has_edge("e_ab")
    assert not g.has_edge("e_bc")


def test_prune_threshold_above_one() -> None:
    g = _three_node_chain()
    g.get_edge("e_ab").properties["traversal_count"] = 5
    g.get_edge("e_bc").properties["traversal_count"] = 2
    removed = prune_low_traversal_edges(g, min_traversals=3)
    assert removed == ["e_bc"]
    assert g.has_edge("e_ab")


def test_prune_respects_keep_edge_types() -> None:
    g = TopologyGraph()
    for nid in "ab":
        g.add_node(
            TopologyNode(
                id=nid, label=nid, type="x", pose=Pose2D(x=0.0, y=0.0)
            )
        )
    # Edge "stairs_link" has count=0 but is in the protected set.
    g.add_edge(
        TopologyEdge(
            id="stairs_link",
            source="a",
            target="b",
            type="stairs_up",
        )
    )
    removed = prune_low_traversal_edges(
        g, min_traversals=1, keep_edge_types=["stairs_up"]
    )
    assert removed == []
    assert g.has_edge("stairs_link")


def test_prune_custom_property_key() -> None:
    g = _three_node_chain()
    g.get_edge("e_ab").properties["used"] = 5
    # e_bc has no "used" -> 0.
    removed = prune_low_traversal_edges(
        g, min_traversals=1, traversal_count_key="used"
    )
    assert removed == ["e_bc"]


# --------------------------- promote_unmapped_transitions ---------------------------


def test_promote_creates_edge_for_hot_pair() -> None:
    g = TopologyGraph()
    for nid, x in [("a", 0.0), ("c", 3.0)]:
        g.add_node(
            TopologyNode(
                id=nid, label=nid, type="x", pose=Pose2D(x=x, y=4.0)
            )
        )
    unmapped = {("a", "c"): 5}
    added = promote_unmapped_transitions(g, unmapped, min_count=2)
    assert added == ["promoted_a__c"]
    edge = g.get_edge("promoted_a__c")
    # Euclidean: sqrt(9 + 0) = 3
    assert edge.cost == pytest.approx(3.0)
    assert edge.properties["traversal_count"] == 5
    assert edge.bidirectional is True


def test_promote_skips_pairs_below_min_count() -> None:
    g = TopologyGraph()
    for nid in "ab":
        g.add_node(
            TopologyNode(
                id=nid, label=nid, type="x", pose=Pose2D(x=0.0, y=0.0)
            )
        )
    added = promote_unmapped_transitions(g, {("a", "b"): 1}, min_count=2)
    assert added == []
    assert not any(e.type == "promoted" for e in g.edges())


def test_promote_skips_pairs_with_missing_nodes() -> None:
    g = TopologyGraph()
    g.add_node(TopologyNode(id="a", label="a", type="x"))
    # b is missing.
    added = promote_unmapped_transitions(g, {("a", "b"): 5}, min_count=1)
    assert added == []


def test_promote_skips_when_edge_already_exists() -> None:
    g = _three_node_chain()
    # e_ab already exists; ("a", "b") should not yield a new edge.
    added = promote_unmapped_transitions(g, {("a", "b"): 99}, min_count=1)
    assert added == []
    assert len([e for e in g.edges() if e.type == "promoted"]) == 0


def test_promote_handles_missing_poses_with_unit_cost() -> None:
    g = TopologyGraph()
    g.add_node(TopologyNode(id="a", label="a", type="x", pose=None))
    g.add_node(TopologyNode(id="b", label="b", type="x", pose=None))
    added = promote_unmapped_transitions(g, {("a", "b"): 3}, min_count=1)
    assert added == ["promoted_a__b"]
    assert g.get_edge("promoted_a__b").cost == 1.0


def test_promote_round_trips_with_annotation() -> None:
    # End-to-end: build a graph that's missing one edge, run annotation,
    # then promote the unmapped transition, then re-annotate -> mapped.
    g = TopologyGraph()
    for nid, x in [("a", 0.0), ("c", 3.0)]:
        g.add_node(
            TopologyNode(
                id=nid, label=nid, type="x", pose=Pose2D(x=x, y=0.0)
            )
        )
    traj = _line((0.0, 0.0), (3.0, 0.0), n=11)
    result = annotate_graph_with_trajectories(g, [traj, traj])
    assert result.unmapped_transitions == {("a", "c"): 2}
    promote_unmapped_transitions(g, result.unmapped_transitions, min_count=2)
    # Now re-annotate: the transition should map.
    result2 = annotate_graph_with_trajectories(g, [traj])
    assert result2.transitions_mapped == 1
    assert result2.unmapped_transitions == {}
