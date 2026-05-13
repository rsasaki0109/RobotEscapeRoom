"""Matplotlib visualization for TopologyGraph and planned paths.

Imported lazily so that the core package has no hard dependency on matplotlib.
Install with ``pip install 'semantic-toponav[viz]'`` to use these helpers.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import TopologyNode

# Colors per semantic node type. Anything unknown falls through to the default.
_NODE_COLORS: dict[str, str] = {
    "entrance": "#2ca02c",
    "room": "#1f77b4",
    "corridor": "#7f7f7f",
    "intersection": "#9467bd",
    "elevator": "#ff7f0e",
    "stairs": "#d62728",
}
_DEFAULT_NODE_COLOR = "#1f77b4"

# Linestyles per edge type. Unknown edge types fall back to a solid line.
_EDGE_STYLE: dict[str, dict[str, Any]] = {
    "traversable": {"linestyle": "-", "color": "#888888", "linewidth": 1.2},
    "stairs_up": {"linestyle": "--", "color": "#d62728", "linewidth": 1.8},
    "stairs_down": {"linestyle": "--", "color": "#d62728", "linewidth": 1.8},
    "elevator_connection": {"linestyle": ":", "color": "#ff7f0e", "linewidth": 2.0},
    "restricted": {"linestyle": "-.", "color": "#aa0000", "linewidth": 1.6},
    "one_way": {"linestyle": "-", "color": "#444444", "linewidth": 1.2},
}
_DEFAULT_EDGE_STYLE: dict[str, Any] = {"linestyle": "-", "color": "#888888", "linewidth": 1.2}

PATH_COLOR = "#e377c2"
PATH_WIDTH = 3.5


class MissingPoseError(ValueError):
    """Raised when a node has no pose and cannot be plotted."""


def _require_pose(node: TopologyNode) -> tuple[float, float]:
    if node.pose is None:
        raise MissingPoseError(
            f"node {node.id!r} has no pose; cannot plot. Add `pose` to all nodes "
            "you intend to visualize."
        )
    return node.pose.x, node.pose.y


def _display_xy(
    node: TopologyNode, *, floor_offset: float, floor_property: str
) -> tuple[float, float]:
    """Apply optional vertical offset based on the node's floor property."""
    x, y = _require_pose(node)
    if floor_offset:
        floor = node.properties.get(floor_property)
        if floor is not None:
            try:
                y = y + float(int(floor)) * floor_offset
            except (TypeError, ValueError):
                pass
    return x, y


def plot_graph(
    graph: TopologyGraph,
    *,
    path: Iterable[str] | None = None,
    title: str | None = None,
    ax: Any | None = None,
    show_labels: bool = True,
    show_edge_ids: bool = False,
    save_path: str | None = None,
    show: bool = False,
    occupancy_grid: Any = None,
    resolution: float = 1.0,
    origin: tuple[float, float] = (0.0, 0.0),
    floor_offset: float = 0.0,
    floor_property: str = "floor",
):
    """Render a TopologyGraph and optionally overlay a planned path.

    Returns the matplotlib ``Figure`` and ``Axes`` so callers can further
    customize. Requires matplotlib at call time, not at import time.
    """
    import matplotlib.pyplot as plt  # local import keeps core dep-free

    fig = None
    if ax is None:
        fig, ax = plt.subplots(figsize=(10, 7))
    else:
        fig = ax.figure

    if occupancy_grid is not None:
        import numpy as np

        arr = np.asarray(occupancy_grid)
        if arr.ndim != 2:
            raise ValueError(
                f"occupancy_grid must be 2D, got shape {arr.shape}"
            )
        h, w = arr.shape
        # Treat input as a "traversability" array: higher = more free.
        # Matches topology_from_occupancy's free_threshold semantics.
        # cmap="gray" maps 0 -> black, 1 -> white, so walls render dark and
        # free space renders light.
        if arr.dtype == bool:
            display = arr.astype(float)
        else:
            display = np.clip(arr.astype(float), 0.0, 1.0)
        extent = (
            origin[0],
            origin[0] + w * resolution,
            origin[1],
            origin[1] + h * resolution,
        )
        ax.imshow(
            display,
            cmap="gray",
            extent=extent,
            origin="lower",
            alpha=0.85,
            zorder=0,
            interpolation="nearest",
        )

    # Edges first so node markers draw on top.
    for edge in graph.edges():
        src = graph.get_node(edge.source)
        tgt = graph.get_node(edge.target)
        x0, y0 = _display_xy(src, floor_offset=floor_offset, floor_property=floor_property)
        x1, y1 = _display_xy(tgt, floor_offset=floor_offset, floor_property=floor_property)
        style = _EDGE_STYLE.get(edge.type, _DEFAULT_EDGE_STYLE)
        ax.plot([x0, x1], [y0, y1], zorder=1, **style)
        if show_edge_ids:
            ax.text(
                (x0 + x1) / 2,
                (y0 + y1) / 2,
                edge.id,
                fontsize=7,
                color="#555555",
                zorder=2,
            )

    # Highlighted path.
    if path is not None:
        path_list = list(path)
        for a, b in zip(path_list, path_list[1:], strict=False):
            na = graph.get_node(a)
            nb = graph.get_node(b)
            x0, y0 = _display_xy(na, floor_offset=floor_offset, floor_property=floor_property)
            x1, y1 = _display_xy(nb, floor_offset=floor_offset, floor_property=floor_property)
            ax.plot(
                [x0, x1],
                [y0, y1],
                color=PATH_COLOR,
                linewidth=PATH_WIDTH,
                solid_capstyle="round",
                alpha=0.85,
                zorder=3,
            )

    # Nodes.
    for node in graph.nodes():
        x, y = _display_xy(node, floor_offset=floor_offset, floor_property=floor_property)
        color = _NODE_COLORS.get(node.type, _DEFAULT_NODE_COLOR)
        ax.scatter([x], [y], s=120, c=color, edgecolors="black", linewidths=0.6, zorder=4)
        if show_labels:
            ax.text(
                x + 0.15,
                y + 0.15,
                node.label or node.id,
                fontsize=8,
                zorder=5,
            )

    _add_legend(ax, graph)

    if title is not None:
        ax.set_title(title)
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    ax.set_aspect("equal", adjustable="datalim")
    ax.grid(True, alpha=0.3)

    if save_path is not None:
        fig.tight_layout()
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
    if show:
        plt.show()

    return fig, ax


def _add_legend(ax: Any, graph: TopologyGraph) -> None:
    """Build a small legend showing only the node/edge types actually used."""
    import matplotlib.lines as mlines

    used_node_types = {n.type for n in graph.nodes()}
    used_edge_types = {e.type for e in graph.edges()}

    handles: list[Any] = []
    for ntype in sorted(used_node_types):
        color = _NODE_COLORS.get(ntype, _DEFAULT_NODE_COLOR)
        handles.append(
            mlines.Line2D(
                [],
                [],
                marker="o",
                linestyle="",
                color=color,
                markeredgecolor="black",
                markersize=8,
                label=f"node: {ntype}",
            )
        )
    for etype in sorted(used_edge_types):
        style = _EDGE_STYLE.get(etype, _DEFAULT_EDGE_STYLE)
        handles.append(mlines.Line2D([], [], label=f"edge: {etype}", **style))

    if handles:
        ax.legend(handles=handles, loc="best", fontsize=8, framealpha=0.9)
