"""Tests for the A* planner."""

from __future__ import annotations

from pathlib import Path

import pytest

from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode
from semantic_toponav.planner.astar import plan_astar
from semantic_toponav.planner.errors import NoPathError, PlanningError

EXAMPLE_YAML = Path(__file__).resolve().parents[1] / "examples" / "indoor_office.yaml"


def _grid_graph() -> TopologyGraph:
    """Small graph with poses so the Euclidean heuristic is meaningful."""
    g = TopologyGraph()
    coords = {"a": (0, 0), "b": (1, 0), "c": (2, 0), "d": (3, 0), "e": (1, 1)}
    for nid, (x, y) in coords.items():
        g.add_node(TopologyNode(id=nid, label=nid.upper(), type="room", pose=Pose2D(x, y)))
    g.add_edge(TopologyEdge(id="ab", source="a", target="b", type="traversable", cost=1.0))
    g.add_edge(TopologyEdge(id="bc", source="b", target="c", type="traversable", cost=1.0))
    g.add_edge(TopologyEdge(id="cd", source="c", target="d", type="traversable", cost=1.0))
    g.add_edge(TopologyEdge(id="be", source="b", target="e", type="traversable", cost=1.0))
    return g


def test_astar_with_pose_heuristic() -> None:
    g = _grid_graph()
    assert plan_astar(g, "a", "d") == ["a", "b", "c", "d"]


def test_astar_without_pose() -> None:
    """A* must still work when nodes have no pose (heuristic returns 0)."""
    g = TopologyGraph()
    for nid in "abc":
        g.add_node(TopologyNode(id=nid, label=nid.upper(), type="room"))
    g.add_edge(TopologyEdge(id="ab", source="a", target="b", type="traversable"))
    g.add_edge(TopologyEdge(id="bc", source="b", target="c", type="traversable"))
    assert plan_astar(g, "a", "c") == ["a", "b", "c"]


def test_astar_indoor_office_default_takes_restricted_shortcut() -> None:
    g = load_graph(EXAMPLE_YAML)
    # The cheap restricted edge is one hop from corridor_main.
    path = plan_astar(g, "entrance", "meeting_room")
    assert path == ["entrance", "corridor_main", "meeting_room"]


def test_astar_indoor_office_to_office_2f_uses_stairs() -> None:
    g = load_graph(EXAMPLE_YAML)
    path = plan_astar(g, "entrance", "office_2f")
    assert "stairs_1f" in path
    assert "stairs_2f" in path


def test_astar_missing_start() -> None:
    g = _grid_graph()
    with pytest.raises(PlanningError):
        plan_astar(g, "z", "a")


def test_astar_no_path() -> None:
    g = TopologyGraph()
    g.add_node(TopologyNode(id="x", label="X", type="room"))
    g.add_node(TopologyNode(id="y", label="Y", type="room"))
    with pytest.raises(NoPathError):
        plan_astar(g, "x", "y")
