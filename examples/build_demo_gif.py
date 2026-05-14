"""Render an animated GIF that cycles through the multi-floor demo plans.

Produces ``docs/images/demo.gif`` — the README hero image. Each frame
shows the same 3-floor office graph (floors stacked vertically) with a
different cost configuration applied, so the viewer can see the
planner shift the route as semantic rules toggle.

Run from the repository root:

    pip install -e '.[viz]'
    python examples/build_demo_gif.py
"""

from __future__ import annotations

import io
from pathlib import Path

import matplotlib.pyplot as plt
from PIL import Image

from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.planner import (
    compose_costs,
    floor_change_penalty,
    plan_astar,
    prefer_elevator,
    same_floor_only,
)
from semantic_toponav.visualization import plot_graph

GRAPH_PATH = Path(__file__).parent / "multi_floor_office.yaml"
OUT_PATH = Path(__file__).resolve().parents[1] / "docs" / "images" / "demo.gif"
FLOOR_OFFSET = 8.0
FRAME_W, FRAME_H = 8.0, 5.5
FRAME_DPI = 110
FRAME_DURATION_MS = 1800   # how long each frame is visible
LOOP = 0                   # loop forever


def _render_frame(graph, path: list[str], caption: str) -> Image.Image:
    """Render one (graph, path, caption) frame to an in-memory PIL image."""
    fig, ax = plt.subplots(figsize=(FRAME_W, FRAME_H), dpi=FRAME_DPI)
    plot_graph(
        graph,
        path=path,
        title=caption,
        ax=ax,
        show_labels=True,
        floor_offset=FLOOR_OFFSET,
    )
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=FRAME_DPI)
    plt.close(fig)
    buf.seek(0)
    return Image.open(buf).convert("P", palette=Image.ADAPTIVE)


def main() -> None:
    graph = load_graph(GRAPH_PATH)

    scenes: list[tuple[str, str, str, object | None]] = [
        # (start, goal, caption, cost_fn)
        (
            "entrance", "exec_office_3f",
            "Default A* — fastest route via stairs",
            None,
        ),
        (
            "entrance", "exec_office_3f",
            "+ prefer_elevator — accessibility-aware",
            compose_costs(prefer_elevator),
        ),
        (
            "entrance", "office_2f",
            "+ floor_change_penalty(50) — minimize floor changes",
            floor_change_penalty(graph, penalty=50),
        ),
        (
            "kitchen_1f", "lab_1f",
            "same_floor_only — strictly within floor 1",
            same_floor_only(graph),
        ),
    ]

    frames: list[Image.Image] = []
    for start, goal, caption, cost_fn in scenes:
        path = (
            plan_astar(graph, start, goal, cost_fn=cost_fn)
            if cost_fn is not None
            else plan_astar(graph, start, goal)
        )
        frames.append(_render_frame(graph, path, caption))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        OUT_PATH,
        save_all=True,
        append_images=frames[1:],
        duration=FRAME_DURATION_MS,
        loop=LOOP,
        optimize=True,
    )
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"wrote {OUT_PATH} ({size_kb:.0f} KB, {len(frames)} frames)")


if __name__ == "__main__":
    main()
