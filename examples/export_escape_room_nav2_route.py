"""Hand the escape-room topology to the Nav2 Route Server.

Exports the full ``robot_escape_room.yaml`` graph so Nav2 can plan over the
same semantic nodes T-0 visits in the Python escape-room runner.

    pip install -e .
    python examples/export_escape_room_nav2_route.py
"""

from __future__ import annotations

from pathlib import Path

from semantic_toponav.conversion import write_nav2_geojson
from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.planner import (
    avoid_restricted,
    compose_costs,
    plan_astar,
    prefer_elevator,
)

ROOT = Path(__file__).parent.parent
GRAPH = ROOT / "examples" / "robot_escape_room.yaml"
OUT_DIR = ROOT / "examples" / "data" / "nav2"
START, GOAL = "holding_cell", "maintenance_exit"


def main() -> None:
    graph = load_graph(str(GRAPH))
    cost_fn = compose_costs(prefer_elevator, avoid_restricted)
    route = plan_astar(graph, START, GOAL, cost_fn=cost_fn)
    print(f"sample route {START} -> {GOAL}: " + " -> ".join(route))

    full = write_nav2_geojson(graph, OUT_DIR / "escape_room_graph.geojson")
    print(f"wrote whole-topology graph  -> {full.relative_to(ROOT)}")

    route_only = write_nav2_geojson(
        graph, OUT_DIR / "escape_room_route.geojson", node_ids=set(route)
    )
    print(f"wrote sample-route graph    -> {route_only.relative_to(ROOT)}")

    print(
        "\nLoad either file in Nav2 Route Server (`graph_filepath`), or feed poses "
        "via `ros2 run semantic_toponav_ros waypoint_publisher` with "
        "`graph_path:=$PWD/examples/robot_escape_room.yaml`."
    )


if __name__ == "__main__":
    main()
