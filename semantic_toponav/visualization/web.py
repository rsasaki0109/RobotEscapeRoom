"""Interactive HTML visualization for TopologyGraph via `pyvis`.

This is the web-browser counterpart of
:func:`semantic_toponav.visualization.plot.plot_graph`. It turns a
TopologyGraph into a single self-contained HTML file that you can open in
any browser — nodes are draggable, edges show tooltips with type / cost
metadata, and a highlighted path can be overlaid.

`pyvis` is imported lazily; install with::

    pip install 'semantic-toponav[viz_web]'

Node y-coordinates are negated when handed to pyvis because pyvis uses
screen coordinates (``+y`` downward) while our world coordinates are
mathematical (``+y`` upward). The label/legend therefore reads the same
way as the matplotlib plot.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from semantic_toponav.graph.topology_graph import TopologyGraph

# Color per semantic node type. Same palette as plot.py so the matplotlib
# and HTML views are visually consistent.
_NODE_COLORS: dict[str, str] = {
    "entrance": "#2ca02c",
    "room": "#1f77b4",
    "corridor": "#7f7f7f",
    "intersection": "#9467bd",
    "elevator": "#ff7f0e",
    "stairs": "#d62728",
}
_DEFAULT_NODE_COLOR = "#1f77b4"

_EDGE_COLOR: dict[str, str] = {
    "traversable": "#888888",
    "stairs_up": "#d62728",
    "stairs_down": "#d62728",
    "elevator_connection": "#ff7f0e",
    "restricted": "#aa0000",
    "one_way": "#444444",
}
_DEFAULT_EDGE_COLOR = "#888888"

PATH_NODE_COLOR = "#e377c2"
PATH_EDGE_COLOR = "#e377c2"
PATH_EDGE_WIDTH = 4.0

# Scale world meters to pyvis pixels. Multi-floor demos are ~10 m wide;
# 50 px/m gives a comfortable initial layout without zooming.
_PIXELS_PER_METER = 50.0


class WebViewerImportError(ImportError):
    """Raised when ``pyvis`` is not installed but a web helper was called."""


def _import_pyvis() -> Any:
    try:
        from pyvis.network import Network
    except ImportError as exc:  # pragma: no cover - exercised only without pyvis
        raise WebViewerImportError(
            "Interactive web visualization requires `pyvis`. Install with "
            f"`pip install 'semantic-toponav[viz_web]'`. ({exc})"
        ) from exc
    return Network


def _node_color(node_type: str, *, on_path: bool) -> str:
    if on_path:
        return PATH_NODE_COLOR
    return _NODE_COLORS.get(node_type, _DEFAULT_NODE_COLOR)


def _edge_color(edge_type: str, *, on_path: bool) -> str:
    if on_path:
        return PATH_EDGE_COLOR
    return _EDGE_COLOR.get(edge_type, _DEFAULT_EDGE_COLOR)


def _node_tooltip(node: Any) -> str:
    lines = [f"<b>{node.id}</b> ({node.type})"]
    if node.label and node.label != node.id:
        lines.append(f"label: {node.label}")
    if node.pose is not None:
        lines.append(
            f"pose: x={node.pose.x:.2f}, y={node.pose.y:.2f}, yaw={node.pose.yaw:.2f}"
        )
    for k, v in sorted(node.properties.items()):
        lines.append(f"{k}: {v}")
    return "<br>".join(lines)


def _edge_tooltip(edge: Any) -> str:
    lines = [f"<b>{edge.id}</b> ({edge.type})", f"cost: {edge.cost:.2f}"]
    if not edge.bidirectional:
        lines.append("one-way")
    for k, v in sorted(edge.properties.items()):
        lines.append(f"{k}: {v}")
    return "<br>".join(lines)


def to_pyvis_network(
    graph: TopologyGraph,
    *,
    path: Sequence[str] | None = None,
    height: str = "650px",
    width: str = "100%",
    use_pose_layout: bool = True,
    physics: bool | None = None,
) -> Any:
    """Build a :class:`pyvis.network.Network` from a TopologyGraph.

    Parameters
    ----------
    graph:
        Source graph. Nodes without a pose are placed by the pyvis physics
        layout if ``use_pose_layout`` is True.
    path:
        Optional list of node ids representing a planned path. Path nodes
        are recolored, and the consecutive edges along the path are drawn
        thicker in the path color.
    height, width:
        Forwarded to ``pyvis.network.Network``. Use CSS-style strings.
    use_pose_layout:
        When True (default), pin nodes that carry a ``pose`` to their
        world coordinates (scaled to pixels). When False, let pyvis lay
        out everything with its barnes-hut physics simulation.
    physics:
        If None, physics is enabled iff at least one node has no pose.
        Pass an explicit bool to override.
    """
    Network = _import_pyvis()
    net = Network(height=height, width=width, directed=False, notebook=False)

    path_set = set(path) if path else set()
    path_edges: set[tuple[str, str]] = set()
    if path:
        for a, b in zip(path, path[1:], strict=False):
            path_edges.add((a, b))
            path_edges.add((b, a))  # graph is undirected for highlight purposes

    any_missing_pose = False
    for node in graph.nodes():
        on_path = node.id in path_set
        kwargs: dict[str, Any] = {
            "label": node.label or node.id,
            "title": _node_tooltip(node),
            "color": _node_color(node.type, on_path=on_path),
        }
        if use_pose_layout and node.pose is not None:
            # pyvis screen y grows downward; flip so map +y faces up.
            kwargs["x"] = float(node.pose.x) * _PIXELS_PER_METER
            kwargs["y"] = -float(node.pose.y) * _PIXELS_PER_METER
            kwargs["physics"] = False
        else:
            any_missing_pose = True
        net.add_node(node.id, **kwargs)

    for edge in graph.edges():
        on_path = (edge.source, edge.target) in path_edges
        net.add_edge(
            edge.source,
            edge.target,
            title=_edge_tooltip(edge),
            color=_edge_color(edge.type, on_path=on_path),
            width=PATH_EDGE_WIDTH if on_path else 1.5,
        )

    if physics is None:
        physics = any_missing_pose or not use_pose_layout
    net.toggle_physics(bool(physics))
    return net


def save_interactive_html(
    graph: TopologyGraph,
    output_path: str | Path,
    *,
    path: Sequence[str] | None = None,
    **kwargs: Any,
) -> Path:
    """Save an interactive HTML view of ``graph`` to ``output_path``.

    Extra keyword args (e.g. ``height``, ``use_pose_layout``) are forwarded
    to :func:`to_pyvis_network`. Returns the written :class:`Path` for
    convenience.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    net = to_pyvis_network(graph, path=path, **kwargs)
    html = net.generate_html(notebook=False)
    out.write_text(html, encoding="utf-8")
    return out


def graph_html(
    graph: TopologyGraph,
    *,
    path: Sequence[str] | None = None,
    **kwargs: Any,
) -> str:
    """Return the interactive HTML as a string (does not write to disk).

    Useful for embedding inside other documents or for assertions in tests.
    """
    net = to_pyvis_network(graph, path=path, **kwargs)
    return net.generate_html(notebook=False)


__all__ = [
    "WebViewerImportError",
    "graph_html",
    "save_interactive_html",
    "to_pyvis_network",
]
