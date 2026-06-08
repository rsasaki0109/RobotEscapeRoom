"""Export the Robot Escape Room as a Foxglove 3D replay MCAP.

Drives the full escape-game timeline from ``semantic_toponav.escape_room``
(every route is a real A* plan) and writes stacked-floor 3D scene data suitable
for Gazebo/RViz-style replay in Foxglove / Lichtblick.

    pip install -e '.[foxglove]'
    PYTHONPATH=. python3 examples/export_escape_room_foxglove_mcap.py

Writes ``docs/foxglove/robot_escape_room_demo.mcap``.
Regenerate the README hero with ``scripts/foxglove_hero/build_escape_room_gif.sh``.
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from mcap.writer import CompressionType, Writer
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Install the Foxglove extra first: pip install -e '.[foxglove]'") from exc

from semantic_toponav.escape_room.runner import (
    ITEMS,
    POWER_ITEM,
    RIDDLES,
    TRUE_EXIT,
    World,
    complete_navigation,
    next_turn,
)
from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.waypoint import path_to_semantic_waypoints

import export_foxglove_mcap as fx
from escape_room_interior import foxglove_furnished_cubes

HERE = Path(__file__).parent
ROOT = HERE.parent
GRAPH_PATH = HERE / "robot_escape_room.yaml"
OUTPUT_PATH = ROOT / "docs/foxglove/robot_escape_room_demo.mcap"
TIMELINE_PATH = ROOT / "docs/foxglove/robot_escape_room_timeline.json"

HZ = 12
FRAMES_PER_HOP = 5
HOLD_FRAMES = 4
TWIST_HOLD = 6
ESCAPE_HOLD = 8
FLOOR_HEIGHT_M = 4.2
FLOOR_LABEL = {-1: "B1", 1: "1F", 2: "2F", 3: "3F"}
UNPOWERED_TYPES = ("unpowered",)

STATUS_SCHEMA = {
    "type": "object",
    "properties": {
        "turn": {"type": "integer"},
        "caption": {"type": "string"},
        "detail": {"type": "string"},
        "events": {"type": "array", "items": {"type": "string"}},
    },
}

NODE_COLORS = {
    "room": (0.31, 0.62, 0.96, 1.0),
    "corridor": (0.58, 0.64, 0.72, 1.0),
    "intersection": (0.66, 0.40, 0.96, 1.0),
    "stairs": (0.96, 0.62, 0.08, 1.0),
    "exit": (0.22, 0.83, 0.45, 1.0),
    "sealed_exit": (0.35, 0.40, 0.48, 1.0),
}


@dataclass
class TimelineFrame:
    items: frozenset[str]
    location: str
    route: list[str]
    progress: float
    turn: int
    caption: str
    detail: str
    events: list[str] = field(default_factory=list)


def _snapshot(
    world: World,
    route: list[str],
    progress: float,
    turn: int,
    caption: str,
    detail: str,
    events: list[str],
) -> TimelineFrame:
    return TimelineFrame(
        frozenset(world.items),
        world.location,
        list(route),
        progress,
        turn,
        caption,
        detail,
        list(events),
    )


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)


def _floor(node: Any) -> int:
    return int(node.properties.get("floor", 1))


def _node_xyz(graph: Any, node_id: str) -> tuple[float, float, float]:
    node = graph.get_node(node_id)
    z = (_floor(node) - 1) * FLOOR_HEIGHT_M
    if node.pose is None:
        return 0.0, 0.0, z
    return node.pose.x, node.pose.y, z


def _edge_open(graph: Any, edge: Any, items: frozenset[str]) -> bool:
    lock = edge.properties.get("lock")
    if lock and lock not in items:
        return False
    if edge.type in UNPOWERED_TYPES and POWER_ITEM not in items:
        return False
    if edge.type == "restricted":
        return False
    return True


def _floor_rect(graph: Any, floor: int) -> list[tuple[float, float, float]]:
    xs, ys = [], []
    for node in graph.nodes():
        if _floor(node) != floor:
            continue
        xs.append(node.pose.x)
        ys.append(node.pose.y)
    if not xs:
        return []
    pad = 2.0
    z = (floor - 1) * FLOOR_HEIGHT_M - 0.04
    return [
        (min(xs) - pad, min(ys) - pad, z),
        (max(xs) + pad, min(ys) - pad, z),
        (max(xs) + pad, max(ys) + pad, z),
        (min(xs) - pad, max(ys) + pad, z),
    ]


def _turn_caption(graph: Any, turn_plan, events: list[str]) -> tuple[str, str]:
    evt = events[-1] if events else ""
    if "ESCAPED" in evt:
        return (
            "ESCAPED",
            "Maintenance Exit (B1) — Gazebo + Nav2 + AMCL · not the Floor-3 decoy",
        )
    if "twist" in evt.lower():
        return (
            "DECOY EXIT sealed",
            "Emergency Exit (3F) welded shut → replan to sublevel",
        )
    if evt.startswith("item:"):
        item_id = evt.split(":", 1)[1].strip()
        label = ITEMS.get(item_id, {}).get("label", item_id.replace("_", " "))
        return f"Collected {label}", "block_edges updated — door now open"
    if evt.startswith("riddle:"):
        rid = evt.split(":", 1)[1].strip()
        for node, spec in RIDDLES.items():
            if spec["id"] == rid:
                return (
                    f"Riddle solved @ {graph.get_node(node).label}",
                    "resolve_goal grounded the clue → new objective unlocked",
                )
        return "Riddle solved", "resolve_goal grounded the clue"
    if turn_plan.status == "exit":
        goal = graph.get_node(TRUE_EXIT).label
        return f"Final run → {goal}", "NavigateThroughPoses · continuous replan"
    if turn_plan.objective is not None:
        goal = graph.get_node(turn_plan.objective.node).label
        kind = "Investigate" if turn_plan.objective.kind == "riddle" else "Reach"
        return f"{kind} {goal}", turn_plan.status
    return "Replanning", "A* on live cost stack (no scripted path)"


def _build_timeline(graph: Any) -> list[TimelineFrame]:
    world = World()
    events = ["T-0 online — Holding Cell"]
    timeline: list[TimelineFrame] = []

    def push_motion(path: list[str], turn: int, caption: str, detail: str):
        if len(path) < 2:
            timeline.append(
                _snapshot(world, path or [world.location], 0.0, turn, caption, detail, events)
            )
            return
        for hop in range(len(path) - 1):
            for step in range(FRAMES_PER_HOP):
                timeline.append(
                    _snapshot(
                        world,
                        path,
                        hop + _ease(step / FRAMES_PER_HOP),
                        turn,
                        caption,
                        detail,
                        events,
                    )
                )

    def hold(state: TimelineFrame, n: int):
        timeline.extend([state] * n)

    for _ in range(49):
        turn_plan = next_turn(graph, world)
        caption, detail = _turn_caption(graph, turn_plan, events)

        if turn_plan.status == "exit":
            path = turn_plan.exit_path or []
            push_motion(path, turn_plan.turn, caption, detail)
            events.append("ESCAPED")
            hold(
                _snapshot(world, path, max(0.0, len(path) - 1), turn_plan.turn, caption, detail, events),
                ESCAPE_HOLD,
            )
            break

        if turn_plan.status == "stuck":
            break

        assert turn_plan.objective is not None
        path = turn_plan.objective.path
        push_motion(path, turn_plan.turn, caption, detail)

        items_before = set(world.items)
        solved_before = set(world.solved)
        arrival = complete_navigation(graph, world, turn_plan.objective.node)
        twist_hold = False
        for item in sorted(world.items - items_before):
            events.append(f"item: {item}")
        for rid in sorted(world.solved - solved_before):
            events.append(f"riddle: {rid}")
        for line in arrival.messages:
            if "Plot twist" in line:
                events.append("twist: Floor-3 exit sealed")
                twist_hold = True

        caption, detail = _turn_caption(graph, turn_plan, events)
        hold(
            _snapshot(world, path, len(path) - 1, turn_plan.turn, caption, detail, events),
            TWIST_HOLD if twist_hold else HOLD_FRAMES,
        )

    return timeline


def _static_scene(graph: Any, frame: TimelineFrame, timestamp_ns: int) -> dict[str, Any]:
    floors = sorted({_floor(n) for n in graph.nodes()})
    floor_lines = []
    for floor in floors:
        rect = _floor_rect(graph, floor)
        if rect:
            floor_lines.append(
                fx._line(rect, (0.22, 0.34, 0.52, 0.82), line_type=fx.LINE_LOOP, thickness=0.07)
            )

    edge_lines = []
    for edge in graph.edges():
        pts = [_node_xyz(graph, edge.source), _node_xyz(graph, edge.target)]
        if not _edge_open(graph, edge, frame.items):
            if edge.properties.get("lock"):
                color = (0.95, 0.34, 0.34, 0.55)
            elif edge.type == "restricted":
                color = (0.96, 0.22, 0.45, 0.55)
            else:
                color = (0.96, 0.62, 0.08, 0.55)
            width = 0.06
        elif edge.type == "elevator_connection":
            color = (0.96, 0.62, 0.08, 0.9)
            width = 0.11
        elif edge.type in {"stairs_up", "stairs_down"}:
            color = (0.96, 0.62, 0.08, 0.75)
            width = 0.08
        else:
            color = (0.62, 0.70, 0.82, 0.88)
            width = 0.10
        edge_lines.append(fx._line(pts, color, line_type=fx.LINE_LIST, thickness=width))

    route_set = set(frame.route)
    route_pts = [_node_xyz(graph, nid) for nid in frame.route]
    route_line = []
    if len(route_pts) >= 2:
        route_line = [fx._line(route_pts, (0.98, 0.28, 0.52, 1.0), thickness=0.20)]

    def _cube(center, size, color: tuple[float, float, float, float]) -> dict[str, Any]:
        cx, cy, cz = center
        sx, sy, sz = size
        return {
            "pose": fx._pose(cx, cy, cz),
            "size": fx._point(sx, sy, sz),
            "color": fx._color(*color),
        }

    cubes = [_cube(fg.center, fg.size, fg.rgba) for fg in foxglove_furnished_cubes(graph, route_set)]

    labels = [
        fx._text(
            (sum(p[0] for p in rect) / len(rect), rect[0][1] - 1.0, rect[0][2] + 0.35),
            f"FLOOR {FLOOR_LABEL.get(floor, floor)}",
            (0.95, 0.98, 1.0, 1.0),
            size=0.62,
        )
        for floor in floors
        if (rect := _floor_rect(graph, floor))
    ]
    for nid in ("holding_cell", "emergency_exit", "maintenance_exit", "control_room"):
        if graph.has_node(nid):
            x, y, z = _node_xyz(graph, nid)
            labels.append(fx._text((x, y + 0.75, z + 0.35), graph.get_node(nid).label, size=0.38))

    labels.append(fx._text((14.0, -10.5, 2.0), frame.caption, (1.0, 1.0, 1.0, 1.0), size=0.48))

    return {
        "deletions": [],
        "entities": [
            fx._entity(
                "escape_room_static",
                timestamp_ns,
                lines=[*floor_lines, *edge_lines, *route_line],
                cubes=cubes,
                texts=labels,
                metadata=[
                    {"key": "source", "value": "examples/robot_escape_room.yaml"},
                    {"key": "demo", "value": "robot_escape_room"},
                    {"key": "meshes", "value": "escape_room_interior.obj"},
                ],
            )
        ],
    }


def _robot_pose(
    graph: Any, route: list[str], progress: float
) -> tuple[tuple[float, float, float], int, list[tuple[float, float, float]]]:
    if len(route) < 2:
        xyz = _node_xyz(graph, route[0] if route else "holding_cell")
        return xyz, 0, [xyz]

    points = [_node_xyz(graph, nid) for nid in route]
    segment = min(int(progress), len(route) - 2)
    local = max(0.0, min(1.0, progress - segment))
    a, b = points[segment], points[segment + 1]
    xyz = (
        a[0] + (b[0] - a[0]) * local,
        a[1] + (b[1] - a[1]) * local,
        a[2] + (b[2] - a[2]) * local,
    )
    traveled = [*points[: segment + 1], xyz]
    return xyz, segment, traveled


def _dynamic_scene(
    graph: Any, frame: TimelineFrame, timestamp_ns: int
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], int]:
    robot_xyz, segment_idx, traveled = _robot_pose(graph, frame.route, frame.progress)
    node_idx = min(segment_idx, len(frame.route) - 1)
    next_idx = min(segment_idx + 1, len(frame.route) - 1)
    pts = [_node_xyz(graph, nid) for nid in frame.route]
    yaw = fx._yaw_between(pts[segment_idx], pts[next_idx], 0.0) if len(pts) >= 2 else 0.0
    pose = fx._pose(*robot_xyz, yaw=yaw)

    scene = {
        "deletions": [],
        "entities": [
            fx._entity(
                "base_link_robot",
                timestamp_ns,
                spheres=[
                    fx._sphere(robot_xyz, (0.13, 0.83, 0.93, 0.45), diameter=1.35),
                    fx._sphere(robot_xyz, (0.13, 0.83, 0.93, 1.0), diameter=0.62),
                    fx._sphere(robot_xyz, (1.0, 1.0, 1.0, 1.0), diameter=0.18),
                ],
                lines=[fx._line(traveled, (0.45, 0.98, 1.0, 1.0), thickness=0.28)],
            )
        ],
    }
    tf = {
        "transforms": [{
            "timestamp": fx._timestamp(timestamp_ns),
            "parent_frame_id": "map",
            "child_frame_id": "base_link",
            "translation": fx._point(*robot_xyz),
            "rotation": pose["orientation"],
        }]
    }
    pose_msg = {"timestamp": fx._timestamp(timestamp_ns), "frame_id": "map", "pose": pose}
    return scene, tf, pose_msg, node_idx


def _write_mcap(graph: Any, timeline: list[TimelineFrame]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    t0 = fx.START_TIME_NS
    frame_count = len(timeline)

    with OUTPUT_PATH.open("wb") as stream:
        writer = Writer(stream, compression=CompressionType.NONE)
        writer.start(profile="foxglove")
        channels = fx._register_channels(writer)
        status_schema = writer.register_schema(
            "semantic_toponav.EscapeRoomStatus", "jsonschema", fx._json_bytes(STATUS_SCHEMA)
        )
        status_channel = writer.register_channel(
            "/semantic_toponav/escape_room/status",
            "json",
            status_schema,
        )
        writer.add_metadata("robot_escape_room", {
            "demo": "robot_escape_room",
            "frames": str(frame_count),
            "source_graph": str(GRAPH_PATH.relative_to(ROOT)),
        })

        for frame_idx, frame in enumerate(timeline):
            timestamp_ns = t0 + round(frame_idx * 1_000_000_000 / HZ)
            waypoints = path_to_semantic_waypoints(graph, frame.route)
            static = _static_scene(graph, frame, timestamp_ns)
            dynamic, tf, pose, node_idx = _dynamic_scene(graph, frame, timestamp_ns)

            fx._write_message(writer, channels["/semantic_toponav/scene"], timestamp_ns, static)
            fx._write_message(writer, channels["/semantic_toponav/scene"], timestamp_ns, dynamic)
            fx._write_message(writer, channels["/tf"], timestamp_ns, tf)
            fx._write_message(writer, channels["/semantic_toponav/pose"], timestamp_ns, pose)
            fx._write_message(writer, channels["/semantic_toponav/route"], timestamp_ns, {
                "start": frame.route[0],
                "goal": frame.route[-1],
                "path": frame.route,
                "policy": "A* + escape-room cost stack",
                "edge_count": max(0, len(frame.route) - 1),
            })
            fx._write_message(writer, channels["/semantic_toponav/waypoints"], timestamp_ns, {
                "timestamp": fx._timestamp(timestamp_ns),
                "current_index": min(node_idx, len(waypoints) - 1),
                "current_node_id": frame.route[node_idx],
                "waypoints": [wp.to_dict() for wp in waypoints],
            })
            fx._write_message(writer, status_channel, timestamp_ns, {
                "turn": frame.turn,
                "caption": frame.caption,
                "detail": frame.detail,
                "events": frame.events,
            })

        writer.finish()


def _write_timeline_json(graph: Any, timeline: list[TimelineFrame]) -> None:
    frames = []
    for frame in timeline:
        frames.append({
            "turn": frame.turn,
            "caption": frame.caption,
            "detail": frame.detail,
            "route_goal": frame.route[-1] if frame.route else "",
            "route": frame.route,
            "progress": frame.progress,
            "location": frame.location,
            "items": sorted(frame.items),
            "events": frame.events,
        })
    TIMELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TIMELINE_PATH.write_text(
        json.dumps({"frames": frames, "hz": HZ}, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(HERE))
    graph = load_graph(GRAPH_PATH)
    timeline = _build_timeline(graph)
    if not timeline:
        raise SystemExit("escape room timeline is empty")
    _write_mcap(graph, timeline)
    _write_timeline_json(graph, timeline)
    duration = len(timeline) / HZ
    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"frames: {len(timeline)} @ {HZ} Hz ({duration:.1f}s)")
    print(f"wrote {OUTPUT_PATH.relative_to(ROOT)} ({size_kb:.0f} KB)")
    print(f"wrote {TIMELINE_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
