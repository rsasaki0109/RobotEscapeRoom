"""Render a node-id path as a step-by-step list of human-readable instructions.

Output is fully deterministic — no LLM, no random wording. The intent is
to provide a stable, edge-aware narration on top of
:func:`semantic_toponav.waypoint.semantic_waypoint.path_to_semantic_waypoints`
(which gives one short imperative per node). ``describe_path`` looks at
the *edge* between adjacent nodes and changes phrasing accordingly so
that, for example, an ``elevator_connection`` between two elevator
landings is rendered as a single transit step ("Take the elevator
from A to B") rather than two disconnected node visits.

An LLM-augmented layer can later be added on top by feeding it these
:class:`PathStep` entries plus the original graph; the deterministic
output here is the floor of that pipeline.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import TopologyEdge, TopologyNode


@dataclass
class PathStep:
    """A single step in a rendered path narration.

    ``node_id``/``edge_id`` are ``None`` for synthetic steps such as
    floor-change call-outs that do not correspond to a node visit.
    """

    index: int
    text: str
    node_id: str | None = None
    edge_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "text": self.text,
            "node_id": self.node_id,
            "edge_id": self.edge_id,
        }


def _floor_of(node: TopologyNode) -> int | None:
    floor = node.properties.get("floor")
    if isinstance(floor, int):
        return floor
    return None


def _edge_between(
    graph: TopologyGraph, src_id: str, tgt_id: str
) -> TopologyEdge | None:
    for edge in graph.neighbors(src_id):
        if graph.other_end(edge, src_id) == tgt_id:
            return edge
    return None


def _arrival_phrase(node: TopologyNode, *, is_goal: bool) -> str:
    label = node.label or node.id
    if is_goal:
        return f"Arrive at {label}"
    if node.type == "elevator":
        return f"Take the elevator at {label}"
    if node.type == "stairs":
        return f"Take the stairs at {label}"
    if node.type == "corridor":
        return f"Proceed through {label}"
    if node.type == "intersection":
        return f"Continue through {label}"
    if node.type in {"room", "entrance"}:
        return f"Enter {label}"
    return f"Pass through {label}"


def _transition_text(
    prev: TopologyNode,
    cur: TopologyNode,
    edge: TopologyEdge | None,
    *,
    is_goal: bool,
) -> str:
    prev_label = prev.label or prev.id
    cur_label = cur.label or cur.id

    if edge is not None:
        if edge.type == "elevator_connection":
            return f"Take the elevator from {prev_label} to {cur_label}"
        if edge.type == "stairs_up":
            return f"Go up the stairs from {prev_label} to {cur_label}"
        if edge.type == "stairs_down":
            return f"Go down the stairs from {prev_label} to {cur_label}"
        if edge.type == "restricted":
            verb = "Arrive at" if is_goal else "Enter"
            return f"{verb} {cur_label} via a restricted route"

    return _arrival_phrase(cur, is_goal=is_goal)


def path_to_steps(
    graph: TopologyGraph,
    path: Sequence[str],
    *,
    include_floor_changes: bool = True,
) -> list[PathStep]:
    """Render a node-id path as a list of :class:`PathStep` entries."""
    if not path:
        return []

    steps: list[PathStep] = []
    last = len(path) - 1

    start_node = graph.get_node(path[0])
    steps.append(
        PathStep(
            index=1,
            text=f"Start at {start_node.label or start_node.id}",
            node_id=start_node.id,
            edge_id=None,
        )
    )

    prev_floor = _floor_of(start_node)

    for i in range(1, len(path)):
        cur = graph.get_node(path[i])
        prev = graph.get_node(path[i - 1])
        edge = _edge_between(graph, prev.id, cur.id)

        text = _transition_text(prev, cur, edge, is_goal=(i == last))
        steps.append(
            PathStep(
                index=len(steps) + 1,
                text=text,
                node_id=cur.id,
                edge_id=edge.id if edge is not None else None,
            )
        )

        if include_floor_changes:
            cur_floor = _floor_of(cur)
            if (
                prev_floor is not None
                and cur_floor is not None
                and cur_floor != prev_floor
            ):
                steps.append(
                    PathStep(
                        index=len(steps) + 1,
                        text=f"Floor change: {prev_floor} -> {cur_floor}",
                        node_id=None,
                        edge_id=None,
                    )
                )
            if cur_floor is not None:
                prev_floor = cur_floor

    return steps


def describe_path(
    graph: TopologyGraph,
    path: Sequence[str],
    *,
    include_floor_changes: bool = True,
) -> list[str]:
    """Render a node-id path as a numbered list of instruction strings.

    Thin wrapper over :func:`path_to_steps` that formats each step as
    ``"N. <text>."``.
    """
    return [
        f"{step.index}. {step.text}."
        for step in path_to_steps(
            graph, path, include_floor_changes=include_floor_changes
        )
    ]


__all__ = ["PathStep", "describe_path", "path_to_steps"]
