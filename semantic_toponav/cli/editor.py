"""Editor-style subcommands for the semantic-toponav CLI.

These commands let users inspect and modify topology graph files without
hand-editing YAML/JSON.

All mutating commands default to printing the modified graph to stdout in
the *same format* as the input. Pass ``--out FILE`` (or ``--in-place``) to
write to disk.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from semantic_toponav.graph.serialization import (
    GraphLoadError,
    graph_to_dict,
    load_graph,
)
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import (
    GraphValidationError,
    Pose2D,
    TopologyEdge,
    TopologyNode,
)


def _coerce_value(raw: str) -> Any:
    if raw.lower() in {"true", "false"}:
        return raw.lower() == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def _parse_props(items: list[str] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"--prop entries must be KEY=VALUE, got {item!r}")
        key, value = item.split("=", 1)
        if not key:
            raise ValueError(f"--prop entry has empty key: {item!r}")
        out[key] = _coerce_value(value)
    return out


def _serialize(graph: TopologyGraph, fmt: str) -> str:
    data = graph_to_dict(graph)
    if fmt == "json":
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _format_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix in {".yaml", ".yml"}:
        return "yaml"
    raise GraphLoadError(
        f"unsupported file extension {suffix!r}; expected .yaml, .yml, or .json"
    )


def _write_or_print(
    graph: TopologyGraph,
    *,
    source: Path,
    out: str | None,
    in_place: bool,
) -> int:
    """Write the graph to `out` / `source` / stdout. Returns a CLI exit code."""
    if out and in_place:
        print("error: pass at most one of --out and --in-place", file=sys.stderr)
        return 2

    target_path: Path | None = None
    if in_place:
        target_path = source
    elif out:
        target_path = Path(out)

    if target_path is not None:
        text = _serialize(graph, _format_for(target_path))
        target_path.write_text(text, encoding="utf-8")
        print(f"wrote {target_path}", file=sys.stderr)
    else:
        text = _serialize(graph, _format_for(source))
        sys.stdout.write(text)
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    try:
        graph = load_graph(args.graph)
    except (GraphLoadError, GraphValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    nodes = list(graph.nodes())
    edges = list(graph.edges())
    if args.type:
        nodes = [n for n in nodes if n.type == args.type]
        edges = [e for e in edges if e.type == args.type]

    show_nodes = args.nodes or not (args.nodes or args.edges)
    show_edges = args.edges or not (args.nodes or args.edges)

    print(f"{args.graph}: {len(graph.node_ids())} nodes, {len(graph.edge_ids())} edges")

    type_counts: dict[str, int] = {}
    for n in graph.nodes():
        type_counts[f"node:{n.type}"] = type_counts.get(f"node:{n.type}", 0) + 1
    for e in graph.edges():
        type_counts[f"edge:{e.type}"] = type_counts.get(f"edge:{e.type}", 0) + 1
    if type_counts:
        print("  types:")
        for k in sorted(type_counts):
            print(f"    {k}: {type_counts[k]}")

    if show_nodes:
        print()
        print(f"Nodes ({len(nodes)}):")
        for n in nodes:
            pose_part = ""
            if n.pose is not None:
                pose_part = f"  pose=({n.pose.x:.2f}, {n.pose.y:.2f})"
            print(f"  {n.id:25s} type={n.type:14s} label={n.label!r}{pose_part}")

    if show_edges:
        print()
        print(f"Edges ({len(edges)}):")
        for e in edges:
            arrow = "<->" if e.bidirectional else "-->"
            print(
                f"  {e.id:35s} {e.source:20s} {arrow} {e.target:20s} "
                f"type={e.type:20s} cost={e.cost}"
            )
    return 0


def cmd_add_node(args: argparse.Namespace) -> int:
    try:
        graph = load_graph(args.graph)
    except (GraphLoadError, GraphValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if (args.x is None) ^ (args.y is None):
        print("error: --x and --y must be provided together", file=sys.stderr)
        return 2

    pose: Pose2D | None = None
    if args.x is not None and args.y is not None:
        pose = Pose2D(x=args.x, y=args.y, yaw=args.yaw, frame_id=args.frame_id)

    try:
        properties = _parse_props(args.prop)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    node = TopologyNode(
        id=args.id,
        label=args.label or args.id,
        type=args.type,
        pose=pose,
        properties=properties,
    )
    try:
        graph.add_node(node)
    except GraphValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    return _write_or_print(
        graph, source=Path(args.graph), out=args.out, in_place=args.in_place
    )


def cmd_add_edge(args: argparse.Namespace) -> int:
    try:
        graph = load_graph(args.graph)
    except (GraphLoadError, GraphValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        properties = _parse_props(args.prop)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    edge_id = args.id or f"{args.source}__{args.target}"
    edge = TopologyEdge(
        id=edge_id,
        source=args.source,
        target=args.target,
        type=args.type,
        cost=args.cost,
        bidirectional=not args.one_way,
        properties=properties,
    )
    try:
        graph.add_edge(edge)
    except GraphValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    return _write_or_print(
        graph, source=Path(args.graph), out=args.out, in_place=args.in_place
    )


def cmd_rm_node(args: argparse.Namespace) -> int:
    try:
        graph = load_graph(args.graph)
    except (GraphLoadError, GraphValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        removed = graph.remove_node(args.id)
    except GraphValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if removed:
        print(
            f"removed {len(removed)} incident edge(s): {', '.join(removed)}",
            file=sys.stderr,
        )
    return _write_or_print(
        graph, source=Path(args.graph), out=args.out, in_place=args.in_place
    )


def cmd_rm_edge(args: argparse.Namespace) -> int:
    try:
        graph = load_graph(args.graph)
    except (GraphLoadError, GraphValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        graph.remove_edge(args.id)
    except GraphValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return _write_or_print(
        graph, source=Path(args.graph), out=args.out, in_place=args.in_place
    )


def _add_output_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--out", help="write the modified graph to this path (else stdout)")
    p.add_argument(
        "--in-place",
        action="store_true",
        help="overwrite the input file in place",
    )


def register_subcommands(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("inspect", help="summarize a topology graph")
    p.add_argument("graph")
    p.add_argument("--nodes", action="store_true", help="list nodes")
    p.add_argument("--edges", action="store_true", help="list edges")
    p.add_argument("--type", help="filter by node or edge type")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("add-node", help="add a node to a topology graph")
    p.add_argument("graph")
    p.add_argument("id", help="new node id")
    p.add_argument("--type", required=True, help="node type (e.g. room, corridor)")
    p.add_argument("--label", help="human-readable label (defaults to id)")
    p.add_argument("--x", type=float, help="pose x")
    p.add_argument("--y", type=float, help="pose y")
    p.add_argument("--yaw", type=float, default=0.0, help="pose yaw (default: 0.0)")
    p.add_argument("--frame-id", default="map", help="pose frame_id (default: map)")
    p.add_argument(
        "--prop",
        action="append",
        metavar="KEY=VALUE",
        help="custom property (repeatable; int/float/bool inferred)",
    )
    _add_output_args(p)
    p.set_defaults(func=cmd_add_node)

    p = sub.add_parser("add-edge", help="add an edge to a topology graph")
    p.add_argument("graph")
    p.add_argument("source")
    p.add_argument("target")
    p.add_argument("--type", required=True, help="edge type (e.g. traversable)")
    p.add_argument("--id", help="edge id (default: SOURCE__TARGET)")
    p.add_argument("--cost", type=float, default=1.0)
    p.add_argument("--one-way", action="store_true", help="make the edge one-way")
    p.add_argument("--prop", action="append", metavar="KEY=VALUE")
    _add_output_args(p)
    p.set_defaults(func=cmd_add_edge)

    p = sub.add_parser("rm-node", help="remove a node and its incident edges")
    p.add_argument("graph")
    p.add_argument("id", help="node id to remove")
    _add_output_args(p)
    p.set_defaults(func=cmd_rm_node)

    p = sub.add_parser("rm-edge", help="remove an edge")
    p.add_argument("graph")
    p.add_argument("id", help="edge id to remove")
    _add_output_args(p)
    p.set_defaults(func=cmd_rm_edge)
