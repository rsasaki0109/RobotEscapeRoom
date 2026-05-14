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

#### Fluent construction

```python
from semantic_toponav.graph import GraphBuilder

graph = (
    GraphBuilder()
    .node("a", type="room", x=0, y=0)             # x=/y= build Pose2D inline
    .node("b", type="corridor", x=1, y=0)
    .node("c", type="room", x=2, y=0, properties={"floor": 1})
    .connect("a", "b", "c", type="traversable")   # lay edges through a chain
    .build()
)

# Or extend an already-loaded graph:
GraphBuilder.from_graph(existing).node("new_node", type="room").build()
```

`node()` accepts either `pose=Pose2D(...)` or `x=`/`y=` (with optional
`yaw=`/`frame_id=`); `edge()` auto-generates an id like
`"<source>__<target>"` when one is not passed.

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
    floor_change_penalty, prefer_floor, same_floor_only,
    compose_costs,
)

cost = compose_costs(avoid_restricted, prefer_elevator)
path = plan_astar(graph, "entrance", "office_2f", cost_fn=cost)
```

`compose_costs` applies each function as a multiplier against the edge's base
cost; any function returning `math.inf` blocks the edge.

The floor-aware helpers (`floor_change_penalty`, `prefer_floor`,
`same_floor_only`) are *factories*: they take a graph and return a
`(edge) -> float` callable. They read the integer `floor` property of each
endpoint to decide cost.

Two more factories handle *runtime availability*:

- `block_edges(edge_ids)` — return `inf` for the listed edge IDs.
- `block_edge_types(edge_types)` — return `inf` for any edge whose `type`
  is in the set.

Both are graph-independent (they only inspect the edge passed in) and
compose cleanly with the semantic cost functions above.

```python
cost = compose_costs(prefer_elevator, floor_change_penalty(graph, penalty=10))
```

### A* heuristics

```python
from semantic_toponav.planner import plan_astar, floor_aware_heuristic

path = plan_astar(
    graph, "entrance", "exec_office_3f",
    heuristic_fn=floor_aware_heuristic(floor_height=2.0),
)
```

The default heuristic is planar Euclidean. `floor_aware_heuristic` adds
`floor_height * abs(delta_floor)` on top, making A* exploration tighter
on multi-floor graphs.

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

### Trajectory log → topology

```python
from semantic_toponav.conversion import topology_from_trajectories

graph = topology_from_trajectories(
    trajectories,         # Iterable of sequences of (x, y)
    eps=0.5,              # cluster radius in meters
    min_samples=3,        # discard clusters below this point count
    node_type="waypoint",
    edge_type="traversable",
    frame_id="map",
    id_prefix="",
)
```

Pure-Python; no scientific-stack dependency required beyond what the
core graph needs. Edges expose a ``traversal_count`` property indicating
how many trajectories used that transition (useful as a downstream
cost-function input — e.g. prefer well-trodden routes).

#### Loading trajectories from CSV

```python
from semantic_toponav.conversion import load_trajectories_from_csv

trajectories = load_trajectories_from_csv(
    path,
    x_column="x",                       # str (header mode) or int (positional)
    y_column="y",
    trajectory_column="trajectory_id",  # None for single trajectory
    has_header=True,                    # set False for positional indices
    delimiter=",",
)
```

Returns ``list[list[tuple[float, float]]]`` — pass directly to
``topology_from_trajectories``. Raises ``CsvTrajectoryLoadError`` on
parse failure or unknown columns. Uses only :mod:`csv` from stdlib.

### Loading ROS map_server bundles (optional)

```python
from semantic_toponav.conversion import load_occupancy_map

m = load_occupancy_map("my_map.yaml")
m.free_mask     # 2D bool array, True where free
m.resolution    # meters per cell
m.origin        # (x, y) of the bottom-left cell, in meters
m.origin_yaw    # yaw of the origin, in radians (rarely used)
m.metadata      # {"negate", "free_thresh", "occupied_thresh", "image"}
```

Honors the standard `map_server` keys (`negate`, `free_thresh`,
`occupied_thresh`) and supports any image format scikit-image can read
(PGM, PNG, BMP, ...). Requires the `[map]` extra. Raises `MapLoadError`
on parse failure or missing image.

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

### Semantic queries

```python
from semantic_toponav.query import (
    NoMatchError,
    find_nodes,
    nearest_node_by_pose,
    nearest_node_by_graph_distance,
)

find_nodes(
    graph,
    type=None,                # exact node-type match
    label_contains=None,      # case-insensitive substring match on label
    label_equals=None,        # exact label match
    properties=None,          # dict of {key: expected_value}, all must match
) -> list[TopologyNode]

nearest_node_by_pose(graph, pose, **filters) -> TopologyNode
nearest_node_by_graph_distance(graph, start_id, **filters) -> tuple[TopologyNode, list[str]]
```

`NoMatchError` is raised when no node satisfies the filters (or, for graph
distance, no matching node is reachable from `start_id`).

#### Embedding-based retrieval

```python
from semantic_toponav.query import (
    cosine_similarity,
    find_nodes_by_embedding,
    nearest_node_by_embedding,
)

cosine_similarity(a, b)                        # plain math, no numpy

find_nodes_by_embedding(
    graph, query,
    top_k=5,
    embedding_property="embedding",
    # Same predicate filters as find_nodes (type / label_* / properties).
)                                              # -> list[(node, similarity)]

nearest_node_by_embedding(graph, query, **filters)   # single highest match
```

Embeddings live in `node.properties[embedding_property]` as any sequence
of floats; the YAML/JSON serializer round-trips them as ordinary lists.
Nodes without an embedding are silently skipped during retrieval, and a
dimension mismatch between the query and any candidate raises
`ValueError`. The encoder itself (CLIP, SigLIP, sentence-transformers,
custom) is out of scope — attach the vectors ahead of time.

### Visit-history memory

```python
from semantic_toponav.memory import (
    record_visit, record_path, clear_history,
    visit_count, last_visited, time_since_visit,
    prefer_unvisited, prefer_familiar, avoid_recently_visited,
)

record_visit(graph, "kitchen", now=None)              # now=None -> time.time()
record_path(graph, ["a", "b", "c"], now=None)         # single timestamp for all
visit_count(graph, "kitchen")                         # -> int (0 if never)
last_visited(graph, "kitchen")                        # -> float | None
time_since_visit(graph, "kitchen", now=None)          # -> float | None
clear_history(graph, node_ids=None)                   # default: every node
```

Visit data is stored on `node.properties` (keys `visit_count`,
`last_visited`) so it round-trips through the YAML/JSON serializer with
no schema change. Both key names are configurable via `count_key=` /
`timestamp_key=` if a graph already uses different conventions.

The memory-aware cost factories follow the same pattern as the floor
helpers — `f(graph, ...) -> (edge) -> float`:

```python
from semantic_toponav.memory import (
    prefer_unvisited, prefer_familiar, avoid_recently_visited,
)
from semantic_toponav.planner import compose_costs, plan_astar

# Bias the planner toward unexplored nodes (coverage / patrol).
cost = prefer_unvisited(graph, visited_multiplier=2.0)

# Retrace already-known routes (safer if unfamiliar nodes are risky).
cost = prefer_familiar(graph, familiar_multiplier=0.5)

# Penalize nodes visited within the last 60 seconds.
cost = avoid_recently_visited(graph, within_seconds=60.0, recent_multiplier=5.0)

# Compose with the rest of the cost stack.
cost = compose_costs(
    prefer_unvisited(graph),
    avoid_recently_visited(graph, within_seconds=60.0),
)
path = plan_astar(graph, "entrance", "lab", cost_fn=cost)
```

All three factories key off the *target* endpoint of each edge — the
node the robot would arrive at — which is the natural choice for "where
have I been recently?" reasoning. `now=` is read once when the factory
is called, not on every edge evaluation, so a single plan call sees a
consistent clock.

The history can also be edited from the shell, following the same
stdout-by-default convention as the editor commands:

```bash
semantic-toponav record-visit  GRAPH NODE_ID [--now TS] [--in-place | --out FILE]
semantic-toponav record-path   GRAPH NODE_ID... [--now TS] [--in-place | --out FILE]
semantic-toponav clear-history GRAPH [NODE_ID...] [--in-place | --out FILE]
semantic-toponav history       GRAPH [NODE_ID...] [--all]
```

`plan` / `waypoints` / `plot` expose matching cost flags:
`--prefer-unvisited [--visited-multiplier M]`,
`--prefer-familiar [--familiar-multiplier M]`,
`--avoid-recent SECONDS [--recent-multiplier M] [--now TS]`.

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

The ROS2 adapter supports two output formats on
`/semantic_toponav/waypoints`, selected by the
`output_format` node parameter:

| `output_format` | wire type | when to use |
|---|---|---|
| `json` (default) | `std_msgs/msg/String` carrying a JSON document | zero-dep MVP, quick `ros2 topic echo` debugging |
| `msg` | `semantic_toponav_msgs/msg/SemanticWaypointArray` | typed fields, `ros2 bag` introspection, downstream subscribers in C++/Python |

Custom message definitions live in `ros2/semantic_toponav_msgs/msg/` and
mirror the Python dataclasses one-for-one:

| `.msg` | mirrors |
|---|---|
| `SemanticWaypoint.msg` | `semantic_toponav.waypoint.SemanticWaypoint` |
| `SemanticWaypointArray.msg` | header + path + waypoints |
| `TopologyNode.msg` | `semantic_toponav.graph.types.TopologyNode` |
| `TopologyEdge.msg` | `semantic_toponav.graph.types.TopologyEdge` |
| `TopologyGraph.msg` | a full `TopologyGraph` snapshot |

Two layout decisions worth noting:

- **Optional pose**: each message carries `(has_pose: bool, frame_id: string,
  pose: geometry_msgs/Pose2D)` side-by-side rather than an optional field.
  `has_pose=false` means downstream consumers should treat the waypoint as
  pose-less (the `pose` and `frame_id` fields are zeroed).
- **Heterogeneous properties**: node and edge `properties` dicts can carry
  strings, numbers, lists, etc. — too irregular for parallel
  key/value arrays. We serialize them as a single `properties_json` string,
  which round-trips through `json.loads`/`json.dumps`.

Conversion helpers live in
`ros2/semantic_toponav_ros/semantic_toponav_ros/msg_conversions.py`. The
`*_to_fields` / `*_from_fields` functions are pure Python and require no
sourced ROS environment — they're how the project's regular pytest suite
validates the wire layout. Thin `*_to_msg` wrappers handle the final copy
onto the generated message classes inside a ROS workspace.

### Graph publishing

`graph_loader_node` publishes the validated graph once at startup on
`/semantic_toponav/graph` as a `semantic_toponav_msgs/TopologyGraph`. The
publisher uses `TRANSIENT_LOCAL` durability with depth 1, so subscribers
that connect after the publish still receive the most recent snapshot
(the standard "latched topic" idiom in ROS2 for slow-changing state like
maps). The topic name is configurable via the `topic` parameter, and the
publish step can be disabled with `publish_graph:=false` if you only
want the load-and-validate behavior.

## Exceptions

| exception | raised by |
|-----------|-----------|
| `GraphValidationError` | `TopologyGraph` insertion or `.validate()` |
| `GraphLoadError` | `load_graph` / `graph_from_dict` |
| `PlanningError` | `plan_astar` / `plan_dijkstra` for bad inputs |
| `NoPathError` | `plan_astar` / `plan_dijkstra` when no route exists |

All four are plain `Exception` subclasses; there is no large exception framework.
