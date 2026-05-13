"""Smoke tests for the matplotlib visualization helper.

These tests are skipped when matplotlib is not installed. They use the Agg
backend so no display is required.
"""

from __future__ import annotations

from pathlib import Path

import pytest

matplotlib = pytest.importorskip("matplotlib")
matplotlib.use("Agg")

from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode
from semantic_toponav.visualization.plot import MissingPoseError, plot_graph

EXAMPLE_YAML = Path(__file__).resolve().parents[1] / "examples" / "indoor_office.yaml"


def test_plot_indoor_office_runs() -> None:
    g = load_graph(EXAMPLE_YAML)
    fig, ax = plot_graph(g, title="indoor office")
    try:
        assert fig is not None
        assert ax is not None
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)


def test_plot_with_path(tmp_path) -> None:
    g = load_graph(EXAMPLE_YAML)
    path = ["entrance", "corridor_main", "lobby_intersection", "meeting_room"]
    out = tmp_path / "fig.png"
    fig, _ = plot_graph(g, path=path, save_path=str(out))
    try:
        assert out.exists()
        assert out.stat().st_size > 0
    finally:
        import matplotlib.pyplot as plt

        plt.close(fig)


def test_plot_raises_when_node_has_no_pose() -> None:
    g = TopologyGraph()
    g.add_node(TopologyNode(id="a", label="A", type="room", pose=Pose2D(0, 0)))
    g.add_node(TopologyNode(id="b", label="B", type="room"))  # no pose
    g.add_edge(TopologyEdge(id="ab", source="a", target="b", type="traversable"))
    with pytest.raises(MissingPoseError):
        plot_graph(g)
