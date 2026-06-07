"""README hero — fleet coordination: who gets granted, and why.

The third of the three-axis heroes (Resolve · Plan · **Coordinate**),
rendered in the same three-panel style as the visual and language heroes
so the front page reads as a set:

  * **left**  — the fleet *requests*: five agents on one 10-node chain,
    each claiming a segment. Submission order is adversarial — the
    long-haul `alpha` (the whole chain) is listed first;
  * **middle** — the *decision*: how many of the five each strategy
    grants, as a bar chart (the same shape as the other heroes' score
    bars). `greedy`/`priority` grant 1; `bnb`/`exhaustive` grant 4;
  * **right** — the *outcome* for the strategy currently in focus: the
    granted agents' segments drawn on the chain, the denied ones listed.

Cycling the strategies makes the lever visible: a naive submission-order
planner grants only the long-haul (1/5, locking everyone out), while a
reordering planner holds it back so four short-haul agents tile the chain
in disjoint segments (4/5). Every number is real output from
`plan_fleet_with_strategy` on an identically-seeded `SharedScheduler`.

    pip install -e '.[viz]'
    python examples/record_coordination_hero.py

Pure-Python core plus matplotlib; no model, no API key.
"""

from __future__ import annotations

import io
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
from semantic_toponav.graph.types import Pose2D

ROOT = Path(__file__).parent.parent
IMAGE_DIR = ROOT / "docs" / "images"
OUT_GIF = IMAGE_DIR / "27_coordination_hero.gif"

CHAIN_N = 10
STRATEGIES = ["greedy", "priority", "bnb", "exhaustive"]
# agent display name, full id, start, goal, priority, color.
AGENTS = [
    ("alpha", "alpha (n0→n9)", "n0", "n9", 5, "#ef4444"),
    ("beta", "beta (n0→n2)", "n0", "n2", 0, "#3b82f6"),
    ("gamma", "gamma (n3→n4)", "n3", "n4", 0, "#16a34a"),
    ("delta", "delta (n5→n6)", "n5", "n6", 0, "#a855f7"),
    ("epsilon", "epsilon (n7→n9)", "n7", "n9", 0, "#f97316"),
]
_COLOR = {a[1]: a[5] for a in AGENTS}
_SHORT = {a[1]: a[0] for a in AGENTS}

GIF_FRAME_MS = 1500
GIF_PAYOFF_MS = 2100   # linger on the reordering payoff (bnb / exhaustive)
GIF_LOOP = 0


def _build_graph():
    graph = chain_graph(CHAIN_N)
    for i, node in enumerate(sorted(graph.nodes(), key=lambda n: int(n.id[1:]))):
        node.pose = Pose2D(float(i), 0.0)
    return graph


def _requests() -> list[FleetRequest]:
    return [
        FleetRequest(agent_id=full, start=s, goal=g, priority=p)
        for _, full, s, g, p, _ in AGENTS
    ]


def _idx(node_id: str) -> int:
    return int(node_id[1:])


def _run(graph, strategy: str, requests):
    scheduler = SharedScheduler()
    result = plan_fleet_with_strategy(
        graph, requests, scheduler, strategy=strategy,
        hold_start=dtime(10, 0), hold_end=dtime(11, 0),
    )
    granted = [r.agent_id for r in result.results if r.granted]
    denied = [r.agent_id for r in result.results if not r.granted]
    return granted, denied


def _draw_requests(ax) -> None:
    ax.set_title("fleet requests · 10-node chain, 5 agents",
                 fontsize=11, fontweight="bold")
    ax.set_xlim(-1.4, CHAIN_N - 0.5)
    ax.set_ylim(-0.7, len(AGENTS) - 0.3)
    # chain ruler.
    ax.plot([0, CHAIN_N - 1], [-0.4, -0.4], "-", color="#cbd5e1", lw=1.4, zorder=1)
    for i in range(CHAIN_N):
        ax.scatter([i], [-0.4], s=22, c="#e2e8f0", edgecolor="#cbd5e1",
                   linewidth=0.8, zorder=2)
        ax.text(i, -0.62, f"n{i}", ha="center", va="top", fontsize=6.5,
                color="#94a3b8")
    for row, (short, _full, s, g, _p, color) in enumerate(AGENTS):
        y = len(AGENTS) - 1 - row
        x0, x1 = _idx(s), _idx(g)
        ax.plot([x0, x1], [y, y], "-", color=color, lw=7.0,
                solid_capstyle="round", alpha=0.9, zorder=3)
        ax.scatter([x0, x1], [y, y], s=46, c=color, edgecolor="white",
                   linewidth=1.0, zorder=4)
        ax.text(-1.3, y, short, ha="left", va="center", fontsize=9.5,
                fontweight="bold", color=color)
        if short == "alpha":
            ax.text((x0 + x1) / 2, y + 0.18, "long-haul · listed first",
                    ha="center", va="bottom", fontsize=7.5, color="#7f1d1d",
                    fontstyle="italic")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def _draw_grant_bars(ax, counts: dict[str, int], focus: str) -> None:
    ypos = list(range(len(STRATEGIES)))[::-1]
    vals = [counts[s] for s in STRATEGIES]
    colors = ["#f59e0b" if s == focus else "#cbd5e1" for s in STRATEGIES]
    ax.barh(ypos, vals, color=colors, edgecolor="#475569", linewidth=0.8,
            zorder=2)
    for y, v in zip(ypos, vals, strict=False):
        ax.text(v + 0.12, y, f"{v}/5", va="center", fontsize=9,
                color="#334155", fontweight="bold")
    ax.set_yticks(ypos)
    ax.set_yticklabels(STRATEGIES, fontsize=9.5)
    ax.set_xlim(0, 5.0)
    ax.set_xticks(range(6))
    ax.set_xlabel("agents granted (of 5)", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.set_title("granted per strategy", fontsize=11, fontweight="bold")
    ax.grid(True, axis="x", color="#eef2f7", zorder=0)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)


def _draw_outcome(ax, granted: list[str], denied: list[str], focus: str,
                  max_granted: int) -> None:
    ax.set_xlim(-0.8, CHAIN_N - 0.5)
    ax.set_ylim(-1.5, len(AGENTS) - 0.3)
    # chain nodes.
    ax.plot([0, CHAIN_N - 1], [0, 0], "-", color="#cbd5e1", lw=1.4, zorder=1)
    for i in range(CHAIN_N):
        ax.scatter([i], [0], s=42, c="#f1f5f9", edgecolor="#cbd5e1",
                   linewidth=1.0, zorder=2)
        ax.text(i, -0.22, f"n{i}", ha="center", va="top", fontsize=6.5,
                color="#94a3b8")
    # granted segments, offset-stacked above the chain.
    for row, full in enumerate(granted):
        y = 0.55 + row * 0.55
        color = _COLOR[full]
        a = next(ag for ag in AGENTS if ag[1] == full)
        x0, x1 = _idx(a[2]), _idx(a[3])
        ax.plot([x0, x1], [y, y], "-", color=color, lw=6.5,
                solid_capstyle="round", alpha=0.9, zorder=3)
        ax.scatter([x0], [y], marker="s", s=70, c=color, edgecolor="black",
                   linewidth=0.8, zorder=4)
        ax.scatter([x1], [y], marker="*", s=150, c=color, edgecolor="black",
                   linewidth=0.8, zorder=4)
        ax.text((x0 + x1) / 2, y + 0.12, _SHORT[full], ha="center",
                va="bottom", fontsize=8, color=color, fontweight="bold")
    if denied:
        ax.text(0, -1.05, "denied: " + ", ".join(_SHORT[d] for d in denied),
                ha="left", va="center", fontsize=8.5, color="#b91c1c")

    n_granted = len(granted)
    is_best = n_granted == max_granted
    ax.set_title(f"{focus}: {n_granted}/5 granted", fontsize=11,
                 fontweight="bold",
                 color="#16a34a" if is_best else "#b91c1c")
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def render_frame(counts, focus, granted, denied, max_granted) -> Image.Image:
    fig, (axr, axb, axo) = plt.subplots(
        1, 3, figsize=(13.2, 4.6), dpi=100,
        gridspec_kw={"width_ratios": [1.15, 0.9, 1.15]},
    )
    _draw_requests(axr)
    _draw_grant_bars(axb, counts, focus)
    _draw_outcome(axo, granted, denied, focus, max_granted)
    fig.suptitle(
        "semantic-toponav · fleet requests → strategy decision → who gets "
        "the chain (greedy 1/5 vs branch-and-bound 4/5)",
        fontsize=12.5, fontweight="bold", y=0.98,
    )
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.93))
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def main() -> None:
    graph = _build_graph()
    requests = _requests()
    outcomes = {s: _run(graph, s, requests) for s in STRATEGIES}
    counts = {s: len(outcomes[s][0]) for s in STRATEGIES}
    max_granted = max(counts.values())
    print("strategy → granted:", counts)

    frames: list[Image.Image] = []
    durations: list[int] = []
    for s in STRATEGIES:
        granted, denied = outcomes[s]
        frames.append(render_frame(counts, s, granted, denied, max_granted))
        durations.append(GIF_PAYOFF_MS if counts[s] == max_granted
                         else GIF_FRAME_MS)

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    frames[0].save(OUT_GIF, save_all=True, append_images=frames[1:],
                   duration=durations, loop=GIF_LOOP, optimize=True)
    size_kb = OUT_GIF.stat().st_size / 1024
    print(f"wrote {OUT_GIF.relative_to(ROOT)} ({size_kb:.0f} KB, "
          f"{len(frames)} frames)")


if __name__ == "__main__":
    main()
