"""Tests for runtime edge-blocking cost factories."""

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
    block_edge_types,
    block_edges,
    compose_costs,
    plan_astar,
    plan_dijkstra,
    prefer_elevator,
)

MULTI_FLOOR = Path(__file__).resolve().parents[1] / "examples" / "multi_floor_office.yaml"


def _diamond() -> TopologyGraph:
    """a -- b -- d (cost 1+1)
       a -- c -- d (cost 5+5).
    """
    g = TopologyGraph()
    for nid in "abcd":
        g.add_node(TopologyNode(id=nid, label=nid.upper(), type="room", pose=Pose2D(0, 0)))
    g.add_edge(TopologyEdge(id="ab", source="a", target="b", type="traversable", cost=1.0))
    g.add_edge(TopologyEdge(id="bd", source="b", target="d", type="traversable", cost=1.0))
    g.add_edge(TopologyEdge(id="ac", source="a", target="c", type="restricted", cost=5.0))
    g.add_edge(TopologyEdge(id="cd", source="c", target="d", type="restricted", cost=5.0))
    return g


# --------------------------- block_edges ---------------------------


def test_block_edges_returns_inf_for_listed() -> None:
    g = _diamond()
    cost = block_edges(["ab"])
    assert math.isinf(cost(g.get_edge("ab")))
    assert math.isclose(cost(g.get_edge("bd")), 1.0)


def test_block_edges_reroutes_planner() -> None:
    g = _diamond()
    # Default takes a -> b -> d (cost 2).
    assert plan_dijkstra(g, "a", "d") == ["a", "b", "d"]
    # Blocking ab forces the detour through c.
    path = plan_dijkstra(g, "a", "d", cost_fn=block_edges(["ab"]))
    assert path == ["a", "c", "d"]


def test_block_edges_can_make_planning_fail() -> None:
    g = _diamond()
    with pytest.raises(NoPathError):
        plan_dijkstra(g, "a", "d", cost_fn=block_edges(["ab", "ac"]))


def test_block_edges_accepts_iterable() -> None:
    g = _diamond()
    cost = block_edges(iter(["ab"]))
    assert math.isinf(cost(g.get_edge("ab")))


def test_block_edges_unknown_ids_are_ignored() -> None:
    g = _diamond()
    cost = block_edges(["zz"])
    for e in g.edges():
        assert math.isclose(cost(e), e.cost)


# --------------------------- block_edge_types ---------------------------


def test_block_edge_types_returns_inf_for_listed_types() -> None:
    g = _diamond()
    cost = block_edge_types({"restricted"})
    assert math.isinf(cost(g.get_edge("ac")))
    assert math.isclose(cost(g.get_edge("ab")), 1.0)


def test_block_edge_types_on_multi_floor_example() -> None:
    g = load_graph(MULTI_FLOOR)
    # Default takes stairs.
    default_path = plan_astar(g, "entrance", "exec_office_3f")
    assert any(nid.startswith("stairs_") for nid in default_path)
    # Blocking stairs_up forces the elevator route.
    path = plan_astar(
        g, "entrance", "exec_office_3f", cost_fn=block_edge_types({"stairs_up"})
    )
    assert any(nid.startswith("elevator_") for nid in path)
    assert not any(nid.startswith("stairs_") for nid in path)


def test_blocking_all_vertical_types_makes_3f_unreachable() -> None:
    g = load_graph(MULTI_FLOOR)
    with pytest.raises(NoPathError):
        plan_astar(
            g,
            "entrance",
            "exec_office_3f",
            cost_fn=block_edge_types({"stairs_up", "elevator_connection"}),
        )


# --------------------------- compose_costs interplay ---------------------------


def test_block_composes_with_other_cost_functions() -> None:
    g = load_graph(MULTI_FLOOR)
    cost = compose_costs(prefer_elevator, block_edge_types({"elevator_connection"}))
    # prefer_elevator alone would route via elevator; blocking elevator forces stairs.
    path = plan_astar(g, "entrance", "exec_office_3f", cost_fn=cost)
    assert any(nid.startswith("stairs_") for nid in path)


# --------------------------- CLI ---------------------------


def test_cli_block_single_edge_changes_route(capsys) -> None:
    rc = cli_main(
        [
            "plan",
            str(MULTI_FLOOR),
            "entrance",
            "exec_office_3f",
            "--block-edge",
            "e_stairs_1f_2f",
            "--format",
            "json",
        ]
    )
    import json as _json
    out = capsys.readouterr().out
    assert rc == 0
    payload = _json.loads(out)
    assert "elevator_1f" in payload["path"]
    assert "stairs_1f" not in payload["path"]


def test_cli_block_edge_type(capsys) -> None:
    rc = cli_main(
        [
            "plan",
            str(MULTI_FLOOR),
            "entrance",
            "exec_office_3f",
            "--block-edge-type",
            "stairs_up",
            "--format",
            "json",
        ]
    )
    import json as _json
    out = capsys.readouterr().out
    assert rc == 0
    payload = _json.loads(out)
    floors = [
        load_graph(MULTI_FLOOR).get_node(nid).properties.get("floor")
        for nid in payload["path"]
    ]
    assert max(floors) == 3
    assert "elevator_1f" in payload["path"]


def test_cli_blocking_everything_returns_error(capsys) -> None:
    rc = cli_main(
        [
            "plan",
            str(MULTI_FLOOR),
            "entrance",
            "exec_office_3f",
            "--block-edge-type",
            "stairs_up",
            "--block-edge-type",
            "elevator_connection",
        ]
    )
    err = capsys.readouterr().err
    assert rc != 0
    assert "no path" in err.lower()
