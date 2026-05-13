"""Tests for the fluent GraphBuilder."""

from __future__ import annotations

import pytest

from semantic_toponav.graph import GraphBuilder, Pose2D, TopologyGraph
from semantic_toponav.graph.types import GraphValidationError
from semantic_toponav.planner import plan_astar

# ----------------------------- basic chaining -----------------------------


def test_node_and_edge_return_self() -> None:
    b = GraphBuilder()
    assert b.node("a", type="room") is b
    assert b.edge("a", "a", type="self_loop") is b


def test_build_returns_topology_graph() -> None:
    g = GraphBuilder().build()
    assert isinstance(g, TopologyGraph)
    assert g.node_ids() == []


def test_build_round_trip_through_planner() -> None:
    g = (
        GraphBuilder()
        .node("a", type="entrance", x=0, y=0)
        .node("b", type="corridor", x=1, y=0)
        .node("c", type="room", x=2, y=0)
        .connect("a", "b", "c")
        .build()
    )
    assert plan_astar(g, "a", "c") == ["a", "b", "c"]


# ----------------------------- pose handling -----------------------------


def test_x_y_create_pose() -> None:
    g = GraphBuilder().node("a", type="room", x=1.5, y=2.5).build()
    pose = g.get_node("a").pose
    assert pose is not None
    assert pose.x == 1.5
    assert pose.y == 2.5
    assert pose.yaw == 0.0
    assert pose.frame_id == "map"


def test_x_y_yaw_frame_id() -> None:
    g = GraphBuilder().node(
        "a", type="room", x=1, y=2, yaw=0.5, frame_id="odom"
    ).build()
    pose = g.get_node("a").pose
    assert pose.yaw == 0.5
    assert pose.frame_id == "odom"


def test_pose_object_accepted() -> None:
    g = GraphBuilder().node(
        "a", type="room", pose=Pose2D(1.0, 2.0, 0.1, "map")
    ).build()
    assert g.get_node("a").pose.x == 1.0


def test_passing_pose_and_xy_raises() -> None:
    with pytest.raises(ValueError):
        GraphBuilder().node("a", type="room", pose=Pose2D(0, 0), x=1, y=2)


def test_partial_xy_raises() -> None:
    with pytest.raises(ValueError):
        GraphBuilder().node("a", type="room", x=1)


def test_node_without_pose_has_none() -> None:
    g = GraphBuilder().node("a", type="room").build()
    assert g.get_node("a").pose is None


# ----------------------------- defaults -----------------------------


def test_label_defaults_to_id() -> None:
    g = GraphBuilder().node("entrance", type="entrance").build()
    assert g.get_node("entrance").label == "entrance"


def test_label_override() -> None:
    g = GraphBuilder().node("e", type="entrance", label="Front Door").build()
    assert g.get_node("e").label == "Front Door"


def test_edge_id_defaults_to_pair() -> None:
    g = (
        GraphBuilder()
        .node("a", type="room")
        .node("b", type="room")
        .edge("a", "b", type="traversable")
        .build()
    )
    assert g.has_edge("a__b")


def test_edge_id_override() -> None:
    g = (
        GraphBuilder()
        .node("a", type="room")
        .node("b", type="room")
        .edge("a", "b", type="traversable", id="custom_id")
        .build()
    )
    assert g.has_edge("custom_id")
    assert not g.has_edge("a__b")


def test_edge_one_way() -> None:
    g = (
        GraphBuilder()
        .node("a", type="room")
        .node("b", type="room")
        .edge("a", "b", type="one_way", bidirectional=False)
        .build()
    )
    edge = g.get_edge("a__b")
    assert edge.bidirectional is False


# ----------------------------- properties -----------------------------


def test_node_properties_attached() -> None:
    g = (
        GraphBuilder()
        .node("a", type="room", properties={"floor": 2, "tag": "lab"})
        .build()
    )
    assert g.get_node("a").properties == {"floor": 2, "tag": "lab"}


def test_edge_properties_attached() -> None:
    g = (
        GraphBuilder()
        .node("a", type="room")
        .node("b", type="room")
        .edge("a", "b", type="elevator_connection", properties={"floor_delta": 1})
        .build()
    )
    assert g.get_edge("a__b").properties == {"floor_delta": 1}


# ----------------------------- connect -----------------------------


def test_connect_chains_edges() -> None:
    g = (
        GraphBuilder()
        .node("a", type="room")
        .node("b", type="corridor")
        .node("c", type="corridor")
        .node("d", type="room")
        .connect("a", "b", "c", "d")
        .build()
    )
    assert {e.id for e in g.edges()} == {"a__b", "b__c", "c__d"}


def test_connect_requires_two_nodes() -> None:
    b = GraphBuilder().node("a", type="room")
    with pytest.raises(ValueError):
        b.connect("a")


def test_connect_uses_supplied_type() -> None:
    g = (
        GraphBuilder()
        .node("a", type="room")
        .node("b", type="room")
        .connect("a", "b", type="elevator_connection", cost=3.0)
        .build()
    )
    edge = g.get_edge("a__b")
    assert edge.type == "elevator_connection"
    assert edge.cost == 3.0


# ----------------------------- error surfaces -----------------------------


def test_duplicate_node_id_raises() -> None:
    b = GraphBuilder().node("a", type="room")
    with pytest.raises(GraphValidationError):
        b.node("a", type="corridor")


def test_unknown_edge_endpoint_raises() -> None:
    b = GraphBuilder().node("a", type="room")
    with pytest.raises(GraphValidationError):
        b.edge("a", "zz", type="traversable")


# ----------------------------- from_graph -----------------------------


def test_from_graph_extends_existing_graph() -> None:
    g = TopologyGraph()
    GraphBuilder.from_graph(g).node("a", type="room").build()
    assert g.has_node("a")


def test_build_is_idempotent() -> None:
    b = GraphBuilder().node("a", type="room")
    g1 = b.build()
    g2 = b.build()
    assert g1 is g2
