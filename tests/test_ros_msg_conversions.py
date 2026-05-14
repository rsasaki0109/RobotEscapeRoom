"""Tests for the ROS2 message-conversion helpers.

These tests exercise the *pure-Python* field-dict layer of
``semantic_toponav_ros.msg_conversions`` only. The `_to_msg` wrappers do a
mechanical copy onto generated message classes and require a sourced ROS2
environment; they are out of scope here.
"""

from __future__ import annotations

import json
from pathlib import Path

from semantic_toponav_ros.msg_conversions import (
    semantic_waypoint_array_to_fields,
    semantic_waypoint_from_fields,
    semantic_waypoint_to_fields,
    topology_edge_from_fields,
    topology_edge_to_fields,
    topology_graph_from_fields,
    topology_graph_to_fields,
    topology_node_from_fields,
    topology_node_to_fields,
)

from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode
from semantic_toponav.waypoint.semantic_waypoint import (
    SemanticWaypoint,
    path_to_semantic_waypoints,
)

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"


# ----------------------------- SemanticWaypoint -----------------------------


def test_semantic_waypoint_round_trip_with_pose() -> None:
    wp = SemanticWaypoint(
        node_id="lobby_1f",
        node_label="Lobby (1F)",
        node_type="room",
        action="enter",
        instruction="Enter Lobby (1F)",
        pose=Pose2D(x=1.5, y=-2.0, yaw=0.75, frame_id="map"),
        properties={"floor": 1, "capacity": 30},
    )
    fields = semantic_waypoint_to_fields(wp)

    assert fields["node_id"] == "lobby_1f"
    assert fields["has_pose"] is True
    assert fields["frame_id"] == "map"
    assert fields["pose"] == {"x": 1.5, "y": -2.0, "theta": 0.75}
    assert json.loads(fields["properties_json"]) == {"floor": 1, "capacity": 30}

    restored = semantic_waypoint_from_fields(fields)
    assert restored == wp


def test_semantic_waypoint_round_trip_without_pose() -> None:
    wp = SemanticWaypoint(
        node_id="virtual_anchor",
        node_label="anchor",
        node_type="intersection",
        action="navigate",
        instruction="Navigate to anchor",
        pose=None,
        properties={},
    )
    fields = semantic_waypoint_to_fields(wp)
    assert fields["has_pose"] is False
    assert fields["frame_id"] == ""
    assert fields["pose"] == {"x": 0.0, "y": 0.0, "theta": 0.0}
    assert fields["properties_json"] == ""

    restored = semantic_waypoint_from_fields(fields)
    assert restored == wp


def test_semantic_waypoint_array_layout() -> None:
    wps = [
        SemanticWaypoint(
            node_id="a",
            node_label="A",
            node_type="entrance",
            action="start",
            instruction="Start at A",
            pose=Pose2D(x=0.0, y=0.0),
        ),
        SemanticWaypoint(
            node_id="b",
            node_label="B",
            node_type="room",
            action="arrive",
            instruction="Arrive at B",
            pose=Pose2D(x=2.0, y=0.0),
        ),
    ]
    fields = semantic_waypoint_array_to_fields(["a", "b"], wps, frame_id="map")
    assert fields["header"] == {"frame_id": "map"}
    assert fields["path"] == ["a", "b"]
    assert len(fields["waypoints"]) == 2
    assert fields["waypoints"][0]["action"] == "start"
    assert fields["waypoints"][1]["action"] == "arrive"


# ------------------------------ TopologyNode --------------------------------


def test_topology_node_round_trip_with_properties() -> None:
    node = TopologyNode(
        id="elevator_1f",
        label="Elevator (1F)",
        type="elevator",
        pose=Pose2D(x=3.0, y=4.0, yaw=1.57, frame_id="map"),
        properties={"capacity": 8, "tags": ["accessible"]},
    )
    fields = topology_node_to_fields(node)
    assert fields["id"] == "elevator_1f"
    assert fields["has_pose"] is True
    assert fields["pose"] == {"x": 3.0, "y": 4.0, "theta": 1.57}
    assert json.loads(fields["properties_json"]) == {
        "capacity": 8,
        "tags": ["accessible"],
    }

    restored = topology_node_from_fields(fields)
    assert restored == node


def test_topology_node_round_trip_no_pose() -> None:
    node = TopologyNode(id="x", label="X", type="room")
    fields = topology_node_to_fields(node)
    restored = topology_node_from_fields(fields)
    assert restored == node


# ------------------------------ TopologyEdge --------------------------------


def test_topology_edge_round_trip() -> None:
    edge = TopologyEdge(
        id="e1",
        source="a",
        target="b",
        type="corridor",
        cost=2.5,
        bidirectional=False,
        properties={"width_m": 1.2},
    )
    fields = topology_edge_to_fields(edge)
    assert fields == {
        "id": "e1",
        "source": "a",
        "target": "b",
        "type": "corridor",
        "cost": 2.5,
        "bidirectional": False,
        "properties_json": json.dumps({"width_m": 1.2}, sort_keys=True),
    }
    restored = topology_edge_from_fields(fields)
    assert restored == edge


# ------------------------------ TopologyGraph -------------------------------


def test_topology_graph_round_trip_minimal() -> None:
    g = TopologyGraph()
    g.add_node(TopologyNode(id="a", label="A", type="room"))
    g.add_node(TopologyNode(id="b", label="B", type="room", pose=Pose2D(1.0, 2.0)))
    g.add_edge(
        TopologyEdge(id="e1", source="a", target="b", type="corridor", cost=1.0)
    )

    fields = topology_graph_to_fields(g, frame_id="map")
    assert fields["header"] == {"frame_id": "map"}
    assert {n["id"] for n in fields["nodes"]} == {"a", "b"}
    assert [e["id"] for e in fields["edges"]] == ["e1"]

    restored = topology_graph_from_fields(fields)
    assert set(restored.node_ids()) == {"a", "b"}
    assert restored.edge_ids() == ["e1"]
    # Pose survives the round trip.
    assert restored.get_node("b").pose == Pose2D(1.0, 2.0)


def test_topology_graph_round_trip_from_example_yaml() -> None:
    graph = load_graph(EXAMPLES_DIR / "multi_floor_office.yaml")
    fields = topology_graph_to_fields(graph)
    restored = topology_graph_from_fields(fields)

    assert set(restored.node_ids()) == set(graph.node_ids())
    assert set(restored.edge_ids()) == set(graph.edge_ids())
    # Spot-check an edge to make sure cost / bidirectional / properties round-trip.
    for eid in graph.edge_ids():
        a = graph.get_edge(eid)
        b = restored.get_edge(eid)
        assert a == b


# --------------------- semantic_waypoint integration ------------------------


def test_path_to_waypoints_round_trip_through_fields() -> None:
    graph = load_graph(EXAMPLES_DIR / "multi_floor_office.yaml")
    path = ["entrance", "corridor_1f", "lobby_1f"]
    wps = path_to_semantic_waypoints(graph, path)
    fields = semantic_waypoint_array_to_fields(path, wps)
    assert fields["path"] == path
    restored = [semantic_waypoint_from_fields(f) for f in fields["waypoints"]]
    assert restored == wps


# --------------------- graph publishing payload shape -----------------------


def test_graph_publish_payload_round_trip_from_example_yaml() -> None:
    """The exact field dict that ``graph_loader_node`` would publish should
    round-trip back to a graph that matches the loaded one.

    This is the unit-test cousin of running the node: we don't need rclpy to
    confirm the wire layout it would emit is structurally lossless.
    """
    graph = load_graph(EXAMPLES_DIR / "multi_floor_office.yaml")
    fields = topology_graph_to_fields(graph, frame_id="map")

    assert fields["header"] == {"frame_id": "map"}
    assert len(fields["nodes"]) == len(graph.node_ids())
    assert len(fields["edges"]) == len(graph.edge_ids())

    restored = topology_graph_from_fields(fields)
    assert set(restored.node_ids()) == set(graph.node_ids())
    assert set(restored.edge_ids()) == set(graph.edge_ids())
    for nid in graph.node_ids():
        assert restored.get_node(nid) == graph.get_node(nid)
