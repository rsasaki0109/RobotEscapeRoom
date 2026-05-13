"""Convert a node-ID path into a list of semantic waypoints.

Output is fully deterministic — no LLM, no random wording.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyNode


@dataclass
class SemanticWaypoint:
    """A semantic waypoint generated from a topology node."""

    node_id: str
    node_label: str
    node_type: str
    action: str
    instruction: str
    pose: Pose2D | None = None
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "node_id": self.node_id,
            "node_label": self.node_label,
            "node_type": self.node_type,
            "action": self.action,
            "instruction": self.instruction,
            "properties": dict(self.properties),
        }
        if self.pose is not None:
            out["pose"] = self.pose.to_dict()
        return out


_ACTION_BY_TYPE: dict[str, str] = {
    "entrance": "enter",
    "room": "enter",
    "corridor": "proceed_through",
    "intersection": "navigate",
    "elevator": "take_elevator",
    "stairs": "use_stairs",
}

_DEFAULT_ACTION_START = "start"
_DEFAULT_ACTION_GOAL = "arrive"
_FALLBACK_ACTION = "pass_through"


def _action_for(node: TopologyNode, position: str) -> str:
    if position == "start":
        return _DEFAULT_ACTION_START
    if position == "goal":
        return _DEFAULT_ACTION_GOAL
    return _ACTION_BY_TYPE.get(node.type, _FALLBACK_ACTION)


def _instruction_for(node: TopologyNode, action: str) -> str:
    label = node.label or node.id
    if action == "start":
        return f"Start at {label}"
    if action == "arrive":
        return f"Arrive at {label}"
    if action == "enter":
        return f"Enter {label}"
    if action == "proceed_through":
        return f"Proceed through {label}"
    if action == "navigate":
        return f"Navigate to {label}"
    if action == "take_elevator":
        return f"Take elevator at {label}"
    if action == "use_stairs":
        return f"Use stairs at {label}"
    return f"Pass through {label}"


def path_to_semantic_waypoints(
    graph: TopologyGraph,
    path: list[str],
) -> list[SemanticWaypoint]:
    """Convert a node-ID path into a list of SemanticWaypoint objects."""
    if not path:
        return []

    waypoints: list[SemanticWaypoint] = []
    last = len(path) - 1
    for i, node_id in enumerate(path):
        node = graph.get_node(node_id)
        if i == 0:
            position = "start"
        elif i == last:
            position = "goal"
        else:
            position = "middle"
        action = _action_for(node, position)
        instruction = _instruction_for(node, action)
        waypoints.append(
            SemanticWaypoint(
                node_id=node.id,
                node_label=node.label,
                node_type=node.type,
                action=action,
                instruction=instruction,
                pose=node.pose,
                properties=dict(node.properties),
            )
        )
    return waypoints
