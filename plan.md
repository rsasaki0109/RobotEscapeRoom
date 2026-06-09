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

## 22′. Current state — post-v1.0 + launch polish (2026-05-28)

Headline numbers and surfaces a future visitor should read first.

- **71 PRs merged before the direct launch-polish commits**, ~16,000
  LOC of Python, **913 tests passing, 1 skipped** at the v1.0 / post-PR
  #67 checkpoint. Main is green after the 2026-05-28 direct commits:
  `ruff` plus pytest on Python 3.10 / 3.11 / 3.12 passed in GitHub
  Actions run `26551836518`.
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
- **README first viewport is now a real Foxglove Studio replay**:
  - Hero GIF — `docs/images/22_foxglove_replay.gif` (recorded from a
    self-hosted Foxglove Studio session opening the generated MCAP)
  - Hero MP4 — `docs/images/22_foxglove_replay.mp4`
  - Replay source — `docs/foxglove/semantic_toponav_demo.mcap`
  - Generator — `examples/export_foxglove_mcap.py`
  - MCAP topics: `/tf` (`foxglove.FrameTransforms`),
    `/semantic_toponav/pose` (`foxglove.PoseInFrame`),
    `/semantic_toponav/scene` (`foxglove.SceneUpdate`),
    `/semantic_toponav/markers` (`visualization_msgs/MarkerArray` for
    old/new Foxglove 3D-panel compatibility),
    `/semantic_toponav/resolve_trace`, `/semantic_toponav/route`,
    `/semantic_toponav/waypoints`, `/semantic_toponav/admission`
- **Gallery still covers the original three axes**:
  - Plan — `docs/images/demo.gif` and the later launch demos
    (`docs/images/21_semantic_toponav_visualization.gif`) show
    multi-floor semantic routing / cost composition
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

### 22′.1 2026-05-28 launch / star-facing polish log

This subsection is intentionally longer than normal because it records
the GitHub-first positioning work that happened after the v1.0 / Phase C
bootstrap plan was last synced. The user's immediate objective was not
new core functionality; it was: make the repository look credible to a
GPT Pro / robotics OSS reviewer quickly enough to earn stars. The
result is a README first viewport that has a real visualization artifact,
not just CLI text or a synthetic illustration.

Direct commits on `main` after the previous plan sync:

- `6c77100 Add TPS semantic navigation hero` — first attempt at a
  semantic/topological navigation hero. Superseded by later recorded
  demos but kept in history.
- `03da210 Replace hero with recorded navigation demo` — replaced the
  first static-ish hero with a recorded navigation demo.
- `987f655 Polish launch metadata` — moved the package metadata to a
  launch-ready posture: `version = "1.0.0"`, stable classifiers and
  project URLs, `CITATION.cff`, `SECURITY.md`, `CODE_OF_CONDUCT.md`,
  social preview asset, and GitHub topic polish
  (`semantic-navigation`, `topological-navigation`, `multi-robot`,
  `fleet-coordination`, `nav2`, `llm-robotics`, etc.). Community
  profile reached 100%.
- `f350009 Add real CLI demo hero` — made the demo claim more honest by
  recording an actual CLI run rather than a purely designed animation.
- `8455f01 Add visualization dashboard demo` — added
  `examples/record_visualization_dashboard.py` plus
  `docs/images/21_semantic_toponav_visualization.gif` / `.mp4`, a
  Foxglove/RViz-style rendered dashboard using real
  `resolve_goal("executive office on 3F")`,
  `plan_astar(..., compose_costs(prefer_elevator))`, and
  `path_to_semantic_waypoints(...)` outputs.
- `89e2e61 Add Foxglove replay export` — added the first real MCAP
  export surface: `examples/export_foxglove_mcap.py`,
  `docs/foxglove/semantic_toponav_demo.mcap`, and
  `docs/foxglove/README.md`.
- `306f234 Add Foxglove replay hero` — upgraded the MCAP so Foxglove's
  3D panel visibly renders the route via
  `/semantic_toponav/markers` (`visualization_msgs/MarkerArray`), then
  recorded a real Foxglove Studio replay to
  `docs/images/22_foxglove_replay.gif` / `.mp4` and promoted that GIF
  to the README hero.

The truthfulness boundary is important and should be preserved in
future docs:

- It is accurate to say the current README hero is a **Foxglove Studio
  replay**. It was recorded from a Foxglove Studio session opening the
  generated MCAP.
- It is accurate to say the MCAP is generated from real
  semantic-toponav planner / resolver / waypoint APIs over the shipped
  `examples/multi_floor_office.yaml` graph.
- It is **not** a physical robot run, not a ROS2 bag captured from a
  live robot, and not a real Foxglove cloud session. Do not imply those
  things unless a future commit actually adds them.
- The earlier `21_semantic_toponav_visualization.gif` is a rendered
  preview dashboard, useful as a fallback visual, but the README hero is
  now `22_foxglove_replay.gif` because that one is recorded from the
  Foxglove UI.

The MCAP generator's current replay story:

- Load graph: `examples/multi_floor_office.yaml`
- Resolve query: `"executive office on 3F"` → `exec_office_3f`
- Plan route:
  `entrance -> corridor_1f -> elevator_1f -> elevator_2f ->
  elevator_3f -> corridor_3f -> exec_office_3f`
- Cost policy: `compose_costs(prefer_elevator)`
- Emit 8 seconds at 12 Hz, 97 frames
- Emit:
  - `/tf` (`map -> base_link`) at 97 messages
  - `/semantic_toponav/pose` at 97 messages
  - `/semantic_toponav/scene` at 98 messages
  - `/semantic_toponav/markers` at 97 messages
  - `/semantic_toponav/waypoints` at 97 messages
  - one-shot `/semantic_toponav/resolve_trace`
  - one-shot `/semantic_toponav/route`
  - one-shot `/semantic_toponav/admission`

Verification commands used before pushing `306f234`:

```bash
python3 examples/export_foxglove_mcap.py
python3 -m ruff check examples/export_foxglove_mcap.py
python3 -m compileall examples/export_foxglove_mcap.py
python3 -m pytest tests/test_multi_floor.py tests/test_semantic_costs.py
python3 - <<'PY'
from collections import Counter
from mcap.reader import make_reader
counts = Counter()
schemas = {}
with open("docs/foxglove/semantic_toponav_demo.mcap", "rb") as stream:
    reader = make_reader(stream)
    for schema, channel, message in reader.iter_messages():
        counts[channel.topic] += 1
        schemas[channel.topic] = schema.name
for topic, count in sorted(counts.items()):
    print(topic, count, schemas[topic])
PY
```

Current asset sizes are small enough for README use:

- `docs/images/22_foxglove_replay.gif` — ~85 KB, 960×540, 44 frames
- `docs/images/22_foxglove_replay.mp4` — ~47 KB, 960×540, 5.5 sec
- `docs/foxglove/semantic_toponav_demo.mcap` — ~2.4 MB
- `docs/images/21_semantic_toponav_visualization.gif` — ~4.7 MB
  fallback dashboard preview, no longer the README hero

Residual issues after the launch-polish pass:

- GitHub Actions still emits a **Node.js 20 deprecation annotation** for
  `actions/checkout@v4` / `actions/setup-python@v5`. The CI jobs pass;
  this is a presentation/maintenance issue, not a test failure.
- PyPI is explicitly skipped for now by user instruction. Do not spend
  time on publish packaging unless the user reverses that instruction.
- `STATUS_FOR_ADVICE.md` is an untracked local file and has repeatedly
  been kept out of commits.
- The README now gives a strong first impression, but there is still no
  hosted docs site, no live ROS2 launch recording, and no physical robot
  deployment artifact. Those should not be invented in copy.

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
   - **v0.2.0 shipped 2026-05-29 by PR #3** (`d5f7e52`, tag + GitHub
     release `v0.2.0`) — NavigateThroughPoses feedback wiring. New
     `on_wait_for_result(feedback)` override (Humble's parameterized
     hook, not the no-arg form) forwards live feedback to four
     blackboard output ports: `current_waypoint_index` (derived as
     `n_poses_dispatched - number_of_poses_remaining`, clamped),
     `number_of_poses_remaining`, `distance_remaining` (m),
     `number_of_recoveries`. All seeded with sentinel `-1` / `NaN` in
     `on_tick()`; mid-flight reads need a `ReactiveSequence` /
     `ReactiveFallback`. gtest `ExposesDocumentedPorts` guards the
     static `providedPorts()` contract. Green CI on the Humble
     container.
   - **v0.3.0 shipped 2026-05-29 by PR #4** (`32710a0`, tag + GitHub
     release `v0.3.0`) — the end-to-end integration test the
     v0.1.0/v0.2.0 smoke check had deferred to "integration tests".
     `test/test_integration_navigate_through_poses.cpp` drives the
     real node against an **in-process `NavigateThroughPoses` action
     server** (a test double) so the full `BtActionNode` lifecycle is
     covered, not just the static contract surface: goal translation
     with the pose-less junction filtered out (server receives the
     pose-bearing count), the BT tree built from XML and ticked
     through the action client/server round-trip, mid-flight feedback
     forwarded to the blackboard (`current_waypoint_index` in
     `[0, n-1]`, `distance_remaining` off `NaN`), and `SUCCESS` with
     `n_poses_dispatched` set. CI green first try (`dispatching 3 of
     4`, test OK in 194 ms, all 7 ctest entries pass). Driving the
     real Nav2 planner/controller stack needs a simulator and stays
     out of scope for unit CI. **This closes the last open Phase C
     follow-up** — nav2-bt is now contract-complete and validated
     against the action interface.
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
   - **v0.3.0 shipped 2026-05-28 by PR #4** (`cb1833d`, tag + GitHub
     release `v0.3.0` with the `.foxe` attached) — third panel
     `Semantic TopoNav Resolve` subscribing to `/resolve_trace`,
     decoding `ResolveTrace` v1 (query / candidates / base_candidates
     / llm_pick / used_fallback / embedding_scores / clarification).
     Renders a rank-movement table (↑/↓ vs base rank, embedding score
     per node, LLM-pick flag), a status badge
     (`clarification_pending` / `llm_pick` / `fallback` / `no_pick`),
     and a clarification band. Pure transform `src/resolve.ts`
     (`buildResolveView` / `normalizeResolveTrace`) jest-tested (12
     cases). Completes the per-wire-format panel coverage story.
   - **v0.4.0 shipped 2026-06-09** — fourth panel
     `Semantic TopoNav Escape Room` subscribing to
     `/semantic_toponav/escape_room/status`, decoding `EscapeRoomStatus`
     (turn caption + puzzle events) for the RobotEscapeRoom Foxglove
     MCAP. Pure transform `src/escape_room.ts` jest-tested. Drop beside
     the 3D scene when replaying `robot_escape_room_demo.mcap`.
   - **Issue #1 closed earlier** — `foxglove-extension build` wired
     into CI; tagged pushes now build + upload the `.foxe`, attached
     to the GitHub release (Node 24 runner via checkout/setup v6).
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

### 23′.4 Star-facing repository polish after the Foxglove hero

The 2026-05-28 work changed the immediate next-step calculus. Before
the Foxglove hero, the repo's biggest adoption problem was that the
first viewport did not immediately communicate "this is robotics
navigation, not only a Python library". That is now substantially fixed:
README opens with a real Foxglove replay and the MCAP can be opened in
Foxglove Studio.

The next moves should therefore be small, presentation-focused, and
boring. Do not restart a major feature axis just because the README is
now stronger.

Recommended order — **all shipped as of 2026-06-06** (status in brackets):

1. **Clear the GitHub Actions Node.js 20 warning.** [DONE — PR #72
   `5bed80b`] Bumped `actions/checkout` and `actions/setup-python` to
   `@v6` (Node.js 24); the deprecation warning is gone and the matrix
   stays green.
2. **Make "Open in Foxglove" even more obvious in README.** [DONE —
   PR #73 `ce4d372`] Added an explicit open-in-Studio CTA near the hero.
3. **Refresh the social preview from the Foxglove hero.** [DONE — PR #73
   `ce4d372`] `docs/images/social_preview.png` rebuilt from a Foxglove
   replay frame so GitHub cards match the first viewport.
4. **Consider a v1.0.1 GitHub Release only after 1–3.** [DONE — PR #74
   `8e12f56`] Cut `v1.0.1` (front-page + CI hygiene patch on top of
   v1.0). PyPI remains skipped per user instruction.

Two further polish PRs landed after this list (see §27′): #82 (plan
docs-sync for the visual axis) and #83 (brighter Foxglove hero +
committed headless regeneration kit). **The §23′.4 list is closed** —
do not re-propose these items.

Things to avoid under the current user direction:

- Do not publish to PyPI. The user explicitly said "pypi ha skip".
- Do not claim the replay is from a physical robot, ROS2 live bag, or
  cloud Foxglove session.
- Do not move the heavy Foxglove self-host / Docker recording machinery
  into the repository unless a reproducible docs-recording workflow is
  explicitly requested. The repo should keep only the generator, MCAP,
  docs, and final assets.
- Do not start Mast3R or a new vision adapter. That remains deferred
  until after the paper.
- Do not add new v1 schemas just to make the MCAP nicer. The MCAP custom
  JSON schemas are replay/demo support; the actual v1 product schemas
  remain the locked schemas under `schemas/`.

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
3. ~~**Real-backend numbers for `eval-grounding`.**~~ Resolved
   2026-06-07 via a **local model** (`OllamaBackend`, no API key) —
   not a user-side decision after all. On the 100-case fixture the
   LLM-augmented resolver cuts fp_resolve 0.19 → 0.06 (abstain
   0.81 → 0.94) and the describer rewrite runs non-fallback
   (`fallback_rate` 0.00, all four invariants 1.00). A cloud
   Anthropic cross-check is optional. See `docs/grounding_report_sample.md`.
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
(see §23′.2), and the 2026-05-28 GitHub-star launch polish has now
landed directly on `main`:

- `89e2e61 Add Foxglove replay export`
- `306f234 Add Foxglove replay hero`

The README first viewport now uses `docs/images/22_foxglove_replay.gif`,
a replay of `docs/foxglove/semantic_toponav_demo.mcap`. As of PR #83 it
is **rendered headless** (no manual screen recording) from a self-hosted
open-source Foxglove fork (Lichtblick) and brightened so the planned
route fills in place-by-place; the reproducible generator lives in
`scripts/foxglove_hero/` (`build_hero_gif.sh` + `render.cjs`). The MCAP
itself is generated by `examples/export_foxglove_mcap.py` from real
semantic-toponav resolver, planner, and waypoint APIs over
`examples/multi_floor_office.yaml`. The caption credits Lichtblick (not
"Foxglove Studio") to stay honest about the render engine.

There is **no new core feature work** remaining in this repo under the
moratorium. Small in-tree launch polish is allowed when it directly
improves trust, first impression, or release hygiene.

The current ship surfaces are split:

1. In-tree launch / README surfaces:
   - README hero: `docs/images/22_foxglove_replay.gif`
   - MP4 fallback: `docs/images/22_foxglove_replay.mp4`
   - replay source: `docs/foxglove/semantic_toponav_demo.mcap`
   - generator: `examples/export_foxglove_mcap.py`
   - docs: `docs/foxglove/README.md`
   - headless regeneration kit: `scripts/foxglove_hero/`
   - GitHub Actions Node.js 20 deprecation warning: RESOLVED (PR #72,
     actions bumped to `@v6` / Node.js 24); CI is green and warning-free
   - user instruction: PyPI is skipped for now

2. Phase C external repos (out-of-repo by design — D-16 / §23′.2):
   - rsasaki0109/semantic-toponav-nav2-bt — v0.3.0 shipped
     (v0.2.0 NavigateThroughPoses feedback ports + v0.3.0 end-to-end
     integration test against an in-process NavigateThroughPoses
     action server, PR #4 `32710a0`). No open follow-ups; the only
     remaining step is exercising the full Nav2 planner/controller
     stack, which needs a simulator (Gazebo) and is gated on
     real-user demand, not a default next move.
   - rsasaki0109/semantic-toponav-foxglove-panel — v0.3.0 shipped
     (3 panels: FleetPlan / Conflicts / Resolve, full per-wire-format
     coverage; issue #1 build-CI closed). No open follow-ups.
   - semantic-toponav-mast3r — deferred until after the paper.

3. §24′ user-side decisions — paper venue / single-vs-companion /
   real-backend grounding numbers / human-eval scope. Not coding,
   not your call to ship.

If the user issues a `tugi` / `tugiikou` cue with this state:

- Do NOT autonomously start a new feature axis in this repo.
- Do NOT start a fourth Phase C package from scratch.
- Surface 2–3 candidate moves with the main trade-off in 2–3
  sentences and wait for the next cue unless the cue is explicitly
  "osusumede" / "yattekou", in which case choose the smallest
  high-impact polishing unit and execute it end-to-end.

Typical candidate menu at this state (the §23′.4 launch-polish items
below are now ALL DONE — listed only for the audit trail; do not
re-propose them):

- In-tree launch hygiene — Node.js 20 warning [DONE #72].
- README polish — "Open this MCAP in Foxglove Studio" CTA [DONE #73].
- Social preview refresh from a Foxglove frame [DONE #73].
- GitHub-only v1.0.1 release [DONE #74].
- Brighter Foxglove hero + headless regeneration kit [DONE #83].
- Phase C external follow-ups are all landed (nav2-bt v0.3.0,
  foxglove-panel v0.3.0). nav2-bt's v0.3.0 integration test against an
  in-process NavigateThroughPoses action server closed the last open
  follow-up; the only remaining Phase C work — exercising the full
  Nav2 planner/controller stack via a simulator — is gated on
  real-user demand, not a default next move; Mast3R (#3) stays
  deferred until after the paper.
- §24′ decision support — surface state, do not pretend to decide.

With that launch-polish list exhausted, a `tugi` cue now means: surface
the §24′ user-side decisions (venue / single-vs-companion / real-backend
grounding numbers / human-eval scope) for the user to judge, or the
§26′ open ends — not new in-tree feature work.

Do not:

- add a 7th Protocol to this repo (moratorium still in force;
  the bar is in D-12)
- publish to PyPI unless the user explicitly reverses "pypi ha skip"
- restart Mast3R (Phase C #3 is deferred until after the paper)
- start new in-tree feature axes (physical loop, online learning,
  multi-fleet) — those are post-v1 / next-paper territory
- overclaim the Foxglove replay as a physical robot run, live ROS2 bag,
  or cloud-hosted Foxglove session
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

## 26′. Visual-localization / navigation axis (2026-06-05 → 06)

A new axis landed after the post-v1.0 state above: **image grounding +
topological navigation**, the perception companion to the text-driven
resolver. It was prompted by a "check for existing OSS / papers" request
and is positioned (in [`docs/related_work.md`](docs/related_work.md))
against LM-Nav (≈1:1 layer map), SPTM, RoboHop / VLMaps / HOV-SG (graph
producers we consume), and ViNT / NoMaD / Nav2 (the local executor we
delegate to per D-16). It does **not** break the readable-core invariant:
the encoder is a `Backend`, locomotion stays out of repo.

Shipped PRs (all merged to `main`, CI green):

| PR | What |
|---|---|
| #75 | `localize_by_image` (image → node, CLIP/Hashing `Backend` + cosine) + the LM-Nav loop `plan_visual_route` / `VisualRouteFollower` (monotonic progress) + `related_work.md` + two demos |
| #76 | `eval-visual-grounding` — image→node `recall@K` arm of the grounding eval (`evaluate_visual_localizer`, gallery+cases corpus, abstention gate) |
| #77 | Neighbor-aware re-rank — `neighbor_weight` blends each candidate's cosine with its scored graph neighbors to damp perceptual aliasing (RoboHop-style) |
| #78 | CLI exposure — `localize` / `visual-route` subcommands |
| #79 | Multi-hop aggregation — `neighbor_hops` widens the corroboration radius (RoboHop multi-layer) |
| #80 | **Fix**: `CLIPBackend` works with `transformers >= 5` (the `get_*_features` return-type shift); deterministic `_feature_tensor` guard + `[vlm]`-gated real-embed smoke |
| #81 | Real-CLIP evidence — `docs/images/24_visual_navigation.gif`, the `visual_depot_drive.yaml` corpus, and `docs/visual_grounding_report_sample.md` (precision@1 = recall@3 = recall@5 = 1.00 on the 5-place Depot benchmark) |

Two-layer eval discipline, mirroring the language arm: the metric
machinery is CI-covered deterministically via `HashingBackend`
(`tests/test_eval_visual_grounding.py`, `test_visual_localization.py`,
`test_visual_navigation.py`, `test_cli_visual.py`), while the real-CLIP
numbers are a manual release-prep artifact (the `[vlm]` extra stays out
of CI by design — same posture as the Anthropic resolver numbers).

New public surface (`semantic_toponav.query`): `localize_by_image`,
`VisualLocalization`, `plan_visual_route`, `VisualRoute`,
`VisualRouteFollower`, `RouteProgress`; CLI `localize` / `visual-route` /
`eval-visual-grounding`. No new Protocol was added — the encoder
`Backend` already covered the plug point, so the §23′.1 moratorium holds.

GitHub About was also trimmed to a single line:
"Semantic topological map navigation in Python — the planning layer
above HD maps and SLAM."

### Open ends for this axis

- Real-CLIP numbers + the navigation GIF were generated on a local
  `[vlm]` checkout (`torch 2.12.0+cpu`, `transformers 5.10.2`); they are
  not reproduced in CI by design.
- ~~`neighbor_weight` / `neighbor_hops` only bite on larger,
  self-similar maps; the 5-place Depot benchmark is too easy to show the
  effect in aggregate (it's unit-tested on an engineered aliasing graph
  instead).~~ **CLOSED (§28′, PR #85).** The re-rank knobs are now
  threaded through `evaluate_visual_localizer` + the CLI, and a
  deterministic engineered aliasing corpus
  (`semantic_toponav.eval.aliasing_visual_corpus`) shows the lift *in
  aggregate* — precision@1 / recall@3 / recall@5 go 0.00 → 1.00,
  reproduced in CI (`tests/test_visual_benchmark.py`).
- Still deferred: the Mast3R `AlignedRgbSource` adapter (Phase C #3,
  post-paper) — the natural heavy-deps source of per-node embeddings.

## 27′. Post-visual launch polish (2026-06-06)

Two presentation-only PRs closed out the §23′.4 launch-polish list after
the visual axis landed. No core feature work — both are docs/asset units
under the §23′.1 moratorium.

| PR | What |
|---|---|
| #82 | `docs(plan): sync visual-localization/navigation axis` — recorded the #75–#81 visual axis into plan.md (this is §26′) |
| #83 | `docs: brighter Foxglove hero GIF + headless regeneration kit` — re-rendered `docs/images/22_foxglove_replay.{gif,mp4}` brighter (cyan route fills place-by-place), and committed `scripts/foxglove_hero/` so the hero is regenerable headless |

### How the hero is now produced (#83)

The README hero is no longer a manual screen recording. The hosted
`app.foxglove.dev` requires sign-in and would upload the MCAP, so the kit
self-hosts the open-source Foxglove fork (Lichtblick) in a container,
serves the committed MCAP same-origin, drives it with Playwright
(`render.cjs`: IndexedDB layout injection → play → CDP screenshot loop),
and assembles frames with ffmpeg (`build_hero_gif.sh`). Render-engine
gotchas captured in `scripts/foxglove_hero/README.md`: the active layout
lives in IndexedDB `lichtblick-layouts` (not localStorage); in
`follow-none` mode panning uses `targetOffset` (not `target`); the TF
connecting line is suppressed via `scene.transforms.lineWidth: 0`. The
replay *content* (topology, route, cyan progress polyline, robot pose)
comes from the MCAP — change the graph/route in
`examples/export_foxglove_mcap.py` and regenerate.

The caption credits Lichtblick (open-source Foxglove) rather than
"Foxglove Studio" to stay honest about the render engine, while keeping
the "drop the MCAP into Foxglove Studio yourself" CTA.

### State after this section

In-tree launch/polish backlog is **empty**. Remaining moves are all
non-coding (§24′ user-side paper decisions) or explicitly deferred
(§23′.3 post-paper axes, Mast3R Phase C #3). A future `tugi` cue should
surface those, not start new in-tree feature work.

## 28′. Neighbor re-rank aggregate evidence (2026-06-07)

Closed the one remaining §26′ open end that *was* a coding task: the
neighbor-aware re-rank (`neighbor_weight` / `neighbor_hops`, PRs #77 /
#79) only had per-case unit-test evidence, because every real-image
corpus on hand (the 5-place Depot drive) was too easy to move the
aggregate numbers. This makes the lift measurable and CI-guarded.

| PR | What |
|---|---|
| #85 | `feat(eval): aggregate evidence for neighbor-aware visual re-ranking` |

What landed:

- **`evaluate_visual_localizer` gained `neighbor_weight` / `neighbor_hops`**,
  forwarded verbatim to `localize_by_image`. Previously the eval could
  not exercise re-ranking at all — that was the root reason no aggregate
  number ever moved. The CLI `eval-visual-grounding` exposes the matching
  `--neighbor-weight` / `--neighbor-hops` flags, so the re-rank can also
  be measured against any real corpus.
- **`semantic_toponav/eval/visual_benchmark.py`** — a torch-free,
  deterministic aliasing benchmark:
  - `VectorTableBackend` — the aggregate-scale sibling of the unit
    tests' `_StubBackend`: returns an engineered unit vector per lookup
    key, so a corpus can be built with analytic embeddings (no images,
    no model).
  - `aliasing_visual_corpus(n_clusters, n_distractors)` — one
    orthogonal 2-D subspace per place; each genuine `true` node is
    corroborated by a graph neighbor, while `n_distractors` higher-cosine
    look-alikes are each propped up only by a private low-scoring
    neighbor. Raw cosine ranks the look-alikes on top (true falls past
    rank 5); neighbor aggregation collapses the isolated spikes and the
    true place wins every case.
  - `neighbor_rerank_ablation` / `neighbor_rerank_ablation_markdown` —
    run the corpus raw vs re-ranked and render the before/after table.
- **Result (deterministic, in CI):** precision@1 / recall@3 / recall@5 =
  **0.00 → 1.00** when re-ranking is turned on. Asserted in
  `tests/test_visual_benchmark.py`; printable via
  `examples/visual_neighbor_ablation_demo.py`; documented in
  `docs/visual_grounding_report_sample.md` and `docs/eval_grounding.md`.
- The visual eval surface (`evaluate_visual_localizer`,
  `load_visual_grounding_corpus`, `VisualGroundingCorpus`, …) is now also
  exported from `semantic_toponav.eval` (it was reachable only via the
  `.grounding` submodule before).

No new Protocol, no new feature axis — this is measurement substrate for
the existing visual axis under the §23′.1 moratorium. The in-tree backlog
is empty again; the §26′ remaining open ends are now non-coding (the
`[vlm]` real-CLIP numbers stay a manual artifact by design) or deferred
(Mast3R Phase C #3).

## 29′. Paper-evidence build-out — the six-chapter figure/corpus arc (2026-06-07)

After §28′ the in-tree backlog was "empty" only in the sense that no new
*feature axis* was open. What remained was the other half of Phase B: the
paper (`docs/paper_outline.md`) named six chapters but several still
pointed at claims without a committed, reproducible figure or corpus
behind them. The 2026-06-07 arc (#86–#95) closed that gap. The framing
throughout: each chapter's headline claim must trace to a deterministic,
CI-guarded artifact a reviewer can regenerate — the same two-layer
discipline (deterministic machinery in CI, optional real-model numbers as
a manual artifact) the eval suites already used.

| PR | Chapter | What landed |
|---|---|---|
| #86 | 6 (visual) | `docs/paper_outline.md` gains the visual-localization chapter + a maturity-grounded decision-support framing tying the §26′ image-grounding axis into the paper structure |
| #87 | 1 (coordination) | **Incremental-admission figure** — insertion repair (`plan_fleet_insert`, PR #59) vs full re-search, quantifying the `O(k·(n+k))`-vs-`O((n+k)!)` win as a committed eval figure |
| #88 | 2 (constraints) | **Semantic-constraints ablation figure** — the same graph re-planned with/without each cost constraint, showing route divergence as a measured table, not just the gallery's visual side-by-side |
| #89 | 1 (coordination) | **Budget-bounded BnB scaling sweep** — branch-and-bound grant-rate / latency as the problem scales, with a token/twork budget bound so the sweep is bounded and reproducible |
| #90 | 5 (conformance) | **External-adapter authoring walkthrough** — `docs/authoring_external_adapters.md`, a contract-page-sized guide to implementing the six Protocols out of repo (the D-16 readable-core split made legible to an integrator) |
| #91 | 3 (grounding) | Language gold corpus **50 → 100 cases**, deepening the precise/ambiguous/unresolvable split that backs the resolver precision@1 / abstention numbers |
| #92 | 3/4 (grounding) | **Local Ollama backend** + real-model grounding numbers with **no API key** — `OllamaBackend`, `tests/test_ollama_backend.py`. Resolves the long-standing "real-backend numbers" open hole (§24′.3) locally rather than via cloud creds |
| #93 | 3/4 (grounding) | **Multi-model robustness** — the abstention/fp-resolve lift is shown to be **capability-gated** (bigger/stronger models abstain more correctly), so the claim is "the contract holds when the model is capable enough", not "any LLM helps" |
| #94 | 3/4 (grounding) | `--llm-timeout` CLI flag + a **35B local-model row** marking the capability ceiling reached on-device |
| #95 | 4 (describer safety) | **3-model describer-safety robustness** — the four deterministic describer invariants are shown to *discriminate* (they catch unsafe rewrites across three models), so Chapter 4's safety property is evidence-backed |

After this arc every paper chapter has at least one committed,
regenerable artifact behind its lead claim, and the real-model grounding
story is reproducible offline (Ollama) instead of gated on cloud
credentials. The §24′.3 "real-backend numbers" hole is effectively closed
(local-model variant); a cloud Anthropic cross-check stays optional.

## 30′. Three-hero README + positioning refresh (2026-06-07)

In parallel with the paper evidence, the README first-viewport story was
upgraded from a single Foxglove hero to **one hero per axis**, so a
visitor sees Plan / Resolve / Coordinate each rendered as a purpose-built
animation rather than inferring all three from one replay.

| PR | What |
|---|---|
| #96 | **Perception → navigation hero** — `docs/images/25_visual_hero.gif`: camera frame → CLIP cosine bars → route progress; the visual-axis twin of the language hero |
| #97 | Rebuilt the GitHub link-unfurl / social image from the perception→navigation hero so the card matches the new first viewport |
| #98 | **Language-grounding hero** — `docs/images/26_language_hero.gif`: sentence → `resolve_goal` score bars → route up the elevator (the gallery's "Language grounding → route" lead) |
| #99 | **Coordination hero** — `docs/images/27_coordination_hero.gif`: fleet requests → strategy decision → who gets the contended chain (greedy vs BnB) |
| #100 | Cross-linked the three heroes in the README and **de-duped** the visual section so the page reads as one three-axis story, not three overlapping demos |
| #101 | `docs/related_work.md` expanded to **all three axes** with honest positioning vs **Nav2 Route Server** and **Open-RMF** (we are the semantic/topological planning layer that *feeds* them, not a competitor) |

The positioning thesis in #101 — "feed the executor, don't compete with
it" — is the same D-16 boundary, now stated explicitly against the two
ecosystems a robotics reviewer will immediately compare against
(Nav2 Route Server for single-robot routing, Open-RMF for fleet
coordination). This sets up §31′.

## 31′. The verifiable-contracts thesis — abstention / no-invent + Nav2 GeoJSON hand-off (2026-06-07 → 06-08)

This arc is the current intellectual center of gravity. Two threads that
had been running separately — *LLM grounding safety* and *Nav2
positioning* — converged into a single thesis, captured in #107's
related-work refresh: **what this project offers above the executor is
verifiable contracts.** The planner does not just produce a route; it
produces a route with checkable properties (it will abstain rather than
invent a destination; it hands Nav2 a schema Nav2 already reads), and
those properties are CI-guarded.

### 31′.1 The abstention / no-invent contract (#102, #104, #105)

| PR | What |
|---|---|
| #102 | **Adversarial no-invent audit** — `semantic_toponav/eval/no_invent.py`: prove the LLM-augmented resolver **cannot invent a destination** that is not a real node. Adversarial prompts (nonexistent rooms, leading phrasing) must resolve to abstention, never to a hallucinated node id |
| #104 | **Abstention benchmark by category** — `semantic_toponav/eval/abstention.py`: NL→node grounding scored on *when it correctly declines*, broken out by failure category (unresolvable / ambiguous / out-of-graph / token-leak) so abstention is measured per-reason, not as one blended rate |
| #105 | **LLM-augmented abstention path** closes the **token-leak categories** — the cases where lexical overlap alone would wrongly resolve (a stray matching word leaks a false positive); the LLM arm is shown to abstain on exactly those, lifting the per-category numbers the deterministic resolver could not |

Together these turn "the resolver is safe" from an assertion into a
measured, category-broken-out contract: the deterministic resolver gives
the floor, the LLM arm closes the token-leak gap, and the no-invent audit
proves the upper bound (no fabricated destinations) holds adversarially.
This is the grounding-safety half of the verifiable-contracts thesis and
the strongest version yet of Chapters 3–4.

### 31′.2 The Nav2 Route Server GeoJSON hand-off (#103, #106)

The execution-side half: make the "feed Nav2, don't compete" boundary a
*working round trip*, not just a stated position.

| PR | What |
|---|---|
| #103 | **Export topology → Nav2 Route Server GeoJSON** — `semantic_toponav/conversion/nav2_route.py` + `examples/export_nav2_route.py` + sample `examples/data/nav2/office_graph.geojson` + `tests/test_nav2_route_export.py`. The semantic topology is emitted in the exact GeoJSON dialect Nav2's Route Server consumes, so the planning layer feeds the executor directly |
| #106 | **Nav2 Route Server GeoJSON reader closes the loop** — the reverse direction + `examples/nav2_roundtrip_demo.py` + `tests/test_nav2_route_roundtrip.py`: a graph can round-trip topology → Nav2 GeoJSON → topology, proving the hand-off is lossless on the shared fields and that we interoperate with (not reimplement) Nav2's routing format |

With both directions committed and round-trip-tested, the D-16 boundary
is now demonstrable: semantic-toponav decides *where and why* and hands
Nav2's Route Server a format it already reads to decide *how to move*.

### 31′.3 Related-work refresh + the thesis statement (#101, #107)

- #101 (logged in §30′) did the three-axis positioning vs Nav2 Route
  Server / Open-RMF.
- #107 refreshed `docs/related_work.md` against **mid-2026 literature**
  and framed the unifying **verifiable-contracts thesis**: the value this
  layer adds over a bare executor is *checkable guarantees* — abstention
  instead of invention, schema-locked wire formats (§21′.5), round-trip
  interop with the executor's own format — all CI-guarded. This is the
  sentence the paper's introduction can now lead with.

### 31′.4 State after this arc

Phase B's paper evidence is materially complete and the project has a
crisp one-line thesis. The remaining gates are still the §24′ user-side
*decisions* (venue, single-vs-companion, human-eval scope), not code. The
moratorium (§23′.1) holds: no 7th Protocol, no new feature axis, no PyPI.

## 32′. Robot Escape Room demo — every cost function in one self-solving game (2026-06-08, ✅ shipped)

A new in-tree **example + gallery** unit built at the user's request
("make the robot complete an escape-game-like quest", then "leave various
puzzles around", then the user's twist: *"I thought it was the 3rd floor
— turns out it was the basement"*). It is presentation/teaching surface
under the §23′.1 moratorium (a worked example, not a feature axis), in
the same spirit as the §23′.4 demos — it reuses only existing planner
primitives.

**Status: shipped** — GitHub repo is `RobotEscapeRoom` (formerly
`semantic-toponav` → `robot-escape-room` → `RobotEscapeRoom`; the Nav2
planner-battle game moved to `Nav2PlannerBattle` to free the slug).
(`ba40fe8`), hero dashboard GIF landed (`2e8f9cd`, v1.0.3). Files:

- `examples/robot_escape_room.yaml` — **multi-floor** escape topology, 18
  nodes across **B1 / 1F / 2F / 3F** (`floor` property +
  `elevator_connection` edges).
- `examples/robot_escape_room.py` — the terminal runner. No scripted
  route: each turn it recomposes the *current* cost stack, asks A\* what
  is reachable now, walks to the nearest objective, acts on arrival, and
  re-plans. Escapes in 6 turns (items 4/4, riddles 3/3).
- `examples/record_escape_room_sim.py` — **README hero** recorder:
  1280×720 Foxglove/RViz-style dashboard (same layout class as
  `record_visualization_dashboard.py`): stacked-floor map + `/tf`,
  topic list, message inspector, route timeline, semantic waypoint
  array. Drives from the runner's real plans — no second game logic.
- `examples/record_escape_room.py` — three-panel analytics variant
  (`docs/images/robot_escape_room_panels.gif`).
- `docs/images/robot_escape_room.gif` — 154 frames @ 18 fps, ~1.6 MB
  (ffmpeg palette pass, 96 colors).
- `README.md` — page hero is the live-simulation GIF; gallery row
  **"Escape room — every cost function in one self-solving game"**
  capstones the individually-demoed cost functions.

### 32′.1 Mechanic → planner-primitive mapping

Each puzzle is a thin narrative skin over a real primitive, so the demo
doubles as a feature tour:

| Puzzle | Primitive |
|---|---|
| Keycard lock (blue / red) | `block_edges(locked_edge_ids)` — door blocked until the matching item is held |
| Riddle terminal | `resolve_goal(graph, clue_answer)` grounds the clue to a node id; a correct grounding reveals where a hidden item is stashed |
| Power gate (Dark Corridor) | `block_edge_types(("unpowered",))` until the power core is collected |
| Laser grid (shortcut) | `avoid_restricted` — a `restricted` shortcut the planner must route around (shown via a reckless-vs-safe `plan_astar` contrast at startup) |
| Stairs vs lift | `prefer_elevator` — parallel `stairs_up` stairwell chain is cheaper, but T-0 rides the lift (shown via a mobility scan at startup) |

### 32′.2 The structural twist (the user's idea)

The twist is *not* coded into the planner — it is pure graph topology +
item state, which is the point:

- A lit **EMERGENCY EXIT** sign on **Floor 3** lures T-0 upward. Its door
  is welded shut: `type: locked`, `properties: {lock: master_seal}` — a
  lock whose key never exists, so `block_edges` keeps it closed forever.
  The runner separates `DECOY_EXIT = "emergency_exit"` from
  `TRUE_EXIT = "maintenance_exit"`.
- The real way out is a **maintenance tunnel in the sublevel (B1)**,
  behind a hatch locked with `hatch_code`.
- A **Floor-3 control-room riddle** grounds `"maintenance exit"` →
  `maintenance_exit` (score 4.0) via `resolve_goal`, revealing the hatch
  code. The route then flips from all-the-way-up to all-the-way-down — an
  emergent consequence of the world state changing under A\*, not a
  scripted branch. The GIF's escape frame shows the pink route plunging
  past the sealed 3F sign down to the B1 sublevel exit.

### 32′.3 Stairs vs lift mechanic — ✅ shipped (2026-06-08)

The fifth mechanic landed on the user's `tugiikou` cue right after the
initial commit:

- `stairwell_1f` / `stairwell_2f` / `stairwell_3f` nodes + `stairs_up`
  edges form a parallel east stairwell; lift hops cost more per floor so
  bare Dijkstra climbs the stairs.
- T-0's runner always composes `prefer_elevator` into the cost stack, so
  the live game rides `elevator_lobby → mid_landing → top_landing` even
  though the stairwell is cheaper.
- `mobility_briefing()` at startup prints both routes side-by-side (same
  pattern as `laser_briefing()`).
- Planning uses `heuristic_fn=lambda *_: 0.0` so semantic edge-cost
  penalties decide the route — Euclidean pose distance would wrongly bias
  toward the lift shaft when stairs and lift tie on node hops.

### 32′.4 Full dashboard hero — ✅ shipped (2026-06-08)

The user rejected the first 960×540 "toy" sim (`f30ba31`). The hero was
rewritten to match `record_visualization_dashboard.py`:

- 1280×720 layout: top bar (`live`, `t=`, turn/wp), map with locked /
  unpowered / restricted edge styling, topics + JSON message inspector,
  route timeline, semantic waypoint array + inventory strip.
- No static "awaiting planner…" intro — motion starts on frame 0.
- `examples/build_social_preview.py` frames a mid-run still from the
  hero GIF for `docs/images/social_preview.png`.

### 32′.5 Reproduction

```bash
# Play it in the terminal (no ROS2, no model, no API key):
PYTHONPATH=. python3 examples/robot_escape_room.py
# Regenerate the README hero (dashboard sim):
PYTHONPATH=. python3 examples/record_escape_room_sim.py
# Three-panel analytics variant:
PYTHONPATH=. python3 examples/record_escape_room.py
# GitHub social preview still:
PYTHONPATH=. python3 examples/build_social_preview.py
```

All recorders are deterministic — every keycard, riddle grounding, and
route leg is real resolver/planner output.

## 33′. Gazebo / Nav2 sim stack + overview MP4 (2026-06-09, ✅ shipped)

Presentation/teaching surface extending §32′ with a physical-sim execution
loop. Still under the §23′.1 moratorium (examples + ROS2 wiring, not a
new planner feature axis).

**Status: shipped** — v1.0.5 (Gazebo + Nav2 + dynamic replan), v1.0.6
(Gazebo overview MP4 + CPU fallback, PR #108), and v1.0.7 (per-room
quests in hero GIF / MCAP, PR #111).

| PR / release | What |
|---|---|
| v1.0.5 | Gazebo world generator, T-0 diff-drive + lidar, Nav2 map export,
  `escape_room_gz_nav2.launch.py`, AMCL, dynamic `escape_room_runner`
  replan, puzzle-caption hero refresh |
| #108 / v1.0.6 | `./scripts/record_escape_room_gz_sim.sh` →
  `docs/images/robot_escape_room_gz.mp4`; CPU overview renderer fallback
  in `examples/escape_room_mesh_render.py` when gz-sim camera is blank |
| #111 / v1.0.7 | `semantic_toponav.escape_room.quests` — one quest per
  graph node; hero GIF quest banner + map highlight; MCAP /
  timeline JSON quest fields; foxglove-panel v0.5.0 quest banner |

### 33′.1 Reproduction

```bash
# Full Gazebo + Nav2 + semantic replan (requires ROS 2 + gz-sim):
./scripts/run_escape_room_gz_nav2.sh

# Record overview MP4 (tries live gz camera, falls back to CPU renderer):
./scripts/record_escape_room_gz_sim.sh

# Offline-only MP4 (no Gazebo):
python3 examples/record_escape_room_gz_mp4.py --offline /tmp/gzframes docs/images/robot_escape_room_gz.mp4
```

### 33′.2 Foxglove escape-room panel (Phase C)

The escape-room MCAP ships `/semantic_toponav/escape_room/status` but
until v0.4.0 of `semantic-toponav-foxglove-panel` users had to read
Raw Messages. The fourth panel (`Semantic TopoNav Escape Room`) renders
turn captions + color-coded puzzle events beside the 3D scene.

**v0.5.0 (2026-06-09)** adds a per-room quest banner (`quest_title`,
`quest_detail`, `quest_mechanic`, ACTIVE/COMPLETE) when replaying MCAPs
exported from v1.0.7+.
