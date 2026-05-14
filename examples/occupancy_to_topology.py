"""Convert a synthetic occupancy grid into a topology graph.

Run from the repository root:

    python examples/occupancy_to_topology.py

This builds a small synthetic floor plan (corridors + a few rooms), runs the
skeletonization-based converter, plans a path on the resulting topology
graph, and saves a figure overlaying the graph and path on the original
occupancy grid.

Requires the ``[viz]`` and ``[map]`` extras::

    pip install -e '.[viz,map]'
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from semantic_toponav.conversion import topology_from_occupancy
from semantic_toponav.planner import plan_astar
from semantic_toponav.visualization import plot_graph

IMAGE_DIR = Path(__file__).resolve().parents[1] / "docs" / "images"
RESOLUTION = 0.25


def build_synthetic_floor() -> np.ndarray:
    """Return a small floor plan: two horizontal corridors connected vertically
    plus three small rooms branching off."""
    h, w = 30, 60
    grid = np.zeros((h, w), dtype=bool)

    # Two horizontal corridors.
    grid[8:11, 4:55] = True
    grid[22:25, 4:55] = True

    # Three vertical links between them.
    grid[8:25, 12:14] = True
    grid[8:25, 30:32] = True
    grid[8:25, 48:50] = True

    # Three rooms off the top corridor.
    grid[3:8, 18:25] = True
    grid[3:8, 36:45] = True
    grid[3:8, 51:57] = True

    return grid


def main() -> None:
    grid = build_synthetic_floor()
    graph = topology_from_occupancy(grid, resolution=RESOLUTION)
    print(
        f"converted {grid.shape[0]}x{grid.shape[1]} occupancy grid "
        f"-> {len(graph.node_ids())} nodes, {len(graph.edge_ids())} edges"
    )

    # Pick the leftmost and rightmost endpoints as start/goal.
    endpoint_nodes = [n for n in graph.nodes() if n.type == "endpoint"]
    endpoint_nodes.sort(key=lambda n: (n.pose.x, n.pose.y))
    start = endpoint_nodes[0].id
    goal = endpoint_nodes[-1].id
    path = plan_astar(graph, start, goal)
    print(f"planned {start} -> {goal} via {len(path)} nodes")

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    bare = IMAGE_DIR / "05_occupancy_graph.png"
    routed = IMAGE_DIR / "06_occupancy_graph_with_path.png"

    plot_graph(
        graph,
        title="occupancy grid -> topology graph",
        occupancy_grid=grid,
        resolution=RESOLUTION,
        show_labels=False,
        save_path=str(bare),
    )
    plot_graph(
        graph,
        path=path,
        title=f"planned path: {start} -> {goal}",
        occupancy_grid=grid,
        resolution=RESOLUTION,
        show_labels=False,
        save_path=str(routed),
    )

    import matplotlib.pyplot as plt

    plt.close("all")
    print(f"saved {bare.relative_to(Path.cwd()) if bare.is_absolute() else bare}")
    print(f"saved {routed.relative_to(Path.cwd()) if routed.is_absolute() else routed}")


if __name__ == "__main__":
    main()
