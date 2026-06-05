"""Export a Foxglove Studio replay from the semantic-toponav demo graph.

The resulting MCAP is generated from real semantic-toponav APIs:

* ``resolve_goal("executive office on 3F")``
* ``plan_astar(..., prefer_elevator)``
* ``path_to_semantic_waypoints``

Run from the repository root:

    python examples/export_foxglove_mcap.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

try:
    from mcap.writer import CompressionType, Writer
except ImportError as exc:  # pragma: no cover - exercised only without optional deps.
    raise SystemExit("Install the Foxglove extra first: pip install -e '.[foxglove]'") from exc

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

GRAPH_PATH = HERE / "multi_floor_office.yaml"
OUTPUT_PATH = ROOT / "docs" / "foxglove" / "semantic_toponav_demo.mcap"

QUERY = "executive office on 3F"
START_NODE = "entrance"
GOAL_NODE = "exec_office_3f"

START_TIME_NS = 1_725_000_000_000_000_000
DURATION_SEC = 8.0
HZ = 12
FRAME_COUNT = int(DURATION_SEC * HZ) + 1
FLOOR_HEIGHT_M = 2.8

LINE_STRIP = 0
LINE_LOOP = 1
LINE_LIST = 2

NODE_COLORS = {
    "entrance": (0.22, 0.83, 0.45, 1.0),
    "room": (0.31, 0.62, 0.96, 1.0),
    "corridor": (0.58, 0.64, 0.72, 1.0),
    "intersection": (0.66, 0.40, 0.96, 1.0),
    "elevator": (0.96, 0.62, 0.08, 1.0),
    "stairs": (0.95, 0.34, 0.34, 1.0),
}


def _schema(properties: dict[str, Any], *, required: list[str] | None = None) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": required or list(properties),
        "additionalProperties": True,
    }


NUMBER = {"type": "number"}
STRING = {"type": "string"}
BOOL = {"type": "boolean"}


def _array(items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": items}


TIMESTAMP_SCHEMA = _schema(
    {"sec": {"type": "integer"}, "nsec": {"type": "integer"}},
    required=["sec", "nsec"],
)
VECTOR3_SCHEMA = _schema({"x": NUMBER, "y": NUMBER, "z": NUMBER}, required=["x", "y", "z"])
QUAT_SCHEMA = _schema(
    {"x": NUMBER, "y": NUMBER, "z": NUMBER, "w": NUMBER},
    required=["x", "y", "z", "w"],
)
COLOR_SCHEMA = _schema({"r": NUMBER, "g": NUMBER, "b": NUMBER, "a": NUMBER})
POSE_SCHEMA = _schema(
    {"position": VECTOR3_SCHEMA, "orientation": QUAT_SCHEMA},
    required=["position", "orientation"],
)
KEY_VALUE_SCHEMA = _schema({"key": STRING, "value": STRING}, required=["key", "value"])
LINE_PRIMITIVE_SCHEMA = _schema(
    {
        "type": {"type": "integer"},
        "pose": POSE_SCHEMA,
        "thickness": NUMBER,
        "scale_invariant": BOOL,
        "points": _array(VECTOR3_SCHEMA),
        "color": COLOR_SCHEMA,
        "colors": _array(COLOR_SCHEMA),
        "indices": _array({"type": "integer"}),
    }
)
SPHERE_PRIMITIVE_SCHEMA = _schema(
    {"pose": POSE_SCHEMA, "size": VECTOR3_SCHEMA, "color": COLOR_SCHEMA}
)
TEXT_PRIMITIVE_SCHEMA = _schema(
    {
        "pose": POSE_SCHEMA,
        "billboard": BOOL,
        "font_size": NUMBER,
        "scale_invariant": BOOL,
        "color": COLOR_SCHEMA,
        "text": STRING,
    }
)
SCENE_ENTITY_SCHEMA = _schema(
    {
        "timestamp": TIMESTAMP_SCHEMA,
        "frame_id": STRING,
        "id": STRING,
        "lifetime": TIMESTAMP_SCHEMA,
        "frame_locked": BOOL,
        "metadata": _array(KEY_VALUE_SCHEMA),
        "arrows": _array(_schema({})),
        "cubes": _array(_schema({})),
        "spheres": _array(SPHERE_PRIMITIVE_SCHEMA),
        "cylinders": _array(_schema({})),
        "lines": _array(LINE_PRIMITIVE_SCHEMA),
        "triangles": _array(_schema({})),
        "texts": _array(TEXT_PRIMITIVE_SCHEMA),
        "models": _array(_schema({})),
    }
)

FOXGLOVE_SCHEMAS: dict[str, dict[str, Any]] = {
    "foxglove.FrameTransforms": _schema(
        {
            "transforms": _array(
                _schema(
                    {
                        "timestamp": TIMESTAMP_SCHEMA,
                        "parent_frame_id": STRING,
                        "child_frame_id": STRING,
                        "translation": VECTOR3_SCHEMA,
                        "rotation": QUAT_SCHEMA,
                    }
                )
            )
        },
        required=["transforms"],
    ),
    "foxglove.PoseInFrame": _schema(
        {"timestamp": TIMESTAMP_SCHEMA, "frame_id": STRING, "pose": POSE_SCHEMA},
        required=["timestamp", "frame_id", "pose"],
    ),
    "foxglove.SceneUpdate": _schema(
        {
            "deletions": _array({"type": "string"}),
            "entities": _array(SCENE_ENTITY_SCHEMA),
        },
        required=["deletions", "entities"],
    ),
}

CUSTOM_SCHEMAS: dict[str, dict[str, Any]] = {
    "visualization_msgs/MarkerArray": _schema(
        {
            "markers": _array(
                _schema(
                    {
                        "header": _schema(
                            {
                                "seq": {"type": "integer"},
                                "stamp": TIMESTAMP_SCHEMA,
                                "frame_id": STRING,
                            }
                        ),
                        "ns": STRING,
                        "id": {"type": "integer"},
                        "type": {"type": "integer"},
                        "action": {"type": "integer"},
                        "pose": POSE_SCHEMA,
                        "scale": VECTOR3_SCHEMA,
                        "color": COLOR_SCHEMA,
                        "lifetime": TIMESTAMP_SCHEMA,
                        "frame_locked": BOOL,
                        "points": _array(VECTOR3_SCHEMA),
                        "colors": _array(COLOR_SCHEMA),
                        "text": STRING,
                        "mesh_resource": STRING,
                        "mesh_use_embedded_materials": BOOL,
                    }
                )
            )
        }
    ),
    "semantic_toponav.ResolveTrace": _schema(
        {
            "query": STRING,
            "candidates": _array(
                _schema(
                    {
                        "node_id": STRING,
                        "score": NUMBER,
                        "reasons": _array(STRING),
                    }
                )
            ),
            "chosen": STRING,
            "source": STRING,
        }
    ),
    "semantic_toponav.Route": _schema(
        {
            "start": STRING,
            "goal": STRING,
            "path": {"type": "array", "items": STRING},
            "policy": STRING,
            "edge_count": {"type": "integer"},
        }
    ),
    "semantic_toponav.WaypointArray": _schema(
        {
            "timestamp": TIMESTAMP_SCHEMA,
            "current_index": {"type": "integer"},
            "current_node_id": STRING,
            "waypoints": _array(
                _schema(
                    {
                        "node_id": STRING,
                        "node_label": STRING,
                        "node_type": STRING,
                        "action": STRING,
                        "instruction": STRING,
                        "properties": _schema({"floor": {"type": "integer"}}, required=[]),
                        "pose": _schema(
                            {
                                "x": NUMBER,
                                "y": NUMBER,
                                "yaw": NUMBER,
                                "frame_id": STRING,
                            }
                        ),
                    }
                )
            ),
        }
    ),
    "semantic_toponav.Admission": _schema(
        {
            "agent_id": STRING,
            "granted": BOOL,
            "reason_code": STRING,
            "route": _array(STRING),
            "reservation_window_sec": NUMBER,
        }
    ),
}


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


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("utf-8")


def _timestamp(ns: int) -> dict[str, int]:
    return {"sec": ns // 1_000_000_000, "nsec": ns % 1_000_000_000}


def _color(r: float, g: float, b: float, a: float = 1.0) -> dict[str, float]:
    return {"r": r, "g": g, "b": b, "a": a}


def _point(x: float, y: float, z: float) -> dict[str, float]:
    return {"x": round(x, 4), "y": round(y, 4), "z": round(z, 4)}


def _pose(x: float, y: float, z: float, yaw: float = 0.0) -> dict[str, Any]:
    half = yaw / 2.0
    return {
        "position": _point(x, y, z),
        "orientation": {
            "x": 0.0,
            "y": 0.0,
            "z": round(math.sin(half), 6),
            "w": round(math.cos(half), 6),
        },
    }


def _floor(node: Any) -> int:
    return int(node.properties.get("floor", 1))


def _node_xyz(node: Any) -> tuple[float, float, float]:
    if node.pose is None:
        return 0.0, 0.0, (_floor(node) - 1) * FLOOR_HEIGHT_M
    return node.pose.x, node.pose.y, (_floor(node) - 1) * FLOOR_HEIGHT_M


def _line(
    points: list[tuple[float, float, float]],
    color: tuple[float, float, float, float],
    *,
    line_type: int = LINE_STRIP,
    thickness: float = 0.08,
) -> dict[str, Any]:
    return {
        "type": line_type,
        "pose": _pose(0.0, 0.0, 0.0),
        "thickness": thickness,
        "scale_invariant": False,
        "points": [_point(*p) for p in points],
        "color": _color(*color),
        "colors": [],
        "indices": [],
    }


def _sphere(
    xyz: tuple[float, float, float],
    color: tuple[float, float, float, float],
    *,
    diameter: float = 0.28,
) -> dict[str, Any]:
    x, y, z = xyz
    return {
        "pose": _pose(x, y, z),
        "size": _point(diameter, diameter, diameter),
        "color": _color(*color),
    }


def _text(
    xyz: tuple[float, float, float],
    value: str,
    color: tuple[float, float, float, float] = (0.89, 0.92, 0.96, 1.0),
    *,
    size: float = 0.34,
) -> dict[str, Any]:
    x, y, z = xyz
    return {
        "pose": _pose(x, y, z),
        "billboard": True,
        "font_size": size,
        "scale_invariant": False,
        "color": _color(*color),
        "text": value,
    }


def _marker(
    *,
    timestamp_ns: int,
    ns: str,
    marker_id: int,
    marker_type: int,
    pose: dict[str, Any] | None = None,
    scale: dict[str, float] | None = None,
    color: tuple[float, float, float, float] = (0.89, 0.92, 0.96, 1.0),
    points: list[tuple[float, float, float]] | None = None,
    text: str = "",
) -> dict[str, Any]:
    return {
        "header": {"seq": 0, "stamp": _timestamp(timestamp_ns), "frame_id": "map"},
        "ns": ns,
        "id": marker_id,
        "type": marker_type,
        "action": 0,
        "pose": pose or _pose(0.0, 0.0, 0.0),
        "scale": scale or _point(0.16, 0.16, 0.16),
        "color": _color(*color),
        "lifetime": {"sec": 0, "nsec": 0},
        "frame_locked": False,
        "points": [_point(*point) for point in points or []],
        "colors": [],
        "text": text,
        "mesh_resource": "",
        "mesh_use_embedded_materials": False,
    }


def _entity(entity_id: str, timestamp_ns: int, **parts: Any) -> dict[str, Any]:
    entity = {
        "timestamp": _timestamp(timestamp_ns),
        "frame_id": "map",
        "id": entity_id,
        "lifetime": {"sec": 0, "nsec": 0},
        "frame_locked": False,
        "metadata": [],
        "arrows": [],
        "cubes": [],
        "spheres": [],
        "cylinders": [],
        "lines": [],
        "triangles": [],
        "texts": [],
        "models": [],
    }
    entity.update(parts)
    return entity


def _edge_lines(graph: Any, edge_type: str) -> list[tuple[float, float, float]]:
    points: list[tuple[float, float, float]] = []
    for edge in graph.edges():
        if edge.type != edge_type:
            continue
        points.extend([_node_xyz(graph.get_node(edge.source)), _node_xyz(graph.get_node(edge.target))])
    return points


def _static_scene(graph: Any, route: list[str], candidates: list[Any], timestamp_ns: int) -> dict[str, Any]:
    floors = sorted({_floor(node) for node in graph.nodes()})
    floor_lines = []
    for floor in floors:
        z = (floor - 1) * FLOOR_HEIGHT_M - 0.04
        floor_lines.append(
            _line(
                [(-0.8, -4.6, z), (12.8, -4.6, z), (12.8, 4.6, z), (-0.8, 4.6, z)],
                (0.18, 0.25, 0.37, 0.62),
                line_type=LINE_LOOP,
                thickness=0.035,
            )
        )

    route_points = [_node_xyz(graph.get_node(node_id)) for node_id in route]
    lines = [
        *floor_lines,
        _line(_edge_lines(graph, "traversable"), (0.45, 0.50, 0.58, 0.7), line_type=LINE_LIST),
        _line(
            _edge_lines(graph, "elevator_connection"),
            (0.96, 0.62, 0.08, 0.9),
            line_type=LINE_LIST,
            thickness=0.11,
        ),
        _line(_edge_lines(graph, "stairs_up"), (0.95, 0.34, 0.34, 0.75), line_type=LINE_LIST),
        _line(route_points, (0.96, 0.22, 0.45, 1.0), thickness=0.14),
    ]
    node_spheres = [
        _sphere(_node_xyz(node), NODE_COLORS.get(node.type, (0.31, 0.62, 0.96, 1.0)))
        for node in graph.nodes()
    ]
    labels = [
        _text((0.0, -5.15, (floor - 1) * FLOOR_HEIGHT_M), f"floor {floor}", size=0.38)
        for floor in floors
    ]
    for node_id in route:
        node = graph.get_node(node_id)
        x, y, z = _node_xyz(node)
        labels.append(_text((x, y + 0.45, z + 0.18), node.label, size=0.24))
    labels.append(
        _text(
            (0.0, 5.1, 0.4),
            f'query: "{QUERY}" -> {candidates[0].node_id}',
            (0.52, 0.92, 0.99, 1.0),
            size=0.32,
        )
    )
    return {
        "deletions": [],
        "entities": [
            _entity(
                "semantic_toponav_static",
                timestamp_ns,
                lines=lines,
                spheres=node_spheres,
                texts=labels,
                metadata=[
                    {"key": "source", "value": "examples/multi_floor_office.yaml"},
                    {"key": "planner", "value": "A* + prefer_elevator"},
                ],
            )
        ],
    }


def _marker_array(
    graph: Any,
    route: list[str],
    timestamp_ns: int,
    robot_xyz: tuple[float, float, float],
    node_idx: int,
) -> dict[str, Any]:
    markers: list[dict[str, Any]] = []
    for floor in sorted({_floor(node) for node in graph.nodes()}):
        z = (floor - 1) * FLOOR_HEIGHT_M - 0.04
        floor_points = [
            (-0.8, -4.6, z),
            (12.8, -4.6, z),
            (12.8, 4.6, z),
            (-0.8, 4.6, z),
            (-0.8, -4.6, z),
        ]
        markers.append(
            _marker(
                timestamp_ns=timestamp_ns,
                ns="floor_outline",
                marker_id=floor,
                marker_type=4,
                scale=_point(0.05, 0.0, 0.0),
                color=(0.18, 0.25, 0.37, 0.72),
                points=floor_points,
            )
        )
        markers.append(
            _marker(
                timestamp_ns=timestamp_ns,
                ns="floor_label",
                marker_id=floor,
                marker_type=9,
                pose=_pose(0.0, -5.15, (floor - 1) * FLOOR_HEIGHT_M + 0.15),
                scale=_point(0.32, 0.32, 0.32),
                color=(0.89, 0.92, 0.96, 1.0),
                text=f"floor {floor}",
            )
        )

    for idx, edge in enumerate(graph.edges()):
        edge_color = (0.45, 0.50, 0.58, 0.65)
        width = 0.07
        if edge.type == "elevator_connection":
            edge_color = (0.96, 0.62, 0.08, 0.95)
            width = 0.12
        elif edge.type.startswith("stairs"):
            edge_color = (0.95, 0.34, 0.34, 0.78)
        markers.append(
            _marker(
                timestamp_ns=timestamp_ns,
                ns="topology_edges",
                marker_id=idx,
                marker_type=5,
                scale=_point(width, 0.0, 0.0),
                color=edge_color,
                points=[_node_xyz(graph.get_node(edge.source)), _node_xyz(graph.get_node(edge.target))],
            )
        )

    for idx, node in enumerate(graph.nodes()):
        color = NODE_COLORS.get(node.type, (0.31, 0.62, 0.96, 1.0))
        markers.append(
            _marker(
                timestamp_ns=timestamp_ns,
                ns="topology_nodes",
                marker_id=idx,
                marker_type=2,
                pose=_pose(*_node_xyz(node)),
                scale=_point(0.3, 0.3, 0.3),
                color=color,
            )
        )

    route_points = [_node_xyz(graph.get_node(node_id)) for node_id in route]
    markers.append(
        _marker(
            timestamp_ns=timestamp_ns,
            ns="semantic_route",
            marker_id=1,
            marker_type=4,
            scale=_point(0.18, 0.0, 0.0),
            color=(0.96, 0.22, 0.45, 1.0),
            points=route_points,
        )
    )
    markers.append(
        _marker(
            timestamp_ns=timestamp_ns,
            ns="robot",
            marker_id=1,
            marker_type=2,
            pose=_pose(*robot_xyz),
            scale=_point(0.52, 0.52, 0.52),
            color=(0.13, 0.83, 0.93, 1.0),
        )
    )
    markers.append(
        _marker(
            timestamp_ns=timestamp_ns,
            ns="robot_label",
            marker_id=1,
            marker_type=9,
            pose=_pose(robot_xyz[0], robot_xyz[1] - 0.55, robot_xyz[2] + 0.35),
            scale=_point(0.26, 0.26, 0.26),
            color=(0.52, 0.92, 0.99, 1.0),
            text=f"base_link | {route[node_idx]}",
        )
    )
    return {"markers": markers}


def _route_geometry(graph: Any, route: list[str]) -> tuple[list[tuple[float, float, float]], list[float]]:
    points = [_node_xyz(graph.get_node(node_id)) for node_id in route]
    cumulative = [0.0]
    for a, b in zip(points[:-1], points[1:], strict=False):
        cumulative.append(cumulative[-1] + math.dist(a, b))
    return points, cumulative


def _sample_route(
    points: list[tuple[float, float, float]],
    cumulative: list[float],
    progress: float,
) -> tuple[tuple[float, float, float], int, float]:
    total = cumulative[-1]
    target = total * max(0.0, min(1.0, progress))
    for idx, (a_dist, b_dist) in enumerate(zip(cumulative[:-1], cumulative[1:], strict=False)):
        if target <= b_dist or idx == len(cumulative) - 2:
            span = max(b_dist - a_dist, 1e-9)
            local = (target - a_dist) / span
            a = points[idx]
            b = points[idx + 1]
            xyz = (
                a[0] + (b[0] - a[0]) * local,
                a[1] + (b[1] - a[1]) * local,
                a[2] + (b[2] - a[2]) * local,
            )
            return xyz, idx, local
    return points[-1], len(points) - 2, 1.0


def _ease(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def _yaw_between(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    fallback: float,
) -> float:
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return fallback
    return math.atan2(dy, dx)


def _dynamic_messages(
    graph: Any,
    route: list[str],
    waypoints: list[Any],
    timestamp_ns: int,
    frame_idx: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], int]:
    points, cumulative = _route_geometry(graph, route)
    progress = _ease(frame_idx / (FRAME_COUNT - 1))
    robot_xyz, segment_idx, _ = _sample_route(points, cumulative, progress)
    node_idx = min(segment_idx, len(route) - 1)
    next_idx = min(segment_idx + 1, len(points) - 1)
    yaw = _yaw_between(points[segment_idx], points[next_idx], 0.0)
    pose = _pose(*robot_xyz, yaw=yaw)

    # Bright "traveled" polyline that follows the route up to the robot, so the
    # replay reads as progress filling in place-by-place (instead of a straight
    # leader line cutting across floors).
    traveled = [*points[: segment_idx + 1], robot_xyz]
    scene = {
        "deletions": [],
        "entities": [
            _entity(
                "base_link_robot",
                timestamp_ns,
                spheres=[
                    _sphere(robot_xyz, (0.13, 0.83, 0.93, 0.30), diameter=0.86),
                    _sphere(robot_xyz, (0.13, 0.83, 0.93, 1.0), diameter=0.38),
                ],
                lines=[
                    _line(traveled, (0.40, 0.95, 1.0, 1.0), thickness=0.2),
                ],
            )
        ],
    }
    tf = {
        "transforms": [
            {
                "timestamp": _timestamp(timestamp_ns),
                "parent_frame_id": "map",
                "child_frame_id": "base_link",
                "translation": _point(*robot_xyz),
                "rotation": pose["orientation"],
            }
        ]
    }
    pose_msg = {"timestamp": _timestamp(timestamp_ns), "frame_id": "map", "pose": pose}
    waypoint_msg = {
        "timestamp": _timestamp(timestamp_ns),
        "current_index": min(node_idx, len(waypoints) - 1),
        "current_node_id": route[node_idx],
        "waypoints": [waypoint.to_dict() for waypoint in waypoints],
    }
    markers = _marker_array(graph, route, timestamp_ns, robot_xyz, node_idx)
    return scene, tf, pose_msg, waypoint_msg, markers, node_idx


def _register_channels(writer: Writer) -> dict[str, int]:
    schemas: dict[str, int] = {}
    for name, schema in {**FOXGLOVE_SCHEMAS, **CUSTOM_SCHEMAS}.items():
        schemas[name] = writer.register_schema(name, "jsonschema", _json_bytes(schema))

    return {
        "/tf": writer.register_channel("/tf", "json", schemas["foxglove.FrameTransforms"]),
        "/semantic_toponav/pose": writer.register_channel(
            "/semantic_toponav/pose", "json", schemas["foxglove.PoseInFrame"]
        ),
        "/semantic_toponav/scene": writer.register_channel(
            "/semantic_toponav/scene", "json", schemas["foxglove.SceneUpdate"]
        ),
        "/semantic_toponav/markers": writer.register_channel(
            "/semantic_toponav/markers", "json", schemas["visualization_msgs/MarkerArray"]
        ),
        "/semantic_toponav/resolve_trace": writer.register_channel(
            "/semantic_toponav/resolve_trace",
            "json",
            schemas["semantic_toponav.ResolveTrace"],
        ),
        "/semantic_toponav/route": writer.register_channel(
            "/semantic_toponav/route", "json", schemas["semantic_toponav.Route"]
        ),
        "/semantic_toponav/waypoints": writer.register_channel(
            "/semantic_toponav/waypoints", "json", schemas["semantic_toponav.WaypointArray"]
        ),
        "/semantic_toponav/admission": writer.register_channel(
            "/semantic_toponav/admission", "json", schemas["semantic_toponav.Admission"]
        ),
    }


def _write_message(writer: Writer, channel_id: int, timestamp_ns: int, message: dict[str, Any]) -> None:
    writer.add_message(
        channel_id=channel_id,
        log_time=timestamp_ns,
        publish_time=timestamp_ns,
        data=_json_bytes(message),
    )


def _write_mcap(graph: Any, candidates: list[Any], route: list[str], waypoints: list[Any]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("wb") as stream:
        writer = Writer(stream, compression=CompressionType.NONE)
        writer.start(profile="foxglove")
        channels = _register_channels(writer)
        writer.add_metadata(
            "semantic_toponav_demo",
            {
                "query": QUERY,
                "start_node": START_NODE,
                "goal_node": GOAL_NODE,
                "route": " -> ".join(route),
                "source_graph": str(GRAPH_PATH.relative_to(ROOT)),
            },
        )

        t0 = START_TIME_NS
        _write_message(writer, channels["/semantic_toponav/scene"], t0, _static_scene(graph, route, candidates, t0))
        _write_message(
            writer,
            channels["/semantic_toponav/resolve_trace"],
            t0,
            {
                "query": QUERY,
                "source": str(GRAPH_PATH.relative_to(ROOT)),
                "chosen": candidates[0].node_id,
                "candidates": [
                    {
                        "node_id": candidate.node_id,
                        "score": candidate.score,
                        "reasons": candidate.reasons,
                    }
                    for candidate in candidates
                ],
            },
        )
        _write_message(
            writer,
            channels["/semantic_toponav/route"],
            t0,
            {
                "start": START_NODE,
                "goal": GOAL_NODE,
                "path": route,
                "policy": "A* + compose_costs(prefer_elevator)",
                "edge_count": max(0, len(route) - 1),
            },
        )
        _write_message(
            writer,
            channels["/semantic_toponav/admission"],
            t0,
            {
                "agent_id": "robot_alpha",
                "granted": True,
                "reason_code": "admitted",
                "route": route,
                "reservation_window_sec": DURATION_SEC,
            },
        )

        for frame_idx in range(FRAME_COUNT):
            timestamp_ns = t0 + round(frame_idx * 1_000_000_000 / HZ)
            scene, tf, pose, waypoint, markers, _ = _dynamic_messages(
                graph, route, waypoints, timestamp_ns, frame_idx
            )
            _write_message(writer, channels["/tf"], timestamp_ns, tf)
            _write_message(writer, channels["/semantic_toponav/pose"], timestamp_ns, pose)
            _write_message(writer, channels["/semantic_toponav/scene"], timestamp_ns, scene)
            _write_message(writer, channels["/semantic_toponav/markers"], timestamp_ns, markers)
            _write_message(writer, channels["/semantic_toponav/waypoints"], timestamp_ns, waypoint)

        writer.finish()


def main() -> None:
    graph, candidates, route, waypoints = _load_demo()
    _write_mcap(graph, candidates, route, waypoints)
    size_kb = OUTPUT_PATH.stat().st_size / 1024
    print(f"query: {QUERY!r} -> {candidates[0].node_id}")
    print(f"route: {' -> '.join(route)}")
    print(f"wrote {OUTPUT_PATH.relative_to(ROOT)} ({size_kb:.0f} KB, {FRAME_COUNT} frames)")


if __name__ == "__main__":
    main()
