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

from semantic_toponav.graph.compaction import compact_graph
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


BACKUP_SUFFIX = ".bak"


def _backup_path(path: Path) -> Path:
    return path.with_name(path.name + BACKUP_SUFFIX)


def _create_backup(target_path: Path) -> Path | None:
    """Copy target to target.bak if target exists. Returns the backup path."""
    if not target_path.exists():
        return None
    backup = _backup_path(target_path)
    backup.write_bytes(target_path.read_bytes())
    return backup


def _write_or_print(
    graph: TopologyGraph,
    *,
    source: Path,
    out: str | None,
    in_place: bool,
    no_backup: bool = False,
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
        if not no_backup:
            backup = _create_backup(target_path)
            if backup is not None:
                print(f"backup: {backup}", file=sys.stderr)
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
        graph,
        source=Path(args.graph),
        out=args.out,
        in_place=args.in_place,
        no_backup=getattr(args, "no_backup", False),
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
        graph,
        source=Path(args.graph),
        out=args.out,
        in_place=args.in_place,
        no_backup=getattr(args, "no_backup", False),
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
        graph,
        source=Path(args.graph),
        out=args.out,
        in_place=args.in_place,
        no_backup=getattr(args, "no_backup", False),
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
        graph,
        source=Path(args.graph),
        out=args.out,
        in_place=args.in_place,
        no_backup=getattr(args, "no_backup", False),
    )


def cmd_compact(args: argparse.Namespace) -> int:
    try:
        graph = load_graph(args.graph)
    except (GraphLoadError, GraphValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.edge_cost_tolerance is None:
        edge_cost_tol = float("inf")
    else:
        edge_cost_tol = args.edge_cost_tolerance

    try:
        result = compact_graph(
            graph,
            endpoint_tolerance=args.endpoint_tolerance,
            edge_cost_tolerance=edge_cost_tol,
            keep_strategy=args.keep_strategy,
        )
    except (ValueError, GraphValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(
        f"merged {len(result.merged_nodes)} node(s); collapsed "
        f"{len(result.collapsed_edges)} parallel edge(s); dropped "
        f"{len(result.dropped_self_loops)} self-loop(s)",
        file=sys.stderr,
    )

    return _write_or_print(
        graph,
        source=Path(args.graph),
        out=args.out,
        in_place=args.in_place,
        no_backup=getattr(args, "no_backup", False),
    )


def cmd_undo(args: argparse.Namespace) -> int:
    target = Path(args.graph)
    backup = _backup_path(target)
    if not backup.exists():
        print(f"error: no backup found at {backup}", file=sys.stderr)
        return 2

    if not target.exists():
        # No current file — just rename the backup back.
        backup.rename(target)
        print(f"restored {target} from {backup}", file=sys.stderr)
        return 0

    # Swap target <-> backup so undo is reversible (call again to redo).
    current_bytes = target.read_bytes()
    backup_bytes = backup.read_bytes()
    target.write_bytes(backup_bytes)
    backup.write_bytes(current_bytes)
    print(f"swapped {target} and {backup}", file=sys.stderr)
    return 0


def _node_summary(node: TopologyNode) -> str:
    pose = ""
    if node.pose is not None:
        pose = f", pose=({node.pose.x:.2f}, {node.pose.y:.2f})"
    return f"type={node.type}, label={node.label!r}{pose}"


def _edge_summary(edge: TopologyEdge) -> str:
    arrow = "<->" if edge.bidirectional else "->"
    return (
        f"{edge.source} {arrow} {edge.target}, type={edge.type}, cost={edge.cost}"
    )


def _node_fields(node: TopologyNode) -> dict[str, Any]:
    pose: tuple[float, float, float, str] | None = None
    if node.pose is not None:
        pose = (node.pose.x, node.pose.y, node.pose.yaw, node.pose.frame_id)
    return {
        "label": node.label,
        "type": node.type,
        "pose": pose,
        "properties": dict(node.properties),
    }


def _edge_fields(edge: TopologyEdge) -> dict[str, Any]:
    return {
        "source": edge.source,
        "target": edge.target,
        "type": edge.type,
        "cost": edge.cost,
        "bidirectional": edge.bidirectional,
        "properties": dict(edge.properties),
    }


def _graph_diff_lines(
    left: TopologyGraph, right: TopologyGraph
) -> list[str]:
    """Return a structural diff between two graphs as printable lines."""
    lines: list[str] = []

    left_nodes = {n.id: n for n in left.nodes()}
    right_nodes = {n.id: n for n in right.nodes()}
    added_n = sorted(set(right_nodes) - set(left_nodes))
    removed_n = sorted(set(left_nodes) - set(right_nodes))
    common_n = sorted(set(left_nodes) & set(right_nodes))
    modified_n: list[tuple[str, dict[str, tuple[Any, Any]]]] = []
    for nid in common_n:
        lf, rf = _node_fields(left_nodes[nid]), _node_fields(right_nodes[nid])
        if lf != rf:
            changed = {k: (lf[k], rf[k]) for k in lf if lf[k] != rf[k]}
            modified_n.append((nid, changed))

    left_edges = {e.id: e for e in left.edges()}
    right_edges = {e.id: e for e in right.edges()}
    added_e = sorted(set(right_edges) - set(left_edges))
    removed_e = sorted(set(left_edges) - set(right_edges))
    common_e = sorted(set(left_edges) & set(right_edges))
    modified_e: list[tuple[str, dict[str, tuple[Any, Any]]]] = []
    for eid in common_e:
        lf, rf = _edge_fields(left_edges[eid]), _edge_fields(right_edges[eid])
        if lf != rf:
            changed = {k: (lf[k], rf[k]) for k in lf if lf[k] != rf[k]}
            modified_e.append((eid, changed))

    if not (added_n or removed_n or modified_n or added_e or removed_e or modified_e):
        return ["(graphs are identical)"]

    if added_n or removed_n or modified_n:
        lines.append("nodes:")
        for nid in removed_n:
            lines.append(f"  - {nid}  ({_node_summary(left_nodes[nid])})")
        for nid in added_n:
            lines.append(f"  + {nid}  ({_node_summary(right_nodes[nid])})")
        for nid, changed in modified_n:
            lines.append(f"  ~ {nid}")
            for key, (lv, rv) in changed.items():
                lines.append(f"      {key}: {lv!r} -> {rv!r}")

    if added_e or removed_e or modified_e:
        lines.append("edges:")
        for eid in removed_e:
            lines.append(f"  - {eid}  ({_edge_summary(left_edges[eid])})")
        for eid in added_e:
            lines.append(f"  + {eid}  ({_edge_summary(right_edges[eid])})")
        for eid, changed in modified_e:
            lines.append(f"  ~ {eid}")
            for key, (lv, rv) in changed.items():
                lines.append(f"      {key}: {lv!r} -> {rv!r}")

    return lines


def _load_graph_relaxed(path: Path) -> TopologyGraph:
    """Like ``load_graph`` but tolerates a ``.bak`` suffix.

    When the path ends in ``.bak`` we look at the *previous* extension to
    pick the loader. This lets ``diff`` and ``undo`` compare against the
    backup file directly without renaming.
    """
    real = path
    if path.suffix == BACKUP_SUFFIX:
        stem = path.with_suffix("")  # strip .bak
        if stem.suffix.lower() in {".yaml", ".yml", ".json"}:
            real = stem  # only used to decide format; actual bytes still read from `path`
            import tempfile

            data = path.read_bytes()
            with tempfile.NamedTemporaryFile(
                suffix=real.suffix, delete=False
            ) as fh:
                fh.write(data)
                tmp = Path(fh.name)
            try:
                return load_graph(tmp)
            finally:
                tmp.unlink(missing_ok=True)
    return load_graph(real)


def cmd_diff(args: argparse.Namespace) -> int:
    """Show the structural difference between two graph files.

    With one positional arg, the graph is compared against its ``.bak``
    backup. With two positional args, ``diff A B`` treats ``A`` as the
    base and ``B`` as the new file (same convention as unix ``diff``).
    """
    if args.other is None:
        new_path = Path(args.graph)
        base_path = _backup_path(new_path)
    else:
        base_path = Path(args.graph)
        new_path = Path(args.other)

    for label, p in (("base", base_path), ("new", new_path)):
        if not p.exists():
            print(f"error: {label} graph not found at {p}", file=sys.stderr)
            return 2
    try:
        base = _load_graph_relaxed(base_path)
        new = _load_graph_relaxed(new_path)
    except (GraphLoadError, GraphValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    lines = _graph_diff_lines(base, new)
    print(f"--- {base_path}")
    print(f"+++ {new_path}")
    for line in lines:
        print(line)
    return 0 if lines == ["(graphs are identical)"] else 1


def _add_output_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--out", help="write the modified graph to this path (else stdout)")
    p.add_argument(
        "--in-place",
        action="store_true",
        help="overwrite the input file in place",
    )
    p.add_argument(
        "--no-backup",
        action="store_true",
        help="skip writing a .bak file before overwriting",
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

    p = sub.add_parser(
        "compact",
        help=(
            "merge nearby nodes and collapse parallel duplicate edges "
            "(lossy graph compaction)"
        ),
    )
    p.add_argument("graph", help="path to topology graph (.yaml / .json)")
    p.add_argument(
        "--endpoint-tolerance",
        type=float,
        default=0.0,
        metavar="METERS",
        help=(
            "merge posed nodes within this Euclidean distance "
            "(default: 0.0 — node merging disabled)"
        ),
    )
    p.add_argument(
        "--edge-cost-tolerance",
        type=float,
        default=None,
        metavar="COST",
        help=(
            "max cost spread within a parallel-edge group that still "
            "allows the group to collapse (default: unlimited)"
        ),
    )
    p.add_argument(
        "--keep-strategy",
        choices=["shortest", "longest", "first"],
        default="shortest",
        help="which edge survives a collapse (default: shortest)",
    )
    _add_output_args(p)
    p.set_defaults(func=cmd_compact)

    p = sub.add_parser(
        "undo",
        help="revert the most recent in-place edit by swapping with its .bak",
    )
    p.add_argument("graph")
    p.set_defaults(func=cmd_undo)

    p = sub.add_parser(
        "diff",
        help="show the structural diff between two graphs (or against .bak)",
    )
    p.add_argument("graph")
    p.add_argument(
        "other",
        nargs="?",
        help="second graph (default: <graph>.bak)",
    )
    p.set_defaults(func=cmd_diff)
