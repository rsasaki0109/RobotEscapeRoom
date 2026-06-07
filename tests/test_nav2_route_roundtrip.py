"""Nav2 Route Server GeoJSON reader / round-trip tests.

The exporter is verified in ``test_nav2_route_export.py``; this file
verifies its inverse — :func:`nav2_geojson_to_topology` /
:func:`read_nav2_geojson` — reads a FeatureCollection back the way Nav2's
``GeoJsonGraphFileLoader`` does, and that a graph survives the export →
read round trip:

* **lossless** (``recombine_bidirectional=True``): the two directed halves
  of a bidirectional edge recombine, so export → read → export is
  idempotent — a fidelity check on the handoff;
* **Nav2-faithful** (``recombine_bidirectional=False``): every LineString
  stays a directed edge (what Nav2 actually materializes), and *replanning*
  over the read-back graph yields the same route — proving Nav2 plans what
  we planned.

See :mod:`semantic_toponav.conversion.nav2_route`.
"""

from __future__ import annotations

import pytest

from semantic_toponav.conversion.nav2_route import (
    Nav2GeoJsonError,
    nav2_geojson_to_topology,
    read_nav2_geojson,
    topology_to_nav2_geojson,
    write_nav2_geojson,
)
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode
from semantic_toponav.planner import compose_costs, plan_astar, prefer_elevator


def _graph() -> TopologyGraph:
    g = TopologyGraph()
    g.add_node(TopologyNode(
        id="lobby", label="Lobby", type="intersection",
        pose=Pose2D(0.0, 0.0), properties={"floor": 1},
    ))
    g.add_node(TopologyNode(
        id="kitchen", label="Kitchen", type="room",
        pose=Pose2D(3.0, 4.0), properties={"floor": 1, "embedding": [0.1, 0.2]},
    ))
    g.add_node(TopologyNode(
        id="elevator", label="Elevator", type="elevator", pose=Pose2D(0.0, 5.0),
    ))
    g.add_edge(TopologyEdge(
        id="e_lobby_kitchen", source="lobby", target="kitchen",
        type="traversable", cost=2.5, bidirectional=True,
    ))
    g.add_edge(TopologyEdge(
        id="e_lobby_elevator", source="lobby", target="elevator",
        type="elevator_link", cost=1.0, bidirectional=False,
    ))
    return g


def _edge_set(g: TopologyGraph) -> set[tuple]:
    """Direction-agnostic edge signatures for comparing two graphs."""
    out = set()
    for e in g.edges():
        ends = frozenset((e.source, e.target)) if e.bidirectional else (e.source, e.target)
        out.add((ends, e.bidirectional, round(e.cost, 6), e.type))
    return out


def test_reads_nodes_with_string_id_label_class_and_pose() -> None:
    fc = topology_to_nav2_geojson(_graph())
    g = nav2_geojson_to_topology(fc)
    kitchen = g.get_node("kitchen")
    assert kitchen.label == "Kitchen"
    assert kitchen.type == "room"            # restored from metadata.class
    assert kitchen.pose is not None
    assert (kitchen.pose.x, kitchen.pose.y) == (3.0, 4.0)
    assert kitchen.properties["floor"] == 1
    # The synthesized metadata keys do not leak back into properties.
    assert "node_id" not in kitchen.properties
    assert "label" not in kitchen.properties
    assert "class" not in kitchen.properties


def test_lossless_roundtrip_recombines_bidirectional() -> None:
    g = _graph()
    back = nav2_geojson_to_topology(topology_to_nav2_geojson(g))
    assert set(back.node_ids()) == set(g.node_ids())
    # One bidirectional + one directed survive as such (not 3 directed edges).
    assert _edge_set(back) == _edge_set(g)
    bidir = [e for e in back.edges() if e.bidirectional]
    assert {e.source for e in bidir} | {e.target for e in bidir} == {"lobby", "kitchen"}


def test_export_read_export_is_idempotent() -> None:
    g = _graph()
    fc1 = topology_to_nav2_geojson(g)
    fc2 = topology_to_nav2_geojson(nav2_geojson_to_topology(fc1))
    assert fc2 == fc1  # the handoff loses nothing the format can carry


def test_nav2_faithful_keeps_directed_edges() -> None:
    g = _graph()
    directed = nav2_geojson_to_topology(
        topology_to_nav2_geojson(g), recombine_bidirectional=False
    )
    # bidirectional lobby↔kitchen → 2 directed; lobby→elevator → 1 = 3 total.
    edges = list(directed.edges())
    assert len(edges) == 3
    assert all(not e.bidirectional for e in edges)
    # Unique edge ids despite the two halves sharing one metadata.edge_id.
    assert len({e.id for e in edges}) == 3


def test_replanning_over_readback_yields_same_route(tmp_path) -> None:
    g = load_office()
    start, goal = "entrance", "exec_office_3f"
    route = plan_astar(g, start, goal, cost_fn=compose_costs(prefer_elevator))

    path = write_nav2_geojson(g, tmp_path / "route.geojson", node_ids=set(route))
    # Nav2 reads directed edges; semantic `class` survives, so the same
    # elevator-preferring cost shaping replans the identical sequence.
    readback = read_nav2_geojson(path, recombine_bidirectional=False)
    replanned = plan_astar(readback, start, goal, cost_fn=compose_costs(prefer_elevator))
    assert replanned == route


def test_write_then_read_roundtrips_on_disk(tmp_path) -> None:
    g = _graph()
    path = write_nav2_geojson(g, tmp_path / "g.geojson")
    back = read_nav2_geojson(path)
    assert set(back.node_ids()) == set(g.node_ids())
    assert _edge_set(back) == _edge_set(g)


def test_hand_authored_graph_without_node_id_metadata_loads() -> None:
    # A third-party Nav2 graph: integer ids, no metadata.node_id.
    fc = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": {"id": 0},
             "geometry": {"type": "Point", "coordinates": [0.0, 0.0]}},
            {"type": "Feature", "properties": {"id": 1},
             "geometry": {"type": "Point", "coordinates": [1.0, 0.0]}},
            {"type": "Feature",
             "properties": {"id": 2, "startid": 0, "endid": 1, "cost": 1.0},
             "geometry": {"type": "LineString", "coordinates": [[0.0, 0.0], [1.0, 0.0]]}},
        ],
    }
    g = nav2_geojson_to_topology(fc)
    assert set(g.node_ids()) == {"0", "1"}          # int id stringified
    assert len(list(g.edges())) == 1


def test_malformed_collections_raise() -> None:
    with pytest.raises(Nav2GeoJsonError):
        nav2_geojson_to_topology({"type": "NotAFeatureCollection"})
    with pytest.raises(Nav2GeoJsonError):
        # edge references a node id with no Point feature
        nav2_geojson_to_topology({
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"id": 5, "startid": 0, "endid": 99, "cost": 1.0},
                "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
            }],
        })


def load_office() -> TopologyGraph:
    from pathlib import Path

    from semantic_toponav.graph.serialization import load_graph

    root = Path(__file__).parent.parent
    return load_graph(str(root / "examples" / "multi_floor_office.yaml"))
