"""Build a topology graph from synthetic trajectory logs.

Run from the repository root:

    python examples/trajectory_to_topology.py

This generates a few overlapping synthetic trajectories that look like a
robot wandering through a T-shaped corridor, converts them via
:func:`semantic_toponav.conversion.topology_from_trajectories`, and saves
a figure showing the raw points alongside the inferred topology graph.
"""

from __future__ import annotations

import random
from pathlib import Path

import matplotlib.pyplot as plt

from semantic_toponav.conversion import topology_from_trajectories
from semantic_toponav.visualization import plot_graph

IMAGE_DIR = Path(__file__).resolve().parents[1] / "docs" / "images"
random.seed(7)


def _walk(points, noise=0.05):
    """Add Gaussian jitter to each point."""
    return [(x + random.gauss(0, noise), y + random.gauss(0, noise)) for x, y in points]


def _line(p0, p1, n=40):
    x0, y0 = p0
    x1, y1 = p1
    return [
        (x0 + (x1 - x0) * t / (n - 1), y0 + (y1 - y0) * t / (n - 1)) for t in range(n)
    ]


def build_trajectories() -> list[list[tuple[float, float]]]:
    """Three traversals over a T-shaped corridor."""
    # Horizontal corridor from (0, 0) to (12, 0); a stub branching south to (6, -6).
    h1 = _line((0.0, 0.0), (12.0, 0.0), n=60)
    h2 = _line((12.0, 0.0), (0.0, 0.0), n=60)
    branch = _line((6.0, 0.0), (6.0, -6.0), n=40)

    # Three trajectories:
    # 1) left -> right (one-way through the top)
    # 2) right -> left (revisit)
    # 3) left -> middle -> branch
    t1 = _walk(h1)
    t2 = _walk(h2)
    t3 = _walk(_line((0.0, 0.0), (6.0, 0.0), n=30) + branch)
    return [t1, t2, t3]


def main() -> None:
    trajectories = build_trajectories()
    print(
        f"input: {len(trajectories)} trajectories with "
        f"{sum(len(t) for t in trajectories)} points"
    )

    graph = topology_from_trajectories(trajectories, eps=1.5, min_samples=2)
    print(f"output: {len(graph.node_ids())} nodes, {len(graph.edge_ids())} edges")

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    out = IMAGE_DIR / "08_trajectory_topology.png"

    fig, ax = plt.subplots(figsize=(11, 7))

    # Raw trajectory points behind the graph.
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c"]
    for i, t in enumerate(trajectories):
        xs = [p[0] for p in t]
        ys = [p[1] for p in t]
        ax.scatter(
            xs, ys, s=8, alpha=0.45, color=colors[i % len(colors)],
            label=f"trajectory {i+1}", zorder=0,
        )

    plot_graph(
        graph,
        title="trajectory log -> topology",
        ax=ax,
        show_labels=False,
    )

    # Highlight high-traversal edges with thicker lines for visual emphasis.
    max_count = max(
        (e.properties.get("traversal_count", 1) for e in graph.edges()),
        default=1,
    )
    for e in graph.edges():
        if e.properties.get("traversal_count", 1) >= max_count and max_count >= 2:
            src = graph.get_node(e.source).pose
            tgt = graph.get_node(e.target).pose
            ax.plot(
                [src.x, tgt.x],
                [src.y, tgt.y],
                color="#9467bd",
                linewidth=3.5,
                alpha=0.5,
                zorder=2,
                solid_capstyle="round",
            )

    ax.legend(loc="lower left", fontsize=8)
    fig.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"saved {out.relative_to(Path.cwd()) if out.is_absolute() else out}")


if __name__ == "__main__":
    main()
