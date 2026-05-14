"""Tests for the semantic query helpers and the find/nearest CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from semantic_toponav.cli.main import main
from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode
from semantic_toponav.query import (
    NoMatchError,
    find_nodes,
    nearest_node_by_graph_distance,
    nearest_node_by_pose,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "indoor_office.yaml"


# ---------------------------- find_nodes ----------------------------


def test_find_nodes_by_type() -> None:
    g = load_graph(EXAMPLE)
    ids = {n.id for n in find_nodes(g, type="elevator")}
    assert ids == {"elevator_1f", "elevator_2f"}


def test_find_nodes_by_label_contains() -> None:
    g = load_graph(EXAMPLE)
    ids = {n.id for n in find_nodes(g, label_contains="corridor")}
    assert ids == {"corridor_main", "corridor_2f"}


def test_find_nodes_by_label_equals() -> None:
    g = load_graph(EXAMPLE)
    ids = {n.id for n in find_nodes(g, label_equals="Kitchen")}
    assert ids == {"kitchen"}


def test_find_nodes_by_property() -> None:
    g = load_graph(EXAMPLE)
    ids = {n.id for n in find_nodes(g, properties={"floor": 2})}
    assert "office_2f" in ids
    assert "kitchen" not in ids


def test_find_nodes_filters_compose() -> None:
    g = load_graph(EXAMPLE)
    ids = {n.id for n in find_nodes(g, type="room", properties={"floor": 1})}
    assert ids == {"kitchen", "meeting_room", "lab"}


def test_find_nodes_no_filters_returns_all() -> None:
    g = load_graph(EXAMPLE)
    assert len(find_nodes(g)) == len(g.node_ids())


# ---------------------------- nearest_node_by_pose ----------------------------


def test_nearest_by_pose_basic() -> None:
    g = load_graph(EXAMPLE)
    # entrance is at (0,0); elevator_1f at (6,0), elevator_2f at (6,10)
    node = nearest_node_by_pose(g, (0.0, 0.0), type="elevator")
    assert node.id == "elevator_1f"


def test_nearest_by_pose_accepts_pose2d() -> None:
    g = load_graph(EXAMPLE)
    node = nearest_node_by_pose(g, Pose2D(0.0, 11.0), type="elevator")
    assert node.id == "elevator_2f"


def test_nearest_by_pose_skips_nodes_without_pose() -> None:
    g = TopologyGraph()
    g.add_node(TopologyNode(id="a", label="A", type="room", pose=Pose2D(0, 0)))
    g.add_node(TopologyNode(id="b", label="B", type="room"))  # no pose
    g.add_node(TopologyNode(id="c", label="C", type="room", pose=Pose2D(10, 10)))
    node = nearest_node_by_pose(g, (5.0, 5.0))
    # b is closer to (5,5) but has no pose; a is closer than c
    assert node.id == "a"


def test_nearest_by_pose_raises_on_no_match() -> None:
    g = load_graph(EXAMPLE)
    with pytest.raises(NoMatchError):
        nearest_node_by_pose(g, (0.0, 0.0), type="nonexistent")


# ---------------------------- nearest_node_by_graph_distance ----------------


def test_nearest_by_graph_distance_basic() -> None:
    g = load_graph(EXAMPLE)
    node, path = nearest_node_by_graph_distance(g, "entrance", type="room")
    # Default planner takes the restricted shortcut to meeting_room (cost 2).
    assert node.id == "meeting_room"
    assert path[0] == "entrance"
    assert path[-1] == "meeting_room"


def test_nearest_by_graph_distance_returns_self_if_matches() -> None:
    g = load_graph(EXAMPLE)
    node, path = nearest_node_by_graph_distance(g, "elevator_1f", type="elevator")
    assert node.id == "elevator_1f"
    assert path == ["elevator_1f"]


def test_nearest_by_graph_distance_unknown_start() -> None:
    g = load_graph(EXAMPLE)
    with pytest.raises(NoMatchError):
        nearest_node_by_graph_distance(g, "nope", type="room")


def test_nearest_by_graph_distance_no_match() -> None:
    g = load_graph(EXAMPLE)
    with pytest.raises(NoMatchError):
        nearest_node_by_graph_distance(g, "entrance", type="zoo")


def test_nearest_by_graph_distance_unreachable_raises() -> None:
    g = TopologyGraph()
    g.add_node(TopologyNode(id="a", label="A", type="room", pose=Pose2D(0, 0)))
    g.add_node(TopologyNode(id="b", label="B", type="room", pose=Pose2D(1, 0)))
    g.add_node(TopologyNode(id="c", label="C", type="elevator", pose=Pose2D(99, 0)))
    g.add_edge(TopologyEdge(id="ab", source="a", target="b", type="traversable"))
    # c is unreachable.
    with pytest.raises(NoMatchError):
        nearest_node_by_graph_distance(g, "a", type="elevator")


# ---------------------------- CLI ----------------------------


def test_cli_find_text(capsys) -> None:
    rc = main(["find", str(EXAMPLE), "--type", "elevator"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "elevator_1f" in out
    assert "elevator_2f" in out


def test_cli_find_json(capsys) -> None:
    rc = main(["find", str(EXAMPLE), "--type", "elevator", "--format", "json"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert {d["id"] for d in data} == {"elevator_1f", "elevator_2f"}


def test_cli_find_by_property(capsys) -> None:
    rc = main(["find", str(EXAMPLE), "--prop", "floor=2", "--format", "json"])
    out = capsys.readouterr().out
    assert rc == 0
    ids = {d["id"] for d in json.loads(out)}
    assert "office_2f" in ids
    assert "kitchen" not in ids


def test_cli_nearest_from_node(capsys) -> None:
    rc = main(
        [
            "nearest",
            str(EXAMPLE),
            "--from-node",
            "entrance",
            "--type",
            "elevator",
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["mode"] == "graph_distance"
    assert data["node"]["id"] == "elevator_1f"
    assert data["path"][0] == "entrance"


def test_cli_nearest_from_pose(capsys) -> None:
    rc = main(
        [
            "nearest",
            str(EXAMPLE),
            "--from-pose",
            "0",
            "0",
            "--type",
            "elevator",
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["mode"] == "euclidean"
    assert data["node"]["id"] == "elevator_1f"


def test_cli_nearest_requires_one_source(capsys) -> None:
    rc = main(
        [
            "nearest",
            str(EXAMPLE),
            "--from-node",
            "entrance",
            "--from-pose",
            "0",
            "0",
            "--type",
            "elevator",
        ]
    )
    err = capsys.readouterr().err
    assert rc != 0
    assert "exactly one" in err


def test_cli_nearest_no_match(capsys) -> None:
    rc = main(
        [
            "nearest",
            str(EXAMPLE),
            "--from-node",
            "entrance",
            "--type",
            "zoo",
        ]
    )
    err = capsys.readouterr().err
    assert rc != 0
    assert "no" in err.lower()
