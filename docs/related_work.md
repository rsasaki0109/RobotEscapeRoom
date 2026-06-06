# Related work — where `semantic-toponav` sits, by axis

How `semantic-toponav` sits next to existing OSS and the literature,
organized by its three axes — **Plan** (semantic/topological routing),
**Coordinate** (multi-robot fleet admission), and **Resolve**
(language/visual grounding). The through-line: this repo stays a
*readable, dependency-light, pure-Python planning + grounding middle
layer* and treats perception models and local locomotion as **pluggable,
out-of-repo** concerns (decision D-16). Most systems below are therefore
*complementary* — several are natural things to plug **into** this layer,
or executors to hand its `SemanticWaypoint` stream **to**.

Where a competitor genuinely overlaps (notably **Nav2's Route Server**,
which since 2024–25 does semantic graph routing with elevator/stairs
nodes, and **Open-RMF** for fleets), this document says so plainly and
names the *remaining* white space rather than overclaiming. It expands
the related-work buckets of [`paper_outline.md`](paper_outline.md) §2
with concrete reference points; the visual-axis sections (SPTM / RoboHop
/ VLMaps / VPR toolboxes) sit under **Resolve / visual** below.

## The architectural twin: LM-Nav

**LM-Nav** (Shah et al., CoRL 2022) composes pre-trained models —
GPT for instruction parsing, CLIP for grounding observations to landmark
phrases, ViNG for graph construction + locomotion — to follow language
instructions over a topological graph, with no fine-tuning. Its layer
decomposition maps almost one-to-one onto this repo:

| LM-Nav stage | `semantic-toponav` counterpart |
|---|---|
| GPT parses instruction → landmark sequence | `resolve_goal` / `llm_resolve_goal` + `DialogSession` |
| CLIP grounds an observation to a landmark | `localize_by_image` (image → node, cosine over node embeddings) |
| topological graph of connectivity | `TopologyGraph` |
| graph search → subgoal sequence | `plan_astar` + `path_to_semantic_waypoints` |
| ViNG drives between nodes | **out of repo** — Nav2 / ViNT / NoMaD / ViNG |

What this repo adds on top of the LM-Nav recipe: a **deterministic floor
the LLM cannot override** (it may rewrite narration / re-rank, never
invent a node id or step), **multi-robot admission + scheduling** (7
fleet strategies, conflict explanations), and **time / reservation /
preference-aware cost composition** — none of which LM-Nav addresses
(it is single-robot, untimed).

- Paper: <https://arxiv.org/abs/2207.04429> · Project + code:
  <https://sites.google.com/view/lmnav>

## Plan axis — topological & semantic routing OSS

The graph-level routing competitors. The headline, stated honestly:
**Nav2's Route Server (2024–25) closed much of the gap on semantic graph
routing**, so the differentiator is no longer "we route over a semantic
graph with elevators" — it is *declarative, composable, dependency-light*
cost rules authored as data.

- **Nav2 Route Server** (ROS 2, Jazzy / Kilted) — a first-class Nav2 task
  server that plans over a predefined navigation graph (GeoJSON), with
  pluggable **edge scorers** (`DistanceScorer`, `TimeScorer`,
  `PenaltyScorer`, **`SemanticScorer`** over node/edge classes,
  `CostmapScorer`, **`DynamicEdgesScorer`** to close/reopen edges at
  runtime) and **route operations** (collision reroute, speed limits,
  traversal-time learning). Nodes can be **elevator / stairs terminals**
  with call-elevator / climb-stairs behaviors. **So multi-floor and
  per-edge semantic costs are *not* unique to this repo — we should not
  lead with them.** Where it stops: no *declarative* time-of-day /
  calendar / recurring-closure model (`DynamicEdgesScorer` is imperative —
  "close this edge now"), no preference → node-default inheritance, no
  reservation-aware routing, and every cost is a compiled C++ plugin
  inside a running ROS 2 stack.
  <https://docs.nav2.org/configuration/packages/configuring-route-server.html>
- **LCAS `topological_navigation`** (L-CAS / STRANDS lineage) — the
  reference OSS topological-nav stack: waypoint nodes + action edges,
  Bayesian topological localisation, monitored-navigation recovery.
  Heavy and ROS-native (mature on ROS 1 Noetic; ROS 2 Humble migration
  in progress), bound to `move_base` / action servers. Its temporal model
  is **FreMEn** — *learned* periodic traversability predicted from
  observed human-activity periodicity — **not** a declarative calendar
  rule. <https://github.com/LCAS/topological_navigation> · FreMEn:
  <https://chronorobotics.fel.cvut.cz/open-science/fremen>
- **KnowRob + CRAM semantic costmaps** / layered context-sensitive
  costmaps (Lu et al., IROS 2014) — translate place labels into planner
  cost (the canonical example is even time-conditioned: "avoid offices
  during working hours"). But these modulate a metric **costmap layer** in
  research-grade ROS 1 stacks, not a graph-level declarative rule engine.
  <https://wiki.ros.org/knowrob>

**Where this repo is genuinely alone:** declarative **calendar / weekday /
`closed_on_dates` / recurring-window** closures, **preference-aware**
routing with edge → node-default inheritance, and **reservation-aware**
costs — all authored as data, unit-testable, pure-Python, no ROS. That
combination does not appear as a named capability in any OSS surveyed.
The clean handoff is the v1-locked `SemanticWaypoint` stream a Nav2
Waypoint Follower / Navigate-Through-Poses (or Route Server graph)
consumes — this is the planning tier that *feeds* Nav2, not a rival. That
handoff is **shipped**: `topology_to_nav2_geojson` /
[`export-nav2`](../semantic_toponav/conversion/nav2_route.py) serializes
the topology into the exact GeoJSON the Route Server's
`GeoJsonGraphFileLoader` parses (semantic `class` / floor under `metadata`,
bidirectional edges split into two directed features), so the semantic
graph this repo authors / grounds / repairs drops straight into Nav2 to
execute over.

## Coordinate axis — multi-robot fleet OSS

The multi-robot competitors. The dominant OSS player is **Open-RMF**; the
differentiators are *explainable admission* and a *deterministic strategy
menu with a provable upper bound*, packaged dependency-light.

- **Open-RMF** (Open Robotics Middleware Framework, OSRA-governed) — the
  de-facto OSS standard for coordinating heterogeneous multi-fleet
  deployments across shared infrastructure (lifts, doors, BMS). Heavy
  C++ / ROS 2 / DDS multi-package stack (`rmf_traffic`, `rmf_task`,
  `rmf_battery`, …); real use needs a per-robot **fleet adapter**.
  Coordination is **space-time trajectory negotiation** (a prospective
  traffic-schedule DB + a deployer-supplied "judge") plus **task bidding**
  (`BidNotice` → `BidProposal` → award). What it lacks vs this repo: no
  **structured explainable denial** (the model is silent non-bidding — no
  machine-readable `reason_code` / `ConflictExplanation` for *why* a task
  was refused), no **hard-deadline admission contract**, and no **atomic
  topology-node reservation with rollback** (it deconflicts trajectories,
  not graph nodes). Apache-2.0, very active.
  <https://www.open-rmf.org/> ·
  <https://osrf.github.io/ros2multirobotbook/rmf-core.html>
- **FreeFleet / `fleet_adapter` templates** — the OSS bridge that wires a
  standalone robot (Nav2 / ROS 1 Nav) into RMF's bidding / traffic APIs
  over Zenoh. A transport / adapter layer *below* RMF; it issues
  `navigate_to_pose`, it does not schedule. Complementary, not a
  competitor. <https://github.com/open-rmf/free_fleet>
- **RobotFleet** (arXiv 2510.10379, 2025, MIT) — centralized multi-robot
  framework that uses **LLMs** to build task-dependency DAGs and an LLM or
  **MILP** to allocate. Graph-based but no deadlines, no priorities, no
  explainable denial, no reservation / rollback — and LLM-in-the-loop is
  heavier and nondeterministic vs this repo's deterministic strategies.
  <https://arxiv.org/abs/2510.10379>
- **Lifelong MAPF / MAPF-LNS2** — continuous path-level conflict repair at
  warehouse scale (hundreds–thousands of agents). Strong where this repo
  is not (dense throughput), weak on semantics, deadlines-as-contracts,
  and explainability — the solver-track baseline this layer deliberately
  sits *above*. <https://arxiv.org/abs/2102.05085>

**Honest gaps:** RMF wins on real infrastructure (lifts / doors / battery
recharge injection), field deployment, and *kinematic* space-time
deconfliction; lifelong-MAPF wins on agent count. The right frame is
**above / beside RMF**, not against it — semantic-toponav decides
*admission + which goal + node reservation + the deadline contract* and
hands the chosen waypoint to a fleet adapter / Nav2 for execution. The one
capability with essentially **no maintained OSS competitor** is the
machine-readable **denial contract** (`reason_code` +
`ConflictExplanation`).

## Resolve axis — language grounding & grounding safety

LM-Nav (above) is the whole-stack architectural twin; this is the
*grounding-safety* literature specifically. Stated honestly: **"a
deterministic floor the LLM cannot override" is not novel in the
abstract** — the novelty is the specific assembly (NL → a *stable
topology node*, a structural no-invent guarantee, **measured abstention /
false-positive-resolve**, as a sim-free OSS layer).

- **Grounded Decoding** (Huang et al., NeurIPS 2023) — the conceptual
  ancestor: jointly decode LLM token probabilities × a grounded model so
  generated actions are both likely *and* feasible, explicitly to stop the
  LLM hallucinating invalid actions. But it is token-level constrained
  *decoding* of an open vocabulary, with no
  deterministic-resolver-is-authoritative split and no abstention.
  <https://arxiv.org/abs/2303.00855>
- **Mobility-VLA** (Google DeepMind, CoRL 2024) — the closest *navigation*
  instance of "LLM constrained to nodes that exist": a long-context VLM
  picks a goal *frame* from a demo tour, executed via an offline
  topological graph. But the VLM *directly picks* the goal (a wrong pick
  is simply wrong — no deterministic floor runs first, no out-of-pool
  fallback, **no abstention / false-positive metric**), and it is a closed
  real-robot system, not an OSS layer. <https://arxiv.org/abs/2407.07775>
- **MapGPT / NavGPT-2 / VLN-CE** (2024) — restrict the LLM's per-step
  choice to currently-navigable adjacent viewpoints (de-facto "can't pick
  a non-existent neighbor"), but the LLM is still the chooser and
  hallucination persists as a named failure mode; per-step and local, no
  goal-level abstention. <https://arxiv.org/abs/2401.07314> ·
  <https://arxiv.org/abs/2407.12366>
- **Constrained LLM re-ranking** ("retrieve a high-recall shortlist → LLM
  re-ranks → hard-drop any off-list output") — this repo's exact pattern,
  well established in the IR / RAG world (e.g. arXiv 2510.05131), just not
  previously applied to NL → topology-node grounding.
- **Abstention literature** — the metric vocabulary this repo reuses for
  navigation grounding: *Know Your Limits* survey (TACL 2024,
  <https://arxiv.org/abs/2407.18418>), *AbstentionBench*
  (<https://arxiv.org/abs/2506.09038>), embodied-QA abstention ("When
  Robots Should Say 'I Don't Know'", 2025,
  <https://arxiv.org/abs/2512.04597>), and **HEAL** (2025), which finds
  embodied LLM agents "lack control mechanisms to reject infeasible
  tasks" — documenting exactly the gap the deterministic floor fills
  (<https://arxiv.org/abs/2506.15065>). All are text / QA, *not* NL → node
  navigation grounding.

**Where this repo is genuinely alone:** grounding **NL → a stable topology
node id** with a *structural* no-invent guarantee (out-of-pool picks
silently fall back) **and** reporting `false_positive_resolve_rate` /
`abstention_rate` / `clarification_rate` as first-class metrics — no OSS
surveyed benchmarks language → node grounding with abstention at all. The
no-invent property is not just asserted but **adversarially audited**:
[`semantic_toponav/eval/no_invent.py`](../semantic_toponav/eval/no_invent.py)
replays hallucinated ids, prompt-injection, payloads, substring / case
near-misses and an out-of-pool clarification pin through the resolver and
checks a **0.00 leak rate** (`run_no_invent_audit` /
`run_no_invent_conformance`) — the regression Grounded Decoding /
Mobility-VLA describe but never ship as a runnable check.

## Resolve / visual axis — perception, localization & locomotion

The remaining sections cover the *visual* grounding surface
(`localize_by_image`, `plan_visual_route`, `VisualRouteFollower`) and the
locomotion layer it delegates to — the systems that bundle heavy
perception with planning, which this repo keeps as a swappable `Backend`.

### Local-execution layer (what `VisualRouteFollower` delegates to)

These own *how to move* between nodes — the layer this repo deliberately
does not implement, exactly as it delegates metric local planning to
Nav2. Candidate executors a `SemanticWaypoint` stream can drive:

- **GNM / ViNT / NoMaD** — mobile-robot navigation foundation models.
  ViNT uses a **topological graph as its global planner** and a learned
  image-goal policy for local control; NoMaD unifies exploration and
  goal-reaching in a diffusion policy. Code:
  <https://github.com/robodhruv/visualnav-transformer> · ROS 2 port:
  <https://github.com/RobotecAI/visualnav-transformer-ros2> · Project:
  <https://general-navigation-models.github.io/>

### Topological localization + locomotion (the two-layer pattern)

The "retrieval network for localization + locomotion network for motion"
split that this repo mirrors at the graph level:

- **SPTM — Semi-Parametric Topological Memory** (Savinov et al., ICLR
  2018). A non-parametric graph of observations + a learned **retrieval
  network** that localizes the current frame to a node (the direct
  ancestor of `localize_by_image`) + a locomotion network that moves
  between nodes. <https://arxiv.org/abs/1803.00653>
- **Pose-Invariant Topological Memory** (Taniguchi et al., ICCV 2021) —
  hardens SPTM-style localization against viewpoint change.
  <https://openaccess.thecvf.com/content/ICCV2021/papers/Taniguchi_Pose_Invariant_Topological_Memory_for_Visual_Navigation_ICCV_2021_paper.pdf>

### Open-vocabulary topological / semantic maps (graph *producers*)

These build the graph (and its node embeddings) this repo *consumes*.
The encoder `Backend` + `AlignedRgbSource` plug points are the seam:

- **RoboHop** (Garg et al., ICRA 2024) — the closest in spirit. A
  purely topological graph with **image segments as nodes** (SAM) each
  carrying a **CLIP descriptor**, queried open-vocabulary; navigation is
  "hops over segments" + segment-servoing, **no learned policy** — the
  same deterministic-planner-plus-grounding stance. Notably it aggregates
  descriptors over graph neighbors (multi-layer graph convolution) to
  fight perceptual aliasing — a concrete idea for a future neighbor-aware
  re-rank in `localize_by_image`. <https://arxiv.org/abs/2405.05792> ·
  <https://oravus.github.io/RoboHop/>
- **VLMaps** (Huang et al., ICRA 2023) — CLIP features fused into a 3D
  map; natural-language landmark indexing. <https://vlmaps.github.io/> ·
  <https://github.com/vlmaps/vlmaps>
- **HOV-SG** (Werby et al., RSS 2024) — hierarchical open-vocabulary 3D
  scene graph (floor / room / object) with cross-floor Voronoi traversal;
  structurally close to this repo's multi-floor graph + grounding.
  <https://hovsg.github.io/> · <https://github.com/hovsg/HOV-SG>
- **ConceptGraphs** — open-vocabulary 3D scene graph (object nodes,
  relation edges); node matching by cosine. Listed in the
  [awesome-semantic-maps](https://github.com/sonia-raychaudhuri/awesome-semantic-maps)
  survey alongside the above.

### Visual Place Recognition toolboxes (evaluation reference)

`localize_by_image` is, at the metric level, node-level **VPR**. These
are the reference frameworks for descriptors and the recall@K protocol —
useful if the grounding eval suite grows an image→node arm next to the
existing language→node [`eval_grounding.md`](eval_grounding.md):

- **AnyLoc** (Keetha et al., RA-L 2024) — training-free universal VPR
  (DINOv2 + VLAD). A reminder that for *pure place recognition* a
  DINOv2-style `Backend` often beats raw CLIP, while CLIP wins for the
  open-vocabulary *language* query — which is exactly why the encoder is
  a swappable `Backend`. <https://anyloc.github.io/>
- **Deep Visual Geo-localization Benchmark** (Berton et al., CVPR 2022)
  — modular VPR pipeline + recall@K.
  <https://github.com/gmberton/deep-visual-geo-localization-benchmark>
- **VPR-Bench** — viewpoint/appearance-quantified VPR evaluation.
  <https://arxiv.org/abs/2005.08135>
- **OpenSeqSLAM2.0** — VPR under changing conditions; *sequence* matching
  rather than single-frame, an alternative to monotonic single-frame
  progress tracking. <https://arxiv.org/abs/1804.02156>
- Survey index: <https://github.com/slz929/awesome-visual-place-recognition>

## Positioning summary

The honest one-paragraph version: on each axis a strong incumbent already
covers the *obvious* capability, so the differentiation is the same four
words everywhere — **declarative, deterministic, explainable,
dependency-light** — assembled into one pure-Python middle layer.

- **Plan.** *Don't* lead with multi-floor or semantic edge costs —
  **Nav2's Route Server already does both** (elevator/stairs nodes,
  `SemanticScorer`, runtime edge closing). Lead with the **declarative
  calendar / preference-inheritance / reservation-aware cost rules
  authored as data** — verified absent elsewhere (Nav2 is imperative C++
  plugins; STRANDS' FreMEn is *learned* periodicity) — and the no-ROS,
  unit-testable packaging.
- **Coordinate.** **Open-RMF** owns trajectory negotiation, task bidding,
  and real lift/door/battery infrastructure at deployment scale. Lead with
  the **machine-readable denial contract** (`reason_code` +
  `ConflictExplanation`) — essentially no maintained OSS competitor — plus
  the deterministic strategy menu with an **exhaustive-MIS provable upper
  bound**, and frame the layer as sitting *above / beside* RMF rather than
  against it.
- **Resolve.** "LLM can't invent a destination" is prior art in the
  abstract (**Grounded Decoding**, action-space masking, **Mobility-VLA**,
  constrained re-ranking). Lead with the *specific* assembly no one else
  ships: **NL → a stable topology node id**, a structural no-invent
  guarantee, and **abstention / false-positive-resolve measured as
  first-class grounding metrics** in a sim-free OSS layer.
- **Not a perception system, not an executor.** RoboHop / VLMaps / HOV-SG
  / SPTM / ViNT embed a heavy learned model; the perception is a
  `Backend`, the locomotion is Nav2 / ViNT — both out of repo. Cite these
  as the perception/execution ends of the same stack, with
  `semantic-toponav` as the deterministic, explainable, fleet- and
  time-aware middle the others lack.
