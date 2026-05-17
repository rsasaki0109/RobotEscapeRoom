"""Coordination strategy comparison demo (PNG + cycling GIF).

Run from the repository root:

    pip install -e '.[viz]'
    python examples/coordination_strategies_demo.py

What it does
------------
Builds a contended fleet scenario on a 10-node ``chain_graph``
arranged so that submission order is the *worst* possible choice —
the first agent in the list is a long-haul that claims every node
on the chain. A naive greedy planner therefore grants exactly one
agent. A reordering planner (BnB or exhaustive MIS) discovers that
holding the long-haul back and granting four short-haul agents
instead is strictly better, and reaches a grant rate of 4/5.

Four strategies are run against an identically-seeded
:class:`SharedScheduler`:

* ``greedy``      — submission-order, the sequential baseline
* ``priority``    — sort by ``FleetRequest.priority`` DESC first
* ``bnb``         — branch-and-bound search over orderings
* ``exhaustive``  — 2^n MIS upper bound (ground truth for grant count)

For each strategy the output is the same graph with every granted
agent's path overlaid in a distinct color and a short title
``"strategy: G/N granted"``. Denied agents are listed underneath.

Two artifacts under ``docs/images/``:

* ``16_coordination_strategies.png`` — 2x2 grid, paper-figure style.
* ``17_coordination_cycle.gif`` — cycling animation through the
  four strategies (1.8 s per frame).

The figures make the BnB vs greedy gap visible: greedy grants 1/5
on this scenario (submission order locks the long-haul agent in
first, blocking everything else), while BnB and exhaustive grant
4/5 by holding the long-haul back so the four short-haul agents
can fit in disjoint chain segments.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from datetime import time as dtime
from pathlib import Path

import matplotlib.pyplot as plt
from PIL import Image

from semantic_toponav.coordination import (
    FleetRequest,
    SharedScheduler,
    plan_fleet_with_strategy,
)
from semantic_toponav.eval.generators import chain_graph
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D
from semantic_toponav.visualization.plot import plot_graph

HERE = Path(__file__).parent
IMAGE_DIR = HERE.parent / "docs" / "images"
OVERVIEW_PNG = IMAGE_DIR / "16_coordination_strategies.png"
CYCLE_GIF = IMAGE_DIR / "17_coordination_cycle.gif"

FRAME_W, FRAME_H = 7.0, 5.0
FRAME_DPI = 110
GIF_FRAME_MS = 1800
GIF_LOOP = 0

# A palette of distinguishable colors for up to ~8 agents.
AGENT_COLORS = [
    "#ef4444",  # red
    "#3b82f6",  # blue
    "#16a34a",  # green
    "#a855f7",  # purple
    "#f97316",  # orange
    "#0891b2",  # teal
    "#db2777",  # magenta
    "#ca8a04",  # gold
]


@dataclass
class StrategyOutcome:
    name: str
    granted: list[tuple[str, list[str], str]]  # (agent_id, path, color)
    denied: list[str]


def _build_requests() -> list[FleetRequest]:
    """5 agents on a 10-node chain — submission order is intentionally bad.

    Alpha is a long-haul (n0..n9) listed first so the greedy planner
    grants it and locks every other agent out. Beta/gamma/delta/epsilon
    occupy disjoint short segments and would all fit *if* alpha were
    held back — which is exactly the reordering BnB / exhaustive find.

    Priority values are set so the priority-ordered run still locks
    alpha in first (priority 5 vs others 0); this isolates the BnB
    reordering as the lever that actually frees the four short
    agents.
    """
    return [
        FleetRequest(agent_id="alpha (n0→n9)",   start="n0", goal="n9", priority=5),
        FleetRequest(agent_id="beta (n0→n2)",    start="n0", goal="n2", priority=0),
        FleetRequest(agent_id="gamma (n3→n4)",   start="n3", goal="n4", priority=0),
        FleetRequest(agent_id="delta (n5→n6)",   start="n5", goal="n6", priority=0),
        FleetRequest(agent_id="epsilon (n7→n9)", start="n7", goal="n9", priority=0),
    ]


def _run_strategy(
    graph: TopologyGraph, strategy: str, requests: list[FleetRequest]
) -> StrategyOutcome:
    """Run one strategy on a fresh scheduler and collect granted/denied."""
    scheduler = SharedScheduler()
    fleet_result = plan_fleet_with_strategy(
        graph,
        requests,
        scheduler,
        strategy=strategy,
        hold_start=dtime(10, 0),
        hold_end=dtime(11, 0),
    )
    granted: list[tuple[str, list[str], str]] = []
    denied: list[str] = []
    color_lookup = {req.agent_id: AGENT_COLORS[i % len(AGENT_COLORS)]
                    for i, req in enumerate(requests)}
    for r in fleet_result.results:
        if r.granted:
            granted.append((r.agent_id, list(r.path), color_lookup[r.agent_id]))
        else:
            denied.append(r.agent_id)
    return StrategyOutcome(name=strategy, granted=granted, denied=denied)


def _overlay_paths(ax, graph: TopologyGraph, outcome: StrategyOutcome) -> None:
    """Draw the base graph, then overlay each granted agent's path in its color.

    For the chain layout (y == 0 for every node) we offset each agent's
    path vertically by a small stride so overlapping segments stay
    visually distinguishable.
    """
    plot_graph(
        graph,
        ax=ax,
        show_labels=True,
        show_edge_ids=False,
    )

    Y_STRIDE = 0.25
    for idx, (agent_id, path, color) in enumerate(outcome.granted):
        y_offset = (idx + 1) * Y_STRIDE
        for a, b in zip(path[:-1], path[1:], strict=False):
            na = graph.get_node(a)
            nb = graph.get_node(b)
            ax.plot(
                [na.pose.x, nb.pose.x],
                [na.pose.y + y_offset, nb.pose.y + y_offset],
                color=color,
                linewidth=4.5,
                solid_capstyle="round",
                alpha=0.85,
                zorder=3,
            )
        start_node = graph.get_node(path[0])
        goal_node = graph.get_node(path[-1])
        ax.scatter(
            [start_node.pose.x], [start_node.pose.y + y_offset],
            marker="s", s=130, c=color,
            edgecolors="black", linewidths=1.0, zorder=6,
        )
        ax.scatter(
            [goal_node.pose.x], [goal_node.pose.y + y_offset],
            marker="*", s=220, c=color,
            edgecolors="black", linewidths=1.0, zorder=6,
        )
        ax.text(
            (start_node.pose.x + goal_node.pose.x) / 2.0,
            y_offset + 0.08,
            agent_id,
            ha="center", va="bottom", fontsize=8, color=color,
            fontweight="bold", zorder=7,
        )

    granted_count = len(outcome.granted)
    n_total = granted_count + len(outcome.denied)
    title = f"{outcome.name}: {granted_count}/{n_total} granted"
    if outcome.denied:
        title += "\ndenied: " + ", ".join(outcome.denied)
    ax.set_title(title, fontsize=10)
    # plot_graph fixes aspect=equal, which forces y to mirror x and
    # blows up the figure. Restore auto-aspect + a tight y-range
    # around the offset stack.
    ax.set_aspect("auto")
    ax.set_ylim(-0.6, max(1.8, (len(outcome.granted) + 1) * Y_STRIDE + 0.3))


def _render_frame(graph: TopologyGraph, outcome: StrategyOutcome) -> Image.Image:
    """Render one strategy as an in-memory PIL frame for the GIF."""
    fig, ax = plt.subplots(figsize=(FRAME_W, FRAME_H), dpi=FRAME_DPI)
    _overlay_paths(ax, graph, outcome)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=FRAME_DPI, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("P", palette=Image.ADAPTIVE)


def _attach_chain_poses(graph: TopologyGraph) -> TopologyGraph:
    """Lay the chain horizontally so each node sits on a tidy x-axis grid.

    :func:`chain_graph` from :mod:`semantic_toponav.eval.generators`
    builds a pose-less topology suitable for coordination evals; the
    renderer needs poses, so we materialize an x = index, y = 0 layout
    here. ``_ = math`` keeps the import alive for callers that swap
    the layout for something fancier.
    """
    nodes = sorted(graph.nodes(), key=lambda n: int(n.id[1:]))
    for i, node in enumerate(nodes):
        node.pose = Pose2D(float(i), 0.0)
    _ = math  # reserved for callers that want a non-linear layout
    return graph


def main() -> None:
    graph = _attach_chain_poses(chain_graph(10))
    requests = _build_requests()

    strategies = ["greedy", "priority", "bnb", "exhaustive"]
    outcomes = [_run_strategy(graph, s, requests) for s in strategies]

    grant_counts = [len(o.granted) for o in outcomes]
    print(f"strategy → grant count: "
          f"{dict(zip(strategies, grant_counts, strict=False))}")

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    # ---- 1) Static 2x2 PNG ------------------------------------------------
    fig, axes = plt.subplots(2, 2, figsize=(FRAME_W * 2.05, FRAME_H * 2.05), dpi=FRAME_DPI)
    for ax, outcome in zip(axes.flat, outcomes, strict=False):
        _overlay_paths(ax, graph, outcome)
    n_agents = len(requests)
    fig.suptitle(
        f"Coordination strategies on a 10-node chain "
        f"({n_agents} agents; submission order is intentionally adversarial)",
        fontsize=13, y=1.00,
    )
    fig.tight_layout()
    fig.savefig(OVERVIEW_PNG, dpi=FRAME_DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {OVERVIEW_PNG.relative_to(Path.cwd()) if OVERVIEW_PNG.is_absolute() else OVERVIEW_PNG}")

    # ---- 2) Cycling GIF --------------------------------------------------
    frames = [_render_frame(graph, o) for o in outcomes]
    frames[0].save(
        CYCLE_GIF,
        save_all=True,
        append_images=frames[1:],
        duration=GIF_FRAME_MS,
        loop=GIF_LOOP,
        optimize=True,
    )
    size_kb = CYCLE_GIF.stat().st_size / 1024
    print(f"wrote {CYCLE_GIF.relative_to(Path.cwd()) if CYCLE_GIF.is_absolute() else CYCLE_GIF} "
          f"({size_kb:.0f} KB, {len(frames)} frames)")


if __name__ == "__main__":
    main()
