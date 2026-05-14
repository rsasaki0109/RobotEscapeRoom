"""Fuse an occupancy-derived topology with recorded trajectories.

Run from the repository root::

    python examples/fusion_demo.py

This builds a synthetic floor plan, derives a skeleton-based topology graph
from it, then plays back synthetic trajectories along two of the corridors
(one heavily used, one lightly used). The result is a single graph whose
edges carry ``traversal_count`` properties — letting you tell hot routes
from rarely-used ones without rebuilding the topology.

Requires the ``[map]`` extra::

    pip install -e '.[map]'
"""

from __future__ import annotations

import numpy as np

from semantic_toponav.conversion import (
    annotate_graph_with_trajectories,
    fuse_trajectories_iteratively,
    topology_from_occupancy,
)


def build_floor() -> np.ndarray:
    """H-shape: two parallel corridors with one mid-span connector."""
    h, w = 24, 50
    grid = np.zeros((h, w), dtype=bool)
    grid[4:7, 4:46] = True     # top corridor
    grid[17:20, 4:46] = True   # bottom corridor
    grid[4:20, 23:26] = True   # mid connector
    return grid


def trajectory_along_corridor(
    y: float, *, x_start: float = 1.5, x_end: float = 11.0, n: int = 80
) -> list[tuple[float, float]]:
    return [(x_start + (x_end - x_start) * t / (n - 1), y) for t in range(n)]


def main() -> None:
    resolution = 0.25
    grid = build_floor()
    graph = topology_from_occupancy(grid, resolution=resolution)
    print(
        f"skeleton -> {len(graph.node_ids())} nodes, {len(graph.edge_ids())} edges"
    )

    h = grid.shape[0]
    top_corridor_y = (h - 1 - 5 + 0.5) * resolution      # row 5
    bottom_corridor_y = (h - 1 - 18 + 0.5) * resolution  # row 18

    # The robot prefers the top corridor 5x more than the bottom one.
    trajectories = (
        [trajectory_along_corridor(top_corridor_y) for _ in range(5)]
        + [trajectory_along_corridor(bottom_corridor_y) for _ in range(1)]
    )

    result = annotate_graph_with_trajectories(
        graph, trajectories, max_snap_distance=1.0
    )
    print(
        f"snapped {result.points_snapped} points, skipped {result.points_skipped}, "
        f"recorded {result.transitions_recorded} transitions "
        f"({result.transitions_mapped} mapped, "
        f"{sum(result.unmapped_transitions.values())} unmapped)"
    )

    used = [
        (e, e.properties.get("traversal_count", 0))
        for e in graph.edges()
    ]
    used.sort(key=lambda kv: kv[1], reverse=True)
    print("\nedges by traversal_count:")
    for edge, count in used:
        src = graph.get_node(edge.source).pose
        tgt = graph.get_node(edge.target).pose
        print(
            f"  {edge.id:<30s} count={count}  "
            f"({src.x:.2f},{src.y:.2f}) -> ({tgt.x:.2f},{tgt.y:.2f})"
        )

    # Now show the high-level wrapper on a fresh skeleton: it loops
    # annotate -> prune -> promote until the topology stabilises.
    graph2 = topology_from_occupancy(grid, resolution=resolution)
    out = fuse_trajectories_iteratively(
        graph2, trajectories, max_snap_distance=1.0, prune_min_traversals=1
    )
    print(
        f"\niterative: {out.iterations} iteration(s), "
        f"converged={out.converged}, "
        f"final graph has {len(graph2.node_ids())} nodes "
        f"and {len(graph2.edge_ids())} edges"
    )
    for step in out.history:
        print(
            f"  iter {step.iteration}: "
            f"+{len(step.promoted_edge_ids)} promoted, "
            f"-{len(step.pruned_edge_ids)} pruned"
        )


if __name__ == "__main__":
    main()
