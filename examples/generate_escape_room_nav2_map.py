"""Generate a Nav2 occupancy map for the escape-room Gazebo sim.

Rasterizes furnished interior collision boxes (walls / props) into a PGM so
Nav2 global planning matches the Gazebo facility layout.

    PYTHONPATH=. python3 examples/generate_escape_room_nav2_map.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "examples"))

from escape_room_interior import foxglove_furnished_cubes

from semantic_toponav.graph.serialization import load_graph

GRAPH = ROOT / "examples" / "robot_escape_room.yaml"
OUT_DIR = ROOT / "examples" / "meshes" / "escape_room" / "gazebo" / "nav2"
RESOLUTION = 0.05
PADDING_M = 6.0
FREE = 254
OCCUPIED = 0


def _is_nav_obstacle(center: tuple[float, float, float], size: tuple[float, float, float]) -> bool:
    _, _, cz = center
    sx, sy, sz = size
    z_lo, z_hi = cz - sz / 2, cz + sz / 2
    if z_hi < 0.12 or z_lo > 0.85:
        return False
    if sz < 0.12 and z_hi < 0.25:
        return False
    return sx > 0.04 and sy > 0.04


def _mark_box(
    grid: bytearray,
    width_px: int,
    height_px: int,
    min_x: float,
    min_y: float,
    cx: float,
    cy: float,
    sx: float,
    sy: float,
) -> None:
    x0, x1 = cx - sx / 2, cx + sx / 2
    y0, y1 = cy - sy / 2, cy + sy / 2
    ix0 = max(0, int((x0 - min_x) / RESOLUTION))
    ix1 = min(width_px - 1, int((x1 - min_x) / RESOLUTION))
    iy0 = max(0, int((y0 - min_y) / RESOLUTION))
    iy1 = min(height_px - 1, int((y1 - min_y) / RESOLUTION))
    for iy in range(iy0, iy1 + 1):
        row = height_px - 1 - iy
        base = row * width_px
        for ix in range(ix0, ix1 + 1):
            grid[base + ix] = OCCUPIED


def main() -> None:
    graph = load_graph(str(GRAPH))
    nodes = list(graph.nodes())
    xs = [float(n.pose.x) for n in nodes if n.pose is not None]
    ys = [float(n.pose.y) for n in nodes if n.pose is not None]
    min_x, max_x = min(xs) - PADDING_M, max(xs) + PADDING_M
    min_y, max_y = min(ys) - PADDING_M, max(ys) + PADDING_M

    width_px = int((max_x - min_x) / RESOLUTION)
    height_px = int((max_y - min_y) / RESOLUTION)
    grid = bytearray([FREE] * (width_px * height_px))

    obstacles = 0
    for cube in foxglove_furnished_cubes(graph, set()):
        if not _is_nav_obstacle(cube.center, cube.size):
            continue
        cx, cy, _ = cube.center
        sx, sy, _ = cube.size
        _mark_box(grid, width_px, height_px, min_x, min_y, cx, cy, sx, sy)
        obstacles += 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pgm = OUT_DIR / "escape_room.pgm"
    pgm.write_bytes(
        b"P5\n" + f"{width_px} {height_px}\n255\n".encode() + bytes(grid)
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
    print(
        f"wrote Nav2 map -> {yaml_path.relative_to(ROOT)} "
        f"({width_px}x{height_px}px, {obstacles} obstacle boxes)"
    )


if __name__ == "__main__":
    main()
