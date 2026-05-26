"""Record the README semantic navigation demo GIF from real project APIs.

The generated asset is not hand-animated marketing art. It loads the
shipped ``multi_floor_office.yaml`` graph, resolves a natural-language
goal, runs A* with ``prefer_elevator``, converts the path into semantic
waypoints, and animates those actual results on the topology.

Run from the repository root:

    python examples/record_semantic_navigation_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

GRAPH_PATH = HERE / "multi_floor_office.yaml"
OUT_PATH = ROOT / "docs" / "images" / "18_semantic_navigation_demo.gif"
QUERY = "executive office on 3F"
START_NODE = "entrance"

BASE_W, BASE_H = 960, 540
SCALE = 2
W, H = BASE_W * SCALE, BASE_H * SCALE
FRAME_COUNT = 84
FRAME_MS = 65
LOOP = 0

BG = (246, 248, 251)
INK = (15, 23, 42)
MUTED = (100, 116, 139)
SUBTLE = (226, 232, 240)
PANEL = (255, 255, 255)
PANEL_DARK = (15, 23, 42)
PATH = (225, 29, 72)
PATH_SOFT = (251, 113, 133)
ROBOT = (14, 165, 233)
GOAL = (245, 158, 11)

NODE_COLORS = {
    "entrance": (34, 197, 94),
    "room": (59, 130, 246),
    "corridor": (100, 116, 139),
    "intersection": (168, 85, 247),
    "elevator": (249, 115, 22),
    "stairs": (220, 38, 38),
}
EDGE_COLORS = {
    "traversable": (148, 163, 184),
    "elevator_connection": (249, 115, 22),
    "stairs_up": (220, 38, 38),
    "stairs_down": (220, 38, 38),
}

MAP_BOX = (34.0, 58.0, 620.0, 374.0)
INFO_BOX = (642.0, 58.0, 926.0, 374.0)
WAYPOINT_BOX = (34.0, 398.0, 926.0, 518.0)
FLOOR_OFFSET = 9.0
Y_MIN = -5.4
Y_MAX = 22.8
X_MIN = -0.8
X_MAX = 12.9


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
FONT_H2 = _font(16, bold=True)
FONT_TITLE = _font(22, bold=True)
FONT_MONO = _font(11)


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
    fill=INK,
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
    step = dash * 2
    t = 0.0
    while t < length:
        t2 = min(t + dash, length)
        p0 = (ax + (bx - ax) * (t / length), ay + (by - ay) * (t / length))
        p1 = (ax + (bx - ax) * (t2 / length), ay + (by - ay) * (t2 / length))
        draw.line([_pt(*p0), _pt(*p1)], fill=fill, width=_s(width))
        t += step


def _wrap(text: str, limit: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        next_line = f"{current} {word}".strip()
        if len(next_line) <= limit:
            current = next_line
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _floor_of(node: Any) -> int:
    value = node.properties.get("floor", 1)
    return int(value)


def _world_xy(node: Any) -> tuple[float, float]:
    if node.pose is None:
        raise ValueError(f"node {node.id!r} has no pose")
    return node.pose.x, node.pose.y + (_floor_of(node) - 1) * FLOOR_OFFSET


def _map_xy(node: Any) -> tuple[float, float]:
    x0, y0, x1, y1 = MAP_BOX
    x, y = _world_xy(node)
    px = x0 + (x - X_MIN) / (X_MAX - X_MIN) * (x1 - x0)
    py = y1 - (y - Y_MIN) / (Y_MAX - Y_MIN) * (y1 - y0)
    return px, py


def _partial(a: tuple[float, float], b: tuple[float, float], t: float) -> tuple[float, float]:
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t


def _ease(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)


def _draw_header(draw: ImageDraw.ImageDraw) -> None:
    _text(draw, (34, 20), "semantic-toponav recorded demo", FONT_TITLE, INK)
    _text(
        draw,
        (642, 25),
        "source: examples/multi_floor_office.yaml",
        FONT_SM,
        MUTED,
    )


def _draw_panel(draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float]) -> None:
    _round_rect(draw, box, 12, PANEL, (203, 213, 225), 1)


def _draw_floor_bands(draw: ImageDraw.ImageDraw) -> None:
    x0, _, x1, _ = MAP_BOX
    for floor in (1, 2, 3):
        y_low = (floor - 1) * FLOOR_OFFSET - 4.8
        y_high = (floor - 1) * FLOOR_OFFSET + 4.8
        _, top = _map_world_xy(0, y_high)
        _, bottom = _map_world_xy(0, y_low)
        fill = (248, 250, 252) if floor % 2 else (241, 245, 249)
        draw.rectangle(_box((x0 + 12, top, x1 - 12, bottom)), fill=fill)
        draw.line([_pt(x0 + 12, bottom), _pt(x1 - 12, bottom)], fill=(226, 232, 240), width=_s(1))
        _text(draw, (x0 + 20, top + 8), f"floor {floor}", FONT_BOLD, MUTED)


def _map_world_xy(x: float, y: float) -> tuple[float, float]:
    x0, y0, x1, y1 = MAP_BOX
    px = x0 + (x - X_MIN) / (X_MAX - X_MIN) * (x1 - x0)
    py = y1 - (y - Y_MIN) / (Y_MAX - Y_MIN) * (y1 - y0)
    return px, py


def _edge_style(edge_type: str) -> tuple[tuple[int, int, int], float, float | None]:
    if edge_type == "elevator_connection":
        return EDGE_COLORS[edge_type], 3.0, 7.0
    if edge_type.startswith("stairs"):
        return EDGE_COLORS.get(edge_type, (220, 38, 38)), 2.4, 6.0
    return EDGE_COLORS.get(edge_type, (148, 163, 184)), 1.8, None


def _draw_graph_base(draw: ImageDraw.ImageDraw, graph: Any) -> None:
    _draw_panel(draw, MAP_BOX)
    _text(draw, (52, 72), "actual topology graph", FONT_H2, INK)
    _draw_floor_bands(draw)

    for edge in graph.edges():
        src = graph.get_node(edge.source)
        tgt = graph.get_node(edge.target)
        color, width, dash = _edge_style(edge.type)
        _line(draw, _map_xy(src), _map_xy(tgt), fill=color, width=width, dash=dash)

    for node in graph.nodes():
        x, y = _map_xy(node)
        color = NODE_COLORS.get(node.type, (59, 130, 246))
        draw.ellipse(_box((x - 6, y - 6, x + 6, y + 6)), fill=color, outline=(15, 23, 42), width=_s(1))
        if node.id in {
            "entrance",
            "elevator_1f",
            "elevator_2f",
            "elevator_3f",
            "corridor_3f",
            "exec_office_3f",
        }:
            label = node.label.replace("Elevator A ", "Elevator ")
            _text(draw, (x + 9, y - 8), label, FONT_XS, INK)


def _draw_path(
    draw: ImageDraw.ImageDraw,
    graph: Any,
    route: list[str],
    progress: float,
) -> tuple[float, float, int]:
    segment = min(int(progress), len(route) - 2)
    local = progress - segment

    for idx, (a, b) in enumerate(zip(route[:-1], route[1:], strict=False)):
        src = graph.get_node(a)
        tgt = graph.get_node(b)
        start = _map_xy(src)
        end = _map_xy(tgt)
        if idx < segment:
            _line(draw, start, end, fill=PATH, width=5.2)
        elif idx == segment:
            mid = _partial(start, end, local)
            _line(draw, start, mid, fill=PATH, width=5.2)
            _line(draw, mid, end, fill=PATH_SOFT, width=3.0, dash=6.0)
        else:
            _line(draw, start, end, fill=(251, 113, 133), width=2.0, dash=6.0)

    a = graph.get_node(route[segment])
    b = graph.get_node(route[segment + 1])
    robot_xy = _partial(_map_xy(a), _map_xy(b), local)
    return robot_xy[0], robot_xy[1], segment


def _draw_robot(draw: ImageDraw.ImageDraw, xy: tuple[float, float]) -> None:
    x, y = xy
    draw.ellipse(_box((x - 15, y - 15, x + 15, y + 15)), fill=(186, 230, 253), outline=ROBOT, width=_s(3))
    draw.ellipse(_box((x - 6, y - 6, x + 6, y + 6)), fill=ROBOT, outline=(255, 255, 255), width=_s(2))
    draw.polygon([_pt(x, y - 23), _pt(x - 7, y - 9), _pt(x + 7, y - 9)], fill=ROBOT)


def _draw_info_panel(
    draw: ImageDraw.ImageDraw,
    candidates: list[Any],
    route: list[str],
    waypoints: list[Any],
    current_idx: int,
) -> None:
    _draw_panel(draw, INFO_BOX)
    x0, y0, _, _ = INFO_BOX
    goal = candidates[0]
    current = waypoints[min(current_idx, len(waypoints) - 1)]

    _text(draw, (x0 + 18, y0 + 18), "1. resolve language goal", FONT_H2, INK)
    _text(draw, (x0 + 18, y0 + 44), f'query: "{QUERY}"', FONT_MONO, INK)
    _round_rect(draw, (x0 + 18, y0 + 66, x0 + 248, y0 + 96), 8, (240, 253, 244), (134, 239, 172))
    _text(draw, (x0 + 31, y0 + 75), f"{goal.node_id}  score={goal.score:.1f}", FONT_BOLD, (22, 101, 52))

    _text(draw, (x0 + 18, y0 + 118), "2. plan route", FONT_H2, INK)
    _text(draw, (x0 + 18, y0 + 144), "plan_astar + prefer_elevator", FONT_MONO, INK)
    route_lines = _wrap(" -> ".join(route), 36)
    for row, line in enumerate(route_lines[:4]):
        _text(draw, (x0 + 18, y0 + 166 + row * 16), line, FONT_MONO, MUTED)

    _text(draw, (x0 + 18, y0 + 246), "3. execute semantic waypoint", FONT_H2, INK)
    _round_rect(draw, (x0 + 18, y0 + 273, x0 + 248, y0 + 304), 8, (239, 246, 255), (147, 197, 253))
    _text(draw, (x0 + 31, y0 + 282), f"{current.action}: {current.node_id}", FONT_BOLD, (30, 64, 175))


def _draw_waypoints(
    draw: ImageDraw.ImageDraw,
    waypoints: list[Any],
    current_idx: int,
) -> None:
    _draw_panel(draw, WAYPOINT_BOX)
    x0, y0, x1, _ = WAYPOINT_BOX
    _text(draw, (x0 + 18, y0 + 15), "semantic waypoint array", FONT_H2, INK)

    col_w = (x1 - x0 - 36) / len(waypoints)
    row_top = y0 + 49
    for idx, waypoint in enumerate(waypoints):
        left = x0 + 18 + idx * col_w
        active = idx == current_idx
        visited = idx < current_idx
        fill = (255, 247, 237) if active else (248, 250, 252)
        outline = GOAL if active else (203, 213, 225)
        _round_rect(draw, (left, row_top, left + col_w - 8, row_top + 52), 8, fill, outline, 2 if active else 1)
        dot = GOAL if active else (34, 197, 94) if visited else (148, 163, 184)
        draw.ellipse(_box((left + 10, row_top + 12, left + 22, row_top + 24)), fill=dot)
        _text(draw, (left + 29, row_top + 9), f"{idx + 1}", FONT_BOLD, INK if active else MUTED)
        for row, line in enumerate(_wrap(waypoint.instruction, 15)[:2]):
            _text(draw, (left + 10, row_top + 30 + row * 13), line, FONT_XS, INK if active else MUTED)


def _render_frame(
    graph: Any,
    candidates: list[Any],
    route: list[str],
    waypoints: list[Any],
    frame_idx: int,
) -> Image.Image:
    img = Image.new("RGBA", (W, H), BG)
    draw = ImageDraw.Draw(img, "RGBA")
    _draw_header(draw)
    _draw_graph_base(draw, graph)

    total_segments = len(route) - 1
    raw = frame_idx / (FRAME_COUNT - 1)
    progress = _ease(raw) * total_segments
    rx, ry, segment = _draw_path(draw, graph, route, progress)
    current_idx = min(round(progress), len(waypoints) - 1)
    _draw_robot(draw, (rx, ry))

    current_node = graph.get_node(route[min(segment, len(route) - 1)])
    _round_rect(draw, (52, 336, 398, 361), 8, (15, 23, 42, 232), None)
    _text(draw, (65, 343), f"current node: {current_node.id}", FONT_SM, (255, 255, 255))

    _draw_info_panel(draw, candidates, route, waypoints, current_idx)
    _draw_waypoints(draw, waypoints, current_idx)

    if frame_idx > FRAME_COUNT - 13:
        alpha = int(230 * ((frame_idx - (FRAME_COUNT - 13)) / 12))
        _round_rect(draw, (340, 202, 620, 259), 14, (15, 23, 42, alpha), (245, 158, 11, alpha), 2)
        _text(draw, (480, 217), "goal reached", FONT_TITLE, (255, 255, 255, alpha), "ma")
        _text(draw, (480, 245), "arrive: exec_office_3f", FONT, (226, 232, 240, alpha), "ma")

    img = img.resize((BASE_W, BASE_H), Image.Resampling.LANCZOS)
    return img.convert("P", palette=Image.ADAPTIVE, colors=96)


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
