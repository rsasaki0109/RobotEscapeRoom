"""Render a TPS-style semantic topological navigation hero GIF.

Produces ``docs/images/18_semantic_tps_navigation.gif``. The animation
shows a third-person robot view with semantic labels, a highlighted
topological route, and the actual planned path on ``multi_floor_office``.

Run from the repository root:

    python examples/build_semantic_tps_gif.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

GRAPH_PATH = HERE / "multi_floor_office.yaml"
OUT_PATH = ROOT / "docs" / "images" / "18_semantic_tps_navigation.gif"

BASE_W, BASE_H = 720, 405
SCALE = 2
W, H = BASE_W * SCALE, BASE_H * SCALE
FRAME_COUNT = 72
FRAME_MS = 70
LOOP = 0

BG_TOP = (28, 38, 50)
BG_BOTTOM = (218, 225, 222)
FLOOR = (154, 166, 164)
FLOOR_DARK = (103, 117, 120)
WALL_LEFT = (72, 88, 106)
WALL_RIGHT = (84, 98, 111)
ROUTE = (239, 68, 68)
ROUTE_2 = (14, 165, 233)
SEMANTIC = (245, 158, 11)
GRAPH = (57, 183, 176)
TEXT = (241, 245, 249)
MUTED = (148, 163, 184)
PANEL = (10, 18, 28, 208)

LANES = {
    "entrance": 0.0,
    "corridor_1f": 0.0,
    "elevator_1f": -0.58,
    "elevator_2f": -0.58,
    "elevator_3f": -0.58,
    "corridor_3f": 0.0,
    "exec_office_3f": 0.58,
}


def _s(value: float) -> int:
    return int(round(value * SCALE))


def _box(xy: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    return tuple(_s(v) for v in xy)


def _pt(x: float, y: float) -> tuple[int, int]:
    return _s(x), _s(y)


def _poly(points: list[tuple[float, float]]) -> list[tuple[int, int]]:
    return [_pt(x, y) for x, y in points]


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]
    for name in names:
        path = Path(name)
        if path.exists():
            return ImageFont.truetype(str(path), _s(size))
    return ImageFont.load_default()


FONT_XS = _font(8)
FONT_SM = _font(10)
FONT = _font(12)
FONT_BOLD = _font(12, bold=True)
FONT_TITLE = _font(18, bold=True)
FONT_MONO = _font(10)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _ease(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)


def _blend(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(round(_lerp(x, y, t))) for x, y in zip(a, b, strict=False))


def _round_rect(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float, float, float],
    radius: float,
    fill,
    outline=None,
    width: int = 1,
) -> None:
    draw.rounded_rectangle(_box(xy), radius=_s(radius), fill=fill, outline=outline, width=_s(width))


def _text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    value: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont = FONT,
    fill=TEXT,
    anchor: str | None = None,
) -> None:
    draw.text(_pt(*xy), value, font=font, fill=fill, anchor=anchor)


def _label(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    value: str,
    *,
    fill=(15, 23, 42, 230),
    outline=(255, 255, 255, 42),
    accent=SEMANTIC,
) -> None:
    x, y = xy
    bbox = draw.textbbox(_pt(x, y), value, font=FONT_SM)
    w = (bbox[2] - bbox[0]) / SCALE + 18
    h = (bbox[3] - bbox[1]) / SCALE + 11
    _round_rect(draw, (x - w / 2, y - h / 2, x + w / 2, y + h / 2), 6, fill, outline)
    draw.ellipse(_box((x - w / 2 + 7, y - 3, x - w / 2 + 13, y + 3)), fill=accent)
    _text(draw, (x - w / 2 + 18, y - 6), value, FONT_SM, TEXT)


def _gradient() -> Image.Image:
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / max(1, H - 1)
        draw.line([(0, y), (W, y)], fill=_blend(BG_TOP, BG_BOTTOM, t))
    return img.convert("RGBA")


def _world_point(lane: float, depth: float) -> tuple[float, float]:
    vp_x, vp_y = BASE_W / 2, 126
    near_y = 355
    width = _lerp(220, 25, depth)
    x = vp_x + lane * width
    y = _lerp(near_y, vp_y + 26, depth)
    return x, y


def _draw_glow_disc(
    layer: Image.Image,
    center: tuple[float, float],
    radius: float,
    color: tuple[int, int, int],
    *,
    text: str | None = None,
    active: bool = False,
) -> None:
    draw = ImageDraw.Draw(layer)
    x, y = center
    for i, alpha in enumerate([42, 52, 64]):
        r = radius + (3 - i) * 5
        draw.ellipse(_box((x - r, y - r, x + r, y + r)), fill=(*color, alpha))
    draw.ellipse(
        _box((x - radius, y - radius, x + radius, y + radius)),
        fill=(*color, 230 if active else 190),
        outline=(255, 255, 255, 190),
        width=_s(1.5),
    )
    draw.ellipse(
        _box((x - radius * 0.32, y - radius * 0.32, x + radius * 0.32, y + radius * 0.32)),
        fill=(255, 255, 255, 235),
    )
    if text:
        _label(draw, (x, y - radius - 15), text, accent=color)


def _draw_corridor(draw: ImageDraw.ImageDraw, floor_label: str, phase: float) -> None:
    # Floor and walls.
    draw.polygon(_poly([(72, 405), (292, 132), (428, 132), (648, 405)]), fill=FLOOR)
    draw.polygon(_poly([(0, 405), (0, 85), (292, 132), (72, 405)]), fill=WALL_LEFT)
    draw.polygon(_poly([(720, 405), (720, 85), (428, 132), (648, 405)]), fill=WALL_RIGHT)
    draw.polygon(_poly([(292, 132), (428, 132), (392, 100), (327, 100)]), fill=(41, 52, 65))

    # Perspective grid on the floor.
    for i in range(8):
        t = (i + phase) % 8 / 8
        y = _lerp(356, 146, t)
        x1 = _lerp(75, 295, t)
        x2 = _lerp(645, 425, t)
        draw.line([_pt(x1, y), _pt(x2, y)], fill=(207, 216, 214, 92), width=_s(1))
    for lane in [-0.8, -0.4, 0.0, 0.4, 0.8]:
        x_near, y_near = _world_point(lane, 0.0)
        x_far, y_far = _world_point(lane, 0.95)
        draw.line([_pt(x_near, y_near), _pt(x_far, y_far)], fill=(93, 109, 114, 96), width=_s(1))

    # Doors and semantic wall signs.
    left_name = "Robotics Lab" if floor_label == "1F" else "Balcony"
    right_name = "Kitchen" if floor_label == "1F" else "Executive Office"
    draw.polygon(_poly([(88, 250), (154, 218), (154, 330), (88, 384)]), fill=(46, 64, 83))
    draw.polygon(_poly([(566, 218), (632, 250), (632, 384), (566, 330)]), fill=(50, 68, 80))
    _label(draw, (130, 216), left_name, accent=GRAPH)
    _label(draw, (590, 216), right_name, accent=SEMANTIC if right_name == "Executive Office" else GRAPH)

    # Floor badge.
    _round_rect(draw, (311, 94, 409, 121), 8, (15, 23, 42, 210), (255, 255, 255, 45))
    _text(draw, (360, 100), f"semantic floor: {floor_label}", FONT_SM, TEXT, "ma")


def _draw_elevator(draw: ImageDraw.ImageDraw, local: float) -> None:
    draw.rectangle(_box((0, 0, 720, 405)), fill=(34, 44, 56))
    for x in [110, 190, 530, 610]:
        draw.rectangle(_box((x, 0, x + 2, 405)), fill=(75, 90, 102))
    draw.polygon(_poly([(188, 405), (266, 120), (454, 120), (532, 405)]), fill=(116, 126, 126))
    draw.rectangle(_box((275, 94, 445, 326)), fill=(52, 65, 77), outline=(181, 193, 200), width=_s(2))
    draw.rectangle(_box((279, 98, 359, 322)), fill=(65, 77, 89))
    draw.rectangle(_box((361, 98, 441, 322)), fill=(59, 71, 84))
    draw.line([_pt(360, 99), _pt(360, 322)], fill=(203, 213, 225), width=_s(1))
    draw.polygon(_poly([(329, 80), (360, 49), (391, 80)]), fill=SEMANTIC)

    floor_float = _lerp(1.0, 3.0, local)
    active_floor = 1 if floor_float < 1.67 else 2 if floor_float < 2.34 else 3
    _round_rect(draw, (488, 105, 598, 264), 10, (12, 20, 33, 214), (255, 255, 255, 40))
    _text(draw, (543, 119), "elevator route", FONT_BOLD, TEXT, "ma")
    for i, floor in enumerate([3, 2, 1]):
        y = 154 + i * 36
        color = SEMANTIC if floor == active_floor else MUTED
        draw.ellipse(_box((514, y - 10, 534, y + 10)), fill=color)
        _text(draw, (546, y - 8), f"{floor}F", FONT_BOLD, TEXT if floor == active_floor else MUTED)
    draw.line([_pt(524, 226), _pt(524, 154)], fill=SEMANTIC, width=_s(3))
    _label(draw, (360, 356), "vertical topological edge", accent=SEMANTIC)


def _draw_robot(draw: ImageDraw.ImageDraw) -> None:
    cx, base = 360, 356
    draw.ellipse(_box((cx - 66, base - 12, cx + 66, base + 12)), fill=(4, 8, 14, 72))
    draw.rounded_rectangle(_box((cx - 36, base - 82, cx + 36, base - 12)), radius=_s(18), fill=(22, 31, 44), outline=(215, 226, 236), width=_s(2))
    draw.rounded_rectangle(_box((cx - 25, base - 71, cx + 25, base - 35)), radius=_s(9), fill=(42, 57, 72))
    draw.ellipse(_box((cx - 16, base - 103, cx + 16, base - 71)), fill=(9, 17, 29), outline=(215, 226, 236), width=_s(2))
    draw.arc(_box((cx - 29, base - 116, cx + 29, base - 58)), 205, 335, fill=ROUTE_2, width=_s(3))
    draw.rectangle(_box((cx - 50, base - 61, cx - 38, base - 22)), fill=(10, 18, 28))
    draw.rectangle(_box((cx + 38, base - 61, cx + 50, base - 22)), fill=(10, 18, 28))
    draw.ellipse(_box((cx - 7, base - 92, cx + 7, base - 78)), fill=SEMANTIC)


def _draw_topology_panel(
    draw: ImageDraw.ImageDraw,
    route: list[str],
    progress: float,
    labels: dict[str, str],
) -> None:
    _round_rect(draw, (465, 22, 700, 178), 12, PANEL, (255, 255, 255, 40))
    _text(draw, (482, 36), "semantic topology", FONT_BOLD, TEXT)
    positions = {
        "entrance": (492, 141),
        "corridor_1f": (548, 141),
        "elevator_1f": (606, 141),
        "elevator_2f": (606, 101),
        "elevator_3f": (606, 61),
        "corridor_3f": (548, 61),
        "exec_office_3f": (492, 61),
    }
    edges = list(zip(route[:-1], route[1:], strict=False))
    for idx, (a, b) in enumerate(edges):
        active = idx <= progress
        color = ROUTE if active else (79, 94, 112)
        width = 4 if active else 2
        draw.line([_pt(*positions[a]), _pt(*positions[b])], fill=color, width=_s(width))
    for idx, node_id in enumerate(route):
        x, y = positions[node_id]
        active = abs(progress - idx) < 0.65 or idx < progress
        color = SEMANTIC if node_id == "exec_office_3f" else GRAPH
        fill = color if active else (30, 41, 59)
        draw.ellipse(_box((x - 9, y - 9, x + 9, y + 9)), fill=fill, outline=(226, 232, 240), width=_s(1))
        if node_id in {"entrance", "elevator_1f", "elevator_3f", "exec_office_3f"}:
            short = {
                "entrance": "start",
                "elevator_1f": "elevator",
                "elevator_3f": "3F",
                "exec_office_3f": "goal",
            }[node_id]
            _text(draw, (x, y + 14), short, FONT_XS, TEXT if active else MUTED, "ma")
    current_idx = min(int(progress), len(route) - 1)
    current = labels[route[current_idx]]
    _text(draw, (482, 160), f"next: {current}", FONT_XS, MUTED)


def _draw_decision_panel(
    draw: ImageDraw.ImageDraw,
    route: list[str],
    progress: float,
    labels: dict[str, str],
) -> None:
    _round_rect(draw, (20, 22, 301, 146), 12, PANEL, (255, 255, 255, 42))
    _text(draw, (36, 37), "goal text", FONT_XS, MUTED)
    _text(draw, (36, 53), "\"executive office on 3F\"", FONT_BOLD, TEXT)
    _text(draw, (36, 79), "resolve_goal -> exec_office_3f", FONT_MONO, (226, 232, 240))
    _text(draw, (36, 99), "A*: prefer_elevator + topology costs", FONT_MONO, (226, 232, 240))
    _text(draw, (36, 119), "waypoints: semantic labels + floor ids", FONT_MONO, (226, 232, 240))

    current_idx = min(int(round(progress)), len(route) - 1)
    node_id = route[current_idx]
    _round_rect(draw, (20, 156, 301, 195), 12, (15, 23, 42, 215), (255, 255, 255, 38))
    draw.ellipse(_box((36, 170, 48, 182)), fill=SEMANTIC)
    _text(draw, (58, 168), f"current semantic node: {labels[node_id]}", FONT_SM, TEXT)


def _draw_waypoints(
    layer: Image.Image,
    route: list[str],
    progress: float,
    labels: dict[str, str],
) -> None:
    draw = ImageDraw.Draw(layer)
    visible: list[tuple[float, str, tuple[float, float]]] = []
    for idx, node_id in enumerate(route):
        rel = idx - progress
        if -0.25 <= rel <= 3.2:
            depth = max(0.08, min(0.90, 0.18 + rel * 0.22))
            visible.append((depth, node_id, _world_point(LANES.get(node_id, 0.0), depth)))
    visible.sort(reverse=True)

    centers = {node_id: center for _, node_id, center in visible}
    for a, b in zip(route[:-1], route[1:], strict=False):
        if a in centers and b in centers:
            draw.line([_pt(*centers[a]), _pt(*centers[b])], fill=(*ROUTE, 170), width=_s(5))

    for depth, node_id, (x, y) in visible:
        radius = _lerp(17, 8, depth)
        color = SEMANTIC if node_id == "exec_office_3f" else GRAPH
        active = abs(route.index(node_id) - progress) < 0.55
        text = labels[node_id] if node_id in {"elevator_1f", "elevator_3f", "exec_office_3f"} else None
        _draw_glow_disc(layer, (x, y), radius, color, text=text, active=active)


def _render_frame(graph, route: list[str], frame_idx: int) -> Image.Image:
    labels = {node.id: node.label for node in graph.nodes()}
    raw_t = frame_idx / (FRAME_COUNT - 1)
    progress = _ease(raw_t) * (len(route) - 1)
    seg = min(int(progress), len(route) - 2)
    local = progress - seg
    current = route[seg]
    nxt = route[seg + 1]
    vertical = current.startswith("elevator_") and nxt.startswith("elevator_")

    img = _gradient()
    draw = ImageDraw.Draw(img, "RGBA")

    if vertical:
        _draw_elevator(draw, local)
    else:
        floor = graph.get_node(current).properties.get("floor", 1)
        if current == "elevator_3f" or nxt in {"corridor_3f", "exec_office_3f"}:
            floor = 3
        _draw_corridor(draw, f"{floor}F", (raw_t * 4.0) % 1.0)
        waypoint_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        _draw_waypoints(waypoint_layer, route, progress, labels)
        img = Image.alpha_composite(img, waypoint_layer)
        draw = ImageDraw.Draw(img, "RGBA")

    _draw_robot(draw)
    _draw_decision_panel(draw, route, progress, labels)
    _draw_topology_panel(draw, route, progress, labels)

    if frame_idx > FRAME_COUNT - 12:
        alpha = int(255 * ((frame_idx - (FRAME_COUNT - 12)) / 11))
        _round_rect(draw, (248, 210, 472, 257), 14, (9, 17, 29, min(225, alpha)), (245, 158, 11, min(220, alpha)))
        _text(draw, (360, 223), "goal reached", FONT_TITLE, (255, 255, 255, alpha), "ma")
        _text(draw, (360, 246), "exec_office_3f admitted route", FONT_SM, (226, 232, 240, alpha), "ma")

    img = img.resize((BASE_W, BASE_H), Image.Resampling.LANCZOS)
    return img.convert("P", palette=Image.ADAPTIVE, colors=128)


def main() -> None:
    from semantic_toponav.graph.serialization import load_graph
    from semantic_toponav.planner import compose_costs, plan_astar, prefer_elevator

    graph = load_graph(GRAPH_PATH)
    route = plan_astar(
        graph,
        "entrance",
        "exec_office_3f",
        cost_fn=compose_costs(prefer_elevator),
    )
    frames = [_render_frame(graph, route, idx) for idx in range(FRAME_COUNT)]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        OUT_PATH,
        save_all=True,
        append_images=frames[1:],
        duration=FRAME_MS,
        loop=LOOP,
        optimize=True,
        disposal=2,
    )
    size_kb = OUT_PATH.stat().st_size / 1024
    print(f"route: {' -> '.join(route)}")
    print(f"wrote {OUT_PATH.relative_to(ROOT)} ({size_kb:.0f} KB, {len(frames)} frames)")


if __name__ == "__main__":
    main()
