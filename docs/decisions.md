# Design Decisions

Early decisions for `semantic-toponav`. The aim is to record *what is
intentionally out of scope* and *why* the project takes the shape it does.

## D-1: Semantic-topological planner is separate from local control

The MVP plans on a semantic topology graph and emits semantic waypoints. It
does **not** issue velocity commands, run model-predictive control, or do
obstacle avoidance. Those are integration targets (Nav2, MPPI, learned local
policies), not core responsibilities.

This split keeps the project useful as a building block for many stacks and
keeps the codebase small.

## D-2: Python-first MVP

The core library is pure Python with one runtime dependency (`pyyaml`). The
ROS2 wrapper lives under `ros2/` as a separate package and is optional. This
keeps iteration fast and keeps the planner usable from notebooks, simulators,
and embodied-AI experiments without dragging in ROS.

## D-3: No dense occupancy planning in core

Occupancy grids, lattice planners, and grid-search A* over metric maps are
explicitly **not** in scope. Adding them would bloat the project and pull it
toward the territory that Nav2 and others already cover well.

The topology graph is the unit of abstraction.

## D-4: No complex plugin architecture initially

Cost functions, heuristics, and waypoint generation are plain Python callables.
There is no plugin registry, no abstract base class, no plugin loader. If a
plugin architecture is needed later it should be added once a real use case
demands it — not pre-emptively.

## D-5: Deterministic waypoint generation (no LLM in the MVP)

`path_to_semantic_waypoints` produces instructions from a small lookup table.
This is deterministic, testable, and free. LLM-generated waypoint text is a
stretch goal once the rest of the system is stable.

## D-6: Edge cost composition uses multipliers, not policies

`compose_costs(f1, f2, ...)` applies each function as a multiplier against the
edge's own cost. This keeps individual cost functions independent — each can
think purely in terms of its own concern (e.g. "elevators are half as costly")
without knowing about other active policies.

A function returning `math.inf` blocks the edge outright.

## D-7: A* heuristic is Euclidean when poses exist, zero otherwise

When both nodes have a `pose`, A* uses Euclidean distance between them as the
heuristic. When either pose is missing it returns `0.0`, so A* degrades to
Dijkstra automatically.

**Known limitation**: the heuristic is only *admissible* (lower-bounds the
true cost) when edge costs scale with geometric distance. When semantic edge
costs are much smaller than the geometric distances between nodes (e.g. all
edges cost `1.0` regardless of length), the heuristic can over-estimate and
A* may return suboptimal paths. In that regime, use `plan_dijkstra`.

This trade-off is acceptable for the MVP because most production deployments
will set edge costs that correlate with distance. A future option is to expose
a heuristic-scale parameter or a non-Euclidean default.

## D-8: Custom exceptions are minimal

Only four custom exceptions exist:

- `GraphValidationError`
- `GraphLoadError`
- `PlanningError`
- `NoPathError`

They are plain `Exception` subclasses. There is no inheritance hierarchy
beyond `NoPathError <: PlanningError`. No exception framework, no error codes.

## D-9: ROS2 wrapper uses `std_msgs/String` for waypoints initially

*Superseded by [D-11](#d-11-custom-ros2-messages-alongside-json).*

Originally the ROS2 wrapper published waypoints as JSON on a
`std_msgs/msg/String` topic to keep packaging overhead low. The custom
`semantic_toponav_msgs` package has since shipped; this decision is kept
for historical context.

## D-10: Stretch features deferred

The MVP intentionally excluded the items below. Several have since shipped
— they are kept in this list with a status marker so the trail from
"explicit non-goal" → "now shipped" is visible:

- topology editor — shipped (CLI subcommands `inspect / add-node /
  add-edge / rm-node / rm-edge`); web editor still deferred
- occupancy-to-topology conversion — shipped
  (`topology_from_occupancy`, plus `load_occupancy_map` for ROS
  `map_server` YAML+PGM bundles)
- trajectory-to-topology generation — shipped
  (`topology_from_trajectories`; CSV via `load_trajectories_from_csv`,
  rosbag2 via `load_trajectories_from_rosbag`)
- semantic memory layer / place recognition — shipped (`memory/`
  module with visit-history cost helpers and embedding-based
  retrieval)
- custom ROS messages — shipped (`semantic_toponav_msgs`)
- multi-floor planning — shipped (`examples/multi_floor_office.yaml`,
  `floor_change_penalty`, `prefer_floor`, `same_floor_only`,
  `floor_aware_heuristic`)
- dynamic graph updates — shipped without mutating the graph itself
  (`block_edges`, `block_edge_types` cost factories plus
  `--block-edge` / `--block-edge-type` CLI flags)
- VLM/CLIP labeling — *still deferred* (retrieval layer ships, encoder
  integration is out of scope)
- Nav2 behavior-tree plugin — *still deferred* (`nav2_demo_node`
  ships as a worked example, not as a BT plugin)

See `docs/experiments.md` for the open items and their status.

## D-11: Custom ROS2 messages alongside JSON

The ROS2 adapter ships a dedicated `semantic_toponav_msgs` package
defining `SemanticWaypoint`, `SemanticWaypointArray`, `TopologyNode`,
`TopologyEdge`, and `TopologyGraph`. Custom messages give downstream
nodes (planners, behavior trees, telemetry) typed access to the
semantic content without re-parsing JSON.

JSON output is *not* removed: `waypoint_publisher_node` exposes an
`output_format` parameter (`semantic` | `json` | `both`) so consumers
that prefer the original `std_msgs/String` wire format keep working.
This dual mode keeps backwards-compatibility while making the typed
path the recommended default.

The Python core ships in two layers:

1. Pure-Python field-dict helpers (`*_to_fields` / `*_from_fields`) in
   `semantic_toponav_ros.msg_conversions` that depend only on the
   dataclass core and are exercised by the regular pytest suite.
2. Thin `*_to_msg` wrappers in the same module that populate generated
   message classes. These require a sourced ROS2 environment and are
   only callable inside the wrapper package.

This split lets contributors validate the wire layout (round-trip
tests on the field-dict layer) without a ROS install.
