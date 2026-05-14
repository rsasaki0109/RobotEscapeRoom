"""Command-line interface for semantic-toponav."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence

from semantic_toponav.cli.editor import register_subcommands as register_editor_subcommands
from semantic_toponav.cli.memory_cli import register_subcommands as register_memory_subcommands
from semantic_toponav.cli.query_cli import register_subcommands as register_query_subcommands
from semantic_toponav.graph.serialization import GraphLoadError, load_graph
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import GraphValidationError, TopologyEdge
from semantic_toponav.memory import (
    avoid_recently_visited,
    prefer_familiar,
    prefer_unvisited,
)
from semantic_toponav.planner import (
    avoid_restricted,
    avoid_stairs,
    block_edge_types,
    block_edges,
    compose_costs,
    default_edge_cost,
    floor_change_penalty,
    plan_astar,
    plan_dijkstra,
    prefer_elevator,
    prefer_floor,
    same_floor_only,
)
from semantic_toponav.planner.errors import NoPathError, PlanningError
from semantic_toponav.waypoint.describe import describe_path, path_to_steps
from semantic_toponav.waypoint.semantic_waypoint import (
    SemanticWaypoint,
    path_to_semantic_waypoints,
)


def _build_cost_fn(args: argparse.Namespace, graph=None) -> Callable[[TopologyEdge], float]:
    fns: list[Callable[[TopologyEdge], float]] = []
    if args.avoid_restricted:
        fns.append(avoid_restricted)
    if args.avoid_stairs:
        fns.append(avoid_stairs)
    if args.prefer_elevator:
        fns.append(prefer_elevator)
    # Dynamic edge availability (id- and type-based blocks).
    blocked_ids = getattr(args, "block_edge", None)
    if blocked_ids:
        fns.append(block_edges(blocked_ids))
    blocked_types = getattr(args, "block_edge_type", None)
    if blocked_types:
        fns.append(block_edge_types(blocked_types))
    # Floor-aware costs require a graph because they look up endpoint floors.
    if graph is not None:
        if getattr(args, "same_floor_only", False):
            fns.append(same_floor_only(graph))
        if getattr(args, "prefer_floor", None) is not None:
            fns.append(prefer_floor(graph, args.prefer_floor))
        penalty = getattr(args, "floor_change_penalty", None)
        if penalty is not None and penalty > 0:
            fns.append(floor_change_penalty(graph, penalty=penalty))
        # Visit-history memory costs.
        if getattr(args, "prefer_unvisited", False):
            fns.append(
                prefer_unvisited(graph, visited_multiplier=args.visited_multiplier)
            )
        if getattr(args, "prefer_familiar", False):
            fns.append(
                prefer_familiar(graph, familiar_multiplier=args.familiar_multiplier)
            )
        within = getattr(args, "avoid_recent", None)
        if within is not None:
            fns.append(
                avoid_recently_visited(
                    graph,
                    within_seconds=within,
                    recent_multiplier=args.recent_multiplier,
                    now=getattr(args, "now", None),
                )
            )
    if not fns:
        return default_edge_cost
    return compose_costs(*fns)


def _run_plan(graph: TopologyGraph, args: argparse.Namespace) -> list[str]:
    cost_fn = _build_cost_fn(args, graph=graph)
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


def cmd_viewer(args: argparse.Namespace) -> int:
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
        from semantic_toponav.visualization.web import save_interactive_html
    except ImportError as exc:
        print(
            f"error: pyvis is required for `viewer`. Install with "
            f"`pip install 'semantic-toponav[viz_web]'` ({exc})",
            file=sys.stderr,
        )
        return 2

    out = save_interactive_html(
        graph,
        args.output,
        path=path,
        use_pose_layout=not args.no_pose_layout,
    )
    print(f"saved {out}")
    if path is not None:
        print(f"highlighted path: {' -> '.join(path)}")
    return 0


def cmd_live_viewer(args: argparse.Namespace) -> int:
    # Validate the graph once up front so a typo doesn't surface only on the
    # first browser hit. Real loading happens on every request anyway.
    try:
        load_graph(args.graph)
    except (GraphLoadError, GraphValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        from semantic_toponav.visualization.live import serve
    except ImportError as exc:
        print(
            f"error: live-viewer requires pyvis. Install with "
            f"`pip install 'semantic-toponav[viz_web]'` ({exc})",
            file=sys.stderr,
        )
        return 2

    print(
        f"serving live view of {args.graph} on http://{args.host}:{args.port} "
        f"(reload check every {args.interval_ms}ms; Ctrl+C to stop)"
    )
    serve(
        args.graph,
        host=args.host,
        port=args.port,
        interval_ms=args.interval_ms,
    )
    return 0


def cmd_describe_path(args: argparse.Namespace) -> int:
    try:
        graph = load_graph(args.graph)
        path = _run_plan(graph, args)
    except (GraphLoadError, GraphValidationError, PlanningError, NoPathError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        steps = path_to_steps(graph, path)
        print(
            json.dumps(
                {
                    "path": path,
                    "steps": [s.to_dict() for s in steps],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(_format_path_text(path))
        print()
        print("Instructions:")
        for line in describe_path(graph, path):
            print(f"  {line}")
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
    p.add_argument("--prefer-floor", type=int, metavar="N", help="prefer routes that stay on floor N")
    p.add_argument(
        "--floor-change-penalty",
        type=float,
        metavar="P",
        help="extra cost added per floor change",
    )
    p.add_argument(
        "--same-floor-only",
        action="store_true",
        help="block edges that cross floors",
    )
    p.add_argument(
        "--block-edge",
        action="append",
        metavar="EDGE_ID",
        help="block a specific edge by id (repeatable)",
    )
    p.add_argument(
        "--block-edge-type",
        action="append",
        metavar="EDGE_TYPE",
        help="block all edges of this type (repeatable)",
    )
    # Visit-history memory costs.
    p.add_argument(
        "--prefer-unvisited",
        action="store_true",
        help="penalize edges that lead to already-visited nodes",
    )
    p.add_argument(
        "--visited-multiplier",
        type=float,
        default=2.0,
        metavar="M",
        help="cost multiplier applied with --prefer-unvisited (default: 2.0)",
    )
    p.add_argument(
        "--prefer-familiar",
        action="store_true",
        help="discount edges that lead to already-visited nodes",
    )
    p.add_argument(
        "--familiar-multiplier",
        type=float,
        default=0.5,
        metavar="M",
        help="cost multiplier applied with --prefer-familiar (default: 0.5)",
    )
    p.add_argument(
        "--avoid-recent",
        type=float,
        metavar="SECONDS",
        help="penalize nodes visited within the past SECONDS",
    )
    p.add_argument(
        "--recent-multiplier",
        type=float,
        default=5.0,
        metavar="M",
        help="cost multiplier applied with --avoid-recent (default: 5.0)",
    )
    p.add_argument(
        "--now",
        type=float,
        metavar="TS",
        help="UNIX timestamp used as 'now' for --avoid-recent (default: wall clock)",
    )
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

    p_describe = sub.add_parser(
        "describe-path",
        help="generate a human-readable step-by-step description of a plan",
    )
    _add_plan_args(p_describe)
    p_describe.set_defaults(func=cmd_describe_path)

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

    p_viewer = sub.add_parser(
        "viewer",
        help="render a graph (and optional path) as an interactive HTML page",
    )
    p_viewer.add_argument("graph", help="path to YAML or JSON topology graph file")
    p_viewer.add_argument(
        "--output",
        "-o",
        default="viewer.html",
        help="output HTML file (default: viewer.html in cwd)",
    )
    p_viewer.add_argument("--start", help="start node id (optional)")
    p_viewer.add_argument("--goal", help="goal node id (optional)")
    p_viewer.add_argument(
        "--algorithm",
        choices=["astar", "dijkstra"],
        default="astar",
        help="planner algorithm when --start/--goal are given (default: astar)",
    )
    p_viewer.add_argument("--avoid-restricted", action="store_true")
    p_viewer.add_argument("--avoid-stairs", action="store_true")
    p_viewer.add_argument("--prefer-elevator", action="store_true")
    p_viewer.add_argument(
        "--no-pose-layout",
        action="store_true",
        help="ignore node poses and let pyvis lay nodes out via physics",
    )
    p_viewer.set_defaults(func=cmd_viewer)

    p_live = sub.add_parser(
        "live-viewer",
        help="run a local HTTP server that auto-refreshes when the graph file changes",
    )
    p_live.add_argument("graph", help="path to YAML or JSON topology graph file")
    p_live.add_argument(
        "--host", default="127.0.0.1", help="interface to bind (default: 127.0.0.1)"
    )
    p_live.add_argument(
        "--port", type=int, default=8765, help="port to listen on (default: 8765)"
    )
    p_live.add_argument(
        "--interval-ms",
        type=int,
        default=1000,
        help="how often the browser polls for changes (default: 1000ms)",
    )
    p_live.set_defaults(func=cmd_live_viewer)

    register_editor_subcommands(sub)
    register_query_subcommands(sub)
    register_memory_subcommands(sub)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
