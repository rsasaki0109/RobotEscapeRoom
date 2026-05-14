"""Command-line interface for semantic-toponav."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence

from semantic_toponav.graph.serialization import GraphLoadError, load_graph
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import GraphValidationError, TopologyEdge
from semantic_toponav.planner import (
    avoid_restricted,
    avoid_stairs,
    compose_costs,
    default_edge_cost,
    plan_astar,
    plan_dijkstra,
    prefer_elevator,
)
from semantic_toponav.planner.errors import NoPathError, PlanningError
from semantic_toponav.waypoint.semantic_waypoint import (
    SemanticWaypoint,
    path_to_semantic_waypoints,
)


def _build_cost_fn(args: argparse.Namespace) -> Callable[[TopologyEdge], float]:
    fns: list[Callable[[TopologyEdge], float]] = []
    if args.avoid_restricted:
        fns.append(avoid_restricted)
    if args.avoid_stairs:
        fns.append(avoid_stairs)
    if args.prefer_elevator:
        fns.append(prefer_elevator)
    if not fns:
        return default_edge_cost
    return compose_costs(*fns)


def _run_plan(graph: TopologyGraph, args: argparse.Namespace) -> list[str]:
    cost_fn = _build_cost_fn(args)
    if args.algorithm == "dijkstra":
        return plan_dijkstra(graph, args.start, args.goal, cost_fn=cost_fn)
    return plan_astar(graph, args.start, args.goal, cost_fn=cost_fn)


def _format_path_text(path: list[str]) -> str:
    return "Path:\n  " + " -> ".join(path)


def _format_waypoints_text(waypoints: list[SemanticWaypoint]) -> str:
    lines = ["Semantic Waypoints:"]
    for i, wp in enumerate(waypoints, start=1):
        lines.append(f"  {i}. {wp.instruction}")
    return "\n".join(lines)


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        graph = load_graph(args.graph)
        graph.validate()
    except (GraphLoadError, GraphValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        f"ok: {args.graph} ({len(graph.node_ids())} nodes, {len(graph.edge_ids())} edges)"
    )
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    try:
        graph = load_graph(args.graph)
        path = _run_plan(graph, args)
    except (GraphLoadError, GraphValidationError, PlanningError, NoPathError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps({"path": path}, ensure_ascii=False, indent=2))
    else:
        print(_format_path_text(path))
    return 0


def cmd_plot(args: argparse.Namespace) -> int:
    try:
        graph = load_graph(args.graph)
    except (GraphLoadError, GraphValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    path: list[str] | None = None
    if args.start and args.goal:
        try:
            path = _run_plan(graph, args)
        except (PlanningError, NoPathError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    elif args.start or args.goal:
        print("error: --start and --goal must be provided together", file=sys.stderr)
        return 2

    try:
        from semantic_toponav.visualization.plot import plot_graph
    except ImportError as exc:
        print(
            f"error: matplotlib is required for `plot`. Install with "
            f"`pip install 'semantic-toponav[viz]'` ({exc})",
            file=sys.stderr,
        )
        return 2

    title = args.title or (f"{args.start} -> {args.goal}" if path else None)
    plot_graph(
        graph,
        path=path,
        title=title,
        save_path=args.save,
        show=args.show,
        show_edge_ids=args.edge_ids,
    )
    if args.save:
        print(f"saved {args.save}")
    return 0


def cmd_waypoints(args: argparse.Namespace) -> int:
    try:
        graph = load_graph(args.graph)
        path = _run_plan(graph, args)
        waypoints = path_to_semantic_waypoints(graph, path)
    except (GraphLoadError, GraphValidationError, PlanningError, NoPathError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(
            json.dumps(
                {
                    "path": path,
                    "waypoints": [wp.to_dict() for wp in waypoints],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(_format_path_text(path))
        print()
        print(_format_waypoints_text(waypoints))
    return 0


def _add_plan_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("graph", help="path to YAML or JSON topology graph file")
    p.add_argument("start", help="start node id")
    p.add_argument("goal", help="goal node id")
    p.add_argument(
        "--algorithm",
        choices=["astar", "dijkstra"],
        default="astar",
        help="planner algorithm (default: astar)",
    )
    p.add_argument("--avoid-restricted", action="store_true", help="block restricted edges")
    p.add_argument("--avoid-stairs", action="store_true", help="penalize stairs edges")
    p.add_argument("--prefer-elevator", action="store_true", help="discount elevator edges")
    p.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="output format (default: text)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="semantic-toponav",
        description="Semantic topological map navigation CLI.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="validate a graph file")
    p_validate.add_argument("graph", help="path to YAML or JSON topology graph file")
    p_validate.set_defaults(func=cmd_validate)

    p_plan = sub.add_parser("plan", help="plan a path between two nodes")
    _add_plan_args(p_plan)
    p_plan.set_defaults(func=cmd_plan)

    p_waypoints = sub.add_parser("waypoints", help="generate semantic waypoints for a plan")
    _add_plan_args(p_waypoints)
    p_waypoints.set_defaults(func=cmd_waypoints)

    p_plot = sub.add_parser("plot", help="render a graph (and optional path) with matplotlib")
    p_plot.add_argument("graph", help="path to YAML or JSON topology graph file")
    p_plot.add_argument("--start", help="start node id (optional)")
    p_plot.add_argument("--goal", help="goal node id (optional)")
    p_plot.add_argument(
        "--algorithm",
        choices=["astar", "dijkstra"],
        default="astar",
        help="planner algorithm when --start/--goal are given (default: astar)",
    )
    p_plot.add_argument("--avoid-restricted", action="store_true")
    p_plot.add_argument("--avoid-stairs", action="store_true")
    p_plot.add_argument("--prefer-elevator", action="store_true")
    p_plot.add_argument("--save", help="save the figure to this path (e.g., out.png)")
    p_plot.add_argument("--show", action="store_true", help="open an interactive window")
    p_plot.add_argument("--edge-ids", action="store_true", help="annotate edge ids")
    p_plot.add_argument("--title", help="override plot title")
    p_plot.set_defaults(func=cmd_plot)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
