"""Escape-room room mesh specs, OBJ export, and isometric box drawing.

Meshes are axis-aligned boxes placed at each topology node. Regenerate OBJ
assets with ``generate_escape_room_meshes.py``; import into Blender / 3ds Max
via ``examples/meshes/escape_room/manifest.json``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FLOOR_HEIGHT_M = 4.2
WALL_HEIGHT_M = 3.0

# width (x), depth (y), height (z) in metres — tuned to graph spacing.
MESH_SIZE: dict[str, tuple[float, float, float]] = {
    "room": (4.0, 4.0, WALL_HEIGHT_M),
    "corridor": (2.6, 2.6, WALL_HEIGHT_M),
    "intersection": (3.2, 3.2, WALL_HEIGHT_M),
    "stairs": (2.2, 2.2, WALL_HEIGHT_M),
    "exit": (3.6, 3.6, WALL_HEIGHT_M),
    "sealed_exit": (3.6, 3.6, WALL_HEIGHT_M),
}

MESH_RGBA: dict[str, tuple[float, float, float, float]] = {
    "room": (0.31, 0.62, 0.96, 0.55),
    "corridor": (0.45, 0.50, 0.58, 0.45),
    "intersection": (0.66, 0.40, 0.96, 0.50),
    "stairs": (0.96, 0.62, 0.08, 0.55),
    "exit": (0.22, 0.83, 0.45, 0.65),
    "sealed_exit": (0.95, 0.34, 0.34, 0.55),
}

HERE = Path(__file__).parent
MESH_DIR = HERE / "meshes" / "escape_room"
MANIFEST_PATH = MESH_DIR / "manifest.json"
SCENE_OBJ = MESH_DIR / "escape_room_scene.obj"


@dataclass(frozen=True)
class RoomMesh:
    node_id: str
    label: str
    node_type: str
    floor: int
    center: tuple[float, float, float]
    size: tuple[float, float, float]
    color: tuple[float, float, float, float]

    @property
    def half(self) -> tuple[float, float, float]:
        sx, sy, sz = self.size
        return sx / 2, sy / 2, sz / 2

    def corners(self) -> list[tuple[float, float, float]]:
        cx, cy, cz = self.center
        hx, hy, hz = self.half
        z0 = cz - hz
        z1 = cz + hz
        return [
            (cx - hx, cy - hy, z0), (cx + hx, cy - hy, z0),
            (cx + hx, cy + hy, z0), (cx - hx, cy + hy, z0),
            (cx - hx, cy - hy, z1), (cx + hx, cy - hy, z1),
            (cx + hx, cy + hy, z1), (cx - hx, cy + hy, z1),
        ]

    def triangles(self) -> list[tuple[int, int, int]]:
        # vertex order matches corners()
        return [
            (1, 2, 3), (1, 3, 4),       # floor (bottom)
            (5, 7, 6), (5, 8, 7),       # roof
            (1, 5, 6), (1, 6, 2),       # front
            (2, 6, 7), (2, 7, 3),       # right
            (3, 7, 8), (3, 8, 4),       # back
            (4, 8, 5), (4, 5, 1),       # left
        ]

    def to_obj(self) -> str:
        lines = [f"# {self.label} ({self.node_id}) floor {self.floor}", f"o {self.node_id}"]
        for x, y, z in self.corners():
            lines.append(f"v {x:.4f} {y:.4f} {z:.4f}")
        for a, b, c in self.triangles():
            lines.append(f"f {a} {b} {c}")
        return "\n".join(lines) + "\n"


def floor_z(floor: int) -> float:
    return (floor - 1) * FLOOR_HEIGHT_M


def node_mesh(graph: Any, node_id: str) -> RoomMesh:
    node = graph.get_node(node_id)
    fl = int(node.properties.get("floor", 1))
    sx, sy, sz = MESH_SIZE.get(node.type, (3.0, 3.0, WALL_HEIGHT_M))
    z_center = floor_z(fl) + sz / 2
    color = MESH_RGBA.get(node.type, (0.4, 0.5, 0.6, 0.5))
    return RoomMesh(
        node_id=node.id,
        label=node.label,
        node_type=node.type,
        floor=fl,
        center=(node.pose.x, node.pose.y, z_center),
        size=(sx, sy, sz),
        color=color,
    )


def all_meshes(graph: Any) -> list[RoomMesh]:
    return [node_mesh(graph, nid) for nid in sorted(graph.node_ids())]


def write_obj(path: Path, meshes: Iterable[RoomMesh], *, combined: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    chunks: list[str] = []
    offset = 0
    for mesh in meshes:
        body = mesh.to_obj()
        if not combined:
            path.write_text(body, encoding="utf-8")
            continue
        lines = body.splitlines()
        vert_lines = [ln for ln in lines if ln.startswith("v ")]
        face_lines = [ln for ln in lines if ln.startswith("f ")]
        chunks.extend([ln for ln in lines if ln.startswith("#") or ln.startswith("o ")])
        chunks.extend(vert_lines)
        for ln in face_lines:
            parts = ln.split()
            idxs = [str(int(p) + offset) for p in parts[1:]]
            chunks.append("f " + " ".join(idxs))
        offset += len(vert_lines)
    if combined:
        header = "# RobotEscapeRoom combined scene\n# units: metres, Z-up\n"
        path.write_text(header + "\n".join(chunks) + "\n", encoding="utf-8")


def write_manifest(meshes: list[RoomMesh]) -> None:
    MESH_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": "robot_escape_room",
        "units": "metres",
        "frame_id": "map",
        "floor_height_m": FLOOR_HEIGHT_M,
        "wall_height_m": WALL_HEIGHT_M,
        "combined_scene": str(SCENE_OBJ.relative_to(HERE.parent)),
        "rooms": [
            {
                "id": m.node_id,
                "label": m.label,
                "type": m.node_type,
                "floor": m.floor,
                "obj": f"meshes/escape_room/{m.node_id}.obj",
                "center": {"x": m.center[0], "y": m.center[1], "z": m.center[2]},
                "size": {"x": m.size[0], "y": m.size[1], "z": m.size[2]},
                "color_rgba": list(m.color),
            }
            for m in meshes
        ],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


# --- isometric drawing helpers (for render_escape_room_hero.py) ----------------

ISO_SCALE = 5.6


@dataclass(frozen=True)
class IsoView:
    cx: float
    cy: float
    scale: float = ISO_SCALE


def iso_project(
    x: float,
    y: float,
    z: float,
    cx: float,
    cy: float,
    *,
    scale: float = ISO_SCALE,
) -> tuple[float, float]:
    dx, dy = x - 14.0, y
    sx = cx + (dx - dy) * scale * 0.74
    sy = cy - z * scale * 1.1 + (dx + dy) * scale * 0.30
    return sx, sy


def fit_iso_view(
    graph: Any,
    width: int,
    height: int,
    *,
    margin: float = 0.10,
    header_h: int = 26,
) -> IsoView:
    """Scale and centre the facility to fill the 3D sim panel."""
    base_cx, base_cy, base_scale = width / 2, height / 2, ISO_SCALE
    corners = [c for m in all_meshes(graph) for c in m.corners()]
    screen = [iso_project(*c, base_cx, base_cy, scale=base_scale) for c in corners]
    xs = [p[0] for p in screen]
    ys = [p[1] for p in screen]
    bbox_w = max(xs) - min(xs)
    bbox_h = max(ys) - min(ys)
    usable_w = width * (1 - 2 * margin)
    usable_h = (height - header_h) * (1 - 2 * margin)
    zoom = min(usable_w / max(bbox_w, 1), usable_h / max(bbox_h, 1))
    scale = base_scale * zoom
    screen = [iso_project(*c, base_cx, base_cy, scale=scale) for c in corners]
    xs = [p[0] for p in screen]
    ys = [p[1] for p in screen]
    bbox_cx = (min(xs) + max(xs)) / 2
    bbox_cy = (min(ys) + max(ys)) / 2
    target_cy = header_h + (height - header_h) / 2
    return IsoView(
        cx=width / 2 + (width / 2 - bbox_cx),
        cy=target_cy + (target_cy - bbox_cy),
        scale=scale,
    )


def iso_depth(x: float, y: float, z: float) -> float:
    return x + y - z * 0.35


def iso_faces(mesh: RoomMesh, cx: float, cy: float) -> list[tuple[float, list[tuple[float, float]], tuple[int, int, int, int]]]:
    corners = mesh.corners()
    pts = [iso_project(*c, cx, cy) for c in corners]
    # bottom 0-3, top 4-7
    floor_face = (iso_depth(*corners[0]), [pts[0], pts[1], pts[2], pts[3]], (30, 41, 59, 200))
    walls = []
    quads = [
        ([0, 1, 5, 4], (45, 55, 72, 210)),
        ([1, 2, 6, 5], (55, 65, 82, 220)),
        ([2, 3, 7, 6], (40, 50, 68, 210)),
        ([3, 0, 4, 7], (35, 45, 62, 200)),
    ]
    for idxs, tint in quads:
        depth = sum(iso_depth(*corners[i]) for i in idxs) / len(idxs)
        walls.append((depth, [pts[i] for i in idxs], tint))
    r, g, b, a = mesh.color
    accent = (int(r * 255), int(g * 255), int(b * 255), min(255, int(a * 255) + 50))
    roof = (iso_depth(*mesh.center) + 0.01, [pts[4], pts[5], pts[6], pts[7]], accent)
    return sorted([floor_face, *walls, roof], key=lambda f: f[0])
