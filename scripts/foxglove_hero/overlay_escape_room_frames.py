"""Compose README hero frames: 2D topology map + enhanced 3D capture + captions.

    python scripts/foxglove_hero/overlay_escape_room_frames.py /tmp/erframes
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "examples"))

from robot_escape_room import POWER_ITEM, UNPOWERED_TYPES  # noqa: E402
from semantic_toponav.graph.serialization import load_graph  # noqa: E402

GRAPH_PATH = ROOT / "examples/robot_escape_room.yaml"
TIMELINE_PATH = ROOT / "docs/foxglove/robot_escape_room_timeline.json"

MAP_W = 400
TOP_H, BOT_H = 56, 64
FLOOR_DY = 9.0
FLOOR_BAND = {-1: 0, 1: 1, 2: 2, 3: 3}
FLOOR_LABEL = {-1: "B1", 1: "1F", 2: "2F", 3: "3F"}
X_MIN, X_MAX = -2.0, 30.0
Y_MIN, Y_MAX = -10.0, 38.0

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

NODE_COLORS = {
    "room": BLUE,
    "corridor": MUTED,
    "intersection": PURPLE,
    "stairs": ORANGE,
    "exit": (34, 197, 94),
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
FONT_MAP_TITLE = _font(15, bold=True)
FONT_MAP = _font(11)
FONT_MAP_SM = _font(9)


def _round_rect(draw, xy, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def _load_timeline() -> list[dict]:
    return json.loads(TIMELINE_PATH.read_text(encoding="utf-8"))["frames"]


def _caption_at(frames: list[dict], idx: int, total: int) -> dict:
    if not frames or total <= 0:
        return {"turn": 0, "caption": "", "detail": "", "route": [], "progress": 0.0, "items": []}
    return frames[min(int(idx * len(frames) / total), len(frames) - 1)]


def _world_xy(node) -> tuple[float, float]:
    floor = int(node.properties.get("floor", 1))
    return node.pose.x, node.pose.y + FLOOR_BAND.get(floor, floor) * FLOOR_DY


def _map_px(x: float, y: float, box: tuple[float, float, float, float]) -> tuple[float, float]:
    x0, y0, x1, y1 = box
    px = x0 + 14 + (x - X_MIN) / (X_MAX - X_MIN) * (x1 - x0 - 28)
    py = y1 - 14 - (y - Y_MIN) / (Y_MAX - Y_MIN) * (y1 - y0 - 28)
    return px, py


def _edge_open(edge, items: set[str]) -> bool:
    lock = edge.properties.get("lock")
    if lock and lock not in items:
        return False
    if edge.type in UNPOWERED_TYPES and POWER_ITEM not in items:
        return False
    if edge.type == "restricted":
        return False
    return True


def _partial(a, b, t):
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t


def _enhance_3d(img: Image.Image) -> Image.Image:
    rgb = img.convert("RGB")
    rgb = ImageEnhance.Brightness(rgb).enhance(1.14)
    rgb = ImageEnhance.Contrast(rgb).enhance(1.18)
    rgb = ImageEnhance.Color(rgb).enhance(1.12)
    return ImageEnhance.Sharpness(rgb).enhance(1.35)


def _render_map(graph, meta: dict, height: int) -> Image.Image:
    items = set(meta.get("items", []))
    route = meta.get("route") or []
    progress = float(meta.get("progress", 0.0))
    box = (0.0, 28.0, float(MAP_W), float(height - 8))

    panel = Image.new("RGBA", (MAP_W, height), PANEL)
    draw = ImageDraw.Draw(panel, "RGBA")
    draw.rectangle((0, 0, MAP_W, 26), fill=(9, 17, 31))
    draw.text((14, 6), "topology map", font=FONT_MAP_TITLE, fill=TEXT)

    for floor, band in FLOOR_BAND.items():
        y_low = band * FLOOR_DY - 4.5
        y_high = band * FLOOR_DY + 4.5
        _, top = _map_px(0, y_high, box)
        _, bottom = _map_px(0, y_low, box)
        fill = PANEL_2 if band % 2 else PANEL_3
        _round_rect(draw, (10, top, MAP_W - 10, bottom), 8, fill, (71, 85, 105), 1)
        draw.text((18, top + 5), f"floor {FLOOR_LABEL[floor]}", font=FONT_MAP, fill=MUTED)

    segment = min(int(progress), len(route) - 2) if len(route) >= 2 else 0
    local = progress - segment if len(route) >= 2 else 0.0

    for edge in graph.edges():
        a = _map_px(*_world_xy(graph.get_node(edge.source)), box)
        b = _map_px(*_world_xy(graph.get_node(edge.target)), box)
        if not _edge_open(edge, items):
            color = (*RED, 170) if edge.properties.get("lock") else (*PINK, 150)
            draw.line([a, b], fill=color, width=2)
        elif edge.type == "elevator_connection":
            draw.line([a, b], fill=(*ORANGE, 200), width=3)
        else:
            draw.line([a, b], fill=(*MUTED, 140), width=2)

    if len(route) >= 2:
        for idx, (a_id, b_id) in enumerate(zip(route[:-1], route[1:], strict=False)):
            a = _map_px(*_world_xy(graph.get_node(a_id)), box)
            b = _map_px(*_world_xy(graph.get_node(b_id)), box)
            if idx < segment:
                draw.line([a, b], fill=(*CYAN, 255), width=5)
            elif idx == segment:
                mid = _partial(a, b, local)
                draw.line([a, mid], fill=(*CYAN, 255), width=5)
                draw.line([mid, b], fill=(*PINK, 120), width=3)
            else:
                draw.line([a, b], fill=(*PINK, 90), width=3)

    route_set = set(route)
    for node in graph.nodes():
        x, y = _map_px(*_world_xy(node), box)
        color = NODE_COLORS.get(node.type, BLUE)
        r = 7 if node.id in route_set else 5
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(*color, 240), outline=(3, 7, 18), width=1)
        if node.id in {"holding_cell", "emergency_exit", "maintenance_exit", "control_room"}:
            draw.text((x, y - 16), node.label[:11], font=FONT_MAP_SM, fill=TEXT, anchor="ma")

    if len(route) >= 2:
        robot = _partial(
            _map_px(*_world_xy(graph.get_node(route[segment])), box),
            _map_px(*_world_xy(graph.get_node(route[segment + 1])), box),
            local,
        )
    else:
        loc = meta.get("location") or (route[0] if route else "holding_cell")
        robot = _map_px(*_world_xy(graph.get_node(loc)), box)

    rx, ry = robot
    draw.ellipse((rx - 12, ry - 12, rx + 12, ry + 12), fill=(*CYAN, 60))
    draw.ellipse((rx - 8, ry - 8, rx + 8, ry + 8), fill=(8, 47, 73), outline=CYAN, width=2)
    draw.ellipse((rx - 3, ry - 3, rx + 3, ry + 3), fill=(255, 255, 255))

    return panel


def _legend_chip(draw, x, y, color, label):
    _round_rect(draw, (x, y, x + 148, y + 28), 10, (18, 30, 52), (51, 65, 85), 1)
    draw.ellipse((x + 10, y + 9, x + 22, y + 21), fill=color)
    draw.text((x + 30, y + 5), label, font=FONT_BADGE, fill=TEXT)


def annotate(path: Path, graph, meta: dict) -> None:
    sim = _enhance_3d(Image.open(path))
    sim_w, sim_h = sim.size
    body_h = sim_h
    total_w = MAP_W + sim_w

    map_panel = _render_map(graph, meta, body_h)
    body = Image.new("RGB", (total_w, body_h), BG)
    body.paste(map_panel.convert("RGB"), (0, 0))
    body.paste(sim, (MAP_W, 0))
    draw_body = ImageDraw.Draw(body)
    draw_body.line([(MAP_W, 0), (MAP_W, body_h)], fill=(51, 65, 85), width=3)

    out = Image.new("RGB", (total_w, body_h + TOP_H + BOT_H), BG)
    out.paste(body, (0, TOP_H))

    draw = ImageDraw.Draw(out)
    draw.rectangle((0, 0, total_w, TOP_H), fill=BAR)
    draw.rectangle((0, body_h + TOP_H, total_w, body_h + TOP_H + BOT_H), fill=BAR)
    draw.line([(0, TOP_H), (total_w, TOP_H)], fill=(51, 65, 85), width=2)
    draw.line([(0, body_h + TOP_H), (total_w, body_h + TOP_H)], fill=(51, 65, 85), width=2)

    draw.text((18, 14), "robot-escape-room", font=FONT_TITLE, fill=TEXT)
    draw.text((300, 18), "2D map + 3D sim · real A* replan each turn", font=FONT_LEGEND, fill=MUTED)

    _round_rect(draw, (total_w - 108, 12, total_w - 18, 42), 14, (6, 78, 59), (45, 212, 191), 1)
    draw.text((total_w - 63, 18), "live", font=FONT_BADGE, fill=(167, 243, 208), anchor="ma")

    caption = meta.get("caption", "")
    detail = meta.get("detail", "")
    turn = meta.get("turn", 0)
    draw.text((18, body_h + TOP_H + 10), f"Turn {turn}", font=FONT_STATUS, fill=AMBER)
    draw.text((110, body_h + TOP_H + 10), caption, font=FONT_STATUS, fill=TEXT)
    if detail:
        draw.text((18, body_h + TOP_H + 36), detail, font=FONT_LEGEND, fill=MUTED)

    lx = total_w - 620
    _legend_chip(draw, lx, 14, CYAN, "cyan = traveled")
    _legend_chip(draw, lx + 158, 14, PINK, "pink = planned")
    _legend_chip(draw, lx + 316, 14, RED, "red = locked")

    out.save(path)


def main() -> None:
    frames_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/erframes")
    graph = load_graph(GRAPH_PATH)
    timeline = _load_timeline()
    paths = sorted(frames_dir.glob("f*.png"))
    if not paths:
        raise SystemExit(f"no frames in {frames_dir}")

    for idx, path in enumerate(paths):
        annotate(path, graph, _caption_at(timeline, idx, len(paths)))
    print(f"annotated {len(paths)} frames with map overlay in {frames_dir}")


if __name__ == "__main__":
    main()
