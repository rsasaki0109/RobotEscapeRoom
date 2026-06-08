"""Record the Robot Escape Room as a full robotics simulation dashboard GIF.

1280×720 Foxglove/RViz-style layout (same class as
``record_visualization_dashboard.py``): map + /tf, topic list, message
inspector, route timeline, and semantic waypoint stream. Every route comes
from ``robot_escape_room.py`` — no scripted animation.

    python examples/record_escape_room_sim.py

Writes ``docs/images/robot_escape_room_dashboard.gif``.
  The README hero (3D Gazebo-style replay) is built via
  ``scripts/foxglove_hero/build_escape_room_gif.sh``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import robot_escape_room as game
from PIL import Image, ImageDraw, ImageFont
from robot_escape_room import (
    DECOY_EXIT,
    ITEMS,
    POWER_ITEM,
    RIDDLES,
    TRUE_EXIT,
    UNPOWERED_TYPES,
    World,
    arrive,
    objectives,
    plan,
)

from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.waypoint import path_to_semantic_waypoints

game.VERBOSE = False

ROOT = Path(__file__).resolve().parents[1]
GRAPH_PATH = Path(__file__).parent / "robot_escape_room.yaml"
OUT_GIF = ROOT / "docs/images/robot_escape_room_dashboard.gif"
OUT_MP4 = ROOT / "docs/images/robot_escape_room_dashboard.mp4"

W, H = 1280, 720
FPS = 18
FRAME_MS = int(1000 / FPS)
FRAMES_PER_HOP = 5
HOLD_FRAMES = 8
TWIST_HOLD = 14
ESCAPE_HOLD = 16

FLOOR_DY = 9.0
FLOOR_BAND = {-1: 0, 1: 1, 2: 2, 3: 3}
X_MIN, X_MAX = -2.0, 30.0
Y_MIN, Y_MAX = -10.0, 38.0

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
ORANGE = (251, 146, 60)

TOP_BAR = (18.0, 14.0, 1262.0, 58.0)
MAP_BOX = (18.0, 72.0, 814.0, 506.0)
TOPIC_BOX = (832.0, 72.0, 1262.0, 360.0)
MSG_BOX = (832.0, 374.0, 1262.0, 506.0)
TIMELINE_BOX = (18.0, 522.0, 814.0, 704.0)
STATUS_BOX = (832.0, 522.0, 1262.0, 704.0)

NODE_COLORS = {
    "room": BLUE,
    "corridor": MUTED,
    "intersection": PURPLE,
    "stairs": ORANGE,
    "exit": GREEN,
    "sealed_exit": DIM,
}

TOPICS = [
    "/tf",
    "/semantic_toponav/route",
    "/semantic_toponav/waypoints",
    "/semantic_toponav/resolve_trace",
    "/semantic_toponav/event_log",
]


def _font(size: int, *, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    family = "DejaVuSansMono" if mono else "DejaVuSans"
    suffix = "-Bold" if bold else ""
    for raw in (
        f"/usr/share/fonts/truetype/dejavu/{family}{suffix}.ttf",
        f"/usr/share/fonts/dejavu/{family}{suffix}.ttf",
    ):
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


@dataclass
class FrameState:
    world: World
    route: list[str]
    progress: float
    waypoints: list[Any]
    turn: int
    events: list[str] = field(default_factory=list)
    resolve_payload: dict[str, Any] | None = None
    banner: str | None = None
    banner_sub: str | None = None
    topic_idx: int = 0


def _round_rect(draw, xy, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(tuple(round(v) for v in xy), radius=round(radius), fill=fill, outline=outline, width=width)


def _text(draw, xy, value, font=FONT, fill=TEXT, anchor=None):
    draw.text((round(xy[0]), round(xy[1])), value, font=font, fill=fill, anchor=anchor)


def _line(draw, a, b, *, fill, width=2, dash=None):
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


def _world_xy(node) -> tuple[float, float]:
    floor = int(node.properties.get("floor", 1))
    band = FLOOR_BAND.get(floor, floor)
    return node.pose.x, node.pose.y + band * FLOOR_DY


def _map_world_xy(x: float, y: float) -> tuple[float, float]:
    x0, y0, x1, y1 = MAP_BOX
    px = x0 + 34 + (x - X_MIN) / (X_MAX - X_MIN) * (x1 - x0 - 68)
    py = y1 - 34 - (y - Y_MIN) / (Y_MAX - Y_MIN) * (y1 - y0 - 68)
    return px, py


def _map_xy(node) -> tuple[float, float]:
    return _map_world_xy(*_world_xy(node))


def _partial(a, b, t):
    return a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t


def _edge_open(graph, edge, world) -> bool:
    lock = edge.properties.get("lock")
    if lock and lock not in world.items:
        return False
    if edge.type in UNPOWERED_TYPES and POWER_ITEM not in world.items:
        return False
    if edge.type == "restricted":
        return False
    return True


def _build_timeline(graph) -> list[FrameState]:
    world = World()
    events = ["[boot] T-0 online — Holding Cell"]
    timeline: list[FrameState] = []
    topic_idx = 0

    def push_motion(path: list[str], turn: int, resolve_payload=None):
        nonlocal topic_idx
        if len(path) < 2:
            wps = path_to_semantic_waypoints(graph, path) if path else []
            timeline.append(FrameState(
                world, path or [world.location], 0.0, wps, turn, list(events),
                resolve_payload=resolve_payload, topic_idx=topic_idx % len(TOPICS),
            ))
            topic_idx += 1
            return
        wps = path_to_semantic_waypoints(graph, path)
        for hop in range(len(path) - 1):
            for step in range(FRAMES_PER_HOP):
                t = _ease(step / FRAMES_PER_HOP)
                timeline.append(FrameState(
                    world, path, hop + t, wps, turn, list(events),
                    resolve_payload=resolve_payload, topic_idx=topic_idx % len(TOPICS),
                ))
                topic_idx += 1

    def hold(state: FrameState, n: int):
        timeline.extend([state] * n)

    twist_seen = False
    for turn in range(1, 50):
        exit_path = plan(graph, world, TRUE_EXIT)
        if exit_path is not None:
            push_motion(exit_path, turn)
            hold(FrameState(
                world, exit_path, len(exit_path) - 1,
                path_to_semantic_waypoints(graph, exit_path), turn, list(events),
                banner="ESCAPED", banner_sub="Maintenance Exit (B1)",
                topic_idx=topic_idx % len(TOPICS),
            ), ESCAPE_HOLD)
            break

        opts = objectives(graph, world)
        if not opts:
            break

        _, node, kind, path = opts[0]
        resolve_payload = None
        if kind.startswith("riddle"):
            riddle = RIDDLES[node]
            resolve_payload = {
                "query": riddle["answer"],
                "chosen": riddle["expect_node"],
                "score": 4.0,
                "reasons": ["label match", "floor ok"],
            }

        push_motion(path, turn, resolve_payload)

        items_before = set(world.items)
        solved_before = set(world.solved)
        world.location = node
        arrive(graph, world, node)

        for item in sorted(world.items - items_before):
            events.append(f"[item] {item}")
        for rid in sorted(world.solved - solved_before):
            events.append(f"[riddle] {rid}")

        hold(FrameState(
            world, path, len(path) - 1,
            path_to_semantic_waypoints(graph, path), turn, list(events),
            resolve_payload=resolve_payload, topic_idx=topic_idx % len(TOPICS),
        ), HOLD_FRAMES)

        if not twist_seen and "riddle_3" in world.solved:
            twist_seen = True
            events.append("[twist] Floor-3 exit sealed — route to sublevel")
            hold(FrameState(
                world, path, len(path) - 1,
                path_to_semantic_waypoints(graph, path), turn, list(events),
                resolve_payload,
                banner="DECOY EXIT", banner_sub="Emergency Exit (3F) is welded shut",
                topic_idx=topic_idx % len(TOPICS),
            ), TWIST_HOLD)

    return timeline


def _draw_background(draw):
    draw.rectangle((0, 0, W, H), fill=BG)
    for x in range(-120, W + 120, 44):
        draw.line([(x, 0), (x - 150, H)], fill=(*GRID, 42), width=1)
    for y in range(0, H, 44):
        draw.line([(0, y), (W, y)], fill=(*GRID, 28), width=1)


def _draw_panel(draw, box, title):
    _round_rect(draw, box, 12, PANEL, (51, 65, 85), 1)
    x0, y0, x1, _ = box
    draw.rectangle((round(x0), round(y0), round(x1), round(y0 + 30)), fill=(9, 17, 31))
    _text(draw, (x0 + 14, y0 + 8), title, FONT_SM, TEXT)


def _draw_top_bar(draw, st: FrameState, t_sec: float):
    _round_rect(draw, TOP_BAR, 12, (10, 21, 40), (51, 65, 85), 1)
    _text(draw, (34, 27), "robot-escape-room simulation", FONT_TITLE, TEXT)
    _text(draw, (380, 31), "map / tf / semantic route / waypoint array", FONT_SM, MUTED)
    _round_rect(draw, (940, 23, 1035, 49), 13, (6, 78, 59), (45, 212, 191), 1)
    _text(draw, (987, 29), "live", FONT_BOLD, (167, 243, 208), "ma")
    _text(draw, (1060, 29), f"t={t_sec:04.1f}s", FONT_MONO, CYAN)
    seg = min(int(st.progress), len(st.route) - 1) if st.route else 0
    _text(draw, (1145, 29), f"turn {st.turn} · wp {seg + 1}/{len(st.waypoints)}", FONT_MONO, AMBER)


def _draw_map(draw, graph, st: FrameState) -> tuple[tuple[float, float], int]:
    _draw_panel(draw, MAP_BOX, "3D/map view: escape facility + robot pose")
    x0, _, x1, _ = MAP_BOX

    for floor, band in FLOOR_BAND.items():
        y_low = band * FLOOR_DY - 4.8
        y_high = band * FLOOR_DY + 4.8
        _, top = _map_world_xy(0, y_high)
        _, bottom = _map_world_xy(0, y_low)
        fill = PANEL_2 if band % 2 else PANEL_3
        _round_rect(draw, (x0 + 18, top, x1 - 18, bottom), 9, fill, (71, 85, 105), 1)
        label = {-1: "B1", 1: "1F", 2: "2F", 3: "3F"}[floor]
        _text(draw, (x0 + 32, top + 9), f"floor {label}", FONT_BOLD, MUTED)

    route = st.route
    segment = min(int(st.progress), len(route) - 2) if len(route) >= 2 else 0
    local = st.progress - segment if len(route) >= 2 else 0.0

    for edge in graph.edges():
        a = _map_xy(graph.get_node(edge.source))
        b = _map_xy(graph.get_node(edge.target))
        if not _edge_open(graph, edge, st.world):
            if edge.type == "restricted":
                _line(draw, a, b, fill=(*PINK, 150), width=2, dash=5)
            elif edge.properties.get("lock"):
                _line(draw, a, b, fill=(*RED, 180), width=2, dash=7)
            else:
                _line(draw, a, b, fill=(*ORANGE, 160), width=2, dash=7)
        elif edge.type == "elevator_connection":
            _line(draw, a, b, fill=(*AMBER, 140), width=3, dash=8)
        elif edge.type in {"stairs_up", "stairs_down"}:
            _line(draw, a, b, fill=(*ORANGE, 110), width=2, dash=6)
        else:
            _line(draw, a, b, fill=(*MUTED, 130), width=2)

    if len(route) >= 2:
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

    route_set = set(route)
    for node in graph.nodes():
        x, y = _map_xy(node)
        color = NODE_COLORS.get(node.type, BLUE)
        r = 8 if node.id in route_set else 6
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(*color, 240), outline=(3, 7, 18), width=2)
        if node.id in {DECOY_EXIT, TRUE_EXIT, "holding_cell", "control_room"}:
            _round_rect(draw, (x - 58, y - 29, x + 58, y - 12), 7, (3, 7, 18, 220), (*color, 190), 1)
            _text(draw, (x, y - 27), node.label[:16], FONT_XS, TEXT, "ma")

    if len(route) >= 2:
        robot = _partial(_map_xy(graph.get_node(route[segment])), _map_xy(graph.get_node(route[segment + 1])), local)
    else:
        robot = _map_xy(graph.get_node(st.world.location))
        segment = 0

    rx, ry = robot
    draw.ellipse((rx - 23, ry - 23, rx + 23, ry + 23), fill=(*CYAN, 38))
    draw.ellipse((rx - 15, ry - 15, rx + 15, ry + 15), fill=(8, 47, 73), outline=CYAN, width=3)
    draw.ellipse((rx - 5, ry - 5, rx + 5, ry + 5), fill=(255, 255, 255))
    _text(draw, (rx + 22, ry - 7), "/tf base_link", FONT_XS, CYAN)
    return robot, segment


def _message_for_topic(topic: str, graph, st: FrameState, robot, segment: int) -> dict[str, Any]:
  node = graph.get_node(st.route[min(segment, len(st.route) - 1)])
  wp = st.waypoints[min(segment, len(st.waypoints) - 1)]
  if topic == "/tf":
      return {
          "frame_id": "map",
          "child_frame_id": "base_link",
          "semantic_node": node.id,
          "screen_xy": [round(robot[0], 1), round(robot[1], 1)],
      }
  if topic == "/semantic_toponav/route":
      return {"turn": st.turn, "path": st.route, "goal": st.route[-1]}
  if topic == "/semantic_toponav/waypoints":
      return {"current": wp.to_dict(), "count": len(st.waypoints), "schema": "SemanticWaypointArray"}
  if topic == "/semantic_toponav/resolve_trace" and st.resolve_payload:
      return st.resolve_payload
  if topic == "/semantic_toponav/event_log":
      return {"events": st.events[-6:]}
  return {"topic": topic}


def _draw_topics(draw, graph, st: FrameState, robot, segment: int, t: float):
    _draw_panel(draw, TOPIC_BOX, "topics")
    selected = TOPICS[st.topic_idx % len(TOPICS)]
    x0, y0, _, _ = TOPIC_BOX
    y = y0 + 45
    for topic in TOPICS:
        active = topic == selected
        color = CYAN if active else MUTED
        fill = (8, 47, 73) if active else (10, 21, 40)
        _round_rect(draw, (x0 + 14, y, x0 + 398, y + 30), 8, fill, (51, 65, 85), 1)
        draw.ellipse((x0 + 26, y + 10, x0 + 36, y + 20), fill=color)
        hz = "18 Hz" if topic == "/tf" else "on event" if "event" in topic else "1 msg"
        _text(draw, (x0 + 48, y + 8), topic, FONT_MONO, TEXT if active else MUTED)
        _text(draw, (x0 + 320, y + 8), hz, FONT_XS, color)
        y += 39

    _draw_panel(draw, MSG_BOX, f"message inspector: {selected}")
    msg = _message_for_topic(selected, graph, st, robot, segment)
    y = MSG_BOX[1] + 39
    for line in json.dumps(msg, ensure_ascii=True, indent=2).splitlines()[:8]:
        _text(draw, (MSG_BOX[0] + 14, y), line, FONT_MONO_XS, TEXT if ":" in line else MUTED)
        y += 14


def _draw_timeline(draw, st: FrameState, t: float):
    _draw_panel(draw, TIMELINE_BOX, "timeline / route progress")
    x0, y0, x1, _ = TIMELINE_BOX
    route = st.route
    if len(route) < 2:
        _text(draw, (x0 + 42, y0 + 60), "planner idle", FONT_MONO, MUTED)
        return
    progress = st.progress / (len(route) - 1)
    base_y = y0 + 90
    left, right = x0 + 42, x1 - 42
    draw.line([(left, base_y), (right, base_y)], fill=(*DIM, 255), width=4)
    for idx, node_id in enumerate(route):
        x = left + (right - left) * idx / (len(route) - 1)
        active = idx <= st.progress
        color = GREEN if active else DIM
        draw.ellipse((x - 7, base_y - 7, x + 7, base_y + 7), fill=color)
        short = node_id.replace("_", " ")[:9]
        _text(draw, (x, base_y + 18), short, FONT_XS, TEXT if active else MUTED, "ma")
    rx = left + (right - left) * progress
    draw.rectangle((left, y0 + 47, rx, y0 + 56), fill=PINK)
    draw.rectangle((rx, y0 + 47, right, y0 + 56), fill=(51, 65, 85))
    _text(draw, (left, y0 + 24), f"playhead {t:04.1f}s", FONT_MONO, CYAN)
    _text(draw, (right, y0 + 24), f"turn {st.turn}", FONT_MONO, MUTED, "ra")


def _draw_status(draw, st: FrameState, segment: int, t: float):
    _draw_panel(draw, STATUS_BOX, "semantic waypoint array")
    x0, y0, _, _ = STATUS_BOX
    y = y0 + 44
    for idx, wp in enumerate(st.waypoints[:7]):
        active = idx == min(segment, len(st.waypoints) - 1)
        done = idx < segment
        color = AMBER if active else GREEN if done else DIM
        fill = (67, 56, 24) if active else (10, 21, 40)
        _round_rect(draw, (x0 + 14, y, x0 + 398, y + 25), 7, fill, (51, 65, 85), 1)
        draw.ellipse((x0 + 25, y + 8, x0 + 34, y + 17), fill=color)
        instr = wp.instruction if len(wp.instruction) <= 42 else wp.instruction[:39] + "..."
        _text(draw, (x0 + 45, y + 6), f"{idx + 1}. {instr}", FONT_XS, TEXT if active else MUTED)
        y += 30
    inv = sum(1 for i in ITEMS if i in st.world.items)
    _round_rect(draw, (x0 + 14, y0 + 251, x0 + 398, y0 + 275), 7, (5, 46, 22), (34, 197, 94), 1)
    _text(draw, (x0 + 28, y0 + 257), f"inventory {inv}/{len(ITEMS)} · riddles {len(st.world.solved)}/{len(RIDDLES)}",
          FONT_MONO_XS, (187, 247, 208))
    _text(draw, (x0 + 278, y0 + 257), f"latency={14 + int(t) % 5}ms", FONT_MONO_XS, (187, 247, 208))


def _render_frame(graph, st: FrameState, frame_idx: int) -> Image.Image:
    t = frame_idx / FPS
    img = Image.new("RGBA", (W, H), BG)
    draw = ImageDraw.Draw(img, "RGBA")
    _draw_background(draw)
    robot, segment = _draw_map(draw, graph, st)
    _draw_top_bar(draw, st, t)
    _draw_topics(draw, graph, st, robot, segment, t)
    _draw_timeline(draw, st, t)
    _draw_status(draw, st, segment, t)
    if st.banner:
        _round_rect(draw, (440, 230, 840, 300), 15, (4, 10, 24, 230), (245, 158, 11, 255), 2)
        _text(draw, (640, 248), st.banner, FONT_TITLE, (255, 255, 255), "ma")
        if st.banner_sub:
            _text(draw, (640, 278), st.banner_sub, FONT_BOLD, (253, 230, 138), "ma")
    return img.convert("RGB")


def _optimize_gif(path: Path) -> None:
    if shutil.which("ffmpeg") is None:
        return
    tmp = path.with_suffix(".opt.gif")
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(path),
         "-lavfi", f"fps={FPS},split[s0][s1];[s0]palettegen=stats_mode=diff:max_colors=96[p];"
         "[s1][p]paletteuse=dither=bayer:bayer_scale=4", str(tmp)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    tmp.replace(path)


def _write_mp4(frames: list[Image.Image]) -> None:
    if shutil.which("ffmpeg") is None:
        return
    with tempfile.TemporaryDirectory(prefix="escape-sim-") as tmp:
        tmp_path = Path(tmp)
        for idx, frame in enumerate(frames):
            frame.save(tmp_path / f"frame_{idx:04d}.png")
        subprocess.run(
            ["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(tmp_path / "frame_%04d.png"),
             "-vf", "format=yuv420p", "-movflags", "+faststart", str(OUT_MP4)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print(f"wrote {OUT_MP4.relative_to(ROOT)}")


def main() -> None:
    graph = load_graph(GRAPH_PATH)
    timeline = _build_timeline(graph)
    frames = [_render_frame(graph, st, i) for i, st in enumerate(timeline)]

    OUT_GIF.parent.mkdir(parents=True, exist_ok=True)
    palette = [f.convert("P", palette=Image.ADAPTIVE, colors=128) for f in frames]
    palette[0].save(OUT_GIF, save_all=True, append_images=palette[1:],
                    duration=FRAME_MS, loop=0, optimize=True, disposal=2)
    _optimize_gif(OUT_GIF)
    _write_mp4(frames)
    print(f"wrote {OUT_GIF.relative_to(ROOT)} ({OUT_GIF.stat().st_size / 1024:.0f} KB, "
          f"{len(frames)} frames @ {FPS} fps)")


if __name__ == "__main__":
    main()
