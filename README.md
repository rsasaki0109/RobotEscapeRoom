# robot-escape-room

[![test](https://github.com/rsasaki0109/robot-escape-room/actions/workflows/test.yml/badge.svg)](https://github.com/rsasaki0109/robot-escape-room/actions/workflows/test.yml)
[![python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

<p align="center">
  <img src="docs/images/robot_escape_room.gif" width="900" alt="Three-panel hero: topology map, robot RGB camera in furnished rooms, and 3D sim — puzzle replan captions each turn as T-0 escapes via the sublevel (Gazebo + Nav2 stack)">
</p>

<p align="center">
  <sub><strong>Every cost function, one self-solving escape game — map + camera + 3D sim.</strong>
  Three panels: stacked-floor <strong>topology map</strong> (2D),
  <strong>robot camera · rgb</strong> (first-person furnished interior),
  and isometric <strong>3D sim · furnished rooms</strong> (imported OBJ meshes).
  Colour legend: cyan = traveled, pink = planned, red = locked.
  Every GIF frame is one real A* planner step — puzzle captions show items,
  riddles, and the Floor-3 decoy twist. Live stack:
  Gazebo + AMCL + Nav2 + <code>escape_room_runner</code> dynamic replan.
  Interactive Foxglove replay:
  <code>docs/foxglove/robot_escape_room_demo.mcap</code>.
  Robot <strong>T-0</strong> recomposes
  <code>block_edges</code> · <code>block_edge_types</code> ·
  <code>avoid_restricted</code> · <code>prefer_elevator</code> ·
  <code>resolve_goal</code> each turn — no scripted route. The lit
  <code>EMERGENCY EXIT</code> on Floor 3 is a decoy; the real way out is
  the sublevel. Play it with
  <code>python examples/robot_escape_room.py</code>.
  Regenerate the hero:
  <code>PYTHONPATH=. python3 examples/generate_escape_room_meshes.py</code> then
  <code>scripts/foxglove_hero/build_escape_room_gif.sh</code>
  (Foxglove MCAP first:
  <code>PYTHONPATH=. python3 examples/export_escape_room_foxglove_mcap.py</code>).
  Other variants:
  <code>python examples/record_escape_room_sim.py</code> → dashboard GIF;
  <code>python examples/record_escape_room.py</code> → three-panel analytics GIF;
  <code>./scripts/record_escape_room_gz_sim.sh</code> → Gazebo overview MP4
  (<code>docs/images/robot_escape_room_gz.mp4</code>).
  <a href="#escape-room--every-cost-function-in-one-self-solving-game">Gallery write-up</a>.</sub>
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
honors it. Hand the graph to the ROS 2 **Nav2 Route Server** with
`semantic-toponav export-nav2` (`topology_to_nav2_geojson`) — this is the
planning tier that *feeds* Nav2, not a rival to it.

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

**See each axis run.** Four worked demos in one style — *input → a scored
decision → the result*, every bar and route from real API output:

- 🎮 [**Escape room**](#escape-room--every-cost-function-in-one-self-solving-game)
  ([top](#semantic-toponav)) — puzzles as planner primitives, emergent
  six-turn escape;
- 🗣️ [**Language grounding → route**](#language-grounding--route) — a
  sentence → `resolve_goal` scores → the A* route up the elevator;
- 📷 [**Visual localization → navigation**](#visual-localization--navigation)
  — a camera frame → CLIP cosine → route progress to the goal;
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

### Escape room — every cost function in one self-solving game

The [**page hero**](#robot-escape-room) is the 3D Foxglove replay GIF above
(<code>export_escape_room_foxglove_mcap.py</code> +
<code>build_escape_room_gif.sh</code>). A Foxglove dashboard variant lives at
<code>docs/images/robot_escape_room_dashboard.gif</code>; a three-panel
analytics variant at <code>docs/images/robot_escape_room_panels.gif</code>;
a Gazebo overview MP4 at
<code>docs/images/robot_escape_room_gz.mp4</code>
(<code>./scripts/record_escape_room_gz_sim.sh</code>).
The gallery
above shows
each feature in isolation; the escape room ties them together. A robot,
**T-0**, wakes in a locked-down facility and has to reason its way out.
Each puzzle is a thin narrative skin over a real planner primitive:

| Puzzle | Primitive |
|---|---|
| Keycard lock | `block_edges` until the matching item is held |
| Dark corridor | `block_edge_types("unpowered")` until the power core is collected |
| Laser shortcut | `avoid_restricted` — shown via reckless-vs-safe briefing at startup |
| Stairs vs lift | `prefer_elevator` — cheaper stairs exist, T-0 rides the lift |
| Riddle terminal | `resolve_goal` grounds the clue and reveals hidden items |

There is **no scripted route** — each turn the runner recomposes the
*current* cost stack, asks A\* what is reachable now, walks to the nearest
objective, and re-plans. The twist is structural: a lit
`EMERGENCY EXIT` on Floor 3 is welded shut (`master_seal` — no key exists);
a control-room riddle grounds `"maintenance exit"` to the sublevel and
hands over the hatch code, flipping the route from all-the-way-up to
all-the-way-down.

**Gazebo / gz-sim:** furnished facility mesh + interior collision boxes — open
in Harmonic with:

```bash
PYTHONPATH=. python3 examples/generate_escape_room_meshes.py
PYTHONPATH=. python3 examples/generate_escape_room_gazebo_world.py
export GZ_SIM_RESOURCE_PATH="$(pwd)/examples/meshes/escape_room/gazebo/models:$GZ_SIM_RESOURCE_PATH"
gz sim examples/meshes/escape_room/gazebo/escape_room.world
```

See [`examples/meshes/escape_room/gazebo/README.md`](examples/meshes/escape_room/gazebo/README.md).

**Nav2:** export the topology with
`python examples/export_escape_room_nav2_route.py` →
`examples/data/nav2/escape_room_graph.geojson`.

**Full sim stack:** `./scripts/run_escape_room_gz_nav2.sh` launches Gazebo +
ros_gz_bridge + Nav2 + semantic waypoint following — see
[`ros2/README.md`](ros2/README.md).

**Record Gazebo MP4:** `./scripts/record_escape_room_gz_sim.sh` replays the
shipped timeline, drives T-0, and captures the overview camera →
`docs/images/robot_escape_room_gz.mp4`. When gz-sim camera output is blank
(headless / no GPU), the script falls back to a CPU overview renderer that
matches the Gazebo camera pose.

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

The **perception twin** of the language hero: where that one grounds a
*sentence* to a place, this grounds a *camera frame*. `localize_by_image`
embeds the frame with a real CLIP encoder and ranks per-node gallery
vectors by cosine similarity; stacking it with the planner closes an
LM-Nav-style loop — `plan_visual_route`, A* to a goal, monotonic progress
via `VisualRouteFollower`.

<p align="center">
  <img src="docs/images/25_visual_hero.gif" width="900" alt="three-panel loop: the robot's live camera frame on the left, the CLIP cosine similarity of that frame against every gallery place in the middle (matched reference photo inset), and the topology on the right with the planned route filling in green place-by-place as each grounded frame advances the robot to the goal">
</p>

<p align="center">
  <sub>Camera frame → CLIP cosine bars → route progress
  (<code>1/5 → 5/5</code>). Every bar and green leg is real
  <code>CLIPBackend</code> output on Gazebo <em>Depot</em> frames — not a
  mock-up. Regenerate with <code>python examples/record_visual_hero.py</code>.
  On the five-place benchmark every drive frame grounds at
  <strong>precision@1 = 1.00</strong>
  (<a href="docs/visual_grounding_report_sample.md">report</a>).
  Locomotion stays out of repo — ViNT / NoMaD or Nav2 owns <em>how to
  move</em>, this owns <em>where on the plan the robot is</em>
  (<a href="docs/related_work.md">related_work.md</a>). Also see the
  per-frame primitive:
  <code>python examples/visual_localization_demo.py</code> /
  <code>examples/visual_navigation_demo.py</code>.</sub>
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
