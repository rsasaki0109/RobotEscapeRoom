"""Indoor office topology demo.

Run from the repository root:

    python examples/run_indoor_demo.py

Demonstrates how semantic cost functions change the route through the same
graph: a restricted shortcut, a stairs preference, and an elevator preference.
"""

from __future__ import annotations

from pathlib import Path

from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.planner import (
    avoid_restricted,
    avoid_stairs,
    compose_costs,
    plan_astar,
    prefer_elevator,
)
from semantic_toponav.waypoint.semantic_waypoint import path_to_semantic_waypoints

GRAPH_PATH = Path(__file__).parent / "indoor_office.yaml"


def _print_section(title: str) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)


def _print_plan(graph, path):
    print("Path:")
    print("  " + " -> ".join(path))
    print("Semantic Waypoints:")
    for i, wp in enumerate(path_to_semantic_waypoints(graph, path), start=1):
        print(f"  {i}. {wp.instruction}")


def main() -> None:
    graph = load_graph(GRAPH_PATH)
    print(f"Loaded {GRAPH_PATH.name}: {len(graph.node_ids())} nodes, {len(graph.edge_ids())} edges")

    _print_section("1) Default A* — entrance to meeting_room")
    _print_section_note = (
        "Without semantic filters the planner happily takes the cheap "
        "restricted shortcut."
    )
    print(_print_section_note)
    path = plan_astar(graph, "entrance", "meeting_room")
    _print_plan(graph, path)

    _print_section("2) avoid_restricted — entrance to meeting_room")
    print("Reroutes through the lobby and avoids the restricted door.")
    path = plan_astar(graph, "entrance", "meeting_room", cost_fn=avoid_restricted)
    _print_plan(graph, path)

    _print_section("3) Default A* — entrance to office_2f")
    print("Default cost prefers stairs (cost 2) over elevator (cost 3).")
    path = plan_astar(graph, "entrance", "office_2f")
    _print_plan(graph, path)

    _print_section("4) avoid_stairs + prefer_elevator — entrance to office_2f")
    print("Accessibility mode: take the elevator instead.")
    path = plan_astar(
        graph,
        "entrance",
        "office_2f",
        cost_fn=compose_costs(avoid_stairs, prefer_elevator),
    )
    _print_plan(graph, path)


if __name__ == "__main__":
    main()
