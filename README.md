# semantic-toponav

[![test](https://github.com/rsasaki0109/semantic-toponav/actions/workflows/test.yml/badge.svg)](https://github.com/rsasaki0109/semantic-toponav/actions/workflows/test.yml)
[![python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

**Global semantic-topological path planner for robots.** Sits *above*
SLAM / HD maps and *below* Nav2 / Autoware / MPPI motion executors —
the layer that decides *where to go* and *why*, while the local
motion stack decides *how to move*. Pure Python core, optional ROS2
adapter, no model dependencies in the core.

<p align="center">
  <img src="docs/images/10_mf_elevator.png" width="640" alt="multi-floor accessibility route via elevator">
</p>

## What it does

- Define a graph of **semantic places** (rooms, corridors, elevators,
  stairs) and traversable edges with composable cost rules
- **Plan routes** with Dijkstra / A* under semantic costs: avoid
  stairs, prefer elevator, block restricted, time-of-day closures,
  reservations, multi-floor heuristics
- **Coordinate multi-agent fleets** via an in-memory shared scheduler:
  FCFS / priority / deadline / joint / branch-and-bound / MIS upper
  bound — plus a stdlib-only HTTP transport for production fan-out
- **Resolve free-text goals** to node ids: deterministic, then optional
  LLM rewrite (out-of-pool picks silently dropped — the LLM cannot
  invent node ids), then optional VLM cosine-similarity grounding,
  then optional multi-turn clarification dialog

## Gallery

| ![default](docs/images/03_default_to_office_2f.png) | ![accessibility](docs/images/04_avoid_stairs_to_office_2f.png) |
|---|---|
| **Default A*** — fastest route via stairs | **avoid_stairs + prefer_elevator** — accessibility-aware |
| ![occupancy](docs/images/05_occupancy_graph.png) | ![path](docs/images/06_occupancy_graph_with_path.png) |
| **Occupancy grid → topology** via skeletonization | **Path on the auto-generated graph** |
| ![trajectory](docs/images/08_trajectory_topology.png) | ![csv](docs/images/13_csv_trajectory.png) |
| **Trajectory log → topology** by greedy clustering | **CSV trajectories** loaded without pandas |

## Quick start

```bash
pip install -e .
semantic-toponav plan          examples/indoor_office.yaml entrance meeting_room
semantic-toponav waypoints     examples/indoor_office.yaml entrance office_2f --avoid-stairs --prefer-elevator
semantic-toponav describe-path examples/indoor_office.yaml entrance office_2f --avoid-stairs --prefer-elevator
```

```python
from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.planner import (
    plan_astar, avoid_stairs, prefer_elevator, compose_costs,
)
from semantic_toponav.waypoint import path_to_semantic_waypoints

graph = load_graph("examples/indoor_office.yaml")
path = plan_astar(graph, "entrance", "office_2f",
                  cost_fn=compose_costs(avoid_stairs, prefer_elevator))
for wp in path_to_semantic_waypoints(graph, path):
    print(wp.instruction)
```

New to the library? Walk through the
[**three-floor tutorial**](docs/tutorial.md) end-to-end.

## Features

| Area | What's there | Docs |
|---|---|---|
| **Map / log conversion** | Occupancy grid, door detection, region segmentation, graph compaction, trajectories, CSV / rosbag2 / ROS map_server | [conversion.md](docs/conversion.md) |
| **Cost composition** | `avoid_*` / `prefer_*` / `block_*`, time-of-day windows, static reservations, multi-floor heuristics | [cost_composition.md](docs/cost_composition.md) |
| **Multi-agent coordination** | `SharedScheduler` + RPC shim (HTTP / custom), `plan_fleet_with_strategy`, joint / BnB / exhaustive-MIS, fairness objectives, deadline admission, synthetic eval suite | [coordination.md](docs/coordination.md) |
| **Semantic queries + LLM/VLM** | `find_nodes` / `nearest_*` / `resolve_goal`, embedding retrieval, CLIP backend, `llm_resolve_goal` + `DialogSession` (multi-turn), visit-history memory | [queries.md](docs/queries.md) |
| **CLI reference** | All subcommands and flags | [cli.md](docs/cli.md) |
| **Visualization** | matplotlib `plot`, interactive pyvis HTML viewer | see below |
| **Schema** | YAML v1 graph format, waypoint JSON schema | [waypoint_schema.md](docs/waypoint_schema.md) |
| **ROS2 integration** | `graph_loader` / `waypoint_publisher` / `nav2_demo` nodes | [ros2/README.md](ros2/README.md) |

## Visualization

```bash
pip install -e '.[viz]'
semantic-toponav plot examples/indoor_office.yaml \
    --start entrance --goal office_2f \
    --avoid-stairs --prefer-elevator --save route.png

pip install -e '.[viz_web]'
semantic-toponav viewer examples/multi_floor_office.yaml \
    --start entrance --goal exec_office_3f --prefer-elevator \
    --output viewer.html
```

The web viewer is a fully offline self-contained HTML file — nodes
are draggable, hovering surfaces type / cost / property tooltips,
and the highlighted path is overlaid in pink.

## Graph schema (v1)

```yaml
version: 1
metadata: {name: indoor_office, frame_id: map}
nodes:
  - id: entrance
    label: Entrance
    type: entrance
    pose: {x: 0.0, y: 0.0, yaw: 0.0, frame_id: map}
    properties: {}
edges:
  - id: entrance_to_corridor
    source: entrance
    target: corridor_main
    type: traversable
    cost: 1.0
    bidirectional: true
    properties: {}
```

Node `type` examples: `corridor`, `room`, `intersection`, `elevator`,
`stairs`, `entrance`. Edge `type` examples: `traversable`,
`stairs_up`, `stairs_down`, `elevator_connection`, `restricted`,
`one_way`. `pose` is optional — without it A* degrades to Dijkstra.

For a fluent builder API, see `semantic_toponav.graph.GraphBuilder`
(documented in [tutorial.md](docs/tutorial.md)).

## What this project is *not*

Deliberately out of scope (use existing systems):

- Low-level control (MPC / MPPI)
- Obstacle avoidance / SLAM / dense occupancy planning
- Behavior trees

The split is *where to go* (this repo) vs *how to move locally*
(Nav2 / Autoware / your motion executor):

| Layer | Responsibility | Owned by |
|---|---|---|
| Global semantic-topological planning | *where* and *why* | this repository |
| Local motion execution | *how to move locally* | Nav2 / MPPI / policy |

## Project status

This is the MVP. See [docs/decisions.md](docs/decisions.md) for the
design notes and [docs/experiments.md](docs/experiments.md) for
roadmap directions. The waypoint JSON wire format produced by
`waypoint_publisher_node` and `SemanticWaypoint.to_dict()` is v1-stable
and documented in [docs/waypoint_schema.md](docs/waypoint_schema.md);
the matching JSON Schema lives under [`schemas/`](schemas/).

## Tests

```bash
pytest -q
```

## License

Apache-2.0.
