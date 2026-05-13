"""Indoor office topology demo.

Run from the repository root:

    python examples/run_indoor_demo.py

Demonstrates how semantic cost functions change the route through the same
graph: a restricted shortcut, a stairs preference, and an elevator preference.

When matplotlib is available, also writes one PNG per scenario to
``docs/images/``.
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
IMAGE_DIR = Path(__file__).resolve().parents[1] / "docs" / "images"


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


def _try_save_plot(graph, path, title, filename):
    try:
        from semantic_toponav.visualization.plot import plot_graph
    except ImportError:
        return
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    target = IMAGE_DIR / filename
    plot_graph(graph, path=path, title=title, save_path=str(target), show=False)
    # Close the figure to avoid leaking memory across scenarios.
    import matplotlib.pyplot as plt

    plt.close("all")
    print(f"  [saved {target.relative_to(Path.cwd()) if target.is_absolute() else target}]")


def _scenario(graph, *, title, start, goal, cost_fn, filename, note):
    _print_section(title)
    print(note)
    path = plan_astar(graph, start, goal, cost_fn=cost_fn)
    _print_plan(graph, path)
    _try_save_plot(graph, path, title, filename)
    return path


def main() -> None:
    graph = load_graph(GRAPH_PATH)
    print(f"Loaded {GRAPH_PATH.name}: {len(graph.node_ids())} nodes, {len(graph.edge_ids())} edges")

    _scenario(
        graph,
        title="1) Default A* — entrance to meeting_room",
        start="entrance",
        goal="meeting_room",
        cost_fn=None,
        filename="01_default_to_meeting_room.png",
        note="Without semantic filters the planner happily takes the cheap restricted shortcut.",
    )

    _scenario(
        graph,
        title="2) avoid_restricted — entrance to meeting_room",
        start="entrance",
        goal="meeting_room",
        cost_fn=avoid_restricted,
        filename="02_avoid_restricted_to_meeting_room.png",
        note="Reroutes through the lobby and avoids the restricted door.",
    )

    _scenario(
        graph,
        title="3) Default A* — entrance to office_2f",
        start="entrance",
        goal="office_2f",
        cost_fn=None,
        filename="03_default_to_office_2f.png",
        note="Default cost prefers stairs (cost 2) over elevator (cost 3).",
    )

    _scenario(
        graph,
        title="4) avoid_stairs + prefer_elevator — entrance to office_2f",
        start="entrance",
        goal="office_2f",
        cost_fn=compose_costs(avoid_stairs, prefer_elevator),
        filename="04_avoid_stairs_to_office_2f.png",
        note="Accessibility mode: take the elevator instead.",
    )


if __name__ == "__main__":
    main()
