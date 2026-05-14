"""Hybrid pipeline: annotate an existing topology graph with traversal data.

Use case: you have a skeleton-derived graph from
:func:`semantic_toponav.conversion.topology_from_occupancy` (geometrically
faithful, semantically anonymous), and one or more recorded runs from
:func:`semantic_toponav.conversion.load_trajectories_from_rosbag` or
:func:`semantic_toponav.conversion.load_trajectories_from_csv`. This module
snaps the recorded points onto the existing nodes and counts traversals
along the existing edges, producing per-node ``visit_count`` and per-edge
``traversal_count`` properties.

The result lets you tell apart well-trodden corridors from rarely-used
ones without re-deriving the topology. Transitions in the trajectory that
have no matching edge in the graph are tallied separately so callers can
decide whether to add edges, widen ``max_snap_distance``, or trust the
skeleton.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import TopologyEdge

Point = tuple[float, float]
_DEFAULT_EDGE_TYPE = "promoted"


@dataclass
class AnnotationResult:
    """Summary statistics from :func:`annotate_graph_with_trajectories`.

    Attributes
    ----------
    points_snapped:
        Number of trajectory points that were assigned to a node.
    points_skipped:
        Number of points dropped because the nearest node was further than
        ``max_snap_distance`` or no posed nodes were available.
    nodes_visited:
        Distinct node ids that received at least one visit.
    transitions_recorded:
        Number of consecutive distinct-node transitions seen across all
        trajectories (after collapsing repeats).
    transitions_mapped:
        Subset of ``transitions_recorded`` that matched an existing edge.
    unmapped_transitions:
        Pairs of node ids (in lexicographic order) that appeared as a
        transition with no matching edge in the graph, with their counts.
    """

    points_snapped: int = 0
    points_skipped: int = 0
    nodes_visited: int = 0
    transitions_recorded: int = 0
    transitions_mapped: int = 0
    unmapped_transitions: dict[tuple[str, str], int] = field(default_factory=dict)


def _nearest_node_id(
    point: Point,
    posed: list[tuple[str, float, float]],
    max_d2: float | None,
) -> str | None:
    px, py = point
    best_id: str | None = None
    best_d2 = math.inf if max_d2 is None else max_d2
    for node_id, x, y in posed:
        d2 = (x - px) ** 2 + (y - py) ** 2
        if d2 < best_d2:
            best_d2 = d2
            best_id = node_id
    return best_id


def _find_edge_between(
    graph: TopologyGraph, a: str, b: str
) -> TopologyEdge | None:
    for edge in graph.neighbors(a):
        if graph.other_end(edge, a) == b:
            return edge
    return None


def annotate_graph_with_trajectories(
    graph: TopologyGraph,
    trajectories: Iterable[Sequence[Point]],
    *,
    max_snap_distance: float | None = None,
    visit_count_key: str = "visit_count",
    traversal_count_key: str = "traversal_count",
) -> AnnotationResult:
    """Annotate ``graph`` in place with traversal data from recorded runs.

    For every trajectory:

    1. Snap each ``(x, y)`` point to the nearest node in ``graph`` that
       has a pose. If ``max_snap_distance`` is set, points whose nearest
       node lies further than that distance are skipped.
    2. Collapse consecutive identical snaps (the robot dwelling near a
       single node).
    3. Increment ``visit_count`` on every visited node's ``properties``
       (once per trajectory visit, not once per snapped point).
    4. For every consecutive ``(a, b)`` pair after collapsing, look up an
       edge between ``a`` and ``b`` and increment ``traversal_count`` on
       its ``properties``. Pairs with no matching edge are tallied under
       ``unmapped_transitions`` in the returned :class:`AnnotationResult`.

    Mutates ``graph`` in place. Nodes without a pose are ignored during
    snapping.
    """
    posed: list[tuple[str, float, float]] = [
        (node.id, node.pose.x, node.pose.y)
        for node in graph.nodes()
        if node.pose is not None
    ]
    result = AnnotationResult()
    if not posed:
        for trajectory in trajectories:
            result.points_skipped += sum(1 for _ in trajectory)
        return result

    max_d2 = (
        None if max_snap_distance is None else max_snap_distance * max_snap_distance
    )
    visited_node_ids: set[str] = set()

    for trajectory in trajectories:
        snapped: list[str] = []
        for x, y in trajectory:
            nid = _nearest_node_id((float(x), float(y)), posed, max_d2)
            if nid is None:
                result.points_skipped += 1
                continue
            result.points_snapped += 1
            if snapped and snapped[-1] == nid:
                continue
            snapped.append(nid)

        for nid in snapped:
            node = graph.get_node(nid)
            node.properties[visit_count_key] = (
                node.properties.get(visit_count_key, 0) + 1
            )
            visited_node_ids.add(nid)

        for a, b in zip(snapped, snapped[1:], strict=False):
            result.transitions_recorded += 1
            edge = _find_edge_between(graph, a, b)
            if edge is None:
                key = (a, b) if a <= b else (b, a)
                result.unmapped_transitions[key] = (
                    result.unmapped_transitions.get(key, 0) + 1
                )
            else:
                edge.properties[traversal_count_key] = (
                    edge.properties.get(traversal_count_key, 0) + 1
                )
                result.transitions_mapped += 1

    result.nodes_visited = len(visited_node_ids)
    return result


def prune_low_traversal_edges(
    graph: TopologyGraph,
    *,
    min_traversals: int = 1,
    traversal_count_key: str = "traversal_count",
    keep_edge_types: Iterable[str] = (),
) -> list[str]:
    """Remove edges whose ``traversal_count`` is below ``min_traversals``.

    Edges that have *no* ``traversal_count`` property are treated as
    zero — call this after :func:`annotate_graph_with_trajectories` so
    well-trodden edges already carry counts and unused ones have none.

    Parameters
    ----------
    min_traversals:
        Edges with strictly fewer traversals are removed.
    traversal_count_key:
        The property key on each edge that holds the count.
    keep_edge_types:
        Edge types to always preserve regardless of count — useful for
        keeping structural elements (stairs, elevators) that may rarely
        appear in recorded runs.

    Mutates ``graph`` in place. Returns the list of removed edge ids.
    """
    protected = set(keep_edge_types)
    removed: list[str] = []
    for edge in list(graph.edges()):
        if edge.type in protected:
            continue
        count = int(edge.properties.get(traversal_count_key, 0))
        if count < min_traversals:
            graph.remove_edge(edge.id)
            removed.append(edge.id)
    return removed


def promote_unmapped_transitions(
    graph: TopologyGraph,
    unmapped_transitions: dict[tuple[str, str], int],
    *,
    min_count: int = 2,
    edge_type: str = _DEFAULT_EDGE_TYPE,
    traversal_count_key: str = "traversal_count",
    id_prefix: str = "promoted_",
) -> list[str]:
    """Add edges for hot transitions that had no matching edge in the graph.

    Given an ``unmapped_transitions`` mapping (typically taken from
    :class:`AnnotationResult.unmapped_transitions`), this creates one
    new bidirectional edge per pair whose count is at least
    ``min_count``. The new edge's ``cost`` is the Euclidean distance
    between the endpoints' poses; when a pose is missing the cost
    falls back to ``1.0``. The pair's traversal count is recorded on
    the new edge so subsequent passes see it as a "warm" edge.

    Skips pairs whose endpoints are no longer in the graph or that
    already have an edge between them (defensive — should not happen if
    the input was produced by the same graph, but allows reuse across
    sessions).

    Mutates ``graph`` in place. Returns the list of added edge ids.
    """
    added: list[str] = []
    for (a, b), count in unmapped_transitions.items():
        if count < min_count:
            continue
        if not (graph.has_node(a) and graph.has_node(b)):
            continue
        if _find_edge_between(graph, a, b) is not None:
            continue
        pa = graph.get_node(a).pose
        pb = graph.get_node(b).pose
        cost = (
            math.hypot(pa.x - pb.x, pa.y - pb.y)
            if pa is not None and pb is not None
            else 1.0
        )
        edge_id = f"{id_prefix}{a}__{b}"
        suffix = 2
        while graph.has_edge(edge_id):
            edge_id = f"{id_prefix}{a}__{b}_v{suffix}"
            suffix += 1
        graph.add_edge(
            TopologyEdge(
                id=edge_id,
                source=a,
                target=b,
                type=edge_type,
                cost=cost,
                bidirectional=True,
                properties={traversal_count_key: count},
            )
        )
        added.append(edge_id)
    return added
