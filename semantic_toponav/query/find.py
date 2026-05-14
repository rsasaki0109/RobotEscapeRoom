"""Filter and nearest-match queries over a TopologyGraph."""

from __future__ import annotations

import math
from typing import Any

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyNode
from semantic_toponav.planner.dijkstra import plan_dijkstra
from semantic_toponav.planner.errors import NoPathError


class NoMatchError(Exception):
    """Raised when no graph node matches the requested filters."""


def _matches(
    node: TopologyNode,
    *,
    type: str | None,
    label_contains: str | None,
    label_equals: str | None,
    properties: dict[str, Any] | None,
) -> bool:
    if type is not None and node.type != type:
        return False
    if label_equals is not None and node.label != label_equals:
        return False
    if label_contains is not None:
        haystack = (node.label or "").lower()
        if label_contains.lower() not in haystack:
            return False
    if properties:
        for key, expected in properties.items():
            if node.properties.get(key) != expected:
                return False
    return True


def find_nodes(
    graph: TopologyGraph,
    *,
    type: str | None = None,
    label_contains: str | None = None,
    label_equals: str | None = None,
    properties: dict[str, Any] | None = None,
) -> list[TopologyNode]:
    """Return all nodes matching the supplied filters.

    Each filter is independent and applied conjunctively. Pass none to
    return every node (a thin wrapper over ``graph.nodes()``).
    """
    return [
        n
        for n in graph.nodes()
        if _matches(
            n,
            type=type,
            label_contains=label_contains,
            label_equals=label_equals,
            properties=properties,
        )
    ]


def _pose_xy(pose: Pose2D | tuple[float, float]) -> tuple[float, float]:
    if isinstance(pose, Pose2D):
        return pose.x, pose.y
    x, y = pose
    return float(x), float(y)


def nearest_node_by_pose(
    graph: TopologyGraph,
    pose: Pose2D | tuple[float, float],
    *,
    type: str | None = None,
    label_contains: str | None = None,
    label_equals: str | None = None,
    properties: dict[str, Any] | None = None,
) -> TopologyNode:
    """Return the node with a pose Euclidean-closest to ``pose``.

    Candidates must (a) have a pose set and (b) satisfy all filters.
    Raises :class:`NoMatchError` if no candidate exists.
    """
    px, py = _pose_xy(pose)

    best: TopologyNode | None = None
    best_d2 = math.inf
    for n in graph.nodes():
        if n.pose is None:
            continue
        if not _matches(
            n,
            type=type,
            label_contains=label_contains,
            label_equals=label_equals,
            properties=properties,
        ):
            continue
        d2 = (n.pose.x - px) ** 2 + (n.pose.y - py) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best = n

    if best is None:
        raise NoMatchError(
            "no node matches the supplied filters (and has a pose, "
            "if Euclidean nearest was requested)"
        )
    return best


def nearest_node_by_graph_distance(
    graph: TopologyGraph,
    start_id: str,
    *,
    type: str | None = None,
    label_contains: str | None = None,
    label_equals: str | None = None,
    properties: dict[str, Any] | None = None,
) -> tuple[TopologyNode, list[str]]:
    """Return the matching node that is *graph-distance* nearest to ``start_id``.

    Returns the matching node along with the shortest path from ``start_id``.
    Raises :class:`NoMatchError` if no matching node is reachable.
    """
    if not graph.has_node(start_id):
        raise NoMatchError(f"start node {start_id!r} not in graph")

    candidates = find_nodes(
        graph,
        type=type,
        label_contains=label_contains,
        label_equals=label_equals,
        properties=properties,
    )
    if not candidates:
        raise NoMatchError("no nodes match the supplied filters")

    best: TopologyNode | None = None
    best_path: list[str] | None = None
    best_cost = math.inf
    for cand in candidates:
        if cand.id == start_id:
            return cand, [start_id]
        try:
            path = plan_dijkstra(graph, start_id, cand.id)
        except NoPathError:
            continue
        # Sum edge costs along the path.
        cost = 0.0
        for a, b in zip(path, path[1:], strict=False):
            for edge in graph.neighbors(a):
                if graph.other_end(edge, a) == b:
                    cost += edge.cost
                    break
        if cost < best_cost:
            best_cost = cost
            best = cand
            best_path = path

    if best is None or best_path is None:
        raise NoMatchError(
            f"no matching node is reachable from {start_id!r}"
        )
    return best, best_path
