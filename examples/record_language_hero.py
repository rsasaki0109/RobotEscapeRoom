"""README hero — language grounding → navigation, in one glance.

The visual hero (``record_visual_hero.py``) answers *"which place do I
see?"*; this is its twin for the **language** axis — *"which place do you
mean?"* — rendered in the same three-panel style so the two read as a
pair:

  * **left**  — the natural-language goal, with the floor and the content
    tokens the resolver pulled out of it;
  * **middle** — the **grounding result**: ``resolve_goal`` scoring every
    node by a bag-of-words + floor-aware match, drawn as a live bar chart
    with the winning node in amber (the same shape as the visual hero's
    CLIP-cosine bars, so "image → place" and "language → place" line up);
  * **right** — the **navigation**: the stacked multi-floor topology with
    the A* route filling in green node-by-node as the robot rides the
    elevator from the entrance up to the grounded goal.

So the reader sees the whole resolve→plan loop —
``"executive office on 3F" → resolve_goal scores → grounded node → A*
route up three floors`` — without reading a word. Every bar and every
green leg is real output from this repo's deterministic resolver and
planner (``resolve_goal`` · ``plan_astar`` + ``prefer_elevator``), not a
mock-up.

    pip install -e '.[viz]'
    python examples/record_language_hero.py

Pure-Python core plus matplotlib; no model, no API key — the resolver is
a bag-of-words scorer by design.
"""

from __future__ import annotations

import io
from pathlib import Path

import matplotlib.pyplot as plt
from PIL import Image

from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.planner import compose_costs, plan_astar, prefer_elevator
from semantic_toponav.query.resolve import _extract_floor, _tokenize, resolve_goal

HERE = Path(__file__).parent
ROOT = HERE.parent
GRAPH_PATH = HERE / "multi_floor_office.yaml"
IMAGE_DIR = ROOT / "docs" / "images"
OUT_GIF = IMAGE_DIR / "26_language_hero.gif"

QUERY = "executive office on 3F"
START_NODE = "entrance"

# Stacked-floor layout: each floor is lifted clear of the one below so the
# elevator column reads as a vertical climb. The in-floor span is ~[-4, 4],
# so a 13 m lift keeps the floors from overlapping.
FLOOR_DY = 13.0

GIF_FRAME_MS = 480     # per route-leg
GIF_INTRO_MS = 1100    # pause on the query + scores before the route draws
GIF_ARRIVE_MS = 1700   # hold the arrived state
GIF_LOOP = 0


def _pos(node) -> tuple[float, float]:
    floor = int(node.properties.get("floor", 1))
    return (node.pose.x, node.pose.y + (floor - 1) * FLOOR_DY)


def _draw_goal(ax, query: str, floor, tokens, winner) -> None:
    ax.axis("off")
    ax.set_title("language goal", fontsize=11, fontweight="bold", loc="left")
    ax.text(
        0.0, 0.90, f"“{query}”", transform=ax.transAxes,
        fontsize=15, fontweight="bold", color="#0f172a", va="top", wrap=True,
    )
    ax.plot([0.0, 1.0], [0.74, 0.74], color="#e2e8f0", lw=1.2,
            transform=ax.transAxes, clip_on=False)
    ax.text(0.0, 0.66, "parsed by resolve_goal", transform=ax.transAxes,
            fontsize=8.5, color="#64748b", va="top")

    # floor + content-token chips, laid out left-to-right on one row
    # (floor chip in blue, content tokens in amber to match the winner bar).
    chips: list[tuple[str, str, str]] = []
    if floor is not None:
        chips.append((f"floor {floor}", "#dbeafe", "#1d4ed8"))
    for tok in tokens:
        chips.append((tok, "#fef3c7", "#b45309"))
    x = 0.0
    for text, fc, ec in chips:
        ax.text(
            x, 0.50, f" {text} ", transform=ax.transAxes, fontsize=10,
            color=ec, va="center", ha="left", fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.3", fc=fc, ec=ec, lw=1.0),
        )
        x += 0.06 + 0.022 * len(text)

    ax.text(0.0, 0.24, "grounded node", transform=ax.transAxes,
            fontsize=8.5, color="#64748b", va="top")
    ax.text(
        0.0, 0.12,
        f"→ {winner.node.label}", transform=ax.transAxes,
        fontsize=14, fontweight="bold", color="#b45309", va="top",
    )
    ax.text(0.0, 0.02, f"   ({winner.node_id})", transform=ax.transAxes,
            fontsize=9, color="#94a3b8", va="top", family="monospace")


def _draw_scores(ax, candidates, winner_id: str) -> None:
    labels = [c.node.label for c in candidates]
    vals = [c.score for c in candidates]
    ypos = list(range(len(candidates)))[::-1]  # best on top
    colors = ["#f59e0b" if c.node_id == winner_id else "#cbd5e1"
              for c in candidates]
    ax.barh(ypos, vals, color=colors, edgecolor="#475569", linewidth=0.8,
            zorder=2)
    for y, v in zip(ypos, vals, strict=False):
        ax.text(v + 0.08, y, f"{v:.0f}", va="center", fontsize=8.5,
                color="#334155")
    ax.set_yticks(ypos)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlim(0.0, max(vals) + 1.0)
    ax.set_xlabel("resolve_goal score (label + floor match)", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.set_title("resolve → node  (bag-of-words + floor)",
                 fontsize=11, fontweight="bold")
    ax.grid(True, axis="x", color="#eef2f7", zorder=0)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)


def _draw_map(ax, graph, route: list[str], filled: int, goal_id: str) -> None:
    pos = {n.id: _pos(n) for n in graph.nodes()}
    # Floor bands + labels.
    for floor in (1, 2, 3):
        y0 = (floor - 1) * FLOOR_DY
        ax.axhspan(y0 - 5.0, y0 + 6.0, color="#f8fafc" if floor % 2 else "#f1f5f9",
                   zorder=0)
        ax.text(-3.4, y0 + 4.6, f"{floor}F", fontsize=11, fontweight="bold",
                color="#cbd5e1", va="center", zorder=1)
    # All edges, faint.
    for e in graph.edges():
        if e.source in pos and e.target in pos:
            (x0, y0), (x1, y1) = pos[e.source], pos[e.target]
            ax.plot([x0, x1], [y0, y1], "-", color="#e2e8f0", lw=1.3, zorder=1)
    # All nodes, faint.
    for n in graph.nodes():
        x, y = pos[n.id]
        ax.scatter([x], [y], s=70, c="#f1f5f9", edgecolor="#cbd5e1",
                   linewidth=1.0, zorder=2)
    # Route: solid green up to `filled`, the rest pending grey.
    rx = [pos[k][0] for k in route]
    ry = [pos[k][1] for k in route]
    ax.plot(rx, ry, "-", color="#94a3b8", lw=2.0, zorder=3)
    if filled > 0:
        ax.plot(rx[:filled + 1], ry[:filled + 1], "-", color="#16a34a",
                lw=3.6, zorder=4)
    robot_idx = min(filled, len(route) - 1)
    for i, k in enumerate(route):
        x, y = pos[k]
        if k == goal_id:
            fc, ec = ("#f59e0b", "#b45309") if filled >= len(route) - 1 else \
                     ("#fde68a", "#d97706")
        elif i <= filled:
            fc, ec = "#16a34a", "#14532d"
        else:
            fc, ec = "#cbd5e1", "#64748b"
        ax.scatter([x], [y], s=300 if k == goal_id else 200, c=fc,
                   edgecolor=ec, linewidth=1.6, zorder=5)
        # Only the start and goal carry labels — the corridor/elevator
        # column in between is self-evident from the floor bands, and
        # labelling every route node collides on the stacked layout.
        if k == START_NODE or k == goal_id:
            ax.annotate(graph.get_node(k).label, (x, y),
                        textcoords="offset points", xytext=(0, 12),
                        ha="center", fontsize=9, color=ec, fontweight="bold")
    # Robot marker.
    rxr, ryr = pos[route[robot_idx]]
    ax.scatter([rxr], [ryr], marker="o", s=120, c="#2563eb",
               edgecolor="white", linewidth=1.8, zorder=6)

    arrived = filled >= len(route) - 1
    cur_floor = int(graph.get_node(route[robot_idx]).properties.get("floor", 1))
    banner = ("ARRIVED · Executive Office (3F)" if arrived
              else f"riding the route → {cur_floor}F")
    ax.set_title(banner, fontsize=11, fontweight="bold",
                 color="#16a34a" if arrived else "#b91c1c")
    ax.set_xlim(-4.0, 14.0)
    ax.set_ylim(-6.0, 2 * FLOOR_DY + 7.0)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def render_frame(graph, *, query, floor, tokens, candidates, winner,
                 route, filled) -> Image.Image:
    fig, (axg, axs, axm) = plt.subplots(
        1, 3, figsize=(13.2, 4.6), dpi=100,
        gridspec_kw={"width_ratios": [1.05, 1.05, 1.05]},
    )
    _draw_goal(axg, query, floor, tokens, winner)
    _draw_scores(axs, candidates, winner.node_id)
    _draw_map(axm, graph, route, filled, winner.node_id)
    fig.suptitle(
        "semantic-toponav · language goal → resolve_goal scores → "
        "grounded node → A* route",
        fontsize=13, fontweight="bold", y=0.98,
    )
    # Fixed-size canvas: a variable banner string would change the
    # `bbox_inches="tight"` crop frame-to-frame and corrupt the GIF, so
    # we lay out within a constant figure and save at the constant size.
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.93))
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def main() -> None:
    graph = load_graph(str(GRAPH_PATH))
    candidates = resolve_goal(graph, QUERY, top_k=5)
    if not candidates:
        raise RuntimeError(f"query did not resolve: {QUERY!r}")
    winner = candidates[0]
    floor, residual = _extract_floor(QUERY)
    tokens = _tokenize(residual)
    route = plan_astar(graph, START_NODE, winner.node_id,
                       cost_fn=compose_costs(prefer_elevator))
    print(f"query {QUERY!r} -> {winner.node_id} (score {winner.score:.0f})")
    print("route: " + " -> ".join(route))

    # One unique frame per route state (filled = 0 .. len-1). Holds are
    # done with per-frame durations rather than duplicate frames, which
    # `optimize=True` would collapse anyway.
    frames: list[Image.Image] = []
    durations: list[int] = []
    for filled in range(len(route)):
        frames.append(render_frame(graph, query=QUERY, floor=floor,
                                    tokens=tokens, candidates=candidates,
                                    winner=winner, route=route, filled=filled))
        if filled == 0:
            durations.append(GIF_INTRO_MS)
        elif filled == len(route) - 1:
            durations.append(GIF_ARRIVE_MS)
        else:
            durations.append(GIF_FRAME_MS)

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    frames[0].save(OUT_GIF, save_all=True, append_images=frames[1:],
                   duration=durations, loop=GIF_LOOP, optimize=True)
    size_kb = OUT_GIF.stat().st_size / 1024
    print(f"wrote {OUT_GIF.relative_to(ROOT)} ({size_kb:.0f} KB, "
          f"{len(frames)} frames)")


if __name__ == "__main__":
    main()
