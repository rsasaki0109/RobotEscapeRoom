"""Tests for floor-aware costs, heuristic, and the 3-floor example."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from semantic_toponav.cli.main import main as cli_main
from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode
from semantic_toponav.planner import (
    NoPathError,
    floor_aware_heuristic,
    floor_change_penalty,
    plan_astar,
    plan_dijkstra,
    prefer_floor,
    same_floor_only,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "multi_floor_office.yaml"


def _tiny_two_floor_graph() -> TopologyGraph:
    """a(1F) -- b(1F) -- c(2F) -- d(2F)."""
    g = TopologyGraph()
    g.add_node(TopologyNode(id="a", label="A", type="room",
                            pose=Pose2D(0, 0), properties={"floor": 1}))
    g.add_node(TopologyNode(id="b", label="B", type="corridor",
                            pose=Pose2D(1, 0), properties={"floor": 1}))
    g.add_node(TopologyNode(id="c", label="C", type="corridor",
                            pose=Pose2D(1, 1), properties={"floor": 2}))
    g.add_node(TopologyNode(id="d", label="D", type="room",
                            pose=Pose2D(2, 1), properties={"floor": 2}))
    g.add_edge(TopologyEdge(id="ab", source="a", target="b", type="traversable", cost=1.0))
    g.add_edge(TopologyEdge(id="bc", source="b", target="c", type="stairs_up", cost=2.0))
    g.add_edge(TopologyEdge(id="cd", source="c", target="d", type="traversable", cost=1.0))
    return g


# ---------------------------- multi-floor example file -----------------------


def test_example_loads_with_3_floors() -> None:
    g = load_graph(EXAMPLE)
    g.validate()
    floors = {n.properties.get("floor") for n in g.nodes()}
    assert floors == {1, 2, 3}


def test_default_route_to_floor_3_uses_stairs() -> None:
    g = load_graph(EXAMPLE)
    path = plan_astar(g, "entrance", "exec_office_3f")
    assert "stairs_1f" in path and "stairs_3f" in path


# ---------------------------- floor_change_penalty ---------------------------


def test_floor_change_penalty_adds_cost_only_on_floor_crossings() -> None:
    g = _tiny_two_floor_graph()
    cost = floor_change_penalty(g, penalty=10.0)
    # ab stays on floor 1 -> no penalty
    ab = g.get_edge("ab")
    assert math.isclose(cost(ab), ab.cost)
    # bc crosses floors -> +10
    bc = g.get_edge("bc")
    assert math.isclose(cost(bc), bc.cost + 10.0)


def test_floor_change_penalty_scales_with_floor_distance() -> None:
    g = _tiny_two_floor_graph()
    g.add_node(TopologyNode(id="e", label="E", type="corridor",
                            pose=Pose2D(1, 2), properties={"floor": 3}))
    g.add_edge(TopologyEdge(id="ce", source="c", target="e", type="stairs_up", cost=2.0))
    g.add_edge(TopologyEdge(id="be", source="b", target="e", type="elevator_connection", cost=3.0))
    cost = floor_change_penalty(g, penalty=10.0)
    be = g.get_edge("be")  # floor 1 -> floor 3
    assert math.isclose(cost(be), be.cost + 20.0)


# ---------------------------- prefer_floor ---------------------------


def test_prefer_floor_keeps_same_floor_edges_at_base_cost() -> None:
    g = _tiny_two_floor_graph()
    cost = prefer_floor(g, 1)
    ab = g.get_edge("ab")
    assert math.isclose(cost(ab), ab.cost)


def test_prefer_floor_doubles_off_floor_edges() -> None:
    g = _tiny_two_floor_graph()
    cost = prefer_floor(g, 1, off_floor_multiplier=2.0)
    cd = g.get_edge("cd")
    assert math.isclose(cost(cd), cd.cost * 2.0)


# ---------------------------- same_floor_only ---------------------------


def test_same_floor_only_blocks_inter_floor_edges() -> None:
    g = _tiny_two_floor_graph()
    cost = same_floor_only(g)
    bc = g.get_edge("bc")
    assert math.isinf(cost(bc))


def test_same_floor_only_makes_cross_floor_planning_fail() -> None:
    g = load_graph(EXAMPLE)
    with pytest.raises(NoPathError):
        plan_dijkstra(g, "entrance", "exec_office_3f", cost_fn=same_floor_only(g))


def test_same_floor_only_allows_within_floor_planning() -> None:
    g = load_graph(EXAMPLE)
    # kitchen and lab are both on floor 1.
    path = plan_dijkstra(g, "kitchen_1f", "lab_1f", cost_fn=same_floor_only(g))
    floors = {g.get_node(nid).properties.get("floor") for nid in path}
    assert floors == {1}


# ---------------------------- floor_aware_heuristic ---------------------------


def test_floor_aware_heuristic_adds_floor_distance() -> None:
    g = _tiny_two_floor_graph()
    h = floor_aware_heuristic(floor_height=5.0)
    # a (0,0,floor1) -> d (2,1,floor2): planar ~sqrt(5)=2.236, +5 for floor diff
    val = h(g, "a", "d")
    expected = math.hypot(2.0, 1.0) + 5.0
    assert math.isclose(val, expected)


def test_floor_aware_heuristic_finds_correct_path() -> None:
    g = load_graph(EXAMPLE)
    path = plan_astar(
        g,
        "entrance",
        "meeting_room_2f",
        heuristic_fn=floor_aware_heuristic(floor_height=2.0),
    )
    assert path[0] == "entrance"
    assert path[-1] == "meeting_room_2f"


def test_floor_aware_heuristic_falls_back_when_floor_missing() -> None:
    g = TopologyGraph()
    g.add_node(TopologyNode(id="a", label="A", type="room", pose=Pose2D(0, 0)))
    g.add_node(TopologyNode(id="b", label="B", type="room", pose=Pose2D(3, 4)))
    g.add_edge(TopologyEdge(id="ab", source="a", target="b", type="traversable"))
    h = floor_aware_heuristic(floor_height=5.0)
    # No floor property on either node — should return planar distance only.
    assert math.isclose(h(g, "a", "b"), 5.0)


# ---------------------------- CLI integration ---------------------------


def test_cli_same_floor_only_blocks_cross_floor(capsys) -> None:
    rc = cli_main(
        [
            "plan",
            str(EXAMPLE),
            "entrance",
            "exec_office_3f",
            "--same-floor-only",
        ]
    )
    err = capsys.readouterr().err
    assert rc != 0
    assert "no path" in err.lower()


def test_cli_floor_change_penalty_high_keeps_route_short(capsys) -> None:
    rc = cli_main(
        [
            "plan",
            str(EXAMPLE),
            "entrance",
            "meeting_room_2f",
            "--floor-change-penalty",
            "100",
            "--format",
            "json",
        ]
    )
    import json as _json
    out = capsys.readouterr().out
    assert rc == 0
    payload = _json.loads(out)
    # The planner should still find a path, since we have to change floors.
    assert payload["path"][0] == "entrance"
    assert payload["path"][-1] == "meeting_room_2f"


def test_cli_prefer_floor(capsys) -> None:
    rc = cli_main(
        [
            "plan",
            str(EXAMPLE),
            "kitchen_1f",
            "lab_1f",
            "--prefer-floor",
            "1",
            "--format",
            "json",
        ]
    )
    import json as _json
    out = capsys.readouterr().out
    assert rc == 0
    payload = _json.loads(out)
    g = load_graph(EXAMPLE)
    for nid in payload["path"]:
        assert g.get_node(nid).properties.get("floor") == 1
