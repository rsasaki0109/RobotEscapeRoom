"""Tests for the edge-aware path-narration helpers."""

from __future__ import annotations

from pathlib import Path

from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode
from semantic_toponav.waypoint.describe import (
    PathStep,
    describe_path,
    path_to_steps,
)

EXAMPLE_YAML = Path(__file__).resolve().parents[1] / "examples" / "indoor_office.yaml"


def _tiny_graph() -> TopologyGraph:
    g = TopologyGraph()
    g.add_node(TopologyNode(id="a", label="Alpha", type="room", pose=Pose2D(0.0, 0.0)))
    g.add_node(TopologyNode(id="b", label="Beta", type="room", pose=Pose2D(1.0, 0.0)))
    g.add_edge(TopologyEdge(id="ab", source="a", target="b", type="traversable"))
    return g


def test_empty_path_yields_empty() -> None:
    g = TopologyGraph()
    assert describe_path(g, []) == []
    assert path_to_steps(g, []) == []


def test_single_node_path_only_emits_start_step() -> None:
    g = _tiny_graph()
    steps = path_to_steps(g, ["a"])
    assert len(steps) == 1
    assert steps[0].text.startswith("Start at Alpha")
    assert steps[0].node_id == "a"
    assert steps[0].edge_id is None


def test_two_node_path_emits_start_and_arrival() -> None:
    g = _tiny_graph()
    lines = describe_path(g, ["a", "b"])
    assert lines == [
        "1. Start at Alpha.",
        "2. Arrive at Beta.",
    ]


def test_uses_node_id_when_label_missing() -> None:
    g = TopologyGraph()
    g.add_node(TopologyNode(id="solo", label="", type="room"))
    steps = path_to_steps(g, ["solo"])
    assert steps[0].text == "Start at solo"


def test_corridor_uses_proceed_phrasing() -> None:
    g = load_graph(EXAMPLE_YAML)
    lines = describe_path(g, ["entrance", "corridor_main", "lobby_intersection", "meeting_room"])
    assert lines[1].startswith("2. Proceed through Main Corridor")
    assert lines[2].startswith("3. Continue through Lobby Intersection")
    assert lines[-1].startswith("4. Arrive at Meeting Room")


def test_restricted_edge_is_called_out() -> None:
    g = load_graph(EXAMPLE_YAML)
    # corridor_main -> meeting_room is the restricted shortcut.
    lines = describe_path(g, ["entrance", "corridor_main", "meeting_room"])
    assert "restricted" in lines[-1].lower()
    assert lines[-1].startswith("3. Arrive at Meeting Room via a restricted route")


def test_elevator_connection_emits_transit_step() -> None:
    g = load_graph(EXAMPLE_YAML)
    path = ["entrance", "corridor_main", "elevator_1f", "elevator_2f", "corridor_2f", "office_2f"]
    steps = path_to_steps(g, path)
    elevator_step = next(s for s in steps if "Take the elevator from" in s.text)
    assert "Elevator A (1F)" in elevator_step.text
    assert "Elevator A (2F)" in elevator_step.text
    assert elevator_step.edge_id == "elevator_link"


def test_stairs_up_emits_transit_step() -> None:
    g = load_graph(EXAMPLE_YAML)
    path = ["entrance", "corridor_main", "lobby_intersection", "stairs_1f", "stairs_2f", "corridor_2f", "office_2f"]
    steps = path_to_steps(g, path)
    stair_step = next(s for s in steps if "Go up the stairs" in s.text)
    assert "North Stairs (1F)" in stair_step.text
    assert "North Stairs (2F)" in stair_step.text
    assert stair_step.edge_id == "stairs_link"


def test_floor_change_callout_inserted() -> None:
    g = load_graph(EXAMPLE_YAML)
    lines = describe_path(
        g,
        ["entrance", "corridor_main", "elevator_1f", "elevator_2f", "corridor_2f", "office_2f"],
    )
    floor_lines = [line for line in lines if "Floor change" in line]
    assert len(floor_lines) == 1
    assert "1 -> 2" in floor_lines[0]


def test_floor_change_callout_can_be_disabled() -> None:
    g = load_graph(EXAMPLE_YAML)
    steps = path_to_steps(
        g,
        ["entrance", "corridor_main", "elevator_1f", "elevator_2f"],
        include_floor_changes=False,
    )
    assert all("Floor change" not in s.text for s in steps)


def test_steps_are_indexed_contiguously() -> None:
    g = load_graph(EXAMPLE_YAML)
    steps = path_to_steps(
        g,
        ["entrance", "corridor_main", "elevator_1f", "elevator_2f", "corridor_2f", "office_2f"],
    )
    assert [s.index for s in steps] == list(range(1, len(steps) + 1))


def test_pathstep_to_dict_round_trips_fields() -> None:
    s = PathStep(index=2, text="Take the elevator from A to B", node_id="b", edge_id="ab")
    assert s.to_dict() == {
        "index": 2,
        "text": "Take the elevator from A to B",
        "node_id": "b",
        "edge_id": "ab",
    }


def test_determinism_across_calls() -> None:
    g = load_graph(EXAMPLE_YAML)
    path = ["entrance", "corridor_main", "elevator_1f", "elevator_2f", "corridor_2f", "office_2f"]
    a = describe_path(g, path)
    b = describe_path(g, path)
    assert a == b
