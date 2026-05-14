"""Visit-history-aware cost factories for the planner.

These follow the same factory pattern as :mod:`semantic_toponav.planner.semantic_costs`:
``f(graph, ...) -> (edge) -> float``. They read visit-history properties
written by :mod:`semantic_toponav.memory.visit` and compose cleanly with
:func:`semantic_toponav.planner.compose_costs`.

The cost applied to an edge is driven by the *target* endpoint (the node
the robot would arrive at if it took the edge), which is the natural choice
for "where have I been recently?" reasoning.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import TopologyEdge
from semantic_toponav.memory.visit import (
    DEFAULT_LAST_VISITED_KEY,
    DEFAULT_VISIT_COUNT_KEY,
)

CostFn = Callable[[TopologyEdge], float]


def prefer_unvisited(
    graph: TopologyGraph,
    *,
    visited_multiplier: float = 2.0,
    count_key: str = DEFAULT_VISIT_COUNT_KEY,
) -> CostFn:
    """Penalize edges that lead to already-visited nodes.

    Edges whose target node has ``visit_count >= 1`` are scaled by
    ``visited_multiplier``. Use this for coverage / exploration tasks
    (room-by-room patrol, frontier seeking) where revisiting a node is
    wasted effort.
    """

    def cost_fn(edge: TopologyEdge) -> float:
        target = graph.get_node(edge.target)
        if int(target.properties.get(count_key, 0)) >= 1:
            return edge.cost * visited_multiplier
        return edge.cost

    return cost_fn


def prefer_familiar(
    graph: TopologyGraph,
    *,
    familiar_multiplier: float = 0.5,
    count_key: str = DEFAULT_VISIT_COUNT_KEY,
) -> CostFn:
    """Reward edges that lead to nodes the robot has visited before.

    Edges whose target node has ``visit_count >= 1`` are scaled by
    ``familiar_multiplier`` (default 0.5 — half-cost). Use this for
    "retrace the well-known route" tasks where unfamiliar nodes are
    riskier than known ones.
    """

    def cost_fn(edge: TopologyEdge) -> float:
        target = graph.get_node(edge.target)
        if int(target.properties.get(count_key, 0)) >= 1:
            return edge.cost * familiar_multiplier
        return edge.cost

    return cost_fn


def avoid_recently_visited(
    graph: TopologyGraph,
    *,
    within_seconds: float,
    recent_multiplier: float = 5.0,
    now: float | None = None,
    timestamp_key: str = DEFAULT_LAST_VISITED_KEY,
) -> CostFn:
    """Penalize edges that lead to nodes visited within the past window.

    A node is "recent" if ``now - last_visited <= within_seconds``. Older
    visits (and unvisited nodes) keep their base cost.

    ``now`` defaults to ``time.time()`` at *factory call time* (not at each
    edge evaluation), so a single plan call sees a consistent clock. Pass
    a fixed value to make the result deterministic.
    """
    cutoff = (time.time() if now is None else float(now)) - float(within_seconds)

    def cost_fn(edge: TopologyEdge) -> float:
        ts = graph.get_node(edge.target).properties.get(timestamp_key)
        if ts is None:
            return edge.cost
        if float(ts) >= cutoff:
            return edge.cost * recent_multiplier
        return edge.cost

    return cost_fn
