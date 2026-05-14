"""Lossy compaction passes for a :class:`TopologyGraph`.

Two operations, applied in order:

1. **Node merging within Euclidean tolerance.** When several posed nodes
   live within ``endpoint_tolerance`` meters of each other, they are
   replaced by a single representative whose pose is the cluster
   centroid. Edges that referenced any of the merged nodes are rerouted
   onto the representative; edges whose endpoints end up identical
   (degenerate self-loops) are dropped.
2. **Parallel-edge collapse.** Edges that share the same endpoint pair
   *and* the same direction flag are grouped. When all the edges in a
   group have costs within ``edge_cost_tolerance`` of each other, the
   group collapses to a single representative chosen by
   ``keep_strategy``; otherwise the edges are kept as distinct paths.

Both stages are lossy: properties on dropped nodes / edges are
discarded, geometry information is averaged or thrown away, and the
caller is responsible for deciding whether the compaction is faithful
enough for the downstream task.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode

KeepStrategy = str  # "shortest" | "longest" | "first"
_KEEP_STRATEGIES: tuple[str, ...] = ("shortest", "longest", "first")


@dataclass
class CompactionResult:
    """Summary returned by :func:`compact_graph`.

    Attributes
    ----------
    merged_nodes:
        ``alias_node_id -> representative_node_id`` mapping. The alias
        node has been removed from the graph; the representative
        survives with its pose updated to the cluster centroid.
    dropped_self_loops:
        Edge ids that turned into self-loops after node merging and were
        therefore removed.
    collapsed_edges:
        ``dropped_edge_id -> kept_edge_id`` mapping from the
        parallel-edge collapse stage.
    """

    merged_nodes: dict[str, str] = field(default_factory=dict)
    dropped_self_loops: list[str] = field(default_factory=list)
    collapsed_edges: dict[str, str] = field(default_factory=dict)


def _disjoint_find(parent: dict[str, str], x: str) -> str:
    root = x
    while parent[root] != root:
        root = parent[root]
    # Path compression.
    while parent[x] != root:
        parent[x], x = root, parent[x]
    return root


def _disjoint_union(parent: dict[str, str], a: str, b: str) -> None:
    ra, rb = _disjoint_find(parent, a), _disjoint_find(parent, b)
    if ra == rb:
        return
    # Keep the lexicographically smaller id as the root for determinism.
    if ra < rb:
        parent[rb] = ra
    else:
        parent[ra] = rb


def _cluster_nodes_by_distance(
    graph: TopologyGraph, tolerance: float
) -> dict[str, list[str]]:
    """Return ``rep_id -> [member_ids]`` for clusters of size >= 2.

    Only nodes carrying a pose participate. Singleton clusters are
    omitted from the return value (they need no rewriting).
    """
    posed: list[tuple[str, float, float]] = [
        (n.id, n.pose.x, n.pose.y)
        for n in graph.nodes()
        if n.pose is not None
    ]
    parent: dict[str, str] = {nid: nid for nid, _, _ in posed}
    tol2 = tolerance * tolerance
    for i in range(len(posed)):
        nid_i, xi, yi = posed[i]
        for j in range(i + 1, len(posed)):
            nid_j, xj, yj = posed[j]
            dx = xi - xj
            dy = yi - yj
            if dx * dx + dy * dy <= tol2:
                _disjoint_union(parent, nid_i, nid_j)

    clusters: dict[str, list[str]] = {}
    for nid, _, _ in posed:
        root = _disjoint_find(parent, nid)
        clusters.setdefault(root, []).append(nid)
    return {root: members for root, members in clusters.items() if len(members) > 1}


def _centroid_pose(
    members: list[TopologyNode], rep: TopologyNode
) -> Pose2D:
    poses = [n.pose for n in members if n.pose is not None]
    cx = sum(p.x for p in poses) / len(poses)
    cy = sum(p.y for p in poses) / len(poses)
    base = rep.pose
    return Pose2D(
        x=cx,
        y=cy,
        yaw=base.yaw if base is not None else 0.0,
        frame_id=base.frame_id if base is not None else "map",
    )


def _merge_nodes(
    graph: TopologyGraph,
    clusters: dict[str, list[str]],
    result: CompactionResult,
) -> None:
    for rep_id, members in clusters.items():
        rep = graph.get_node(rep_id)
        member_nodes = [graph.get_node(mid) for mid in members]
        rep.pose = _centroid_pose(member_nodes, rep)

        alias_to_rep: dict[str, str] = {mid: rep_id for mid in members if mid != rep_id}
        for alias in alias_to_rep:
            result.merged_nodes[alias] = rep_id

        # Reroute every edge that touches an alias onto the representative.
        for edge_id in list(graph.edge_ids()):
            edge = graph.get_edge(edge_id)
            new_source = alias_to_rep.get(edge.source, edge.source)
            new_target = alias_to_rep.get(edge.target, edge.target)
            if new_source == edge.source and new_target == edge.target:
                continue
            if new_source == new_target:
                graph.remove_edge(edge_id)
                result.dropped_self_loops.append(edge_id)
                continue
            replacement = TopologyEdge(
                id=edge.id,
                source=new_source,
                target=new_target,
                type=edge.type,
                cost=edge.cost,
                bidirectional=edge.bidirectional,
                properties=dict(edge.properties),
            )
            graph.remove_edge(edge_id)
            graph.add_edge(replacement)

        # Finally, drop alias nodes (no edges left referencing them).
        for alias in alias_to_rep:
            graph.remove_node(alias)


def _edge_group_key(edge: TopologyEdge) -> tuple:
    """Return a hashable key under which two edges are 'parallel'.

    Bidirectional edges with the same endpoint pair (in any order)
    share a key. Directed edges only share a key when both source and
    target match exactly.
    """
    if edge.bidirectional:
        a, b = sorted((edge.source, edge.target))
        return ("bi", a, b)
    return ("di", edge.source, edge.target)


def _pick_representative(
    candidates: list[TopologyEdge], strategy: KeepStrategy
) -> TopologyEdge:
    if strategy == "shortest":
        return min(candidates, key=lambda e: (e.cost, e.id))
    if strategy == "longest":
        # Negate cost so min still picks the longest, then break ties
        # toward the lexicographically smallest id.
        return min(candidates, key=lambda e: (-e.cost, e.id))
    if strategy == "first":
        # Insertion order is preserved by dict, so the smallest index wins.
        return candidates[0]
    raise ValueError(
        f"unknown keep_strategy {strategy!r}; expected one of {_KEEP_STRATEGIES}"
    )


def _collapse_parallel_edges(
    graph: TopologyGraph,
    *,
    edge_cost_tolerance: float,
    keep_strategy: KeepStrategy,
    result: CompactionResult,
) -> None:
    if keep_strategy not in _KEEP_STRATEGIES:
        raise ValueError(
            f"unknown keep_strategy {keep_strategy!r}; expected one of "
            f"{_KEEP_STRATEGIES}"
        )

    groups: dict[tuple, list[TopologyEdge]] = {}
    for edge in graph.edges():
        groups.setdefault(_edge_group_key(edge), []).append(edge)

    for candidates in groups.values():
        if len(candidates) < 2:
            continue
        cost_span = max(e.cost for e in candidates) - min(e.cost for e in candidates)
        if cost_span > edge_cost_tolerance:
            continue
        keeper = _pick_representative(candidates, keep_strategy)
        for edge in candidates:
            if edge.id == keeper.id:
                continue
            graph.remove_edge(edge.id)
            result.collapsed_edges[edge.id] = keeper.id


def compact_graph(
    graph: TopologyGraph,
    *,
    endpoint_tolerance: float = 0.0,
    edge_cost_tolerance: float = math.inf,
    keep_strategy: KeepStrategy = "shortest",
) -> CompactionResult:
    """Apply node merging and parallel-edge collapse, in place.

    Parameters
    ----------
    graph:
        Graph to mutate.
    endpoint_tolerance:
        Euclidean distance, in the same units as node poses (meters in
        the ROS convention), under which two posed nodes are merged
        into a cluster. ``0.0`` disables the merge stage entirely so
        only exact-endpoint duplicates collapse downstream.
    edge_cost_tolerance:
        Maximum spread of edge costs within a parallel-edge group that
        still allows the group to collapse. The default ``math.inf``
        always collapses same-endpoint duplicates; pass a finite value
        to keep genuinely distinct (different-length) parallel paths.
    keep_strategy:
        Which edge survives in a collapsed group. One of
        ``"shortest"``, ``"longest"``, ``"first"``. Ties break toward
        the lexicographically smallest edge id.

    Returns
    -------
    CompactionResult
        Summary of what was rewritten or dropped.
    """
    if endpoint_tolerance < 0:
        raise ValueError(
            f"endpoint_tolerance must be non-negative, got {endpoint_tolerance}"
        )
    if edge_cost_tolerance < 0:
        raise ValueError(
            f"edge_cost_tolerance must be non-negative, got {edge_cost_tolerance}"
        )

    result = CompactionResult()

    if endpoint_tolerance > 0:
        clusters = _cluster_nodes_by_distance(graph, endpoint_tolerance)
        if clusters:
            _merge_nodes(graph, clusters, result)

    _collapse_parallel_edges(
        graph,
        edge_cost_tolerance=edge_cost_tolerance,
        keep_strategy=keep_strategy,
        result=result,
    )

    return result
