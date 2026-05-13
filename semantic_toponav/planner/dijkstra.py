"""Dijkstra shortest-path planner over a TopologyGraph."""

from __future__ import annotations

import heapq
import math
from collections.abc import Callable

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import TopologyEdge
from semantic_toponav.planner.errors import NoPathError, PlanningError


def _default_cost(edge: TopologyEdge) -> float:
    return edge.cost


def plan_dijkstra(
    graph: TopologyGraph,
    start_id: str,
    goal_id: str,
    cost_fn: Callable[[TopologyEdge], float] | None = None,
) -> list[str]:
    """Plan a shortest path from ``start_id`` to ``goal_id`` using Dijkstra.

    Returns the list of node IDs from start to goal (inclusive).
    Raises ``PlanningError`` if either endpoint is missing, and ``NoPathError``
    if no path exists.
    """
    if not graph.has_node(start_id):
        raise PlanningError(f"start node {start_id!r} not in graph")
    if not graph.has_node(goal_id):
        raise PlanningError(f"goal node {goal_id!r} not in graph")
    if start_id == goal_id:
        return [start_id]

    cost = cost_fn or _default_cost

    dist: dict[str, float] = {start_id: 0.0}
    came_from: dict[str, str] = {}
    # Heap entries: (g_cost, counter, node_id). Counter for stable ordering.
    counter = 0
    open_heap: list[tuple[float, int, str]] = [(0.0, counter, start_id)]
    closed: set[str] = set()

    while open_heap:
        g, _, current = heapq.heappop(open_heap)
        if current in closed:
            continue
        if current == goal_id:
            return _reconstruct(came_from, start_id, goal_id)
        closed.add(current)

        for edge in graph.neighbors(current):
            neighbor = graph.other_end(edge, current)
            if neighbor in closed:
                continue
            step = cost(edge)
            if step is None or math.isinf(step):
                continue
            if step < 0:
                raise PlanningError(
                    f"cost function returned negative cost {step} for edge {edge.id!r}"
                )
            ng = g + step
            if ng < dist.get(neighbor, math.inf):
                dist[neighbor] = ng
                came_from[neighbor] = current
                counter += 1
                heapq.heappush(open_heap, (ng, counter, neighbor))

    raise NoPathError(f"no path from {start_id!r} to {goal_id!r}")


def _reconstruct(came_from: dict[str, str], start_id: str, goal_id: str) -> list[str]:
    path = [goal_id]
    while path[-1] != start_id:
        prev = came_from.get(path[-1])
        if prev is None:
            raise NoPathError(
                f"path reconstruction failed: missing predecessor for {path[-1]!r}"
            )
        path.append(prev)
    path.reverse()
    return path
