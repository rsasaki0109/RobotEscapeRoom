"""Tests for the pyvis-backed interactive web visualization.

Gated on `pyvis` so CI without the `viz_web` extra cleanly skips the file.
We assert structural things in the generated HTML rather than diff-ing
the literal bytes (pyvis is free to evolve its template).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pyvis")

from semantic_toponav.graph.serialization import load_graph  # noqa: E402
from semantic_toponav.graph.topology_graph import TopologyGraph  # noqa: E402
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode  # noqa: E402
from semantic_toponav.visualization import (  # noqa: E402
    graph_html,
    save_interactive_html,
    to_pyvis_network,
)

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"


def _small_graph() -> TopologyGraph:
    g = TopologyGraph()
    g.add_node(
        TopologyNode(id="a", label="Lobby", type="room", pose=Pose2D(0.0, 0.0))
    )
    g.add_node(
        TopologyNode(id="b", label="Hall", type="corridor", pose=Pose2D(2.0, 0.0))
    )
    g.add_node(
        TopologyNode(id="c", label="Stairs", type="stairs", pose=Pose2D(2.0, 2.0))
    )
    g.add_edge(
        TopologyEdge(id="ab", source="a", target="b", type="traversable", cost=1.0)
    )
    g.add_edge(
        TopologyEdge(id="bc", source="b", target="c", type="stairs_up", cost=2.0)
    )
    return g


# ----------------------------- pyvis network -----------------------------


def test_to_pyvis_network_carries_all_nodes_and_edges() -> None:
    g = _small_graph()
    net = to_pyvis_network(g)
    node_ids = {n["id"] for n in net.nodes}
    assert node_ids == {"a", "b", "c"}
    assert len(net.edges) == 2


def test_pose_layout_pins_nodes_and_flips_y() -> None:
    g = _small_graph()
    net = to_pyvis_network(g)
    by_id = {n["id"]: n for n in net.nodes}
    # Node `c` lives at world (2, 2). After flipping, y in pyvis is negative.
    assert by_id["c"]["x"] == 2.0 * 50.0
    assert by_id["c"]["y"] == -2.0 * 50.0
    # Pinned nodes have `physics=False`.
    assert by_id["a"]["physics"] is False


def test_unposed_node_skips_coords() -> None:
    g = _small_graph()
    g.add_node(TopologyNode(id="d", label="virtual", type="intersection"))
    net = to_pyvis_network(g)
    by_id = {n["id"]: n for n in net.nodes}
    assert "x" not in by_id["d"]
    assert "y" not in by_id["d"]


def test_path_highlight_recolors_nodes_and_edges() -> None:
    g = _small_graph()
    net = to_pyvis_network(g, path=["a", "b", "c"])
    by_id = {n["id"]: n for n in net.nodes}
    # Path color (#e377c2) applied to all path nodes.
    for nid in ("a", "b", "c"):
        assert by_id[nid]["color"] == "#e377c2"
    # Both edges sit on the path, so both get the path color and width.
    for e in net.edges:
        assert e["color"] == "#e377c2"
        assert e["width"] == 4.0


def test_partial_path_only_highlights_in_segment() -> None:
    g = _small_graph()
    net = to_pyvis_network(g, path=["a", "b"])
    by_id = {n["id"]: n for n in net.nodes}
    assert by_id["a"]["color"] == "#e377c2"
    assert by_id["b"]["color"] == "#e377c2"
    # `c` is *not* on the path, keeps its semantic color.
    assert by_id["c"]["color"] != "#e377c2"
    # Only the ab edge is highlighted; bc reverts to its type color.
    by_edge = {(e["from"], e["to"]): e for e in net.edges}
    ab = by_edge.get(("a", "b")) or by_edge.get(("b", "a"))
    bc = by_edge.get(("b", "c")) or by_edge.get(("c", "b"))
    assert ab["color"] == "#e377c2"
    assert bc["color"] != "#e377c2"


def test_unknown_node_type_uses_default_color() -> None:
    g = TopologyGraph()
    g.add_node(
        TopologyNode(id="x", label="x", type="mystery", pose=Pose2D(0.0, 0.0))
    )
    net = to_pyvis_network(g)
    assert net.nodes[0]["color"] == "#1f77b4"


# ----------------------------- HTML generation -----------------------------


def test_graph_html_contains_node_labels() -> None:
    g = _small_graph()
    html = graph_html(g)
    assert "Lobby" in html
    assert "Hall" in html
    assert "Stairs" in html
    # The pyvis runtime is bundled inline as a vis.js network.
    assert "vis-network" in html or "DataSet" in html


def test_save_interactive_html_writes_file(tmp_path: Path) -> None:
    g = _small_graph()
    out = save_interactive_html(g, tmp_path / "viewer.html")
    assert out.exists()
    contents = out.read_text(encoding="utf-8")
    assert contents.startswith("<")
    assert "Lobby" in contents


def test_save_interactive_html_creates_parent_dirs(tmp_path: Path) -> None:
    g = _small_graph()
    out = save_interactive_html(g, tmp_path / "deep" / "nested" / "viewer.html")
    assert out.exists()


# -------------------------- with bundled example --------------------------


def test_round_trip_with_multi_floor_example(tmp_path: Path) -> None:
    """The bundled multi-floor demo should produce a non-empty viewer with
    every node and a highlighted path."""
    graph = load_graph(EXAMPLES_DIR / "multi_floor_office.yaml")
    path = ["entrance", "corridor_1f", "elevator_1f"]
    # Sanity: path nodes exist in the example.
    for nid in path:
        graph.get_node(nid)

    out = save_interactive_html(graph, tmp_path / "multi.html", path=path)
    html = out.read_text(encoding="utf-8")
    for nid in graph.node_ids():
        assert nid in html
