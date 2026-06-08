"""Generate an open-space Nav2 map for the escape-room Gazebo sim.

The facility collision geometry lives in Gazebo; this map gives Nav2 a
metric ``map`` frame aligned with ``robot_escape_room.yaml`` poses.

    PYTHONPATH=. python3 examples/generate_escape_room_nav2_map.py
"""

from __future__ import annotations

import struct
from pathlib import Path

import yaml

from semantic_toponav.graph.serialization import load_graph

ROOT = Path(__file__).resolve().parents[1]
GRAPH = ROOT / "examples" / "robot_escape_room.yaml"
OUT_DIR = ROOT / "examples" / "meshes" / "escape_room" / "gazebo" / "nav2"
RESOLUTION = 0.05
PADDING_M = 6.0


def main() -> None:
    graph = load_graph(str(GRAPH))
    nodes = list(graph.nodes())
    xs = [float(n.pose.x) for n in nodes if n.pose is not None]
    ys = [float(n.pose.y) for n in nodes if n.pose is not None]
    min_x, max_x = min(xs) - PADDING_M, max(xs) + PADDING_M
    min_y, max_y = min(ys) - PADDING_M, max(ys) + PADDING_M

    width_m = max_x - min_x
    height_m = max_y - min_y
    width_px = int(width_m / RESOLUTION)
    height_px = int(height_m / RESOLUTION)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pgm = OUT_DIR / "escape_room.pgm"
    # map_server: high values = free space
    pgm.write_bytes(
        b"P5\n"
        + f"{width_px} {height_px}\n255\n".encode()
        + struct.pack(f"{width_px * height_px}B", *([254] * (width_px * height_px)))
    )

    meta = {
        "image": pgm.name,
        "resolution": RESOLUTION,
        "origin": [min_x, min_y, 0.0],
        "negate": 0,
        "occupied_thresh": 0.65,
        "free_thresh": 0.196,
        "mode": "trinary",
    }
    yaml_path = OUT_DIR / "escape_room.yaml"
    yaml_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    print(f"wrote Nav2 map -> {yaml_path.relative_to(ROOT)} ({width_px}x{height_px}px)")


if __name__ == "__main__":
    main()
