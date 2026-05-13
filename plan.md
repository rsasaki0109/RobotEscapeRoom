# semantic-toponav Implementation Plan

## 0. Project Intent

`semantic-toponav` is an open-source robotics navigation project based on
Semantic Topological Maps.

The goal is not to build another occupancy-grid navigation stack.
The goal is to explore the next abstraction layer above HD maps and dense metric
maps:

- Semantic Topological Map
- Graph-based Navigation
- Semantic Waypoint Planning
- Memory-oriented Navigation
- Navigation for Embodied AI

The system should separate navigation into two layers:

1. Global Semantic-Topological Planning
2. Local Motion Execution

This repository focuses on the first layer:

- topology graph abstraction
- semantic node and edge definitions
- graph routing
- semantic waypoint generation
- topology-aware navigation interfaces

The following are explicitly out of scope for the core project:

- MPC
- MPPI
- low-level control
- obstacle avoidance
- SLAM
- dense occupancy planning

Those should be integrated through existing systems such as ROS2 Nav2,
Autoware, MPPI planners, or policy-based local planners.

## 1. Development Principles

Use a small concrete implementation first.
Avoid early over-abstraction.

Prioritize:

- simple graph structure
- readable code
- fast experimentation
- working examples
- clear serialization formats
- testable planning behavior

Avoid:

- large middleware design
- plugin systems in the first version
- generic graph frameworks unless truly needed
- premature performance optimization
- complex class hierarchies

The MVP should be usable from Python first, then wrapped for ROS2.
ROS2 integration should not pollute the core graph and planner code.

## 2. Target Repository Structure

Create this structure:

```text
semantic-toponav/
├── semantic_toponav/
│   ├── __init__.py
│   ├── graph/
│   │   ├── __init__.py
│   │   ├── types.py
│   │   ├── topology_graph.py
│   │   └── serialization.py
│   ├── planner/
│   │   ├── __init__.py
│   │   ├── astar.py
│   │   ├── dijkstra.py
│   │   └── semantic_costs.py
│   ├── waypoint/
│   │   ├── __init__.py
│   │   └── semantic_waypoint.py
│   └── cli/
│       ├── __init__.py
│       └── main.py
├── ros2/
│   ├── README.md
│   └── semantic_toponav_ros/
│       ├── package.xml
│       ├── setup.py
│       ├── resource/
│       │   └── semantic_toponav_ros
│       └── semantic_toponav_ros/
│           ├── __init__.py
│           ├── graph_loader_node.py
│           └── waypoint_publisher_node.py
├── examples/
│   ├── indoor_office.yaml
│   ├── indoor_office.json
│   └── run_indoor_demo.py
├── docs/
│   ├── decisions.md
│   ├── experiments.md
│   └── interfaces.md
├── tests/
│   ├── test_graph_serialization.py
│   ├── test_dijkstra.py
│   ├── test_astar.py
│   └── test_semantic_waypoints.py
├── pyproject.toml
├── README.md
└── plan.md
```

The first milestone can skip ROS2 runtime execution if ROS2 is not installed,
but the ROS2 package skeleton and node code should be written cleanly.

## 3. Milestone 1: Python Package Skeleton

Create a minimal Python package using `pyproject.toml`.

Recommended dependencies:

- `pyyaml` for YAML graph loading
- `networkx` is optional, but prefer not using it for the first implementation
- `pytest` for tests
- `ruff` for linting if desired

Suggested `pyproject.toml` goals:

- package name: `semantic-toponav`
- import package: `semantic_toponav`
- Python version: `>=3.10`
- CLI command: `semantic-toponav`

Acceptance criteria:

- `python -m semantic_toponav.cli.main --help` works
- `pytest` can discover tests
- package imports work from the repository root

## 4. Milestone 2: Core Graph Data Model

Implement a small, explicit graph model.

### Node

File: `semantic_toponav/graph/types.py`

Define a `TopologyNode` dataclass:

- `id: str`
- `label: str`
- `type: str`
- `pose: Optional[Pose2D]`
- `properties: dict[str, Any]`

Node type examples:

- `corridor`
- `room`
- `intersection`
- `elevator`
- `stairs`
- `entrance`

Pose should be optional because the graph is semantic first.
However, optional geometry is useful for heuristic A* cost and visualization.

Define a simple `Pose2D` dataclass:

- `x: float`
- `y: float`
- `yaw: float = 0.0`
- `frame_id: str = "map"`

### Edge

Define a `TopologyEdge` dataclass:

- `id: str`
- `source: str`
- `target: str`
- `type: str`
- `cost: float = 1.0`
- `bidirectional: bool = True`
- `properties: dict[str, Any]`

Edge type examples:

- `traversable`
- `stairs_up`
- `stairs_down`
- `elevator_connection`
- `restricted`
- `one_way`

### Graph

File: `semantic_toponav/graph/topology_graph.py`

Implement `TopologyGraph` with:

- `add_node(node: TopologyNode) -> None`
- `add_edge(edge: TopologyEdge) -> None`
- `get_node(node_id: str) -> TopologyNode`
- `neighbors(node_id: str) -> list[TopologyEdge]`
- `has_node(node_id: str) -> bool`
- `validate() -> None`
- `node_ids() -> list[str]`
- `edge_ids() -> list[str]`

Validation should check:

- duplicate node IDs
- duplicate edge IDs
- edge source exists
- edge target exists
- edge cost is non-negative
- one-way / bidirectional semantics are internally consistent

Do not add a complex abstract graph interface in the MVP.

Acceptance criteria:

- can create graph in code
- can add semantic nodes and edges
- can query neighbors
- invalid edge references raise a clear exception

## 5. Milestone 3: YAML and JSON Serialization

File: `semantic_toponav/graph/serialization.py`

Support loading and saving topology graphs from YAML and JSON.

Recommended schema:

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
  - id: corridor_main
    label: Main Corridor
    type: corridor
    pose: {x: 4.0, y: 0.0, yaw: 0.0, frame_id: map}
    properties:
      floor: 1
edges:
  - id: entrance_to_corridor
    source: entrance
    target: corridor_main
    type: traversable
    cost: 1.0
    bidirectional: true
    properties: {}
```

Implement:

- `load_graph(path: str | Path) -> TopologyGraph`
- `save_graph(graph: TopologyGraph, path: str | Path) -> None`
- `graph_from_dict(data: dict[str, Any]) -> TopologyGraph`
- `graph_to_dict(graph: TopologyGraph) -> dict[str, Any]`

Use file extension to select YAML or JSON:

- `.yaml`
- `.yml`
- `.json`

Acceptance criteria:

- YAML example loads
- JSON example loads
- graph can round-trip through YAML
- graph can round-trip through JSON
- schema errors produce readable exceptions

## 6. Milestone 4: Dijkstra Planner

File: `semantic_toponav/planner/dijkstra.py`

Implement Dijkstra over the topology graph.

API:

```python
def plan_dijkstra(
    graph: TopologyGraph,
    start_id: str,
    goal_id: str,
    cost_fn: Callable[[TopologyEdge], float] | None = None,
) -> list[str]:
    ...
```

Behavior:

- return node ID path from start to goal
- include start and goal in the path
- raise a clear exception if no path exists
- raise a clear exception if start or goal does not exist
- use edge cost by default
- support custom cost function

Acceptance criteria:

- shortest path works on simple graph
- no-path case is tested
- restricted edge can be avoided through custom cost function

## 7. Milestone 5: A* Planner

File: `semantic_toponav/planner/astar.py`

Implement A* on the topology graph.

API:

```python
def plan_astar(
    graph: TopologyGraph,
    start_id: str,
    goal_id: str,
    cost_fn: Callable[[TopologyEdge], float] | None = None,
    heuristic_fn: Callable[[TopologyGraph, str, str], float] | None = None,
) -> list[str]:
    ...
```

Default heuristic:

- if both nodes have `pose`, use Euclidean distance
- otherwise return `0.0`

This makes A* degrade to Dijkstra when geometry is unavailable.

Acceptance criteria:

- path equals expected route on office example
- heuristic works when poses exist
- planner still works when poses are missing
- missing node and no-path errors are tested

## 8. Milestone 6: Semantic-Aware Routing

File: `semantic_toponav/planner/semantic_costs.py`

Implement simple semantic cost helpers.

Examples:

```python
def default_edge_cost(edge: TopologyEdge) -> float:
    ...

def avoid_restricted(edge: TopologyEdge) -> float:
    ...

def prefer_elevator(edge: TopologyEdge) -> float:
    ...

def avoid_stairs(edge: TopologyEdge) -> float:
    ...

def compose_costs(*cost_functions):
    ...
```

Initial cost policy:

- `restricted` edges should be very expensive or blocked
- `stairs_up` / `stairs_down` can have additional penalty
- `elevator_connection` can be preferred for accessibility mode
- `one_way` should only be traversable in the allowed direction

Keep this simple.
Do not create a full policy engine yet.

Acceptance criteria:

- same graph can produce different route depending on semantic cost function
- tests cover restricted, stairs, and elevator preference

## 9. Milestone 7: Semantic Waypoint Generation

File: `semantic_toponav/waypoint/semantic_waypoint.py`

Planner output should not only be raw node IDs.
Convert a path into semantic waypoints.

Define:

```python
@dataclass
class SemanticWaypoint:
    node_id: str
    node_label: str
    node_type: str
    action: str
    instruction: str
    pose: Pose2D | None = None
    properties: dict[str, Any] = field(default_factory=dict)
```

Implement:

```python
def path_to_semantic_waypoints(
    graph: TopologyGraph,
    path: list[str],
) -> list[SemanticWaypoint]:
    ...
```

Example instructions:

- entering a corridor: `Proceed through Main Corridor`
- entering an intersection: `Navigate to Lobby Intersection`
- entering an elevator: `Take elevator at Elevator A`
- entering stairs: `Use stairs at North Stairs`
- entering room: `Enter Meeting Room`

The wording can be simple and deterministic.
Avoid LLM-generated instructions in the MVP.

Acceptance criteria:

- path node IDs convert to semantic waypoints
- node type changes produce appropriate action strings
- output is deterministic and testable

## 10. Milestone 8: CLI

File: `semantic_toponav/cli/main.py`

Implement a small CLI for local experimentation.

Commands:

```bash
semantic-toponav validate examples/indoor_office.yaml
semantic-toponav plan examples/indoor_office.yaml entrance meeting_room
semantic-toponav waypoints examples/indoor_office.yaml entrance meeting_room
```

Suggested options:

- `--algorithm astar|dijkstra`
- `--avoid-restricted`
- `--avoid-stairs`
- `--prefer-elevator`
- `--format text|json`

Output examples:

```text
Path:
  entrance -> corridor_main -> lobby_intersection -> meeting_room
```

```text
Semantic Waypoints:
  1. Enter Entrance
  2. Proceed through Main Corridor
  3. Navigate to Lobby Intersection
  4. Enter Meeting Room
```

Acceptance criteria:

- CLI validates graph file
- CLI prints path
- CLI prints semantic waypoints
- JSON output is machine-readable

## 11. Milestone 9: Indoor Navigation Example

File: `examples/indoor_office.yaml`

Create a small but meaningful indoor topology:

- entrance
- main corridor
- lobby intersection
- kitchen
- meeting room
- lab
- elevator
- stairs
- second floor corridor
- second floor office

Include multiple route options:

- normal corridor route
- stairs route
- elevator route
- restricted route

This is important because semantic-aware routing needs route alternatives.

Also create:

- `examples/indoor_office.json`
- `examples/run_indoor_demo.py`

The demo should:

- load graph
- plan route
- print node path
- print semantic waypoints
- show a second plan with `avoid_stairs` or `prefer_elevator`

Acceptance criteria:

- example can be run without ROS2
- output clearly demonstrates semantic routing

## 12. Milestone 10: Documentation

Create and maintain:

### `README.md`

Include:

- project purpose
- what this project is and is not
- quick start
- graph schema example
- CLI examples
- planner behavior
- ROS2 integration status

### `docs/interfaces.md`

Document:

- graph schema
- Python API
- planner API
- semantic waypoint structure
- ROS2 message strategy

### `docs/decisions.md`

Record early design decisions:

- semantic-topological planner is separate from local control
- Python-first MVP
- no dense occupancy planning in core
- no complex plugin architecture initially
- deterministic waypoint generation instead of LLM-generated text

### `docs/experiments.md`

Track:

- indoor office graph
- semantic cost experiments
- route comparison examples
- future VLM / CLIP / memory experiments

Acceptance criteria:

- a new contributor can understand the project from README
- interface docs are precise enough to implement against
- design decisions explain what is intentionally out of scope

## 13. Milestone 11: ROS2 Package Skeleton

Create `ros2/semantic_toponav_ros`.

This package should be a thin adapter.
The core Python package should remain ROS-independent.

### Graph Loader Node

File: `ros2/semantic_toponav_ros/semantic_toponav_ros/graph_loader_node.py`

Responsibilities:

- read graph path from ROS parameter
- load topology graph
- validate graph
- expose basic information through logs or service

Parameters:

- `graph_path`
- `frame_id`

### Waypoint Publisher Node

File: `ros2/semantic_toponav_ros/semantic_toponav_ros/waypoint_publisher_node.py`

Responsibilities:

- load graph
- plan from `start_node` to `goal_node`
- publish semantic waypoint sequence

For the MVP, if custom ROS messages are too much, publish JSON on:

```text
/semantic_toponav/waypoints
```

using `std_msgs/msg/String`.

Later, replace with custom messages:

- `SemanticWaypoint.msg`
- `SemanticWaypointArray.msg`
- `TopologyNode.msg`
- `TopologyEdge.msg`

Acceptance criteria:

- package layout is valid
- node code is readable
- ROS dependency is isolated under `ros2/`
- repository still works without ROS2 installed

## 14. Milestone 12: Nav2 Integration Demo

Create docs and a minimal demo path for Nav2 integration.

The core idea:

1. semantic-toponav plans node route
2. route is converted to semantic waypoints
3. each waypoint may include an optional pose
4. Nav2 receives pose goals for local execution

For MVP, do not implement deep Nav2 behavior-tree integration.
Start with:

- publish waypoints
- provide a script/node that converts waypoint poses to Nav2 goals
- document assumptions

Create:

- `ros2/README.md`
- optional `ros2/semantic_toponav_ros/semantic_toponav_ros/nav2_demo_node.py`

Nav2 integration should be described as:

- semantic planner decides "where and why"
- Nav2 handles "how to move locally"

Acceptance criteria:

- clear demo instructions exist
- adapter boundary is documented
- no low-level local planning is implemented in this repository

## 15. Testing Plan

Use `pytest`.

Minimum tests:

- graph node/edge creation
- duplicate node and edge errors
- edge with missing source/target error
- YAML load
- JSON load
- YAML/JSON round-trip
- Dijkstra shortest path
- A* with pose heuristic
- A* without pose heuristic
- no-path exception
- semantic costs change route
- path-to-waypoints conversion
- CLI smoke tests if practical

Test command:

```bash
pytest -q
```

If using `rtk` in this local environment:

```bash
rtk pytest -q
```

## 16. Suggested Implementation Order

Recommended order for Claude:

1. Create Python package skeleton and `pyproject.toml`
2. Implement graph dataclasses
3. Implement `TopologyGraph`
4. Implement YAML/JSON serialization
5. Add indoor office YAML example
6. Add serialization tests
7. Implement Dijkstra
8. Implement A*
9. Add planner tests
10. Implement semantic cost functions
11. Add semantic routing tests
12. Implement semantic waypoint generation
13. Add waypoint tests
14. Implement CLI
15. Add demo script
16. Write README and docs
17. Add ROS2 package skeleton
18. Add ROS2 waypoint publisher node
19. Document Nav2 integration
20. Run tests and fix failures

Do not begin with ROS2.
The core graph and planner should work before ROS2 integration.

## 17. Error Handling Guidelines

Use clear custom exceptions where useful:

- `GraphValidationError`
- `GraphLoadError`
- `PlanningError`
- `NoPathError`

Keep exceptions simple.
Do not build a large exception framework.

Error messages should include:

- node ID
- edge ID
- graph file path where relevant
- start and goal IDs for planning failures

## 18. Coding Style Guidelines

Keep code direct and concrete.

Use:

- dataclasses
- type hints
- small modules
- deterministic functions
- simple tests

Avoid:

- global mutable state
- hidden planner configuration
- inheritance-heavy design
- runtime magic
- ROS imports inside core modules

The package should be useful as a normal Python library:

```python
from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.planner.astar import plan_astar
from semantic_toponav.waypoint.semantic_waypoint import path_to_semantic_waypoints

graph = load_graph("examples/indoor_office.yaml")
path = plan_astar(graph, "entrance", "meeting_room")
waypoints = path_to_semantic_waypoints(graph, path)
```

## 19. Definition of Done for MVP

The MVP is done when:

- graph schema is defined
- YAML and JSON graph files load
- indoor office example exists
- Dijkstra works
- A* works
- semantic cost routing works
- semantic waypoints are generated
- CLI can validate and plan
- tests pass
- README explains the concept and usage
- docs explain interfaces and decisions
- ROS2 package skeleton exists
- waypoint publisher node exists
- Nav2 integration boundary is documented

The MVP does not need:

- production-grade editor UI
- custom ROS messages
- full Nav2 behavior tree integration
- real robot deployment
- SLAM integration
- occupancy grid conversion
- VLM labeling
- CLIP embeddings
- memory graph

## 20. Stretch Goals After MVP

Only after the MVP works:

- simple topology editor CLI
- web-based topology graph viewer/editor
- occupancy-to-topology conversion experiment
- trajectory-to-topology generation
- semantic memory layer
- place recognition
- VLM semantic labeling
- CLIP embedding per node
- dynamic graph updates
- multi-floor navigation examples
- custom ROS2 messages
- Nav2 behavior tree plugin
- embodied AI agent interface

## 21. Claude Prompt

Use this prompt when handing the work to Claude:

```text
You are implementing the initial MVP for semantic-toponav.

Read plan.md first and follow it closely.
Start with the Python core package, not ROS2.

Implementation priorities:
1. concrete graph dataclasses
2. YAML/JSON serialization
3. Dijkstra and A*
4. semantic cost functions
5. semantic waypoint generation
6. indoor office example
7. CLI
8. tests
9. docs
10. ROS2 skeleton only after the core works

Keep the design simple.
Do not introduce a complex abstraction layer.
Do not implement local planning, obstacle avoidance, SLAM, MPC, or MPPI.
Those are integration targets, not this repository's core.

Run tests before finishing and summarize what was implemented.
```

