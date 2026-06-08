# Changelog

All notable changes to `semantic-toponav` are recorded in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Working area for changes that land after the v1.0.2 tag.

## [1.0.2] — 2026-06-08

Escape-room front-page polish on top of v1.0.1. No changes to the six
v1-locked public wire schemas or core planner / resolver / coordinator
behavior.

### Added — Robot Escape Room demo + live-simulation hero

- `examples/robot_escape_room.yaml` / `robot_escape_room.py` — a
  self-solving multi-floor escape game where every puzzle is a real
  planner primitive (`block_edges`, `block_edge_types`, `avoid_restricted`,
  `prefer_elevator`, `resolve_goal`); no scripted route.
- `examples/record_escape_room_sim.py` — Foxglove/RViz-style dashboard
  GIF recorder with smooth `/tf` motion, mission HUD, and event log.
- `examples/record_escape_room.py` — three-panel analytics variant
  (`docs/images/robot_escape_room_panels.gif`).

### Changed — README / GitHub positioning

- README hero is the live-simulation escape-room GIF; title leads with
  **Robot Escape Room · semantic-toponav**.
- GitHub About description and topics (`escape-room`, `game-demo`)
  updated to match.
- `examples/build_social_preview.py` rebuilt from the escape-room sim
  hero; `docs/images/social_preview.png` refreshed.
- Hero GIF second-pass ffmpeg palette optimization (~2.9 MB → ~640 KB).

### Added — LLM-augmented abstention path closes the token-leak categories

- `semantic_toponav.query.llm_resolve.ABSTAIN_AWARE_SYSTEM`: a system
  prompt that licenses the resolver to **decline** (emit `Clarify:`) when
  *no* candidate genuinely denotes the requested place — the stock prompt
  only allowed a clarify on mutual *ambiguity*, so it still pressured the
  model to pick an off-topic candidate the keyword matcher had leaked in.
  The structural no-invent guarantee is unchanged; only *when the model
  may abstain* changes.
- `run_abstention_benchmark` gains a `system=` passthrough (defaulting to
  `ABSTAIN_AWARE_SYSTEM` on the LLM path), `eval.abstention.TranscriptBackend`
  + `load_abstention_transcript` replay a recorded reference transcript so
  the LLM path runs reproducibly in CI (no API key, no network — a miss
  raises so transcript/corpus drift fails loudly), and
  `abstention_comparison_markdown` renders the before/after. On the
  committed corpus the LLM-augmented path drives the leak categories to
  zero false-positive resolves — **`false_premise` 0.17 → 0.00**,
  **`out_of_map` 0.33 → 0.00** — abstaining on the exact three queries the
  deterministic floor leaked (`the basement kitchen`, `the server room`,
  `the break room`) while still resolving all six answerable controls. The
  example `examples/eval_abstention_benchmark.py` prints the comparison and
  takes `--llm-backend ollama|anthropic` to reproduce against a real model;
  guarded by `tests/test_abstention.py`.

### Added — abstention benchmark for NL→node grounding, by category

- `semantic_toponav/eval/abstention.py` (`run_abstention_benchmark` /
  `load_abstention_corpus` / `abstention_report_markdown`) measures
  whether a resolver correctly **abstains** on a query it cannot ground,
  broken out by a taxonomy — `answerable` / `unresolvable` /
  `false_premise` / `out_of_map` — mirroring text-QA abstention
  benchmarks (AbstentionBench / *Know Your Limits*) for spatial
  grounding. Per category it reports `abstain_rate` /
  `false_positive_resolve_rate`. On the committed 24-case corpus
  (`tests/fixtures/grounding/abstention_taxonomy.yaml`) the deterministic
  floor scores: answerable 0.00 abstain (resolves all), unresolvable 1.00,
  `false_premise` 0.17 fp, **`out_of_map` 0.33 fp** — surfacing exactly
  where a stray `room` / `kitchen` token leaks ("the server room" → the
  meeting room). Per the landscape survey, no OSS benchmarks language→node
  grounding with an abstention taxonomy. Example
  `examples/eval_abstention_benchmark.py`; guarded by
  `tests/test_abstention.py`.

### Added — Nav2 Route Server GeoJSON reader closes the hand-off loop

- `semantic_toponav.conversion.nav2_route` gains the exporter's inverse —
  `nav2_geojson_to_topology` / `read_nav2_geojson` (+ `Nav2GeoJsonError`) —
  reading a Route Server FeatureCollection back the way Nav2's
  `GeoJsonGraphFileLoader` does: `Point` features → nodes (string id /
  label / semantic `class` restored from `metadata`, integer-id fallback
  for hand-authored graphs), `LineString` features → directed edges. A
  `recombine_bidirectional` toggle either rejoins the two directed halves
  the exporter splits (lossless: **export → read → export is
  byte-identical**) or keeps them directed (exactly what Nav2 materializes).
- New `examples/nav2_roundtrip_demo.py` closes the loop end to end with no
  ROS install: plan an elevator-preferring route, export it, **replan over
  the directed read-back and get the identical sequence** (the semantic
  `class` survives, so the same cost shaping reproduces the route), then
  re-export losslessly to confirm byte-identity. Proves Nav2 plans what we
  planned — the "feed Nav2, don't compete" claim, in code. Guarded by
  `tests/test_nav2_route_roundtrip.py`.

### Added — Nav2 Route Server GeoJSON exporter (feed Nav2, don't compete)

- `semantic_toponav/conversion/nav2_route.py`
  (`topology_to_nav2_geojson` / `write_nav2_geojson`) and a
  `semantic-toponav export-nav2` CLI serialize a `TopologyGraph` into the
  exact GeoJSON the ROS 2 **Nav2 Route Server**'s `GeoJsonGraphFileLoader`
  parses: `Point` nodes with integer ids + semantic `class` / label /
  floor under `metadata`, directed `LineString` edges with `startid` /
  `endid` / `cost`, bidirectional edges split into two directed features,
  `[x, y]` map-frame metres. Makes the "planning tier *above* Nav2, not a
  rival" positioning concrete — the research (`related_work.md`) found
  Nav2's Route Server now does semantic graph routing, so this hands it
  our semantic graph rather than competing. Example
  `examples/export_nav2_route.py` (+ committed sample
  `examples/data/nav2/office_graph.geojson`); guarded by
  `tests/test_nav2_route_export.py` and CLI tests.

### Added — adversarial no-invent audit for the resolver

- `semantic_toponav/eval/no_invent.py` turns the resolver's documented
  "the LLM cannot invent a node id" property into a **runnable adversarial
  regression**: `run_no_invent_audit` / `run_no_invent_conformance` replay
  a catalog of hostile LLM replies (hallucinated ids, real-but-out-of-pool
  ids, prompt-injection, payloads, substring / case near-misses, multi-pick
  confusers) plus an out-of-pool `ClarificationAnswer.chosen_id`, and check
  that **no out-of-pool id ever reaches the output** (leak rate 0.00).
  Backend-free (scripted `EchoBackend`), so it runs in CI. Exposed from
  `semantic_toponav.eval`; example `examples/eval_no_invent_audit.py`;
  guarded by `tests/test_no_invent.py`. This is the language-grounding
  twin of the describer-safety invariants — and the regression Grounded
  Decoding / Mobility-VLA describe but never ship (see `related_work.md`).

### Changed — related-work / positioning expanded to all three axes

- `docs/related_work.md` grew from visual-only to a **per-axis** map
  (Plan · Coordinate · Resolve) of how the library sits next to current
  OSS and research, with an honest pass on the strong incumbents the old
  doc didn't name: **Nav2 Route Server** (which since 2024–25 does
  semantic graph routing with elevator/stairs nodes + `SemanticScorer`,
  so multi-floor is no longer a differentiator), **Open-RMF** (fleet
  trajectory negotiation + bidding), and the grounding-safety prior art
  (**Grounded Decoding**, **Mobility-VLA**, constrained re-ranking,
  abstention literature). The positioning summary now names the *remaining*
  white space per axis (declarative calendar/preference/reservation
  rules · machine-readable denial contract · measured abstention for
  NL→node) rather than overclaiming.
- `docs/paper_outline.md` §2 related-work table adds a Multi-robot-fleet-OSS
  row (Open-RMF) and updates the middleware row for Nav2 Route Server.

### Changed — front-page leads with perception → navigation

- README hero is now `docs/images/25_visual_hero.gif`, a three-panel
  loop (live camera frame · CLIP cosine vs the place gallery · A* route
  filling in to the goal) so the top of the page shows the image
  grounding *and* the navigation, not just the planner output. The
  Foxglove replay GIF keeps its caption and moves into its own
  "Foxglove replay" section.
- `docs/images/social_preview.png` (GitHub link-unfurl image) rebuilt
  from a still of that hero, so shared links carry the same
  perception → navigation story.
- "What it does" now ends with a **See each axis run** block
  cross-linking the three matched heroes (language / visual /
  coordination), and the Visual-localization section shows the
  per-frame localization GIF (`23_visual_localization.gif`) as the
  localize *primitive* — the full localize → plan → follow loop it used
  to duplicate is the page hero.

### Added

- `examples/record_visual_hero.py` — reproducible builder for the
  three-panel hero GIF, driven by the same real `CLIPBackend` and the
  `localize_by_image` / `plan_visual_route` / `VisualRouteFollower`
  API the visual section documents.
- `examples/record_language_hero.py` + `docs/images/26_language_hero.gif`
  — the language twin of the visual hero (new "Language grounding →
  route" gallery item): the goal `"executive office on 3F"` parsed to a
  floor + content tokens, `resolve_goal` scores drawn as a bar chart
  with the winner in amber, and the A* route filling up the stacked
  three-floor topology. Real deterministic resolver + planner output,
  no model or API key.
- `examples/record_coordination_hero.py` + `docs/images/27_coordination_hero.gif`
  — the Coordinate twin (replaces the cycling GIF in the README's
  "Multi-agent coordination" section): the five fleet requests on one
  chain, a per-strategy "agents granted" bar chart, and the per-strategy
  outcome cycling greedy (1/5) → branch-and-bound (4/5). Real
  `plan_fleet_with_strategy` output. With the visual and language heroes
  this completes a matched three-panel hero per axis
  (Resolve · Plan/Coordinate · Visual).
- `examples/build_social_preview.py` reworked to frame that hero still
  as a full-width strip (was a Foxglove frame).

---

## [1.0.1] — 2026-05-28

Front-page and CI hygiene patch on top of v1.0.0. No changes to the
six v1-locked public wire schemas, no behavior changes in the
planner, coordinator, or resolver. Adds the Foxglove Studio replay
demo path as an installable optional extra, refreshes the README
hero and social preview to lead with that demo, and bumps the CI
actions to the Node.js 24 runtime.

### Added — Foxglove Studio replay path

- `examples/export_foxglove_mcap.py` — end-to-end example that runs
  `resolve_goal` + `plan_astar(..., compose_costs(prefer_elevator))`
  + `path_to_semantic_waypoints` on `examples/multi_floor_office.yaml`
  and writes `docs/foxglove/semantic_toponav_demo.mcap` with
  `/semantic_toponav/scene` (`foxglove.SceneUpdate`), `/tf`
  (`foxglove.FrameTransforms`), `/semantic_toponav/pose`
  (`foxglove.PoseInFrame`), `/semantic_toponav/markers`
  (`visualization_msgs/MarkerArray`), and semantic
  route / waypoint / resolve / admission topics.
- `[foxglove]` optional extra in `pyproject.toml` pulling in `mcap`
  and `mcap-protobuf-support` for the export path.
- `docs/foxglove/README.md` — four-step "Open in Foxglove Studio"
  setup guide, full topic / schema table, and regeneration
  instructions.
- `docs/foxglove/semantic_toponav_demo.mcap` — checked-in replay
  source matching the README hero GIF.

### Added — Launch metadata

- `CITATION.cff` for citation tooling.
- `SECURITY.md` with the reporting channel.
- `CODE_OF_CONDUCT.md` (Contributor Covenant v2.1).
- `examples/build_social_preview.py` — reproducible builder for the
  1280×640 GitHub social preview at `docs/images/social_preview.png`.

### Changed — Front page

- README hero now embeds the Foxglove Studio replay GIF
  (`docs/images/22_foxglove_replay.gif`) and spells out the
  Open-in-Foxglove path: links the source MCAP, links the Studio web
  app at `studio.foxglove.dev`, and points at
  `docs/foxglove/README.md` for the four-step panel setup.
- GitHub social preview (`docs/images/social_preview.png`) right
  pane now shows a frame from the Foxglove Studio replay of
  `semantic_toponav_demo.mcap` instead of the matplotlib recorded
  demo. Same overall layout; build via
  `python examples/build_social_preview.py`.

### Changed — CI runtime

- `.github/workflows/test.yml` — `actions/checkout` bumped from
  `v4` to `v6` and `actions/setup-python` from `v5` to `v6`. Both
  v6 majors run on Node.js 24, clearing the per-job Node.js 20
  deprecation annotations. No input changes; `ubuntu-latest` already
  satisfies the runner-version floor.

### Fixed

- `semantic_toponav.__version__` was drifted at `"0.1.0"` since the
  initial MVP — re-synced to the package version. `pyproject.toml`,
  `CITATION.cff`, and `semantic_toponav.__version__` now all read
  `1.0.1`.

---

## [1.0.0] — 2026-05-17

First tagged release of the post-MVP project, consolidating PR
#1–#70. The release captures the original MVP plus the 33-PR
post-MVP arc that brought the project to *feature-complete across
the original roadmap and Phase B paper-freeze polish* (per
`docs/paper_outline.md` and `plan.md` §22′ / §23′.1). v1.0 ships
the locked public wire schemas + the language-grounding eval
substrate; user-side decisions tracked in `plan.md` §24′ (paper
venue, single-vs-companion, Anthropic-backend numbers, human-eval
scope) remain open and do not block the tag.

### v1.0 stability guarantees

Six **public wire formats** are now locked under
[`docs/schema_v1.md`](docs/schema_v1.md). Adding or removing a field,
changing a type, or shifting an enum value all require a v2 schema
bump. Internal search algorithms (BnB pruning detail, cost-function
composition, storage backends) explicitly remain free to evolve.

| Surface | Locked schema |
|---|---|
| `SemanticWaypointArray` | [`schemas/semantic_waypoint_array.schema.json`](schemas/semantic_waypoint_array.schema.json) |
| `PlanWithSchedulerResult` | [`schemas/plan_with_scheduler_result_v1.schema.json`](schemas/plan_with_scheduler_result_v1.schema.json) |
| `FleetPlanResult` | [`schemas/fleet_plan_result_v1.schema.json`](schemas/fleet_plan_result_v1.schema.json) |
| `ConflictExplanation` | [`schemas/conflict_explanation_v1.schema.json`](schemas/conflict_explanation_v1.schema.json) |
| `ResolveTrace` (= `LLMResolveResult.to_dict()`) | [`schemas/resolve_trace_v1.schema.json`](schemas/resolve_trace_v1.schema.json) |
| Preference metadata | documented inline in [`docs/schema_v1.md`](docs/schema_v1.md) |

Six **Protocol plug points** are exposed with public conformance
suites under `semantic_toponav.testing.conformance`. Adapter authors
get a one-call invariant check (no pytest dep required):
`LLMBackend`, encoder `Backend`, `AlignedRgbSource`,
`SchedulerProtocol`, `Transport`, `ConflictPolicy`.

Test suite at the tag: **913 passing, 1 skipped** (3 warnings, all
from third-party `skimage` low-contrast image diagnostics).

### Added — Core graph, planner, waypoint

- Topology graph data model + YAML/JSON serialization
  + `GraphBuilder` fluent API (PR #6)
- Dijkstra + A* planners with composable cost functions
- Semantic waypoint generation with deterministic per-step text
- CLI: `inspect / plan / waypoints` and topology editor (PR #19:
  `add-node / add-edge / rm-node / rm-edge / undo / diff` with
  automatic `.bak` snapshots)
- Deterministic edge-aware path narration (`describe-path` /
  `path_to_steps`, PR #23) with elevator / stairs / restricted
  phrasing and explicit floor-change call-outs
- Deterministic natural-language goal resolution
  (`resolve` / `resolve_goal`, PR #24) with floor-reference parsing
  (`2F` / `floor 2` / `second floor` / `2nd floor`)

### Added — Map and trajectory conversion

- Occupancy grid → topology via skeletonization (PR #18)
- Door detection via clearance + distance transform
  (`mark_doors_by_clearance`, PR #27)
- Region segmentation with doorway pinching
  (`annotate_regions`, PR #28)
- Lossy graph compaction (`compact_graph`, PR #30)
- Occupancy CLI: `from-occupancy / mark-doors / annotate-regions`
  with `.bak` snapshots on in-place mutation (PR #29)
- Trajectory loading from CSV (PR #4) and rosbag2 (PR #12)
- Trajectory post-processing (`prune_low_traversal_edges` /
  `promote_unmapped_transitions`, PR #21)
- Iterative occupancy + trajectory fusion
  (`fuse_trajectories_iteratively`, PR #26)

### Added — Cost composition

- Dynamic edge availability (`block_edges` / `block_edge_types`, PR #3)
- Time-of-day restrictions (`time_aware`, `--at-time`, midnight-wrap, PR #25)
- Static reservation table (`reservation_aware`, `--reservations FILE`, PR #31)
- Calendar-aware extensions (`at_date=`, weekday filters,
  `closed_on_dates`, PR #54)
- Soft per-edge preferences (`preference_aware` with caller-defined
  keys, clamp-to-`[0.1, 10.0]`, PR #55)
- Node-level preference defaults (endpoint-node average inheritance,
  `use_node_defaults=False` opt-out, PR #56)
- Multi-floor cost helpers (`floor_change_penalty` / `prefer_floor` /
  `same_floor_only` / `floor_aware_heuristic`)

### Added — Multi-agent coordination

- `SharedScheduler` in-memory reservation broker with atomic
  `claim_many` rollback + minute-by-minute midnight-wrap-aware
  interval overlap (PR #34)
- Pluggable `ConflictPolicy` (FCFS default, priority-based preemption)
- `plan_with_scheduler` + `plan_fleet` entry points
- `plan_fleet_joint` (n! enumeration + heuristic ordering fallback, PR #35)
- `plan_fleet_with_strategy` dispatcher with
  `greedy | priority | deadline | joint | bnb | exhaustive | insert`
  strategies
- Hard deadline admission (`admission="hard"`, structured
  `reason_code = ok | no_path | deadline_miss | reservation_conflict |
  policy_rejected`, PR #37)
- Branch-and-bound joint scheduler (`plan_fleet_bnb`) with grants /
  cost / budget pruning + CBS-lite `ConflictExplanation` (PR #38)
- BnB fairness objectives (`minimax_cost` / `max_fairness`, PR #42)
- Transport-agnostic scheduler RPC shim (`SchedulerProtocol` /
  `Transport` / `SchedulerService` / `SchedulerClient` /
  `LocalTransport`, PR #41)
- HTTP reference transport (`HttpSchedulerServer` + `HttpTransport`,
  stdlib-only, PR #43)
- Exhaustive MIS baseline (`plan_fleet_exhaustive`) as theoretical
  grant-rate upper bound (PR #45)
- Scheduler state persistence (`save_scheduler` / `load_scheduler`,
  round-trips through the existing reservation YAML/JSON, PR #50)
- Insertion-based fleet repair (`plan_fleet_insert`,
  `O(k·(n+k))` insertion search for incremental admission, PR #59)

### Added — Visit-history memory

- Visit-history memory layer (PR #7)
- Memory CLI subcommands and planner flags (PR #8)
- Embedding-based semantic node retrieval (PR #5)

### Added — LLM / VLM grounding

- VLM/CLIP encoder integration with pluggable
  `semantic_toponav.encoders.Backend` Protocol (PR #32) — Hashing
  (dependency-free) and CLIP backends; `embed_region_patches` and
  the `[vlm]` extra
- LLM-augmented `describe-path` / `resolve` (PR #33) — `LLMBackend`
  Protocol with `EchoBackend` (scripted, no deps) and
  `AnthropicBackend` (lazy SDK, `[llm]` extra)
- Region embeddings injected into the LLM prompt as scalar
  `embedding_score=` fields (raw vectors never serialized, PR #39)
- Clarification dialog primitives (`ClarificationQuestion`,
  `ClarificationAnswer`, `AmbiguousGoalError`, PR #40)
- Multi-turn `DialogSession` (cross-reply `free_text` accumulation, PR #44)
- `AlignedRgbSource` Protocol + `StaticImageRgbSource` reference
  (out-of-repo Mast3R / RGB-D adapter plug point, PR #52)
- Mid-traversal LLM describer rewrite (`llm_describe_path` gains
  `start_index=` / `situation=` kwargs; original step numbers
  preserved, PR #57)

### Added — Evaluation substrate

- Synthetic eval suite (`eval-synthetic` / `eval-report`, PR #36) —
  4 deterministic graph generators (chain / star / doorway /
  multi-floor office), latency p50/p95, Jain fairness,
  JSONL+Markdown reports
- Exhaustive strategy wired into eval runner + grant_rate
  denominator fix (PR #46)
- `--bnb-objective` CLI flag on eval-synthetic (PR #47)
- Language-grounding eval suite (`eval-grounding`, PR #60) — gold
  corpus YAML, `evaluate_resolver` (precision@1 / recall@3 /
  recall@5 / clarification_rate / false_positive_resolve_rate /
  abstention_rate), `evaluate_describer_safety` (4 deterministic
  invariants for rewrite safety). Shipped fixture:
  `tests/fixtures/grounding/multi_floor_office.yaml` (50 cases;
  expanded 22 → 50 in PR #69).

### Added — Protocol conformance + schema lock

- Public Protocol conformance suites under
  `semantic_toponav.testing.conformance` (6 suites, PR #53) — adapter
  authors invoke them as runtime self-checks, no pytest dep required
- Conformance failure-mode depth (PR #58) — empty / large / unicode
  prompts; determinism opt-in; `cos(v,v)≈1`; idempotent release;
  `claim_many` atomic rollback; half-open `[09:00, 09:30) +
  [09:30, 10:00)` adjacency; shape stability
- **v1.0 wire schema lock** (PR #61) — JSON Schemas + `to_dict()`
  methods + `tests/test_schema_v1_lock.py` cross-validates dataclass
  and schema (drift fails CI)

### Added — Visualization

- Interactive HTML viewer via pyvis (`semantic-toponav viewer`, PR #13 / #16)
- Live-reloading viewer (`live-viewer`, file-watch + `/mtime.json`
  polling, PR #22)
- matplotlib `plot` subcommand
- 4-frame animated GIF hero in the README via
  `examples/build_demo_gif.py` (PR #49)

### Added — ROS2 integration

- Custom `semantic_toponav_msgs` package (PR #9)
- `graph_loader_node` publishing `TopologyGraph` over ROS topics (PR #10)
- `nav2_demo_node` bridging `SemanticWaypointArray` →
  `NavigateThroughPoses` (PR #11)
- ROS2 README + integration boundary docs

### Documentation

- Three-floor end-to-end tutorial (PR #15, `docs/tutorial.md`)
- `decisions.md` refresh after early PRs (PR #17)
- README slim from 1125 → 161 lines with visual gallery (PR #48);
  5 new docs split out (`conversion`, `cost_composition`,
  `coordination`, `queries`, `cli`)
- `docs/experiments.md` synced through PR #50 (PR #51)
- README polish 2026-05-15 — three-axis What-it-does
  (Plan / Coordinate / Resolve), multi-floor gallery row, status
  reflecting post-PR-59 surface
- `docs/eval_grounding.md` documenting the grounding metrics + corpus
  format + CLI (PR #60)
- `docs/schema_v1.md` documenting the v1 freeze policy (PR #61)
- `docs/paper_outline.md` — 5-chapter evaluation structure +
  evidence index + open holes for paper-writing (PR #62)
- `docs/grounding_report_sample.md` — committed snapshot of
  `eval-grounding` output against the shipped corpus (deterministic
  + EchoBackend rows + describer safety invariants, PR #67;
  regenerated in PR #69 against the expanded 50-case fixture).
  Provenance header notes the commit each snapshot came from.
  Real-backend Anthropic numbers stay an explicit user-side
  decision per `docs/paper_outline.md` open holes.
- `examples/vlm_region_embedding_demo.py` (PR #65) and
  `examples/coordination_strategies_demo.py` (PR #66) ship hero
  visuals for the Plan / Resolve / Coordinate axes in the README
  gallery — VLM region patches and BnB-beats-greedy 1/5-vs-4/5.
- `decisions.md` integrity pass (PR #68) — D-12 through D-17
  record the post-MVP-arc design judgments that aren't derivable
  from the code: Protocol bar, v1 schema lock policy, LLM safety
  property, MAPF non-competition stance, out-of-repo adapter
  split, paper-freeze direction.
- `examples/ten_minute_tour.py` (PR #70) — single-file Resolve +
  Plan + Coordinate walk-through on the multi_floor_office graph.
  README quickstart points there as the newcomer entry point
  before the deeper `docs/tutorial.md`. No plotting, no LLM
  credentials, runs in under a second.

### Tooling and CI

- GitHub Actions matrix (py3.10 / 3.11 / 3.12) + ruff (PR #1)
- Apache-2.0 license (PR #2)
- CONTRIBUTING guide, issue and PR templates (PR #14)
- `SemanticWaypointArray` JSON schema marked v1-stable (PR #20)
- Per-file E402 ruff ignores for tests that use
  `pytest.importorskip(...)` before module-level imports
  (added incrementally)

### Changed

This is the first tagged release, so the "Changed" section is
sparse by definition — *changes since the previous tag* don't exist
yet. Substantive *behavioral* shifts from the original MVP plan
that future readers should be aware of:

- The cost-function family grew from a fixed `avoid_*` /
  `prefer_*` set to composable helpers via `compose_costs(...)`,
  preserving every original helper
- The fleet API grew from `plan_fleet` (sequential greedy) to a
  family of seven strategies dispatched via
  `plan_fleet_with_strategy`; the original `plan_fleet` remains the
  greedy entry point
- `llm_describe_path` gained `start_index=` / `situation=` kwargs in
  PR #57; calls passing only positional args remain unchanged
- `preference_aware` learned to read node-level defaults in PR #56;
  graphs without node-level `preferences` see no behavioral change

### Removed

Nothing removed for v1.0.

### Deprecated

Nothing deprecated for v1.0.

### Security

No known security advisories at the v1.0 tag. The LLM grounding path
maintains its design rule: the model cannot invent node ids
(out-of-pool picks transparently fall back to the deterministic
ranking), and raw query vectors are never serialized in
`ResolveTrace.embedding_scores` — only scalar similarities.

### Migration notes

No migration notes for v1.0 (the previous tag `v0.1.0` was the
initial public-release tag and predates the post-MVP arc this
release consolidates). Future migration notes (for v2 schema
bumps, removed CLI flags, etc.) will appear in this section per
the freeze policy in [`docs/schema_v1.md`](docs/schema_v1.md).

[Unreleased]: https://github.com/rsasaki0109/robot-escape-room/compare/v1.0.2...HEAD
[1.0.2]: https://github.com/rsasaki0109/robot-escape-room/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/rsasaki0109/robot-escape-room/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/rsasaki0109/robot-escape-room/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/rsasaki0109/robot-escape-room/releases/tag/v0.1.0
