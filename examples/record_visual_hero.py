"""README hero — perception → navigation, in one glance.

This is the *visual-navigation* loop (``visual_navigation_demo.py``)
re-staged as a three-panel hero GIF so a first-time reader sees both
halves of what semantic-toponav does at once:

  * **left**  — the robot's live camera frame (the raw perception input);
  * **middle** — the **image-processing result**: the live frame embedded
    by a real CLIP encoder and scored by cosine similarity against every
    place in the gallery, drawn as a live bar chart with the matched
    reference photo inset. This is the panel the other demos *summarize*
    in one line of text — here it is the picture;
  * **right** — the **navigation**: the topology with the planned A*
    route filling in green place-by-place as each grounded frame advances
    the robot toward the goal.

So the reader sees the pipeline end to end —
``camera frame → CLIP cosine → grounded node → route progress`` — without
reading a word. It reuses exactly the same pieces as the other visual
demos (``localize_by_image`` for the per-frame scores,
``plan_visual_route`` + ``VisualRouteFollower`` for the route and
progress), so the hero is not a mock-up: every bar and every green leg is
real CLIP output on the Gazebo *Depot* frames.

    pip install -e '.[vlm,viz]'
    python examples/record_visual_hero.py

Downloads ``openai/clip-vit-base-patch32`` on first run; needs only the
``[vlm]`` + ``[viz]`` extras (the heavy ROS/Gazebo rig that recorded the
frames lives out of this pure-Python core).
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

from semantic_toponav.encoders.backends import CLIPBackend
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode
from semantic_toponav.query import (
    VisualRouteFollower,
    localize_by_image,
    plan_visual_route,
)

HERE = Path(__file__).parent
DATA_DIR = HERE / "data" / "depot_views"
IMAGE_DIR = HERE.parent / "docs" / "images"
OUT_GIF = IMAGE_DIR / "25_visual_hero.gif"

# node id, label, type, world (x, y), reference frame.
PLACES = [
    ("bay", "Loading Bay", "area", (-4.0, 0.0), "proto_bay.jpg"),
    ("brick", "Brick Gateway", "doorway", (0.0, 2.0), "proto_brick.jpg"),
    ("drum", "Drum Storage", "room", (3.0, 3.0), "proto_drum.jpg"),
    ("crate", "Crate Aisle", "room", (3.0, -2.0), "proto_crate.jpg"),
    ("util", "Utility Corner", "room", (0.0, -2.0), "proto_util.jpg"),
]
ROUTE_ORDER = ["bay", "brick", "drum", "crate", "util"]
GOAL = "util"

GIF_FRAME_MS = 300
GIF_LOOP = 0

_BY_KEY = {key: (label, xy, proto) for key, label, _, xy, proto in PLACES}
# Fixed top-to-bottom order for the cosine bars so they never reshuffle.
_BAR_ORDER = ROUTE_ORDER


def build_graph(backend: CLIPBackend) -> TopologyGraph:
    """Topology graph with CLIP gallery embeddings and a traversable chain."""
    graph = TopologyGraph()
    for key, label, ntype, (x, y), proto in PLACES:
        vec = backend.embed_image(str(DATA_DIR / proto))
        graph.add_node(
            TopologyNode(
                id=key,
                label=label,
                type=ntype,
                pose=Pose2D(x, y),
                properties={"embedding": vec},
            )
        )
    for a, b in zip(ROUTE_ORDER, ROUTE_ORDER[1:], strict=False):
        graph.add_edge(
            TopologyEdge(id=f"{a}_{b}", source=a, target=b, type="traversable")
        )
    return graph


def _draw_camera(ax, cam_img: np.ndarray) -> None:
    ax.imshow(cam_img)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title("robot camera (live)", fontsize=11, fontweight="bold")


def _draw_perception(
    ax, scores: dict[str, float], grounded_key: str, score: float
) -> None:
    """Middle panel: cosine bars vs the gallery + matched reference inset."""
    labels = [_BY_KEY[k][0] for k in _BAR_ORDER]
    vals = [scores.get(k, 0.0) for k in _BAR_ORDER]
    ypos = list(range(len(_BAR_ORDER)))[::-1]  # first place on top
    colors = [
        "#f59e0b" if k == grounded_key else "#cbd5e1" for k in _BAR_ORDER
    ]
    ax.barh(ypos, vals, color=colors, edgecolor="#475569", linewidth=0.8, zorder=2)
    for y, k, v in zip(ypos, _BAR_ORDER, vals, strict=False):
        # The winner's score is shown in the matched-reference inset title,
        # and its bar runs under that inset — skip the (occluded) duplicate.
        if k == grounded_key:
            continue
        ax.text(v + 0.012, y, f"{v:.2f}", va="center", fontsize=8, color="#334155")
    ax.set_yticks(ypos)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlim(0.0, 1.0)
    ax.set_xlabel("CLIP cosine vs gallery", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.set_title("image → place  (CLIP)", fontsize=11, fontweight="bold")
    ax.grid(True, axis="x", color="#eef2f7", zorder=0)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    # Matched reference photo, inset top-right, so "image processing
    # result" is concrete: this live frame ≈ this stored place photo.
    proto = _BY_KEY[grounded_key][2]
    ref = np.asarray(Image.open(DATA_DIR / proto).convert("RGB"))
    axr = ax.inset_axes([0.46, 0.60, 0.52, 0.42])
    axr.imshow(ref)
    axr.set_xticks([])
    axr.set_yticks([])
    for spine in axr.spines.values():
        spine.set_edgecolor("#f59e0b")
        spine.set_linewidth(2.0)
    axr.set_title(
        f"≈ {_BY_KEY[grounded_key][0]}  ({score:.2f})",
        fontsize=8, color="#b45309", fontweight="bold", pad=2,
    )


def _draw_map(
    ax,
    *,
    robot_xy: tuple[float, float],
    route: list[str],
    index: int,
    reached_goal: bool,
) -> None:
    done = set(route[:index])
    current = route[index]
    xs = [_BY_KEY[k][1][0] for k in route]
    ys = [_BY_KEY[k][1][1] for k in route]
    ax.plot(xs, ys, "-", color="#94a3b8", lw=2.0, zorder=1)
    if index > 0:
        ax.plot(
            xs[: index + 1], ys[: index + 1], "-",
            color="#16a34a", lw=3.4, zorder=2,
        )
    for key, label, _, (x, y), _ in PLACES:
        if key == current:
            fc, ec = "#ef4444", "#7f1d1d"
        elif key in done:
            fc, ec = "#16a34a", "#14532d"
        elif key in route:
            fc, ec = "#cbd5e1", "#64748b"
        else:
            fc, ec = "#f1f5f9", "#94a3b8"
        on = key == current
        ax.scatter(
            [x], [y], s=470 if on else 230, c=fc, edgecolor=ec,
            linewidth=2.0 if on else 1.0, zorder=3,
        )
        ax.annotate(
            label, (x, y), textcoords="offset points", xytext=(0, 13),
            ha="center", fontsize=9,
            fontweight="bold" if on else "normal", color=ec,
        )
    ax.scatter(
        [robot_xy[0]], [robot_xy[1]], marker="o", s=150,
        c="#2563eb", edgecolor="white", linewidth=1.8, zorder=5,
    )
    ax.annotate(
        "robot", robot_xy, textcoords="offset points", xytext=(0, -16),
        ha="center", fontsize=8, color="#1d4ed8",
    )
    banner = (
        "GOAL REACHED"
        if reached_goal
        else f"→ heading to {_BY_KEY[current][0]}"
    )
    ax.set_title(
        banner, fontsize=11, fontweight="bold",
        color="#16a34a" if reached_goal else "#b91c1c",
    )
    ax.set_xlim(-6.0, 5.0)
    ax.set_ylim(-4.5, 5.0)
    ax.set_aspect("equal")
    ax.set_xlabel("x (m)", fontsize=8)
    ax.set_ylabel("y (m)", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.grid(True, color="#eef2f7")


def render_frame(
    cam_img: np.ndarray,
    *,
    scores: dict[str, float],
    robot_xy: tuple[float, float],
    route: list[str],
    index: int,
    grounded_key: str,
    score: float,
    reached_goal: bool,
) -> Image.Image:
    """One composite: camera | CLIP cosine bars | route + progress."""
    fig, (axc, axp, axm) = plt.subplots(
        1, 3, figsize=(13.2, 4.0), dpi=100,
        gridspec_kw={"width_ratios": [1.25, 1.0, 1.15]},
    )
    _draw_camera(axc, cam_img)
    _draw_perception(axp, scores, grounded_key, score)
    _draw_map(
        axm, robot_xy=robot_xy, route=route, index=index,
        reached_goal=reached_goal,
    )
    fig.suptitle(
        "semantic-toponav · camera frame → CLIP cosine → grounded place → route progress",
        fontsize=13, fontweight="bold", y=1.03,
    )
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def main() -> None:
    meta = json.loads((DATA_DIR / "route_meta.json").read_text())
    frames_meta = meta["frames"]

    print("loading CLIP (openai/clip-vit-base-patch32)…")
    backend = CLIPBackend()
    graph = build_graph(backend)
    print(f"stamped {len(PLACES)} place nodes with CLIP gallery vectors")

    start_path = DATA_DIR / "frame00.jpg"
    visual_route = plan_visual_route(graph, start_path, GOAL, backend)
    route = visual_route.route
    print(
        f"grounded start → {visual_route.start.node.id} "
        f"(cos {visual_route.start.score:.3f})"
    )
    print("planned route: " + " -> ".join(route))

    follower = VisualRouteFollower(graph, route, backend)
    gif_frames: list[Image.Image] = []
    for i, fm in enumerate(frames_meta):
        cam_path = DATA_DIR / f"frame{i:02d}.jpg"
        cam_img = np.asarray(Image.open(cam_path).convert("RGB"))
        # Full per-place cosine scores for the perception bars.
        loc = localize_by_image(graph, cam_path, backend, top_k=len(PLACES))
        scores = {node.id: s for node, s in loc.ranked}
        progress = follower.update(cam_path)
        gif_frames.append(
            render_frame(
                cam_img,
                scores=scores,
                robot_xy=(fm["x"], fm["y"]),
                route=route,
                index=progress.index,
                grounded_key=progress.localized.node.id,
                score=progress.score,
                reached_goal=progress.reached_goal,
            )
        )
        flag = "✓" if progress.advanced else (" " if progress.on_route else "·")
        print(
            f"  frame {i:02d}: grounded={progress.localized.node.id:6s} "
            f"cos={progress.score:.3f} {flag} "
            f"at={progress.current_node.id:6s} ({progress.index + 1}/{len(route)})"
        )

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    gif_frames[0].save(
        OUT_GIF, save_all=True, append_images=gif_frames[1:],
        duration=GIF_FRAME_MS, loop=GIF_LOOP, optimize=True,
    )
    size_kb = OUT_GIF.stat().st_size / 1024
    reached = "yes" if follower.reached_goal else "no"
    print(
        f"\nreached goal {GOAL!r}: {reached}\n"
        f"wrote {OUT_GIF} ({size_kb:.0f} KB, {len(gif_frames)} frames)"
    )


if __name__ == "__main__":
    main()
