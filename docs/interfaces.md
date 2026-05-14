# Interfaces

This document describes the stable interfaces of `semantic-toponav`.

## Graph schema (version 1)

A YAML/JSON document with three top-level keys:

| key | type | required | notes |
|-----|------|----------|-------|
| `version` | int | yes | currently `1` |
| `metadata` | mapping | optional | free-form (e.g. `name`, `frame_id`, `description`) |
| `nodes` | list of node mappings | yes | see below |
| `edges` | list of edge mappings | yes | see below |

### Node

| field | type | required | default | notes |
|-------|------|----------|---------|-------|
| `id` | str | yes | — | must be unique within graph |
| `label` | str | no | `id` | human-readable name |
| `type` | str | yes | — | semantic class (see below) |
| `pose` | mapping | no | `null` | `{x, y, yaw, frame_id}` |
| `properties` | mapping | no | `{}` | free-form |

Common node types: `entrance`, `room`, `corridor`, `intersection`, `elevator`,
`stairs`. Unknown types are allowed and treated as `pass_through` for waypoint
generation.

### Edge

| field | type | required | default | notes |
|-------|------|----------|---------|-------|
| `id` | str | yes | — | must be unique within graph |
| `source` | str | yes | — | source node id |
| `target` | str | yes | — | target node id |
| `type` | str | yes | — | semantic class (see below) |
| `cost` | float | no | `1.0` | non-negative |
| `bidirectional` | bool | no | `true` | when `false` the edge is one-way |
| `properties` | mapping | no | `{}` | free-form |

Common edge types: `traversable`, `stairs_up`, `stairs_down`,
`elevator_connection`, `restricted`, `one_way`.

## Python API

### Loading and saving

```python
from semantic_toponav.graph.serialization import (
    load_graph, save_graph, graph_from_dict, graph_to_dict,
)

graph = load_graph("graph.yaml")       # or .yml / .json
save_graph(graph, "out.json")
```

Loader and saver pick YAML vs JSON from the file extension. Loader raises
`GraphLoadError` on parse failure, missing file, or schema violation.

### Graph operations

```python
from semantic_toponav.graph import TopologyGraph, TopologyNode, TopologyEdge, Pose2D

g = TopologyGraph()
g.add_node(TopologyNode(id="a", label="A", type="room", pose=Pose2D(0, 0)))
g.add_node(TopologyNode(id="b", label="B", type="room"))
g.add_edge(TopologyEdge(id="ab", source="a", target="b", type="traversable"))

g.has_node("a")        # -> True
g.get_node("a")        # -> TopologyNode
g.neighbors("a")       # -> list[TopologyEdge]
g.other_end(edge, "a") # -> str (the opposite endpoint of the edge)
g.node_ids()           # -> list[str]
g.edge_ids()           # -> list[str]
g.remove_node("a")     # -> list[str] (ids of incident edges removed alongside)
g.remove_edge("ab")    # -> None
g.validate()           # raises GraphValidationError on any inconsistency
```

### Planning

```python
from semantic_toponav.planner import plan_astar, plan_dijkstra

path = plan_astar(graph, start_id, goal_id)
path = plan_dijkstra(graph, start_id, goal_id)
```

Both return `list[str]` (node IDs including start and goal). They raise:

- `PlanningError` if start or goal is missing, or a cost function returns a negative value
- `NoPathError` if no route exists

`plan_astar` accepts an optional `heuristic_fn(graph, a_id, b_id) -> float`.
The default uses Euclidean distance between node poses, or `0.0` if either
pose is missing (so A* degrades to Dijkstra).

### Semantic cost functions

```python
from semantic_toponav.planner import (
    default_edge_cost, avoid_restricted, avoid_stairs, prefer_elevator,
    compose_costs,
)

cost = compose_costs(avoid_restricted, prefer_elevator)
path = plan_astar(graph, "entrance", "office_2f", cost_fn=cost)
```

`compose_costs` applies each function as a multiplier against the edge's base
cost; any function returning `math.inf` blocks the edge.

### Semantic waypoints

```python
from semantic_toponav.waypoint import SemanticWaypoint, path_to_semantic_waypoints

waypoints = path_to_semantic_waypoints(graph, path)
for wp in waypoints:
    print(wp.action, wp.instruction)
```

Each `SemanticWaypoint` has:

- `node_id`, `node_label`, `node_type`
- `action`: one of `start`, `arrive`, `enter`, `proceed_through`, `navigate`,
  `take_elevator`, `use_stairs`, `pass_through`
- `instruction`: human-readable sentence (deterministic — no LLM)
- `pose`: optional `Pose2D`
- `properties`: copy of the node's properties

### Occupancy → topology (optional)

```python
from semantic_toponav.conversion import topology_from_occupancy

graph = topology_from_occupancy(
    occupancy_grid,         # 2D bool/float array, free cells truthy
    resolution=0.05,
    origin=(0.0, 0.0),      # ROS map convention: world position of bottom-left cell
    free_threshold=0.5,     # used when grid is not boolean
    endpoint_type="endpoint",
    junction_type="intersection",
    edge_type="corridor",
)
```

Requires NumPy and scikit-image (`pip install 'semantic-toponav[map]'`).
Skeleton pixels with degree 1 become `endpoint` nodes, degree-3-or-higher
clusters become a single `intersection` node, and traced segments become
edges whose `cost` is the segment's pixel-step length scaled by
`resolution`.

### Visualization (optional)

```python
from semantic_toponav.visualization import plot_graph

fig, ax = plot_graph(
    graph,
    path=path,                # optional, highlighted in pink
    title="my route",
    save_path="out.png",      # writes PNG via matplotlib
    show=False,               # set True for interactive window
    show_edge_ids=False,
    occupancy_grid=grid,      # optional background overlay (2D array)
    resolution=0.05,          # used with occupancy_grid for extent
    origin=(0.0, 0.0),        # bottom-left cell position in world coords
)
```

Requires matplotlib (install with `pip install 'semantic-toponav[viz]'`).
Nodes without a `pose` cannot be plotted and raise `MissingPoseError`.

## ROS2 message strategy

For the MVP the ROS2 adapter publishes waypoints as JSON inside
`std_msgs/msg/String` on:

```text
/semantic_toponav/waypoints
```

This avoids requiring a custom message package during the first iteration.
Custom messages (`SemanticWaypoint.msg`, `SemanticWaypointArray.msg`,
`TopologyNode.msg`, `TopologyEdge.msg`) are a planned follow-up.

## Exceptions

| exception | raised by |
|-----------|-----------|
| `GraphValidationError` | `TopologyGraph` insertion or `.validate()` |
| `GraphLoadError` | `load_graph` / `graph_from_dict` |
| `PlanningError` | `plan_astar` / `plan_dijkstra` for bad inputs |
| `NoPathError` | `plan_astar` / `plan_dijkstra` when no route exists |

All four are plain `Exception` subclasses; there is no large exception framework.
