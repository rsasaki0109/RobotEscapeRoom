"""Unit tests for :func:`semantic_toponav.graph.compact_graph`."""

from __future__ import annotations

import math

import pytest

from semantic_toponav.graph import (
    CompactionResult,
    Pose2D,
    TopologyEdge,
    TopologyGraph,
    TopologyNode,
    compact_graph,
)


def _node(node_id: str, x: float, y: float) -> TopologyNode:
    return TopologyNode(
        id=node_id,
        label=node_id,
        type="room",
        pose=Pose2D(x=x, y=y),
    )


def _edge(
    eid: str,
    src: str,
    tgt: str,
    *,
    cost: float = 1.0,
    bidirectional: bool = True,
    edge_type: str = "corridor",
) -> TopologyEdge:
    return TopologyEdge(
        id=eid,
        source=src,
        target=tgt,
        type=edge_type,
        cost=cost,
        bidirectional=bidirectional,
    )


# --------------------------- parallel-edge collapse ---------------------------


def test_collapse_dedups_same_endpoint_bidirectional_edges() -> None:
    g = TopologyGraph()
    g.add_node(_node("a", 0.0, 0.0))
    g.add_node(_node("b", 1.0, 0.0))
    g.add_edge(_edge("e1", "a", "b", cost=1.0))
    g.add_edge(_edge("e2", "a", "b", cost=1.05))

    result = compact_graph(g)

    # Default tolerance=inf, default keep_strategy=shortest → e1 wins.
    assert isinstance(result, CompactionResult)
    assert result.collapsed_edges == {"e2": "e1"}
    assert g.edge_ids() == ["e1"]


def test_collapse_treats_reverse_bidirectional_as_parallel() -> None:
    g = TopologyGraph()
    g.add_node(_node("a", 0.0, 0.0))
    g.add_node(_node("b", 1.0, 0.0))
    g.add_edge(_edge("ab", "a", "b", cost=1.0))
    g.add_edge(_edge("ba", "b", "a", cost=1.2))

    compact_graph(g)

    assert g.edge_ids() == ["ab"]


def test_collapse_keeps_distinct_directed_pair() -> None:
    g = TopologyGraph()
    g.add_node(_node("a", 0.0, 0.0))
    g.add_node(_node("b", 1.0, 0.0))
    g.add_edge(_edge("ab", "a", "b", cost=1.0, bidirectional=False))
    g.add_edge(_edge("ba", "b", "a", cost=1.0, bidirectional=False))

    compact_graph(g)

    # Directed pair represents two distinct traversals → keep both.
    assert set(g.edge_ids()) == {"ab", "ba"}


def test_collapse_respects_cost_tolerance() -> None:
    g = TopologyGraph()
    g.add_node(_node("a", 0.0, 0.0))
    g.add_node(_node("b", 1.0, 0.0))
    g.add_edge(_edge("short", "a", "b", cost=1.0))
    g.add_edge(_edge("long", "a", "b", cost=3.0))

    # Tolerance 1.0 < span 2.0 → keep both as genuinely-different paths.
    result = compact_graph(g, edge_cost_tolerance=1.0)
    assert result.collapsed_edges == {}
    assert set(g.edge_ids()) == {"short", "long"}


def test_collapse_keep_strategy_longest() -> None:
    g = TopologyGraph()
    g.add_node(_node("a", 0.0, 0.0))
    g.add_node(_node("b", 1.0, 0.0))
    g.add_edge(_edge("short", "a", "b", cost=1.0))
    g.add_edge(_edge("long", "a", "b", cost=3.0))

    compact_graph(g, edge_cost_tolerance=math.inf, keep_strategy="longest")

    assert g.edge_ids() == ["long"]


def test_collapse_keep_strategy_first_uses_insertion_order() -> None:
    g = TopologyGraph()
    g.add_node(_node("a", 0.0, 0.0))
    g.add_node(_node("b", 1.0, 0.0))
    g.add_edge(_edge("second", "a", "b", cost=10.0))
    g.add_edge(_edge("first_inserted_after", "a", "b", cost=1.0))

    compact_graph(g, keep_strategy="first")

    assert g.edge_ids() == ["second"]


def test_unknown_keep_strategy_raises() -> None:
    g = TopologyGraph()
    g.add_node(_node("a", 0.0, 0.0))
    g.add_node(_node("b", 1.0, 0.0))
    g.add_edge(_edge("e", "a", "b"))
    with pytest.raises(ValueError, match="keep_strategy"):
        compact_graph(g, keep_strategy="nope")


def test_negative_tolerance_rejected() -> None:
    g = TopologyGraph()
    with pytest.raises(ValueError, match="endpoint_tolerance"):
        compact_graph(g, endpoint_tolerance=-0.5)
    with pytest.raises(ValueError, match="edge_cost_tolerance"):
        compact_graph(g, edge_cost_tolerance=-0.1)


# --------------------------- node merging ---------------------------


def test_endpoint_tolerance_merges_close_nodes() -> None:
    g = TopologyGraph()
    g.add_node(_node("a", 0.0, 0.0))
    g.add_node(_node("a_dup", 0.05, 0.0))  # within tolerance
    g.add_node(_node("far", 5.0, 0.0))
    g.add_edge(_edge("e_dup_far", "a_dup", "far", cost=4.95))

    result = compact_graph(g, endpoint_tolerance=0.1)

    assert "a_dup" in result.merged_nodes
    assert result.merged_nodes["a_dup"] == "a"
    assert not g.has_node("a_dup")
    assert g.has_node("a")
    assert g.has_node("far")
    edge = g.get_edge("e_dup_far")
    assert edge.source == "a"  # rerouted
    assert edge.target == "far"


def test_node_merge_drops_self_loops() -> None:
    g = TopologyGraph()
    g.add_node(_node("a", 0.0, 0.0))
    g.add_node(_node("a_dup", 0.02, 0.0))
    g.add_edge(_edge("inner", "a", "a_dup", cost=0.02))

    result = compact_graph(g, endpoint_tolerance=0.1)

    assert result.dropped_self_loops == ["inner"]
    assert "inner" not in g.edge_ids()


def test_node_merge_centroids_pose() -> None:
    g = TopologyGraph()
    g.add_node(_node("a", 0.0, 0.0))
    g.add_node(_node("b", 0.4, 0.0))
    g.add_node(_node("c", 0.0, 0.4))
    # Far node so merge cluster stays {a, b, c}.
    g.add_node(_node("far", 10.0, 10.0))

    compact_graph(g, endpoint_tolerance=0.6)

    # Representative is "a" (smallest id); pose averages over the cluster.
    rep = g.get_node("a")
    assert rep.pose is not None
    assert rep.pose.x == pytest.approx((0.0 + 0.4 + 0.0) / 3.0)
    assert rep.pose.y == pytest.approx((0.0 + 0.0 + 0.4) / 3.0)


def test_unposed_nodes_skip_distance_merge() -> None:
    g = TopologyGraph()
    g.add_node(_node("a", 0.0, 0.0))
    # No pose → cannot be distance-merged even if you'd expect it.
    g.add_node(
        TopologyNode(id="ghost", label="g", type="room", pose=None)
    )
    g.add_edge(_edge("e", "a", "ghost"))

    result = compact_graph(g, endpoint_tolerance=10.0)

    assert result.merged_nodes == {}
    assert g.has_node("ghost")


def test_merge_then_collapse_in_one_pass() -> None:
    """Node merge can expose new same-endpoint duplicates that then collapse."""
    g = TopologyGraph()
    g.add_node(_node("a", 0.0, 0.0))
    g.add_node(_node("a_dup", 0.02, 0.0))
    g.add_node(_node("b", 1.0, 0.0))
    g.add_edge(_edge("p1", "a", "b", cost=1.0))
    g.add_edge(_edge("p2", "a_dup", "b", cost=1.0))

    result = compact_graph(g, endpoint_tolerance=0.1)

    assert "a_dup" in result.merged_nodes
    # After rerouting, p1 and p2 both connect a↔b → one of them gets collapsed.
    assert len(result.collapsed_edges) == 1
    assert g.edge_ids() == ["p1"]


def test_no_op_when_graph_is_already_clean() -> None:
    g = TopologyGraph()
    g.add_node(_node("a", 0.0, 0.0))
    g.add_node(_node("b", 2.0, 0.0))
    g.add_edge(_edge("ab", "a", "b", cost=2.0))

    result = compact_graph(g, endpoint_tolerance=0.5)

    assert result == CompactionResult()
    assert set(g.node_ids()) == {"a", "b"}
    assert g.edge_ids() == ["ab"]


def test_compaction_result_is_dataclass_instance() -> None:
    g = TopologyGraph()
    result = compact_graph(g)
    assert isinstance(result, CompactionResult)
    assert result.merged_nodes == {}
    assert result.dropped_self_loops == []
    assert result.collapsed_edges == {}
