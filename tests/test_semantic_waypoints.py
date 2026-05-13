"""Tests for path -> SemanticWaypoint conversion."""

from __future__ import annotations

from pathlib import Path

from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode
from semantic_toponav.waypoint.semantic_waypoint import (
    SemanticWaypoint,
    path_to_semantic_waypoints,
)

EXAMPLE_YAML = Path(__file__).resolve().parents[1] / "examples" / "indoor_office.yaml"


def test_empty_path_yields_empty() -> None:
    g = TopologyGraph()
    assert path_to_semantic_waypoints(g, []) == []


def test_actions_for_known_types() -> None:
    g = load_graph(EXAMPLE_YAML)
    path = ["entrance", "corridor_main", "lobby_intersection", "meeting_room"]
    wps = path_to_semantic_waypoints(g, path)
    assert [w.action for w in wps] == ["start", "proceed_through", "navigate", "arrive"]
    assert wps[0].instruction.startswith("Start at")
    assert wps[-1].instruction.startswith("Arrive at")


def test_elevator_and_stairs_actions() -> None:
    g = load_graph(EXAMPLE_YAML)
    path = ["entrance", "corridor_main", "elevator_1f", "elevator_2f", "corridor_2f", "office_2f"]
    wps = path_to_semantic_waypoints(g, path)
    actions = [w.action for w in wps]
    assert "take_elevator" in actions
    # office_2f is the goal so its action is "arrive", not "enter"
    assert wps[-1].action == "arrive"


def test_waypoint_preserves_pose_and_label() -> None:
    g = TopologyGraph()
    g.add_node(
        TopologyNode(id="a", label="Alpha", type="room", pose=Pose2D(1.5, 2.5, 0.1, "map"))
    )
    g.add_node(TopologyNode(id="b", label="Beta", type="room"))
    g.add_edge(TopologyEdge(id="ab", source="a", target="b", type="traversable"))
    wps = path_to_semantic_waypoints(g, ["a", "b"])
    assert isinstance(wps[0], SemanticWaypoint)
    assert wps[0].pose is not None
    assert wps[0].pose.x == 1.5
    assert wps[0].node_label == "Alpha"
    assert wps[1].pose is None


def test_determinism() -> None:
    """Same input must produce the same waypoint list."""
    g = load_graph(EXAMPLE_YAML)
    path = ["entrance", "corridor_main", "lobby_intersection", "meeting_room"]
    a = [w.to_dict() for w in path_to_semantic_waypoints(g, path)]
    b = [w.to_dict() for w in path_to_semantic_waypoints(g, path)]
    assert a == b
