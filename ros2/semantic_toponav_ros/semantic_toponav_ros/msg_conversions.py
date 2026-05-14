"""Conversion helpers between Python dataclasses and `semantic_toponav_msgs`.

The pure-Python `to_*_fields` helpers convert a dataclass into a dict whose
keys match the corresponding `.msg` field names. They have no ROS dependency
and are exercised by the project's regular pytest suite.

The `to_*_msg` helpers populate an already-imported message class instance
from those field dicts. They require the generated `semantic_toponav_msgs`
package to be importable at runtime and are therefore only callable inside
a sourced ROS2 environment.
"""

from __future__ import annotations

import json
from typing import Any

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode
from semantic_toponav.waypoint.semantic_waypoint import SemanticWaypoint


def _pose_fields(pose: Pose2D | None) -> dict[str, Any]:
    """Return the (has_pose, frame_id, pose) triple for a message field dict.

    Custom messages always carry the three fields side-by-side, so we mirror
    that layout exactly. When ``pose`` is None the pose values are zeroed.
    """
    if pose is None:
        return {
            "has_pose": False,
            "frame_id": "",
            "pose": {"x": 0.0, "y": 0.0, "theta": 0.0},
        }
    return {
        "has_pose": True,
        "frame_id": pose.frame_id,
        "pose": {"x": pose.x, "y": pose.y, "theta": pose.yaw},
    }


def _pose_from_fields(
    has_pose: bool, frame_id: str, pose: dict[str, float]
) -> Pose2D | None:
    if not has_pose:
        return None
    return Pose2D(
        x=float(pose["x"]),
        y=float(pose["y"]),
        yaw=float(pose["theta"]),
        frame_id=frame_id or "map",
    )


def _properties_to_json(properties: dict[str, Any]) -> str:
    if not properties:
        return ""
    return json.dumps(properties, ensure_ascii=False, sort_keys=True)


def _properties_from_json(properties_json: str) -> dict[str, Any]:
    if not properties_json:
        return {}
    return dict(json.loads(properties_json))


# ----------------------------- SemanticWaypoint -----------------------------


def semantic_waypoint_to_fields(wp: SemanticWaypoint) -> dict[str, Any]:
    """Return a SemanticWaypoint message as a dict keyed by .msg field names."""
    return {
        "node_id": wp.node_id,
        "node_label": wp.node_label,
        "node_type": wp.node_type,
        "action": wp.action,
        "instruction": wp.instruction,
        **_pose_fields(wp.pose),
        "properties_json": _properties_to_json(wp.properties),
    }


def semantic_waypoint_from_fields(fields: dict[str, Any]) -> SemanticWaypoint:
    """Inverse of :func:`semantic_waypoint_to_fields`."""
    return SemanticWaypoint(
        node_id=fields["node_id"],
        node_label=fields["node_label"],
        node_type=fields["node_type"],
        action=fields["action"],
        instruction=fields["instruction"],
        pose=_pose_from_fields(
            fields["has_pose"], fields.get("frame_id", ""), fields["pose"]
        ),
        properties=_properties_from_json(fields.get("properties_json", "")),
    )


# --------------------------- SemanticWaypointArray --------------------------


def semantic_waypoint_array_to_fields(
    path: list[str],
    waypoints: list[SemanticWaypoint],
    *,
    frame_id: str = "map",
) -> dict[str, Any]:
    """Return a SemanticWaypointArray message as a field dict.

    The header is left as a stamp-less placeholder; the caller fills the
    timestamp from the active ROS clock when constructing the actual message.
    """
    return {
        "header": {"frame_id": frame_id},
        "path": list(path),
        "waypoints": [semantic_waypoint_to_fields(wp) for wp in waypoints],
    }


# ------------------------------ TopologyNode --------------------------------


def topology_node_to_fields(node: TopologyNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "label": node.label,
        "type": node.type,
        **_pose_fields(node.pose),
        "properties_json": _properties_to_json(node.properties),
    }


def topology_node_from_fields(fields: dict[str, Any]) -> TopologyNode:
    return TopologyNode(
        id=fields["id"],
        label=fields["label"],
        type=fields["type"],
        pose=_pose_from_fields(
            fields["has_pose"], fields.get("frame_id", ""), fields["pose"]
        ),
        properties=_properties_from_json(fields.get("properties_json", "")),
    )


# ------------------------------ TopologyEdge --------------------------------


def topology_edge_to_fields(edge: TopologyEdge) -> dict[str, Any]:
    return {
        "id": edge.id,
        "source": edge.source,
        "target": edge.target,
        "type": edge.type,
        "cost": float(edge.cost),
        "bidirectional": bool(edge.bidirectional),
        "properties_json": _properties_to_json(edge.properties),
    }


def topology_edge_from_fields(fields: dict[str, Any]) -> TopologyEdge:
    return TopologyEdge(
        id=fields["id"],
        source=fields["source"],
        target=fields["target"],
        type=fields["type"],
        cost=float(fields["cost"]),
        bidirectional=bool(fields["bidirectional"]),
        properties=_properties_from_json(fields.get("properties_json", "")),
    )


# ------------------------------ TopologyGraph -------------------------------


def topology_graph_to_fields(
    graph: TopologyGraph,
    *,
    frame_id: str = "map",
) -> dict[str, Any]:
    return {
        "header": {"frame_id": frame_id},
        "nodes": [topology_node_to_fields(n) for n in graph.nodes()],
        "edges": [topology_edge_to_fields(e) for e in graph.edges()],
    }


def topology_graph_from_fields(fields: dict[str, Any]) -> TopologyGraph:
    graph = TopologyGraph()
    for n in fields.get("nodes", []):
        graph.add_node(topology_node_from_fields(n))
    for e in fields.get("edges", []):
        graph.add_edge(topology_edge_from_fields(e))
    return graph


# ----------------------- message-instance construction ----------------------
#
# These helpers require `semantic_toponav_msgs` and `geometry_msgs` to be
# importable, which is only the case inside a sourced ROS2 environment. They
# are thin: they copy fields straight from the dict layer onto the generated
# message class instances.


def _apply_pose_fields(msg: Any, fields: dict[str, Any]) -> None:
    """Copy (has_pose, frame_id, pose) from a field dict onto a msg instance."""
    msg.has_pose = bool(fields["has_pose"])
    msg.frame_id = str(fields.get("frame_id", ""))
    msg.pose.x = float(fields["pose"]["x"])
    msg.pose.y = float(fields["pose"]["y"])
    msg.pose.theta = float(fields["pose"]["theta"])


def semantic_waypoint_to_msg(wp: SemanticWaypoint) -> Any:
    """Construct a `semantic_toponav_msgs.msg.SemanticWaypoint` from ``wp``."""
    from semantic_toponav_msgs.msg import SemanticWaypoint as SemanticWaypointMsg

    fields = semantic_waypoint_to_fields(wp)
    msg = SemanticWaypointMsg()
    msg.node_id = fields["node_id"]
    msg.node_label = fields["node_label"]
    msg.node_type = fields["node_type"]
    msg.action = fields["action"]
    msg.instruction = fields["instruction"]
    _apply_pose_fields(msg, fields)
    msg.properties_json = fields["properties_json"]
    return msg


def semantic_waypoint_array_to_msg(
    path: list[str],
    waypoints: list[SemanticWaypoint],
    *,
    frame_id: str = "map",
    stamp: Any = None,
) -> Any:
    """Construct a SemanticWaypointArray from a path + waypoint list."""
    from semantic_toponav_msgs.msg import (
        SemanticWaypointArray as SemanticWaypointArrayMsg,
    )

    msg = SemanticWaypointArrayMsg()
    msg.header.frame_id = frame_id
    if stamp is not None:
        msg.header.stamp = stamp
    msg.path = list(path)
    msg.waypoints = [semantic_waypoint_to_msg(wp) for wp in waypoints]
    return msg


def topology_node_to_msg(node: TopologyNode) -> Any:
    from semantic_toponav_msgs.msg import TopologyNode as TopologyNodeMsg

    fields = topology_node_to_fields(node)
    msg = TopologyNodeMsg()
    msg.id = fields["id"]
    msg.label = fields["label"]
    msg.type = fields["type"]
    _apply_pose_fields(msg, fields)
    msg.properties_json = fields["properties_json"]
    return msg


def topology_edge_to_msg(edge: TopologyEdge) -> Any:
    from semantic_toponav_msgs.msg import TopologyEdge as TopologyEdgeMsg

    fields = topology_edge_to_fields(edge)
    msg = TopologyEdgeMsg()
    msg.id = fields["id"]
    msg.source = fields["source"]
    msg.target = fields["target"]
    msg.type = fields["type"]
    msg.cost = fields["cost"]
    msg.bidirectional = fields["bidirectional"]
    msg.properties_json = fields["properties_json"]
    return msg


def topology_graph_to_msg(
    graph: TopologyGraph,
    *,
    frame_id: str = "map",
    stamp: Any = None,
) -> Any:
    from semantic_toponav_msgs.msg import TopologyGraph as TopologyGraphMsg

    msg = TopologyGraphMsg()
    msg.header.frame_id = frame_id
    if stamp is not None:
        msg.header.stamp = stamp
    msg.nodes = [topology_node_to_msg(n) for n in graph.nodes()]
    msg.edges = [topology_edge_to_msg(e) for e in graph.edges()]
    return msg
