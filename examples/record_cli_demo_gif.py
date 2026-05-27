"""Record a real CLI demo GIF for the README hero.

Unlike the showcase renderer, this script captures actual CLI command
output from ``semantic_toponav.cli.main`` and renders it beside the same
planned route on the shipped graph.

Run from the repository root:

    python examples/record_cli_demo_gif.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

GRAPH_PATH = HERE / "multi_floor_office.yaml"
GRAPH_ARG = "examples/multi_floor_office.yaml"
OUT_PATH = ROOT / "docs" / "images" / "20_semantic_toponav_cli_demo.gif"
QUERY = "executive office on 3F"
START_NODE = "entrance"
GOAL_NODE = "exec_office_3f"

BASE_W, BASE_H = 960, 540
SCALE = 2
W, H = BASE_W * SCALE, BASE_H * SCALE
FRAME_COUNT = 86
FRAME_MS = 70
LOOP = 0

BG = (8, 13, 25)
PANEL = (13, 24, 44)
PANEL2 = (15, 28, 52)
GRID = (43, 60, 90)
TEXT = (226, 232, 240)
MUTED = (148, 163, 184)
GREEN = (34, 197, 94)
CYAN = (34, 211, 238)
PINK = (244, 63, 94)
AMBER = (245, 158, 11)
BLUE = (96, 165, 250)
PURPLE = (168, 85, 247)

NODE_COLORS = {
    "entrance": GREEN,
    "room": BLUE,
    "corridor": MUTED,
    "intersection": PURPLE,
    "elevator": AMBER,
    "stairs": (248, 113, 113),
}

FLOOR_OFFSET = 9.0
X_MIN = -0.8
X_MAX = 12.9
Y_MIN = -5.4
Y_MAX = 22.8
GRAPH_BOX = (462.0, 92.0, 924.0, 374.0)
TERM_BOX = (32.0, 92.0, 432.0, 438.0)


def _s(value: float) -> int:
    return int(round(value * SCALE))


def _pt(x: float, y: float) -> tuple[int, int]:
    return _s(x), _s(y)


def _box(xy: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    return tuple(_s(v) for v in xy)


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for raw in paths:
        path = Path(raw)
        if path.exists():
            return ImageFont.truetype(str(path), _s(size))
    return ImageFont.load_default()


FONT_XS = _font(8)
FONT_SM = _font(10)
FONT = _font(12)
FONT_BOLD = _font(12, bold=True)
FONT_TITLE = _font(24, bold=True)
FONT_MONO = _font(10)


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


def _wrap_line(line: str, width: int) -> list[str]:
    if len(line) <= width:
        return [line]
    out: list[str] = []
    cur = line
    indent = "  "
    while len(cur) > width:
        split = cur.rfind(" ", 0, width)
        if split < 12:
            split = width
        out.append(cur[:split])
        cur = indent + cur[split:].lstrip()
    if cur:
        out.append(cur)
    return out


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _run_cli(args: list[str]) -> str:
    cmd = [sys.executable, "-m", "semantic_toponav.cli.main", *args]
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return proc.stdout.strip()


def _capture_demo_output() -> list[tuple[str, str]]:
    commands = [
        (
            f'python -m semantic_toponav.cli.main resolve {GRAPH_ARG} "{QUERY}"',
            _run_cli(["resolve", GRAPH_ARG, QUERY]),
        ),
        (
            f"python -m semantic_toponav.cli.main plan {GRAPH_ARG} {START_NODE} {GOAL_NODE} --prefer-elevator",
            _run_cli(["plan", GRAPH_ARG, START_NODE, GOAL_NODE, "--prefer-elevator"]),
        ),
        (
            f"python -m semantic_toponav.cli.main waypoints {GRAPH_ARG} {START_NODE} {GOAL_NODE} --prefer-elevator",
            _run_cli(["waypoints", GRAPH_ARG, START_NODE, GOAL_NODE, "--prefer-elevator"]),
        ),
    ]
    return commands


def _visible_terminal_lines(commands: list[tuple[str, str]], frame_t: float) -> list[tuple[str, tuple[int, int, int]]]:
    # Reveal one real command/output block at a time.
    block_progress = min(len(commands) - 1, int(frame_t * len(commands)))
    block_t = frame_t * len(commands) - block_progress
    lines: list[tuple[str, tuple[int, int, int]]] = []
    for idx, (cmd, output) in enumerate(commands):
        if idx > block_progress:
            break
        lines.append((f"$ {cmd}", CYAN))
        output_lines: list[str] = []
        for raw in output.splitlines():
            output_lines.extend(_wrap_line(raw, 54))
        if idx < block_progress:
            visible_count = len(output_lines)
        else:
            visible_count = int(len(output_lines) * _ease(block_t))
        for line in output_lines[:visible_count]:
            color = GREEN if "exec_office_3f" in line or "Arrive" in line else TEXT
            if "Path:" in line or "Semantic Waypoints:" in line or "Candidates" in line:
                color = AMBER
            lines.append((line, color))
        lines.append(("", MUTED))
    return lines[-18:]


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


def _draw_background(draw: ImageDraw.ImageDraw) -> None:
    draw.rectangle(_box((0, 0, BASE_W, BASE_H)), fill=BG)
    for x in range(0, BASE_W, 42):
        draw.line([_pt(x, 0), _pt(x - 120, BASE_H)], fill=(*GRID, 60), width=1)
    for y in range(0, BASE_H, 42):
        draw.line([_pt(0, y), _pt(BASE_W, y)], fill=(*GRID, 38), width=1)


def _draw_header(draw: ImageDraw.ImageDraw) -> None:
    _text(draw, (32, 24), "semantic-toponav real CLI demo", FONT_TITLE, TEXT)
    _text(draw, (34, 58), "Captured commands + the same route animated on the shipped graph", FONT, MUTED)
    _round_rect(draw, (716, 24, 928, 61), 18, (5, 46, 22, 210), (34, 197, 94, 210))
    _text(draw, (822, 35), "actual CLI output", FONT_BOLD, (187, 247, 208), "ma")


def _draw_terminal(draw: ImageDraw.ImageDraw, commands: list[tuple[str, str]], frame_t: float) -> None:
    _round_rect(draw, TERM_BOX, 16, PANEL, (71, 85, 105, 150), 1)
    x0, y0, _, _ = TERM_BOX
    draw.rectangle(_box((x0, y0, x0 + 400, y0 + 30)), fill=(4, 10, 24, 230))
    for i, color in enumerate([(248, 113, 113), (250, 204, 21), (34, 197, 94)]):
        draw.ellipse(_box((x0 + 16 + i * 18, y0 + 10, x0 + 26 + i * 18, y0 + 20)), fill=color)
    _text(draw, (x0 + 84, y0 + 9), "bash - semantic-toponav", FONT_XS, MUTED)
    y = y0 + 46
    for line, color in _visible_terminal_lines(commands, frame_t):
        _text(draw, (x0 + 18, y), line, FONT_MONO, color)
        y += 16


def _draw_graph(draw: ImageDraw.ImageDraw, graph: Any, route: list[str], progress: float) -> tuple[float, float, int]:
    _round_rect(draw, GRAPH_BOX, 18, PANEL2, (96, 165, 250, 130), 1)
    x0, _, x1, _ = GRAPH_BOX
    for floor in (1, 2, 3):
        y_low = (floor - 1) * FLOOR_OFFSET - 4.9
        y_high = (floor - 1) * FLOOR_OFFSET + 4.9
        _, top = _map_world_xy(0, y_high)
        _, bottom = _map_world_xy(0, y_low)
        fill = (20, 38, 70, 230) if floor % 2 else (15, 31, 60, 230)
        _round_rect(draw, (x0 + 10, top, x1 - 10, bottom), 10, fill, (71, 85, 105, 130))
        _text(draw, (x0 + 24, top + 10), f"floor {floor}", FONT_BOLD, MUTED)

    for edge in graph.edges():
        a = _map_xy(graph.get_node(edge.source))
        b = _map_xy(graph.get_node(edge.target))
        if edge.type == "elevator_connection":
            _line(draw, a, b, fill=(*AMBER, 120), width=2.8, dash=7)
        elif edge.type.startswith("stairs"):
            _line(draw, a, b, fill=(248, 113, 113, 100), width=2.2, dash=6)
        else:
            _line(draw, a, b, fill=(148, 163, 184, 150), width=1.8)

    segment = min(int(progress), len(route) - 2)
    local = progress - segment
    for idx, (a_id, b_id) in enumerate(zip(route[:-1], route[1:], strict=False)):
        a = _map_xy(graph.get_node(a_id))
        b = _map_xy(graph.get_node(b_id))
        if idx < segment:
            _line(draw, a, b, fill=(*PINK, 255), width=4.4)
        elif idx == segment:
            mid = _partial(a, b, local)
            _line(draw, a, mid, fill=(*PINK, 255), width=4.4)
            _line(draw, mid, b, fill=(*PINK, 85), width=2.0)
        else:
            _line(draw, a, b, fill=(*PINK, 70), width=1.8, dash=6)

    for node in graph.nodes():
        x, y = _map_xy(node)
        color = NODE_COLORS.get(node.type, BLUE)
        draw.ellipse(_box((x - 5, y - 5, x + 5, y + 5)), fill=(*color, 240), outline=(4, 10, 24), width=_s(1))
        if node.id in {"entrance", "elevator_1f", "elevator_3f", "exec_office_3f"}:
            label = node.label.replace("Elevator A ", "Elevator ")
            _round_rect(draw, (x - 43, y - 28, x + 43, y - 11), 7, (4, 10, 24, 210), (*color, 180))
            _text(draw, (x, y - 25), label, FONT_XS, TEXT, "ma")

    a = _map_xy(graph.get_node(route[segment]))
    b = _map_xy(graph.get_node(route[segment + 1]))
    return (*_partial(a, b, local), segment)


def _draw_robot(draw: ImageDraw.ImageDraw, x: float, y: float) -> None:
    draw.ellipse(_box((x - 19, y - 19, x + 19, y + 19)), fill=(*CYAN, 42))
    draw.ellipse(_box((x - 13, y - 13, x + 13, y + 13)), fill=(8, 47, 73), outline=CYAN, width=_s(3))
    draw.ellipse(_box((x - 4, y - 4, x + 4, y + 4)), fill=(255, 255, 255))


def _draw_waypoints(draw: ImageDraw.ImageDraw, waypoints: list[Any], current_idx: int) -> None:
    _round_rect(draw, (462, 396, 924, 438), 14, PANEL, (71, 85, 105, 150), 1)
    col_w = 438 / len(waypoints)
    for idx, waypoint in enumerate(waypoints):
        left = 474 + idx * col_w
        active = idx == current_idx
        visited = idx < current_idx
        color = AMBER if active else GREEN if visited else (71, 85, 105)
        draw.ellipse(_box((left, 414, left + 10, 424)), fill=color)
        _text(draw, (left + 14, 410), waypoint.action.split("_")[0], FONT_XS, TEXT if active else MUTED)


def _load_route() -> tuple[Any, list[str], list[Any]]:
    from semantic_toponav.graph.serialization import load_graph
    from semantic_toponav.planner import compose_costs, plan_astar, prefer_elevator
    from semantic_toponav.waypoint import path_to_semantic_waypoints

    graph = load_graph(GRAPH_PATH)
    route = plan_astar(graph, START_NODE, GOAL_NODE, cost_fn=compose_costs(prefer_elevator))
    return graph, route, path_to_semantic_waypoints(graph, route)


def _render_frame(
    commands: list[tuple[str, str]],
    graph: Any,
    route: list[str],
    waypoints: list[Any],
    frame_idx: int,
) -> Image.Image:
    raw = frame_idx / (FRAME_COUNT - 1)
    progress = _ease(max(0.0, (raw - 0.18) / 0.78)) * (len(route) - 1)
    img = Image.new("RGBA", (W, H), BG)
    draw = ImageDraw.Draw(img, "RGBA")
    _draw_background(draw)
    _draw_header(draw)
    _draw_terminal(draw, commands, raw)
    rx, ry, segment = _draw_graph(draw, graph, route, progress)
    _draw_robot(draw, rx, ry)
    current_idx = min(round(progress), len(waypoints) - 1)
    _draw_waypoints(draw, waypoints, current_idx)
    _text(draw, (462, 457), f"route: {' -> '.join(route)}", FONT_XS, MUTED)
    if raw > 0.9:
        alpha = int(225 * min(1.0, (raw - 0.9) / 0.1))
        _round_rect(draw, (576, 210, 806, 264), 16, (4, 10, 24, alpha), (245, 158, 11, alpha), 2)
        _text(draw, (691, 225), "goal reached", FONT_TITLE, (255, 255, 255, alpha), "ma")
    img = img.resize((BASE_W, BASE_H), Image.Resampling.LANCZOS)
    return img.convert("P", palette=Image.ADAPTIVE, colors=128)


def main() -> None:
    commands = _capture_demo_output()
    graph, route, waypoints = _load_route()
    frames = [
        _render_frame(commands, graph, route, waypoints, idx)
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
    print(f"captured {len(commands)} CLI commands")
    print(f"route: {' -> '.join(route)}")
    print(f"wrote {OUT_PATH.relative_to(ROOT)} ({size_kb:.0f} KB, {len(frames)} frames)")


if __name__ == "__main__":
    main()
