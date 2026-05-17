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

---

> **Sections 0–18 above are the original MVP plan, preserved as
> historical record.** What follows in sections 19+ reflects the
> current state of the repository as of 2026-05-17 (post-PR #62). For
> the running paper-track direction see also
> [`docs/paper_outline.md`](docs/paper_outline.md) and the memory
> file `project_paper_freeze_direction.md`.

## 19′. Definition of Done for MVP — ✅ Complete

The MVP shipped in the initial PR arc. Items below are kept as
historical record; everything is done.

- ✅ graph schema is defined
- ✅ YAML and JSON graph files load
- ✅ indoor office example exists
- ✅ Dijkstra + A* work
- ✅ semantic cost routing works
- ✅ semantic waypoints are generated
- ✅ CLI can validate and plan
- ✅ tests pass (913 passed, 1 skipped as of 2026-05-17, post-PR #67)
- ✅ README explains the concept and usage
- ✅ docs explain interfaces and decisions
- ✅ ROS2 package skeleton exists
- ✅ waypoint publisher node exists
- ✅ Nav2 integration boundary is documented

The MVP intentionally did not include the items below at the time;
many have since shipped (see §20′) or are deferred to ecosystem
repos (see §23′).

- production-grade editor UI → `live-viewer` ships; web *editor* is Phase C
- custom ROS messages → shipped (PR #9, `semantic_toponav_msgs`)
- full Nav2 behavior tree integration → Phase C ecosystem
- real robot deployment → not a repo concern
- SLAM integration → out of scope, integration target only
- occupancy grid conversion → shipped (PR #18 / #27 / #28 / #29)
- VLM labeling → shipped (PR #32 + #52)
- CLIP embeddings → shipped (PR #32)
- memory graph → shipped (PR #7)

## 20′. Stretch Goals After MVP — ✅ All shipped

Every item from the original "after the MVP works" list has landed.
PR references kept so a future reader can trace each capability back
to its introduction.

- ✅ simple topology editor CLI — PR #19 (`inspect / add-node /
  add-edge / rm-node / rm-edge / undo / diff` with auto `.bak`)
- ✅ web-based topology graph viewer — PR #16 (`viewer`, pyvis) +
  PR #22 (`live-viewer` with file-watch). *Browser-mutation editor*
  is Phase C ecosystem.
- ✅ occupancy-to-topology conversion — PR #18 (fusion pipeline) +
  PR #27 (door detection) + PR #28 (region segmentation) +
  PR #29 (full CLI)
- ✅ trajectory-to-topology — PR #4–5 (CSV / rosbag2) + PR #21
  (post-processing) + PR #26 (iterative fusion)
- ✅ semantic memory layer — PR #7
- ✅ place recognition — PR #7 / #8 (embedding-based retrieval)
- ✅ VLM semantic labeling — PR #32 + PR #52 (`AlignedRgbSource`
  Protocol for out-of-repo adapters)
- ✅ CLIP embedding per node — PR #32 (`embed-regions` CLI)
- ✅ dynamic graph updates — PR #19 (CLI editor + undo) + PR #22
  (live-reload)
- ✅ multi-floor navigation examples — `floor_change_penalty` /
  `prefer_floor` / `same_floor_only` / `floor_aware_heuristic` cost
  helpers + `examples/multi_floor_office.yaml` +
  `examples/run_multi_floor_demo.py`
- ✅ custom ROS2 messages — PR #9
- ⏸ Nav2 behavior tree plugin — deferred to Phase C (C++/ROS, out-of-repo)
- ✅ embodied AI agent interface — generalized as six Protocols
  with public conformance suites (PR #53 + #58)

## 21′. Post-MVP arc — coordination, language, eval, conformance

After the MVP and stretch goals landed, the project grew a substantial
post-MVP arc organized around five axes.

### 21′.1 Online coordination

- PR #34 — `SharedScheduler` + `plan_fleet` + `ConflictPolicy` plug point
- PR #35 — `plan_fleet_joint` (n! enumeration + heuristic fallback)
- PR #37 — Hard deadline admission with structured `reason_code`
- PR #38 — Branch-and-bound joint scheduler + `ConflictExplanation`
  (CBS-lite diagnostics)
- PR #41 — Scheduler RPC shim (`SchedulerProtocol` / `Transport`)
- PR #42 — BnB fairness objectives (`minimax_cost` / `max_fairness`)
- PR #43 — HTTP reference transport (stdlib-only)
- PR #45 — Exhaustive MIS baseline (`plan_fleet_exhaustive`, grant-rate upper bound)
- PR #50 — Scheduler state persistence (`save_scheduler` / `load_scheduler`)
- PR #59 — Insertion-based fleet repair (`plan_fleet_insert`,
  `O(k·(n+k))` vs `O((n+k)!)`)

### 21′.2 LLM / VLM grounding

- PR #32 — VLM/CLIP encoder integration (`Backend` Protocol)
- PR #33 — LLM-augmented `describe-path` / `resolve` (`LLMBackend`
  Protocol, deterministic floor + LLM rewrite)
- PR #39 — Region embeddings injected as scalar `embedding_score=`
  (raw vectors never serialized)
- PR #40 — Clarification dialog primitives
- PR #44 — Multi-turn `DialogSession`
- PR #52 — `AlignedRgbSource` Protocol + `StaticImageRgbSource`
- PR #57 — Mid-traversal LLM describer rewrite (`start_index=` /
  `situation=` kwargs)

### 21′.3 Cost composition

- PR #25 — Time-of-day restrictions (`time_aware`, midnight-wrap)
- PR #31 — Static reservation table (`reservation_aware`)
- PR #54 — Calendar-aware temporal graphs (`at_date=`, weekday
  filters, `closed_on_dates`)
- PR #55 — Soft preference cost (`preference_aware`, caller-defined
  keys, clamp-to-`[0.1, 10.0]`)
- PR #56 — Node-level preference defaults (endpoint-node average
  inheritance, `use_node_defaults=False` opt-out)

### 21′.4 Evaluation + measurement substrate

- PR #36 — Synthetic eval suite (`eval-synthetic` / `eval-report`,
  4 generators, latency p50/p95, Jain fairness, JSONL+Markdown)
- PR #46 — Exhaustive into eval suite + grant_rate denominator fix
- PR #47 — `--bnb-objective` CLI flag on eval-synthetic
- PR #60 — Language-grounding eval suite (`eval-grounding`,
  gold-corpus YAML, resolver + describer-safety metrics)

### 21′.5 Protocol conformance + schema discipline

- PR #53 — Public Protocol conformance suites (six suites under
  `semantic_toponav.testing.conformance`)
- PR #58 — Conformance failure-mode depth (empty/large/unicode
  prompts; determinism; cos(v,v)≈1; idempotent release; atomic
  rollback; half-open adjacency; shape stability)
- PR #61 — **v1.0 wire schema lock** — `PlanWithSchedulerResult`,
  `FleetPlanResult`, `ConflictExplanation`, `ResolveTrace`, plus
  preference metadata; 15 tests keep dataclass `to_dict()` shapes
  and JSON Schema files in lockstep. Closed-set `reason_code` enum
  (`"ok" | "no_path" | "deadline_miss" | "reservation_conflict" |
  "policy_rejected"`) is verified consistent across
  `PlanWithSchedulerResult` and `ConflictExplanation` so adapters
  dispatching on it never see surprise values

### 21′.6 Documentation + branding

- PR #48 — README slim (1125 → 161 lines) + visual gallery + 5
  new docs (`conversion` / `cost_composition` / `coordination` /
  `queries` / `cli`)
- PR #49 — Animated GIF hero (4-frame multi-floor demo)
- PR #51 — `docs/experiments.md` sync through PR #50
- PR #62 — `docs/paper_outline.md` (5-chapter evaluation structure
  + evidence index + open holes)
- PR #63 — **`CHANGELOG.md`** consolidating PR #1–#62 into v1.0
  release notes (Keep a Changelog format, semver). The `[1.0.0]`
  section is marked **pending** so flipping it to an ISO date and
  cutting the tag is a one-line edit when the user-side decisions
  in §24′ are made
- PR #64 — Cross-reference audit aligning docs with the
  post-PR-#63 v1 surface (added `live-viewer` / `undo` / `diff` /
  `eval-grounding` to `cli.md`; fixed `fleet-plan --strategy`
  choices; added Stable-wire-format sections to `coordination.md` +
  `queries.md`; refreshed `tutorial.md` "Going further"; cleared
  two stale Future-directions lines in `experiments.md` about
  repair search + mid-traversal rewrite)
- PR #65 — **VLM region-embedding demo** —
  `examples/vlm_region_embedding_demo.py` builds the end-to-end
  `annotate_regions` → `embed_region_patches(HashingBackend)` →
  cosine-similarity heatmap pipeline against the bundled sample
  map. Outputs: `docs/images/14_vlm_region_overview.png` (2×2 grid)
  + `docs/images/15_vlm_region_cycle.gif` (3-frame cycling
  animation). README gains a "VLM region embedding" gallery row;
  the docstring + caption explicitly call out the `CLIPBackend` +
  `AlignedRgbSource` upgrade path
- PR #66 — **Coordination-strategies demo** —
  `examples/coordination_strategies_demo.py` builds an
  intentionally adversarial 5-agent scenario on a 10-node chain
  where greedy / priority grant 1/5 and BnB / exhaustive grant 4/5.
  Outputs: `docs/images/16_coordination_strategies.png` +
  `docs/images/17_coordination_cycle.gif`. With this PR the README
  gallery covers all three axes (Plan / Resolve / Coordinate) with
  hero visuals — `docs/paper_outline.md` §4 has its lead figure
- PR #67 — **Committed sample grounding report**
  (`docs/grounding_report_sample.md`) — static snapshot of
  `eval-grounding` against the shipped corpus with a provenance
  header (git ref / date / exact command) and "How to read these
  numbers" annotations. Reviewers / paper-writers see the actual
  deterministic resolver result (precision@1 = 1.00, fp_resolve =
  0.20) without firing up the eval CLI. Real-backend Anthropic
  snapshot is intentionally not committed (would require API
  credentials in CI); user-side open hole per
  `docs/paper_outline.md` §7
- README polish 2026-05-15 (`3d31fd1`) — three-axis What-it-does,
  multi-floor gallery row, status section reflecting post-PR-59 surface

## 22′. Current state — post-v1.0 (post-PR #71, post-Phase-C bootstrap, 2026-05-18)

Headline numbers and surfaces a future visitor should read first.

- **71 PRs merged**, ~16,000 LOC of Python, **913 tests passing, 1
  skipped**
- **`v1.0.0` tagged 2026-05-17** — annotated tag at commit `880de64`
  (release PR #71), GitHub Release published as latest. CHANGELOG's
  `[1.0.0] — pending` flipped to `2026-05-17`; `[Unreleased]` polish
  folded into the v1.0 body
- **Six v1-locked wire formats** with JSON Schema validation in CI
  (`SemanticWaypointArray`, `PlanWithSchedulerResult`,
  `FleetPlanResult`, `ConflictExplanation`, `ResolveTrace`, plus
  the preference metadata convention)
- **Six Protocol plug points** with public conformance suites
  including failure-mode depth: `LLMBackend`, encoder `Backend`,
  `AlignedRgbSource`, `SchedulerProtocol`, `Transport`,
  `ConflictPolicy`
- **Seven fleet strategies** (`greedy` / `priority` / `deadline` /
  `joint` / `bnb` × 3 objectives / `exhaustive` MIS / `insert`)
  exposed via Python API; `fleet-plan` / `eval-synthetic` CLIs
  cover all but `insert` (Python-only by design — see
  `coordination.md`)
- **Two eval suites** — `eval-synthetic` for coordination,
  `eval-grounding` for language. Both produce JSONL + Markdown
  for later re-rendering.
- **Three-axis README gallery hero coverage**:
  - Plan — `docs/images/demo.gif` (4-frame multi-floor cost
    composition cycling)
  - Resolve — `docs/images/15_vlm_region_cycle.gif` (3-frame VLM
    region cosine-similarity heatmap cycling)
  - Coordinate — `docs/images/17_coordination_cycle.gif` (4-frame
    greedy 1/5 vs BnB 4/5 cycling)
- **Reference grounding numbers** on the **expanded 50-case fixture**
  `tests/fixtures/grounding/multi_floor_office.yaml` (33 precise /
  9 ambiguous / 8 unresolvable): deterministic resolver
  precision@1 = 1.00, recall@3 = recall@5 = 1.00,
  false_positive_resolve = 0.25, abstention = 0.75. Sample report
  committed at `docs/grounding_report_sample.md` (provenance pinned
  to `feat/grounding-corpus-expansion @ 16be17bad650`) so the numbers
  are visible without firing up the CLI.
- **Phase C ecosystem bootstrap (out-of-repo per §23′.2)** started
  2026-05-17 / 2026-05-18:
  - [`rsasaki0109/semantic-toponav-nav2-bt`](https://github.com/rsasaki0109/semantic-toponav-nav2-bt)
    v0.1.0 scaffold + lint-cleanup PR #2 (`a38e716`, closes issue #1).
    `ament_lint_auto` + `ament_lint_common` green; cpplint / uncrustify
    / xmllint / lint_cmake all pass, `ament_copyright` excluded via
    `AMENT_LINT_AUTO_EXCLUDE` and documented.
  - [`rsasaki0109/semantic-toponav-foxglove-panel`](https://github.com/rsasaki0109/semantic-toponav-foxglove-panel)
    v0.2.0 (`990aef6`). Two panels: `Semantic TopoNav Panel`
    (`/fleet_plan_result` → per-agent Gantt + reason_code table) and
    `Semantic TopoNav Conflicts` (`/conflict_explanations` → count-by-
    reason summary + per-conflict table). 12 jest tests green on
    Node 20.

`docs/paper_outline.md` organizes these into a 5-chapter paper
evaluation structure with an evidence index pointing back at the
exact test names that back each claim.

## 23′. Forward direction — Phase B + Phase C

This is the live forward direction, written after the 2026-05-15
GPT pro 2nd review which advised *"collapse, not expand"*: the
natural extensions of every PR #35 axis have all shipped, so the
next moves are paper-track and ecosystem, not more in-tree features.

### 23′.1 Phase B — paper freeze + v1.0 release (current)

| Phase B item | Status |
|---|---|
| Phase A: `eval-grounding` shipped | ✅ PR #60 (2026-05-16) |
| v1.0 schema lock | ✅ PR #61 (2026-05-16) |
| Paper outline doc | ✅ PR #62 (2026-05-16) |
| CHANGELOG / release notes consolidating PR #1–#62 | ✅ PR #63 (2026-05-17) |
| Cross-reference audit (tutorial / experiments / cli) vs v1 surface | ✅ PR #64 (2026-05-17) |
| **v1.0.0 release** — CHANGELOG date flip + annotated tag + GitHub Release | ✅ PR #71 (2026-05-17, `880de64`) |
| User-side decisions (see §24′) | gating paper-writing only — did not gate the tag |

**All Phase B core coding items shipped.** Post-Phase-B polish PRs
(grouped under `CHANGELOG.md [Unreleased] → Documentation`) have
also landed:

| Polish PR | What |
|---|---|
| ✅ PR #65 (2026-05-17) | VLM region-embedding demo (`examples/vlm_region_embedding_demo.py`) + cycling GIF in README gallery |
| ✅ PR #66 (2026-05-17) | Coordination-strategies demo (`examples/coordination_strategies_demo.py`) + cycling GIF; the 1/5-vs-4/5 BnB-beats-greedy figure paper §4 needed |
| ✅ PR #67 (2026-05-17) | `docs/grounding_report_sample.md` static snapshot with provenance header |
| ✅ PR #68 (2026-05-17) | `docs/decisions.md` integrity pass — D-12..D-17 (Protocol bar, schema lock policy, LLM safety property, MAPF non-competition, out-of-repo split, paper-freeze direction) |
| ✅ PR #69 (2026-05-17) | Gold corpus expansion 22 → 50 cases (33 precise / 9 ambiguous / 8 unresolvable); sample report regenerated; cross-refs in `eval_grounding.md` / `paper_outline.md` / `experiments.md` / smoke-test assert refreshed |
| ✅ PR #70 (2026-05-17) | `examples/ten_minute_tour.py` single-file Plan + Resolve + Coordinate walk-through + README quickstart pointer |

After these, the README gallery covers all three axes (Plan /
Resolve / Coordinate) with hero visuals, the v1 wire formats are
locked + sample-validated, the grounding numbers are visible
without running anything, the design-decision log is current
through the post-MVP arc, the gold corpus is stress-tested at 50
cases, and a 10-minute single-file tour is the README's
sanity-check entry point. **§25′'s in-bounds-coding list is
exhausted**, the v1.0.0 tag has shipped (PR #71), and the next
work surfaces are the Phase C external repos (§23′.2 below) plus
the user-side decisions in §24′ — no more in-tree code-track work
remains under the moratorium.

**Protocol moratorium until v1.0** — the bar for adding a 7th
Protocol is intentionally high (≥2 non-toy implementations or a
heavy optional dep to isolate, contract page-sized + conformance-
testable, small i/o, defined fallback). What is needed *instead*
is stable trace schemas; that need is covered by §21′.5.

### 23′.2 Phase C — ecosystem repos (post-v1.0)

Explicitly out-of-repo to keep the readable-Python-core narrative
intact (no torch / Mast3R weights / C++ / TypeScript in core).
Order picked by adoption-pull:

1. **`semantic-toponav-nav2-bt`** (C++) — Nav2 BT plugin wrapping
   the `SemanticWaypointArray` → `NavigateThroughPoses` bridge
   (`nav2_demo_node.py`). Biggest robotics-user pull. Needs v1.0
   schema lock tagged first (§22′ covers it).
   - **v0.1.0 scaffolded 2026-05-17** at
     [`rsasaki0109/semantic-toponav-nav2-bt`](https://github.com/rsasaki0109/semantic-toponav-nav2-bt).
     `FollowSemanticWaypointsAction` BT.CPP v3 action node
     (`nav2_behavior_tree::BtActionNode<NavigateThroughPoses>`)
     reads `SemanticWaypointArray` from blackboard, filters
     `has_pose=false`, converts to `PoseStamped[]`, dispatches.
     Sample BT XML + gtest smoke (factory registration). Green CI
     on ROS 2 Humble container with Nav2 + BT.CPP v3 + the upstream
     `v1.0.0`-tagged `semantic_toponav_msgs`.
   - **Issue #1 closed 2026-05-17 by PR #2** (`a38e716`) —
     `ament_lint_auto` + `ament_lint_common` re-enabled; cpplint /
     uncrustify / xmllint / lint_cmake green. `ament_copyright`
     excluded via `AMENT_LINT_AUTO_EXCLUDE` (it expects a
     `CONTRIBUTING.md` and rejects the standard Apache-2.0 LICENSE
     text), documented in `CMakeLists.txt` + `CHANGELOG.md`. BT
     factory builder lambdas refactored into anonymous-namespace
     functions so uncrustify lambda-indent rules apply cleanly.
   - Open follow-up: v0.2 NavigateThroughPoses feedback wiring
     (current_waypoint, distance_remaining → blackboard) so upper
     BTs can branch on progress. Not started.
2. **`semantic-toponav-foxglove-panel`** (TypeScript) — Foxglove
   custom panel(s) visualizing the v1 wire formats.
   - **v0.1.0 scaffolded 2026-05-17, v0.2.0 shipped 2026-05-18**
     at
     [`rsasaki0109/semantic-toponav-foxglove-panel`](https://github.com/rsasaki0109/semantic-toponav-foxglove-panel)
     (release commit `990aef6`). Two panels registered:
     - `Semantic TopoNav Panel` — subscribes to `/fleet_plan_result`,
       decodes `FleetPlanResult` v1, renders per-agent Gantt of
       claims + `reason_code`-colored status table. Midnight-
       wrapping reservations (`end <= start`) split at day boundary.
     - `Semantic TopoNav Conflicts` — subscribes to
       `/conflict_explanations`, decodes `ConflictExplanation` v1
       (either array or single-record form), renders count-by-
       reason summary band + per-conflict table.
   - Pure data transforms (`src/gantt.ts`, `src/conflicts.ts`) are
     jest-tested separately from the Foxglove extension API (12
     tests green on Node 20). Shared `reason_code` palette across
     panels.
   - Open follow-up: issue #1 — wire `foxglove-extension build`
     into CI for tagged `.foxe` artifact releases. Not started.
   - Open follow-up: third panel `Semantic TopoNav Resolve` for the
     `ResolveTrace` wire format (chosen_node / abstained / candidates
     / scores). Would complete the per-wire-format panel coverage
     story. Not started.
3. **`semantic-toponav-mast3r`** (Python + torch) — Adapter
   implementing `AlignedRgbSource` against Mast3R rerenders. Plug
   point (PR #52) is already in core; this package fills in the
   heavy-deps side. **Deferred until after the paper** per the
   `project-paper-freeze-direction` memory — so the paper isn't
   framed around the vision-model adapter story. Not started.

Ecosystem items deliberately gated on real-user demand:

- WebSocket / NATS reference transports (HTTP already covers the
  pattern)
- MILP / CP-SAT solver baseline via `ortools` (past install
  failures; opt-in `[opt]` extra, user approval required)
- Cloud-backend conformance (real `AnthropicBackend` / CLIP through
  the suites — requires CI creds wired in user-controlled Actions)
- BnB-based deeper repair (insertion repair covers the practical
  incremental-admission use case)

### 23′.3 Post-v1.0 / next-paper territory

Explicitly *not* in scope for the current paper or v1.0:

- Physical execution loop integration (closed-loop SLA)
- Online environment learning (graph updates from execution feedback)
- Multi-fleet coordination across service boundaries
- Head-to-head MAPF on gridworld (CBS / EECBS / MAPF-LNS2 turf)

## 24′. Open holes — user-side decisions

Decisions that gate writing or releasing. None of them are coding
tasks; they need user judgment.

1. **Venue.** Robotics-systems (RSS / IROS / ICRA / CoRL) vs OSS
   tooling track vs LM4Nav workshop. Affects which chapters get the
   longest treatment.
2. **Single paper vs companion paper.** All five chapters in one
   work risks each being shallow. Splitting (coordination + schema
   as paper A, grounding + describer safety as paper B) is
   plausible.
3. **Real-backend numbers for `eval-grounding`.** The current
   reference numbers are deterministic only. Anthropic backend
   numbers on the 22-case fixture are needed before chapter 3
   framing is final.
4. **Human-eval scope for describer rewrite.** 0 cases (rely on the
   four deterministic invariants), 20–50 cases (sidebar coherence
   rating), or larger crowd panel.
5. ~~**v1.0 tag timing.**~~ Resolved 2026-05-17 — tagged
   immediately (PR #71 / `880de64`); the paper-side decisions
   intentionally do not gate the tag. Left here so the resolution
   trail is visible.

## 25′. Claude handoff prompt (post-v1.0, post-Phase-C bootstrap)

```text
You are continuing work on semantic-toponav, a v1.0-tagged Python OSS
planner that sits between dense maps and motion executors.

Read plan.md sections 22′–24′ first to know the current state. The
short version: v1.0.0 is tagged (PR #71 / 880de64), Phase B Python
coding is closed, two Phase C external repos have been bootstrapped
(see §23′.2), and §25′'s historic in-tree coding list is fully
exhausted. There is **no in-tree work** remaining in this repo
under the moratorium.

The current ship surfaces are split:

1. Phase C external repos (out-of-repo by design — D-16 / §23′.2):
   - rsasaki0109/semantic-toponav-nav2-bt — v0.1.0 + lint cleanup
     shipped. Open: v0.2 NavigateThroughPoses feedback wiring.
   - rsasaki0109/semantic-toponav-foxglove-panel — v0.2.0 shipped
     (2 panels). Open: issue #1 foxglove-extension build CI; new
     ResolveTrace panel for v0.3.
   - semantic-toponav-mast3r — deferred until after the paper.

2. §24′ user-side decisions — paper venue / single-vs-companion /
   real-backend grounding numbers / human-eval scope. Not coding,
   not your call to ship.

If the user issues a `tugi` / `tugiikou` cue with this state:

- Do NOT autonomously start a new feature axis in this repo.
- Do NOT start a fourth Phase C package from scratch.
- Surface 2–3 candidate moves with the main trade-off in 2–3
  sentences and wait for the next cue (this is the established
  AskUserQuestion pattern — see the user-ship-pattern memory).

Typical candidate menu at this state:

- Phase C #1 (Nav2 BT) v0.2 — NavigateThroughPoses feedback ports
  (current_waypoint, distance_remaining) → blackboard so upper
  BTs can branch on progress.
- Phase C #2 (Foxglove) v0.3 — `Semantic TopoNav Resolve` panel
  for /resolve_trace, completing per-wire-format panel coverage.
- Phase C #2 (Foxglove) issue #1 — wire `foxglove-extension build`
  into CI for tagged `.foxe` artifact releases.
- §24′ decision support — surface state, do not pretend to decide.

Do not:

- add a 7th Protocol to this repo (moratorium still in force;
  the bar is in D-12)
- restart Mast3R (Phase C #3 is deferred until after the paper)
- start new in-tree feature axes (physical loop, online learning,
  multi-fleet) — those are post-v1 / next-paper territory
- compete head-to-head with MAPF specialists on gridworld
- regenerate docs/grounding_report_sample.md from CI — it is a
  manual release-prep artifact by design (see the file's "Notes"
  section)
- bump the v1 schemas without a v2 plan + a real consumer asking
  (the schema lock policy is in D-13)

Workflow conventions:

- One PR per coherent unit; ship full cycles (design → implement
  → tests → push → PR → CI → squash-merge --delete-branch → git
  pull on main) without re-confirmation between steps. For
  Phase C external repos this includes the CI iter loop until
  green (uncrustify / linters / etc.)
- Commit author = self only (no Co-Authored-By)
- PR descriptions never include AI-generation footers
- Python tests use venv at .venv-pyvis/ with PYTHONPATH unset to
  avoid ROS pytest plugin leakage
- gh CLI lives at ~/.local/bin/gh (prepend PATH)
- plan.md is tracked; update it (especially §22′ and §23′.2)
  whenever a Phase C external repo PR lands so future Claude
  sessions start oriented. Same convention applies even though
  the work happens out-of-repo.

For Phase C external repos:

- public Apache-2.0 repos created via gh repo create require
  explicit transcript-visible `ok!` consent from the user — the
  auto-mode classifier rejects them otherwise. Paraphrase the
  action in plain text first.
- Sibling directory layout: /media/sasaki/aiueo/ai_coding_ws/
  <repo-name>. Use the same root as this repo.

Cue cadence the user expects:

- "tugi" / "tugiikou" / "susummou" / "nokori yattekou" — go to the
  next thing. With the in-tree list exhausted this means surface
  candidates, not start work blindly.
- "yattekou" / "yatte" — green-light the most recently proposed
  unit, ship full PR cycle.
- "osusumede" — your recommendation, decide and ship.
- "comit!" / "push!" / "merge!" — explicit gates the user wants
  before those actions.
- "ok!" — explicit consent for an auto-mode-blocked action that
  was paraphrased just above (typically public gh repo create).
- "kore nani?" / "nanisiteruno?" — orientation request, give a
  tight status, do not start new work.
- "ittan plan md wo … kousin shitekudasai" / "ittan plan.md wo …
  kousin site owari!" — update plan.md without committing; wait
  for explicit "comit!". The "owari!" variant means "and we're
  done for the session" — do not chain into new feature work.
- "katadukeyou!" — session-close cleanup. Sweep for untracked
  files, stale branches, memory entries that need today's facts.
  Do not start new feature work.
```

