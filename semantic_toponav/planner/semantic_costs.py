"""Semantic-aware cost functions for topology-graph planning.

These are deliberately simple — they multiply or add a penalty based on
edge ``type``/``properties``. ``compose_costs`` combines them by applying
each function as a multiplier on the base cost.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import TopologyEdge

CostFn = Callable[[TopologyEdge], float]

BLOCKED = math.inf

DEFAULT_FLOOR_PROPERTY = "floor"


def default_edge_cost(edge: TopologyEdge) -> float:
    """Return the edge's declared cost."""
    return edge.cost


def avoid_restricted(edge: TopologyEdge) -> float:
    """Block restricted edges entirely.

    An edge is considered restricted if its ``type`` is ``"restricted"`` or
    if ``properties.restricted`` is truthy.
    """
    if edge.type == "restricted" or edge.properties.get("restricted"):
        return BLOCKED
    return edge.cost


def avoid_stairs(edge: TopologyEdge) -> float:
    """Heavily penalize stairs edges (accessibility mode)."""
    if edge.type in {"stairs_up", "stairs_down"}:
        return edge.cost + 50.0
    return edge.cost


def prefer_elevator(edge: TopologyEdge) -> float:
    """Make elevator connections cheaper than the default."""
    if edge.type == "elevator_connection":
        return max(0.0, edge.cost * 0.5)
    return edge.cost


def _endpoint_floors(
    graph: TopologyGraph, edge: TopologyEdge, floor_property: str
) -> tuple[object, object]:
    src = graph.get_node(edge.source).properties.get(floor_property)
    tgt = graph.get_node(edge.target).properties.get(floor_property)
    return src, tgt


def floor_change_penalty(
    graph: TopologyGraph,
    *,
    penalty: float = 10.0,
    floor_property: str = DEFAULT_FLOOR_PROPERTY,
) -> CostFn:
    """Add a per-floor penalty to edges that change floor.

    Returns a cost function suitable for ``plan_*`` and ``compose_costs``.
    Edges where either endpoint lacks the ``floor`` property are charged
    normally.
    """

    def cost_fn(edge: TopologyEdge) -> float:
        src_floor, tgt_floor = _endpoint_floors(graph, edge, floor_property)
        if src_floor is None or tgt_floor is None or src_floor == tgt_floor:
            return edge.cost
        return edge.cost + penalty * abs(int(src_floor) - int(tgt_floor))

    return cost_fn


def prefer_floor(
    graph: TopologyGraph,
    floor: int,
    *,
    off_floor_multiplier: float = 2.0,
    floor_property: str = DEFAULT_FLOOR_PROPERTY,
) -> CostFn:
    """Multiply edge cost when either endpoint is not on the preferred floor.

    Edges fully on ``floor`` are charged normally; edges that leave or
    enter another floor are scaled by ``off_floor_multiplier``.
    """

    def cost_fn(edge: TopologyEdge) -> float:
        src_floor, tgt_floor = _endpoint_floors(graph, edge, floor_property)
        if src_floor == floor and tgt_floor == floor:
            return edge.cost
        return edge.cost * off_floor_multiplier

    return cost_fn


def same_floor_only(
    graph: TopologyGraph,
    *,
    floor_property: str = DEFAULT_FLOOR_PROPERTY,
) -> CostFn:
    """Block every edge whose endpoints are on different floors."""

    def cost_fn(edge: TopologyEdge) -> float:
        src_floor, tgt_floor = _endpoint_floors(graph, edge, floor_property)
        if src_floor is None or tgt_floor is None:
            return edge.cost
        if src_floor != tgt_floor:
            return BLOCKED
        return edge.cost

    return cost_fn


def block_edges(edge_ids: Iterable[str]) -> CostFn:
    """Block a fixed set of edges by id.

    Useful for runtime state like "this corridor is closed for cleaning" or
    "the freight elevator is out of service" — the underlying graph stays
    intact and a different :func:`block_edges` call can be used on the next
    plan.

    Returns a cost function that yields ``math.inf`` for the listed edges
    and ``edge.cost`` otherwise.
    """
    blocked = set(edge_ids)

    def cost_fn(edge: TopologyEdge) -> float:
        if edge.id in blocked:
            return BLOCKED
        return edge.cost

    return cost_fn


def block_edge_types(edge_types: Iterable[str]) -> CostFn:
    """Block all edges whose ``type`` is in ``edge_types``.

    Example: ``block_edge_types({"elevator_connection"})`` to plan around an
    elevator outage without touching the graph.
    """
    blocked = set(edge_types)

    def cost_fn(edge: TopologyEdge) -> float:
        if edge.type in blocked:
            return BLOCKED
        return edge.cost

    return cost_fn


def compose_costs(*cost_functions: CostFn) -> CostFn:
    """Compose multiple cost functions.

    The base cost is ``default_edge_cost``. Each additional function is
    applied as a *ratio against the edge's own cost*: if function ``f``
    returns ``v`` for an edge whose own cost is ``c``, the multiplier is
    ``v / c`` (or 1.0 if ``c == 0``). Multipliers compound, and any
    function returning ``inf`` blocks the edge.

    This keeps individual cost functions independent and composable.
    """

    def composed(edge: TopologyEdge) -> float:
        base = edge.cost
        multiplier = 1.0
        for fn in cost_functions:
            v = fn(edge)
            if math.isinf(v):
                return math.inf
            if base == 0:
                # Allow additive adjustments via absolute value when base is 0.
                multiplier *= 1.0 + v
            else:
                multiplier *= v / base
        return base * multiplier

    return composed
