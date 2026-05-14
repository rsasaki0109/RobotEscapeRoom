"""Multi-floor topology demo.

Run from the repository root:

    python examples/run_multi_floor_demo.py

Loads ``examples/multi_floor_office.yaml`` (3 floors, 17 nodes, 18 edges),
plans the same start/goal under several floor-aware cost configurations,
and saves figures that stack the three floors vertically so the vertical
elevator/stairs columns are visible.
"""

from __future__ import annotations

from pathlib import Path

from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.planner import (
    compose_costs,
    floor_aware_heuristic,
    floor_change_penalty,
    plan_astar,
    prefer_elevator,
    prefer_floor,
)
from semantic_toponav.visualization import plot_graph

GRAPH_PATH = Path(__file__).parent / "multi_floor_office.yaml"
IMAGE_DIR = Path(__file__).resolve().parents[1] / "docs" / "images"


def _print_plan(graph, path):
    print("Path:")
    print("  " + " -> ".join(path))
    floors = [graph.get_node(nid).properties.get("floor") for nid in path]
    print(f"  Floors visited: {floors}")


def _save(graph, path, title, filename):
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    out = IMAGE_DIR / filename
    plot_graph(
        graph,
        path=path,
        title=title,
        save_path=str(out),
        show_labels=True,
        floor_offset=8.0,  # stack floor 2 +8 above floor 1, floor 3 +16, etc.
    )
    import matplotlib.pyplot as plt
    plt.close("all")
    print(f"  saved {out.relative_to(Path.cwd()) if out.is_absolute() else out}")


def main() -> None:
    graph = load_graph(GRAPH_PATH)
    print(f"loaded {GRAPH_PATH.name}: {len(graph.node_ids())} nodes, {len(graph.edge_ids())} edges")

    print()
    print("=" * 60)
    print("1) Default: entrance (1F) -> exec_office_3f (3F)")
    print("=" * 60)
    path = plan_astar(graph, "entrance", "exec_office_3f")
    _print_plan(graph, path)
    _save(graph, path, "default A*: entrance -> exec_office_3f", "09_mf_default.png")

    print()
    print("=" * 60)
    print("2) Accessibility: avoid stairs + prefer elevator")
    print("=" * 60)
    path = plan_astar(
        graph,
        "entrance",
        "exec_office_3f",
        cost_fn=compose_costs(prefer_elevator),
        heuristic_fn=floor_aware_heuristic(floor_height=2.0),
    )
    _print_plan(graph, path)
    _save(graph, path, "prefer elevator: entrance -> exec_office_3f", "10_mf_elevator.png")

    print()
    print("=" * 60)
    print("3) Sightseeing on floor 2: prefer_floor(2)")
    print("=" * 60)
    path = plan_astar(
        graph,
        "entrance",
        "exec_office_3f",
        cost_fn=prefer_floor(graph, 2, off_floor_multiplier=2.5),
    )
    _print_plan(graph, path)
    _save(graph, path, "prefer_floor(2): entrance -> exec_office_3f", "11_mf_prefer_2.png")

    print()
    print("=" * 60)
    print("4) Heavy floor-change penalty stops at lowest floor possible")
    print("=" * 60)
    path = plan_astar(
        graph,
        "entrance",
        "meeting_room_2f",
        cost_fn=floor_change_penalty(graph, penalty=50.0),
    )
    _print_plan(graph, path)
    _save(graph, path, "floor_change_penalty=50: entrance -> meeting_room_2f", "12_mf_floor_penalty.png")


if __name__ == "__main__":
    main()
