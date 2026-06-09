"""Render escape-room facility from imported OBJ room meshes.

Loads ``escape_room_scene.obj`` (Wavefront) and rasterises solid floor / wall /
ceiling faces for the hero GIF isometric panel and robot RGB camera panel.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from escape_room_meshes import (
    FLOOR_HEIGHT_M,
    SCENE_OBJ,
    IsoView,
    all_meshes,
    fit_iso_view,
    iso_depth,
    iso_project,
)

CAMERA_HEIGHT_M = 0.72
FOV_RAD = 1.05
OVERVIEW_EYE = (14.0, -10.0, 24.0)
OVERVIEW_LOOK_AT = (14.0, 0.0, 0.0)
OVERVIEW_RPY = (0.0, 0.65, 0.85)
LIGHT_DIR = np.array([0.25, -0.35, 0.90], dtype=np.float64)
LIGHT_DIR /= np.linalg.norm(LIGHT_DIR)

FLOOR_RGB: dict[str, tuple[int, int, int]] = {
    "room": (68, 74, 88),
    "corridor": (52, 56, 66),
    "intersection": (78, 72, 86),
    "stairs": (82, 70, 54),
    "exit": (56, 88, 72),
    "sealed_exit": (92, 58, 58),
}


@dataclass(frozen=True)
class ObjGroup:
    name: str
    label: str
    node_type: str
    faces: tuple[tuple[int, int, int], ...]


@dataclass(frozen=True)
class RenderTri:
    v0: tuple[float, float, float]
    v1: tuple[float, float, float]
    v2: tuple[float, float, float]
    color: tuple[int, int, int]
    node_id: str
    surface: str


def _shade(base: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * factor))) for c in base)


def _normal(v0, v1, v2) -> np.ndarray:
    a = np.array(v1, dtype=np.float64) - np.array(v0, dtype=np.float64)
    b = np.array(v2, dtype=np.float64) - np.array(v0, dtype=np.float64)
    n = np.cross(a, b)
    ln = float(np.linalg.norm(n))
    if ln < 1e-9:
        return np.array([0.0, 0.0, 1.0])
    return n / ln


def _surface(mesh_meta: Any, v0, v1, v2) -> str:
    cz = mesh_meta.center[2]
    hz = mesh_meta.size[2] / 2
    avg_z = (v0[2] + v1[2] + v2[2]) / 3
    if avg_z <= cz - hz + 0.08:
        return "floor"
    if avg_z >= cz + hz - 0.08:
        return "ceiling"
    return "wall"


def _tri_color(mesh_meta: Any, surface: str, normal: np.ndarray) -> tuple[int, int, int]:
    node_type = mesh_meta.node_type
    r, g, b, _ = mesh_meta.color
    if surface == "floor":
        base = FLOOR_RGB.get(node_type, FLOOR_RGB["room"])
    elif surface == "ceiling":
        base = _shade((int(r * 210), int(g * 210), int(b * 210)), 1.08)
    else:
        base = (int(r * 220), int(g * 220), int(b * 220))
    lambert = 0.58 + 0.42 * max(0.0, float(np.dot(normal, LIGHT_DIR)))
    return _shade(base, lambert)


def load_obj_scene(path: Path = SCENE_OBJ) -> tuple[list[tuple[float, float, float]], list[ObjGroup]]:
    """Import Wavefront OBJ — supports combined scenes with global face indices."""
    if not path.exists():
        raise FileNotFoundError(f"missing OBJ scene: {path}")

    vertices: list[tuple[float, float, float]] = []
    groups: list[ObjGroup] = []
    name = ""
    label = ""
    node_type = "room"
    faces: list[tuple[int, int, int]] = []

    def flush() -> None:
        nonlocal faces, name, label, node_type
        if name and faces:
            groups.append(
                ObjGroup(
                    name=name,
                    label=label or name,
                    node_type=node_type,
                    faces=tuple(faces),
                )
            )
        faces = []

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            if line.startswith("# ") and " floor " in line and "(" in line and ")" in line:
                chunk = line[2:]
                label = chunk.split("(")[0].strip()
                name = chunk.split("(")[1].split(")")[0].strip()
            continue
        if line.startswith("o "):
            flush()
            name = line[2:].strip()
            if not label:
                label = name
            node_type = "room"
            continue
        if line.startswith("v "):
            parts = line.split()
            vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
            continue
        if line.startswith("f "):
            idx = [int(p.split("/")[0]) - 1 for p in line.split()[1:4]]
            if len(idx) == 3:
                faces.append((idx[0], idx[1], idx[2]))

    flush()
    return vertices, groups


def build_render_tris(graph: Any, obj_path: Path | None = None) -> list[RenderTri]:
    """Build shaded triangles from detailed interior room geometry."""
    del obj_path  # geometry is procedural; OBJ export uses the same source
    from escape_room_interior import all_room_geometry

    _MAT_SURFACE = {
        "floor_tile": "floor",
        "floor_tile_alt": "floor",
        "ceiling": "ceiling",
        "light": "ceiling",
        "wall": "wall",
        "wainscot": "wall",
        "door_frame": "wall",
        "prop": "prop",
    }

    tris: list[RenderTri] = []
    for room in all_room_geometry(graph):
        r, g, b, _ = room.color
        bases = {
            "floor_tile": (86, 90, 102),
            "floor_tile_alt": (70, 74, 84),
            "wall": (int(r * 250), int(g * 250), int(b * 250)),
            "wainscot": (58, 62, 74),
            "ceiling": (int(r * 215), int(g * 215), int(b * 215)),
            "light": (255, 252, 225),
            "door_frame": (46, 50, 62),
            "prop": (int(r * 195 + 25), int(g * 195 + 25), int(b * 195 + 25)),
        }
        for gt in room.tris:
            n = _normal(gt.v0, gt.v1, gt.v2)
            surf = _MAT_SURFACE.get(gt.material, "wall")
            base = bases.get(gt.material, bases["wall"])
            if gt.material == "light":
                color = base
            else:
                lambert = 0.55 + 0.45 * max(0.0, float(np.dot(n, LIGHT_DIR)))
                color = _shade(base, lambert)
            tris.append(RenderTri(gt.v0, gt.v1, gt.v2, color, room.node_id, surf))
    return tris


_TRI_CACHE: list[RenderTri] | None = None


def clear_tri_cache() -> None:
    global _TRI_CACHE
    _TRI_CACHE = None


def _tris(graph: Any) -> list[RenderTri]:
    global _TRI_CACHE
    if _TRI_CACHE is None:
        _TRI_CACHE = build_render_tris(graph)
    return _TRI_CACHE


def render_iso_facility(
    graph: Any,
    *,
    width: int,
    height: int,
    view: IsoView | None = None,
) -> Image.Image:
    """Isometric render of imported OBJ room meshes."""
    if view is None:
        view = fit_iso_view(graph, width, height)

    base = Image.new("RGBA", (width, height), (8, 12, 22, 255))
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer, "RGBA")

    faces: list[tuple[float, list[tuple[float, float]], tuple[int, int, int, int], str]] = []
    for tri in _tris(graph):
        pts = [
            iso_project(*tri.v0, view.cx, view.cy, scale=view.scale),
            iso_project(*tri.v1, view.cx, view.cy, scale=view.scale),
            iso_project(*tri.v2, view.cx, view.cy, scale=view.scale),
        ]
        depth = (
            iso_depth(*tri.v0) + iso_depth(*tri.v1) + iso_depth(*tri.v2)
        ) / 3
        alpha = 255 if tri.surface != "floor" else 235
        faces.append((depth, pts, (*tri.color, alpha), tri.node_id))

    for depth, pts, rgba, _ in sorted(faces, key=lambda f: f[0]):
        draw.polygon(pts, fill=rgba)

    out = Image.alpha_composite(base, layer)
    # room labels on floor
    label_draw = ImageDraw.Draw(out, "RGBA")
    for mesh in all_meshes(graph):
        if mesh.node_id not in {
            "holding_cell", "emergency_exit", "maintenance_exit", "control_room",
            "atrium", "elevator_lobby",
        }:
            continue
        x, y, z = mesh.center
        lx, ly = iso_project(x, y, z - mesh.size[2] / 2 + 0.15, view.cx, view.cy, scale=view.scale)
        label_draw.text((lx, ly), mesh.label[:14], fill=(230, 235, 245, 220), anchor="ma")
    return out


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
        za = (fa - 1) * FLOOR_HEIGHT_M
        zb = (fb - 1) * FLOOR_HEIGHT_M
        pos = np.array([
            a.pose.x + (b.pose.x - a.pose.x) * local,
            a.pose.y + (b.pose.y - a.pose.y) * local,
            za + (zb - za) * local + CAMERA_HEIGHT_M,
        ], dtype=np.float64)
        ahead = np.array([b.pose.x, b.pose.y, zb + CAMERA_HEIGHT_M], dtype=np.float64)
        fwd = ahead - pos
        fwd[2] *= 0.35
        n = float(np.linalg.norm(fwd))
        forward = fwd / n if n > 1e-6 else np.array([1.0, 0.0, 0.0])
        return pos, forward

    loc = meta.get("location") or (route[0] if route else "holding_cell")
    node = graph.get_node(loc)
    fl = int(node.properties.get("floor", 1))
    z = (fl - 1) * FLOOR_HEIGHT_M + CAMERA_HEIGHT_M
    pos = np.array([node.pose.x, node.pose.y, z], dtype=np.float64)
    forward = np.array([1.0, 0.0, 0.0], dtype=np.float64)
    for edge in graph.edges():
        if edge.source == loc:
            tgt = graph.get_node(edge.target)
            forward = np.array([tgt.pose.x - node.pose.x, tgt.pose.y - node.pose.y, 0.0])
            break
        if edge.target == loc:
            src = graph.get_node(edge.source)
            forward = np.array([node.pose.x - src.pose.x, node.pose.y - src.pose.y, 0.0])
            break
    n = float(np.linalg.norm(forward))
    return pos, forward / n if n > 1e-6 else forward


def _camera_basis_look_at(
    eye: tuple[float, float, float],
    target: tuple[float, float, float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    eye_v = np.array(eye, dtype=np.float64)
    forward = np.array(target, dtype=np.float64) - eye_v
    forward /= max(float(np.linalg.norm(forward)), 1e-6)
    world_up = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    right = np.cross(forward, world_up)
    rn = float(np.linalg.norm(right))
    right = right / rn if rn > 1e-6 else np.array([0.0, 1.0, 0.0])
    up = np.cross(right, forward)
    up /= max(float(np.linalg.norm(up)), 1e-6)
    return eye_v, forward, right, up


def _camera_basis_rpy(
    eye: tuple[float, float, float],
    rpy: tuple[float, float, float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    del rpy
    return _camera_basis_look_at(eye, OVERVIEW_LOOK_AT)


def _project_tris(
    eye: np.ndarray,
    forward: np.ndarray,
    right: np.ndarray,
    up: np.ndarray,
    *,
    width: int,
    height: int,
    tris: list[RenderTri],
) -> Image.Image:
    focal = width / (2.0 * math.tan(FOV_RAD / 2.0))
    base = Image.new("RGBA", (width, height), (118, 122, 128, 255))
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer, "RGBA")

    polys: list[tuple[float, list[tuple[float, float]], tuple[int, int, int]]] = []
    for tri in tris:
        pts: list[tuple[float, float]] = []
        depths: list[float] = []
        any_front = False
        for v in (tri.v0, tri.v1, tri.v2):
            rel = np.array(v, dtype=np.float64) - eye
            cz_raw = float(np.dot(rel, forward))
            if cz_raw >= 0.15:
                any_front = True
            cz = max(0.15, cz_raw)
            sx = width / 2 + focal * float(np.dot(rel, right)) / cz
            sy = height / 2 - focal * float(np.dot(rel, up)) / cz
            pts.append((sx, sy))
            depths.append(cz)
        if not any_front:
            continue
        polys.append((sum(depths) / 3, pts, tri.color))

    for _, pts, color in sorted(polys, key=lambda p: p[0], reverse=True):
        draw.polygon(pts, fill=(*color, 255))

    return Image.alpha_composite(base, layer)


def _robot_ground_pose(graph: Any, meta: dict) -> tuple[np.ndarray, float]:
    eye, forward = _robot_pose(graph, meta)
    pos = eye.copy()
    pos[2] = max(0.05, pos[2] - CAMERA_HEIGHT_M + 0.05)
    yaw = math.atan2(float(forward[1]), float(forward[0]))
    return pos, yaw


def render_overview_facility(
    graph: Any,
    meta: dict,
    *,
    width: int,
    height: int,
) -> Image.Image:
    """Overview RGB view matching the Gazebo ``overview_camera`` pose."""
    eye, forward, right, up = _camera_basis_rpy(OVERVIEW_EYE, OVERVIEW_RPY)
    img = _project_tris(eye, forward, right, up, width=width, height=height, tris=_tris(graph))

    pos, yaw = _robot_ground_pose(graph, meta)
    rel = pos - eye
    cz = max(0.15, float(np.dot(rel, forward)))
    focal = width / (2.0 * math.tan(FOV_RAD / 2.0))
    sx = width / 2 + focal * float(np.dot(rel, right)) / cz
    sy = height / 2 - focal * float(np.dot(rel, up)) / cz

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")
    body = 11.0
    hx = math.cos(yaw) * body
    hy = math.sin(yaw) * body
    px, py = -math.sin(yaw) * 4.5, math.cos(yaw) * 4.5
    draw.polygon(
        [(sx + hx + px, sy + hy + py), (sx + hx - px, sy + hy - py),
         (sx - hx - px, sy - hy - py), (sx - hx + px, sy - hy + py)],
        fill=(34, 211, 238, 245),
        outline=(248, 250, 252, 255),
    )
    draw.ellipse((sx - 4, sy - 4, sx + 4, sy + 4), fill=(248, 250, 252, 255))
    return Image.alpha_composite(img, overlay)


def render_camera_facility(
    graph: Any,
    meta: dict,
    *,
    width: int,
    height: int,
) -> Image.Image:
    """First-person RGB view rasterising imported OBJ room meshes."""
    eye, forward = _robot_pose(graph, meta)
    world_up = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    right = np.cross(forward, world_up)
    rn = float(np.linalg.norm(right))
    right = right / rn if rn > 1e-6 else np.array([0.0, 1.0, 0.0])
    up = np.cross(right, forward)
    up /= max(float(np.linalg.norm(up)), 1e-6)

    img = _project_tris(eye, forward, right, up, width=width, height=height, tris=_tris(graph))

    loc = meta.get("location") or "holding_cell"
    brightness = 0.34 if loc == "dark_corridor" else 1.0
    if graph.has_node(loc):
        node = graph.get_node(loc)
        if node.type == "corridor" and loc != "dark_corridor":
            brightness = 0.82
    if brightness < 1.0:
        dim = Image.new("RGBA", (width, height), (0, 0, 0, int((1.0 - brightness) * 170)))
        img = Image.alpha_composite(img, dim)

    return img
