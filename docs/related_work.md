# Related work — visual localization & topological navigation

How `semantic-toponav`'s visual-localization / navigation surface
(`localize_by_image`, `plan_visual_route`, `VisualRouteFollower`) sits
next to existing OSS and the literature. The short version: the closest
systems all bundle *perception* (heavy learned models) with the planning
layer; this repo keeps the planning/grounding layer as a readable,
dependency-light library and treats the perception model and the local
locomotion policy as **pluggable, out-of-repo** concerns (decision
D-16). So the systems below are mostly *complementary*, not competitors —
several are natural things to plug **into** this layer.

This document expands the "LLM navigation agents" and "Open-vocabulary
semantic SLAM" buckets of [`paper_outline.md`](paper_outline.md) §2 with
the specific reference points for the visual axis.

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

## Local-execution layer (what `VisualRouteFollower` delegates to)

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

## Topological localization + locomotion (the two-layer pattern)

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

## Open-vocabulary topological / semantic maps (graph *producers*)

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

## Visual Place Recognition toolboxes (evaluation reference)

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

- **Not a perception system.** RoboHop / VLMaps / HOV-SG / SPTM / ViNT
  all embed a heavy learned model. This repo stays a readable planning +
  grounding layer; the model is a `Backend`, the locomotion is Nav2 /
  ViNT — both out of repo.
- **Not single-robot, not untimed.** LM-Nav and the VLN/foundation-model
  line are single-agent and untimed. The multi-robot admission /
  scheduling / temporal-cost machinery is this repo's distinctive axis.
- **Cite as foundation, not competition.** The visual surface lets the
  paper frame these as the perception/execution ends of the same stack,
  with `semantic-toponav` as the deterministic, fleet- and time-aware
  middle the others lack.
