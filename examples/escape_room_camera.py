"""First-person RGB camera view for the escape-room hero panel.

Renders a pinhole projection of the same 3DGS splat cloud used in the 3D sim,
from the robot pose and look direction along the active route segment.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from escape_room_3dgs_map import sample_splats

CAMERA_HEIGHT_M = 0.72
FOV_RAD = 1.05
SPLAT_CACHE: list[tuple[float, float, float, float, int, int, int]] | None = None


def _splats(graph: Any) -> list[tuple[float, float, float, float, int, int, int]]:
    global SPLAT_CACHE
    if SPLAT_CACHE is None:
        SPLAT_CACHE = sample_splats(graph)
    return SPLAT_CACHE


def _normalize(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n < 1e-6:
        return v
    return v / n


def _robot_pose(graph: Any, meta: dict) -> tuple[np.ndarray, np.ndarray]:
    route = meta.get("route") or []
    progress = float(meta.get("progress", 0.0))
    if len(route) >= 2:
        segment = min(int(progress), len(route) - 2)
        local = max(0.0, min(1.0, progress - segment))
        a = graph.get_node(route[segment])
        b = graph.get_node(route[segment + 1])
        fa = int(a.properties.get("floor", 1))
        fb = int(b.properties.get("floor", 1))
        za = (fa - 1) * 4.2
        zb = (fb - 1) * 4.2
        pos = np.array([
            a.pose.x + (b.pose.x - a.pose.x) * local,
            a.pose.y + (b.pose.y - a.pose.y) * local,
            za + (zb - za) * local + CAMERA_HEIGHT_M,
        ], dtype=np.float64)
        ahead = np.array([b.pose.x, b.pose.y, zb + CAMERA_HEIGHT_M], dtype=np.float64)
        forward = _normalize(ahead - pos)
        return pos, forward

    loc = meta.get("location") or (route[0] if route else "holding_cell")
    node = graph.get_node(loc)
    fl = int(node.properties.get("floor", 1))
    z = (fl - 1) * 4.2 + CAMERA_HEIGHT_M
    pos = np.array([node.pose.x, node.pose.y, z], dtype=np.float64)
    forward = np.array([1.0, 0.0, 0.0], dtype=np.float64)
    for edge in graph.edges():
        if edge.source == loc:
            tgt = graph.get_node(edge.target)
            forward = _normalize(np.array([tgt.pose.x - node.pose.x, tgt.pose.y - node.pose.y, 0.0]))
            break
        if edge.target == loc:
            src = graph.get_node(edge.source)
            forward = _normalize(np.array([node.pose.x - src.pose.x, node.pose.y - src.pose.y, 0.0]))
            break
    return pos, forward


def render_camera_view(
    graph: Any,
    meta: dict,
    *,
    width: int,
    height: int,
) -> Image.Image:
    """Render robot RGB camera frame from 3DGS splats (RGBA)."""
    eye, forward = _robot_pose(graph, meta)
    world_up = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    right = _normalize(np.cross(forward, world_up))
    if float(np.linalg.norm(right)) < 1e-4:
        right = np.array([0.0, 1.0, 0.0], dtype=np.float64)
    up = _normalize(np.cross(right, forward))

    focal = width / (2.0 * math.tan(FOV_RAD / 2.0))
    projected: list[tuple[float, float, float, float, int, int, int]] = []

    splats = _splats(graph)
    for idx, (x, y, z, _r_px, r, g, b) in enumerate(splats):
        if idx % 2 == 1:
            continue
        rel = np.array([x, y, z], dtype=np.float64) - eye
        cx = float(np.dot(rel, right))
        cy = float(np.dot(rel, up))
        cz = float(np.dot(rel, forward))
        if cz < 0.25:
            continue
        sx = width / 2 + focal * cx / cz
        sy = height / 2 - focal * cy / cz
        if sx < -40 or sx > width + 40 or sy < -40 or sy > height + 40:
            continue
        radius = max(2.5, min(28.0, 0.55 * focal / cz))
        projected.append((cz, sx, sy, radius, r, g, b))

    base = Image.new("RGBA", (width, height), (8, 10, 14, 255))
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    stamp = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
    px = stamp.load()
    for iy in range(24):
        for ix in range(24):
            d2 = ((ix - 11.5) ** 2 + (iy - 11.5) ** 2) / (10.5 * 10.5)
            if d2 <= 1.0:
                px[ix, iy] = (255, 255, 255, int(210 * math.exp(-d2 * 2.0)))

    draw = ImageDraw.Draw(layer, "RGBA")
    for cz, sx, sy, radius, r, g, b in sorted(projected, key=lambda s: s[0], reverse=True):
        alpha = Image.new("RGBA", (24, 24), (r, g, b, 0))
        alpha.putalpha(stamp.split()[3])
        size = max(3, int(radius * 2))
        blob = alpha.resize((size, size), Image.Resampling.LANCZOS)
        layer.paste(blob, (int(sx - size / 2), int(sy - size / 2)), blob)

    out = Image.alpha_composite(base, layer.filter(ImageFilter.GaussianBlur(radius=0.35)))
    out = Image.alpha_composite(out, layer)
    out = out.filter(ImageFilter.GaussianBlur(radius=0.7))

    loc = meta.get("location") or "holding_cell"
    node = graph.get_node(loc) if graph.has_node(loc) else None
    brightness = 1.0
    if loc == "dark_corridor":
        brightness = 0.32
    elif node and node.type == "corridor":
        brightness = 0.78
    if brightness < 1.0:
        dim = Image.new("RGBA", (width, height), (0, 0, 0, int((1.0 - brightness) * 180)))
        out = Image.alpha_composite(out, dim)

    # vignette
    vig = Image.new("L", (width, height), 0)
    vdraw = ImageDraw.Draw(vig)
    vdraw.ellipse((-width * 0.15, -height * 0.1, width * 1.15, height * 1.1), fill=220)
    vig = vig.filter(ImageFilter.GaussianBlur(radius=min(width, height) // 5))
    out = Image.composite(
        Image.new("RGBA", (width, height), (0, 0, 0, 255)),
        out,
        Image.eval(vig, lambda p: 255 - p),
    )

    hud = ImageDraw.Draw(out, "RGBA")
    hud.rectangle((0, 0, width, 26), fill=(9, 17, 31, 230))
    return out
