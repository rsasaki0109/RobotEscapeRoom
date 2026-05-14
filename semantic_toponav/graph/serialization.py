"""YAML/JSON serialization for TopologyGraph."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import (
    GraphValidationError,
    Pose2D,
    TopologyEdge,
    TopologyNode,
)

SCHEMA_VERSION = 1


class GraphLoadError(Exception):
    """Raised when a graph file cannot be parsed."""


def graph_from_dict(data: dict[str, Any]) -> TopologyGraph:
    """Build a TopologyGraph from a plain dict (schema version 1)."""
    if not isinstance(data, dict):
        raise GraphLoadError("graph document must be a mapping")

    version = data.get("version", 1)
    if version != SCHEMA_VERSION:
        raise GraphLoadError(
            f"unsupported graph schema version: {version} (expected {SCHEMA_VERSION})"
        )

    raw_nodes = data.get("nodes", [])
    raw_edges = data.get("edges", [])
    if not isinstance(raw_nodes, list):
        raise GraphLoadError("'nodes' must be a list")
    if not isinstance(raw_edges, list):
        raise GraphLoadError("'edges' must be a list")

    graph = TopologyGraph()

    for i, raw in enumerate(raw_nodes):
        if not isinstance(raw, dict):
            raise GraphLoadError(f"node #{i} is not a mapping")
        try:
            node = _node_from_dict(raw)
        except (KeyError, TypeError, ValueError) as exc:
            raise GraphLoadError(f"invalid node #{i}: {exc}") from exc
        try:
            graph.add_node(node)
        except GraphValidationError as exc:
            raise GraphLoadError(str(exc)) from exc

    for i, raw in enumerate(raw_edges):
        if not isinstance(raw, dict):
            raise GraphLoadError(f"edge #{i} is not a mapping")
        try:
            edge = _edge_from_dict(raw)
        except (KeyError, TypeError, ValueError) as exc:
            raise GraphLoadError(f"invalid edge #{i}: {exc}") from exc
        try:
            graph.add_edge(edge)
        except GraphValidationError as exc:
            raise GraphLoadError(str(exc)) from exc

    return graph


def graph_to_dict(graph: TopologyGraph) -> dict[str, Any]:
    """Serialize a TopologyGraph to a plain dict (schema version 1)."""
    return {
        "version": SCHEMA_VERSION,
        "nodes": [_node_to_dict(n) for n in graph.nodes()],
        "edges": [_edge_to_dict(e) for e in graph.edges()],
    }


def load_graph(path: str | Path) -> TopologyGraph:
    """Load a TopologyGraph from a YAML or JSON file.

    The format is selected by extension: ``.yaml``/``.yml`` or ``.json``.
    """
    p = Path(path)
    if not p.exists():
        raise GraphLoadError(f"graph file not found: {p}")

    suffix = p.suffix.lower()
    text = p.read_text(encoding="utf-8")
    try:
        if suffix in {".yaml", ".yml"}:
            data = yaml.safe_load(text)
        elif suffix == ".json":
            data = json.loads(text)
        else:
            raise GraphLoadError(
                f"unsupported file extension {suffix!r}; expected .yaml, .yml, or .json"
            )
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise GraphLoadError(f"failed to parse {p}: {exc}") from exc

    if data is None:
        raise GraphLoadError(f"graph file is empty: {p}")

    try:
        return graph_from_dict(data)
    except GraphLoadError as exc:
        raise GraphLoadError(f"{p}: {exc}") from exc


def save_graph(graph: TopologyGraph, path: str | Path) -> None:
    """Save a TopologyGraph to YAML or JSON. Format selected by extension."""
    p = Path(path)
    suffix = p.suffix.lower()
    data = graph_to_dict(graph)
    if suffix in {".yaml", ".yml"}:
        p.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
    elif suffix == ".json":
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        raise GraphLoadError(
            f"unsupported file extension {suffix!r}; expected .yaml, .yml, or .json"
        )


def _node_from_dict(data: dict[str, Any]) -> TopologyNode:
    node_id = str(data["id"])
    label = str(data.get("label", node_id))
    node_type = str(data["type"])
    pose_data = data.get("pose")
    pose = Pose2D.from_dict(pose_data) if isinstance(pose_data, dict) else None
    properties = data.get("properties") or {}
    if not isinstance(properties, dict):
        raise TypeError("'properties' must be a mapping")
    return TopologyNode(
        id=node_id,
        label=label,
        type=node_type,
        pose=pose,
        properties=dict(properties),
    )


def _edge_from_dict(data: dict[str, Any]) -> TopologyEdge:
    edge_id = str(data["id"])
    source = str(data["source"])
    target = str(data["target"])
    edge_type = str(data["type"])
    cost = float(data.get("cost", 1.0))
    bidirectional = bool(data.get("bidirectional", True))
    properties = data.get("properties") or {}
    if not isinstance(properties, dict):
        raise TypeError("'properties' must be a mapping")
    return TopologyEdge(
        id=edge_id,
        source=source,
        target=target,
        type=edge_type,
        cost=cost,
        bidirectional=bidirectional,
        properties=dict(properties),
    )


def _node_to_dict(node: TopologyNode) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": node.id,
        "label": node.label,
        "type": node.type,
    }
    if node.pose is not None:
        out["pose"] = node.pose.to_dict()
    out["properties"] = dict(node.properties)
    return out


def _edge_to_dict(edge: TopologyEdge) -> dict[str, Any]:
    return {
        "id": edge.id,
        "source": edge.source,
        "target": edge.target,
        "type": edge.type,
        "cost": edge.cost,
        "bidirectional": edge.bidirectional,
        "properties": dict(edge.properties),
    }
