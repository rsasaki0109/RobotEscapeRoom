"""Visit-history memory layer demo.

Run from the repository root:

    python examples/memory_demo.py

Demonstrates how recording visited nodes biases subsequent plans:

1. Default plan on a multi-floor office.
2. After visiting one branch, ``prefer_unvisited`` steers the planner
   toward the unexplored part of the graph (good for coverage).
3. After completing a familiar tour, ``prefer_familiar`` makes the
   planner retrace that tour for new requests (good for safety / reuse).
4. ``avoid_recently_visited`` adds a time decay so visits from long ago
   stop influencing the plan.
"""

from __future__ import annotations

from pathlib import Path

from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.memory import (
    avoid_recently_visited,
    clear_history,
    prefer_familiar,
    prefer_unvisited,
    record_path,
)
from semantic_toponav.planner import compose_costs, plan_astar

GRAPH_PATH = Path(__file__).parent / "multi_floor_office.yaml"


def _show(label: str, path: list[str]) -> None:
    print(f"{label:28s} {' -> '.join(path)}")


def main() -> None:
    graph = load_graph(GRAPH_PATH)

    print("=== 1. Default plan (no memory) ===")
    p0 = plan_astar(graph, "entrance", "exec_office_3f")
    _show("default", p0)

    print("\n=== 2. prefer_unvisited after touring the stairs ===")
    record_path(graph, p0, now=1000.0)
    p1 = plan_astar(
        graph, "entrance", "exec_office_3f",
        cost_fn=prefer_unvisited(graph, visited_multiplier=4.0),
    )
    _show("after stairs tour", p1)

    print("\n=== 3. prefer_familiar — retrace the known route ===")
    clear_history(graph)
    record_path(graph, p0, now=2000.0)
    p2 = plan_astar(
        graph, "entrance", "exec_office_3f",
        cost_fn=prefer_familiar(graph),
    )
    _show("retraced route", p2)

    print("\n=== 4. avoid_recently_visited with a fresh visit ===")
    clear_history(graph)
    # Robot just walked through the stairs branch a few seconds ago.
    record_path(graph, p0, now=3000.0)
    cost = compose_costs(
        avoid_recently_visited(graph, within_seconds=60.0, recent_multiplier=10.0, now=3010.0)
    )
    p3 = plan_astar(graph, "entrance", "exec_office_3f", cost_fn=cost)
    _show("recent stairs penalty", p3)

    print("\n=== 5. same window, but visits are now old ===")
    cost_old = compose_costs(
        avoid_recently_visited(graph, within_seconds=60.0, recent_multiplier=10.0, now=9999.0)
    )
    p4 = plan_astar(graph, "entrance", "exec_office_3f", cost_fn=cost_old)
    _show("memory has decayed", p4)


if __name__ == "__main__":
    main()
