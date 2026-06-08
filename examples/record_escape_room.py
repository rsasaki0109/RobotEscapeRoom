"""Render the Robot Escape Room as a README gallery GIF.

Run from the repository root:

    python examples/record_escape_room.py

Replays the exact escape that ``robot_escape_room.py`` plays — same planner,
same puzzle logic, imported directly — and captures it as a three-panel
animation in the same style as the language / coordination heroes:

  * **left**   — the turn narrative (what T-0 is trying next, plus the
    structural twist when the Floor-3 exit turns out to be a decoy);
  * **middle** — the stacked multi-floor topology with the live A* route
    filling in green leg-by-leg and T-0 riding along;
  * **right**  — the active planner primitives for this world state
    (``block_edges``, ``block_edge_types``, ``avoid_restricted``) and the
    item / riddle checklist.

Writes ``docs/images/robot_escape_room_panels.gif``. For the README
simulation hero use ``record_escape_room_sim.py``.
"""

from __future__ import annotations

import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import robot_escape_room as game  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from PIL import Image  # noqa: E402
from robot_escape_room import (  # noqa: E402
    DECOY_EXIT,
    ITEMS,
    POWER_ITEM,
    RIDDLES,
    TRUE_EXIT,
    UNPOWERED_TYPES,
    World,
    arrive,
    objectives,
    plan,
)

from semantic_toponav.graph.serialization import load_graph  # noqa: E402

game.VERBOSE = False

ROOT = Path(__file__).resolve().parents[1]
GRAPH_PATH = Path(__file__).parent / "robot_escape_room.yaml"
OUT_PATH = ROOT / "docs" / "images" / "robot_escape_room_panels.gif"

FLOOR_DY = 11.0
FLOOR_BAND = {-1: 0, 1: 1, 2: 2, 3: 3}
FLOOR_LABEL = {-1: "B1", 1: "1F", 2: "2F", 3: "3F"}

GIF_INTRO_MS = 2000
GIF_LEG_MS = 520
GIF_ARRIVE_MS = 1100
GIF_TWIST_MS = 2400
GIF_ESCAPE_MS = 2600
GIF_LOOP = 0

NODE_COLORS = {
    "room": "#3b82f6",
    "corridor": "#94a3b8",
    "intersection": "#a78bfa",
    "stairs": "#fb923c",
    "exit": "#22c55e",
    "sealed_exit": "#64748b",
}
ITEM_COLORS = {
    "keycard_blue": "#38bdf8",
    "keycard_red": "#ef4444",
    "power_core": "#facc15",
    "hatch_code": "#34d399",
}
ITEM_NAMES = {
    "keycard_blue": "blue keycard",
    "keycard_red": "red keycard",
    "power_core": "power core",
    "hatch_code": "hatch code",
}


def _pos(node) -> tuple[float, float]:
    floor = int(node.properties.get("floor", 1))
    band = FLOOR_BAND.get(floor, floor)
    return (node.pose.x, node.pose.y + band * FLOOR_DY)


def _active_rules(graph, world) -> list[tuple[str, str, str]]:
    """(name, detail, color) for the primitives panel."""
    rules: list[tuple[str, str, str]] = [
        ("avoid_restricted", "laser grid shortcut", "#d946ef"),
        ("prefer_elevator", "accessibility — ride the lift", "#38bdf8"),
    ]
    locked = [
        edge.id
        for edge in graph.edges()
        if edge.properties.get("lock") and edge.properties["lock"] not in world.items
    ]
    if locked:
        rules.append(("block_edges", f"{len(locked)} locked door(s)", "#ef4444"))
    if POWER_ITEM not in world.items:
        rules.append(("block_edge_types", "unpowered corridor", "#f59e0b"))
    return rules


def _edge_style(graph, edge, world, path_edges):
    if edge.id in path_edges:
        return "#16a34a", 4.2, "solid", 4
    if edge.type in {"stairs_up", "stairs_down"}:
        return "#fb923c", 2.0, (0, (3, 2)), 1
    if edge.type == "restricted":
        return "#d946ef", 2.0, (0, (1, 3)), 1
    if edge.type == "elevator_connection":
        return "#38bdf8", 2.4, "solid", 2
    lock = edge.properties.get("lock")
    if lock and lock not in world.items:
        return "#ef4444", 2.2, (0, (4, 3)), 1
    if edge.type in UNPOWERED_TYPES and POWER_ITEM not in world.items:
        return "#f59e0b", 2.2, (0, (4, 3)), 1
    return "#475569", 1.4, "solid", 1


def _draw_narrative(ax, *, turn: int | None, headline: str, body: str) -> None:
    ax.axis("off")
    ax.set_title("turn narrative", fontsize=11, fontweight="bold", loc="left")
    if turn is not None:
        ax.text(0.0, 0.92, f"Turn {turn}", transform=ax.transAxes,
                fontsize=22, fontweight="bold", color="#f8fafc", va="top")
    ax.text(0.0, 0.72, headline, transform=ax.transAxes,
            fontsize=13, fontweight="bold", color="#fcd34d", va="top", wrap=True)
    ax.plot([0.0, 1.0], [0.62, 0.62], color="#334155", lw=1.0,
            transform=ax.transAxes, clip_on=False)
    ax.text(0.0, 0.54, body, transform=ax.transAxes,
            fontsize=10.5, color="#cbd5e1", va="top", wrap=True)
    ax.text(0.0, 0.04,
            "No scripted route — each turn recomposes the cost stack,\n"
            "asks A* what is reachable, and walks to the nearest lead.",
            transform=ax.transAxes, fontsize=8.5, color="#64748b", va="bottom")


def _draw_primitives(ax, graph, world) -> None:
    ax.axis("off")
    ax.set_title("active planner primitives", fontsize=11, fontweight="bold", loc="left")
    y = 0.88
    for name, detail, color in _active_rules(graph, world):
        ax.text(0.0, y, f"  {name}  ", transform=ax.transAxes,
                fontsize=10, fontweight="bold", color="#0f172a", va="top",
                bbox=dict(boxstyle="round,pad=0.35", fc=color, ec=color, alpha=0.92))
        ax.text(0.0, y - 0.10, detail, transform=ax.transAxes,
                fontsize=9, color="#94a3b8", va="top")
        y -= 0.20

    ax.text(0.0, 0.34, "inventory", transform=ax.transAxes,
            fontsize=9, color="#64748b", va="top")
    y = 0.26
    for item in ITEMS:
        if item in world.items:
            mark, color = "[x]", "#34d399"
        elif item in world.known:
            mark, color = "[ ]", "#f8fafc"
        else:
            mark, color = "[?]", "#64748b"
        ax.text(0.0, y, f"{mark} {ITEM_NAMES[item]}", transform=ax.transAxes,
                fontsize=10, color=color, va="top", family="monospace")
        y -= 0.08

    ax.text(0.0, 0.02, f"riddles {len(world.solved)}/{len(RIDDLES)}",
            transform=ax.transAxes, fontsize=9.5, color="#cbd5e1", va="bottom")


def _draw_map(ax, graph, world, path, filled: int, goal_id: str | None) -> None:
    pos = {n.id: _pos(n) for n in graph.nodes()}

    for floor, band in FLOOR_BAND.items():
        y0 = band * FLOOR_DY
        ax.axhspan(y0 - 5.5, y0 + 6.5,
                   color="#111827" if band % 2 else "#0b1220", zorder=0)
        ax.text(-2.6, y0 + 4.8, FLOOR_LABEL[floor], fontsize=11,
                fontweight="bold", color="#475569", va="center", zorder=1)

    path_edges: set[str] = set()
    if path:
        seg = set(zip(path, path[1:], strict=False))
        for e in graph.edges():
            if (e.source, e.target) in seg or (e.target, e.source) in seg:
                path_edges.add(e.id)

    for e in graph.edges():
        if e.source not in pos or e.target not in pos:
            continue
        x1, y1 = pos[e.source]
        x2, y2 = pos[e.target]
        color, lw, ls, z = _edge_style(graph, e, world, path_edges)
        ax.plot([x1, x2], [y1, y2], color=color, linewidth=lw, linestyle=ls, zorder=z)

    route_idx = min(filled, len(path) - 1) if path else 0
    robot_id = path[route_idx] if path else world.location

    for n in graph.nodes():
        x, y = pos[n.id]
        on_route = path and n.id in path[: filled + 1]
        fc = NODE_COLORS.get(n.type, "#64748b")
        ec = "#14532d" if on_route else "#0f172a"
        size = 360 if n.id == goal_id else 260
        if n.id == DECOY_EXIT:
            size = 300
        ax.scatter([x], [y], s=size, c=fc, edgecolors=ec,
                   linewidths=1.8 if on_route else 1.2, zorder=5)
        if n.id in {world.location, goal_id, DECOY_EXIT, TRUE_EXIT}:
            ax.text(x, y - 1.35, n.label, color="#e2e8f0", fontsize=7.5,
                    ha="center", va="top", zorder=6)
        if n.id == DECOY_EXIT:
            ax.text(x, y + 1.35, "SEALED", color="#fca5a5", fontsize=7,
                    ha="center", va="bottom", fontweight="bold", zorder=6)

    for item, spec in ITEMS.items():
        if item in world.known and item not in world.items:
            x, y = pos[spec["node"]]
            ax.scatter([x], [y + 0.2], marker="*", s=280,
                       c=ITEM_COLORS[item], edgecolors="#0f172a", linewidths=1.0, zorder=7)

    if path:
        rx = [pos[k][0] for k in path]
        ry = [pos[k][1] for k in path]
        ax.plot(rx, ry, "-", color="#334155", lw=2.0, zorder=3)
        if filled > 0:
            ax.plot(rx[: filled + 1], ry[: filled + 1], "-",
                    color="#16a34a", lw=4.0, zorder=4)

    rx, ry = pos[robot_id]
    ax.scatter([rx], [ry], marker="o", s=180, c="#f8fafc",
               edgecolors="#2563eb", linewidths=2.4, zorder=8)
    ax.text(rx, ry, "T-0", color="#0f172a", fontsize=7, fontweight="bold",
            ha="center", va="center", zorder=9)

    if path and goal_id:
        goal = graph.get_node(goal_id).label
        banner = (f"arrived · {goal}" if filled >= len(path) - 1
                  else f"routing → {goal}")
        color = "#16a34a" if filled >= len(path) - 1 else "#38bdf8"
    else:
        banner = f"at {graph.get_node(world.location).label}"
        color = "#94a3b8"
    ax.set_title(banner, fontsize=11, fontweight="bold", color=color)
    ax.set_xlim(-3.0, 31.0)
    ax.set_ylim(-8.0, 3 * FLOOR_DY + 8.0)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)

    legend = [
        Line2D([0], [0], color="#16a34a", lw=4, label="A* route"),
        Line2D([0], [0], color="#ef4444", lw=2, ls="--", label="locked"),
        Line2D([0], [0], color="#f59e0b", lw=2, ls="--", label="unpowered"),
        Line2D([0], [0], color="#d946ef", lw=2, ls=":", label="laser grid"),
        Line2D([0], [0], color="#fb923c", lw=2, ls="--", label="stairs"),
        Line2D([0], [0], color="#38bdf8", lw=2, label="elevator"),
    ]
    ax.legend(handles=legend, loc="lower left", fontsize=7, framealpha=0.2,
              facecolor="#111827", edgecolor="#334155", labelcolor="#e2e8f0")


def _render(graph, world, path, filled, *, turn, headline, body, goal_id) -> Image.Image:
    fig = plt.figure(figsize=(13.4, 5.2), dpi=100, facecolor="#0f172a")
    gs = fig.add_gridspec(1, 3, width_ratios=[1.0, 1.35, 0.95], wspace=0.22)
    ax_n = fig.add_subplot(gs[0, 0], facecolor="#0f172a")
    ax_m = fig.add_subplot(gs[0, 1], facecolor="#0f172a")
    ax_p = fig.add_subplot(gs[0, 2], facecolor="#0f172a")

    _draw_narrative(ax_n, turn=turn, headline=headline, body=body)
    _draw_map(ax_m, graph, world, path, filled, goal_id)
    _draw_primitives(ax_p, graph, world)

    fig.suptitle(
        "semantic-toponav · escape room — every cost function in one self-solving game",
        fontsize=12.5, fontweight="bold", color="#f8fafc", y=0.98,
    )
    fig.subplots_adjust(left=0.04, right=0.98, top=0.90, bottom=0.08, wspace=0.28)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def _append_route_frames(frames, durations, graph, world, path, *, turn, headline, body):
    goal_id = path[-1]
    for filled in range(len(path)):
        frames.append(_render(
            graph, world, path, filled,
            turn=turn, headline=headline, body=body, goal_id=goal_id,
        ))
        durations.append(GIF_LEG_MS)
    frames.append(_render(
        graph, world, path, len(path) - 1,
        turn=turn, headline=headline, body=body, goal_id=goal_id,
    ))
    durations.append(GIF_ARRIVE_MS)


def main() -> None:
    graph = load_graph(GRAPH_PATH)
    world = World()
    frames: list[Image.Image] = []
    durations: list[int] = []

    frames.append(_render(
        graph, world, None, 0,
        turn=None,
        headline="Lockdown.",
        body="A lit EMERGENCY EXIT sign points up to Floor 3 — but is that "
        "really the way out?",
        goal_id=None,
    ))
    durations.append(GIF_INTRO_MS)

    twist_seen = False
    for turn in range(1, 50):
        exit_path = plan(graph, world, TRUE_EXIT)
        if exit_path is not None:
            _append_route_frames(
                frames, durations, graph, world, exit_path,
                turn=turn,
                headline="The real exit is open.",
                body="T-0 turns around and plunges all the way down to the "
                "sublevel — never through the sealed Floor-3 sign.",
            )
            world.location = TRUE_EXIT
            frames.append(_render(
                graph, world, exit_path, len(exit_path) - 1,
                turn=turn,
                headline="FREEDOM.",
                body="Escaped through the Maintenance Exit on B1 — items 4/4, "
                "riddles 3/3.",
                goal_id=TRUE_EXIT,
            ))
            durations.append(GIF_ESCAPE_MS)
            break

        opts = objectives(graph, world)
        if not opts:
            frames.append(_render(
                graph, world, None, 0,
                turn=turn, headline="Stuck.", body="No reachable objective.",
                goal_id=None,
            ))
            durations.append(GIF_ARRIVE_MS)
            break

        _, node, kind, path = opts[0]
        label = graph.get_node(node).label
        verb = "Decode the riddle at" if kind.startswith("riddle") else "Reach"
        _append_route_frames(
            frames, durations, graph, world, path,
            turn=turn,
            headline=f"{verb} {label}",
            body="Live A* over the current cost stack — keycards, power, and "
            "the laser grid all apply.",
        )

        items_before = set(world.items)
        solved_before = set(world.solved)
        world.location = node
        arrive(graph, world, node)

        gained = world.items - items_before
        solved = world.solved - solved_before
        notes: list[str] = []
        if gained:
            notes.append("picked up " + ", ".join(ITEM_NAMES[i] for i in sorted(gained)))
        if solved:
            notes.append("riddle solved")
        if notes:
            frames.append(_render(
                graph, world, None, 0,
                turn=turn,
                headline="World state changed.",
                body="; ".join(notes) + " — re-planning on the next turn.",
                goal_id=None,
            ))
            durations.append(GIF_ARRIVE_MS)

        if not twist_seen and "riddle_3" in world.solved:
            twist_seen = True
            decoy = graph.get_node(DECOY_EXIT).label
            frames.append(_render(
                graph, world, None, 0,
                turn=turn,
                headline="Plot twist.",
                body=f"The {decoy} is welded shut — the real way out was never "
                "up. T-0 heads for the sublevel.",
                goal_id=DECOY_EXIT,
            ))
            durations.append(GIF_TWIST_MS)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        OUT_PATH,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=GIF_LOOP,
        optimize=True,
        disposal=2,
    )
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"wrote {OUT_PATH.relative_to(ROOT)} ({size_kb:.0f} KB, {len(frames)} frames)")


if __name__ == "__main__":
    main()
