# Changelog

All notable changes to `semantic-toponav` are recorded in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Working area for changes that land after the v1.0.0 tag. Currently
empty.

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

[Unreleased]: https://github.com/rsasaki0109/semantic-toponav/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/rsasaki0109/semantic-toponav/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/rsasaki0109/semantic-toponav/releases/tag/v0.1.0
