"""Tests for time_aware (temporal restrictions on edges and nodes)."""

from __future__ import annotations

import math
from datetime import datetime, time

import pytest

from semantic_toponav.cli.main import main as cli_main
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode
from semantic_toponav.planner import (
    NoPathError,
    compose_costs,
    plan_astar,
    time_aware,
)


def _diamond_with_window(
    *,
    closed_edge: list | None = None,
    closed_node: list | None = None,
) -> TopologyGraph:
    """a -- b -- d (cost 1+1); a -- c -- d (cost 5+5). b is the fast hop."""
    g = TopologyGraph()
    for nid in "abcd":
        node = TopologyNode(
            id=nid,
            label=nid.upper(),
            type="room",
            pose=Pose2D(0, 0),
            properties={"closed_during": closed_node} if (nid == "b" and closed_node) else {},
        )
        g.add_node(node)
    props_ab = {"closed_during": closed_edge} if closed_edge else {}
    g.add_edge(TopologyEdge(id="ab", source="a", target="b", type="traversable", cost=1.0, properties=props_ab))
    g.add_edge(TopologyEdge(id="bd", source="b", target="d", type="traversable", cost=1.0))
    g.add_edge(TopologyEdge(id="ac", source="a", target="c", type="restricted", cost=5.0))
    g.add_edge(TopologyEdge(id="cd", source="c", target="d", type="restricted", cost=5.0))
    return g


def test_edge_closed_during_blocks_edge_at_time() -> None:
    g = _diamond_with_window(closed_edge=[["12:00", "13:00"]])
    cost = time_aware(g, at_time="12:30")
    assert math.isinf(cost(g.get_edge("ab")))
    # The other edges are untouched.
    assert cost(g.get_edge("bd")) == 1.0
    assert cost(g.get_edge("ac")) == 5.0


def test_edge_closed_outside_window_uses_base_cost() -> None:
    g = _diamond_with_window(closed_edge=[["12:00", "13:00"]])
    cost = time_aware(g, at_time="11:59")
    assert cost(g.get_edge("ab")) == 1.0
    cost = time_aware(g, at_time="13:00")
    assert cost(g.get_edge("ab")) == 1.0


def test_node_closure_blocks_incident_edges() -> None:
    g = _diamond_with_window(closed_node=[["12:00", "13:00"]])
    cost = time_aware(g, at_time="12:30")
    # Both edges touching `b` (the fast hop's middle) are blocked.
    assert math.isinf(cost(g.get_edge("ab")))
    assert math.isinf(cost(g.get_edge("bd")))
    # The slow route around (a-c-d) is still available.
    assert math.isfinite(cost(g.get_edge("ac")))
    assert math.isfinite(cost(g.get_edge("cd")))


def test_midnight_wrap_interval() -> None:
    g = _diamond_with_window(closed_edge=[["22:00", "06:00"]])
    for t in ["22:00", "23:59", "00:00", "05:59"]:
        cost = time_aware(g, at_time=t)
        assert math.isinf(cost(g.get_edge("ab"))), t
    for t in ["06:00", "12:00", "21:59"]:
        cost = time_aware(g, at_time=t)
        assert math.isfinite(cost(g.get_edge("ab"))), t


def test_multiple_intervals_any_match_blocks() -> None:
    g = _diamond_with_window(
        closed_edge=[["09:00", "10:00"], ["14:00", "15:00"]]
    )
    for t in ["09:30", "14:30"]:
        assert math.isinf(time_aware(g, at_time=t)(g.get_edge("ab")))
    for t in ["10:00", "13:59", "15:00"]:
        assert math.isfinite(time_aware(g, at_time=t)(g.get_edge("ab")))


def test_accepts_time_and_datetime() -> None:
    g = _diamond_with_window(closed_edge=[["12:00", "13:00"]])
    assert math.isinf(time_aware(g, at_time=time(12, 30))(g.get_edge("ab")))
    assert math.isinf(
        time_aware(g, at_time=datetime(2026, 5, 14, 12, 30))(g.get_edge("ab"))
    )


def test_accepts_hhmmss_string() -> None:
    g = _diamond_with_window(closed_edge=[["12:00:00", "13:00:00"]])
    assert math.isinf(time_aware(g, at_time="12:30:00")(g.get_edge("ab")))


def test_planner_reroutes_around_closed_window() -> None:
    g = _diamond_with_window(closed_edge=[["12:00", "13:00"]])
    # During the window the fast route is unavailable; planner must take a-c-d.
    path = plan_astar(g, "a", "d", cost_fn=time_aware(g, at_time="12:30"))
    assert path == ["a", "c", "d"]
    # Outside the window the fast route is restored.
    path = plan_astar(g, "a", "d", cost_fn=time_aware(g, at_time="13:30"))
    assert path == ["a", "b", "d"]


def test_planner_fails_when_node_closure_disconnects_graph() -> None:
    g = _diamond_with_window(closed_node=[["12:00", "13:00"]])
    # Closing b is fine — there's still a-c-d. Verify that.
    path = plan_astar(g, "a", "d", cost_fn=time_aware(g, at_time="12:30"))
    assert path == ["a", "c", "d"]

    # Now close ALL the non-c nodes during the window so no route is left.
    g2 = TopologyGraph()
    for nid in "ad":
        g2.add_node(TopologyNode(id=nid, label=nid, type="room", pose=Pose2D(0, 0)))
    g2.add_node(
        TopologyNode(
            id="mid",
            label="mid",
            type="room",
            pose=Pose2D(0, 0),
            properties={"closed_during": [["12:00", "13:00"]]},
        )
    )
    g2.add_edge(TopologyEdge(id="a_mid", source="a", target="mid", type="traversable"))
    g2.add_edge(TopologyEdge(id="mid_d", source="mid", target="d", type="traversable"))
    with pytest.raises(NoPathError):
        plan_astar(g2, "a", "d", cost_fn=time_aware(g2, at_time="12:30"))


def test_composes_with_other_cost_functions() -> None:
    from semantic_toponav.planner import avoid_restricted

    g = _diamond_with_window(closed_edge=[["12:00", "13:00"]])
    # During the window: ab is closed (time) AND ac/cd are restricted -> no path.
    with pytest.raises(NoPathError):
        plan_astar(
            g,
            "a",
            "d",
            cost_fn=compose_costs(
                avoid_restricted, time_aware(g, at_time="12:30")
            ),
        )
    # Outside the window: ab is fine, restricted blocks ac/cd, so a-b-d wins.
    path = plan_astar(
        g,
        "a",
        "d",
        cost_fn=compose_costs(avoid_restricted, time_aware(g, at_time="13:30")),
    )
    assert path == ["a", "b", "d"]


def test_missing_closed_during_property_is_silent() -> None:
    g = _diamond_with_window()
    cost = time_aware(g, at_time="12:30")
    # All edges keep their base cost.
    assert cost(g.get_edge("ab")) == 1.0
    assert cost(g.get_edge("ac")) == 5.0


def test_malformed_closed_during_raises() -> None:
    g = _diamond_with_window(closed_edge=[["12:00"]])  # missing end
    cost = time_aware(g, at_time="12:30")
    with pytest.raises(ValueError):
        cost(g.get_edge("ab"))


def test_invalid_hhmm_string_raises() -> None:
    g = _diamond_with_window(closed_edge=[["not-a-time", "13:00"]])
    cost = time_aware(g, at_time="12:30")
    with pytest.raises(ValueError):
        cost(g.get_edge("ab"))


def test_at_time_invalid_type_raises() -> None:
    g = _diamond_with_window()
    with pytest.raises(TypeError):
        time_aware(g, at_time=12345)  # type: ignore[arg-type]


def test_cli_at_time_blocks_edge_during_window(tmp_path, capsys) -> None:
    yaml = tmp_path / "g.yaml"
    yaml.write_text(
        """version: 1
metadata: {name: t}
nodes:
  - {id: a, label: A, type: room, pose: {x: 0, y: 0, yaw: 0, frame_id: map}}
  - {id: b, label: B, type: room, pose: {x: 1, y: 0, yaw: 0, frame_id: map}}
  - {id: c, label: C, type: room, pose: {x: 1, y: 1, yaw: 0, frame_id: map}}
  - {id: d, label: D, type: room, pose: {x: 2, y: 0, yaw: 0, frame_id: map}}
edges:
  - {id: ab, source: a, target: b, type: traversable, cost: 1.0, properties: {closed_during: [['12:00', '13:00']]}}
  - {id: bd, source: b, target: d, type: traversable, cost: 1.0}
  - {id: ac, source: a, target: c, type: traversable, cost: 5.0}
  - {id: cd, source: c, target: d, type: traversable, cost: 5.0}
""",
        encoding="utf-8",
    )
    import json

    rc = cli_main(["plan", str(yaml), "a", "d", "--at-time", "12:30", "--format", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["path"] == ["a", "c", "d"]

    rc = cli_main(["plan", str(yaml), "a", "d", "--at-time", "13:30", "--format", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["path"] == ["a", "b", "d"]
