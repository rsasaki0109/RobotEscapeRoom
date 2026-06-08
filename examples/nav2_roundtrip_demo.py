"""Close the loop with Nav2: plan here, hand off, and prove the hand-off.

Since 2024–25 the ROS 2 **Nav2 Route Server** plans over a predefined
navigation graph loaded from GeoJSON. semantic-toponav is the planning /
grounding tier *above* Nav2 — it authors, grounds and repairs the semantic
topology, then exports it for Nav2 to execute over. ``export_nav2_route.py``
shows the export; this script closes the loop and *proves the hand-off
loses nothing that matters*, end to end, with no ROS install:

  1. plan a semantic route (elevator-preferring A*);
  2. export just that route to Nav2 Route Server GeoJSON;
  3. read it back the way Nav2's ``GeoJsonGraphFileLoader`` would —
     directed edges only — and **replan**: the sequence is identical, so
     Nav2 plans what we planned;
  4. read it back losslessly and re-export: the FeatureCollection is
     byte-identical, so the round trip carries every field the format can.

    pip install -e .
    python examples/nav2_roundtrip_demo.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from semantic_toponav.conversion import (
    nav2_geojson_to_topology,
    read_nav2_geojson,
    topology_to_nav2_geojson,
    write_nav2_geojson,
)
from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.planner import compose_costs, plan_astar, prefer_elevator

ROOT = Path(__file__).parent.parent
GRAPH = ROOT / "examples" / "multi_floor_office.yaml"
START, GOAL = "entrance", "exec_office_3f"


def main() -> None:
    graph = load_graph(str(GRAPH))
    cost_fn = compose_costs(prefer_elevator)

    route = plan_astar(graph, START, GOAL, cost_fn=cost_fn)
    print(f"1. planned semantic route {START} -> {GOAL}:")
    print("   " + " -> ".join(route))

    with tempfile.TemporaryDirectory() as tmp:
        path = write_nav2_geojson(graph, Path(tmp) / "route.geojson", node_ids=set(route))
        print(f"\n2. exported the route to Nav2 Route Server GeoJSON ({path.name})")

        # 3. Nav2-faithful read: directed edges only, then replan. The
        #    semantic `class` of every node survives the hand-off, so the same
        #    elevator-preferring cost shaping reproduces the same route.
        nav2_view = read_nav2_geojson(path, recombine_bidirectional=False)
        replanned = plan_astar(nav2_view, START, GOAL, cost_fn=cost_fn)
        same = replanned == route
        print(
            f"\n3. read back as Nav2 sees it ({len(list(nav2_view.edges()))} directed "
            f"edges) and replanned:"
        )
        print("   " + " -> ".join(replanned))
        print(f"   identical to the original route: {same}")

        # 4. Lossless read: recombine the directed halves, re-export, compare.
        fc = topology_to_nav2_geojson(graph, node_ids=set(route))
        reexport = topology_to_nav2_geojson(nav2_geojson_to_topology(fc))
        print(
            f"\n4. lossless round trip (export -> read -> export) is "
            f"byte-identical: {reexport == fc}"
        )

    if not (same and reexport == fc):
        raise SystemExit("round trip did NOT preserve the route — hand-off is lossy")

    print(
        "\nsemantic-toponav owns *where to go and why*; Nav2 owns *how to "
        "move*. The route survives the hand-off in both directions."
    )


if __name__ == "__main__":
    main()
