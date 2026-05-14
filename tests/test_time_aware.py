"""Tests for time_aware (temporal restrictions on edges and nodes)."""

from __future__ import annotations

import math
from datetime import date, datetime, time

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


# ---------------------------------------------------------------------------
# Calendar layer (at_date): weekday filters + closed_on_dates overrides.
# ---------------------------------------------------------------------------


def test_weekday_filter_blocks_only_on_listed_weekdays() -> None:
    # Edge closed 09:00-17:00 only on Mon-Fri (weekdays 0..4).
    g = _diamond_with_window(closed_edge=[["09:00", "17:00", [0, 1, 2, 3, 4]]])
    # 2026-05-15 is a Friday -> closure active.
    cost_fri = time_aware(g, at_time="10:00", at_date=date(2026, 5, 15))
    assert math.isinf(cost_fri(g.get_edge("ab")))
    # 2026-05-16 is a Saturday -> closure dormant, base cost.
    cost_sat = time_aware(g, at_time="10:00", at_date=date(2026, 5, 16))
    assert cost_sat(g.get_edge("ab")) == 1.0


def test_weekday_names_are_equivalent_to_ints() -> None:
    g_int = _diamond_with_window(closed_edge=[["09:00", "17:00", [0, 1, 2, 3, 4]]])
    g_name = _diamond_with_window(
        closed_edge=[["09:00", "17:00", ["Mon", "Tue", "Wed", "Thu", "Fri"]]]
    )
    on_fri = date(2026, 5, 15)
    on_sun = date(2026, 5, 17)
    for graph in (g_int, g_name):
        assert math.isinf(time_aware(graph, at_time="10:00", at_date=on_fri)(graph.get_edge("ab")))
        assert math.isfinite(time_aware(graph, at_time="10:00", at_date=on_sun)(graph.get_edge("ab")))


def test_weekday_filter_without_at_date_raises() -> None:
    g = _diamond_with_window(closed_edge=[["09:00", "17:00", [0, 1, 2, 3, 4]]])
    cost = time_aware(g, at_time="10:00")
    with pytest.raises(ValueError, match="weekday filter but no at_date"):
        cost(g.get_edge("ab"))


def test_invalid_weekday_int_raises() -> None:
    g = _diamond_with_window(closed_edge=[["09:00", "17:00", [7]]])
    with pytest.raises(ValueError, match="weekday int must be in 0..6"):
        time_aware(g, at_time="10:00", at_date=date(2026, 5, 15))(g.get_edge("ab"))


def test_invalid_weekday_name_raises() -> None:
    g = _diamond_with_window(closed_edge=[["09:00", "17:00", ["xyz"]]])
    with pytest.raises(ValueError, match="unknown weekday"):
        time_aware(g, at_time="10:00", at_date=date(2026, 5, 15))(g.get_edge("ab"))


def test_closed_on_dates_full_day_override_on_edge() -> None:
    g = _diamond_with_window()
    # Stamp a holiday onto the edge directly.
    g.get_edge("ab").properties["closed_on_dates"] = ["2026-12-25", "2026-01-01"]
    cost_xmas = time_aware(g, at_time="03:00", at_date=date(2026, 12, 25))
    assert math.isinf(cost_xmas(g.get_edge("ab")))
    cost_other = time_aware(g, at_time="03:00", at_date=date(2026, 12, 26))
    assert cost_other(g.get_edge("ab")) == 1.0


def test_closed_on_dates_on_node_blocks_incident_edges() -> None:
    g = _diamond_with_window()
    g.get_node("b").properties["closed_on_dates"] = ["2026-12-25"]
    cost = time_aware(g, at_time="03:00", at_date=date(2026, 12, 25))
    assert math.isinf(cost(g.get_edge("ab")))
    assert math.isinf(cost(g.get_edge("bd")))
    assert math.isfinite(cost(g.get_edge("ac")))


def test_closed_on_dates_inactive_without_at_date() -> None:
    g = _diamond_with_window()
    g.get_edge("ab").properties["closed_on_dates"] = ["2026-12-25"]
    # No at_date supplied -> closed_on_dates is dormant, edge keeps base cost.
    cost = time_aware(g, at_time="03:00")
    assert cost(g.get_edge("ab")) == 1.0


def test_datetime_at_time_derives_date_automatically() -> None:
    # Friday 2026-05-15: weekday-filtered closure active.
    g = _diamond_with_window(closed_edge=[["09:00", "17:00", ["mon", "fri"]]])
    cost = time_aware(g, at_time=datetime(2026, 5, 15, 10, 0))
    assert math.isinf(cost(g.get_edge("ab")))
    # Sunday 2026-05-17: dormant.
    cost = time_aware(g, at_time=datetime(2026, 5, 17, 10, 0))
    assert cost(g.get_edge("ab")) == 1.0


def test_at_date_explicit_overrides_datetime_at_time() -> None:
    g = _diamond_with_window(closed_edge=[["09:00", "17:00", ["fri"]]])
    # at_time datetime says Sunday, but at_date kwarg says Friday -> Friday wins.
    cost = time_aware(
        g,
        at_time=datetime(2026, 5, 17, 10, 0),
        at_date=date(2026, 5, 15),
    )
    assert math.isinf(cost(g.get_edge("ab")))


def test_at_date_accepts_iso_string() -> None:
    g = _diamond_with_window(closed_edge=[["09:00", "17:00", ["fri"]]])
    cost = time_aware(g, at_time="10:00", at_date="2026-05-15")
    assert math.isinf(cost(g.get_edge("ab")))


def test_at_date_invalid_string_raises() -> None:
    g = _diamond_with_window()
    with pytest.raises(ValueError, match="ISO 'YYYY-MM-DD'"):
        time_aware(g, at_time="10:00", at_date="2026/05/15")


def test_closed_on_dates_malformed_raises() -> None:
    g = _diamond_with_window()
    g.get_edge("ab").properties["closed_on_dates"] = ["2026-13-99"]
    cost = time_aware(g, at_time="03:00", at_date=date(2026, 5, 15))
    with pytest.raises(ValueError, match="not ISO"):
        cost(g.get_edge("ab"))


def test_calendar_features_compose_with_avoid_restricted() -> None:
    from semantic_toponav.planner import avoid_restricted

    g = _diamond_with_window(closed_edge=[["09:00", "17:00", ["fri"]]])
    cost = compose_costs(
        avoid_restricted,
        time_aware(g, at_time="10:00", at_date=date(2026, 5, 15)),
    )
    # Friday in window: ab blocked (calendar), ac/cd restricted -> no path.
    with pytest.raises(NoPathError):
        plan_astar(g, "a", "d", cost_fn=cost)
    # Saturday: ab open, restricted still blocks ac/cd -> a-b-d.
    cost_sat = compose_costs(
        avoid_restricted,
        time_aware(g, at_time="10:00", at_date=date(2026, 5, 16)),
    )
    path = plan_astar(g, "a", "d", cost_fn=cost_sat)
    assert path == ["a", "b", "d"]


def test_cli_at_date_with_at_time_blocks_weekday_filtered_edge(tmp_path, capsys) -> None:
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
  - {id: ab, source: a, target: b, type: traversable, cost: 1.0, properties: {closed_during: [['09:00', '17:00', ['mon','tue','wed','thu','fri']]]}}
  - {id: bd, source: b, target: d, type: traversable, cost: 1.0}
  - {id: ac, source: a, target: c, type: traversable, cost: 5.0}
  - {id: cd, source: c, target: d, type: traversable, cost: 5.0}
""",
        encoding="utf-8",
    )
    import json

    # Friday 2026-05-15 at 10:00 -> closure active, planner reroutes a-c-d.
    rc = cli_main([
        "plan", str(yaml), "a", "d",
        "--at-time", "10:00", "--at-date", "2026-05-15",
        "--format", "json",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["path"] == ["a", "c", "d"]

    # Saturday 2026-05-16 same time -> closure dormant, fast route restored.
    rc = cli_main([
        "plan", str(yaml), "a", "d",
        "--at-time", "10:00", "--at-date", "2026-05-16",
        "--format", "json",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["path"] == ["a", "b", "d"]


def test_cli_at_date_without_at_time_raises(tmp_path, capsys) -> None:
    yaml = tmp_path / "g.yaml"
    yaml.write_text(
        """version: 1
metadata: {name: t}
nodes:
  - {id: a, label: A, type: room, pose: {x: 0, y: 0, yaw: 0, frame_id: map}}
  - {id: b, label: B, type: room, pose: {x: 1, y: 0, yaw: 0, frame_id: map}}
edges:
  - {id: ab, source: a, target: b, type: traversable, cost: 1.0}
""",
        encoding="utf-8",
    )
    rc = cli_main(["plan", str(yaml), "a", "b", "--at-date", "2026-05-15"])
    assert rc != 0
    err = capsys.readouterr().err
    assert "--at-date requires --at-time" in err
