"""Deterministic README hero renderer — one frame per planner step.

Renders split-view frames directly from ``robot_escape_room_timeline.json``
so the robot visibly moves every frame. No Docker / Playwright capture drift.

    PYTHONPATH=. python3 scripts/foxglove_hero/render_escape_room_hero.py /tmp/erframes
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "examples"))

from escape_room_3dgs_map import load_map  # noqa: E402
from escape_room_camera import render_camera_view  # noqa: E402
from escape_room_meshes import IsoView, all_meshes, fit_iso_view, iso_project  # noqa: E402

from semantic_toponav.escape_room.runner import POWER_ITEM, UNPOWERED_TYPES  # noqa: E402
from semantic_toponav.graph.serialization import load_graph  # noqa: E402

GRAPH_PATH = ROOT / "examples/robot_escape_room.yaml"
TIMELINE_PATH = ROOT / "docs/foxglove/robot_escape_room_timeline.json"

MAP_W, CAM_W, SIM_W = 280, 340, 660
BODY_H = 480
TOP_H, BOT_H = 56, 64
FLOOR_HEIGHT_M = 4.2
FLOOR_LABEL = {-1: "B1", 1: "1F", 2: "2F", 3: "3F"}
X_MIN, X_MAX = -2.0, 30.0
Y_MIN, Y_MAX = -10.0, 38.0
_ISO_VIEW: IsoView | None = None

BG = (8, 14, 28)
BAR = (12, 22, 42)
PANEL = (13, 24, 44)
PANEL_2 = (15, 29, 52)
PANEL_3 = (19, 35, 61)
TEXT = (248, 250, 252)
MUTED = (148, 163, 184)
CYAN = (34, 211, 238)
PINK = (244, 63, 94)
RED = (248, 113, 113)
AMBER = (245, 158, 11)
BLUE = (96, 165, 250)
PURPLE = (168, 85, 247)
ORANGE = (251, 146, 60)
DIM = (71, 85, 105)
GREEN = (34, 197, 94)

NODE_COLORS = {
    "room": BLUE,
    "corridor": MUTED,
    "intersection": PURPLE,
    "stairs": ORANGE,
    "exit": GREEN,
    "sealed_exit": DIM,
}


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    family = "DejaVuSans-Bold" if bold else "DejaVuSans"
    for raw in (
        f"/usr/share/fonts/truetype/dejavu/{family}.ttf",
        f"/usr/share/fonts/dejavu/{family}.ttf",
    ):
        path = Path(raw)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


FONT_TITLE = _font(26, bold=True)
FONT_STATUS = _font(22, bold=True)
FONT_LEGEND = _font(16)
FONT_BADGE = _font(14, bold=True)
FONT_PANEL = _font(15, bold=True)
FONT_SM = _font(11)
FONT_XS = _font(9)


def _round_rect(draw, xy, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def _floor(node) -> int:
    return int(node.properties.get("floor", 1))


def _node_xyz(graph, node_id: str) -> tuple[float, float, float]:
    node = graph.get_node(node_id)
    z = (_floor(node) - 1) * FLOOR_HEIGHT_M
    return node.pose.x, node.pose.y, z


def _iso_view(graph) -> IsoView:
    global _ISO_VIEW
    if _ISO_VIEW is None:
        _ISO_VIEW = fit_iso_view(graph, SIM_W, BODY_H)
    return _ISO_VIEW


def _iso(x: float, y: float, z: float, view: IsoView) -> tuple[float, float]:
    return iso_project(x, y, z, view.cx, view.cy, scale=view.scale)


def _depth(x: float, y: float, z: float) -> float:
    return x + y - z * 0.35


def _partial(a, b, t):
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t


def _edge_open(edge, items: set[str]) -> bool:
    lock = edge.properties.get("lock")
    if lock and lock not in items:
        return False
    if edge.type in UNPOWERED_TYPES and POWER_ITEM not in items:
        return False
    return edge.type != "restricted"


def _world_xy(node) -> tuple[float, float]:
    floor = _floor(node)
    band = {-1: 0, 1: 1, 2: 2, 3: 3}.get(floor, floor)
    return node.pose.x, node.pose.y + band * 9.0


def _map_px(x, y, box):
    x0, y0, x1, y1 = box
    px = x0 + 14 + (x - X_MIN) / (X_MAX - X_MIN) * (x1 - x0 - 28)
    py = y1 - 14 - (y - Y_MIN) / (Y_MAX - Y_MIN) * (y1 - y0 - 28)
    return px, py


def _robot_xy(graph, meta: dict) -> tuple[float, float, float]:
    route = meta.get("route") or []
    progress = float(meta.get("progress", 0.0))
    if len(route) >= 2:
        segment = min(int(progress), len(route) - 2)
        local = max(0.0, min(1.0, progress - segment))
        a = _node_xyz(graph, route[segment])
        b = _node_xyz(graph, route[segment + 1])
        return (
            a[0] + (b[0] - a[0]) * local,
            a[1] + (b[1] - a[1]) * local,
            a[2] + (b[2] - a[2]) * local,
        )
    loc = meta.get("location") or (route[0] if route else "holding_cell")
    return _node_xyz(graph, loc)


def _render_map(graph, meta: dict) -> Image.Image:
    items = set(meta.get("items", []))
    route = meta.get("route") or []
    progress = float(meta.get("progress", 0.0))
    box = (0.0, 28.0, float(MAP_W), float(BODY_H - 8))

    panel = Image.new("RGBA", (MAP_W, BODY_H), PANEL)
    draw = ImageDraw.Draw(panel, "RGBA")
    draw.rectangle((0, 0, MAP_W, 26), fill=(9, 17, 31))
    draw.text((14, 6), "topology map", font=FONT_PANEL, fill=TEXT)

    for floor, band in [(-1, 0), (1, 1), (2, 2), (3, 3)]:
        y_low, y_high = band * 9.0 - 4.5, band * 9.0 + 4.5
        _, top = _map_px(0, y_high, box)
        _, bottom = _map_px(0, y_low, box)
        fill = PANEL_2 if band % 2 else PANEL_3
        _round_rect(draw, (10, top, MAP_W - 10, bottom), 8, fill, (71, 85, 105), 1)
        draw.text((18, top + 5), f"floor {FLOOR_LABEL[floor]}", font=FONT_SM, fill=MUTED)

    segment = min(int(progress), len(route) - 2) if len(route) >= 2 else 0
    local = progress - segment if len(route) >= 2 else 0.0

    for edge in graph.edges():
        a = _map_px(*_world_xy(graph.get_node(edge.source))[:2], box)
        b = _map_px(*_world_xy(graph.get_node(edge.target))[:2], box)
        if not _edge_open(edge, items):
            draw.line([a, b], fill=(*RED, 160), width=2)
        elif edge.type == "elevator_connection":
            draw.line([a, b], fill=(*ORANGE, 210), width=3)
        else:
            draw.line([a, b], fill=(*MUTED, 150), width=2)

    if len(route) >= 2:
        for idx, (a_id, b_id) in enumerate(zip(route[:-1], route[1:], strict=False)):
            a = _map_px(*_world_xy(graph.get_node(a_id))[:2], box)
            b = _map_px(*_world_xy(graph.get_node(b_id))[:2], box)
            if idx < segment:
                draw.line([a, b], fill=(*CYAN, 255), width=5)
            elif idx == segment:
                mid = _partial(a, b, local)
                draw.line([a, mid], fill=(*CYAN, 255), width=5)
                draw.line([mid, b], fill=(*PINK, 130), width=3)
            else:
                draw.line([a, b], fill=(*PINK, 100), width=3)

    route_set = set(route)
    for node in graph.nodes():
        x, y = _map_px(*_world_xy(node), box)
        color = NODE_COLORS.get(node.type, BLUE)
        r = 7 if node.id in route_set else 5
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(*color, 240), outline=(3, 7, 18), width=1)

    if len(route) >= 2:
        a = _world_xy(graph.get_node(route[segment]))
        b = _world_xy(graph.get_node(route[segment + 1]))
        mx, my = _map_px(
            a[0] + (b[0] - a[0]) * local,
            a[1] + (b[1] - a[1]) * local,
            box,
        )
    else:
        loc = meta.get("location") or (route[0] if route else "holding_cell")
        mx, my = _map_px(*_world_xy(graph.get_node(loc)), box)
    draw.ellipse((mx - 14, my - 14, mx + 14, my + 14), fill=(*CYAN, 50))
    draw.ellipse((mx - 9, my - 9, mx + 9, my + 9), fill=(8, 47, 73), outline=CYAN, width=3)
    draw.ellipse((mx - 3, my - 3, mx + 3, my + 3), fill=(255, 255, 255))
    draw.text((mx + 14, my - 6), "T-0", font=FONT_SM, fill=CYAN)

    return panel


def _render_camera(graph, meta: dict) -> Image.Image:
    panel = render_camera_view(graph, meta, width=CAM_W, height=BODY_H)
    draw = ImageDraw.Draw(panel, "RGBA")
    draw.text((14, 6), "robot camera · rgb", font=FONT_PANEL, fill=TEXT)

    loc = meta.get("location") or "holding_cell"
    if graph.has_node(loc):
        node = graph.get_node(loc)
        fl = int(node.properties.get("floor", 1))
        floor_tag = FLOOR_LABEL.get(fl, str(fl))
        draw.text((CAM_W - 14, 6), f"{node.label[:16]} · {floor_tag}", font=FONT_SM, fill=MUTED, anchor="ra")

    # REC badge + crosshair
    draw.ellipse((16, BODY_H - 28, 28, BODY_H - 16), fill=(239, 68, 68))
    draw.text((34, BODY_H - 30), "REC", font=FONT_SM, fill=(252, 165, 165))
    cx, cy = CAM_W // 2, BODY_H // 2 + 8
    draw.line([(cx - 14, cy), (cx - 4, cy)], fill=(148, 163, 184, 180), width=1)
    draw.line([(cx + 4, cy), (cx + 14, cy)], fill=(148, 163, 184, 180), width=1)
    draw.line([(cx, cy - 14), (cx, cy - 4)], fill=(148, 163, 184, 180), width=1)
    draw.line([(cx, cy + 4), (cx, cy + 14)], fill=(148, 163, 184, 180), width=1)
    return panel


_FACILITY_BG: Image.Image | None = None


def _render_sim(graph, meta: dict) -> Image.Image:
    global _FACILITY_BG
    view = _iso_view(graph)
    if _FACILITY_BG is None:
        _FACILITY_BG = load_map(graph)

    items = set(meta.get("items", []))
    route = meta.get("route") or []
    progress = float(meta.get("progress", 0.0))
    panel = Image.new("RGBA", (SIM_W, BODY_H), (10, 18, 34))
    panel.paste(_FACILITY_BG, (0, 0), _FACILITY_BG)
    draw = ImageDraw.Draw(panel, "RGBA")

    draw.rectangle((0, 0, SIM_W, 26), fill=(9, 17, 31, 240))
    draw.text((14, 6), "3D sim · furnished rooms", font=FONT_PANEL, fill=TEXT)
    draw.text((SIM_W - 14, 6), "OBJ interior meshes", font=FONT_SM, fill=MUTED, anchor="ra")

    segment = min(int(progress), len(route) - 2) if len(route) >= 2 else 0
    local = progress - segment if len(route) >= 2 else 0.0
    rx, ry, rz = _robot_xy(graph, meta)

    edges: list[tuple[float, tuple, tuple, tuple, int]] = []
    for edge in graph.edges():
        a = _node_xyz(graph, edge.source)
        b = _node_xyz(graph, edge.target)
        if not _edge_open(edge, items):
            color = (*RED, 140)
            width = 2
        elif edge.type == "elevator_connection":
            color = (*ORANGE, 220)
            width = 4
        else:
            color = (*MUTED, 160)
            width = 2
        depth = (_depth(*a) + _depth(*b)) / 2
        edges.append((depth, color, _iso(*a, view), _iso(*b, view), width))

    if len(route) >= 2:
        for idx, (a_id, b_id) in enumerate(zip(route[:-1], route[1:], strict=False)):
            a = _node_xyz(graph, a_id)
            b = _node_xyz(graph, b_id)
            if idx < segment:
                edges.append(((_depth(*a) + _depth(*b)) / 2, (*CYAN, 255), _iso(*a, view), _iso(*b, view), 5))
            elif idx == segment:
                mid = (
                    a[0] + (b[0] - a[0]) * local,
                    a[1] + (b[1] - a[1]) * local,
                    a[2] + (b[2] - a[2]) * local,
                )
                edges.append(((_depth(*a) + _depth(*mid)) / 2, (*CYAN, 255), _iso(*a, view), _iso(*mid, view), 5))
                edges.append(((_depth(*mid) + _depth(*b)) / 2, (*PINK, 180), _iso(*mid, view), _iso(*b, view), 4))
            else:
                edges.append(((_depth(*a) + _depth(*b)) / 2, (*PINK, 120), _iso(*a, view), _iso(*b, view), 4))

    for _edge_depth, color, a, b, width in sorted(edges, key=lambda e: e[0]):
        draw.line([a, b], fill=color, width=width)

    rsx, rsy = _iso(rx, ry, rz, view)
    draw.ellipse((rsx - 18, rsy - 18, rsx + 18, rsy + 18), fill=(*CYAN, 45))
    draw.ellipse((rsx - 12, rsy - 12, rsx + 12, rsy + 12), fill=(8, 47, 73), outline=CYAN, width=3)
    draw.ellipse((rsx - 4, rsy - 4, rsx + 4, rsy + 4), fill=(255, 255, 255))
    draw.text((rsx + 16, rsy - 8), "T-0", font=FONT_SM, fill=CYAN)

    for mesh in all_meshes(graph):
        if mesh.node_id in {"holding_cell", "emergency_exit", "maintenance_exit", "control_room"}:
            x, y, z = mesh.center
            lx, ly = iso_project(x, y, z + mesh.size[2] / 2 + 0.2, view.cx, view.cy, scale=view.scale)
            draw.text((lx, ly), mesh.label[:14], font=FONT_XS, fill=TEXT, anchor="ma")

    return panel


def _legend_chip(draw, x, y, color, label):
    _round_rect(draw, (x, y, x + 148, y + 28), 10, (18, 30, 52), (51, 65, 85), 1)
    draw.ellipse((x + 10, y + 9, x + 22, y + 21), fill=color)
    draw.text((x + 30, y + 5), label, font=FONT_BADGE, fill=TEXT)


def render_frame(graph, meta: dict) -> Image.Image:
    total_w = MAP_W + CAM_W + SIM_W
    body = Image.new("RGB", (total_w, BODY_H), BG)
    body.paste(_render_map(graph, meta).convert("RGB"), (0, 0))
    body.paste(_render_camera(graph, meta).convert("RGB"), (MAP_W, 0))
    body.paste(_render_sim(graph, meta).convert("RGB"), (MAP_W + CAM_W, 0))
    draw_body = ImageDraw.Draw(body)
    draw_body.line([(MAP_W, 0), (MAP_W, BODY_H)], fill=(51, 65, 85), width=3)
    draw_body.line([(MAP_W + CAM_W, 0), (MAP_W + CAM_W, BODY_H)], fill=(51, 65, 85), width=3)

    out = Image.new("RGB", (total_w, BODY_H + TOP_H + BOT_H), BG)
    out.paste(body, (0, TOP_H))
    draw = ImageDraw.Draw(out)
    draw.rectangle((0, 0, total_w, TOP_H), fill=BAR)
    draw.rectangle((0, BODY_H + TOP_H, total_w, BODY_H + TOP_H + BOT_H), fill=BAR)
    draw.line([(0, TOP_H), (total_w, TOP_H)], fill=(51, 65, 85), width=2)
    draw.line([(0, BODY_H + TOP_H), (total_w, BODY_H + TOP_H)], fill=(51, 65, 85), width=2)

    draw.text((18, 14), "RobotEscapeRoom", font=FONT_TITLE, fill=TEXT)
    draw.text((300, 18), "2D topo + camera + furnished sim · puzzle replan each turn", font=FONT_LEGEND, fill=MUTED)
    _round_rect(draw, (total_w - 108, 12, total_w - 18, 42), 14, (6, 78, 59), (45, 212, 191), 1)
    draw.text((total_w - 63, 18), "live", font=FONT_BADGE, fill=(167, 243, 208), anchor="ma")

    turn = meta.get("turn", 0)
    draw.text((18, BODY_H + TOP_H + 10), f"Turn {turn}", font=FONT_STATUS, fill=AMBER)
    draw.text((110, BODY_H + TOP_H + 10), meta.get("caption", ""), font=FONT_STATUS, fill=TEXT)
    if meta.get("detail"):
        draw.text((18, BODY_H + TOP_H + 36), meta["detail"], font=FONT_LEGEND, fill=MUTED)

    lx = total_w - 620
    _legend_chip(draw, lx, 14, CYAN, "cyan = traveled")
    _legend_chip(draw, lx + 158, 14, PINK, "pink = planned")
    _legend_chip(draw, lx + 316, 14, RED, "red = locked")
    return out


def main() -> None:
    frames_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/erframes")
    frames_dir.mkdir(parents=True, exist_ok=True)
    graph = load_graph(GRAPH_PATH)
    timeline = json.loads(TIMELINE_PATH.read_text(encoding="utf-8"))["frames"]
    if not timeline:
        raise SystemExit("timeline is empty")

    for idx, meta in enumerate(timeline):
        render_frame(graph, meta).save(frames_dir / f"f{idx:03d}.png")

    print(f"rendered {len(timeline)} deterministic frames -> {frames_dir}")


if __name__ == "__main__":
    main()
