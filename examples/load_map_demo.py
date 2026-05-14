"""Load a ROS map_server YAML+PGM bundle and run the conversion + planner.

Run from the repository root:

    python examples/load_map_demo.py

Reads ``examples/sample_map.yaml`` (with the matching PGM), converts to a
topology graph, plans across it, and writes a figure to ``docs/images/``.
"""

from __future__ import annotations

from pathlib import Path

from semantic_toponav.conversion import load_occupancy_map, topology_from_occupancy
from semantic_toponav.planner import plan_astar
from semantic_toponav.visualization import plot_graph

HERE = Path(__file__).parent
IMAGE_DIR = HERE.parent / "docs" / "images"
MAP_YAML = HERE / "sample_map.yaml"


def main() -> None:
    m = load_occupancy_map(MAP_YAML)
    print(
        f"loaded {MAP_YAML.name}: shape={m.shape} "
        f"resolution={m.resolution} origin={m.origin}"
    )

    graph = topology_from_occupancy(
        m.free_mask, resolution=m.resolution, origin=m.origin
    )
    print(
        f"converted: {len(graph.node_ids())} nodes, {len(graph.edge_ids())} edges"
    )

    endpoints = sorted(
        (n for n in graph.nodes() if n.type == "endpoint"),
        key=lambda n: (n.pose.x, n.pose.y),
    )
    if len(endpoints) < 2:
        print("need at least 2 endpoints to demo planning; skipping path overlay")
        path = None
        start = goal = None
    else:
        start = endpoints[0].id
        goal = endpoints[-1].id
        path = plan_astar(graph, start, goal)
        print(f"planned {start} -> {goal} via {len(path)} nodes")

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    out = IMAGE_DIR / "07_sample_map_topology.png"
    plot_graph(
        graph,
        path=path,
        title=(
            f"sample_map.yaml ({m.shape[1]}x{m.shape[0]}px @ {m.resolution} m/px)"
            + (f"  path: {start} -> {goal}" if path else "")
        ),
        occupancy_grid=m.free_mask,
        resolution=m.resolution,
        origin=m.origin,
        show_labels=False,
        save_path=str(out),
    )
    import matplotlib.pyplot as plt

    plt.close("all")
    print(f"saved {out.relative_to(Path.cwd()) if out.is_absolute() else out}")


if __name__ == "__main__":
    main()
