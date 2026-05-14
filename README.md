# semantic-toponav

Open-source robotics navigation built around **Semantic Topological Maps**.

`semantic-toponav` is the *global, semantic, graph-level* planning layer that
sits **above** dense metric maps and HD maps, and **below** any low-level
motion executor (Nav2, Autoware, MPPI, learned policies, ...).

It explores the next abstraction layer for robot navigation:

- semantic topological map
- graph-based navigation
- semantic waypoint planning
- memory-oriented navigation
- navigation for embodied AI

## What this project *is*

A small, readable Python core that:

- defines an explicit semantic topology graph (nodes, edges, semantic types)
- loads/saves graphs as YAML or JSON
- plans routes with Dijkstra and A*
- supports semantic-aware routing (avoid restricted, avoid stairs, prefer elevator, ...)
- converts a node path into a list of semantic waypoints
- ships a CLI for validation, planning, and waypoint generation
- ships a ROS2 adapter package skeleton for integration (Nav2 etc.)

## What this project is *not*

It deliberately does **not** include:

- low-level control (MPC, MPPI)
- obstacle avoidance
- SLAM
- dense occupancy planning
- behavior trees

Those should be integrated through existing systems (Nav2, Autoware, custom local planners).
The split is:

| Layer | Responsibility | Owned by |
|------|---------------|-----------|
| Global semantic-topological planning | *where* and *why* | this repository |
| Local motion execution | *how to move locally* | Nav2 / MPPI / policy |

## Quick start

```bash
pip install -e .
```

Generate a path from the bundled office example:

```bash
semantic-toponav validate examples/indoor_office.yaml
semantic-toponav plan      examples/indoor_office.yaml entrance meeting_room
semantic-toponav waypoints examples/indoor_office.yaml entrance office_2f --avoid-stairs --prefer-elevator
```

Or run the full demo (shows how semantic costs change the route):

```bash
python examples/run_indoor_demo.py
```

## Occupancy grid → topology

A skeletonization-based converter turns a 2D occupancy grid into a topology
graph automatically. Endpoints become `endpoint` nodes; junctions become
`intersection` nodes; everything in between becomes `corridor` edges with
cost proportional to skeleton length.

```bash
pip install -e '.[viz,map]'
python examples/occupancy_to_topology.py
```

```python
import numpy as np
from semantic_toponav.conversion import topology_from_occupancy

grid = np.zeros((30, 60), dtype=bool)
grid[8:11, 4:55] = True       # horizontal corridor
grid[22:25, 4:55] = True      # second horizontal corridor
grid[8:25, 12:14] = True      # vertical link
graph = topology_from_occupancy(grid, resolution=0.25)
```

| occupancy grid + auto-generated topology | planned path overlay |
|-----------------------------------------|----------------------|
| ![grid](docs/images/05_occupancy_graph.png) | ![path](docs/images/06_occupancy_graph_with_path.png) |

## Trajectory log → topology

When you don't have an occupancy grid but you do have logs of where the
robot went (or where users / pedestrians walked), you can induce a
topology directly from those tracks. Points are clustered greedily; each
dense cluster becomes a node; consecutive cluster transitions become
edges with a `traversal_count` property — higher counts mark routes the
robot took repeatedly.

```python
from semantic_toponav.conversion import topology_from_trajectories

graph = topology_from_trajectories(
    [traj_a, traj_b],   # each traj is a sequence of (x, y)
    eps=0.5,            # cluster radius in meters
    min_samples=3,      # drop sparser clusters as noise
)
```

```bash
python examples/trajectory_to_topology.py
```

![trajectory to topology](docs/images/08_trajectory_topology.png)

### Loading ROS map_server bundles

`semantic-toponav` can load the standard `map_server` YAML + PGM/PNG/BMP
pair used by ROS Nav2:

```python
from semantic_toponav.conversion import load_occupancy_map, topology_from_occupancy

m = load_occupancy_map("examples/sample_map.yaml")
graph = topology_from_occupancy(m.free_mask, resolution=m.resolution, origin=m.origin)
```

`negate`, `free_thresh`, and `occupied_thresh` are honored. The bundled
`examples/sample_map.{yaml,pgm}` is small enough to skim and produces a
topology with rooms, a main corridor, and a planned route:

```bash
python examples/load_map_demo.py
```

![sample map topology](docs/images/07_sample_map_topology.png)

## Visualization

Install the optional viz extra and use the `plot` subcommand or the Python helper:

```bash
pip install -e '.[viz]'

semantic-toponav plot examples/indoor_office.yaml \
    --start entrance --goal office_2f \
    --avoid-stairs --prefer-elevator \
    --save route.png
```

```python
from semantic_toponav.visualization import plot_graph
plot_graph(graph, path=path, save_path="route.png")
```

Below: same graph, two different cost configurations.

| Default A* | `avoid_stairs + prefer_elevator` |
|------------|-----------------------------------|
| ![default](docs/images/03_default_to_office_2f.png) | ![accessibility](docs/images/04_avoid_stairs_to_office_2f.png) |

## Graph schema (v1)

```yaml
version: 1
metadata:
  name: indoor_office
  frame_id: map
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

Node `type` examples: `corridor`, `room`, `intersection`, `elevator`, `stairs`, `entrance`.
Edge `type` examples: `traversable`, `stairs_up`, `stairs_down`, `elevator_connection`,
`restricted`, `one_way`.

`pose` is optional. Without it, A* degrades to Dijkstra.

## Python API

```python
from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.planner import (
    plan_astar, avoid_restricted, avoid_stairs, prefer_elevator, compose_costs,
)
from semantic_toponav.waypoint import path_to_semantic_waypoints

graph = load_graph("examples/indoor_office.yaml")

path = plan_astar(
    graph, "entrance", "office_2f",
    cost_fn=compose_costs(avoid_stairs, prefer_elevator),
)
for wp in path_to_semantic_waypoints(graph, path):
    print(wp.instruction)
```

## Semantic queries

Translate natural-language-style intents ("nearest elevator", "any room on
floor 2") into concrete graph operations:

```python
from semantic_toponav.query import (
    find_nodes, nearest_node_by_pose, nearest_node_by_graph_distance,
)

elevators = find_nodes(graph, type="elevator")
office_2f_nodes = find_nodes(graph, properties={"floor": 2})

# Euclidean nearest (no path required).
nearest = nearest_node_by_pose(graph, (0.0, 0.0), type="elevator")

# Graph-distance nearest, with shortest path included.
node, path = nearest_node_by_graph_distance(graph, "entrance", type="room")
```

```bash
semantic-toponav find    examples/indoor_office.yaml --type elevator
semantic-toponav nearest examples/indoor_office.yaml --from-node entrance --type room
semantic-toponav nearest examples/indoor_office.yaml --from-pose 0 0 --type elevator
```

## CLI

```text
# Planning
semantic-toponav validate  GRAPH
semantic-toponav plan      GRAPH START GOAL [--algorithm astar|dijkstra] [--avoid-restricted]
                                            [--avoid-stairs] [--prefer-elevator]
                                            [--format text|json]
semantic-toponav waypoints GRAPH START GOAL [...same options...]
semantic-toponav plot      GRAPH [--start S --goal G] [--avoid-*] [--save FILE] [--show]
                                                       [--edge-ids] [--title STR]

# Editing (write to stdout by default; pass --in-place or --out FILE to persist)
semantic-toponav inspect   GRAPH [--nodes] [--edges] [--type T]
semantic-toponav add-node  GRAPH ID --type T [--label L] [--x X --y Y [--yaw R]]
                                             [--prop KEY=VALUE ...] [--in-place | --out FILE]
semantic-toponav add-edge  GRAPH SRC TGT --type T [--id ID] [--cost C] [--one-way]
                                                  [--prop KEY=VALUE ...] [--in-place | --out FILE]
semantic-toponav rm-node   GRAPH ID [--in-place | --out FILE]   # cascades to incident edges
semantic-toponav rm-edge   GRAPH ID [--in-place | --out FILE]

# Semantic queries
semantic-toponav find      GRAPH [--type T] [--label-contains S] [--label-equals S]
                                 [--prop KEY=VALUE ...] [--format text|json]
semantic-toponav nearest   GRAPH (--from-pose X Y | --from-node ID)
                                 [...same filter flags as `find`...]
```

Build a tiny graph from scratch:

```bash
echo 'version: 1
metadata: {name: scratch}
nodes: []
edges: []' > scratch.yaml

semantic-toponav add-node scratch.yaml a --type entrance --x 0 --y 0 --in-place
semantic-toponav add-node scratch.yaml b --type corridor --x 2 --y 0 --in-place
semantic-toponav add-node scratch.yaml c --type room     --x 4 --y 0 --in-place
semantic-toponav add-edge scratch.yaml a b --type traversable --in-place
semantic-toponav add-edge scratch.yaml b c --type traversable --in-place
semantic-toponav waypoints scratch.yaml a c
```

## ROS2 integration

The core Python package is ROS-independent. The ROS2 wrapper lives under
`ros2/semantic_toponav_ros/`. See [`ros2/README.md`](ros2/README.md) for the
adapter design and the Nav2 integration boundary.

## Project status

This is the MVP. Things explicitly out of scope for the first version include
custom ROS messages, a behavior-tree Nav2 plugin, occupancy-to-topology
conversion, VLM labeling, and CLIP embeddings. See
[`docs/decisions.md`](docs/decisions.md) for the reasoning and
[`docs/experiments.md`](docs/experiments.md) for future directions.

## Tests

```bash
pytest -q
```

## License

Apache-2.0.
