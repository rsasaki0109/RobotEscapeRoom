# semantic-toponav

[![test](https://github.com/rsasaki0109/semantic-toponav/actions/workflows/test.yml/badge.svg)](https://github.com/rsasaki0109/semantic-toponav/actions/workflows/test.yml)
[![python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

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
semantic-toponav validate      examples/indoor_office.yaml
semantic-toponav plan          examples/indoor_office.yaml entrance meeting_room
semantic-toponav waypoints     examples/indoor_office.yaml entrance office_2f --avoid-stairs --prefer-elevator
semantic-toponav describe-path examples/indoor_office.yaml entrance office_2f --avoid-stairs --prefer-elevator
```

The `describe-path` subcommand renders the plan as numbered, edge-aware
step-by-step instructions (e.g. "Take the elevator from Elevator A (1F)
to Elevator A (2F)", plus an explicit "Floor change: 1 -> 2" call-out)
on top of `plan` / `waypoints`.

Or run the full demo (shows how semantic costs change the route):

```bash
python examples/run_indoor_demo.py
```

New to the library? The [**three-floor tutorial**](docs/tutorial.md)
walks through the full workflow end-to-end — load, plan, customize
costs, emit waypoints, and visualize — against the bundled multi-floor
office graph.

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

### Door / threshold detection

`mark_doors_by_clearance` runs a distance transform on the binarized
grid and flags narrow-passage nodes and edges. Each node-with-cells
gets a `min_clearance` (meters) property; nodes and edges whose
clearance is below an explicit or auto-percentile threshold get
re-typed `door`.

```python
from semantic_toponav.conversion import (
    mark_doors_by_clearance, topology_from_occupancy,
)
graph = topology_from_occupancy(grid, resolution=0.05)
result = mark_doors_by_clearance(graph, grid, resolution=0.05,
                                 clearance_threshold=0.6)  # meters
print(result.node_ids, result.edge_ids)
```

### Region segmentation (room-aware labels)

`annotate_regions` runs connected-component labeling on free space and
stamps `region_id` on every node-with-cells. When `clearance_threshold`
(or `clearance_percentile`) is supplied the same distance transform
used by the door detector pinches narrow passages off, so each room
becomes a distinct component instead of one giant blob spanning the
whole floor.

```python
from semantic_toponav.conversion import (
    annotate_regions, topology_from_occupancy,
)
graph = topology_from_occupancy(grid, resolution=0.05)
result = annotate_regions(graph, grid, resolution=0.05,
                          clearance_threshold=0.6)  # pinch doorways
for rid, info in result.regions.items():
    print(rid, info.area_m2, info.centroid_world)
```

### Occupancy pipeline from the CLI

The same three steps are exposed as subcommands so you can go from a
ROS `map_server` bundle to a room-aware graph without writing Python.
In-place mutations write a `.bak` first (pass `--no-backup` to skip),
and either `--clearance-threshold METERS` or `--clearance-percentile P`
(but not both) pins the doorway-pinching cutoff.

```sh
# Skeletonize an occupancy bundle into a topology graph.
semantic-toponav from-occupancy map.yaml --out office.yaml

# Re-type narrow-passage nodes / edges as doors.
semantic-toponav mark-doors office.yaml map.yaml \
    --clearance-threshold 0.6 --in-place

# Stamp region_id on every node, splitting rooms at the doorways.
semantic-toponav annotate-regions office.yaml map.yaml \
    --clearance-threshold 0.6 --show-regions --in-place
```

### Compacting a noisy graph

Skeletonization sometimes produces tightly-clustered endpoint nodes (a
few cells apart) and multiple near-parallel edges between the same pair
of clusters. `compact` is a lossy pass that merges nearby posed nodes
into a single representative (centroid pose) and collapses
same-endpoint duplicate edges. Use `--keep-strategy` to control which
parallel edge survives, and `--edge-cost-tolerance` to refuse the
collapse when the candidate edges differ in length beyond your taste:

```sh
# Merge nodes within 30 cm and collapse exact-endpoint duplicates.
semantic-toponav compact office.yaml \
    --endpoint-tolerance 0.3 --in-place

# Keep distinct paths whose costs differ by more than 1.0 m.
semantic-toponav compact office.yaml \
    --endpoint-tolerance 0.3 --edge-cost-tolerance 1.0 \
    --keep-strategy shortest --out compacted.yaml
```

## Dynamic edge availability

Block specific edges or whole edge types at plan time without mutating the
graph. Useful for runtime state — "this corridor is closed for cleaning",
"the freight elevator is down" — that should affect *this* plan but not
the next one.

```python
from semantic_toponav.planner import (
    plan_astar, block_edges, block_edge_types, compose_costs, prefer_elevator,
)

# Plan as if the freight elevator and one stairwell were unusable.
path = plan_astar(
    graph, "entrance", "exec_office_3f",
    cost_fn=compose_costs(
        prefer_elevator,
        block_edges(["elevator_link_freight"]),
        block_edge_types({"stairs_up"}),
    ),
)
```

```bash
semantic-toponav plan multi_floor_office.yaml entrance exec_office_3f \
    --block-edge-type stairs_up \
    --block-edge e_corridor_2f_to_office_2f
```

Both flags are repeatable. A blocked edge returns `math.inf` from the cost
function and `NoPathError` is raised if blocking removes the last route.

### Time-of-day restrictions

Attach a `closed_during` property to an edge (or a node — closure
propagates to its incident edges) listing recurring HH:MM windows
when it's unavailable. An interval whose end is `<=` start wraps
midnight, so `["22:00", "06:00"]` is interpreted as the overnight
window.

```yaml
edges:
  - id: corridor_clean
    source: lobby
    target: corridor_main
    type: traversable
    properties:
      closed_during: [["14:00", "15:00"]]   # cleaning window
nodes:
  - id: kitchen
    label: Kitchen
    type: room
    properties:
      closed_during: [["22:00", "06:00"]]    # overnight
```

```bash
semantic-toponav plan office.yaml entrance kitchen --at-time 23:30
semantic-toponav plan office.yaml entrance meeting_room --at-time 14:30
```

```python
from semantic_toponav.planner import plan_astar, time_aware

path = plan_astar(graph, "entrance", "kitchen",
                  cost_fn=time_aware(graph, at_time="23:30"))
```

`time_aware` composes with the other cost functions via `compose_costs`.

### Multi-agent resource reservations

`time_aware` reads recurring closures that live *on the graph*.
`reservation_aware` handles claims that live *outside the graph* — another
agent has booked a corridor, elevator, or room for a specific interval and
this planner needs to route around the claim without editing the shared
YAML.

A reservation file is a flat list of `(resource_id, [start, end])` entries.
`resource_id` may name either a node OR an edge — when the cost function is
queried, the active set at `--at-time` is computed once, and any edge whose
own id or whose endpoint is in that set is blocked.

```yaml
# reservations.yaml
version: 1
reservations:
  - {resource_id: corridor_main, start: "10:00", end: "10:03", agent_id: robot_a}
  - {resource_id: elevator_E1,   start: "10:01", end: "10:05", agent_id: robot_a}
  - {resource_id: kitchen,       start: "12:00", end: "12:15", agent_id: robot_b}
```

```bash
semantic-toponav plan office.yaml entrance lab_1f \
    --reservations reservations.yaml --at-time 10:02
```

```python
from semantic_toponav.planner import (
    plan_astar, load_reservations, reservation_aware,
)

table = load_reservations("reservations.yaml")
path = plan_astar(graph, "entrance", "lab_1f",
                  cost_fn=reservation_aware(table, at_time="10:02"))
```

Reservations and time-of-day closures compose freely via `compose_costs`,
so an `--at-time` query can simultaneously honor static cleaning windows
on the graph and live claims from a shared scheduler.

### Online coordination: SharedScheduler + plan_fleet

The reservation file is a static snapshot. The
`semantic_toponav.coordination` subpackage adds the *online* layer — an
in-memory `SharedScheduler` that hands out and revokes claims at
runtime, a pluggable `ConflictPolicy` (`first_come_first_served` by
default; `priority_based` preempts lower-priority holders), and two
convenience entry points:

```python
from semantic_toponav.coordination import (
    SharedScheduler, FleetRequest, plan_fleet, plan_with_scheduler,
    priority_based,
)

scheduler = SharedScheduler()  # or SharedScheduler(policy=priority_based)

# One agent at a time:
result = plan_with_scheduler(
    graph, agent_id="r1", start="entrance", goal="kitchen",
    scheduler=scheduler, hold_start="10:00", hold_end="11:00",
)
# result.granted, result.path, result.claims (per-resource Reservations)

# Or a fleet, planned sequentially against the same scheduler:
fleet = plan_fleet(
    graph,
    [FleetRequest("r1", "entrance", "kitchen"),
     FleetRequest("r2", "entrance", "lab"),
     FleetRequest("r3", "entrance", "office_2f", priority=5)],
    scheduler,
    hold_start="10:00", hold_end="11:00",
)
print(fleet.all_granted, fleet.by_agent())
```

Sequential greedy is the simplest correct strategy: each agent sees
the claims left by the earlier ones, so the assignment is
deterministic in the request order. Under the priority policy, a
request with `priority > 0` is allowed to plan as if no reservations
existed and then preempts any conflicting holds at claim time —
useful when an emergency / oncall agent has to route over already-
booked resources.

CLI form for dry-runs:

```bash
semantic-toponav fleet-plan examples/indoor_office.yaml \
    --agent r1:entrance:kitchen \
    --agent r2:entrance:lab \
    --agent r3:entrance:office_2f:5 \
    --hold-start 10:00 --hold-end 11:00 \
    --policy priority
```

Each invocation builds a fresh empty scheduler — production
deployments wire `SharedScheduler` into a long-running service.

#### Joint fleet optimization beyond sequential greedy

Sequential greedy commits to the caller's order. `plan_fleet_joint`
clones the scheduler, tries multiple orderings on the copy, scores
each by `(granted_count, total_path_cost)`, and applies the winning
ordering to the real scheduler. Small fleets (`n! ≤ max_permutations`,
default `120` = `5!`) are enumerated; larger fleets fall back to a
fixed set of heuristic orderings (insertion / reverse / priority-DESC
/ deadline-ASC):

```python
from semantic_toponav.coordination import (
    SharedScheduler, FleetRequest,
    plan_fleet_joint, plan_fleet_with_strategy,
)

scheduler = SharedScheduler()
joint = plan_fleet_joint(
    graph,
    [FleetRequest("r1", "entrance", "kitchen"),
     FleetRequest("r2", "entrance", "lab"),
     FleetRequest("r3", "entrance", "office_2f", deadline="11:00")],
    scheduler,
    hold_start="10:00", hold_end="12:00",
)
print(joint.chosen_order, joint.trials_evaluated, joint.enumerated)
# joint.fleet_result is the live FleetPlanResult from the winning order.

# Or one dispatcher across all strategies:
res = plan_fleet_with_strategy(
    graph, requests, scheduler,
    strategy="deadline",  # "greedy" | "priority" | "deadline" | "joint"
    hold_start="10:00", hold_end="12:00",
)
```

The CLI exposes the same via `--strategy`, and the `--agent` syntax
gains an optional `:HH:MM` deadline suffix:

```bash
semantic-toponav fleet-plan examples/indoor_office.yaml \
    --agent r1:entrance:kitchen:0:11:00 \
    --agent r2:entrance:lab:0:10:30 \
    --hold-start 10:00 --hold-end 12:00 \
    --strategy deadline
```

#### Branch-and-bound ordering search

`plan_fleet_joint` enumerates every permutation when `n! ≤ 120` and
falls back to four heuristic orderings beyond that. `plan_fleet_bnb`
is the pruned cousin: a DFS over partial agent orderings that scores
each leaf by `(granted_count, total_path_cost)` and cuts subtrees
that can't beat the running best. Three pruners fire — grants upper
bound, cost tie-break lower bound, and a hard `max_nodes` /
`time_budget_ms` budget — so the call stays bounded even on
adversarial inputs. On the synthetic eval suite (`n=4`, all four
scenarios) BnB matches `joint` on both grants and cost while running
about 2× faster, exactly the pruning win the design predicts.

```python
from semantic_toponav.coordination import plan_fleet_bnb

result = plan_fleet_bnb(
    graph, requests, scheduler,
    hold_start="10:00", hold_end="11:00",
    admission="hard",
    max_nodes=10_000,
)
# result.chosen_order, result.stats.nodes_pruned_by_{grants,cost},
# result.conflict_explanations  # CBS-lite "who blocked whom"
```

`plan_fleet_bnb` also returns a list of `ConflictExplanation` records
— a lightweight, descriptive analogue of CBS conflict-tree nodes
("agent X was blocked by holds from agents A, B on resources …") so
operators can diagnose admission failures without re-running the
search. CLI parity: `semantic-toponav fleet-plan ... --strategy bnb`
and `eval-synthetic --strategy bnb`.

#### Hard deadline admission control

`FleetRequest.deadline` started life as a sort key for the
`deadline` strategy. It now also functions as a *hard* constraint
when `admission="hard"` is passed to `plan_with_scheduler`,
`plan_fleet`, `plan_fleet_with_strategy`, or `plan_fleet_joint` (or
`--admission hard` on the CLI). A request whose projected arrival
time (`hold_start + path_cost × minutes_per_cost_unit`) exceeds its
deadline is rejected up-front with `reason_code="deadline_miss"`
and *zero* claims on the scheduler:

```python
result = plan_with_scheduler(
    graph, "robot42", "lobby", "office_2f", scheduler,
    hold_start="10:00", hold_end="11:00",
    deadline="10:05",
    admission="hard",
    minutes_per_cost_unit=1.0,
)
# result.granted == False, result.reason_code == "deadline_miss"
# scheduler.claims_for("robot42") == []
```

`PlanWithSchedulerResult.reason_code` is `"ok" | "no_path" |
"deadline_miss" | "reservation_conflict" | "policy_rejected"` —
use it for switch / dispatch rather than parsing `failure_reason`.
The default `admission="soft"` preserves pre-PR-37 behavior so
existing call sites are unaffected. The synthetic eval suite
reports `deadline_miss_count` per `(scenario, strategy)` trial,
which is how you tell whether the `deadline` strategy is actually
saving more grants than `greedy` under tight deadlines.

### Synthetic evaluation suite

Functional tests prove the planner *runs*; the synthetic eval suite
measures *how well* each strategy does. Four canonical graphs
(chain, star, doorway, multi-floor) plus deterministic, seed-driven
fleet generators feed `plan_fleet_with_strategy` and emit a pivoted
markdown table over the four strategies:

```bash
semantic-toponav eval-synthetic \
    --scenario all --n-agents 3 --seed 0 \
    --hold-start 10:00 --hold-end 11:00 --summary
```

Persist results to JSONL and reprint later without re-running the
planner:

```bash
semantic-toponav eval-synthetic --scenario all --n-agents 4 \
    --hold-start 10:00 --hold-end 11:00 --out trials.jsonl
semantic-toponav eval-report trials.jsonl --summary
```

The metrics block reports grant rate, total path cost, coordination
makespan, max wait, Jain's fairness, conflict count, and per-strategy
latency p50 / max. Python API mirror: `from semantic_toponav.eval
import Scenario, run_sweep, trials_to_markdown_table`. Use this
suite to validate that a strategy change actually helps — and on
which scenarios it doesn't.

## Multi-floor navigation

When nodes carry a `floor` property, three additional cost helpers and one
A* heuristic become available:

```python
from semantic_toponav.planner import (
    plan_astar, floor_change_penalty, prefer_floor, same_floor_only,
    floor_aware_heuristic, compose_costs, prefer_elevator,
)

graph = load_graph("examples/multi_floor_office.yaml")

# Stay on floor 1 unless absolutely necessary.
path = plan_astar(graph, "entrance", "exec_office_3f",
                  cost_fn=floor_change_penalty(graph, penalty=50))

# Strictly within-floor planning.
path = plan_astar(graph, "kitchen_1f", "lab_1f",
                  cost_fn=same_floor_only(graph))

# Accessibility: prefer elevators with a floor-aware heuristic.
path = plan_astar(graph, "entrance", "exec_office_3f",
                  cost_fn=compose_costs(prefer_elevator),
                  heuristic_fn=floor_aware_heuristic(floor_height=2.0))
```

The same flags are wired into the CLI: `--prefer-floor N`,
`--floor-change-penalty P`, `--same-floor-only`.

```bash
python examples/run_multi_floor_demo.py
```

![multi-floor plan, elevator route](docs/images/10_mf_elevator.png)

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

Trajectories can also be loaded from CSV (stdlib only, no pandas):

```python
from semantic_toponav.conversion import load_trajectories_from_csv

trajs = load_trajectories_from_csv(
    "examples/sample_trajectories.csv",
    x_column="x",
    y_column="y",
    trajectory_column="trajectory_id",   # grouping column, optional
)
```

Both header-based (`x`, `y`, `trajectory_id`) and headerless / positional
(integer column indices) layouts are supported. Run
`python examples/load_csv_demo.py` for an end-to-end demo:

![csv to topology](docs/images/13_csv_trajectory.png)

### Loading trajectories directly from a rosbag2 recording

If you have a ROS2 environment sourced, you can skip the CSV step
entirely and read trajectories straight out of a `ros2 bag record` output:

```python
from semantic_toponav.conversion import (
    load_trajectories_from_rosbag,
    topology_from_trajectories,
)

trajs = load_trajectories_from_rosbag("my_run")    # directory or .db3 file
graph = topology_from_trajectories(trajs, eps=0.5, min_samples=3)
```

Supported topic types are `nav_msgs/msg/Odometry`,
`geometry_msgs/msg/PoseStamped`, and
`geometry_msgs/msg/PoseWithCovarianceStamped`; each topic becomes one
trajectory in the returned list. The loader imports `rosbag2_py` and
`rclpy` lazily, so the rest of the package keeps working without ROS2
installed.

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

### Interactive web viewer

For exploration in a browser, install the `viz_web` extra (pulls in
[pyvis](https://pyvis.readthedocs.io/)) and write out a self-contained
HTML page:

```bash
pip install -e '.[viz_web]'

# From the CLI:
semantic-toponav viewer examples/multi_floor_office.yaml \
    --start entrance --goal exec_office_3f --prefer-elevator \
    --output viewer.html
xdg-open viewer.html

# Or from Python (via the bundled demo):
python examples/web_viewer_demo.py     # writes examples/multi_floor_viewer.html
```

```python
from semantic_toponav.visualization import save_interactive_html

save_interactive_html(graph, "viewer.html", path=plan)
```

Nodes are draggable, hovering surfaces type/cost/property tooltips, and
the highlighted path is overlaid in pink. The generated file is fully
offline — open it on any machine without re-running Python.

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

### Programmatic graph construction

For small graphs or unit tests, the fluent `GraphBuilder` is usually less
ceremony than hand-writing dataclasses:

```python
from semantic_toponav.graph import GraphBuilder
from semantic_toponav.planner import plan_astar

graph = (
    GraphBuilder()
    .node("entrance", type="entrance", x=0, y=0)
    .node("corridor", type="corridor", x=2, y=0)
    .node("lab",      type="room",     x=4, y=0, label="Robotics Lab")
    .connect("entrance", "corridor", "lab")           # chain edges in one call
    .build()
)

path = plan_astar(graph, "entrance", "lab")
```

`x=`/`y=` (and optional `yaw`/`frame_id`) build a `Pose2D` inline; `connect()`
lays edges through a sequence of node ids; `edge()` auto-generates an id
like `"<source>__<target>"` when one isn't passed.

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

### Embedding-based retrieval

Nodes can carry an arbitrary embedding vector under
`properties["embedding"]`. Attach CLIP / SigLIP / sentence-encoder vectors
ahead of time and `semantic-toponav` will rank candidates by cosine
similarity — no model dependency in the core:

```python
from semantic_toponav.query import (
    find_nodes_by_embedding, nearest_node_by_embedding,
)

# ... attach node.properties["embedding"] = [...]  ahead of time ...

matches = find_nodes_by_embedding(graph, query_vec, top_k=5, type="room")
goal = nearest_node_by_embedding(graph, query_vec, type="room")
```

`python examples/embedding_demo.py` runs a self-contained demo using
deterministic toy embeddings.

### VLM / CLIP encoder integration

Vectors don't have to be hand-rolled. The `semantic_toponav.encoders`
subpackage exposes a `Backend` protocol with two concrete encoders:

- `HashingBackend` — deterministic SHA-derived encoder. Zero
  dependencies. Same input always produces the same L2-normalized
  vector — useful for tests, demos, and as a smoke-test backend when
  the heavier deps aren't available.
- `CLIPBackend` — lazy `transformers.CLIPModel` wrapper. Requires the
  `[vlm]` extra (`pip install 'semantic-toponav[vlm]'`); model +
  processor load on the first `embed_*` call.

The natural pair is `embed_region_patches`, which crops one image
patch per `annotate_regions` component, embeds it, and stamps the
result onto every graph node carrying that region id:

```python
from semantic_toponav.conversion.occupancy import annotate_regions
from semantic_toponav.conversion.vlm import embed_region_patches
from semantic_toponav.encoders import HashingBackend, CLIPBackend

regions = annotate_regions(graph, occ.free_mask, resolution=occ.resolution)
backend = CLIPBackend()  # or HashingBackend(dim=64) for tests
embed_region_patches(graph, occ.free_mask, regions, backend)

# Every node now carries node.properties["embedding"], so the existing
# find_nodes_by_embedding query helper works out of the box.
```

CLI form:

```bash
semantic-toponav embed-regions graph.yaml map.yaml \
    --backend hashing --dim 64 --in-place
# or with a real RGB photo aligned to the floor plan:
semantic-toponav embed-regions graph.yaml map.yaml \
    --backend clip --image rendered.png --pad-cells 2 --in-place
```

### LLM-augmented describe-path / resolve

The deterministic `describe_path` / `resolve_goal` always run first;
an optional LLM layer can rewrite the narration into natural prose or
re-rank the top-k candidates by reading their labels. The LLM is
never allowed to invent a step or a node id — unparseable replies
or out-of-pool picks transparently fall back to the deterministic
output.

```python
from semantic_toponav.llm import EchoBackend, AnthropicBackend
from semantic_toponav.waypoint import llm_describe_path
from semantic_toponav.query import llm_resolve_goal

# Tests / offline demos: EchoBackend takes a scripted list of replies.
backend = EchoBackend(script=[
    "1. Walk in through the entrance.\n2. Head down the main corridor.\n"
    "3. Step into the meeting room.",
])
result = llm_describe_path(graph, ["entrance", "corridor_main", "meeting_room"], backend)
print(result.steps)            # rewritten prose, one entry per deterministic step
print(result.used_fallback)    # False; rewrite was accepted

# Real backend: requires the [llm] extra and ANTHROPIC_API_KEY.
backend = AnthropicBackend()  # picks ANTHROPIC_API_KEY from env
res = llm_resolve_goal(graph, "the conference room on the second floor", backend, top_k=5)
print(res.candidates[0].node_id, res.llm_reason)
```

CLI form (opt-in via `--llm-backend`):

```bash
# Echo backend is dependency-free and useful for scripted demos.
semantic-toponav describe-path examples/indoor_office.yaml entrance meeting_room \
    --llm-backend echo \
    --llm-script "1. Walk in.\n2. Head into the corridor.\n3. Settle into the meeting room."

# Real rewrite via Anthropic (needs ANTHROPIC_API_KEY + the [llm] extra).
semantic-toponav describe-path examples/indoor_office.yaml entrance meeting_room \
    --llm-backend anthropic --llm-style friendly

# Re-rank free-text goal candidates.
semantic-toponav resolve examples/indoor_office.yaml "the conference room on the second floor" \
    --llm-backend anthropic
```

#### Clarification dialog for ambiguous goals

When the deterministic resolver's top-1 and top-2 candidates have
near-equal scores, or when the LLM emits a `Clarify: <question>`
line instead of a `Top match:` pick, the result carries a
`ClarificationQuestion` instead of committing to a single answer.
Callers ask the user, then re-call `llm_resolve_goal` with a
`ClarificationAnswer` (either a `chosen_id` from the surfaced
candidate ids — out-of-pool ids are silently dropped, so the "no
invented node ids" safety property still holds — or a `free_text`
hint appended to the original query). Add
`raise_on_ambiguous=True` to surface the question through
`AmbiguousGoalError` instead.

```python
from semantic_toponav.query import (
    llm_resolve_goal, ClarificationAnswer, AmbiguousGoalError,
)

result = llm_resolve_goal(graph, "meeting room", backend)
if result.clarification is not None:
    print("Ambiguous:", result.clarification.question)
    user_pick = ask_user(result.clarification.candidates)  # node id
    result = llm_resolve_goal(
        graph, "meeting room", backend,
        clarification=ClarificationAnswer(chosen_id=user_pick),
    )
```

CLI: `resolve ... --llm-backend ... --clarify-with NODE_ID` or
`--clarify-free "on the second floor"`. JSON output grows
`llm.clarification.question` and `llm.clarification.candidate_ids`
when ambiguity is detected.

#### Visual grounding via region embeddings

When `embed-regions` has stamped region-level embeddings onto the
graph (see PR #32), `llm_resolve_goal` can take an optional
`query_encoder` and compute per-candidate cosine similarity between
the query text and each node's stored embedding. The scores are
injected into the LLM prompt as structured fields
(`embedding_score=0.42`), never as raw vectors — the model uses
them as additional retrieval signal but still picks only from the
deterministic candidate pool. CLI parity: `resolve ... --llm-backend
... --vlm-backend hashing|clip`. Candidates without an embedding
show `embedding_score=—` so the model can tell "no visual signal"
apart from "weak visual signal".

```python
from semantic_toponav.encoders import HashingBackend
from semantic_toponav.llm import EchoBackend
from semantic_toponav.query import llm_resolve_goal

# (Assume graph has been run through embed-regions or has node
# embeddings stamped some other way.)
result = llm_resolve_goal(
    graph, "second floor office", EchoBackend(script=[...]),
    query_encoder=HashingBackend(dim=32),
)
print(result.embedding_scores)  # {node_id: cosine}
```

### Visit-history memory

A small memory layer records when each node was last visited, then lets
the planner reason over that history. Visit data lives in
`node.properties` so it round-trips through YAML/JSON with no schema
change.

```python
from semantic_toponav.memory import (
    record_path, prefer_unvisited, prefer_familiar, avoid_recently_visited,
)
from semantic_toponav.planner import plan_astar

# Record the path the robot actually traversed.
record_path(graph, executed_path)

# Bias the next plan toward unexplored nodes (coverage / patrol).
path = plan_astar(graph, "entrance", "lab", cost_fn=prefer_unvisited(graph))

# Or retrace a familiar route, or avoid nodes touched in the last minute.
plan_astar(graph, "entrance", "lab", cost_fn=prefer_familiar(graph))
plan_astar(
    graph, "entrance", "lab",
    cost_fn=avoid_recently_visited(graph, within_seconds=60.0),
)
```

`python examples/memory_demo.py` walks through coverage, retrace, and
time-decay scenarios on the multi-floor example graph.

The same history layer is also addressable from the shell:

```bash
# Record what the robot just traversed, then plan again preferring new ground.
semantic-toponav record-path examples/multi_floor_office.yaml \
    entrance corridor_1f lobby_1f stairs_1f stairs_2f stairs_3f corridor_3f exec_office_3f \
    --in-place
semantic-toponav plan examples/multi_floor_office.yaml entrance exec_office_3f \
    --prefer-unvisited --visited-multiplier 10
semantic-toponav history examples/multi_floor_office.yaml
semantic-toponav clear-history examples/multi_floor_office.yaml --in-place
```

## CLI

```text
# Planning
semantic-toponav validate  GRAPH
semantic-toponav plan      GRAPH START GOAL [--algorithm astar|dijkstra] [--avoid-restricted]
                                            [--avoid-stairs] [--prefer-elevator]
                                            [--prefer-unvisited [--visited-multiplier M]]
                                            [--prefer-familiar [--familiar-multiplier M]]
                                            [--avoid-recent SECONDS [--recent-multiplier M] [--now TS]]
                                            [--at-time HH:MM] [--format text|json]
semantic-toponav waypoints     GRAPH START GOAL [...same options...]
semantic-toponav describe-path GRAPH START GOAL [...same options...]
semantic-toponav plot          GRAPH [--start S --goal G] [--avoid-*] [--save FILE] [--show]
                                                           [--edge-ids] [--title STR]

# Visit history (write to stdout by default; pass --in-place or --out FILE to persist)
semantic-toponav record-visit  GRAPH NODE_ID [--now TS] [--in-place | --out FILE]
semantic-toponav record-path   GRAPH NODE_ID... [--now TS] [--in-place | --out FILE]
semantic-toponav clear-history GRAPH [NODE_ID...] [--in-place | --out FILE]
semantic-toponav history       GRAPH [NODE_ID...] [--all]

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
semantic-toponav resolve   GRAPH "natural language goal text"
                                 [--top-k N] [--format text|json]
```

`resolve` is a deterministic (no-LLM) free-text node lookup. It
tokenizes the query, parses floor references (`2F` / `floor 2` /
`second floor` / `2nd floor`), and ranks nodes by label / type token
overlap plus floor match — useful as the offline floor under a later
LLM resolver.

```bash
semantic-toponav resolve examples/indoor_office.yaml "the kitchen"
semantic-toponav resolve examples/indoor_office.yaml "second floor office"
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
`ros2/semantic_toponav_ros/` and the custom message definitions under
`ros2/semantic_toponav_msgs/`. The wrapper ships three nodes:
`graph_loader` (publishes the validated graph as a latched `TopologyGraph`),
`waypoint_publisher` (plans and publishes semantic waypoints in JSON or
typed form), and `nav2_demo` (a worked example that forwards semantic
waypoints to Nav2's `NavigateThroughPoses`). See
[`ros2/README.md`](ros2/README.md) for the adapter design, the JSON vs
typed-message comparison, and the Nav2 integration boundary.

## Project status

This is the MVP. Things explicitly out of scope for the first version
include a behavior-tree Nav2 plugin, occupancy-to-topology conversion, VLM
labeling, and CLIP embeddings. See
[`docs/decisions.md`](docs/decisions.md) for the reasoning and
[`docs/experiments.md`](docs/experiments.md) for future directions.

The JSON wire format produced by `waypoint_publisher_node` and
`SemanticWaypoint.to_dict()` is documented (and v1-stable) under
[`docs/waypoint_schema.md`](docs/waypoint_schema.md), with a matching
JSON Schema in [`schemas/`](schemas/).

## Tests

```bash
pytest -q
```

## License

Apache-2.0.
