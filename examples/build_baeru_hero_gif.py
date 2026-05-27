"""Build a polished README hero GIF from real semantic-toponav APIs.

This is the more visual counterpart to ``record_semantic_navigation_demo.py``.
It still loads the shipped graph, resolves the natural-language goal, plans
with A* + ``prefer_elevator``, and renders the generated semantic waypoints.

Run from the repository root:

    python examples/build_baeru_hero_gif.py
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

GRAPH_PATH = HERE / "multi_floor_office.yaml"
OUT_PATH = ROOT / "docs" / "images" / "19_semantic_toponav_showcase.gif"
QUERY = "executive office on 3F"
START_NODE = "entrance"

BASE_W, BASE_H = 960, 540
SCALE = 2
W, H = BASE_W * SCALE, BASE_H * SCALE
FRAME_COUNT = 96
FRAME_MS = 58
LOOP = 0

BG0 = (4, 10, 24)
BG1 = (10, 20, 44)
CARD = (11, 23, 46, 214)
CARD2 = (15, 31, 60, 232)
LINE = (67, 87, 120)
TEXT = (241, 245, 249)
MUTED = (148, 163, 184)
CYAN = (34, 211, 238)
PINK = (244, 63, 94)
AMBER = (245, 158, 11)
GREEN = (34, 197, 94)
BLUE = (96, 165, 250)
PURPLE = (168, 85, 247)

NODE_COLORS = {
    "entrance": GREEN,
    "room": BLUE,
    "corridor": MUTED,
    "intersection": PURPLE,
    "elevator": AMBER,
    "stairs": (239, 68, 68),
}

FLOOR_OFFSET = 9.0
X_MIN = -0.8
X_MAX = 12.9
Y_MIN = -5.4
Y_MAX = 22.8
GRAPH_BOX = (336.0, 82.0, 914.0, 386.0)


def _s(value: float) -> int:
    return int(round(value * SCALE))


def _pt(x: float, y: float) -> tuple[int, int]:
    return _s(x), _s(y)


def _box(xy: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    return tuple(_s(v) for v in xy)


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]
    for raw in paths:
        path = Path(raw)
        if path.exists():
            return ImageFont.truetype(str(path), _s(size))
    return ImageFont.load_default()


FONT_XS = _font(9)
FONT_SM = _font(11)
FONT = _font(13)
FONT_BOLD = _font(13, bold=True)
FONT_H2 = _font(17, bold=True)
FONT_TITLE = _font(30, bold=True)
FONT_BIG = _font(28, bold=True)
FONT_MONO = _font(11)


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _blend(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b, strict=False))


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


def _line(
    draw: ImageDraw.ImageDraw,
    a: tuple[float, float],
    b: tuple[float, float],
    *,
    fill,
    width: float = 2.0,
    dash: float | None = None,
) -> None:
    if dash is None:
        draw.line([_pt(*a), _pt(*b)], fill=fill, width=_s(width))
        return

    ax, ay = a
    bx, by = b
    length = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
    if length <= 0:
        return
    t = 0.0
    while t < length:
        t2 = min(length, t + dash)
        p0 = (ax + (bx - ax) * t / length, ay + (by - ay) * t / length)
        p1 = (ax + (bx - ax) * t2 / length, ay + (by - ay) * t2 / length)
        draw.line([_pt(*p0), _pt(*p1)], fill=fill, width=_s(width))
        t += dash * 2


def _wrap(text: str, limit: int) -> list[str]:
    words = text.split()
    out: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                out.append(current)
            current = word
    if current:
        out.append(current)
    return out


def _floor_of(node: Any) -> int:
    return int(node.properties.get("floor", 1))


def _world_xy(node: Any) -> tuple[float, float]:
    if node.pose is None:
        raise ValueError(f"node {node.id!r} has no pose")
    return node.pose.x, node.pose.y + (_floor_of(node) - 1) * FLOOR_OFFSET


def _map_world_xy(x: float, y: float) -> tuple[float, float]:
    x0, y0, x1, y1 = GRAPH_BOX
    px = x0 + (x - X_MIN) / (X_MAX - X_MIN) * (x1 - x0)
    py = y1 - (y - Y_MIN) / (Y_MAX - Y_MIN) * (y1 - y0)
    return px, py


def _map_xy(node: Any) -> tuple[float, float]:
    return _map_world_xy(*_world_xy(node))


def _partial(a: tuple[float, float], b: tuple[float, float], t: float) -> tuple[float, float]:
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t


def _background(frame_idx: int) -> Image.Image:
    img = Image.new("RGB", (W, H), BG0)
    draw = ImageDraw.Draw(img, "RGBA")
    for y in range(H):
        t = y / max(1, H - 1)
        draw.line([(0, y), (W, y)], fill=_blend(BG0, BG1, t))

    phase = frame_idx * 6
    grid = (65, 91, 132, 52)
    for x in range(-80 * SCALE + phase % (80 * SCALE), W + 80 * SCALE, 80 * SCALE):
        draw.line([(x, 0), (x - 230 * SCALE, H)], fill=grid, width=1)
    for y in range(-64 * SCALE + phase % (64 * SCALE), H + 64 * SCALE, 64 * SCALE):
        draw.line([(0, y), (W, y)], fill=grid, width=1)

    # Soft glow around the graph area.
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow, "RGBA")
    gd.ellipse(_box((280, 62, 900, 420)), fill=(34, 211, 238, 40))
    gd.ellipse(_box((530, 105, 1000, 470)), fill=(244, 63, 94, 36))
    glow = glow.filter(ImageFilter.GaussianBlur(_s(42)))
    return Image.alpha_composite(img.convert("RGBA"), glow)


def _draw_header(draw: ImageDraw.ImageDraw, stage: str) -> None:
    _text(draw, (34, 28), "semantic-toponav", FONT_BIG, TEXT)
    _text(draw, (39, 78), "language goal -> topology route", FONT, MUTED)

    stages = ["resolve", "plan", "waypoints", "arrive"]
    x = 34.0
    for name in stages:
        active = name == stage
        color = CYAN if name == "resolve" else PINK if name == "plan" else AMBER if name == "waypoints" else GREEN
        fill = (*color, 46) if active else (15, 31, 60, 170)
        outline = (*color, 230) if active else (71, 85, 105, 160)
        w = {"resolve": 67, "plan": 54, "waypoints": 92, "arrive": 62}[name]
        _round_rect(draw, (x, 112, x + w, 143), 15, fill, outline, 1)
        draw.ellipse(_box((x + 12, 123, x + 21, 132)), fill=(*color, 255))
        _text(draw, (x + 29, 120), name, FONT_SM, TEXT if active else MUTED)
        x += w + 6


def _draw_terminal(draw: ImageDraw.ImageDraw, candidates: list[Any], route: list[str], typed_query: str) -> None:
    _round_rect(draw, (34, 164, 300, 382), 14, CARD, (71, 85, 105, 130), 1)
    _text(draw, (52, 183), "live planner trace", FONT_H2, TEXT)
    _text(draw, (52, 216), "$ resolve_goal", FONT_MONO, CYAN)
    _text(draw, (52, 235), f'"{typed_query}"', FONT_MONO, TEXT)
    if typed_query == QUERY:
        candidate = candidates[0]
        _text(draw, (52, 266), f"-> {candidate.node_id}", FONT_MONO, GREEN)
        _text(draw, (52, 285), f"score={candidate.score:.1f}", FONT_MONO, MUTED)
        _text(draw, (52, 316), "$ plan_astar", FONT_MONO, PINK)
        for row, line in enumerate(_wrap(" -> ".join(route), 25)[:3]):
            _text(draw, (52, 335 + row * 16), line, FONT_XS, MUTED)


def _draw_floor_stack(draw: ImageDraw.ImageDraw) -> None:
    x0, _, x1, _ = GRAPH_BOX
    for floor in (1, 2, 3):
        y_low = (floor - 1) * FLOOR_OFFSET - 4.9
        y_high = (floor - 1) * FLOOR_OFFSET + 4.9
        _, top = _map_world_xy(0, y_high)
        _, bottom = _map_world_xy(0, y_low)
        fill = (15, 31, 60, 140) if floor % 2 else (18, 36, 70, 135)
        outline = (96, 165, 250, 90)
        _round_rect(draw, (x0, top, x1, bottom), 12, fill, outline, 1)
        _text(draw, (x0 + 18, top + 10), f"floor {floor}", FONT_BOLD, (203, 213, 225))


def _draw_graph(draw: ImageDraw.ImageDraw, graph: Any) -> None:
    _round_rect(draw, (316, 48, 936, 410), 20, (7, 15, 32, 160), (96, 165, 250, 80), 1)
    _draw_floor_stack(draw)

    for edge in graph.edges():
        a = _map_xy(graph.get_node(edge.source))
        b = _map_xy(graph.get_node(edge.target))
        if edge.type == "elevator_connection":
            _line(draw, a, b, fill=(245, 158, 11, 132), width=2.8, dash=7)
        elif edge.type.startswith("stairs"):
            _line(draw, a, b, fill=(239, 68, 68, 110), width=2.0, dash=6)
        else:
            _line(draw, a, b, fill=(148, 163, 184, 115), width=1.8)

    for node in graph.nodes():
        x, y = _map_xy(node)
        color = NODE_COLORS.get(node.type, BLUE)
        draw.ellipse(_box((x - 5, y - 5, x + 5, y + 5)), fill=(*color, 230))


def _draw_route(
    base: Image.Image,
    graph: Any,
    route: list[str],
    progress: float,
) -> tuple[float, float, int]:
    segment = min(int(progress), len(route) - 2)
    local = progress - segment

    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow, "RGBA")
    line = ImageDraw.Draw(base, "RGBA")

    for idx, (a_id, b_id) in enumerate(zip(route[:-1], route[1:], strict=False)):
        a = _map_xy(graph.get_node(a_id))
        b = _map_xy(graph.get_node(b_id))
        if idx < segment:
            gd.line([_pt(*a), _pt(*b)], fill=(*PINK, 155), width=_s(12))
            line.line([_pt(*a), _pt(*b)], fill=(*PINK, 245), width=_s(4))
        elif idx == segment:
            mid = _partial(a, b, local)
            gd.line([_pt(*a), _pt(*mid)], fill=(*PINK, 170), width=_s(14))
            line.line([_pt(*a), _pt(*mid)], fill=(*PINK, 255), width=_s(5))
            line.line([_pt(*mid), _pt(*b)], fill=(244, 63, 94, 95), width=_s(2))
        else:
            line.line([_pt(*a), _pt(*b)], fill=(244, 63, 94, 70), width=_s(2))

    glow = glow.filter(ImageFilter.GaussianBlur(_s(8)))
    base.alpha_composite(glow)

    a = _map_xy(graph.get_node(route[segment]))
    b = _map_xy(graph.get_node(route[segment + 1]))
    robot_xy = _partial(a, b, local)
    return robot_xy[0], robot_xy[1], segment


def _draw_robot(draw: ImageDraw.ImageDraw, xy: tuple[float, float], frame_idx: int) -> None:
    x, y = xy
    pulse = 1.0 + 0.18 * math.sin(frame_idx * 0.35)
    r = 16 * pulse
    draw.ellipse(_box((x - r * 1.9, y - r * 1.9, x + r * 1.9, y + r * 1.9)), fill=(*CYAN, 34))
    draw.ellipse(_box((x - r, y - r, x + r, y + r)), fill=(8, 47, 73, 255), outline=(*CYAN, 255), width=_s(3))
    draw.ellipse(_box((x - 5, y - 5, x + 5, y + 5)), fill=(255, 255, 255, 255))
    draw.polygon([_pt(x, y - 25), _pt(x - 8, y - 9), _pt(x + 8, y - 9)], fill=(*CYAN, 255))


def _draw_node_labels(draw: ImageDraw.ImageDraw, graph: Any, route: list[str], segment: int) -> None:
    for idx, node_id in enumerate(route):
        node = graph.get_node(node_id)
        x, y = _map_xy(node)
        active = idx <= segment + 1
        color = AMBER if node.type == "elevator" else GREEN if idx == len(route) - 1 else CYAN
        draw.ellipse(_box((x - 8, y - 8, x + 8, y + 8)), outline=(*color, 235), width=_s(2))
        if active and node_id in {"entrance", "elevator_1f", "elevator_3f", "exec_office_3f"}:
            text = node.label.replace("Elevator A ", "Elevator ")
            w = max(76, int(draw.textlength(text, font=FONT_XS) / SCALE) + 18)
            _round_rect(draw, (x - w / 2, y - 34, x + w / 2, y - 14), 8, (2, 6, 23, 210), (*color, 160))
            _text(draw, (x, y - 30), text, FONT_XS, TEXT, "ma")


def _draw_waypoint_strip(draw: ImageDraw.ImageDraw, waypoints: list[Any], current_idx: int) -> None:
    _round_rect(draw, (34, 424, 926, 512), 18, CARD, (96, 165, 250, 80), 1)
    _text(draw, (55, 443), "semantic waypoint stream", FONT_H2, TEXT)
    usable_w = 842
    col_w = usable_w / len(waypoints)
    left0 = 55
    top = 470
    for idx, wp in enumerate(waypoints):
        left = left0 + idx * col_w
        active = idx == current_idx
        visited = idx < current_idx
        color = AMBER if active else GREEN if visited else (71, 85, 105)
        fill = (*color, 52) if active else (15, 31, 60, 190)
        _round_rect(draw, (left, top, left + col_w - 8, top + 28), 10, fill, (*color, 190), 1)
        draw.ellipse(_box((left + 9, top + 10, left + 16, top + 17)), fill=(*color, 255))
        label = wp.action.replace("_", " ")
        _text(draw, (left + 23, top + 7), label[:13], FONT_XS, TEXT if active or visited else MUTED)


def _draw_right_card(draw: ImageDraw.ImageDraw, candidates: list[Any], route: list[str], current_node: str) -> None:
    _round_rect(draw, (688, 48, 928, 168), 18, CARD2, (34, 211, 238, 120), 1)
    _text(draw, (708, 68), "grounded decision", FONT_H2, TEXT)
    _text(draw, (708, 99), f"goal: {candidates[0].node_id}", FONT_MONO, GREEN)
    _text(draw, (708, 119), f"current: {current_node}", FONT_MONO, CYAN)
    _text(draw, (708, 139), f"hops: {len(route) - 1}  policy: prefer_elevator", FONT_MONO, MUTED)


def _stage_for(t: float, progress: float, max_progress: float) -> str:
    if t < 0.23:
        return "resolve"
    if progress < max_progress * 0.36:
        return "plan"
    if progress < max_progress:
        return "waypoints"
    return "arrive"


def _render_frame(
    graph: Any,
    candidates: list[Any],
    route: list[str],
    waypoints: list[Any],
    frame_idx: int,
) -> Image.Image:
    raw = frame_idx / (FRAME_COUNT - 1)
    query_chars = int(len(QUERY) * min(1.0, raw / 0.22))
    typed_query = QUERY[:query_chars]
    progress_t = _ease(max(0.0, (raw - 0.18) / 0.74))
    max_progress = len(route) - 1
    progress = progress_t * max_progress
    stage = _stage_for(raw, progress, max_progress)

    img = _background(frame_idx)
    draw = ImageDraw.Draw(img, "RGBA")
    _draw_header(draw, stage)
    _draw_terminal(draw, candidates, route, typed_query)
    _draw_graph(draw, graph)
    robot_x, robot_y, segment = _draw_route(img, graph, route, progress)
    draw = ImageDraw.Draw(img, "RGBA")
    _draw_node_labels(draw, graph, route, segment)
    _draw_robot(draw, (robot_x, robot_y), frame_idx)
    current_idx = min(round(progress), len(waypoints) - 1)
    _draw_waypoint_strip(draw, waypoints, current_idx)
    _draw_right_card(draw, candidates, route, route[min(segment, len(route) - 1)])

    if stage == "arrive":
        alpha = int(220 * min(1.0, (raw - 0.92) / 0.08))
        _round_rect(draw, (365, 190, 656, 254), 18, (2, 6, 23, alpha), (245, 158, 11, alpha), 2)
        _text(draw, (510, 205), "goal reached", FONT_TITLE, (255, 255, 255, alpha), "ma")
        _text(draw, (510, 239), "exec_office_3f", FONT_BOLD, (253, 230, 138, alpha), "ma")

    img = img.resize((BASE_W, BASE_H), Image.Resampling.LANCZOS)
    return img.convert("P", palette=Image.ADAPTIVE, colors=128)


def _load_demo() -> tuple[Any, list[Any], list[str], list[Any]]:
    from semantic_toponav.graph.serialization import load_graph
    from semantic_toponav.planner import compose_costs, plan_astar, prefer_elevator
    from semantic_toponav.query.resolve import resolve_goal
    from semantic_toponav.waypoint import path_to_semantic_waypoints

    graph = load_graph(GRAPH_PATH)
    candidates = resolve_goal(graph, QUERY)
    if not candidates:
        raise RuntimeError(f"query did not resolve: {QUERY!r}")
    route = plan_astar(
        graph,
        START_NODE,
        candidates[0].node_id,
        cost_fn=compose_costs(prefer_elevator),
    )
    waypoints = path_to_semantic_waypoints(graph, route)
    return graph, candidates, route, waypoints


def main() -> None:
    graph, candidates, route, waypoints = _load_demo()
    frames = [
        _render_frame(graph, candidates, route, waypoints, idx)
        for idx in range(FRAME_COUNT)
    ]
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
    print(f"query: {QUERY!r} -> {candidates[0].node_id}")
    print(f"route: {' -> '.join(route)}")
    print(f"wrote {OUT_PATH.relative_to(ROOT)} ({size_kb:.0f} KB, {len(frames)} frames)")


if __name__ == "__main__":
    main()
