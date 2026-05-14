"""Convert one or more trajectory logs into a TopologyGraph.

Algorithm:

1. **Greedy spatial clustering**. Walk through all points (across all input
   trajectories) and assign each to the nearest existing cluster within
   ``eps`` meters, otherwise create a new cluster. The cluster centroid is
   updated incrementally as points are absorbed.
2. **Density filter**. Drop clusters whose point count is below
   ``min_samples`` so isolated noise points along corridors don't become
   nodes.
3. **Edge induction**. For each trajectory in order, follow the sequence of
   *valid* cluster assignments and collapse repeated consecutive
   assignments. Each transition between distinct valid clusters becomes an
   undirected edge between the corresponding nodes. Repeat traversals of
   the same pair are tracked as ``traversal_count`` on the edge's
   properties — higher counts indicate well-trodden routes.

This is intentionally a small, dependency-free clusterer (no scikit-learn,
no scipy). It is order-dependent but works well in practice for trajectory
logs where the robot's path defines the topology.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode


Point = tuple[float, float]


def _greedy_cluster(
    points: Sequence[Point], eps: float
) -> tuple[list[Point], list[int], list[int]]:
    """Greedy single-pass clusterer.

    Returns ``(centroids, sizes, assignments)`` where ``assignments[i]`` is
    the cluster index assigned to ``points[i]``.
    """
    centroids: list[Point] = []
    sizes: list[int] = []
    assignments: list[int] = []
    for x, y in points:
        best_idx = -1
        best_d2 = eps * eps
        for i, (cx, cy) in enumerate(centroids):
            d2 = (cx - x) ** 2 + (cy - y) ** 2
            if d2 <= best_d2:
                best_d2 = d2
                best_idx = i
        if best_idx == -1:
            centroids.append((x, y))
            sizes.append(1)
            assignments.append(len(centroids) - 1)
        else:
            cx, cy = centroids[best_idx]
            n = sizes[best_idx]
            centroids[best_idx] = ((cx * n + x) / (n + 1), (cy * n + y) / (n + 1))
            sizes[best_idx] = n + 1
            assignments.append(best_idx)
    return centroids, sizes, assignments


def topology_from_trajectories(
    trajectories: Iterable[Sequence[Point]],
    *,
    eps: float = 0.5,
    min_samples: int = 3,
    node_type: str = "waypoint",
    edge_type: str = "traversable",
    frame_id: str = "map",
    id_prefix: str = "",
) -> TopologyGraph:
    """Build a TopologyGraph from one or more 2D trajectory logs.

    Parameters
    ----------
    trajectories:
        Iterable of trajectories, each a sequence of ``(x, y)`` points.
    eps:
        Maximum distance (meters) within which points join an existing cluster.
    min_samples:
        Clusters with fewer than this many points are discarded.
    node_type, edge_type, frame_id, id_prefix:
        Override the labels applied to generated nodes/edges.
    """
    traj_list: list[list[Point]] = [list(t) for t in trajectories]
    all_points: list[Point] = []
    traj_ownership: list[int] = []
    for ti, t in enumerate(traj_list):
        for x, y in t:
            all_points.append((float(x), float(y)))
            traj_ownership.append(ti)

    if not all_points:
        return TopologyGraph()

    centroids, sizes, assignments = _greedy_cluster(all_points, eps)
    valid = {i for i, sz in enumerate(sizes) if sz >= min_samples}

    graph = TopologyGraph()
    cluster_to_node: dict[int, str] = {}
    for cid in sorted(valid):
        cx, cy = centroids[cid]
        node_id = f"{id_prefix}wp_{cid}"
        graph.add_node(
            TopologyNode(
                id=node_id,
                label=node_id,
                type=node_type,
                pose=Pose2D(x=cx, y=cy, yaw=0.0, frame_id=frame_id),
                properties={"cluster_size": sizes[cid]},
            )
        )
        cluster_to_node[cid] = node_id

    # Group assignments by trajectory.
    per_traj: list[list[int]] = [[] for _ in traj_list]
    for global_idx, cid in enumerate(assignments):
        per_traj[traj_ownership[global_idx]].append(cid)

    # Edge counts keyed by an unordered pair of cluster ids.
    edge_counts: dict[tuple[int, int], int] = {}
    for cluster_seq in per_traj:
        # Keep only valid clusters and collapse consecutive duplicates.
        collapsed: list[int] = []
        for cid in cluster_seq:
            if cid not in valid:
                continue
            if collapsed and collapsed[-1] == cid:
                continue
            collapsed.append(cid)
        for a, b in zip(collapsed, collapsed[1:], strict=False):
            key = (a, b) if a <= b else (b, a)
            edge_counts[key] = edge_counts.get(key, 0) + 1

    for (a, b), count in edge_counts.items():
        source = cluster_to_node[a]
        target = cluster_to_node[b]
        ax, ay = centroids[a]
        bx, by = centroids[b]
        cost = math.hypot(ax - bx, ay - by)
        graph.add_edge(
            TopologyEdge(
                id=f"{id_prefix}e_{a}_{b}",
                source=source,
                target=target,
                type=edge_type,
                cost=cost,
                bidirectional=True,
                properties={"traversal_count": count},
            )
        )

    return graph
