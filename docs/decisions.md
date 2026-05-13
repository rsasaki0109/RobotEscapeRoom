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

Custom ROS messages add packaging overhead and slow iteration. The first
version of the ROS2 wrapper publishes waypoints as JSON on a
`std_msgs/msg/String` topic. Custom messages (`SemanticWaypoint.msg`, etc.)
are a planned follow-up.

## D-10: Stretch features deferred

The MVP intentionally excludes:

- topology editor UI (CLI or web)
- occupancy-to-topology conversion
- trajectory-to-topology generation
- VLM/CLIP labeling
- semantic memory layer / place recognition
- dynamic graph updates
- Nav2 behavior-tree plugin
- custom ROS messages
- multi-floor planning beyond the office example

These are listed in `docs/experiments.md` as future directions.
