"""Memory subcommands for the semantic-toponav CLI.

Lets users record / inspect / clear visit history on a topology graph
file from the shell. Mutating commands follow the same output convention
as the editor commands: print to stdout by default, ``--out FILE`` or
``--in-place`` writes to disk.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from semantic_toponav.cli.editor import _add_output_args, _write_or_print
from semantic_toponav.graph.serialization import GraphLoadError, load_graph
from semantic_toponav.graph.types import GraphValidationError
from semantic_toponav.memory import (
    clear_history,
    last_visited,
    record_path,
    record_visit,
    visit_count,
)


def cmd_record_visit(args: argparse.Namespace) -> int:
    try:
        graph = load_graph(args.graph)
    except (GraphLoadError, GraphValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        record_visit(graph, args.node, now=args.now)
    except KeyError as exc:
        print(f"error: unknown node {exc}", file=sys.stderr)
        return 2
    return _write_or_print(
        graph, source=Path(args.graph), out=args.out, in_place=args.in_place
    )


def cmd_record_path(args: argparse.Namespace) -> int:
    try:
        graph = load_graph(args.graph)
    except (GraphLoadError, GraphValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        record_path(graph, args.nodes, now=args.now)
    except KeyError as exc:
        print(f"error: unknown node {exc}", file=sys.stderr)
        return 2
    return _write_or_print(
        graph, source=Path(args.graph), out=args.out, in_place=args.in_place
    )


def cmd_clear_history(args: argparse.Namespace) -> int:
    try:
        graph = load_graph(args.graph)
    except (GraphLoadError, GraphValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        clear_history(graph, args.nodes or None)
    except KeyError as exc:
        print(f"error: unknown node {exc}", file=sys.stderr)
        return 2
    return _write_or_print(
        graph, source=Path(args.graph), out=args.out, in_place=args.in_place
    )


def cmd_history(args: argparse.Namespace) -> int:
    try:
        graph = load_graph(args.graph)
    except (GraphLoadError, GraphValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    node_ids = args.nodes or graph.node_ids()
    rows: list[tuple[str, int, float | None]] = []
    for nid in node_ids:
        try:
            count = visit_count(graph, nid)
            ts = last_visited(graph, nid)
        except KeyError as exc:
            print(f"error: unknown node {exc}", file=sys.stderr)
            return 2
        rows.append((nid, count, ts))
    if not args.all:
        rows = [r for r in rows if r[1] > 0]
    if not rows:
        print("(no visit history)")
        return 0
    print(f"{'node':25s} {'count':>6s}  last_visited")
    for nid, count, ts in rows:
        ts_part = f"{ts:.3f}" if ts is not None else "-"
        print(f"{nid:25s} {count:>6d}  {ts_part}")
    return 0


def register_subcommands(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "record-visit", help="mark a node as visited in a topology graph file"
    )
    p.add_argument("graph")
    p.add_argument("node", help="node id to record a visit for")
    p.add_argument(
        "--now",
        type=float,
        help="UNIX timestamp to record (default: wall clock at run time)",
    )
    _add_output_args(p)
    p.set_defaults(func=cmd_record_visit)

    p = sub.add_parser(
        "record-path",
        help="mark every node in a path as visited with a single timestamp",
    )
    p.add_argument("graph")
    p.add_argument("nodes", nargs="+", help="node ids traversed (in order)")
    p.add_argument("--now", type=float)
    _add_output_args(p)
    p.set_defaults(func=cmd_record_path)

    p = sub.add_parser("clear-history", help="drop visit history (default: all nodes)")
    p.add_argument("graph")
    p.add_argument("nodes", nargs="*", help="node ids to clear (default: every node)")
    _add_output_args(p)
    p.set_defaults(func=cmd_clear_history)

    p = sub.add_parser("history", help="show visit counts and timestamps")
    p.add_argument("graph")
    p.add_argument("nodes", nargs="*", help="node ids to show (default: every node)")
    p.add_argument(
        "--all",
        action="store_true",
        help="include unvisited nodes (default: only visited)",
    )
    p.set_defaults(func=cmd_history)
