"""Tests for the visit-history memory layer."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from semantic_toponav.graph import GraphBuilder
from semantic_toponav.graph.serialization import graph_from_dict, graph_to_dict
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode
from semantic_toponav.memory import (
    avoid_recently_visited,
    clear_history,
    last_visited,
    prefer_familiar,
    prefer_unvisited,
    record_path,
    record_visit,
    time_since_visit,
    visit_count,
)
from semantic_toponav.planner import compose_costs, plan_dijkstra

# ----------------------------- fixtures -----------------------------


def _line_graph() -> TopologyGraph:
    """a -- b -- c (each edge cost 1.0)."""
    return (
        GraphBuilder()
        .node("a", type="room", x=0, y=0)
        .node("b", type="room", x=1, y=0)
        .node("c", type="room", x=2, y=0)
        .connect("a", "b", "c")
        .build()
    )


def _diamond() -> TopologyGraph:
    """Two parallel routes a->b->d and a->c->d, both cost 2.0."""
    g = TopologyGraph()
    for nid in "abcd":
        g.add_node(TopologyNode(id=nid, label=nid, type="room", pose=Pose2D(0, 0)))
    g.add_edge(TopologyEdge(id="ab", source="a", target="b", type="traversable", cost=1.0))
    g.add_edge(TopologyEdge(id="bd", source="b", target="d", type="traversable", cost=1.0))
    g.add_edge(TopologyEdge(id="ac", source="a", target="c", type="traversable", cost=1.0))
    g.add_edge(TopologyEdge(id="cd", source="c", target="d", type="traversable", cost=1.0))
    return g


# ----------------------------- record_visit -----------------------------


def test_record_visit_sets_count_and_timestamp() -> None:
    g = _line_graph()
    ts = record_visit(g, "a", now=1000.0)
    assert ts == 1000.0
    assert visit_count(g, "a") == 1
    assert last_visited(g, "a") == 1000.0


def test_record_visit_increments_count() -> None:
    g = _line_graph()
    record_visit(g, "a", now=1000.0)
    record_visit(g, "a", now=1100.0)
    record_visit(g, "a", now=1200.0)
    assert visit_count(g, "a") == 3
    assert last_visited(g, "a") == 1200.0


def test_unvisited_node_returns_defaults() -> None:
    g = _line_graph()
    assert visit_count(g, "a") == 0
    assert last_visited(g, "a") is None
    assert time_since_visit(g, "a", now=1000.0) is None


def test_time_since_visit() -> None:
    g = _line_graph()
    record_visit(g, "a", now=1000.0)
    assert time_since_visit(g, "a", now=1050.0) == 50.0


def test_record_visit_uses_wall_clock_by_default() -> None:
    g = _line_graph()
    ts = record_visit(g, "a")
    assert ts > 0
    assert last_visited(g, "a") == ts


def test_record_visit_unknown_node_raises() -> None:
    g = _line_graph()
    with pytest.raises(KeyError):
        record_visit(g, "missing", now=0.0)


# ----------------------------- record_path -----------------------------


def test_record_path_writes_all_nodes_with_same_timestamp() -> None:
    g = _line_graph()
    record_path(g, ["a", "b", "c"], now=2000.0)
    for nid in "abc":
        assert visit_count(g, nid) == 1
        assert last_visited(g, nid) == 2000.0


def test_record_path_repeats_increment_revisited_nodes() -> None:
    g = _line_graph()
    record_path(g, ["a", "b"], now=1000.0)
    record_path(g, ["b", "c"], now=1100.0)
    assert visit_count(g, "a") == 1
    assert visit_count(g, "b") == 2
    assert visit_count(g, "c") == 1
    assert last_visited(g, "b") == 1100.0


# ----------------------------- clear_history -----------------------------


def test_clear_history_all_nodes() -> None:
    g = _line_graph()
    record_path(g, ["a", "b", "c"], now=1000.0)
    clear_history(g)
    for nid in "abc":
        assert visit_count(g, nid) == 0
        assert last_visited(g, nid) is None


def test_clear_history_subset() -> None:
    g = _line_graph()
    record_path(g, ["a", "b", "c"], now=1000.0)
    clear_history(g, ["a"])
    assert visit_count(g, "a") == 0
    assert visit_count(g, "b") == 1
    assert visit_count(g, "c") == 1


def test_clear_history_is_idempotent() -> None:
    g = _line_graph()
    clear_history(g)
    clear_history(g)
    assert visit_count(g, "a") == 0


# ----------------------------- custom property keys -----------------------------


def test_record_visit_respects_custom_keys() -> None:
    g = _line_graph()
    record_visit(
        g, "a",
        now=1000.0,
        count_key="my_count",
        timestamp_key="my_ts",
    )
    assert g.get_node("a").properties["my_count"] == 1
    assert g.get_node("a").properties["my_ts"] == 1000.0
    # Default key getters see nothing.
    assert visit_count(g, "a") == 0


# ----------------------------- serialization round-trip -----------------------------


def test_history_round_trips_through_dict() -> None:
    g = _line_graph()
    record_path(g, ["a", "b"], now=1234.5)
    payload = graph_to_dict(g)
    g2 = graph_from_dict(payload)
    assert visit_count(g2, "a") == 1
    assert last_visited(g2, "b") == 1234.5


def test_history_round_trips_through_yaml(tmp_path: Path) -> None:
    yaml = pytest.importorskip("yaml")  # noqa: F841
    from semantic_toponav.graph.serialization import load_graph, save_graph

    g = _line_graph()
    record_path(g, ["a", "c"], now=42.0)
    out = tmp_path / "g.yaml"
    save_graph(g, out)
    g2 = load_graph(out)
    assert visit_count(g2, "a") == 1
    assert visit_count(g2, "b") == 0
    assert last_visited(g2, "c") == 42.0


# ----------------------------- prefer_unvisited -----------------------------


def test_prefer_unvisited_steers_planner_to_new_branch() -> None:
    g = _diamond()
    # Default: ties, planner picks an arbitrary (but deterministic) path of length 3.
    base = plan_dijkstra(g, "a", "d")
    assert len(base) == 3
    # Walking via b first makes the b-branch "visited".
    record_visit(g, "b", now=1000.0)
    # The unvisited branch (c) should now be preferred.
    path = plan_dijkstra(g, "a", "d", cost_fn=prefer_unvisited(g))
    assert path == ["a", "c", "d"]


def test_prefer_unvisited_default_multiplier_is_two() -> None:
    g = _diamond()
    record_visit(g, "b", now=1000.0)
    cost = prefer_unvisited(g)
    assert math.isclose(cost(g.get_edge("ab")), 2.0)
    assert math.isclose(cost(g.get_edge("ac")), 1.0)


# ----------------------------- prefer_familiar -----------------------------


def test_prefer_familiar_retraces_known_route() -> None:
    g = _diamond()
    record_path(g, ["b", "d"], now=1000.0)
    path = plan_dijkstra(g, "a", "d", cost_fn=prefer_familiar(g))
    assert path == ["a", "b", "d"]


def test_prefer_familiar_default_multiplier_is_half() -> None:
    g = _diamond()
    record_visit(g, "b", now=1000.0)
    cost = prefer_familiar(g)
    assert math.isclose(cost(g.get_edge("ab")), 0.5)
    assert math.isclose(cost(g.get_edge("ac")), 1.0)


# ----------------------------- avoid_recently_visited -----------------------------


def test_avoid_recently_visited_penalizes_inside_window() -> None:
    g = _diamond()
    record_visit(g, "b", now=900.0)
    cost = avoid_recently_visited(g, within_seconds=60.0, now=950.0)
    assert math.isclose(cost(g.get_edge("ab")), 5.0)  # default multiplier 5
    assert math.isclose(cost(g.get_edge("ac")), 1.0)


def test_avoid_recently_visited_ignores_old_visits() -> None:
    g = _diamond()
    record_visit(g, "b", now=100.0)
    cost = avoid_recently_visited(g, within_seconds=60.0, now=1000.0)
    assert math.isclose(cost(g.get_edge("ab")), 1.0)


def test_avoid_recently_visited_reroutes_planner() -> None:
    g = _diamond()
    record_path(g, ["a", "b", "d"], now=1000.0)
    cost = avoid_recently_visited(g, within_seconds=60.0, now=1010.0)
    path = plan_dijkstra(g, "a", "d", cost_fn=cost)
    assert path == ["a", "c", "d"]


def test_avoid_recently_visited_unvisited_nodes_unaffected() -> None:
    g = _diamond()
    cost = avoid_recently_visited(g, within_seconds=60.0, now=1000.0)
    for e in g.edges():
        assert math.isclose(cost(e), e.cost)


# ----------------------------- compose -----------------------------


def test_compose_with_other_cost_functions() -> None:
    g = _diamond()
    # Make b "visited recently" — composing prefer_unvisited with a graph-blind
    # default cost shouldn't change anything for the unvisited branch.
    record_visit(g, "b", now=1000.0)
    composed = compose_costs(prefer_unvisited(g))
    assert math.isclose(composed(g.get_edge("ab")), 2.0)
    assert math.isclose(composed(g.get_edge("ac")), 1.0)


def test_compose_unvisited_with_recent_penalty() -> None:
    g = _diamond()
    record_visit(g, "b", now=1000.0)
    cost = compose_costs(
        prefer_unvisited(g, visited_multiplier=2.0),
        avoid_recently_visited(g, within_seconds=60.0, recent_multiplier=3.0, now=1010.0),
    )
    # Visited + recent → 2 * 3 = 6 * 1.0 base
    assert math.isclose(cost(g.get_edge("ab")), 6.0)
    assert math.isclose(cost(g.get_edge("ac")), 1.0)
