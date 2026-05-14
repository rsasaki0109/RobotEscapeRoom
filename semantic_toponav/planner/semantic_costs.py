"""Semantic-aware cost functions for topology-graph planning.

These are deliberately simple — they multiply or add a penalty based on
edge ``type``/``properties``. ``compose_costs`` combines them by applying
each function as a multiplier on the base cost.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from semantic_toponav.graph.types import TopologyEdge

CostFn = Callable[[TopologyEdge], float]

BLOCKED = math.inf


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
