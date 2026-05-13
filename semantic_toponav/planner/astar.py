"""A* planner over a TopologyGraph."""

from __future__ import annotations

import heapq
import math
from collections.abc import Callable

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import TopologyEdge
from semantic_toponav.planner.errors import NoPathError, PlanningError


def _default_cost(edge: TopologyEdge) -> float:
    return edge.cost


def euclidean_heuristic(graph: TopologyGraph, a_id: str, b_id: str) -> float:
    """Euclidean distance between node poses; 0 if either is missing."""
    a = graph.get_node(a_id).pose
    b = graph.get_node(b_id).pose
    if a is None or b is None:
        return 0.0
    return math.hypot(a.x - b.x, a.y - b.y)


def floor_aware_heuristic(
    *,
    floor_property: str = "floor",
    floor_height: float = 4.0,
):
    """Build an A* heuristic that adds an inter-floor distance term.

    Each unit of floor difference between the two nodes contributes
    ``floor_height`` (meters) to the heuristic, on top of the planar
    Euclidean distance. Falls back to plain Euclidean when either
    node lacks the floor property.
    """

    def heuristic(graph: TopologyGraph, a_id: str, b_id: str) -> float:
        a = graph.get_node(a_id)
        b = graph.get_node(b_id)
        planar = 0.0
        if a.pose is not None and b.pose is not None:
            planar = math.hypot(a.pose.x - b.pose.x, a.pose.y - b.pose.y)
        fa = a.properties.get(floor_property)
        fb = b.properties.get(floor_property)
        if fa is None or fb is None:
            return planar
        return planar + abs(int(fa) - int(fb)) * floor_height

    return heuristic


def plan_astar(
    graph: TopologyGraph,
    start_id: str,
    goal_id: str,
    cost_fn: Callable[[TopologyEdge], float] | None = None,
    heuristic_fn: Callable[[TopologyGraph, str, str], float] | None = None,
) -> list[str]:
    """Plan with A*.

    Falls back to Dijkstra-equivalent behavior when the heuristic returns 0
    (e.g., when poses are missing).
    """
    if not graph.has_node(start_id):
        raise PlanningError(f"start node {start_id!r} not in graph")
    if not graph.has_node(goal_id):
        raise PlanningError(f"goal node {goal_id!r} not in graph")
    if start_id == goal_id:
        return [start_id]

    cost = cost_fn or _default_cost
    heuristic = heuristic_fn or euclidean_heuristic

    g_score: dict[str, float] = {start_id: 0.0}
    came_from: dict[str, str] = {}
    counter = 0
    open_heap: list[tuple[float, int, str]] = [
        (heuristic(graph, start_id, goal_id), counter, start_id)
    ]
    closed: set[str] = set()

    while open_heap:
        _, _, current = heapq.heappop(open_heap)
        if current in closed:
            continue
        if current == goal_id:
            return _reconstruct(came_from, start_id, goal_id)
        closed.add(current)

        cg = g_score[current]
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
            ng = cg + step
            if ng < g_score.get(neighbor, math.inf):
                g_score[neighbor] = ng
                came_from[neighbor] = current
                counter += 1
                f = ng + heuristic(graph, neighbor, goal_id)
                heapq.heappush(open_heap, (f, counter, neighbor))

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
