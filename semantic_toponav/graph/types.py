"""Core data types for the semantic topology graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class GraphValidationError(Exception):
    """Raised when a topology graph fails validation."""


@dataclass
class Pose2D:
    """Optional 2D pose attached to a topology node.

    The graph is semantic-first, so pose is optional. When present it enables
    Euclidean heuristics for A* and visualization.
    """

    x: float
    y: float
    yaw: float = 0.0
    frame_id: str = "map"

    def to_dict(self) -> dict[str, Any]:
        return {"x": self.x, "y": self.y, "yaw": self.yaw, "frame_id": self.frame_id}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Pose2D":
        return cls(
            x=float(data["x"]),
            y=float(data["y"]),
            yaw=float(data.get("yaw", 0.0)),
            frame_id=str(data.get("frame_id", "map")),
        )


@dataclass
class TopologyNode:
    """A semantic node in the topology graph."""

    id: str
    label: str
    type: str
    pose: Pose2D | None = None
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class TopologyEdge:
    """A semantic edge connecting two topology nodes."""

    id: str
    source: str
    target: str
    type: str
    cost: float = 1.0
    bidirectional: bool = True
    properties: dict[str, Any] = field(default_factory=dict)
