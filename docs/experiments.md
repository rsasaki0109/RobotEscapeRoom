# Experiments and Future Directions

A running log of experiments and the longer-horizon directions for the
project.

## Current

### Indoor office topology

`examples/indoor_office.yaml` (12 nodes, 13 edges across two floors) is the
default test bed. It includes:

- a restricted shortcut (`corridor_main -> meeting_room` of type `restricted`)
- a stairs route (`stairs_1f <-> stairs_2f`, type `stairs_up`)
- an elevator route (`elevator_1f <-> elevator_2f`, type `elevator_connection`)

This is enough to show that semantic cost functions actually change the
chosen route:

| Cost configuration | Route |
|--------------------|-------|
| default | `entrance -> corridor_main -> meeting_room` (uses restricted shortcut) |
| `avoid_restricted` | `entrance -> corridor_main -> lobby_intersection -> meeting_room` |
| default (to 2F) | `entrance -> ... -> stairs_1f -> stairs_2f -> ... -> office_2f` |
| `avoid_stairs + prefer_elevator` | `entrance -> ... -> elevator_1f -> elevator_2f -> ... -> office_2f` |

Reproduce with `python examples/run_indoor_demo.py`.

### Heuristic admissibility

When semantic edge costs (~1.0) are much smaller than geometric distances
between node poses, the default Euclidean A* heuristic over-estimates and
A* may return suboptimal paths. Switching to Dijkstra recovers optimality.
See `docs/decisions.md` (D-7).

## Shipped since the MVP

Quick index of features that started life on this page and have since
landed. Each links to the still-relevant follow-up work.

- Occupancy grid → topology + ROS `map_server` loader, plus a
  post-processing door / threshold detector
  (`mark_doors_by_clearance`) that uses a distance transform of the
  binarized grid to flag narrow-passage nodes (typed `door`) and
  edges whose straight-line minimum clearance falls below an explicit
  or auto-percentile threshold, and a connected-component region
  annotator (`annotate_regions`) that labels free-space components
  with optional doorway pinching (so each pinched room becomes a
  distinct `region_id` stamped onto every node) — pairs naturally
  with the door detector for room-aware graphs. The whole pipeline
  is also reachable from the CLI without writing Python:
  `semantic-toponav from-occupancy MAP.yaml --out g.yaml`,
  `semantic-toponav mark-doors GRAPH MAP.yaml --in-place`, and
  `semantic-toponav annotate-regions GRAPH MAP.yaml --in-place` (with
  `--clearance-threshold` / `--clearance-percentile` / `--min-region-area`
  knobs and automatic `.bak` snapshots on overwrite).
- Trajectory log → topology + CSV loader + rosbag2 loader
- Visit-history memory layer + embedding-based place retrieval
- Multi-floor planning (`floor_change_penalty`, `prefer_floor`,
  `same_floor_only`, `floor_aware_heuristic`)
- Dynamic edge availability (`block_edges`, `block_edge_types`)
- Custom ROS2 messages (`semantic_toponav_msgs`) alongside JSON
- Worked Nav2 example (`nav2_demo_node` bridging `SemanticWaypointArray`
  to `NavigateThroughPoses`)
- CLI graph editor (`inspect / add-node / add-edge / rm-node /
  rm-edge / undo / diff`, with automatic `.bak` snapshots on every
  in-place mutation)
- Interactive HTML viewer (`semantic-toponav viewer`, plus the
  `to_pyvis_network` / `save_interactive_html` API)
- Local live-reloading viewer (`semantic-toponav live-viewer GRAPH`
  serves a single page that polls `/mtime.json` and reloads when the
  graph file on disk changes; pairs with the CLI editor for a
  development loop)
- Deterministic, edge-aware path narration
  (`semantic-toponav describe-path GRAPH FROM TO`, plus the
  `describe_path` / `path_to_steps` API) — turns a plan into numbered
  step-by-step instructions with edge-type-aware phrasing for
  elevators / stairs / restricted edges and explicit floor-change
  call-outs. Intended as the deterministic floor under any later
  LLM-augmented instruction layer.
- Deterministic natural-language goal resolution
  (`semantic-toponav resolve GRAPH "second floor office"`, plus the
  `resolve_goal` / `GoalCandidate` API) — bag-of-words scorer with
  label/type token matches and floor-reference parsing (`2F` /
  `floor 2` / `second floor` / `2nd floor`), with deterministic
  tie-breaking. The text-only sibling of the embedding-based
  `find_nodes_by_embedding`. Intended as the offline floor under any
  later LLM resolver.
- Soft per-edge preferences (`preference_aware(graph,
  preferences={...})`, plus the `--prefer KEY[:WEIGHT]` CLI flag) —
  edges carry an optional `preferences: {key: score, ...}` property
  with caller-defined dimension names; at query time the planner is
  given a weight per dimension (positive to favor, negative to avoid)
  and each edge's cost is scaled by
  `clamp(1.0 - Σ(weight × score), min_multiplier, max_multiplier)`.
  The clamp (default `0.1` floor, `10.0` ceiling) keeps any single
  strong preference from fully zeroing an edge or sending the cost
  to infinity — use `block_edges` / `time_aware` for hard cuts. Nodes
  may also carry the same `preferences` mapping: incident edges that
  don't specify a value for a given key inherit the average over any
  endpoint nodes that carry the key, so a whole "scenic park" region
  can be tagged on one or two nodes rather than every edge — disable
  with `use_node_defaults=False`. Composes with the rest of the
  cost-function family so a single query can honor restricted-edge
  bans, time-of-day closures, reservations, *and* a
  scenic-vs-crowded preference at the same time. The "shortest vs
  scenic vs least-crowded の自然な抽象化" Future Direction is now
  organized as exactly this generic preference blender with
  caller-defined keys, rather than as named per-dimension cost
  helpers.
- Time-of-day edge / node restrictions
  (`time_aware(graph, at_time=...)`, plus the `--at-time HH:MM` CLI
  flag) — edges (and edges incident to closed nodes) carry an
  optional `closed_during: [[start, end], ...]` property of recurring
  HH:MM windows; intervals whose end is `<=` start wrap midnight.
  Composes with the existing `block_edges` / `prefer_elevator` /
  `floor_change_penalty` family. The calendar layer is opt-in: a
  three-element `[start, end, weekdays]` form gates the window to
  specific weekdays (Mon=0..Sun=6 ints or three-letter names), and a
  separate `closed_on_dates: [YYYY-MM-DD, ...]` property fully closes
  the entity for the entire ISO date. Activate it with
  `--at-date YYYY-MM-DD` on the CLI (or pass a `datetime` to
  `time_aware(at_time=...)` to derive the date automatically). A
  weekday-filtered entry seen without `at_date` raises rather than
  silently letting the planner route through what may be a closed
  edge.
- Three-floor end-to-end tutorial at `docs/tutorial.md`
- Hybrid occupancy + trajectory pipeline
  (`annotate_graph_with_trajectories` + post-processing helpers
  `prune_low_traversal_edges` and `promote_unmapped_transitions` —
  snap recorded runs onto a skeleton-derived graph, drop edges that
  no one used, and promote frequent transitions that had no edge into
  new candidate edges), plus the high-level
  `fuse_trajectories_iteratively` wrapper that loops the cycle until
  the topology is stable (with a max-iterations cap so oscillating
  thresholds can't run forever)
- v1-stable JSON Schema for `SemanticWaypointArray`
  (`docs/waypoint_schema.md`,
  `schemas/semantic_waypoint_array.schema.json`)
- Lossy graph compaction (`compact_graph`, plus the
  `semantic-toponav compact GRAPH` CLI subcommand) — merges posed
  nodes within an Euclidean tolerance into a centroid representative
  and collapses parallel duplicate edges between the same endpoints.
  Knobs: `--endpoint-tolerance METERS` for node merging,
  `--edge-cost-tolerance COST` to refuse the collapse when candidates
  differ in length, `--keep-strategy shortest|longest|first` for which
  edge survives. Targets the parallel-skeleton-branch artifact that
  `topology_from_occupancy` leaves behind in wide corridors.
- VLM / CLIP encoder integration — pluggable
  `semantic_toponav.encoders.Backend` protocol with two concrete
  encoders (`HashingBackend`: deterministic, dependency-free, ideal
  for CI / smoke tests; `CLIPBackend`: lazy HuggingFace
  `transformers.CLIPModel` wrapper gated on the `[vlm]` extra) plus a
  `conversion.vlm.embed_region_patches` bridge that consumes
  `annotate_regions`' `RegionInfo.bbox_cells`, crops one patch per
  labeled component, embeds it, and stamps the resulting L2-normalized
  vector onto every node carrying the matching `region_id`. The text-
  and image-vectors live in the same protocol so a NL query embedded
  with the same backend rides the existing
  `find_nodes_by_embedding` / `nearest_node_by_embedding` similarity
  helpers without extra glue. Reachable from the CLI as
  `semantic-toponav embed-regions GRAPH MAP --backend hashing|clip
  [--image RGB.png --pad-cells N --include-region RID --in-place]`.
- Multi-agent shared-resource reservations (`Reservation` /
  `ReservationTable` / `reservation_aware`, plus the
  `--reservations FILE` CLI flag on `plan` / `waypoints` /
  `describe-path`) — accepts a YAML/JSON table of
  `(resource_id, [start, end])` claims (`resource_id` matches a node
  *or* an edge id) and blocks any edge whose own id, or whose
  source / target node id, is held at `--at-time`. Reads the same
  `HH:MM` / midnight-wrap clock semantics as `time_aware` and composes
  with the rest of the cost-function family — one query can honor
  static cleaning windows on the graph *and* live claims from a
  shared scheduler simultaneously.
- LLM-augmented `describe-path` / `resolve` — pluggable
  `semantic_toponav.llm.LLMBackend` protocol with two concrete
  backends (`EchoBackend`: scripted / fall-back-echo, dependency-free
  for tests; `AnthropicBackend`: lazy Anthropic SDK wrapper gated on
  the `[llm]` extra) plus
  `semantic_toponav.waypoint.llm_describe_path` and
  `semantic_toponav.query.llm_resolve_goal`. The deterministic
  `describe_path` and `resolve_goal` floors always run first; the
  LLM only rewrites prose (with one rewritten line per deterministic
  step, never merging or splitting) or re-ranks the top-k candidates
  *from* the deterministic shortlist (it cannot invent a node id —
  out-of-pool picks transparently fall back). `llm_describe_path` also
  accepts `start_index=` and `situation=` for **mid-traversal rewrite**
  — the agent has already visited `path[:start_index]`, so only the
  remaining steps are handed to the LLM, with the original step
  numbers preserved and an optional natural-language situation hint
  (e.g. *"corridor closed for cleaning"*) injected into the prompt.
  Reachable from the CLI as `semantic-toponav describe-path GRAPH ...
  --llm-backend echo|anthropic [--llm-style HINT --llm-script REPLY]`
  and `semantic-toponav resolve GRAPH "text" --llm-backend ...`.
- Online multi-agent coordination — new
  `semantic_toponav.coordination` subpackage with `SharedScheduler`
  (in-memory reservation broker — `claim` / `release` /
  `release_all` / `table()` snapshot for `reservation_aware`),
  pluggable `ConflictPolicy` (`first_come_first_served` default;
  `priority_based` preempts lower-priority holders), and two entry
  points: `plan_with_scheduler` plans one agent against the live
  scheduler state and atomically claims every node + edge on the
  resulting path (rolling back partial claims on conflict); and
  `plan_fleet` runs a sequence of `FleetRequest` entries against the
  same scheduler so later agents naturally route around earlier
  holds. Priority-marked requests are allowed to plan as if no
  reservations existed and preempt at claim time. Minute-by-minute
  midnight-wrap-aware interval overlap shares `time_aware`'s clock
  semantics. Reachable from the CLI as `semantic-toponav fleet-plan
  GRAPH --agent ID:START:GOAL[:PRIORITY] ... --hold-start HH:MM
  --hold-end HH:MM [--policy fcfs|priority --rollback-on-failure]`.
- Real-time scheduler RPC shim — `SchedulerProtocol` (a
  Protocol matching `SharedScheduler`'s public surface),
  `Transport` (single `send(dict) -> dict` method),
  `SchedulerService` (server-side wrapper around one real
  scheduler), `SchedulerClient` (drop-in proxy implementing
  `SchedulerProtocol`), and `LocalTransport` (in-process reference
  transport for tests / demos). Messages are plain JSON-safe dicts
  using `HH:MM:SS` strings for times. Existing planner entry points
  (`plan_with_scheduler`, `plan_fleet` with `greedy` / `priority` /
  `deadline` strategies) accept the client unchanged; `joint` /
  `bnb` strategies still need a local scheduler since they rely on
  `SharedScheduler.clone()`. This PR ships *only* the contract +
  in-process transport — production deployments plug in HTTP /
  WebSocket / NATS / gRPC / their custom bus by implementing the
  one-method `Transport` protocol.
- Clarification dialog primitives for `llm_resolve_goal` —
  `ClarificationQuestion` / `ClarificationAnswer` /
  `AmbiguousGoalError` (frozen, JSON-friendly). The resolver detects
  deterministic ambiguity by top-1 / top-2 score delta against an
  ``ambiguity_threshold`` (default ``0.5``) and reports it via
  `LLMResolveResult.clarification`; the LLM can also emit a
  `Clarify: <question>` line as an alternative ambiguity signal.
  Callers thread the user's reply back via the new
  ``clarification=ClarificationAnswer(chosen_id=...)`` kwarg, which
  narrows the candidate pool to that id (out-of-pool ids dropped, so
  the "no invented node ids" safety property holds). Strict mode
  available through ``raise_on_ambiguous=True`` →
  :class:`AmbiguousGoalError`. CLI parity:
  `semantic-toponav resolve ... --llm-backend ... [--clarify-with
  NODE_ID --clarify-free TEXT]`; JSON output grows a
  `llm.clarification` block on ambiguity. The richer multi-turn
  session-state and mid-traversal-rewrite work is still open — this
  PR ships the minimum vocabulary that makes the rest of it
  expressible.
- Region-embedding context for the LLM goal resolver — PR #32 and
  PR #33 confluence. `llm_resolve_goal` now accepts an optional
  `query_encoder: Backend` and embeds the user query, then computes
  per-candidate cosine similarity against any node embeddings
  stamped by `embed_region_patches`. The resulting scores are
  injected into the LLM prompt as scalar `embedding_score=` fields
  (never raw vectors — that's the deliberate safety property: the
  LLM is given retrieval *results*, not opaque numerics) and
  surfaced on the result as `embedding_scores: dict[str, float]`
  for telemetry. The LLM still picks only from the deterministic
  candidate pool, so the new signal augments the rerank without
  breaking the "no invented node ids" guarantee. Reachable from
  the CLI as `semantic-toponav resolve GRAPH "text" --llm-backend
  ... --vlm-backend hashing|clip [--vlm-dim N --vlm-clip-model
  REPO --vlm-clip-device cpu|cuda]`. Default is "off" so call
  sites unaware of PR #32 stay unchanged.
- Branch-and-bound joint scheduler — new
  `semantic_toponav.coordination.plan_fleet_bnb` does a pruned DFS
  over partial agent orderings, scoring each leaf by
  `(granted_count DESC, total_path_cost ASC)` and pruning subtrees
  that can't beat the running best on either axis (plus a hard
  `max_nodes` / `time_budget_ms` budget). Same optimum as
  `plan_fleet_joint` when both have headroom (property-tested) but
  measurably cheaper on contended scenarios — synthetic-eval smoke
  shows BnB ≈ 2× faster than joint on `n=4` across all four
  canonical scenarios while matching grants and cost. The result
  also carries `ConflictExplanation` entries, a CBS-lite description
  of "agent X was blocked by holds from agents A, B on resources …"
  so operators can diagnose admission failures without re-running
  the search. Strategy literal grows `"bnb"`;
  `plan_fleet_with_strategy` dispatches to it; CLI parity through
  `semantic-toponav fleet-plan ... --strategy bnb` and
  `eval-synthetic --strategy bnb`.
- Hard deadline admission control —
  `FleetRequest.deadline` is now a hard constraint under
  `admission="hard"` (default still `"soft"` for back-compat). A
  request whose projected arrival `hold_start + path_cost ×
  minutes_per_cost_unit` exceeds its deadline is rejected up-front
  with `reason_code="deadline_miss"` and zero claims on the
  scheduler. `PlanWithSchedulerResult.reason_code` is now a typed
  `"ok" | "no_path" | "deadline_miss" | "reservation_conflict" |
  "policy_rejected"` literal so callers can dispatch without parsing
  `failure_reason`. The flag threads through `plan_with_scheduler`,
  `plan_fleet`, `plan_fleet_joint`, and `plan_fleet_with_strategy`
  uniformly. CLI: `semantic-toponav fleet-plan ... --admission
  soft|hard [--minutes-per-cost-unit FLOAT]`. The eval suite reports
  `deadline_miss_count` per trial, and a smoke sweep on
  `multi_floor` with `--admission hard --deadline-tightness 1.0
  --minutes-per-cost-unit 5.0` already shows the `deadline` strategy
  cutting misses (1 → 2) and `joint` keeping the lowest admitted
  total cost.
- Synthetic evaluation suite for coordination strategies —
  `semantic_toponav.eval` subpackage with deterministic, seed-driven
  graph generators (chain / star / doorway / multi-floor), fleet +
  reservation generators, a `Scenario` / `TrialResult` runner that
  rebuilds the scheduler per strategy so trials are independent, and
  a JSONL-roundtrip + pivoted markdown report. Metrics: grant rate,
  total path cost, coordination makespan, mean/max wait,
  Jain's fairness, conflict count, and per-strategy latency
  (p50 / mean / max). Reachable from the CLI as
  `semantic-toponav eval-synthetic [--scenario chain|star|doorway|
  multi_floor|all --n-agents N --strategy greedy|priority|deadline|
  joint --deadline-tightness 0..1 --priority-distribution
  uniform|mixed|high --out FILE.jsonl --summary]` and
  `semantic-toponav eval-report FILE.jsonl [--summary]`. Designed as
  the evaluation substrate for follow-up coordination work
  (hard-deadline admission control, branch-and-bound joint
  scheduler, fairness-aware ordering, etc.).
- Joint fleet optimization beyond sequential greedy —
  `plan_fleet_joint` clones the scheduler (new
  `SharedScheduler.clone`), tries every permutation when
  `n! ≤ max_permutations` (default `120` = `5!`) or a fixed set of
  heuristic orderings (insertion / reverse / priority-DESC /
  deadline-ASC) for larger fleets, scores each trial by
  `(granted_count, total_path_cost)` (more grants wins; ties broken
  by cheaper paths across granted agents), and applies the winning
  ordering to the live scheduler in a single committing call. Plus
  `plan_fleet_with_strategy` as a single dispatcher across
  `greedy | priority | deadline | joint`, and a new optional
  `FleetRequest.deadline` field used as the EDF sort key. Reachable
  from the CLI by extending the existing flag set:
  `semantic-toponav fleet-plan ... --strategy joint` (or
  `priority` / `deadline`); the `--agent` syntax gains an optional
  `:HH:MM` deadline suffix
  (`--agent r1:entrance:kitchen:0:11:00`).
- Fairness-aware BnB objectives — `plan_fleet_bnb` gains an
  `objective` parameter with three modes: `"min_cost"` (default,
  unchanged), `"minimax_cost"` (minimize the maximum per-agent path
  cost — picks egalitarian orderings even when total cost ties), and
  `"max_fairness"` (maximize Jain's fairness index over per-agent
  path costs). Grants upper-bound pruning stays universal; the cost
  lower-bound prune branches per objective (partial sum dominates
  `min_cost`, partial max dominates `minimax_cost`, fairness mode
  skips the prune since Jain's index is non-monotone).
  `BnBPlanResult.per_agent_costs` exposes the winner's per-agent
  cost map; `plan_fleet_with_strategy` threads the choice through as
  `bnb_objective`; CLI parity through `eval-synthetic
  --bnb-objective min_cost|minimax_cost|max_fairness`.
- HTTP reference transport for `SchedulerService` —
  `HttpSchedulerServer` (stdlib `ThreadingHTTPServer` + `urllib`),
  `HttpTransport` (one-method `Transport`, `urllib.request`-POSTs
  JSON), and the full lifecycle (start / shutdown / context manager
  / idempotent re-call). Wire contract: `POST /` with JSON body, 200
  with service body, 400 with `{"error": ..., "kind": "RpcError"}`
  for malformed payloads (matches the in-body error shape
  `SchedulerService` already uses), 404 / 405 for wrong path /
  method. Pairs with `SchedulerClient` for end-to-end multi-process
  fleets. No new dependencies — stdlib only.
- Multi-turn `DialogSession` for LLM goal resolution — stateful
  wrapper around `llm_resolve_goal` that accumulates
  `ClarificationAnswer.free_text` hints across replies, so "the
  second floor one" plus a later "with the big window" narrows
  together instead of resetting each turn. `start(text)` initiates
  the dialog; `reply(answer)` advances it; `is_resolved()` /
  `chosen()` / `question()` expose state; `turns` records the full
  conversation (`DialogTurn` per round with the effective query,
  the answer, and the resolver's result). The `chosen_id` field
  stays one-shot — matches the existing one-call semantics, so the
  "no invented node ids" safety property is preserved through the
  underlying resolver. Pure dataclass + delegation; no new
  dependencies.
- Exhaustive MIS baseline for grants — `plan_fleet_exhaustive`
  answers a more fundamental question than the sequential planners:
  *if every agent planned independently, what is the largest
  grantable subset of those plans?* That's the maximum independent
  set on the path-overlap conflict graph, a strict upper bound on
  grants for fixed paths. Plans each agent on a fresh clone (no
  sequential effect), builds the conflict graph (edges canonicalized
  so `a→b` and `b→a` collide), enumerates subsets in decreasing
  size, stops at the first conflict-free one, applies the chosen
  subset to the live scheduler and pads the result with synthetic
  denial entries for dropped agents so the `grant_rate = granted /
  len(results)` denominator stays consistent across strategies.
  Capped at `n_limit=16` (≈65k subsets, sub-ms). When BnB matches
  exhaustive grant count, no scheduling tweak inside the existing
  framework can do better. Strategy literal grows `"exhaustive"`;
  CLI parity through `eval-synthetic --strategy exhaustive`. Pure
  Python, no external solver dependency.
- Scheduler state persistence — `save_scheduler(scheduler, path)`
  writes the live scheduler's claims to YAML or JSON using the
  existing static reservation format, so a file saved here can be
  fed straight into `load_reservations` for offline planning;
  `load_scheduler(path, *, policy=...)` constructs a fresh
  `SharedScheduler` primed with every reservation from the file in
  insertion order. Conflict policy is operational state (not data),
  so it does *not* round-trip — pass `policy=priority_based` at
  load time to override the default FCFS. Closes the persistence
  gap left by the RPC shim and HTTP transport: long-running
  coordinator services can now checkpoint before restart, and
  operators can prime a fresh scheduler with a known baseline.

See `docs/decisions.md` D-10 for the original "non-goals" list with
shipped / deferred markers.

- Aligned-RGB plug point for `embed_region_patches`
  (`semantic_toponav.encoders.AlignedRgbSource` protocol +
  `StaticImageRgbSource` reference implementation). Lets the
  embedding pipeline pull patches from a real-world RGB image in the
  occupancy-grid coordinate frame instead of cropping the binary
  occupancy itself — so a Mast3R-style adapter, a top-down camera,
  or an orthorectified drone capture can feed CLIPBackend / a custom
  VLM without changing the encoder layer. The protocol surface is
  intentionally minimal (`shape` + `crop(bbox)`) so adapter packages
  (`semantic-toponav-mast3r` etc.) only need to implement those two
  members and stay torch-free in this repo. `embed_region_patches`
  enforces `rgb_source.shape == image.shape[:2]` so misalignment
  fails loudly, and `RegionEmbeddingResult.source` records whether
  patches came from `"occupancy"` or `"rgb_source"`.

- **Protocol conformance suites** (`semantic_toponav.testing.conformance`)
  ship as a public, importable package — one `run_<name>_conformance`
  function per Protocol (`LLMBackend`, encoder `Backend`,
  `AlignedRgbSource`, `SchedulerProtocol`, `Transport`, the
  `ConflictPolicy` callable). The suites raise `AssertionError` on
  contract violation, so out-of-tree adapter authors
  (`semantic-toponav-mast3r`, custom NATS transports, deadline-aware
  policies) get the same checks the built-in implementations are
  validated against in `tests/test_conformance_builtins.py`. This
  is the "raise the floor on existing protocols" follow-up to the
  policy in `decisions.md` — no new protocols, more depth on the
  ones already shipped. See [conformance.md](conformance.md).

## Future directions

What's still open. Each is a candidate for an experiment branch.

### Map construction

- **occupancy grid → topology** follow-ups: door / threshold detection
  ships (`mark_doors_by_clearance`), region segmentation for
  room-aware labels ships (`annotate_regions`, see below), and lossy
  parallel-skeleton compaction now ships (`compact_graph`, see the
  "Shipped since the MVP" entry). What's still open is more aggressive
  geometric pruning — collapsing two genuinely-parallel paths through
  a wide corridor into one rather than dedup'ing same-endpoint
  duplicates.
- **trajectory log → topology** follow-ups: DBSCAN / k-medoids cluster
  alternatives, time-aware clustering for dwell detection. The basic
  fusion of the two pipelines now ships
  (`annotate_graph_with_trajectories` plus
  `prune_low_traversal_edges` and `promote_unmapped_transitions`),
  and so does the iterative wrapper that loops snap → prune → promote
  to convergence (`fuse_trajectories_iteratively`, returning an
  :class:`IterativeFusionResult` with per-iteration history and a
  converged flag, oscillation-safe via `max_iterations`). What's
  still open is validating the result on a real recorded run.
- **VLM / CLIP labeling of regions** follow-ups: the encoder layer
  now ships (see the "Shipped" entry — `HashingBackend` for tests +
  `CLIPBackend` for real semantics, batched, plus
  `embed_region_patches` keying off `annotate_regions` bboxes). What's
  still open is *learned* region segmentation — today the patch
  anchors are connected-component bboxes from a binarized occupancy
  grid, so the encoder embeds geometric extents rather than rendered
  RGB photographs of the actual rooms. Wiring an aligned-RGB pipeline
  (Mast3R / mesh-render / robot-camera keyframes) and a finer-grained
  patch segmenter on top of it is the natural next step.

### Planning

- temporal graphs — recurring HH:MM-window restrictions ship
  (`time_aware` + `--at-time`), and the calendar layer ships too:
  three-element `closed_during` entries
  (`[start, end, weekdays]`, with `weekdays` as ints 0..6 or
  three-letter names) gate windows to specific weekdays, and the
  `closed_on_dates: [YYYY-MM-DD, ...]` property closes a node or
  edge for an entire ISO date. The CLI flag is `--at-date YYYY-MM-DD`
  (or pass a `datetime` to `time_aware(at_time=...)` to derive the
  date automatically).
- multi-agent / shared-resource planning — single-snapshot
  reservations ship (`reservation_aware` + `--reservations`), the
  online coordination layer ships
  (`SharedScheduler` + `plan_with_scheduler` + `plan_fleet` +
  `semantic-toponav fleet-plan`), the joint optimization baseline
  ships (`plan_fleet_joint` + `--strategy joint`), the synthetic
  evaluation suite ships (`eval-synthetic` / `eval-report`), hard
  deadline admission control ships (`admission="hard"` +
  `reason_code="deadline_miss"`), the branch-and-bound joint
  scheduler ships with grants / cost / budget pruning
  (`plan_fleet_bnb` + `--strategy bnb`, plus `ConflictExplanation`
  for CBS-lite diagnostics), fairness-aware ordering with
  minimax-cost / Jain-index objectives ships
  (`plan_fleet_bnb(..., objective="minimax_cost" | "max_fairness")` +
  `eval-synthetic --bnb-objective`), and an exhaustive MIS baseline
  ships as the theoretical grant-rate upper bound
  (`plan_fleet_exhaustive` + `--strategy exhaustive`) so heuristic
  results can be compared against the optimum on the same scenario.
  Scheduler persistence ships
  (`save_scheduler` / `load_scheduler`) so coordinator services can
  checkpoint across restarts. The real-time RPC shim ships
  (`SchedulerProtocol` + `SchedulerClient` + `LocalTransport`) with
  an HTTP reference transport
  (`HttpSchedulerServer` + `HttpTransport`, stdlib only). What's
  still open: anytime / repair search that mutates an existing
  committed ordering rather than re-running from scratch; a real
  MILP / CP-SAT solver baseline (e.g. via `ortools`) for the
  densely contended end where the pure-Python exhaustive baseline
  no longer fits the `n_limit=16` cap; and additional non-HTTP
  reference transports (WebSocket loop / NATS adapter) living in
  this repo.

### Embodied AI

- LLM-augmented waypoint instructions and goal parsing now ship as a
  thin rewrite/refine layer (`llm_describe_path` and `llm_resolve_goal`
  + the `--llm-backend echo|anthropic` CLI flags — see the "Shipped"
  entry). Region-embedding context for the resolver also ships
  (`--vlm-backend hashing|clip` + `embedding_scores` in the prompt
  and result — see the "Shipped" entry). The smallest dialog
  primitive ships
  (`ClarificationQuestion` / `ClarificationAnswer` /
  `AmbiguousGoalError`), and the multi-turn session driver
  (`DialogSession` + `DialogTurn`) ships too — accumulates
  `free_text` hints across replies so consecutive answers narrow
  rather than reset. What's still open: *mid-traversal* rewrite
  where the describer regenerates instructions as the robot's
  position changes (the dialog layer today targets goal
  resolution, not the running describer); and learned region
  segmentation under an aligned-RGB pipeline (Mast3R / mesh-render
  / robot-camera keyframes) so the VLM embeds actual photographs
  rather than occupancy-grid bbox crops.
- topology graphs as scratchpad for embodied agents

### Tooling

- web-based graph *editor* (the viewer ships; the editor part —
  add/remove/move nodes from a browser — does not)
- Foxglove panel for live topology + path overlays (out-of-repo, would
  live as a separate npm package consuming the v1 JSON wire format;
  the in-repo `live-viewer` covers the local dev loop today)

### Integration

- **Nav2 behavior-tree plugin** that consumes `SemanticWaypointArray`
  natively (today the included `nav2_demo_node` is a one-shot worked
  example, not a BT plugin)
- Autoware adapter
- ROS1 bridge or shim for legacy deployments
