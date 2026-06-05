"""Visual localization demo — ground a robot's camera to a topology node.

This is the perception companion to the text-driven resolve demos: it
turns each frame of a robot's forward camera into the topology node it
most likely depicts, using the core
:func:`semantic_toponav.query.localize_by_image` helper with a **real
CLIP** encoder.

Pipeline
--------
1. Build a small topology graph of named places in a warehouse
   (``Loading Bay``, ``Brick Gateway``, ``Drum Storage``,
   ``Crate Aisle``, ``Utility Corner``) connected along a route.
2. Stamp each node with a CLIP embedding of one *reference* frame —
   the "gallery" a mapping pass would have captured at that place.
3. Replay the robot driving the route. For every frame, call
   :func:`localize_by_image` to ground it against the gallery and
   render, side by side:
     * left  — the robot's camera view (what it sees);
     * right — a top-down map with the route, the robot's position,
       and the CLIP-grounded place highlighted, plus a HUD reading
       out the perceived place and cosine score.
4. Write an animated GIF.

The camera frames were rendered offline in Gazebo (the OpenRobotics
*Depot* world, CC-BY 4.0) and downsized into ``examples/data/depot_views/``;
the heavy ROS/Gazebo capture rig lives out of this pure-Python core by
design (decision D-16). This script needs only the ``[vlm]`` +
``[viz]`` extras:

    pip install -e '.[vlm,viz]'
    python examples/visual_localization_demo.py

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
from semantic_toponav.graph.types import Pose2D, TopologyNode
from semantic_toponav.query import localize_by_image

HERE = Path(__file__).parent
DATA_DIR = HERE / "data" / "depot_views"
IMAGE_DIR = HERE.parent / "docs" / "images"
OUT_GIF = IMAGE_DIR / "23_visual_localization.gif"

# Each place: graph node id, human label, type, world (x, y), and the
# reference frame filename CLIP embeds as that node's gallery vector.
PLACES = [
    ("bay", "Loading Bay", "area", (-4.0, 0.0), "proto_bay.jpg"),
    ("brick", "Brick Gateway", "doorway", (0.0, 2.0), "proto_brick.jpg"),
    ("drum", "Drum Storage", "room", (3.0, 3.0), "proto_drum.jpg"),
    ("crate", "Crate Aisle", "room", (3.0, -2.0), "proto_crate.jpg"),
    ("util", "Utility Corner", "room", (0.0, -2.0), "proto_util.jpg"),
]
ROUTE_ORDER = ["bay", "brick", "drum", "crate", "util"]

GIF_FRAME_MS = 280
GIF_LOOP = 0


def build_graph(backend: CLIPBackend) -> TopologyGraph:
    """Topology graph whose nodes carry CLIP gallery embeddings."""
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
    return graph


def _xy(key: str) -> tuple[float, float]:
    for k, _, _, xy, _ in PLACES:
        if k == key:
            return xy
    raise KeyError(key)


def _label(key: str) -> str:
    for k, label, _, _, _ in PLACES:
        if k == key:
            return label
    raise KeyError(key)


def render_frame(
    cam_img: np.ndarray,
    *,
    robot_xy: tuple[float, float],
    grounded_key: str,
    score: float,
) -> Image.Image:
    """One composite panel: camera view | top-down nav map + HUD."""
    fig, (axc, axm) = plt.subplots(
        1, 2, figsize=(10.0, 3.9), dpi=100,
        gridspec_kw={"width_ratios": [1.33, 1.0]},
    )

    # --- left: robot camera POV -------------------------------------
    axc.imshow(cam_img)
    axc.set_xticks([])
    axc.set_yticks([])
    axc.set_title("robot camera", fontsize=11, fontweight="bold")
    axc.text(
        0.5, -0.07,
        f"CLIP → perceived: {_label(grounded_key)}  (cos {score:.2f})",
        transform=axc.transAxes, ha="center", va="top",
        fontsize=11, color="#0f172a",
        bbox=dict(boxstyle="round,pad=0.3", fc="#fde68a", ec="#d97706"),
    )

    # --- right: top-down nav map ------------------------------------
    xs = [_xy(k)[0] for k in ROUTE_ORDER]
    ys = [_xy(k)[1] for k in ROUTE_ORDER]
    axm.plot(xs, ys, "-", color="#94a3b8", lw=2.0, zorder=1)
    for key, label, _, (x, y), _ in PLACES:
        on = key == grounded_key
        axm.scatter(
            [x], [y], s=460 if on else 230,
            c="#ef4444" if on else "#cbd5e1",
            edgecolor="#7f1d1d" if on else "#64748b",
            linewidth=2.0 if on else 1.0, zorder=3,
        )
        axm.annotate(
            label, (x, y), textcoords="offset points", xytext=(0, 13),
            ha="center", fontsize=9,
            fontweight="bold" if on else "normal",
            color="#b91c1c" if on else "#475569",
        )
    axm.scatter(
        [robot_xy[0]], [robot_xy[1]], marker="o", s=140,
        c="#2563eb", edgecolor="white", linewidth=1.8, zorder=5,
    )
    axm.annotate(
        "robot", robot_xy, textcoords="offset points", xytext=(0, -16),
        ha="center", fontsize=8, color="#1d4ed8",
    )
    axm.set_title("topology + grounded place", fontsize=11, fontweight="bold")
    axm.set_xlim(-6.0, 5.0)
    axm.set_ylim(-4.5, 5.0)
    axm.set_aspect("equal")
    axm.set_xlabel("x (m)", fontsize=8)
    axm.set_ylabel("y (m)", fontsize=8)
    axm.tick_params(labelsize=7)
    axm.grid(True, color="#eef2f7")

    fig.suptitle(
        "semantic-toponav · visual localization (real CLIP)",
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

    gif_frames: list[Image.Image] = []
    hits = 0
    for i, fm in enumerate(frames_meta):
        cam_path = DATA_DIR / f"frame{i:02d}.jpg"
        cam_img = np.asarray(Image.open(cam_path).convert("RGB"))
        result = localize_by_image(graph, cam_path, backend)
        grounded = result.node.id
        hits += grounded == fm["nearest"]
        gif_frames.append(
            render_frame(
                cam_img,
                robot_xy=(fm["x"], fm["y"]),
                grounded_key=grounded,
                score=result.score,
            )
        )
        print(
            f"  frame {i:02d}: grounded={grounded:6s} "
            f"nearest={fm['nearest']:6s} cos={result.score:.3f}"
        )

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    gif_frames[0].save(
        OUT_GIF, save_all=True, append_images=gif_frames[1:],
        duration=GIF_FRAME_MS, loop=GIF_LOOP, optimize=True,
    )
    size_kb = OUT_GIF.stat().st_size / 1024
    print(
        f"\ngrounded-to-nearest agreement: {hits}/{len(frames_meta)}\n"
        f"wrote {OUT_GIF} ({size_kb:.0f} KB, {len(gif_frames)} frames)"
    )


if __name__ == "__main__":
    main()
