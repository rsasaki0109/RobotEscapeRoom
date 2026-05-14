"""Unit + CLI tests for multi-agent shared-resource reservations."""

from __future__ import annotations

import json
import math
from datetime import datetime, time

import pytest

from semantic_toponav.cli.main import main as cli_main
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode
from semantic_toponav.planner import (
    NoPathError,
    Reservation,
    ReservationLoadError,
    ReservationTable,
    avoid_restricted,
    compose_costs,
    load_reservations,
    plan_astar,
    reservation_aware,
    time_aware,
)

# --------------------------- fixtures ---------------------------


def _diamond() -> TopologyGraph:
    """a-b-d (fast: 1+1) and a-c-d (slow: 5+5)."""
    g = TopologyGraph()
    for nid in "abcd":
        g.add_node(
            TopologyNode(id=nid, label=nid.upper(), type="room", pose=Pose2D(0, 0))
        )
    g.add_edge(TopologyEdge(id="ab", source="a", target="b", type="traversable", cost=1.0))
    g.add_edge(TopologyEdge(id="bd", source="b", target="d", type="traversable", cost=1.0))
    g.add_edge(TopologyEdge(id="ac", source="a", target="c", type="traversable", cost=5.0))
    g.add_edge(TopologyEdge(id="cd", source="c", target="d", type="traversable", cost=5.0))
    return g


# --------------------------- ReservationTable ---------------------------


def test_table_add_returns_stored_reservation() -> None:
    table = ReservationTable()
    r = table.add("ab", "12:00", "13:00", agent_id="robot_a")
    assert isinstance(r, Reservation)
    assert r.resource_id == "ab"
    assert r.start == time(12, 0)
    assert r.end == time(13, 0)
    assert r.agent_id == "robot_a"
    assert len(table) == 1
    assert list(table) == [r]


def test_table_add_accepts_time_and_datetime() -> None:
    table = ReservationTable()
    table.add("ab", time(9, 30), time(10, 0))
    table.add("cd", datetime(2026, 5, 14, 11), datetime(2026, 5, 14, 11, 30))
    assert {r.resource_id for r in table} == {"ab", "cd"}


def test_closed_at_returns_active_resource_ids() -> None:
    table = ReservationTable()
    table.add("ab", "12:00", "13:00")
    table.add("bd", "14:00", "15:00")
    assert table.closed_at("12:30") == {"ab"}
    assert table.closed_at("13:00") == set()  # end is exclusive
    assert table.closed_at("14:30") == {"bd"}
    assert table.closed_at("23:00") == set()


def test_closed_at_supports_midnight_wrap() -> None:
    table = ReservationTable()
    table.add("ab", "22:00", "06:00")
    for t in ["22:00", "23:30", "00:00", "05:59"]:
        assert table.closed_at(t) == {"ab"}, t
    for t in ["06:00", "12:00", "21:59"]:
        assert table.closed_at(t) == set(), t


def test_closed_at_returns_fresh_set_per_call() -> None:
    table = ReservationTable()
    table.add("ab", "12:00", "13:00")
    a = table.closed_at("12:30")
    b = table.closed_at("12:30")
    assert a == b
    a.add("contamination")
    assert "contamination" not in table.closed_at("12:30")


# --------------------------- reservation_aware cost ---------------------------


def test_blocks_edge_by_edge_id() -> None:
    g = _diamond()
    table = ReservationTable()
    table.add("ab", "12:00", "13:00")
    cost = reservation_aware(table, at_time="12:30")
    assert math.isinf(cost(g.get_edge("ab")))
    assert cost(g.get_edge("bd")) == 1.0
    assert cost(g.get_edge("ac")) == 5.0


def test_blocks_edge_when_endpoint_is_reserved() -> None:
    g = _diamond()
    table = ReservationTable()
    # Reserve node b → both incident edges should fail.
    table.add("b", "12:00", "13:00")
    cost = reservation_aware(table, at_time="12:30")
    assert math.isinf(cost(g.get_edge("ab")))
    assert math.isinf(cost(g.get_edge("bd")))
    assert math.isfinite(cost(g.get_edge("ac")))


def test_no_active_reservations_returns_base_cost() -> None:
    g = _diamond()
    table = ReservationTable()
    table.add("ab", "12:00", "13:00")
    cost = reservation_aware(table, at_time="14:00")
    assert cost(g.get_edge("ab")) == 1.0
    assert cost(g.get_edge("bd")) == 1.0


def test_unknown_resource_id_is_ignored() -> None:
    """Reservations referencing absent ids do not blow up — they just match nothing."""
    g = _diamond()
    table = ReservationTable()
    table.add("phantom_edge", "12:00", "13:00")
    cost = reservation_aware(table, at_time="12:30")
    for e in ("ab", "bd", "ac", "cd"):
        assert math.isfinite(cost(g.get_edge(e)))


def test_at_time_accepts_string_time_and_datetime() -> None:
    g = _diamond()
    table = ReservationTable()
    table.add("ab", "12:00", "13:00")
    for at in ["12:30", time(12, 30), datetime(2026, 5, 14, 12, 30)]:
        cost = reservation_aware(table, at_time=at)
        assert math.isinf(cost(g.get_edge("ab"))), at


def test_planner_reroutes_around_reservation() -> None:
    g = _diamond()
    table = ReservationTable()
    table.add("ab", "12:00", "13:00", agent_id="robot_a")
    path = plan_astar(g, "a", "d", cost_fn=reservation_aware(table, at_time="12:30"))
    assert path == ["a", "c", "d"]
    # Outside the window: fast route restored.
    path = plan_astar(g, "a", "d", cost_fn=reservation_aware(table, at_time="13:30"))
    assert path == ["a", "b", "d"]


def test_planner_fails_when_all_edges_reserved() -> None:
    g = _diamond()
    table = ReservationTable()
    for eid in ("ab", "ac"):
        table.add(eid, "12:00", "13:00")
    with pytest.raises(NoPathError):
        plan_astar(g, "a", "d", cost_fn=reservation_aware(table, at_time="12:30"))


def test_composes_with_time_aware_and_avoid_restricted() -> None:
    g = _diamond()
    # ac is restricted by static type; ab is restricted by another agent's claim.
    g.remove_edge("ac")
    g.add_edge(TopologyEdge(id="ac", source="a", target="c", type="restricted", cost=5.0))

    table = ReservationTable()
    table.add("ab", "12:00", "13:00")

    cost = compose_costs(
        avoid_restricted,
        time_aware(g, at_time="12:30"),
        reservation_aware(table, at_time="12:30"),
    )
    # During the window the fast route is reserved and the slow route is
    # restricted → no path.
    with pytest.raises(NoPathError):
        plan_astar(g, "a", "d", cost_fn=cost)


# --------------------------- serialization ---------------------------


def test_to_dict_round_trips_through_from_dict() -> None:
    table = ReservationTable()
    table.add("ab", "12:00", "13:00", agent_id="robot_a")
    table.add("b", "14:00:30", "14:05")
    payload = table.to_dict()
    reloaded = ReservationTable.from_dict(payload)
    assert len(reloaded) == 2
    assert reloaded.entries[0].resource_id == "ab"
    assert reloaded.entries[0].agent_id == "robot_a"
    assert reloaded.entries[1].resource_id == "b"
    assert reloaded.entries[1].agent_id is None
    assert reloaded.entries[1].start == time(14, 0, 30)


def test_to_dict_omits_agent_id_when_unset() -> None:
    table = ReservationTable()
    table.add("ab", "12:00", "13:00")
    payload = table.to_dict()
    assert "agent_id" not in payload["reservations"][0]


def test_load_reservations_yaml(tmp_path) -> None:
    p = tmp_path / "res.yaml"
    p.write_text(
        "version: 1\n"
        "reservations:\n"
        "  - {resource_id: ab, start: '12:00', end: '13:00', agent_id: robot_a}\n"
        "  - {resource_id: bd, start: '12:30', end: '12:45'}\n",
        encoding="utf-8",
    )
    table = load_reservations(p)
    assert len(table) == 2
    assert table.entries[0].agent_id == "robot_a"
    assert table.closed_at("12:30") == {"ab", "bd"}


def test_load_reservations_json(tmp_path) -> None:
    p = tmp_path / "res.json"
    p.write_text(
        json.dumps(
            {
                "version": 1,
                "reservations": [
                    {"resource_id": "ab", "start": "12:00", "end": "13:00"},
                ],
            }
        ),
        encoding="utf-8",
    )
    table = load_reservations(p)
    assert len(table) == 1


def test_load_reservations_missing_file(tmp_path) -> None:
    with pytest.raises(ReservationLoadError, match="not found"):
        load_reservations(tmp_path / "absent.yaml")


def test_load_reservations_unsupported_extension(tmp_path) -> None:
    p = tmp_path / "res.txt"
    p.write_text("nope", encoding="utf-8")
    with pytest.raises(ReservationLoadError, match="unsupported file extension"):
        load_reservations(p)


def test_load_reservations_wrong_schema_version(tmp_path) -> None:
    p = tmp_path / "res.yaml"
    p.write_text("version: 99\nreservations: []\n", encoding="utf-8")
    with pytest.raises(ReservationLoadError, match="schema version"):
        load_reservations(p)


def test_load_reservations_missing_required_key(tmp_path) -> None:
    p = tmp_path / "res.yaml"
    p.write_text(
        "version: 1\n"
        "reservations:\n"
        "  - {resource_id: ab, start: '12:00'}\n",  # missing end
        encoding="utf-8",
    )
    with pytest.raises(ReservationLoadError, match="'end'"):
        load_reservations(p)


def test_load_reservations_malformed_time(tmp_path) -> None:
    p = tmp_path / "res.yaml"
    p.write_text(
        "version: 1\n"
        "reservations:\n"
        "  - {resource_id: ab, start: 'not-a-time', end: '13:00'}\n",
        encoding="utf-8",
    )
    with pytest.raises(ReservationLoadError, match="invalid time"):
        load_reservations(p)


def test_load_reservations_rejects_non_string_resource_id(tmp_path) -> None:
    p = tmp_path / "res.yaml"
    p.write_text(
        "version: 1\n"
        "reservations:\n"
        "  - {resource_id: 42, start: '12:00', end: '13:00'}\n",
        encoding="utf-8",
    )
    with pytest.raises(ReservationLoadError, match="resource_id"):
        load_reservations(p)


def test_load_reservations_rejects_non_string_agent_id(tmp_path) -> None:
    p = tmp_path / "res.yaml"
    p.write_text(
        "version: 1\n"
        "reservations:\n"
        "  - {resource_id: ab, start: '12:00', end: '13:00', agent_id: 42}\n",
        encoding="utf-8",
    )
    with pytest.raises(ReservationLoadError, match="agent_id"):
        load_reservations(p)


# --------------------------- CLI integration ---------------------------


def _write_diamond_graph(path) -> None:
    path.write_text(
        """version: 1
metadata: {name: t}
nodes:
  - {id: a, label: A, type: room, pose: {x: 0, y: 0, yaw: 0, frame_id: map}}
  - {id: b, label: B, type: room, pose: {x: 1, y: 0, yaw: 0, frame_id: map}}
  - {id: c, label: C, type: room, pose: {x: 1, y: 1, yaw: 0, frame_id: map}}
  - {id: d, label: D, type: room, pose: {x: 2, y: 0, yaw: 0, frame_id: map}}
edges:
  - {id: ab, source: a, target: b, type: traversable, cost: 1.0}
  - {id: bd, source: b, target: d, type: traversable, cost: 1.0}
  - {id: ac, source: a, target: c, type: traversable, cost: 5.0}
  - {id: cd, source: c, target: d, type: traversable, cost: 5.0}
""",
        encoding="utf-8",
    )


def test_cli_reservations_reroute(tmp_path, capsys) -> None:
    yaml = tmp_path / "g.yaml"
    _write_diamond_graph(yaml)
    res = tmp_path / "res.yaml"
    res.write_text(
        "version: 1\n"
        "reservations:\n"
        "  - {resource_id: ab, start: '12:00', end: '13:00', agent_id: robot_a}\n",
        encoding="utf-8",
    )
    rc = cli_main(
        [
            "plan",
            str(yaml),
            "a",
            "d",
            "--reservations",
            str(res),
            "--at-time",
            "12:30",
            "--format",
            "json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["path"] == ["a", "c", "d"]


def test_cli_reservations_outside_window_uses_fast_route(tmp_path, capsys) -> None:
    yaml = tmp_path / "g.yaml"
    _write_diamond_graph(yaml)
    res = tmp_path / "res.yaml"
    res.write_text(
        "version: 1\n"
        "reservations:\n"
        "  - {resource_id: ab, start: '12:00', end: '13:00'}\n",
        encoding="utf-8",
    )
    rc = cli_main(
        [
            "plan",
            str(yaml),
            "a",
            "d",
            "--reservations",
            str(res),
            "--at-time",
            "13:30",
            "--format",
            "json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["path"] == ["a", "b", "d"]


def test_cli_reservations_requires_at_time(tmp_path, capsys) -> None:
    yaml = tmp_path / "g.yaml"
    _write_diamond_graph(yaml)
    res = tmp_path / "res.yaml"
    res.write_text(
        "version: 1\nreservations: []\n",
        encoding="utf-8",
    )
    rc = cli_main(["plan", str(yaml), "a", "d", "--reservations", str(res)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--at-time" in err


def test_cli_reservations_bad_file_reports_error(tmp_path, capsys) -> None:
    yaml = tmp_path / "g.yaml"
    _write_diamond_graph(yaml)
    rc = cli_main(
        [
            "plan",
            str(yaml),
            "a",
            "d",
            "--reservations",
            str(tmp_path / "missing.yaml"),
            "--at-time",
            "12:30",
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "reservation" in err.lower()
