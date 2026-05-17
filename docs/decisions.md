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

---

> Decisions below were taken during the post-MVP arc (PR #32–#67).
> They are the design judgments a future contributor needs to know
> "why we did things this way" and which are *not* derivable from
> reading the code alone.

## D-12: Protocol-based plug points, but with a hard bar for adding new ones

Where D-4 set the early rule ("no plugin architecture initially"), the
post-MVP arc relaxed it to ship six concrete plug points:
`LLMBackend`, encoder `Backend`, `AlignedRgbSource`,
`SchedulerProtocol`, `Transport`, and the `ConflictPolicy` callable
type. Each one isolated a real friction point — `LLMBackend` lets
`AnthropicBackend` and any out-of-repo cloud backend share one
contract; `AlignedRgbSource` lets a Mast3R rerender adapter live
in a separate package without changing the in-repo VLM code.

The bar for adding the *next* Protocol is intentionally high to
prevent abstraction creep:

1. At least two non-toy implementations, OR isolation of a heavy
   optional dependency that pulls in torch / C++ extensions / etc.
2. An external-repo implementer is currently asking for it —
   "might want later" is not enough.
3. The contract fits on one page and is **conformance-testable**
   with failure-mode coverage (see D-13's reference to
   `tests/test_conformance_builtins.py`).
4. Inputs and outputs are small and do not leak core graph or
   scheduler internals.
5. Fallback on absence is defined.
6. Core deterministic behavior works without the Protocol present.

The current six all pass this bar. A seventh Protocol is on
moratorium until v1.0 ships — what's needed *instead* of more
Protocols is stable trace schemas, which is what D-13 locks down.

## D-13: v1.0 public wire schemas are locked under `docs/schema_v1.md`

Six public wire formats are committed to a stable v1 contract,
each with a JSON Schema file under [`schemas/`](../schemas/) and
a corresponding `to_dict()` method on the dataclass. `to_dict()`
shapes and the schema files are kept in lockstep by
`tests/test_schema_v1_lock.py` — drift fails CI.

| Surface | Why it's locked |
|---|---|
| `SemanticWaypointArray` | Nav2 / Autoware bridge contract |
| `PlanWithSchedulerResult` | Adapters and dashboards dispatch on `reason_code` (closed enum) |
| `FleetPlanResult` | CLI, eval, adapter all read it |
| `ConflictExplanation` | CBS-lite contribution, external readers consume it |
| `ResolveTrace` (= `LLMResolveResult.to_dict()`) | Language-grounding eval + UI overlays |
| `preferences` metadata convention | Reproducibility of semantic cost weights |

The freeze policy:

- Adding / removing / renaming a field requires a v2 schema bump
- Changing a type or shifting a `reason_code` enum value requires v2
- Tightening *or* loosening a constraint requires v2 (loosening
  breaks producers that exhaustively switch)

Internal search algorithms (BnB pruning detail, cost-function
composition, storage backends), eval-report shapes, and conformance
suite internals are **explicitly not part of the lock**. The
contract surface is public dataclasses + Protocol contracts; the
implementations behind them stay free to evolve.

## D-14: LLM safety property — deterministic floor first, LLM cannot invent

Every LLM-augmented entry point keeps a deterministic floor under
the rewrite layer:

- `llm_describe_path` runs `path_to_steps` first and asks the LLM
  to rewrite *that* numbered list. Unparseable replies, wrong step
  counts, or out-of-range step indices all fall back to the
  deterministic text. A rewritten step that drops the underlying
  node label is caught by `evaluate_describer_safety`'s
  `references_preserved` invariant.
- `llm_resolve_goal` runs `resolve_goal` first and asks the LLM to
  pick from the *deterministic top-k pool*. Out-of-pool picks are
  silently dropped — the safety invariant "the LLM cannot invent a
  node id" holds by construction. Out-of-band `Clarify:` replies
  surface as a `ClarificationQuestion` rather than a bogus pick.

This rule has two consequences worth recording:

1. The grounded metrics (`precision@1`, `recall@k`,
   `false_positive_resolve_rate`) are bounded by the deterministic
   floor on the *correctness* axis — the LLM only changes outcomes
   on the *clarification* and *re-ranking* axes.
2. Raw query vectors are never sent to the LLM in
   `LLMResolveResult.embedding_scores` — only the *scalar* cosine
   scores. The prompt carries structured retrieval context, not
   opaque numerics.

The shipped conformance suite + the grounding eval (D-13 + PR #60)
make this measurable; the resolver doc spells it out under the
"deterministic floor + LLM safety layer" headline.

## D-15: MAPF non-competition stance

The project's coordination layer ships seven fleet strategies
(`greedy` / `priority` / `deadline` / `joint` / `bnb` × 3 objectives
/ `exhaustive` MIS / `insert` repair), an HTTP scheduler RPC shim,
and an `eval-synthetic` measurement suite. None of it is intended
to compete head-to-head with **specialized MAPF solvers**
(CBS / EECBS / MAPF-LNS2) on standard MAPF gridworld benchmarks
(MovingAI, mapf.info, Flatland).

The reasoning: that turf is dominated by solvers that have spent
years optimizing pure-MAPF performance. Trying to beat them on
their own metric would distract from where this project actually
contributes — *semantic / time / language constraints* layered on
top of multi-agent admission. The `eval-synthetic` suite measures
performance under those constraints; MAPF benchmarks are kept as
*reference materials* for reproducibility, not as the primary
yardstick.

If the project ever does want a head-to-head, the entry point is
the `SchedulerProtocol` (D-12) — wrap a CBS-style solver behind it
and feed it through the existing eval harness. That's a paper
extension, not v1.0 work.

## D-16: Heavy adapters live out-of-repo

Torch, C++ ROS plugins, TypeScript Foxglove panels, and large
model weights stay *out of the core repo* by policy. The core
sells itself on "readable Python, zero hard deps, contract-tested
plug points" — adding torch would invalidate every part of that
sentence.

The three ecosystem packages already on the Phase C roadmap:

| Package | Lives where | Why out-of-repo |
|---|---|---|
| `semantic-toponav-nav2-bt` | C++ ROS2 plugin repo | Native compile + Nav2 BT XML wiring; core stays Python-only |
| `semantic-toponav-foxglove` | TypeScript / npm | Frontend + bundler stack; no Python user wants to install npm to plan a route |
| `semantic-toponav-mast3r` | Python + torch | Mast3R weights are ~hundreds of MB; the `AlignedRgbSource` Protocol (D-12) is the contract the package implements |

Each package depends on this repo's locked schemas (D-13) +
Protocols (D-12), not on internal APIs. The split keeps adoption
incremental: a robotics user can pip-install `semantic-toponav`
without ever touching the ecosystem packages.

## D-17: Paper-freeze direction, Protocol moratorium until v1.0

After the post-MVP arc reached feature-complete state across the
original roadmap (PR #35–#59 shipping every "still open" item from
the early Future-directions list), the project switched mode from
**expand** to **collapse**: no new features, finish the eval
substrate, lock the schemas, write the paper.

The phase structure:

1. **Phase A — last research-completeness PR.** `eval-grounding`
   (PR #60) wired language resolution + describer rewrite into the
   eval surface. With Phase A done, the *Language-Specified Goals*
   axis of the paper has measurable headline numbers.
2. **Phase B — paper freeze + v1.0 release prep.** Schema lock
   (PR #61), paper outline (PR #62), CHANGELOG (PR #63),
   cross-reference audit (PR #64), and three visualization /
   sample-report polish PRs (#65 / #66 / #67). All Phase B coding
   items are shipped.
3. **Phase C — ecosystem packages, post-v1.0.** See D-16.

While Phase B is in flight (and until v1.0 is tagged), the
**Protocol moratorium** in D-12 is in force: do not add a seventh
Protocol, even if a future axis would benefit from one. Adding
more abstraction during a freeze defeats the freeze.

Decisions still gating v1.0 are *user-side* (paper venue, single
vs companion paper, real-backend grounding numbers, human-eval
scope, tag timing). They're tracked in
[`plan.md`](../plan.md) §24′, not here, because they shift faster
than this file should.
