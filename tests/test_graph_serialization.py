"""Tests for graph construction, validation, and YAML/JSON round-trip."""

from __future__ import annotations

from pathlib import Path

import pytest

from semantic_toponav.graph.serialization import (
    GraphLoadError,
    graph_from_dict,
    graph_to_dict,
    load_graph,
    save_graph,
)
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import (
    GraphValidationError,
    Pose2D,
    TopologyEdge,
    TopologyNode,
)

EXAMPLE_YAML = Path(__file__).resolve().parents[1] / "examples" / "indoor_office.yaml"
EXAMPLE_JSON = Path(__file__).resolve().parents[1] / "examples" / "indoor_office.json"


def _build_tiny_graph() -> TopologyGraph:
    g = TopologyGraph()
    g.add_node(TopologyNode(id="a", label="A", type="room", pose=Pose2D(0.0, 0.0)))
    g.add_node(TopologyNode(id="b", label="B", type="corridor", pose=Pose2D(1.0, 0.0)))
    g.add_node(TopologyNode(id="c", label="C", type="room", pose=Pose2D(2.0, 0.0)))
    g.add_edge(TopologyEdge(id="ab", source="a", target="b", type="traversable"))
    g.add_edge(TopologyEdge(id="bc", source="b", target="c", type="traversable"))
    return g


def test_add_node_and_edge() -> None:
    g = _build_tiny_graph()
    assert g.has_node("a")
    assert g.has_edge("ab")
    assert {e.id for e in g.neighbors("b")} == {"ab", "bc"}


def test_duplicate_node_id_raises() -> None:
    g = _build_tiny_graph()
    with pytest.raises(GraphValidationError):
        g.add_node(TopologyNode(id="a", label="A2", type="room"))


def test_duplicate_edge_id_raises() -> None:
    g = _build_tiny_graph()
    with pytest.raises(GraphValidationError):
        g.add_edge(TopologyEdge(id="ab", source="a", target="b", type="traversable"))


def test_edge_missing_source_raises() -> None:
    g = _build_tiny_graph()
    with pytest.raises(GraphValidationError):
        g.add_edge(TopologyEdge(id="zx", source="z", target="a", type="traversable"))


def test_edge_missing_target_raises() -> None:
    g = _build_tiny_graph()
    with pytest.raises(GraphValidationError):
        g.add_edge(TopologyEdge(id="az", source="a", target="z", type="traversable"))


def test_negative_cost_raises() -> None:
    g = _build_tiny_graph()
    with pytest.raises(GraphValidationError):
        g.add_edge(
            TopologyEdge(id="neg", source="a", target="b", type="traversable", cost=-1.0)
        )


def test_one_way_edge_neighbors() -> None:
    g = TopologyGraph()
    g.add_node(TopologyNode(id="a", label="A", type="room"))
    g.add_node(TopologyNode(id="b", label="B", type="room"))
    g.add_edge(
        TopologyEdge(id="ab", source="a", target="b", type="one_way", bidirectional=False)
    )
    assert [e.id for e in g.neighbors("a")] == ["ab"]
    assert g.neighbors("b") == []


def test_dict_roundtrip() -> None:
    g = _build_tiny_graph()
    data = graph_to_dict(g)
    g2 = graph_from_dict(data)
    assert g2.node_ids() == g.node_ids()
    assert g2.edge_ids() == g.edge_ids()


def test_load_yaml_example() -> None:
    g = load_graph(EXAMPLE_YAML)
    assert "entrance" in g.node_ids()
    assert "office_2f" in g.node_ids()
    g.validate()


def test_load_json_example() -> None:
    g = load_graph(EXAMPLE_JSON)
    assert "entrance" in g.node_ids()
    g.validate()


def test_yaml_roundtrip(tmp_path: Path) -> None:
    g = _build_tiny_graph()
    target = tmp_path / "graph.yaml"
    save_graph(g, target)
    g2 = load_graph(target)
    assert g2.node_ids() == g.node_ids()
    assert g2.edge_ids() == g.edge_ids()


def test_json_roundtrip(tmp_path: Path) -> None:
    g = _build_tiny_graph()
    target = tmp_path / "graph.json"
    save_graph(g, target)
    g2 = load_graph(target)
    assert g2.node_ids() == g.node_ids()
    assert g2.edge_ids() == g.edge_ids()


def test_unsupported_extension_raises(tmp_path: Path) -> None:
    bogus = tmp_path / "graph.txt"
    bogus.write_text("nope")
    with pytest.raises(GraphLoadError):
        load_graph(bogus)


def test_unknown_schema_version_raises() -> None:
    with pytest.raises(GraphLoadError):
        graph_from_dict({"version": 99, "nodes": [], "edges": []})


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(GraphLoadError):
        load_graph(tmp_path / "does_not_exist.yaml")
