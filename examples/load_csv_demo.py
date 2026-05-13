"""Load trajectory CSV and convert to a topology graph.

Run from the repository root:

    python examples/load_csv_demo.py

Reads ``examples/sample_trajectories.csv`` (three named runs over a
T-shaped corridor), runs :func:`topology_from_trajectories`, plans a
short path, and writes a figure to ``docs/images/``.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from semantic_toponav.conversion import (
    load_trajectories_from_csv,
    topology_from_trajectories,
)
from semantic_toponav.planner import plan_dijkstra
from semantic_toponav.visualization import plot_graph

HERE = Path(__file__).parent
IMAGE_DIR = HERE.parent / "docs" / "images"
CSV_PATH = HERE / "sample_trajectories.csv"


def main() -> None:
    trajectories = load_trajectories_from_csv(CSV_PATH)
    total = sum(len(t) for t in trajectories)
    print(f"loaded {CSV_PATH.name}: {len(trajectories)} trajectories, {total} points")

    graph = topology_from_trajectories(trajectories, eps=1.5, min_samples=2)
    print(f"converted: {len(graph.node_ids())} nodes, {len(graph.edge_ids())} edges")

    # Plan between the two waypoints with the most extreme x.
    sorted_nodes = sorted(graph.nodes(), key=lambda n: n.pose.x)
    start = sorted_nodes[0].id
    goal = sorted_nodes[-1].id
    path = plan_dijkstra(graph, start, goal)
    print(f"planned {start} -> {goal} via {len(path)} nodes")

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    out = IMAGE_DIR / "13_csv_trajectory.png"

    fig, ax = plt.subplots(figsize=(11, 7))
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c"]
    for i, t in enumerate(trajectories):
        xs = [p[0] for p in t]
        ys = [p[1] for p in t]
        ax.scatter(
            xs, ys, s=8, alpha=0.4, color=colors[i % len(colors)],
            label=f"traj {i+1}", zorder=0,
        )
    plot_graph(
        graph,
        path=path,
        title=f"CSV -> topology: {start} -> {goal}",
        ax=ax,
        show_labels=False,
    )
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"saved {out.relative_to(Path.cwd()) if out.is_absolute() else out}")


if __name__ == "__main__":
    main()
