"""Synthetic 3D Gaussian Splatting map for the escape-room 3D sim panel.

Builds a dense coloured splat cloud from ``robot_escape_room.yaml`` room meshes
and renders an isometric background PNG aligned with ``render_escape_room_hero.py``.

Regenerate:
    PYTHONPATH=. python3 examples/generate_escape_room_3dgs_map.py
"""

from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter

from escape_room_meshes import (
    FLOOR_HEIGHT_M,
    MESH_DIR,
    IsoView,
    all_meshes,
    fit_iso_view,
    iso_depth,
    iso_project,
)

HERE = Path(__file__).parent
MAP_PATH = MESH_DIR / "escape_room_3dgs_map.png"

# Must match scripts/foxglove_hero/render_escape_room_hero.py
SIM_W, BODY_H = 780, 480
SPLAT_SEED = 42


def _stable_hash(x: float, y: float, z: float) -> float:
    n = int(round(x * 17 + y * 31 + z * 53)) & 0xFFFF
    return ((n * 1103515245 + 12345) >> 16) / 65535.0


def _splat_rgb(x: float, y: float, z: float, node_type: str) -> tuple[int, int, int]:
    h = _stable_hash(x, y, z)
    h2 = _stable_hash(y, z, x)
    floor_z = math.floor(z / FLOOR_HEIGHT_M) * FLOOR_HEIGHT_M
    rel_z = z - floor_z

    if rel_z < 0.25:
        return (
            int(95 + h * 70),
            int(78 + h2 * 55),
            int(62 + h * 48),
        )
    if rel_z > 2.6:
        return (
            int(110 + h * 60),
            int(125 + h2 * 50),
            int(145 + h * 55),
        )
    palette = {
        "room": ((70, 120, 150), (90, 160, 130), (130, 100, 170)),
        "corridor": ((85, 95, 110), (100, 110, 125), (75, 88, 105)),
        "intersection": ((140, 110, 80), (160, 130, 95), (120, 140, 160)),
        "stairs": ((150, 95, 55), (170, 115, 70), (130, 85, 50)),
        "exit": ((60, 150, 110), (80, 170, 125), (55, 130, 95)),
        "sealed_exit": ((170, 75, 75), (150, 65, 65), (130, 55, 55)),
    }
    bases = palette.get(node_type, palette["room"])
    pick = bases[int(h * len(bases)) % len(bases)]
    return (
        int(pick[0] + h2 * 55),
        int(pick[1] + h * 45),
        int(pick[2] + (1 - h) * 40),
    )


def sample_splats(graph: Any, *, seed: int = SPLAT_SEED) -> list[tuple[float, float, float, float, int, int, int]]:
    """Return splats as (x, y, z, radius_px, r, g, b) in map frame."""
    rng = random.Random(seed)
    splats: list[tuple[float, float, float, float, int, int, int]] = []

    for mesh in all_meshes(graph):
        cx, cy, cz = mesh.center
        hx, hy, hz = mesh.half
        z0, z1 = cz - hz, cz + hz

        # floor slab
        for _ in range(160 if mesh.node_type == "room" else 80):
            x = rng.uniform(cx - hx * 0.92, cx + hx * 0.92)
            y = rng.uniform(cy - hy * 0.92, cy + hy * 0.92)
            z = z0 + rng.uniform(0.0, 0.12)
            r = rng.uniform(2.8, 6.2)
            splats.append((x, y, z, r, *_splat_rgb(x, y, z, mesh.node_type)))

        # walls
        for _ in range(120 if mesh.node_type != "corridor" else 60):
            face = rng.randint(0, 3)
            t = rng.random()
            u = rng.uniform(-0.9, 0.9)
            if face == 0:
                x, y = cx - hx, cy + hy * u
            elif face == 1:
                x, y = cx + hx * u, cy - hy
            elif face == 2:
                x, y = cx + hx, cy + hy * u
            else:
                x, y = cx + hx * u, cy + hy
            z = rng.uniform(z0 + 0.1, z1 - 0.1)
            r = rng.uniform(2.6, 6.5)
            splats.append((x, y, z, r, *_splat_rgb(x, y, z, mesh.node_type)))

        # ceiling + clutter
        for _ in range(45):
            x = rng.uniform(cx - hx * 0.7, cx + hx * 0.7)
            y = rng.uniform(cy - hy * 0.7, cy + hy * 0.7)
            z = z1 - rng.uniform(0.0, 0.15)
            r = rng.uniform(1.8, 3.8)
            splats.append((x, y, z, r, *_splat_rgb(x, y, z, mesh.node_type)))

        if mesh.node_type in {"room", "intersection"}:
            for _ in range(35):
                x = rng.uniform(cx - hx * 0.5, cx + hx * 0.5)
                y = rng.uniform(cy - hy * 0.5, cy + hy * 0.5)
                z = rng.uniform(z0 + 0.4, z1 - 0.4)
                r = rng.uniform(1.5, 3.2)
                splats.append((x, y, z, r, *_splat_rgb(x, y, z, mesh.node_type)))

    # corridor spine between connected nodes
    for edge in graph.edges():
        a = graph.get_node(edge.source)
        b = graph.get_node(edge.target)
        fa = int(a.properties.get("floor", 1))
        fb = int(b.properties.get("floor", 1))
        if fa != fb:
            continue
        z = (fa - 1) * FLOOR_HEIGHT_M + 0.08
        for t in np.linspace(0.05, 0.95, 20):
            x = a.pose.x + (b.pose.x - a.pose.x) * t + rng.uniform(-0.25, 0.25)
            y = a.pose.y + (b.pose.y - a.pose.y) * t + rng.uniform(-0.25, 0.25)
            r = rng.uniform(2.0, 4.0)
            splats.append((x, y, z, r, *_splat_rgb(x, y, z, "corridor")))

    return splats


def render_3dgs_background(
    graph: Any,
    *,
    width: int = SIM_W,
    height: int = BODY_H,
    view: IsoView | None = None,
    seed: int = SPLAT_SEED,
) -> Image.Image:
    """Render isometric 3DGS splat background (RGBA)."""
    if view is None:
        view = fit_iso_view(graph, width, height)
    splats = sample_splats(graph, seed=seed)
    projected: list[tuple[float, float, float, float, int, int, int]] = []
    for x, y, z, radius, r, g, b in splats:
        sx, sy = iso_project(x, y, z, view.cx, view.cy, scale=view.scale)
        radius *= view.scale / 5.6
        if -20 <= sx < width + 20 and -20 <= sy < height + 20:
            projected.append((iso_depth(x, y, z), sx, sy, radius, r, g, b))

    base = Image.new("RGBA", (width, height), (6, 10, 20, 255))
    draw_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    stamp = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    stamp_px = stamp.load()
    for iy in range(32):
        for ix in range(32):
            dx, dy = ix - 15.5, iy - 15.5
            d2 = (dx * dx + dy * dy) / (14.0 * 14.0)
            if d2 <= 1.0:
                stamp_px[ix, iy] = (255, 255, 255, int(220 * math.exp(-d2 * 2.2)))

    for _, sx, sy, radius, r, g, b in sorted(projected, key=lambda s: s[0]):
        alpha = Image.new("RGBA", (32, 32), (r, g, b, 0))
        alpha.putalpha(stamp.split()[3])
        scaled = alpha.resize((max(2, int(radius * 2)), max(2, int(radius * 2))), Image.Resampling.LANCZOS)
        px = int(sx - scaled.width / 2)
        py = int(sy - scaled.height / 2)
        draw_layer.paste(scaled, (px, py), scaled)

    glow = draw_layer.filter(ImageFilter.GaussianBlur(radius=0.6))
    out = Image.alpha_composite(base, glow)
    out = Image.alpha_composite(out, draw_layer)
    return out


def ensure_map(graph: Any, path: Path = MAP_PATH) -> Path:
    if not path.exists():
        write_map(graph, path)
    return path


def write_map(graph: Any, path: Path = MAP_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    img = render_3dgs_background(graph)
    img.save(path, optimize=True)
    return path


def load_map(graph: Any, path: Path = MAP_PATH) -> Image.Image:
    ensure_map(graph, path)
    return Image.open(path).convert("RGBA")
