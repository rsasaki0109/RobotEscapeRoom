"""CLI subcommands for semantic node queries (`find`, `nearest`)."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from semantic_toponav.cli.editor import _parse_props
from semantic_toponav.graph.serialization import GraphLoadError, load_graph
from semantic_toponav.graph.types import GraphValidationError, TopologyNode
from semantic_toponav.query import (
    NoMatchError,
    find_nodes,
    nearest_node_by_graph_distance,
    nearest_node_by_pose,
    resolve_goal,
)


def _filters_from_args(args: argparse.Namespace) -> dict[str, Any]:
    props: dict[str, Any] | None = None
    if getattr(args, "prop", None):
        try:
            props = _parse_props(args.prop)
        except ValueError as exc:
            raise SystemExit(f"error: {exc}") from exc
        if not props:
            props = None
    return {
        "type": getattr(args, "type", None),
        "label_contains": getattr(args, "label_contains", None),
        "label_equals": getattr(args, "label_equals", None),
        "properties": props,
    }


def _node_summary(n: TopologyNode) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": n.id,
        "label": n.label,
        "type": n.type,
        "properties": dict(n.properties),
    }
    if n.pose is not None:
        out["pose"] = n.pose.to_dict()
    return out


def cmd_find(args: argparse.Namespace) -> int:
    try:
        graph = load_graph(args.graph)
    except (GraphLoadError, GraphValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        filters = _filters_from_args(args)
    except SystemExit as exc:
        print(str(exc.code), file=sys.stderr)
        return 2

    matches = find_nodes(graph, **filters)
    if args.format == "json":
        print(json.dumps([_node_summary(n) for n in matches], ensure_ascii=False, indent=2))
    else:
        if not matches:
            print("(no matches)")
        else:
            print(f"Matches ({len(matches)}):")
            for n in matches:
                pose_part = ""
                if n.pose is not None:
                    pose_part = f"  pose=({n.pose.x:.2f}, {n.pose.y:.2f})"
                print(
                    f"  {n.id:25s} type={n.type:14s} label={n.label!r}{pose_part}"
                )
    return 0


def cmd_nearest(args: argparse.Namespace) -> int:
    try:
        graph = load_graph(args.graph)
    except (GraphLoadError, GraphValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if (args.from_pose is None) == (args.from_node is None):
        print(
            "error: pass exactly one of --from-pose X Y or --from-node ID",
            file=sys.stderr,
        )
        return 2

    try:
        filters = _filters_from_args(args)
    except SystemExit as exc:
        print(str(exc.code), file=sys.stderr)
        return 2

    payload: dict[str, Any]
    try:
        if args.from_pose is not None:
            x, y = args.from_pose
            node = nearest_node_by_pose(graph, (x, y), **filters)
            payload = {"mode": "euclidean", "node": _node_summary(node)}
        else:
            node, path = nearest_node_by_graph_distance(
                graph, args.from_node, **filters
            )
            payload = {
                "mode": "graph_distance",
                "node": _node_summary(node),
                "path": path,
            }
    except NoMatchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Nearest ({payload['mode']}):")
        n = payload["node"]
        print(f"  id    : {n['id']}")
        print(f"  type  : {n['type']}")
        print(f"  label : {n['label']!r}")
        if "pose" in n:
            print(f"  pose  : ({n['pose']['x']:.2f}, {n['pose']['y']:.2f})")
        if "path" in payload:
            print("  path  : " + " -> ".join(payload["path"]))
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    try:
        graph = load_graph(args.graph)
    except (GraphLoadError, GraphValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    text = " ".join(args.text) if isinstance(args.text, list) else args.text
    candidates = resolve_goal(graph, text, top_k=args.top_k)

    if args.format == "json":
        payload = {
            "query": text,
            "candidates": [
                {
                    "node_id": c.node_id,
                    "score": c.score,
                    "reasons": list(c.reasons),
                    "node": _node_summary(c.node),
                }
                for c in candidates
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if not candidates:
            print("(no matches)")
        else:
            print(f"Candidates ({len(candidates)}):")
            for c in candidates:
                print(
                    f"  {c.node_id:25s} score={c.score:<5g} "
                    f"label={c.node.label!r} type={c.node.type}"
                )
                for reason in c.reasons:
                    print(f"      - {reason}")
    return 0


def _add_filter_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--type", help="filter by node type")
    p.add_argument("--label-contains", help="case-insensitive substring match on label")
    p.add_argument("--label-equals", help="exact label match")
    p.add_argument(
        "--prop",
        action="append",
        metavar="KEY=VALUE",
        help="filter by property (repeatable; int/float/bool inferred)",
    )
    p.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="output format (default: text)",
    )


def register_subcommands(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("find", help="list nodes matching semantic filters")
    p.add_argument("graph")
    _add_filter_args(p)
    p.set_defaults(func=cmd_find)

    p = sub.add_parser(
        "nearest",
        help="find the nearest matching node (Euclidean from --from-pose or "
        "graph-distance from --from-node)",
    )
    p.add_argument("graph")
    p.add_argument(
        "--from-pose",
        type=float,
        nargs=2,
        metavar=("X", "Y"),
        help="Euclidean reference pose",
    )
    p.add_argument(
        "--from-node",
        metavar="NODE_ID",
        help="graph-distance reference node",
    )
    _add_filter_args(p)
    p.set_defaults(func=cmd_nearest)

    p = sub.add_parser(
        "resolve",
        help="resolve a free-text goal (e.g. 'the second floor lab') to "
        "ranked candidate nodes",
    )
    p.add_argument("graph")
    p.add_argument(
        "text",
        nargs="+",
        help="natural-language description of the goal "
        "(multiple words are joined with spaces)",
    )
    p.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="return at most this many candidates (default: 5)",
    )
    p.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="output format (default: text)",
    )
    p.set_defaults(func=cmd_resolve)
