# semantic-toponav

[![test](https://github.com/rsasaki0109/semantic-toponav/actions/workflows/test.yml/badge.svg)](https://github.com/rsasaki0109/semantic-toponav/actions/workflows/test.yml)
[![python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

<p align="center">
  <img src="docs/images/25_visual_hero.gif" width="900" alt="three-panel loop: the robot's live camera frame on the left, the CLIP cosine similarity of that frame against every gallery place in the middle (matched reference photo inset), and the topology on the right with the planned route filling in green place-by-place as each grounded frame advances the robot to the goal">
</p>

<p align="center">
  <sub><strong>Perception → navigation, in one glance.</strong> A real
  <code>CLIPBackend</code> embeds each live camera frame (left), scores it
  by cosine similarity against every place in the gallery (middle — the
  matched reference photo inset, the winning bar in amber), and the
  grounded node drives the robot one step further along its A* route
  (right, filling green <code>1/5 → 5/5</code> to the goal). Every bar and
  every green leg is real CLIP output on the Gazebo <em>Depot</em> frames —
  not a mock-up. Regenerate with
  <code>python examples/record_visual_hero.py</code>; the API behind it
  (<code>localize_by_image</code> · <code>plan_visual_route</code> ·
  <code>VisualRouteFollower</code>) is documented under
  <a href="#visual-localization--navigation">Visual localization &amp;
  navigation</a>.</sub>
</p>

**Grounded middle planning layer for robot navigation.** Bridges
dense maps (SLAM / occupancy / HD) and motion executors (Nav2 /
Autoware / MPPI / learned policies) with a graph-level layer that
decides *where to go, why, and who first* — under language goals,
calendar-aware closures, soft preferences, deadlines, and multi-agent
reservations. Pure-Python core, zero hard dependencies, full Protocol
conformance suites.

Use it when a robot stack already has local motion, but still needs:

- language goals grounded into stable topology node ids;
- semantic A* routes over rooms, corridors, elevators, stairs, closures, and preferences;
- multi-robot reservation/admission decisions with explainable denial reasons.

---

## What it does

Three orthogonal axes, all composable:

### Plan
Routes on semantic graphs with composable cost rules. `compose_costs`
stacks `avoid_stairs` / `prefer_elevator` / `block_edges` /
`time_aware` / `preference_aware` / `reservation_aware` /
`floor_change_penalty` and a dozen others into a single A* call. No
re-implementations per scenario — declare what you want, the planner
honors it.

### Coordinate
Multi-agent fleets with atomic reservations and **seven strategies**:
`greedy` / `priority` / `deadline` / `joint` / `bnb` (branch-and-bound,
3 objectives) / `exhaustive` (MIS upper bound) / `insert`
(insertion-based repair). Hard deadline admission with a structured
`reason_code` so denials are explainable. Optional in-process or HTTP
scheduler for fan-out across processes.

### Resolve
Natural-language goals → node ids. The deterministic floor
(bag-of-words + floor parsing) always runs first; an LLM may rewrite
prose or re-rank the top-k pool but **cannot invent node ids** —
out-of-pool picks silently fall back, a property **adversarially
audited** at a 0.00 leak rate (hallucinated ids, prompt-injection,
payloads, near-misses — see
[`eval/no_invent.py`](semantic_toponav/eval/no_invent.py)). Multi-turn
`DialogSession` for ambiguous queries; optional CLIP / VLM cosine
retrieval for embedding-grounded resolves.

**See each axis run.** Three worked heroes in one style — *input → a
scored decision → the result*, every bar and route from real API output:

- 🗣️ [**Language grounding → route**](#language-grounding--route) — a
  sentence → `resolve_goal` scores → the A* route up the elevator;
- 📷 [**Visual localization → navigation**](#visual-localization--navigation)
  ([top](#semantic-toponav)) — a camera frame → CLIP cosine → route
  progress to the goal;
- 🚦 [**Multi-agent coordination**](#multi-agent-coordination) — fleet
  requests → the strategy decision → who gets the chain.

---

## Quick start

```bash
pip install -e .
semantic-toponav plan          examples/indoor_office.yaml entrance meeting_room
semantic-toponav waypoints     examples/indoor_office.yaml entrance office_2f --avoid-stairs --prefer-elevator
semantic-toponav describe-path examples/indoor_office.yaml entrance office_2f --avoid-stairs --prefer-elevator
```

```python
from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.planner import (
    plan_astar, avoid_stairs, prefer_elevator, compose_costs,
)
from semantic_toponav.waypoint import path_to_semantic_waypoints

graph = load_graph("examples/indoor_office.yaml")
path = plan_astar(graph, "entrance", "office_2f",
                  cost_fn=compose_costs(avoid_stairs, prefer_elevator))
for wp in path_to_semantic_waypoints(graph, path):
    print(wp.instruction)
```

New here? Run the
[**ten-minute tour**](examples/ten_minute_tour.py)
(`python examples/ten_minute_tour.py`) for a single-file walkthrough
of the three axes — Resolve, Plan, Coordinate — on the shipped
`multi_floor_office.yaml` graph. No plotting, no LLM credentials,
runs in under a second.

For a deeper read, walk through the
[**three-floor tutorial**](docs/tutorial.md) end-to-end.

---

## Gallery

### Language grounding → route

The **language twin** of the page hero: where that one grounds a
*camera frame* to a place, this grounds a *sentence*. `resolve_goal`
scores every node by a bag-of-words + floor-aware match, the top node
becomes the goal, and `plan_astar` rides the elevator up to it.

<p align="center">
  <img src="docs/images/26_language_hero.gif" width="900" alt="three panels: the natural-language goal with its parsed floor and content tokens on the left, a bar chart of resolve_goal scores per node in the middle with the winner in amber, and the stacked three-floor topology on the right with the A* route filling in green from the entrance up the elevator to the grounded executive office">
</p>

<p align="center">
  <sub>The query <code>"executive office on 3F"</code> parses to
  <code>floor 3</code> + tokens <code>{executive, office}</code>;
  <code>resolve_goal</code> scores <code>Executive Office</code> at 7
  (floor + both labels) clear of the four floor-only 3F candidates at 3,
  and <code>plan_astar(..., prefer_elevator)</code> climbs
  <code>entrance → corridor → elevator 1F→2F→3F → executive office</code>.
  Every bar and green leg is real output from the deterministic resolver
  and planner — no model, no API key. Regenerate with
  <code>python examples/record_language_hero.py</code>.</sub>
</p>

### Cost composition

The same graph re-planned under different cost stacks. The path
changes; nothing about the graph does.

| default A* | + avoid_stairs + prefer_elevator |
|---|---|
| ![default to office](docs/images/03_default_to_office_2f.png) | ![accessibility](docs/images/04_avoid_stairs_to_office_2f.png) |

| default to meeting room | + restricted-edge avoidance |
|---|---|
| ![default meeting](docs/images/01_default_to_meeting_room.png) | ![avoid restricted](docs/images/02_avoid_restricted_to_meeting_room.png) |

### Multi-floor planning

`floor_change_penalty`, `prefer_floor`, `same_floor_only`, and a
`floor_aware_heuristic` make multi-storey layouts a first-class
target — no per-floor sub-graphs needed.

| default (cheapest stairs route) | prefer_elevator |
|---|---|
| ![mf default](docs/images/09_mf_default.png) | ![mf elevator](docs/images/10_mf_elevator.png) |

| prefer_floor=2 (bias toward 2F) | floor_change_penalty (avoid hopping floors) |
|---|---|
| ![mf prefer 2](docs/images/11_mf_prefer_2.png) | ![mf floor penalty](docs/images/12_mf_floor_penalty.png) |

### Conversion pipeline

Topology graphs can be authored by hand or **generated from
existing artifacts**: occupancy grids via skeletonization +
clearance-aware door detection + region segmentation, or trajectory
logs (CSV / rosbag2) via greedy clustering.

| occupancy grid → topology | path on the auto-generated graph |
|---|---|
| ![occupancy](docs/images/05_occupancy_graph.png) | ![occupancy path](docs/images/06_occupancy_graph_with_path.png) |

| trajectory log → topology | CSV trajectory (no pandas) |
|---|---|
| ![trajectory](docs/images/08_trajectory_topology.png) | ![csv](docs/images/13_csv_trajectory.png) |

### VLM region embedding

After `annotate_regions` carves a graph into rooms,
`embed_region_patches` stamps an encoder vector onto every node in
each region (CLIP, Hashing, or any
[`Backend`](docs/conformance.md)-conforming adapter). At query time
the same vector can be used to retrieve nodes by cosine similarity —
the same wire format the LLM resolver consumes as
`embedding_score=` context.

<p align="center">
  <img src="docs/images/15_vlm_region_cycle.gif" width="640" alt="cycling through three query regions; nodes light up by cosine similarity">
</p>

<p align="center">
  <sub>Three query regions, three different highlight patterns. The
  example uses the dependency-free <code>HashingBackend</code>; swap in
  <code>CLIPBackend</code> + an <code>AlignedRgbSource</code> to ground
  text queries on real photographs. Reproduce via
  <code>python examples/vlm_region_embedding_demo.py</code>.</sub>
</p>

### Visual localization & navigation

`localize_by_image` grounds the robot's current camera frame to the
topology node it most likely depicts — the image counterpart of the
language resolver — by embedding the frame with a real CLIP encoder and
ranking the per-node gallery vectors by cosine similarity. Stacking it
with the planner closes an LM-Nav-style loop: ground the start
(`plan_visual_route`), A*-plan to a goal, then track monotonic progress
along the route as frames stream in (`VisualRouteFollower`).

<p align="center">
  <img src="docs/images/23_visual_localization.gif" width="640" alt="robot camera view on the left, top-down topology on the right; CLIP grounds each current frame to the place it most likely depicts, with the cosine score">
</p>

<p align="center">
  <sub>The <strong>localization primitive</strong> on the Gazebo Depot
  world with a <strong>real <code>CLIPBackend</code></strong>: each
  camera frame is grounded to the place it most likely depicts by cosine
  similarity — the image counterpart of <code>resolve_goal</code>. On
  this five-place benchmark every drive frame grounds to its place at
  <strong>precision@1 = 1.00</strong>
  (<a href="docs/visual_grounding_report_sample.md">report</a>). The
  <a href="#semantic-toponav">page hero</a> stacks this with the planner
  for the full localize → plan → follow loop; node-to-node locomotion
  stays out of repo by design — a learned image-goal policy (ViNT /
  NoMaD) or Nav2 owns <em>how to move</em>, this owns <em>where on the
  plan the robot is</em>
  (<a href="docs/related_work.md">related_work.md</a>). Reproduce:
  <code>python examples/visual_localization_demo.py</code> (per-frame) /
  <code>examples/visual_navigation_demo.py</code> (full loop).</sub>
</p>

### Multi-agent coordination

The same scheduler under four ordering strategies. The scenario is
intentionally adversarial — a long-haul agent is submitted first, so
naive greedy locks every other agent out (1/5 granted). Branch-and-
bound and the exhaustive MIS baseline reorder the queue and fit four
short-haul agents into disjoint segments (4/5 granted).

<p align="center">
  <img src="docs/images/27_coordination_hero.gif" width="900" alt="three panels: the five fleet requests on one chain (the long-haul alpha listed first), a bar chart of agents granted per strategy (greedy and priority 1/5, bnb and exhaustive 4/5), and the per-strategy outcome showing greedy granting only the long-haul versus branch-and-bound tiling four short-haul agents into disjoint segments">
</p>

<p align="center">
  <sub>The <strong>Coordinate</strong> twin of the visual and language
  heroes, in the same three-panel style: the <em>requests</em> (five
  agents on one chain, the long-haul listed first), the <em>decision</em>
  (agents granted per strategy), and the <em>outcome</em> for the strategy
  in focus. greedy / priority → 1/5 (submission order locks the long-haul
  in, denying everyone else); bnb / exhaustive → 4/5 (hold the long-haul
  back, four shorts tile disjoint segments). Every number is real output
  from <code>plan_fleet_with_strategy</code> on an identically-seeded
  <code>SharedScheduler</code>. Regenerate via
  <code>python examples/record_coordination_hero.py</code>; the cycling
  per-strategy graph view (<code>17_coordination_cycle.gif</code>) and the
  static 2×2 (<code>16_coordination_strategies.png</code>) come from
  <code>examples/coordination_strategies_demo.py</code>.</sub>
</p>

---

## Features

| Area | What's there | Docs |
|---|---|---|
| **Map / log conversion** | Occupancy grid, door detection, region segmentation, graph compaction, trajectories, CSV / rosbag2 / ROS map_server | [conversion.md](docs/conversion.md) |
| **Cost composition** | `avoid_*` / `prefer_*` / `block_*`, time-of-day windows, calendar-aware closures, soft preferences (node / edge), static reservations, multi-floor heuristics | [cost_composition.md](docs/cost_composition.md) |
| **Multi-agent coordination** | `SharedScheduler` + RPC shim (HTTP / custom), `plan_fleet_with_strategy` (7 strategies), branch-and-bound + fairness objectives, exhaustive-MIS upper bound, insertion-based repair, deadline admission, scheduler persistence, synthetic eval suite | [coordination.md](docs/coordination.md) |
| **Semantic queries + LLM/VLM** | `find_nodes` / `nearest_*` / `resolve_goal`, embedding retrieval, CLIP backend, `llm_resolve_goal` + `DialogSession` (multi-turn), mid-traversal describer rewrite, visit-history memory | [queries.md](docs/queries.md) |
| **CLI reference** | All subcommands and flags | [cli.md](docs/cli.md) |
| **Visualization** | matplotlib `plot`, interactive pyvis HTML viewer, live-reloading viewer | see below |
| **Schema** | YAML v1 graph format + six v1-locked JSON wire schemas (waypoint array, plan / fleet result, conflict explanation, resolve trace, preference metadata) | [schema_v1.md](docs/schema_v1.md) · [waypoint_schema.md](docs/waypoint_schema.md) |
| **Protocol conformance** | Reusable suites under `semantic_toponav.testing.conformance` for `LLMBackend` / encoder `Backend` / `AlignedRgbSource` / `SchedulerProtocol` / `Transport` / `ConflictPolicy` with failure-mode depth | [conformance.md](docs/conformance.md) |
| **Language-grounding eval** | YAML gold-corpus driver for `resolve_goal` / `llm_resolve_goal` (precision@1, top-k recall, clarification / fp-resolve / abstention rates) + describer-rewrite safety invariants for `llm_describe_path` | [eval_grounding.md](docs/eval_grounding.md) · [sample report](docs/grounding_report_sample.md) |
| **ROS2 integration** | `graph_loader` / `waypoint_publisher` / `nav2_demo` nodes | [ros2/README.md](ros2/README.md) |

---

## Visualization

```bash
pip install -e '.[viz]'
semantic-toponav plot examples/indoor_office.yaml \
    --start entrance --goal office_2f \
    --avoid-stairs --prefer-elevator --save route.png

pip install -e '.[viz_web]'
semantic-toponav viewer examples/multi_floor_office.yaml \
    --start entrance --goal exec_office_3f --prefer-elevator \
    --output viewer.html

semantic-toponav live-viewer examples/multi_floor_office.yaml
```

The web viewer is a fully offline self-contained HTML file — nodes
are draggable, hovering surfaces type / cost / property tooltips,
and the highlighted path is overlaid in pink. `live-viewer` adds a
file-watch loop so edits to the YAML reload the browser tab.

### Foxglove replay

<p align="center">
  <img src="docs/images/22_foxglove_replay.gif" width="720" alt="Foxglove replay: stacked floor-1/2/3 topology with the planned route filling in place-by-place as the robot rides the elevator up to the executive office, rendered from semantic-toponav MCAP data">
</p>

<p align="center">
  <sub>Replay of real planner output — semantic topology, robot pose, route, and waypoint stream — rendered headless in open-source Foxglove (<a href="https://github.com/lichtblick-suite/lichtblick">Lichtblick</a>) from the shipped MCAP. <strong>Open it yourself:</strong> drop <a href="docs/foxglove/semantic_toponav_demo.mcap"><code>docs/foxglove/semantic_toponav_demo.mcap</code></a> into <a href="https://studio.foxglove.dev/">Foxglove Studio</a> — see <a href="docs/foxglove/README.md">docs/foxglove/README.md</a> for the panel setup, or <a href="scripts/foxglove_hero/README.md"><code>scripts/foxglove_hero/</code></a> to regenerate this GIF.</sub>
</p>

```bash
pip install -e '.[foxglove]'
python examples/export_foxglove_mcap.py
```

Open `docs/foxglove/semantic_toponav_demo.mcap` in Foxglove Studio.
It contains `/semantic_toponav/scene` as `foxglove.SceneUpdate`, `/tf`
as `foxglove.FrameTransforms`, `/semantic_toponav/pose` as
`foxglove.PoseInFrame`, `/semantic_toponav/markers` as
`visualization_msgs/MarkerArray`, and semantic route / waypoint /
resolve topics from the same planner run shown in the README demo.

---

## Graph schema (v1)

```yaml
version: 1
metadata: {name: indoor_office, frame_id: map}
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

Node `type` examples: `corridor`, `room`, `intersection`, `elevator`,
`stairs`, `entrance`. Edge `type` examples: `traversable`,
`stairs_up`, `stairs_down`, `elevator_connection`, `restricted`,
`one_way`. `pose` is optional — without it A* degrades to Dijkstra.

For a fluent builder API, see `semantic_toponav.graph.GraphBuilder`
(documented in [tutorial.md](docs/tutorial.md)).

---

## What this project is *not*

Deliberately out of scope (use existing systems):

- Low-level control (MPC / MPPI)
- Obstacle avoidance / SLAM / dense occupancy planning
- Behavior trees
- Head-to-head MAPF solver on gridworld (that's CBS / EECBS / MAPF-LNS2
  territory; this layer sits above pure grid MAPF and adds semantic /
  time / language constraints instead)

The split is *where to go* (this repo) vs *how to move locally*
(Nav2 / Autoware / your motion executor):

| Layer | Responsibility | Owned by |
|---|---|---|
| Global semantic-topological planning | *where* / *why* / *who first* | this repository |
| Local motion execution | *how to move locally* | Nav2 / MPPI / policy |

---

## Status

Feature-complete across the original roadmap and the 25-PR post-MVP
arc: synthetic eval suite, branch-and-bound + fairness objectives,
HTTP transport, exhaustive MIS baseline, scheduler persistence, public
Protocol conformance suites with failure-mode depth, calendar-aware
closures, soft preferences (edge + node defaults), mid-traversal LLM
rewrites, insertion-based fleet repair, language-grounding eval suite,
and v1.0 schema lock across six wire formats. See
[docs/decisions.md](docs/decisions.md) for design notes,
[docs/experiments.md](docs/experiments.md) for the full feature index,
and [docs/paper_outline.md](docs/paper_outline.md) for the working
outline of the paper that organizes the post-MVP arc.

Six public wire formats are **v1-locked** under [`schemas/`](schemas/):
`SemanticWaypointArray` (waypoint publisher),
`PlanWithSchedulerResult` + `FleetPlanResult` (fleet admission),
`ConflictExplanation` (CBS-lite diagnostics), `ResolveTrace`
(language grounding), and the `preferences` metadata convention. See
[docs/schema_v1.md](docs/schema_v1.md) for the freeze policy and
[CHANGELOG.md](CHANGELOG.md) for the consolidated v1.0 release
notes spanning PR #1–#62.

---

## Tests

```bash
pytest -q                              # 875 tests, ~20s
ruff check .
```

## License

Apache-2.0.
