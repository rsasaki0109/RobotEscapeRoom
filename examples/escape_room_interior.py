"""Detailed interior room geometry — walls with doorways, tiles, props.

Each topology node becomes a furnished room shell (not a plain box). Geometry
feeds OBJ export and the hero GIF mesh renderer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from escape_room_meshes import (
    MESH_RGBA,
    MESH_SIZE,
    WALL_HEIGHT_M,
    floor_z,
)

WALL_T = 0.14
DOOR_W = 1.05
DOOR_H = 2.15
SLAB_T = 0.08


@dataclass
class GeoTri:
    v0: tuple[float, float, float]
    v1: tuple[float, float, float]
    v2: tuple[float, float, float]
    material: str


@dataclass
class RoomGeometry:
    node_id: str
    label: str
    node_type: str
    floor: int
    center: tuple[float, float, float]
    size: tuple[float, float, float]
    color: tuple[float, float, float, float]
    tris: list[GeoTri] = field(default_factory=list)


def _add_tri(room: RoomGeometry, v0, v1, v2, material: str) -> None:
    room.tris.append(GeoTri(v0, v1, v2, material))


def _add_quad(room: RoomGeometry, v0, v1, v2, v3, material: str) -> None:
    _add_tri(room, v0, v1, v2, material)
    _add_tri(room, v0, v2, v3, material)


def _add_box(
    room: RoomGeometry,
    x0: float,
    y0: float,
    z0: float,
    x1: float,
    y1: float,
    z1: float,
    material: str,
) -> None:
    verts = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]
    quads = (
        (0, 1, 2, 3), (4, 6, 5, 0), (0, 5, 6, 1), (1, 6, 7, 2),
        (2, 7, 4, 3), (3, 4, 5, 0),
    )
    for a, b, c, d in quads:
        _add_quad(room, verts[a], verts[b], verts[c], verts[d], material)


def _door_walls(graph: Any, node_id: str) -> list[tuple[str, int]]:
    """Return wall openings as (axis, sign) for same-floor neighbours."""
    node = graph.get_node(node_id)
    fl = int(node.properties.get("floor", 1))
    doors: list[tuple[str, int]] = []
    for edge in graph.edges():
        if edge.source == node_id:
            other_id = edge.target
        elif edge.target == node_id:
            other_id = edge.source
        else:
            continue
        other = graph.get_node(other_id)
        if int(other.properties.get("floor", 1)) != fl:
            continue
        dx = other.pose.x - node.pose.x
        dy = other.pose.y - node.pose.y
        if abs(dx) >= abs(dy) and abs(dx) > 0.4:
            doors.append(("x", 1 if dx > 0 else -1))
        elif abs(dy) > 0.4:
            doors.append(("y", 1 if dy > 0 else -1))
    return doors


def _wall_segments(
    span0: float,
    span1: float,
    gap0: float,
    gap1: float,
) -> list[tuple[float, float]]:
    if gap1 <= span0 or gap0 >= span1:
        return [(span0, span1)]
    segs: list[tuple[float, float]] = []
    if gap0 > span0:
        segs.append((span0, min(gap0, span1)))
    if gap1 < span1:
        segs.append((max(gap1, span0), span1))
    return segs


def _tiled_floor(room: RoomGeometry, cx: float, cy: float, hx: float, hy: float, z: float) -> None:
    tiles = 4
    for ix in range(tiles):
        for iy in range(tiles):
            x0 = cx - hx + (2 * hx) * ix / tiles
            x1 = cx - hx + (2 * hx) * (ix + 1) / tiles
            y0 = cy - hy + (2 * hy) * iy / tiles
            y1 = cy - hy + (2 * hy) * (iy + 1) / tiles
            mat = "floor_tile" if (ix + iy) % 2 == 0 else "floor_tile_alt"
            _add_quad(room, (x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z), mat)


def _ceiling_lights(room: RoomGeometry, cx: float, cy: float, hx: float, hy: float, z: float) -> None:
    for ox, oy in ((0, 0), (-hx * 0.45, 0), (hx * 0.45, 0)):
        _add_box(room, cx + ox - 0.35, cy + oy - 0.18, z - 0.04, cx + ox + 0.35, cy + oy + 0.18, z, "light")


def _wall_y(
    room: RoomGeometry,
    x: float,
    y0: float,
    y1: float,
    z0: float,
    z1: float,
    *,
    door: bool,
    door_cy: float,
) -> None:
    gap0, gap1 = door_cy - DOOR_W / 2, door_cy + DOOR_W / 2
    for ya, yb in _wall_segments(y0, y1, gap0, gap1) if door else [(y0, y1)]:
        _add_quad(room, (x, ya, z0), (x, yb, z0), (x, yb, z1), (x, ya, z1), "wall")
        ws = z0 + min(1.0, z1 - z0) * 0.35
        _add_quad(room, (x, ya, z0), (x, yb, z0), (x, yb, ws), (x, ya, ws), "wainscot")
    if door:
        _add_box(room, x - 0.06, gap0, z0, x + 0.06, gap0 + 0.07, z0 + DOOR_H, "door_frame")
        _add_box(room, x - 0.06, gap1 - 0.07, z0, x + 0.06, gap1, z0 + DOOR_H, "door_frame")
        _add_box(room, x - 0.06, gap0, z0 + DOOR_H - 0.07, x + 0.06, gap1, z0 + DOOR_H, "door_frame")


def _wall_x(
    room: RoomGeometry,
    y: float,
    x0: float,
    x1: float,
    z0: float,
    z1: float,
    *,
    door: bool,
    door_cx: float,
) -> None:
    gap0, gap1 = door_cx - DOOR_W / 2, door_cx + DOOR_W / 2
    for xa, xb in _wall_segments(x0, x1, gap0, gap1) if door else [(x0, x1)]:
        _add_quad(room, (xa, y, z0), (xb, y, z0), (xb, y, z1), (xa, y, z1), "wall")
        ws = z0 + min(1.0, z1 - z0) * 0.35
        _add_quad(room, (xa, y, z0), (xb, y, z0), (xb, y, ws), (xa, y, ws), "wainscot")
    if door:
        _add_box(room, gap0, y - 0.06, z0, gap0 + 0.07, y + 0.06, z0 + DOOR_H, "door_frame")
        _add_box(room, gap1 - 0.07, y - 0.06, z0, gap1, y + 0.06, z0 + DOOR_H, "door_frame")
        _add_box(room, gap0, y - 0.06, z0 + DOOR_H - 0.07, gap1, y + 0.06, z0 + DOOR_H, "door_frame")


# (name, dx, dy, sx, sy, sz) relative to room centre at floor z0
ROOM_PROPS: dict[str, list[tuple[str, float, float, float, float, float, float]]] = {
    "holding_cell": [
        ("prop", -0.9, 0.0, 0.35, 1.6, 0.45, 0.5),
        ("prop", 0.85, -0.7, 0.25, 0.18, 1.4, 0.25),
        ("prop", 0.85, 0.7, 0.25, 0.18, 1.4, 0.25),
    ],
    "server_room": [
        ("prop", -0.9, -0.8, 0.9, 0.45, 0.55, 1.8),
        ("prop", -0.9, 0.0, 0.9, 0.45, 0.55, 1.8),
        ("prop", -0.9, 0.8, 0.9, 0.45, 0.55, 1.8),
        ("prop", 0.5, 0.0, 0.9, 0.6, 0.4, 0.9),
    ],
    "main_lab": [
        ("prop", 0.0, 0.0, 0.9, 1.4, 0.75, 0.85),
        ("prop", -1.0, -1.0, 0.9, 0.5, 0.5, 1.0),
        ("prop", -1.0, 1.0, 0.9, 0.5, 0.5, 1.0),
    ],
    "security_office": [
        ("prop", 0.2, 0.0, 0.75, 1.2, 0.75, 0.75),
        ("prop", -1.1, 0.0, 0.75, 0.35, 0.9, 1.4),
        ("prop", 1.0, -1.0, 0.75, 0.55, 0.45, 0.55),
    ],
    "storage_bay": [
        ("prop", -0.8, -0.8, 0.55, 0.9, 0.9, 1.2),
        ("prop", 0.8, -0.8, 0.55, 0.9, 0.9, 1.2),
        ("prop", 0.0, 0.9, 0.55, 1.6, 0.7, 0.7),
    ],
    "control_room": [
        ("prop", 0.0, 0.2, 0.85, 1.8, 0.8, 0.9),
        ("prop", -1.0, -0.8, 0.85, 0.45, 1.2, 1.6),
        ("prop", 1.0, -0.8, 0.85, 0.45, 1.2, 1.6),
    ],
    "elevator_lobby": [
        ("prop", 0.6, 0.0, 0.9, 0.9, 0.05, 2.2),
        ("prop", -0.8, 0.0, 0.9, 0.35, 0.9, 1.1),
    ],
    "emergency_exit": [
        ("prop", 0.0, 0.5, 1.0, 1.4, 0.12, 2.1),
        ("prop", 0.0, -0.6, 0.9, 0.8, 0.6, 0.4),
    ],
    "maintenance_exit": [
        ("prop", 0.0, 0.4, 1.0, 1.2, 0.1, 2.0),
    ],
    "basement_tunnel": [
        ("prop", -0.5, 0.0, 0.45, 0.8, 0.5, 0.5),
        ("prop", 0.6, 0.0, 0.45, 0.8, 0.5, 0.5),
    ],
}


def build_room_geometry(graph: Any, node_id: str) -> RoomGeometry:
    node = graph.get_node(node_id)
    fl = int(node.properties.get("floor", 1))
    sx, sy, sz = MESH_SIZE.get(node.type, (3.0, 3.0, WALL_HEIGHT_M))
    cx, cy = node.pose.x, node.pose.y
    z0 = floor_z(fl)
    z1 = z0 + sz
    hx, hy = sx / 2, sy / 2
    color = MESH_RGBA.get(node.type, (0.4, 0.5, 0.6, 0.5))

    room = RoomGeometry(
        node_id=node_id,
        label=node.label,
        node_type=node.type,
        floor=fl,
        center=(cx, cy, z0 + sz / 2),
        size=(sx, sy, sz),
        color=color,
    )

    doors = _door_walls(graph, node_id)
    door_x_pos = {sign for axis, sign in doors if axis == "x"}
    door_y_pos = {sign for axis, sign in doors if axis == "y"}

    _tiled_floor(room, cx, cy, hx - WALL_T, hy - WALL_T, z0 + SLAB_T)
    _add_box(room, cx - hx, cy - hy, z1 - SLAB_T, cx + hx, cy + hy, z1, "ceiling")
    _ceiling_lights(room, cx, cy, hx, hy, z1 - 0.02)

    xi0, xi1 = cx - hx, cx + hx
    yi0, yi1 = cy - hy, cy + hy

    _wall_y(room, xi0, yi0, yi1, z0, z1, door=(-1 in door_x_pos), door_cy=cy)
    _wall_y(room, xi1, yi0, yi1, z0, z1, door=(1 in door_x_pos), door_cy=cy)
    _wall_x(room, yi0, xi0, xi1, z0, z1, door=(-1 in door_y_pos), door_cx=cx)
    _wall_x(room, yi1, xi0, xi1, z0, z1, door=(1 in door_y_pos), door_cx=cx)

    for _name, dx, dy, bsx, bsy, bsz, bz in ROOM_PROPS.get(node_id, []):
        _add_box(
            room,
            cx + dx - bsx / 2,
            cy + dy - bsy / 2,
            z0 + bz,
            cx + dx + bsx / 2,
            cy + dy + bsy / 2,
            z0 + bz + bsz,
            "prop",
        )

    if node.type == "stairs":
        steps = 5
        for i in range(steps):
            t = i / steps
            _add_box(
                room,
                cx - hx * 0.5,
                cy - hy * 0.4 + (hy * 0.8) * t,
                z0 + sz * t / steps,
                cx + hx * 0.5,
                cy - hy * 0.4 + (hy * 0.8) * (t + 1 / steps),
                z0 + sz * (t + 1 / steps) / steps,
                "prop",
            )

    return room


def all_room_geometry(graph: Any) -> list[RoomGeometry]:
    return [build_room_geometry(graph, nid) for nid in sorted(graph.node_ids())]


def geometry_to_obj(room: RoomGeometry) -> str:
    lines = [f"# {room.label} ({room.node_id}) floor {room.floor}", f"o {room.node_id}"]
    for tri in room.tris:
        for v in (tri.v0, tri.v1, tri.v2):
            lines.append(f"v {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}")
    base = 0
    for _tri in room.tris:
        lines.append(f"f {base + 1} {base + 2} {base + 3}")
        base += 3
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class FoxgloveCube:
    center: tuple[float, float, float]
    size: tuple[float, float, float]
    rgba: tuple[float, float, float, float]


def _fg_cube(
    x0: float,
    y0: float,
    z0: float,
    x1: float,
    y1: float,
    z1: float,
    rgba: tuple[float, float, float, float],
    out: list[FoxgloveCube],
) -> None:
    out.append(
        FoxgloveCube(
            center=((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2),
            size=(abs(x1 - x0), abs(y1 - y0), abs(z1 - z0)),
            rgba=rgba,
        )
    )


def _fg_wall_y(
    x: float,
    y0: float,
    y1: float,
    z0: float,
    z1: float,
    *,
    door: bool,
    door_cy: float,
    rgba: tuple[float, float, float, float],
    out: list[FoxgloveCube],
) -> None:
    gap0, gap1 = door_cy - DOOR_W / 2, door_cy + DOOR_W / 2
    for ya, yb in _wall_segments(y0, y1, gap0, gap1) if door else [(y0, y1)]:
        _fg_cube(x - WALL_T / 2, ya, z0, x + WALL_T / 2, yb, z1, rgba, out)
    if door:
        frame = (rgba[0] * 0.45, rgba[1] * 0.45, rgba[2] * 0.45, rgba[3])
        _fg_cube(x - 0.06, gap0, z0, x + 0.06, gap0 + 0.07, z0 + DOOR_H, frame, out)
        _fg_cube(x - 0.06, gap1 - 0.07, z0, x + 0.06, gap1, z0 + DOOR_H, frame, out)
        _fg_cube(x - 0.06, gap0, z0 + DOOR_H - 0.07, x + 0.06, gap1, z0 + DOOR_H, frame, out)


def _fg_wall_x(
    y: float,
    x0: float,
    x1: float,
    z0: float,
    z1: float,
    *,
    door: bool,
    door_cx: float,
    rgba: tuple[float, float, float, float],
    out: list[FoxgloveCube],
) -> None:
    gap0, gap1 = door_cx - DOOR_W / 2, door_cx + DOOR_W / 2
    for xa, xb in _wall_segments(x0, x1, gap0, gap1) if door else [(x0, x1)]:
        _fg_cube(xa, y - WALL_T / 2, z0, xb, y + WALL_T / 2, z1, rgba, out)
    if door:
        frame = (rgba[0] * 0.45, rgba[1] * 0.45, rgba[2] * 0.45, rgba[3])
        _fg_cube(gap0, y - 0.06, z0, gap0 + 0.07, y + 0.06, z0 + DOOR_H, frame, out)
        _fg_cube(gap1 - 0.07, y - 0.06, z0, gap1, y + 0.06, z0 + DOOR_H, frame, out)
        _fg_cube(gap0, y - 0.06, z0 + DOOR_H - 0.07, gap1, y + 0.06, z0 + DOOR_H, frame, out)


def foxglove_furnished_cubes(graph: Any, route_set: set[str]) -> list[FoxgloveCube]:
    """Compact furnished-room primitives for Foxglove (floors, walls, props)."""
    cubes: list[FoxgloveCube] = []
    for node_id in sorted(graph.node_ids()):
        node = graph.get_node(node_id)
        fl = int(node.properties.get("floor", 1))
        sx, sy, sz = MESH_SIZE.get(node.type, (3.0, 3.0, WALL_HEIGHT_M))
        cx, cy = node.pose.x, node.pose.y
        z0 = floor_z(fl)
        z1 = z0 + sz
        hx, hy = sx / 2, sy / 2
        r, g, b, a = MESH_RGBA.get(node.type, (0.4, 0.5, 0.6, 0.5))
        if node_id in route_set:
            wall = (r, g, b, min(1.0, a + 0.3))
            floor = (0.34, 0.36, 0.42, 0.95)
            prop = (r * 0.85 + 0.1, g * 0.85 + 0.1, b * 0.85 + 0.1, 0.92)
        else:
            wall = (r * 0.65, g * 0.65, b * 0.65, a * 0.75)
            floor = (0.26, 0.28, 0.32, 0.85)
            prop = (r * 0.55, g * 0.55, b * 0.55, 0.8)

        ih, iw = hx - WALL_T, hy - WALL_T
        _fg_cube(cx - ih, cy - iw, z0, cx + ih, cy + iw, z0 + SLAB_T, floor, cubes)
        _fg_cube(cx - hx, cy - hy, z1 - SLAB_T, cx + hx, cy + hy, z1, (wall[0] * 0.8, wall[1] * 0.8, wall[2] * 0.8, 0.7), cubes)
        for ox, oy in ((0, 0), (-hx * 0.45, 0), (hx * 0.45, 0)):
            _fg_cube(
                cx + ox - 0.35, cy + oy - 0.18, z1 - 0.06,
                cx + ox + 0.35, cy + oy + 0.18, z1 - 0.01,
                (1.0, 0.98, 0.88, 0.95),
                cubes,
            )

        doors = _door_walls(graph, node_id)
        door_x_pos = {sign for axis, sign in doors if axis == "x"}
        door_y_pos = {sign for axis, sign in doors if axis == "y"}
        xi0, xi1 = cx - hx, cx + hx
        yi0, yi1 = cy - hy, cy + hy
        _fg_wall_y(xi0, yi0, yi1, z0, z1, door=(-1 in door_x_pos), door_cy=cy, rgba=wall, out=cubes)
        _fg_wall_y(xi1, yi0, yi1, z0, z1, door=(1 in door_x_pos), door_cy=cy, rgba=wall, out=cubes)
        _fg_wall_x(yi0, xi0, xi1, z0, z1, door=(-1 in door_y_pos), door_cx=cx, rgba=wall, out=cubes)
        _fg_wall_x(yi1, xi0, xi1, z0, z1, door=(1 in door_y_pos), door_cx=cx, rgba=wall, out=cubes)

        for _name, dx, dy, bsx, bsy, bsz, bz in ROOM_PROPS.get(node_id, []):
            _fg_cube(
                cx + dx - bsx / 2, cy + dy - bsy / 2, z0 + bz,
                cx + dx + bsx / 2, cy + dy + bsy / 2, z0 + bz + bsz,
                prop,
                cubes,
            )
        if node.type == "stairs":
            for i in range(5):
                t = i / 5
                _fg_cube(
                    cx - hx * 0.5,
                    cy - hy * 0.4 + (hy * 0.8) * t,
                    z0 + sz * t / 5,
                    cx + hx * 0.5,
                    cy - hy * 0.4 + (hy * 0.8) * (t + 1 / 5),
                    z0 + sz * (t + 1 / 5) / 5,
                    prop,
                    cubes,
                )
    return cubes
