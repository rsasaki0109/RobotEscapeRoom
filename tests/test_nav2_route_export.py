"""TopologyGraph → Nav2 Route Server GeoJSON exporter tests.

Verifies the serialized FeatureCollection matches what Nav2's
``GeoJsonGraphFileLoader`` parses: Point nodes with integer ids + metadata,
directed LineString edges with ``startid`` / ``endid`` / ``cost``,
bidirectional edges split into two directed features, and pose-less nodes
rejected. See :mod:`semantic_toponav.conversion.nav2_route`.
"""

from __future__ import annotations

import json

import pytest

from semantic_toponav.conversion.nav2_route import (
    topology_to_nav2_geojson,
    write_nav2_geojson,
)
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode


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


def _nodes(fc):
    return [f for f in fc["features"] if f["geometry"]["type"] == "Point"]


def _edges(fc):
    return [f for f in fc["features"] if f["geometry"]["type"] == "LineString"]


def test_feature_collection_shape() -> None:
    fc = topology_to_nav2_geojson(_graph())
    assert fc["type"] == "FeatureCollection"
    assert len(_nodes(fc)) == 3
    # one bidirectional (→ 2 directed) + one directed = 3 edge features.
    assert len(_edges(fc)) == 3


def test_nodes_have_integer_ids_coords_and_metadata() -> None:
    fc = topology_to_nav2_geojson(_graph())
    by_label = {n["properties"]["metadata"]["node_id"]: n for n in _nodes(fc)}
    kitchen = by_label["kitchen"]
    assert isinstance(kitchen["properties"]["id"], int)
    assert kitchen["geometry"]["coordinates"] == [3.0, 4.0]  # [x, y] metres
    meta = kitchen["properties"]["metadata"]
    assert meta["class"] == "room"          # SemanticScorer reads `class`
    assert meta["label"] == "Kitchen"
    assert meta["floor"] == 1
    assert "embedding" not in meta          # vectors are stripped


def test_node_ids_are_unique_and_referenced_by_edges() -> None:
    fc = topology_to_nav2_geojson(_graph())
    node_ids = {n["properties"]["id"] for n in _nodes(fc)}
    assert len(node_ids) == len(_nodes(fc))
    for e in _edges(fc):
        assert e["properties"]["startid"] in node_ids
        assert e["properties"]["endid"] in node_ids
    # node and edge id ranges are disjoint.
    edge_ids = {e["properties"]["id"] for e in _edges(fc)}
    assert node_ids.isdisjoint(edge_ids)


def test_bidirectional_edge_becomes_two_directed_features() -> None:
    fc = topology_to_nav2_geojson(_graph())
    lk = [e for e in _edges(fc)
          if e["properties"]["metadata"]["edge_id"] == "e_lobby_kitchen"]
    assert len(lk) == 2
    pairs = {(e["properties"]["startid"], e["properties"]["endid"]) for e in lk}
    a, b = next(iter(pairs))
    assert (b, a) in pairs  # the swapped direction is present
    assert all(e["properties"]["cost"] == 2.5 for e in lk)


def test_directed_edge_stays_single() -> None:
    fc = topology_to_nav2_geojson(_graph())
    le = [e for e in _edges(fc)
          if e["properties"]["metadata"]["edge_id"] == "e_lobby_elevator"]
    assert len(le) == 1


def test_poseless_node_raises() -> None:
    g = _graph()
    g.add_node(TopologyNode(id="ghost", label="Ghost", type="room", pose=None))
    g.add_edge(TopologyEdge(
        id="e", source="lobby", target="ghost", type="traversable",
    ))
    with pytest.raises(ValueError, match="no pose"):
        topology_to_nav2_geojson(g)


def test_node_ids_subset_filters_nodes_and_edges() -> None:
    fc = topology_to_nav2_geojson(_graph(), node_ids={"lobby", "kitchen"})
    assert {n["properties"]["metadata"]["node_id"] for n in _nodes(fc)} == {
        "lobby", "kitchen",
    }
    # the elevator edge is dropped (its endpoint is outside the subset).
    for e in _edges(fc):
        assert e["properties"]["metadata"]["edge_id"] == "e_lobby_kitchen"


def test_custom_route_frame_when_pose_frame_blank() -> None:
    g = TopologyGraph()
    g.add_node(TopologyNode(
        id="n", label="N", type="room", pose=Pose2D(1.0, 2.0, frame_id=""),
    ))
    fc = topology_to_nav2_geojson(g, route_frame="odom")
    assert _nodes(fc)[0]["properties"]["frame"] == "odom"


def test_write_roundtrips_valid_json(tmp_path) -> None:
    out = write_nav2_geojson(_graph(), tmp_path / "graph.geojson")
    assert out.exists()
    loaded = json.loads(out.read_text())
    assert loaded["type"] == "FeatureCollection"
    assert len(loaded["features"]) == 6  # 3 nodes + 3 directed edges
