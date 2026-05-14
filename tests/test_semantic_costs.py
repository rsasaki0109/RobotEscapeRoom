"""Tests for semantic cost functions and their effect on routing."""

from __future__ import annotations

from pathlib import Path

from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.planner.astar import plan_astar
from semantic_toponav.planner.dijkstra import plan_dijkstra
from semantic_toponav.planner.semantic_costs import (
    avoid_restricted,
    avoid_stairs,
    compose_costs,
    prefer_elevator,
)

EXAMPLE_YAML = Path(__file__).resolve().parents[1] / "examples" / "indoor_office.yaml"


def test_avoid_restricted_changes_route() -> None:
    g = load_graph(EXAMPLE_YAML)
    default_path = plan_astar(g, "entrance", "meeting_room")
    restricted_path = plan_astar(g, "entrance", "meeting_room", cost_fn=avoid_restricted)
    assert "lobby_intersection" not in default_path
    assert "lobby_intersection" in restricted_path


def test_avoid_stairs_switches_to_elevator() -> None:
    g = load_graph(EXAMPLE_YAML)
    default_path = plan_astar(g, "entrance", "office_2f")
    assert "stairs_1f" in default_path  # default takes stairs

    cost = compose_costs(avoid_stairs)
    new_path = plan_astar(g, "entrance", "office_2f", cost_fn=cost)
    assert "stairs_1f" not in new_path
    assert "elevator_1f" in new_path


def test_prefer_elevator_picks_elevator_when_close() -> None:
    # Use Dijkstra: the default Euclidean A* heuristic is not admissible when
    # semantic edge costs (~1.0) are much smaller than geometric distances
    # between poses, so A* may miss the optimal route here. Cost-function
    # behavior is what we are actually validating in this test.
    g = load_graph(EXAMPLE_YAML)
    cost = compose_costs(prefer_elevator)
    path = plan_dijkstra(g, "entrance", "office_2f", cost_fn=cost)
    assert "elevator_1f" in path


def test_compose_costs_blocks_when_any_returns_inf() -> None:
    g = load_graph(EXAMPLE_YAML)
    cost = compose_costs(avoid_restricted, avoid_stairs)
    path = plan_astar(g, "entrance", "meeting_room", cost_fn=cost)
    assert "lobby_intersection" in path
