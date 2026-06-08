"""Record the Robot Escape Room as a Foxglove/RViz-style live simulation GIF.

Unlike ``record_escape_room.py`` (three-panel analytics hero), this renders a
single **simulation dashboard**: stacked-floor map, smooth ``/tf`` robot motion
along real A* legs, mission HUD, inventory, and a scrolling event log. Every
route and puzzle outcome comes from ``robot_escape_room.py`` — no second game
logic.

    python examples/record_escape_room_sim.py

Writes ``docs/images/robot_escape_room.gif`` (overwrites the README hero).
The three-panel version is still available via ``record_escape_room.py`` →
``docs/images/robot_escape_room_panels.gif``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

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

game.VERBOSE = False

ROOT = Path(__file__).resolve().parents[1]
GRAPH_PATH = Path(__file__).parent / "robot_escape_room.yaml"
OUT_GIF = ROOT / "docs" / "images" / "robot_escape_room.gif"
OUT_MP4 = ROOT / "docs" / "images" / "robot_escape_room.mp4"

W, H = 960, 540
FPS = 12
FRAME_MS = int(1000 / FPS)
FRAMES_PER_HOP = 3
HOLD_FRAMES = 5
INTRO_FRAMES = 8
TWIST_HOLD = 8
ESCAPE_HOLD = 10

FLOOR_DY = 9.0
FLOOR_BAND = {-1: 0, 1: 1, 2: 2, 3: 3}
FLOOR_LABEL = {-1: "B1", 1: "1F", 2: "2F", 3: "3F"}

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

MAP_BOX = (12.0, 48.0, 676.0, 392.0)
HUD_BOX = (688.0, 48.0, 948.0, 188.0)
LOG_BOX = (688.0, 198.0, 948.0, 392.0)
TIMELINE_BOX = (12.0, 404.0, 948.0, 528.0)

X_MIN, X_MAX = -2.0, 30.0
Y_MIN, Y_MAX = -10.0, 38.0

NODE_COLORS = {
    "room": BLUE,
    "corridor": MUTED,
    "intersection": PURPLE,
    "stairs": ORANGE,
    "exit": GREEN,
    "sealed_exit": DIM,
}


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
class Keyframe:
    world: World
    path: list[str] | None
    progress: float
    turn: int | None
    mission: str
    subcaption: str
    events: list[str] = field(default_factory=list)
    banner: str | None = None


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


def _map_xy(node) -> tuple[float, float]:
    x, y = _world_xy(node)
    x0, y0, x1, y1 = MAP_BOX
    px = x0 + 28 + (x - X_MIN) / (X_MAX - X_MIN) * (x1 - x0 - 56)
    py = y1 - 28 - (y - Y_MIN) / (Y_MAX - Y_MIN) * (y1 - y0 - 56)
    return px, py


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


def _path_edges(path: list[str]) -> set[tuple[str, str]]:
    return set(zip(path, path[1:], strict=False))


def _build_timeline(graph) -> list[Keyframe]:
    world = World()
    events = ["[boot] T-0 online — Holding Cell"]
    timeline: list[Keyframe] = [
        Keyframe(
            world, None, 0.0, None,
            "ROBOT ESCAPE ROOM",
            "Lockdown active. EMERGENCY EXIT sign points to Floor 3…",
            list(events),
        ),
    ]

    def hold(kf: Keyframe, n: int) -> None:
        timeline.extend([kf] * n)

    hold(timeline[-1], INTRO_FRAMES)

    twist_seen = False
    for turn in range(1, 50):
        exit_path = plan(graph, world, TRUE_EXIT)
        if exit_path is not None:
            mission = "ESCAPE — sublevel tunnel open"
            sub = "Route plunges past the sealed Floor-3 sign"
            _append_motion(timeline, graph, world, exit_path, turn, mission, sub, events)
            kf = Keyframe(
                world, exit_path, len(exit_path) - 1, turn,
                "FREEDOM", "Maintenance Exit (B1) — not the Floor-3 decoy",
                events + ["[escape] T-0 cleared the sublevel hatch"],
                banner="ESCAPED",
            )
            hold(kf, ESCAPE_HOLD)
            break

        opts = objectives(graph, world)
        if not opts:
            timeline.append(Keyframe(world, None, 0.0, turn, "STUCK", "No reachable objective", events))
            break

        _, node, kind, path = opts[0]
        label = graph.get_node(node).label
        mission = f"Turn {turn}: investigate {label}" if kind.startswith("riddle") else f"Turn {turn}: reach {label}"
        sub = "Replanning on live block_edges / avoid_restricted / prefer_elevator stack"
        _append_motion(timeline, graph, world, path, turn, mission, sub, events)

        items_before = set(world.items)
        solved_before = set(world.solved)
        world.location = node
        arrive(graph, world, node)

        for item in sorted(world.items - items_before):
            events.append(f"[item] picked up {item}")
        for rid in sorted(world.solved - solved_before):
            events.append(f"[riddle] solved {rid}")

        hold(Keyframe(
            world, path, len(path) - 1, turn, mission, "Objective complete — world state updated", list(events),
        ), HOLD_FRAMES)

        if not twist_seen and "riddle_3" in world.solved:
            twist_seen = True
            decoy = graph.get_node(DECOY_EXIT).label
            events.append(f"[twist] {decoy} is welded shut — real exit is sublevel")
            hold(Keyframe(
                world, None, 0.0, turn,
                "PLOT TWIST", "The lit exit was a decoy. Hatch code acquired.",
                list(events), banner="DECOY EXIT",
            ), TWIST_HOLD)

    return timeline


def _append_motion(
    timeline: list[Keyframe],
    graph,
    world: World,
    path: list[str],
    turn: int,
    mission: str,
    sub: str,
    events: list[str],
) -> None:
    if len(path) < 2:
        timeline.append(Keyframe(world, path, 0.0, turn, mission, sub, list(events)))
        return
    for hop in range(len(path) - 1):
        for step in range(FRAMES_PER_HOP):
            t = _ease(step / FRAMES_PER_HOP)
            timeline.append(Keyframe(
                world, path, hop + t, turn, mission, sub, list(events),
            ))


def _draw_background(draw: ImageDraw.ImageDraw) -> None:
    draw.rectangle((0, 0, W, H), fill=BG)
    for x in range(-120, W + 120, 44):
        draw.line([(x, 0), (x - 150, H)], fill=(*GRID, 42), width=1)
    for y in range(0, H, 44):
        draw.line([(0, y), (W, y)], fill=(*GRID, 28), width=1)


def _draw_top_bar(draw, kf: Keyframe, t_sec: float) -> None:
    box = (12.0, 8.0, 948.0, 40.0)
    _round_rect(draw, box, 10, (10, 21, 40), (51, 65, 85), 1)
    _text(draw, (34, 24), "Robot Escape Room · semantic-toponav", FONT_TITLE, TEXT)
    _text(draw, (430, 28), "live simulation / map · tf · semantic route", FONT_SM, MUTED)
    _round_rect(draw, (748, 14, 820, 34), 10, (6, 78, 59), (45, 212, 191), 1)
    _text(draw, (784, 18), "SIM", FONT_BOLD, (167, 243, 208), "ma")
    _text(draw, (838, 18), f"t={t_sec:05.1f}s", FONT_MONO, CYAN)
    turn = kf.turn if kf.turn is not None else "—"
    _text(draw, (920, 18), f"turn {turn}", FONT_MONO, AMBER, "ra")


def _draw_map(draw, graph, kf: Keyframe) -> tuple[float, float]:
    _round_rect(draw, MAP_BOX, 12, PANEL, (51, 65, 85), 1)
    x0, y0, x1, _ = MAP_BOX
    draw.rectangle((round(x0), round(y0), round(x1), round(y0 + 28)), fill=(9, 17, 31))
    _text(draw, (x0 + 14, y0 + 7), "map / tf — stacked facility topology", FONT_SM, TEXT)

    x0m, y0m, x1m, y1m = MAP_BOX
    for floor, band in FLOOR_BAND.items():
        y_low = band * FLOOR_DY - 4.5
        y_high = band * FLOOR_DY + 5.5
        py_top = y1m - 28 - (y_high - Y_MIN) / (Y_MAX - Y_MIN) * (y1m - y0m - 56)
        py_bot = y1m - 28 - (y_low - Y_MIN) / (Y_MAX - Y_MIN) * (y1m - y0m - 56)
        fill = PANEL_2 if band % 2 else PANEL_3
        _round_rect(draw, (x0m + 14, py_top, x1m - 14, py_bot), 8, fill, (71, 85, 105), 1)
        _text(draw, (x0m + 26, py_top + 7), FLOOR_LABEL[floor], FONT_BOLD, MUTED)

    route_pairs = _path_edges(kf.path) if kf.path else set()
    progress = kf.progress if kf.path else 0.0

    for edge in graph.edges():
        if edge.source not in {n.id for n in graph.nodes()}:
            continue
        a = _map_xy(graph.get_node(edge.source))
        b = _map_xy(graph.get_node(edge.target))
        pair = (edge.source, edge.target)
        rev = (edge.target, edge.source)
        on_route = pair in route_pairs or rev in route_pairs

        if not _edge_open(graph, edge, kf.world):
            if edge.type == "restricted":
                _line(draw, a, b, fill=(*PINK, 150), width=2, dash=5)
            elif edge.properties.get("lock"):
                _line(draw, a, b, fill=(*RED, 180), width=2, dash=7)
            else:
                _line(draw, a, b, fill=(*ORANGE, 160), width=2, dash=7)
        elif edge.type == "elevator_connection":
            _line(draw, a, b, fill=(*AMBER, 200 if on_route else 110), width=3 if on_route else 2, dash=6)
        elif edge.type in {"stairs_up", "stairs_down"}:
            _line(draw, a, b, fill=(*ORANGE, 180 if on_route else 100), width=2, dash=5)
        elif on_route:
            _line(draw, a, b, fill=(*CYAN, 255), width=4)
        else:
            _line(draw, a, b, fill=(*MUTED, 120), width=2)

    if kf.path and len(kf.path) >= 2:
        seg = min(int(progress), len(kf.path) - 2)
        local = progress - seg
        for idx, (a_id, b_id) in enumerate(zip(kf.path[:-1], kf.path[1:], strict=False)):
            a = _map_xy(graph.get_node(a_id))
            b = _map_xy(graph.get_node(b_id))
            if idx < seg:
                _line(draw, a, b, fill=(*GREEN, 255), width=5)
            elif idx == seg:
                mid = _partial(a, b, local)
                _line(draw, a, mid, fill=(*GREEN, 255), width=5)
                _line(draw, mid, b, fill=(*GREEN, 70), width=2, dash=6)

    for node in graph.nodes():
        x, y = _map_xy(node)
        color = NODE_COLORS.get(node.type, BLUE)
        r = 7 if node.id == kf.world.location else 5
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(*color, 240), outline=(3, 7, 18), width=2)
        if node.id in {DECOY_EXIT, TRUE_EXIT, kf.world.location}:
            _text(draw, (x, y - 16), node.label[:18], FONT_XS, TEXT, "ma")

    if kf.path and len(kf.path) >= 2:
        seg = min(int(progress), len(kf.path) - 2)
        local = progress - seg
        a = _map_xy(graph.get_node(kf.path[seg]))
        b = _map_xy(graph.get_node(kf.path[seg + 1]))
        rx, ry = _partial(a, b, local)
    else:
        rx, ry = _map_xy(graph.get_node(kf.world.location))

    draw.ellipse((rx - 22, ry - 22, rx + 22, ry + 22), fill=(*CYAN, 40))
    draw.ellipse((rx - 14, ry - 14, rx + 14, ry + 14), fill=(8, 47, 73), outline=CYAN, width=3)
    draw.ellipse((rx - 4, ry - 4, rx + 4, ry + 4), fill=(255, 255, 255))
    _text(draw, (rx + 18, ry - 6), "T-0 /tf", FONT_XS, CYAN)
    return rx, ry


def _draw_hud(draw, kf: Keyframe) -> None:
    _round_rect(draw, HUD_BOX, 12, PANEL, (51, 65, 85), 1)
    x0, y0, _, _ = HUD_BOX
    draw.rectangle((round(x0), round(y0), round(HUD_BOX[2]), round(y0 + 28)), fill=(9, 17, 31))
    _text(draw, (x0 + 14, y0 + 7), "mission + inventory", FONT_SM, TEXT)
    y = y0 + 40
    _text(draw, (x0 + 14, y), kf.mission, FONT_BOLD, AMBER)
    y += 22
    for line in kf.subcaption[:2]:
        _text(draw, (x0 + 14, y), line, FONT_XS, MUTED)
        y += 16
    y += 6
    _text(draw, (x0 + 14, y), "inventory", FONT_XS, DIM)
    y += 16
    for item in ITEMS:
        if item in kf.world.items:
            mark, color = "[x]", GREEN
        elif item in kf.world.known:
            mark, color = "[ ]", TEXT
        else:
            mark, color = "[?]", DIM
        _text(draw, (x0 + 14, y), f"{mark} {item}", FONT_MONO_XS, color)
        y += 14
    _text(draw, (x0 + 14, y + 4), f"riddles {len(kf.world.solved)}/{len(RIDDLES)}", FONT_MONO_XS, MUTED)


def _draw_log(draw, kf: Keyframe, robot_xy: tuple[float, float]) -> None:
    _round_rect(draw, LOG_BOX, 12, PANEL, (51, 65, 85), 1)
    x0, y0, _, _ = LOG_BOX
    draw.rectangle((round(x0), round(y0), round(LOG_BOX[2]), round(y0 + 28)), fill=(9, 17, 31))
    _text(draw, (x0 + 14, y0 + 7), "event log", FONT_SM, TEXT)
    y = y0 + 40
    for line in kf.events[-9:]:
        color = CYAN if line.startswith("[boot]") else GREEN if "[escape]" in line else AMBER if "[twist]" in line else TEXT
        _text(draw, (x0 + 14, y), line[:44], FONT_MONO_XS, color)
        y += 15
    _round_rect(draw, (x0 + 14, LOG_BOX[3] - 78, LOG_BOX[2] - 14, LOG_BOX[3] - 14), 8, (10, 21, 40), (51, 65, 85), 1)
    payload = {
        "frame_id": "map",
        "child_frame_id": "base_link",
        "semantic_node": kf.world.location,
        "screen_xy": [round(robot_xy[0], 1), round(robot_xy[1], 1)],
    }
    _text(draw, (x0 + 22, LOG_BOX[3] - 68), "/tf", FONT_MONO_XS, CYAN)
    for i, line in enumerate(json.dumps(payload, indent=2).splitlines()[:3]):
        _text(draw, (x0 + 22, LOG_BOX[3] - 52 + i * 13), line, FONT_MONO_XS, MUTED)


def _draw_timeline(draw, kf: Keyframe, t_sec: float) -> None:
    _round_rect(draw, TIMELINE_BOX, 12, PANEL, (51, 65, 85), 1)
    x0, y0, x1, _ = TIMELINE_BOX
    draw.rectangle((round(x0), round(y0), round(x1), round(y0 + 28)), fill=(9, 17, 31))
    _text(draw, (x0 + 14, y0 + 7), "current A* leg / route progress", FONT_SM, TEXT)
    if not kf.path or len(kf.path) < 2:
        _text(draw, (x0 + 20, y0 + 52), "awaiting planner…", FONT_MONO, MUTED)
        return
    base_y = y0 + 88
    left, right = x0 + 36, x1 - 36
    draw.line([(left, base_y), (right, base_y)], fill=(*DIM, 255), width=4)
    prog = kf.progress / (len(kf.path) - 1)
    for idx, node_id in enumerate(kf.path):
        x = left + (right - left) * idx / (len(kf.path) - 1)
        active = idx <= kf.progress
        color = GREEN if active else DIM
        draw.ellipse((x - 6, base_y - 6, x + 6, base_y + 6), fill=color)
        short = node_id.replace("_", " ")[:10]
        _text(draw, (x, base_y + 16), short, FONT_XS, TEXT if active else MUTED, "ma")
    rx = left + (right - left) * prog
    draw.rectangle((left, y0 + 48, rx, y0 + 56), fill=CYAN)
    draw.rectangle((rx, y0 + 48, right, y0 + 56), fill=(51, 65, 85))
    _text(draw, (left, y0 + 34), f"leg {kf.progress:.1f}/{len(kf.path) - 1}", FONT_MONO_XS, CYAN)


def _render_frame(graph, kf: Keyframe, frame_idx: int) -> Image.Image:
    t_sec = frame_idx / FPS
    img = Image.new("RGBA", (W, H), BG)
    draw = ImageDraw.Draw(img, "RGBA")
    _draw_background(draw)
    _draw_top_bar(draw, kf, t_sec)
    robot_xy = _draw_map(draw, graph, kf)
    _draw_hud(draw, kf)
    _draw_log(draw, kf, robot_xy)
    _draw_timeline(draw, kf, t_sec)
    if kf.banner:
        alpha = 230
        _round_rect(draw, (330, 220, 630, 278), 12, (4, 10, 24, alpha), (245, 158, 11, alpha), 2)
        _text(draw, (480, 236), kf.banner, FONT_TITLE, (255, 255, 255, alpha), "ma")
        _text(draw, (480, 262), kf.subcaption[:40], FONT_SM, (253, 230, 138, alpha), "ma")
    return img.convert("RGB")


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
    frames = [_render_frame(graph, kf, i) for i, kf in enumerate(timeline)]

    OUT_GIF.parent.mkdir(parents=True, exist_ok=True)
    palette_frames = [f.convert("P", palette=Image.ADAPTIVE, colors=128) for f in frames]
    palette_frames[0].save(
        OUT_GIF, save_all=True, append_images=palette_frames[1:],
        duration=FRAME_MS, loop=0, optimize=True, disposal=2,
    )
    _write_mp4(frames)
    size_kb = OUT_GIF.stat().st_size / 1024
    print(f"wrote {OUT_GIF.relative_to(ROOT)} ({size_kb:.0f} KB, {len(frames)} frames @ {FPS} fps)")


if __name__ == "__main__":
    main()
