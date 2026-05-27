"""Record a Foxglove/RViz-style visualization dashboard demo.

The animation is generated from real semantic-toponav data:

* ``resolve_goal("executive office on 3F")``
* ``plan_astar(..., prefer_elevator)``
* ``path_to_semantic_waypoints``

It renders those results as a robot visualization dashboard with a map
view, topic/message inspectors, current pose, waypoint stream, route
timeline, and semantic event log. It also writes an MP4 if ``ffmpeg`` is
available.

Run from the repository root:

    python examples/record_visualization_dashboard.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

GRAPH_PATH = HERE / "multi_floor_office.yaml"
GIF_PATH = ROOT / "docs" / "images" / "21_semantic_toponav_visualization.gif"
MP4_PATH = ROOT / "docs" / "images" / "21_semantic_toponav_visualization.mp4"
QUERY = "executive office on 3F"
START_NODE = "entrance"
GOAL_NODE = "exec_office_3f"

W, H = 1280, 720
FRAME_COUNT = 108
FPS = 18
FRAME_MS = int(1000 / FPS)
LOOP = 0

BG = (7, 11, 21)
PANEL = (13, 24, 44)
PANEL_2 = (15, 29, 52)
PANEL_3 = (19, 35, 61)
GRID = (39, 57, 88)
TEXT = (226, 232, 240)
MUTED = (148, 163, 184)
DIM = (71, 85, 105)
GREEN = (34, 197, 94)
CYAN = (34, 211, 238)
PINK = (244, 63, 94)
AMBER = (245, 158, 11)
BLUE = (96, 165, 250)
PURPLE = (168, 85, 247)
RED = (248, 113, 113)

NODE_COLORS = {
    "entrance": GREEN,
    "room": BLUE,
    "corridor": MUTED,
    "intersection": PURPLE,
    "elevator": AMBER,
    "stairs": RED,
}

TOP_BAR = (18.0, 14.0, 1262.0, 58.0)
MAP_BOX = (18.0, 72.0, 814.0, 506.0)
TOPIC_BOX = (832.0, 72.0, 1262.0, 360.0)
MSG_BOX = (832.0, 374.0, 1262.0, 506.0)
TIMELINE_BOX = (18.0, 522.0, 814.0, 704.0)
STATUS_BOX = (832.0, 522.0, 1262.0, 704.0)

FLOOR_OFFSET = 9.0
X_MIN = -1.0
X_MAX = 13.0
Y_MIN = -5.6
Y_MAX = 22.9


def _font(size: int, *, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    family = "DejaVuSansMono" if mono else "DejaVuSans"
    suffix = "-Bold" if bold else ""
    paths = [
        f"/usr/share/fonts/truetype/dejavu/{family}{suffix}.ttf",
        f"/usr/share/fonts/dejavu/{family}{suffix}.ttf",
    ]
    for raw in paths:
        path = Path(raw)
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


FONT_XS = _font(10)
FONT_SM = _font(12)
FONT = _font(14)
FONT_BOLD = _font(14, bold=True)
FONT_H2 = _font(17, bold=True)
FONT_TITLE = _font(22, bold=True)
FONT_MONO = _font(12, mono=True)
FONT_MONO_XS = _font(10, mono=True)


def _round_rect(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float, float, float],
    radius: float,
    fill,
    outline=None,
    width: int = 1,
) -> None:
    draw.rounded_rectangle(tuple(round(v) for v in xy), radius=round(radius), fill=fill, outline=outline, width=width)


def _text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    value: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont = FONT,
    fill=TEXT,
    anchor: str | None = None,
) -> None:
    draw.text((round(xy[0]), round(xy[1])), value, font=font, fill=fill, anchor=anchor)


def _line(
    draw: ImageDraw.ImageDraw,
    a: tuple[float, float],
    b: tuple[float, float],
    *,
    fill,
    width: int = 2,
    dash: int | None = None,
) -> None:
    if dash is None:
        draw.line([a, b], fill=fill, width=width)
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
        draw.line([p0, p1], fill=fill, width=width)
        t += dash * 2


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _floor_of(node: Any) -> int:
    return int(node.properties.get("floor", 1))


def _world_xy(node: Any) -> tuple[float, float]:
    if node.pose is None:
        raise ValueError(f"node {node.id!r} has no pose")
    return node.pose.x, node.pose.y + (_floor_of(node) - 1) * FLOOR_OFFSET


def _map_world_xy(x: float, y: float) -> tuple[float, float]:
    x0, y0, x1, y1 = MAP_BOX
    px = x0 + 34 + (x - X_MIN) / (X_MAX - X_MIN) * (x1 - x0 - 68)
    py = y1 - 34 - (y - Y_MIN) / (Y_MAX - Y_MIN) * (y1 - y0 - 68)
    return px, py


def _map_xy(node: Any) -> tuple[float, float]:
    return _map_world_xy(*_world_xy(node))


def _partial(a: tuple[float, float], b: tuple[float, float], t: float) -> tuple[float, float]:
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t


def _wrap(text: str, limit: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= limit:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_background(draw: ImageDraw.ImageDraw) -> None:
    draw.rectangle((0, 0, W, H), fill=BG)
    for x in range(-120, W + 120, 44):
        draw.line([(x, 0), (x - 150, H)], fill=(*GRID, 42), width=1)
    for y in range(0, H, 44):
        draw.line([(0, y), (W, y)], fill=(*GRID, 28), width=1)


def _draw_panel(draw: ImageDraw.ImageDraw, box: tuple[float, float, float, float], title: str) -> None:
    _round_rect(draw, box, 12, PANEL, (51, 65, 85), 1)
    x0, y0, x1, _ = box
    draw.rectangle((round(x0), round(y0), round(x1), round(y0 + 30)), fill=(9, 17, 31))
    _text(draw, (x0 + 14, y0 + 8), title, FONT_SM, TEXT)


def _draw_top_bar(draw: ImageDraw.ImageDraw, t_sec: float, route: list[str], current_idx: int) -> None:
    _round_rect(draw, TOP_BAR, 12, (10, 21, 40), (51, 65, 85), 1)
    _text(draw, (34, 27), "semantic-toponav visualization", FONT_TITLE, TEXT)
    _text(draw, (330, 31), "map / tf / semantic route / waypoint array", FONT_SM, MUTED)
    _round_rect(draw, (940, 23, 1035, 49), 13, (6, 78, 59), (45, 212, 191), 1)
    _text(draw, (987, 29), "live", FONT_BOLD, (167, 243, 208), "ma")
    _text(draw, (1060, 29), f"t={t_sec:04.1f}s", FONT_MONO, CYAN)
    _text(draw, (1145, 29), f"wp {current_idx + 1}/{len(route)}", FONT_MONO, AMBER)


def _draw_map(
    draw: ImageDraw.ImageDraw,
    graph: Any,
    route: list[str],
    progress: float,
) -> tuple[tuple[float, float], int]:
    _draw_panel(draw, MAP_BOX, "3D/map view: semantic topology + robot pose")
    x0, _, x1, _ = MAP_BOX
    for floor in (1, 2, 3):
        y_low = (floor - 1) * FLOOR_OFFSET - 4.8
        y_high = (floor - 1) * FLOOR_OFFSET + 4.8
        _, top = _map_world_xy(0, y_high)
        _, bottom = _map_world_xy(0, y_low)
        fill = PANEL_2 if floor % 2 else PANEL_3
        _round_rect(draw, (x0 + 18, top, x1 - 18, bottom), 9, fill, (71, 85, 105), 1)
        _text(draw, (x0 + 32, top + 9), f"floor {floor}", FONT_BOLD, MUTED)

    # Static topology.
    for edge in graph.edges():
        a = _map_xy(graph.get_node(edge.source))
        b = _map_xy(graph.get_node(edge.target))
        if edge.type == "elevator_connection":
            _line(draw, a, b, fill=(*AMBER, 135), width=3, dash=8)
        elif edge.type.startswith("stairs"):
            _line(draw, a, b, fill=(*RED, 105), width=2, dash=7)
        else:
            _line(draw, a, b, fill=(*MUTED, 130), width=2)

    # Route trail.
    segment = min(int(progress), len(route) - 2)
    local = progress - segment
    for idx, (a_id, b_id) in enumerate(zip(route[:-1], route[1:], strict=False)):
        a = _map_xy(graph.get_node(a_id))
        b = _map_xy(graph.get_node(b_id))
        if idx < segment:
            _line(draw, a, b, fill=(*PINK, 255), width=5)
        elif idx == segment:
            mid = _partial(a, b, local)
            _line(draw, a, mid, fill=(*PINK, 255), width=5)
            _line(draw, mid, b, fill=(*PINK, 80), width=3, dash=8)
        else:
            _line(draw, a, b, fill=(*PINK, 56), width=2, dash=8)

    for node in graph.nodes():
        x, y = _map_xy(node)
        color = NODE_COLORS.get(node.type, BLUE)
        r = 6 if node.id not in route else 8
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(*color, 240), outline=(3, 7, 18), width=2)
        if node.id in {"entrance", "elevator_1f", "elevator_2f", "elevator_3f", "exec_office_3f"}:
            label = node.label.replace("Elevator A ", "Elevator ")
            _round_rect(draw, (x - 50, y - 29, x + 50, y - 12), 7, (3, 7, 18, 220), (*color, 190), 1)
            _text(draw, (x, y - 27), label, FONT_XS, TEXT, "ma")

    robot = _partial(_map_xy(graph.get_node(route[segment])), _map_xy(graph.get_node(route[segment + 1])), local)
    rx, ry = robot
    draw.ellipse((rx - 23, ry - 23, rx + 23, ry + 23), fill=(*CYAN, 38))
    draw.ellipse((rx - 15, ry - 15, rx + 15, ry + 15), fill=(8, 47, 73), outline=CYAN, width=3)
    draw.ellipse((rx - 5, ry - 5, rx + 5, ry + 5), fill=(255, 255, 255))
    _text(draw, (rx + 22, ry - 7), "/tf base_link", FONT_XS, CYAN)
    return robot, segment


def _message_for_topic(topic: str, graph: Any, candidates: list[Any], route: list[str], waypoints: list[Any], segment: int, robot: tuple[float, float]) -> dict[str, Any]:
    waypoint = waypoints[min(segment, len(waypoints) - 1)]
    node = graph.get_node(route[min(segment, len(route) - 1)])
    if topic == "/semantic_toponav/resolve_trace":
        return {
            "query": QUERY,
            "chosen": candidates[0].node_id,
            "score": candidates[0].score,
            "reasons": candidates[0].reasons[:2],
        }
    if topic == "/semantic_toponav/route":
        return {"start": START_NODE, "goal": GOAL_NODE, "path": route}
    if topic == "/semantic_toponav/waypoints":
        return {
            "current": waypoint.to_dict(),
            "count": len(waypoints),
            "schema": "SemanticWaypointArray",
        }
    if topic == "/tf":
        return {
            "frame_id": "map",
            "child_frame_id": "base_link",
            "semantic_node": node.id,
            "screen_xy": [round(robot[0], 1), round(robot[1], 1)],
        }
    return {"topic": topic}


def _draw_topics(
    draw: ImageDraw.ImageDraw,
    graph: Any,
    candidates: list[Any],
    route: list[str],
    waypoints: list[Any],
    segment: int,
    robot: tuple[float, float],
    t: float,
) -> None:
    _draw_panel(draw, TOPIC_BOX, "topics")
    topics = [
        "/tf",
        "/semantic_toponav/resolve_trace",
        "/semantic_toponav/route",
        "/semantic_toponav/waypoints",
        "/semantic_toponav/conflict_explanation",
    ]
    selected = topics[min(len(topics) - 1, int(t * len(topics) * 0.85) % 4)]
    x0, y0, _, _ = TOPIC_BOX
    y = y0 + 45
    for topic in topics:
        active = topic == selected
        color = CYAN if active else MUTED
        fill = (8, 47, 73) if active else (10, 21, 40)
        _round_rect(draw, (x0 + 14, y, x0 + 398, y + 30), 8, fill, (51, 65, 85), 1)
        draw.ellipse((x0 + 26, y + 10, x0 + 36, y + 20), fill=color)
        hz = "18 Hz" if topic == "/tf" else "1 msg" if "conflict" not in topic else "idle"
        _text(draw, (x0 + 48, y + 8), topic, FONT_MONO, TEXT if active else MUTED)
        _text(draw, (x0 + 342, y + 8), hz, FONT_XS, color)
        y += 39

    _draw_panel(draw, MSG_BOX, f"message inspector: {selected}")
    msg = _message_for_topic(selected, graph, candidates, route, waypoints, segment, robot)
    payload = json.dumps(msg, ensure_ascii=True, indent=2)
    y = MSG_BOX[1] + 39
    for line in payload.splitlines()[:7]:
        _text(draw, (MSG_BOX[0] + 14, y), line, FONT_MONO_XS, TEXT if ":" in line else MUTED)
        y += 14


def _draw_timeline(draw: ImageDraw.ImageDraw, route: list[str], progress: float, t: float) -> None:
    _draw_panel(draw, TIMELINE_BOX, "timeline / route progress")
    x0, y0, x1, y1 = TIMELINE_BOX
    base_y = y0 + 90
    left = x0 + 42
    right = x1 - 42
    draw.line([(left, base_y), (right, base_y)], fill=(*DIM, 255), width=4)
    for idx, node_id in enumerate(route):
        x = left + (right - left) * idx / (len(route) - 1)
        active = idx <= progress
        color = GREEN if active else DIM
        draw.ellipse((x - 7, base_y - 7, x + 7, base_y + 7), fill=color)
        short = node_id.replace("elevator_", "el_").replace("corridor_", "cor_").replace("exec_office_3f", "goal")
        _text(draw, (x, base_y + 18), short, FONT_XS, TEXT if active else MUTED, "ma")
    rx = left + (right - left) * progress / (len(route) - 1)
    draw.rectangle((left, y0 + 47, rx, y0 + 56), fill=PINK)
    draw.rectangle((rx, y0 + 47, right, y0 + 56), fill=(51, 65, 85))
    _text(draw, (left, y0 + 24), f"playhead {t:04.1f}s", FONT_MONO, CYAN)
    _text(draw, (right, y0 + 24), "semantic route", FONT_MONO, MUTED, "ra")


def _draw_status(draw: ImageDraw.ImageDraw, waypoints: list[Any], segment: int, t: float) -> None:
    _draw_panel(draw, STATUS_BOX, "semantic waypoint array")
    x0, y0, _, _ = STATUS_BOX
    y = y0 + 44
    for idx, waypoint in enumerate(waypoints[:7]):
        active = idx == min(segment, len(waypoints) - 1)
        done = idx < segment
        color = AMBER if active else GREEN if done else DIM
        fill = (67, 56, 24) if active else (10, 21, 40)
        _round_rect(draw, (x0 + 14, y, x0 + 398, y + 25), 7, fill, (51, 65, 85), 1)
        draw.ellipse((x0 + 25, y + 8, x0 + 34, y + 17), fill=color)
        _text(draw, (x0 + 45, y + 6), f"{idx + 1}. {waypoint.instruction}", FONT_XS, TEXT if active else MUTED)
        y += 30
    _round_rect(draw, (x0 + 14, y0 + 251, x0 + 398, y0 + 275), 7, (5, 46, 22), (34, 197, 94), 1)
    _text(draw, (x0 + 28, y0 + 257), "reservation/admission: granted", FONT_MONO_XS, (187, 247, 208))
    _text(draw, (x0 + 278, y0 + 257), f"latency={18 + int(t) % 6}ms", FONT_MONO_XS, (187, 247, 208))


def _render_frame(graph: Any, candidates: list[Any], route: list[str], waypoints: list[Any], frame_idx: int) -> Image.Image:
    t = frame_idx / FPS
    raw = frame_idx / (FRAME_COUNT - 1)
    progress = _ease(raw) * (len(route) - 1)
    img = Image.new("RGBA", (W, H), BG)
    draw = ImageDraw.Draw(img, "RGBA")
    _draw_background(draw)
    robot, segment = _draw_map(draw, graph, route, progress)
    _draw_top_bar(draw, t, route, min(round(progress), len(route) - 1))
    _draw_topics(draw, graph, candidates, route, waypoints, segment, robot, raw)
    _draw_timeline(draw, route, progress, t)
    _draw_status(draw, waypoints, segment, t)
    if raw > 0.91:
        alpha = int(220 * min(1.0, (raw - 0.91) / 0.09))
        _round_rect(draw, (440, 230, 680, 286), 15, (4, 10, 24, alpha), (245, 158, 11, alpha), 2)
        _text(draw, (560, 245), "goal reached", FONT_TITLE, (255, 255, 255, alpha), "ma")
        _text(draw, (560, 274), GOAL_NODE, FONT_BOLD, (253, 230, 138, alpha), "ma")
    return img.convert("RGB")


def _load_demo() -> tuple[Any, list[Any], list[str], list[Any]]:
    from semantic_toponav.graph.serialization import load_graph
    from semantic_toponav.planner import compose_costs, plan_astar, prefer_elevator
    from semantic_toponav.query.resolve import resolve_goal
    from semantic_toponav.waypoint import path_to_semantic_waypoints

    graph = load_graph(GRAPH_PATH)
    candidates = resolve_goal(graph, QUERY)
    if not candidates:
        raise RuntimeError(f"query did not resolve: {QUERY!r}")
    route = plan_astar(graph, START_NODE, GOAL_NODE, cost_fn=compose_costs(prefer_elevator))
    waypoints = path_to_semantic_waypoints(graph, route)
    return graph, candidates, route, waypoints


def _write_mp4(frames: list[Image.Image]) -> None:
    if shutil.which("ffmpeg") is None:
        print("ffmpeg not found; skipped MP4")
        return
    with tempfile.TemporaryDirectory(prefix="semantic-toponav-frames-") as tmp:
        tmp_path = Path(tmp)
        for idx, frame in enumerate(frames):
            frame.save(tmp_path / f"frame_{idx:04d}.png")
        cmd = [
            "ffmpeg",
            "-y",
            "-framerate",
            str(FPS),
            "-i",
            str(tmp_path / "frame_%04d.png"),
            "-vf",
            "format=yuv420p",
            "-movflags",
            "+faststart",
            str(MP4_PATH),
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"wrote {MP4_PATH.relative_to(ROOT)}")


def main() -> None:
    graph, candidates, route, waypoints = _load_demo()
    frames = [_render_frame(graph, candidates, route, waypoints, idx) for idx in range(FRAME_COUNT)]
    GIF_PATH.parent.mkdir(parents=True, exist_ok=True)
    gif_frames = [frame.convert("P", palette=Image.ADAPTIVE, colors=128) for frame in frames]
    gif_frames[0].save(
        GIF_PATH,
        save_all=True,
        append_images=gif_frames[1:],
        duration=FRAME_MS,
        loop=LOOP,
        optimize=True,
        disposal=2,
    )
    _write_mp4(frames)
    size_kb = GIF_PATH.stat().st_size / 1024
    print(f"query: {QUERY!r} -> {candidates[0].node_id}")
    print(f"route: {' -> '.join(route)}")
    print(f"wrote {GIF_PATH.relative_to(ROOT)} ({size_kb:.0f} KB, {len(frames)} frames)")


if __name__ == "__main__":
    main()
