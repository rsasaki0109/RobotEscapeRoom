"""Hand the semantic topology to the Nav2 Route Server.

Since 2024–25 the ROS 2 **Nav2 Route Server** plans over a predefined
navigation graph loaded from GeoJSON. That makes semantic-toponav's stance
concrete: it is the planning / grounding tier that sits *above* Nav2, not
a rival to it — author / ground / repair the semantic topology here, then
export it for Nav2 to execute over.

This script plans a semantic route, then writes **two** Nav2 graphs:

  1. the whole topology (so the Route Server can plan any goal over it);
  2. just the committed route's nodes (the degenerate "follow this plan"
     graph).

Each node carries its semantic ``class`` / label / floor under the Nav2
``metadata`` key (where a ``SemanticScorer`` reads it); bidirectional
edges are split into the two directed edges Nav2 expects.

    pip install -e .
    python examples/export_nav2_route.py
"""

from __future__ import annotations

from pathlib import Path

from semantic_toponav.conversion import write_nav2_geojson
from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.planner import compose_costs, plan_astar, prefer_elevator

ROOT = Path(__file__).parent.parent
GRAPH = ROOT / "examples" / "multi_floor_office.yaml"
OUT_DIR = ROOT / "examples" / "data" / "nav2"
START, GOAL = "entrance", "exec_office_3f"


def main() -> None:
    graph = load_graph(str(GRAPH))
    route = plan_astar(graph, START, GOAL, cost_fn=compose_costs(prefer_elevator))
    print(f"planned route {START} -> {GOAL}: " + " -> ".join(route))

    full = write_nav2_geojson(graph, OUT_DIR / "office_graph.geojson")
    print(f"wrote whole-topology graph  -> {full.relative_to(ROOT)}")

    route_only = write_nav2_geojson(
        graph, OUT_DIR / "office_route.geojson", node_ids=set(route)
    )
    print(f"wrote committed-route graph -> {route_only.relative_to(ROOT)}")

    print(
        "\nLoad either in a Nav2 Route Server: set the GeoJsonGraphFileLoader "
        "`graph_filepath` to the file, then call the ComputeRoute / "
        "ComputeAndTrackRoute action. semantic-toponav owns *where to go and "
        "why*; Nav2 owns *how to move*."
    )


if __name__ == "__main__":
    main()
