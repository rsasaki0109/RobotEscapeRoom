"""Visual topological navigation demo — the LM-Nav loop, end to end.

Where ``visual_localization_demo.py`` answers *"which place do I see?"*
frame by frame, this demo closes the navigation loop the way LM-Nav
does, using only this repo's pieces:

1. **Ground the start.** Embed the robot's first frame with a **real
   CLIP** encoder and localize it to a topology node
   (:func:`semantic_toponav.query.localize_by_image`).
2. **Plan on the graph.** A*-search from that grounded start to the goal
   node and expand the route into semantic waypoints
   (:func:`semantic_toponav.query.plan_visual_route`).
3. **Follow by re-localizing.** Replay the drive; for every frame,
   :class:`~semantic_toponav.query.VisualRouteFollower` re-grounds it and
   reports monotonic progress along the committed route.

The actual node-to-node locomotion is *not* in this repo by design
(decision D-16): a learned image-goal policy (ViNT / NoMaD / ViNG) or
Nav2 owns *how to move*; this demo owns *where on the plan the robot has
reached*. So the robot's path here is replayed from the recorded route,
and the interesting signal is the **perception → progress** mapping
drawn on the map.

Each frame renders side by side:
  * left  — the robot's camera view;
  * right — the topology with the planned route, done / current / pending
    waypoints colored in, the robot's position, and a HUD reading out the
    grounded place, the cosine score, and progress ``i/N``.

The frames were rendered offline in Gazebo (the OpenRobotics *Depot*
world, CC-BY 4.0) and downsized into ``examples/data/depot_views/``; the
heavy ROS/Gazebo rig lives out of this pure-Python core. This script
needs only the ``[vlm]`` + ``[viz]`` extras:

    pip install -e '.[vlm,viz]'
    python examples/visual_navigation_demo.py

It downloads the ``openai/clip-vit-base-patch32`` weights on first run.
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
from semantic_toponav.query import VisualRouteFollower, plan_visual_route

HERE = Path(__file__).parent
DATA_DIR = HERE / "data" / "depot_views"
IMAGE_DIR = HERE.parent / "docs" / "images"
OUT_GIF = IMAGE_DIR / "24_visual_navigation.gif"

# Each place: node id, label, type, world (x, y), reference frame.
PLACES = [
    ("bay", "Loading Bay", "area", (-4.0, 0.0), "proto_bay.jpg"),
    ("brick", "Brick Gateway", "doorway", (0.0, 2.0), "proto_brick.jpg"),
    ("drum", "Drum Storage", "room", (3.0, 3.0), "proto_drum.jpg"),
    ("crate", "Crate Aisle", "room", (3.0, -2.0), "proto_crate.jpg"),
    ("util", "Utility Corner", "room", (0.0, -2.0), "proto_util.jpg"),
]
ROUTE_ORDER = ["bay", "brick", "drum", "crate", "util"]
GOAL = "util"

GIF_FRAME_MS = 280
GIF_LOOP = 0

_BY_KEY = {key: (label, xy) for key, label, _, xy, _ in PLACES}


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


def render_frame(
    cam_img: np.ndarray,
    *,
    robot_xy: tuple[float, float],
    route: list[str],
    index: int,
    grounded_key: str,
    score: float,
    reached_goal: bool,
) -> Image.Image:
    """One composite panel: camera view | top-down route + progress HUD."""
    fig, (axc, axm) = plt.subplots(
        1, 2, figsize=(10.0, 3.9), dpi=100,
        gridspec_kw={"width_ratios": [1.33, 1.0]},
    )
    done = set(route[:index])
    current = route[index]

    # --- left: robot camera POV -------------------------------------
    axc.imshow(cam_img)
    axc.set_xticks([])
    axc.set_yticks([])
    axc.set_title("robot camera", fontsize=11, fontweight="bold")
    axc.text(
        0.5, -0.07,
        f"CLIP → {_BY_KEY[grounded_key][0]}  (cos {score:.2f})   "
        f"progress {index + 1}/{len(route)}",
        transform=axc.transAxes, ha="center", va="top",
        fontsize=11, color="#0f172a",
        bbox=dict(boxstyle="round,pad=0.3", fc="#fde68a", ec="#d97706"),
    )

    # --- right: top-down route map ----------------------------------
    xs = [_BY_KEY[k][1][0] for k in route]
    ys = [_BY_KEY[k][1][1] for k in route]
    axm.plot(xs, ys, "-", color="#94a3b8", lw=2.0, zorder=1)
    # Traversed leg drawn solid green up to the current node.
    if index > 0:
        axm.plot(
            xs[: index + 1], ys[: index + 1], "-",
            color="#16a34a", lw=3.2, zorder=2,
        )
    for key, label, _, (x, y), _ in PLACES:
        if key == current:
            fc, ec = "#ef4444", "#7f1d1d"      # current target
        elif key in done:
            fc, ec = "#16a34a", "#14532d"      # already reached
        elif key in route:
            fc, ec = "#cbd5e1", "#64748b"      # pending
        else:
            fc, ec = "#f1f5f9", "#94a3b8"      # off-route
        on = key == current
        axm.scatter(
            [x], [y], s=460 if on else 230, c=fc, edgecolor=ec,
            linewidth=2.0 if on else 1.0, zorder=3,
        )
        axm.annotate(
            label, (x, y), textcoords="offset points", xytext=(0, 13),
            ha="center", fontsize=9,
            fontweight="bold" if on else "normal",
            color=ec,
        )
    axm.scatter(
        [robot_xy[0]], [robot_xy[1]], marker="o", s=140,
        c="#2563eb", edgecolor="white", linewidth=1.8, zorder=5,
    )
    axm.annotate(
        "robot", robot_xy, textcoords="offset points", xytext=(0, -16),
        ha="center", fontsize=8, color="#1d4ed8",
    )
    banner = "GOAL REACHED" if reached_goal else f"→ heading to {_BY_KEY[current][0]}"
    axm.set_title(banner, fontsize=11, fontweight="bold",
                  color="#16a34a" if reached_goal else "#b91c1c")
    axm.set_xlim(-6.0, 5.0)
    axm.set_ylim(-4.5, 5.0)
    axm.set_aspect("equal")
    axm.set_xlabel("x (m)", fontsize=8)
    axm.set_ylabel("y (m)", fontsize=8)
    axm.tick_params(labelsize=7)
    axm.grid(True, color="#eef2f7")

    fig.suptitle(
        "semantic-toponav · visual navigation (localize → plan → follow)",
        fontsize=13, fontweight="bold", y=1.02,
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

    # 1+2. Ground the first frame and plan to the goal.
    start_path = DATA_DIR / "frame00.jpg"
    visual_route = plan_visual_route(graph, start_path, GOAL, backend)
    route = visual_route.route
    print(
        f"grounded start → {visual_route.start.node.id} "
        f"(cos {visual_route.start.score:.3f})"
    )
    print("planned route: " + " -> ".join(route))
    for wp in visual_route.waypoints:
        print(f"    {wp.action:10s} {wp.instruction}")

    # 3. Follow the route by re-localizing each frame.
    follower = VisualRouteFollower(graph, route, backend)
    gif_frames: list[Image.Image] = []
    for i, fm in enumerate(frames_meta):
        cam_path = DATA_DIR / f"frame{i:02d}.jpg"
        cam_img = np.asarray(Image.open(cam_path).convert("RGB"))
        progress = follower.update(cam_path)
        gif_frames.append(
            render_frame(
                cam_img,
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
