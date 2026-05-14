"""Tests for the Dijkstra planner."""

from __future__ import annotations

import math

import pytest

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode
from semantic_toponav.planner.dijkstra import plan_dijkstra
from semantic_toponav.planner.errors import NoPathError, PlanningError


def _line_graph() -> TopologyGraph:
    """a - b - c - d, plus a longer detour a - e - d."""
    g = TopologyGraph()
    for i in "abcde":
        g.add_node(TopologyNode(id=i, label=i.upper(), type="corridor", pose=Pose2D(0, 0)))
    g.add_edge(TopologyEdge(id="ab", source="a", target="b", type="traversable", cost=1.0))
    g.add_edge(TopologyEdge(id="bc", source="b", target="c", type="traversable", cost=1.0))
    g.add_edge(TopologyEdge(id="cd", source="c", target="d", type="traversable", cost=1.0))
    g.add_edge(TopologyEdge(id="ae", source="a", target="e", type="traversable", cost=5.0))
    g.add_edge(TopologyEdge(id="ed", source="e", target="d", type="traversable", cost=5.0))
    return g


def test_shortest_path() -> None:
    g = _line_graph()
    assert plan_dijkstra(g, "a", "d") == ["a", "b", "c", "d"]


def test_start_equals_goal() -> None:
    g = _line_graph()
    assert plan_dijkstra(g, "a", "a") == ["a"]


def test_missing_start_raises() -> None:
    g = _line_graph()
    with pytest.raises(PlanningError):
        plan_dijkstra(g, "z", "d")


def test_missing_goal_raises() -> None:
    g = _line_graph()
    with pytest.raises(PlanningError):
        plan_dijkstra(g, "a", "z")


def test_no_path_raises() -> None:
    g = TopologyGraph()
    g.add_node(TopologyNode(id="x", label="X", type="room"))
    g.add_node(TopologyNode(id="y", label="Y", type="room"))
    with pytest.raises(NoPathError):
        plan_dijkstra(g, "x", "y")


def test_custom_cost_blocks_edge() -> None:
    """A custom cost function returning inf should make the planner avoid the edge."""
    g = _line_graph()

    def block_bc(edge: TopologyEdge) -> float:
        if edge.id == "bc":
            return math.inf
        return edge.cost

    assert plan_dijkstra(g, "a", "d", cost_fn=block_bc) == ["a", "e", "d"]
