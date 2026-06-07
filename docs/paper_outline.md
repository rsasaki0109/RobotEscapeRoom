# Paper outline — internal working document

> This is the working outline that the `semantic-toponav` evaluation
> and design decisions are organized against. It is **not** the paper
> itself — it tracks what claims the paper will make, where the
> evidence for each claim already lives in the repo, and which gaps
> still need filling before submission. The evaluation structure
> follows the recommendation captured in
> [`STATUS_FOR_ADVICE.md`](../STATUS_FOR_ADVICE.md) §7; it grew from
> five to **six chapters** when the visual-localization / topological-
> navigation axis landed (PRs #75–#81, #85) — see Chapter 6 and the
> refreshed decision section at the end.

## Working title

**Grounded Semantic-Topological Planning for Multi-Robot Navigation under Language-Specified Goals and Temporal Resource Constraints**

Variant subtitle: *A monitored middle planning layer between dense maps and motion executors.*

## Positioning paragraph (for the abstract)

`semantic-toponav` proposes a **middle planning layer** that sits
between dense metric maps (SLAM / occupancy / HD) and motion
executors (Nav2 / Autoware / learned policies). The layer decides
*where to go, why, and who first* — under language-specified goals,
calendar-aware closures, soft preferences, deadlines, and
multi-agent reservations. The contribution is not a better MAPF
solver; it is a **monitored, plugin-tested layer** where LLM/VLM
grounding feeds a deterministic planner that hands a resource-aware
fleet scheduler an explainable admission decision.

Three claims hold the abstract together:

1. The middle layer is *expressive enough* to absorb language and
   time/preference constraints without losing fleet performance
   (Chapters 1–2).
2. Grounding *into the graph* is *safe by construction* and works
   from both language and perception: the deterministic floor goes
   first, the LLM cannot invent node ids, rewrite invariants are
   measurable, and the same graph an image grounds against is
   re-rankable by its own topology (Chapters 3–4, 6).
3. The plugin contracts are *testable*, not just declarative
   (Chapter 5).

## What the paper is *not*

| Often-asked-about | Why it's out of scope |
|---|---|
| Head-to-head MAPF on gridworld (CBS / EECBS / MAPF-LNS2) | That is their turf. We compete on *semantic / time / language constraints*, not on raw MAPF performance. |
| End-to-end Vision-Language Navigation (HM3D / OVON / RxR scores) | We are a planning *layer*, not a closed-loop navigation policy. Embedding / grounding evals are scoped to retrieval over a topological graph, not to physical execution. |
| LLM training / fine-tuning | We never train a model. The LLM is a plugin behind a Protocol. |
| Low-level control (MPC / MPPI), SLAM, obstacle avoidance | Deliberately out of scope — see [`docs/decisions.md`](decisions.md). |

---

## Section sketch

1. **Introduction** — middle-layer thesis, three claims, what the paper is not
2. **Related work** — MAPF, semantic SLAM, VLN, LLM navigation agents, scheduling
3. **System overview** — graph schema, cost composition, scheduler, LLM/VLM plugin points
4. **Evaluation chapter 1 — Fleet scheduling and admission**
5. **Evaluation chapter 2 — Semantic constraints ablation**
6. **Evaluation chapter 3 — Language grounding**
7. **Evaluation chapter 4 — Describer rewrite safety**
8. **Evaluation chapter 5 — Protocol conformance as engineering contribution**
9. **Evaluation chapter 6 — Visual localization and topological navigation**
10. **Discussion / limitations**
11. **Conclusion**

### 1. Introduction

Claims to land in the intro:

- The split *where-to-go* vs *how-to-move-locally* is real and
  underserved as a contract — most systems either bake graph
  planning into the motion stack (Nav2) or leave it to bespoke
  scripts (typical research papers)
- "Language-specified goals" requires *grounding into something*;
  for navigation that something is a graph, and the act of grounding
  is more constrained than open-vocabulary VLN benchmarks suggest
- A layer that gets the *contracts* right (admission reasons,
  conflict explanations, resolve traces, conformance suites) is
  more useful long-term than one that gets one number on one
  benchmark right

Threads to weave through:

- Reproducibility: every figure ships from a seed-driven generator
  or a versioned fixture (see Chapter 1 / Chapter 3)
- Audit-ability: every reject is structured (`reason_code`), every
  LLM rewrite has a deterministic floor underneath
- Optional-by-default: heavy dependencies (CLIP, Mast3R, ortools)
  live behind extras or out-of-repo packages

### 2. Related work

Buckets to cover:

| Bucket | Reference points | Position |
|---|---|---|
| Classical MAPF | CBS, EECBS, MAPF-LNS2, MovingAI benchmark, Flatland | Cite as the solver-track baseline; we deliberately don't compete on it |
| Open-vocabulary semantic SLAM | ConceptGraphs, OpenScene, OK-Robot | Adjacent — we consume a *graph*, they produce one. Plug point story (`AlignedRgbSource`, encoder `Backend`) connects us |
| Vision-Language Navigation | HM3D-OVON, RxR, R2R, RoomTour3D | The "end-to-end" branch. We are the middle layer; VLN systems can plug into us via `llm_resolve_goal` / `embed_region_patches` |
| LLM navigation agents | SayCan, NavGPT, LM-Nav, Voyager | Architectural cousins; ours adds (a) deterministic floor + LLM-cannot-invent safety, (b) multi-agent admission. LM-Nav maps onto our layers almost 1:1 — see [`related_work.md`](related_work.md) |
| Visual place recognition / topological localization | SPTM, RoboHop, AnyLoc, VPR-Bench, ViNT/NoMaD | `localize_by_image` is node-level VPR; `VisualRouteFollower` is the SPTM retrieval-network role. Perception (`Backend`) + locomotion (ViNT/Nav2) stay out of repo. Detail in [`related_work.md`](related_work.md) |
| Multi-robot scheduling | EDF, MILP-based job-shop, lifelong MAPF | We do FCFS / priority / EDF / joint / BnB / exhaustive / insertion, all under one CLI — and an explanation surface they typically don't expose |
| Robotic middleware | Nav2, Autoware, MoveIt | We sit *upstream* of these; the `SemanticWaypoint` schema (v1-locked) is the bridge |

### 3. System overview

Sections:

- **Graph schema (v1)** — node/edge types, properties (preferences, floor, closed_during, closed_on_dates). Pointer: [`docs/waypoint_schema.md`](waypoint_schema.md), [`docs/schema_v1.md`](schema_v1.md)
- **Cost composition** — `compose_costs` stack, the 12+ composable cost-fn helpers. Pointer: [`docs/cost_composition.md`](cost_composition.md)
- **Multi-agent scheduler** — `SharedScheduler`, atomic claim_many with rollback, 7 strategies, `ConflictPolicy` plug point, optional RPC. Pointer: [`docs/coordination.md`](coordination.md)
- **LLM/VLM plugin points** — `LLMBackend`, encoder `Backend`, `AlignedRgbSource`, with the deterministic-floor-then-LLM safety pattern. Pointer: [`docs/queries.md`](queries.md), [`docs/conformance.md`](conformance.md)
- **Wire surfaces (v1-locked)** — `SemanticWaypointArray`, `PlanWithSchedulerResult`, `FleetPlanResult`, `ConflictExplanation`, `ResolveTrace`, preference metadata. Pointer: [`docs/schema_v1.md`](schema_v1.md)

System-overview figures to include:

- Layer diagram (dense map → semantic-toponav → motion executor)
- One full reject-explanation trace (`reason_code` + `ConflictExplanation`)
- One end-to-end pipeline (query → resolve → plan → admit → describe → execute), with the deterministic floor and LLM rewrite shown as separate boxes

---

### 4. Evaluation chapter 1 — Fleet scheduling and admission

**Claim:** the layer absorbs realistic multi-agent contention with
explainable admission decisions; the strategy family scales from
trivial-greedy to an exhaustive MIS upper bound, and a fast
insertion-based repair planner handles the live-update case.

**Setup:**

- 4 deterministic graph generators (`chain`, `star`, `doorway`, `multi_floor_office`) seeded by `(scenario, seed)`. Pointer: [`semantic_toponav/eval/generators.py`](../semantic_toponav/eval/generators.py).
- 7 strategies: `greedy`, `priority`, `deadline`, `joint`, `bnb` × 3 objectives, `exhaustive` (MIS upper bound), `insert`. Pointer: [`docs/coordination.md`](coordination.md).
- Hard vs soft admission (`reason_code` distribution shifts).

**Metrics already shipped:** grant_rate, total_path_cost, makespan, max_wait, Jain fairness, conflict_count, deadline_misses, latency_ms (p50/p95). All available via `eval-synthetic` + `eval-report`. Pointer: [`semantic_toponav/eval/metrics.py`](../semantic_toponav/eval/metrics.py).

**Headline figures to render:**

- Grant-rate by strategy across the 4 generators (BnB vs exhaustive shows whether pruning is matching the optimum)
- Jain fairness when `bnb-objective={min_cost, minimax_cost, max_fairness}` — the fairness/cost tradeoff is the BnB story
- Latency p50/p95 by fleet size — how each strategy scales
- `reason_code` distribution under hard admission with tightening deadlines — the explainability story
- Insertion repair vs full BnB on the *incremental admission* scenario (one new request added to a committed fleet)

**Already in the repo:** every metric, every CLI flag, every fixture. The PR producing each figure is a `eval-synthetic --scenario … --strategy …` invocation.

**Gap to fill before camera-ready:**

- ~~A larger-scale sweep (n_agents up to 32 with `bnb` budget-bounded) to show the BnB partial-best behavior under tight time budgets~~ **DONE** — [`examples/eval_bnb_budget_sweep.py`](../examples/eval_bnb_budget_sweep.py) sweeps `n = 3k` agents over clustered contention with a fixed `max_nodes` budget: BnB completes and matches the exhaustive optimum on the smallest fleet, stays strictly above greedy (anytime) on larger fleets where the budget is exhausted, and keeps running past `n = 24` where the 2^n exhaustive baseline is infeasible. Guarded by [`tests/test_eval_bnb_budget_sweep.py`](../tests/test_eval_bnb_budget_sweep.py)
- ~~A dedicated incremental-admission scenario script wrapping `plan_fleet_insert` so the repair figure is reproducible without hand-stitching~~ **DONE** — [`examples/eval_incremental_admission.py`](../examples/eval_incremental_admission.py) renders the deterministic naive-append vs insertion-repair vs full-BnB table (insertion repair admits the urgent newcomer and matches the BnB optimum at 16× fewer trial orderings); guarded by [`tests/test_eval_incremental_admission.py`](../tests/test_eval_incremental_admission.py)

### 5. Evaluation chapter 2 — Semantic constraints ablation

**Claim:** the same coordination machinery accepts time-of-day,
calendar, soft preference, floor-aware, and restricted-edge
constraints — and refuses to silently route around an unspecified
calendar.

**Setup:** one graph (the multi-floor office), one fleet, eight
constraint configurations:

1. baseline (no constraints)
2. `time_aware` recurring closure
3. `time_aware` + `--at-date` weekday filter
4. `time_aware` + `closed_on_dates` full-day override
5. `preference_aware` (scenic, edge-level)
6. `preference_aware` (node-level inheritance, `use_node_defaults=True`)
7. `floor_change_penalty`
8. `compose_costs(prefer_elevator, block_edge_type stairs_up)`

**Metrics:**

- Constraint satisfaction (0/1 per agent — pass / silently routed through a closed resource)
- Explainability: when admission is denied, is `reason_code` informative?
- Soft-preference shift: under increasing weight, does the route smoothly migrate to higher-scoring edges? (Plot expected path-cost vs preference weight)
- Calendar-safety: with weekday-filtered closures and no `at_date`, the planner *must* raise (the "explicit error > silent skip" decision from PR #54). Show the error rate at 100%.

**Already in the repo:** every constraint, the CLI flags
(`--at-time`, `--at-date`, `--prefer`, `--prefer-floor`,
`--same-floor-only`, `--block-edge-type`), and corresponding unit
tests under `tests/test_time_aware.py`, `tests/test_preference_aware.py`,
`tests/test_floor_aware.py`.

**Gap to fill:**

- ~~An ablation runner that emits a one-row-per-config Markdown table.~~
  **DONE** — [`examples/eval_constraints_ablation.py`](../examples/eval_constraints_ablation.py)
  runs nine configurations (baseline, three time-of-day/calendar variants,
  edge- and node-level soft preference, floor-change penalty, a
  `compose_costs` block, and the calendar-safety raise) on one office
  graph + fixed query, emitting a one-row-per-config table that shows the
  route migrating onto the scenic corridor, the penalty surfacing in the
  plan cost, and the weekday-without-date query raising. Guarded by
  [`tests/test_eval_constraints_ablation.py`](../tests/test_eval_constraints_ablation.py).

### 6. Evaluation chapter 3 — Language grounding

**Claim:** the deterministic floor (`resolve_goal`) is competitive on
narrow, label-aware queries; the LLM-augmented path adds value
mostly on *abstention* (correctly recognizing unresolvable queries)
and *clarification* (asking instead of guessing on ambiguous ones).

**Setup:**

- Gold corpus: `tests/fixtures/grounding/multi_floor_office.yaml` (100 cases, 66 precise / 18 ambiguous / 16 unresolvable; expanded 22 → 50 → 100). Pointer: [`docs/eval_grounding.md`](eval_grounding.md).
- Both resolvers (`deterministic`, `llm_resolve_goal` over `EchoBackend` / `AnthropicBackend`) run via `eval-grounding` CLI.

**Metrics:** precision@1, recall@3, recall@5, clarification_rate, false_positive_resolve_rate, abstention_rate.

**Headline numbers (already measured, deterministic resolver, 100-case fixture):**

- precision@1 = 1.00
- recall@3 = recall@5 = 1.00
- clarification_rate = 0.00 (deterministic resolver doesn't emit `ClarificationQuestion` on its own)
- false_positive_resolve_rate = 0.19 (3/16 unresolvable — `"server room"`, `"secret room"` and `"break room"` all pull `meeting_room_2f` via the `'room'` label token)
- abstention_rate = 0.81

**The story this tells:** bag-of-words + floor parsing handles every *answerable* query in the fixture even after the 22 → 50 → 100 expansions widened the linguistic surface (ordinal/word/abbreviated floor mentions, single-token labels, label fragments, comma-separated and verb-phrase forms, bare-type queries). Doubling the corpus did not dent the precision ceiling — the deterministic floor resolves every answerable query at 100 cases. The remaining axis where the LLM-augmented resolver should win is **abstention** — we expect the LLM-augmented `false_positive_resolve_rate` to drop below 0.19 (the persistent `'room'`-token false positive). With `EchoBackend` it actually rises to 1.00 (echo-fallback can't tell "no candidate" from "any candidate"), so the EchoBackend numbers are illustrative of the *machinery*, not of the *contribution*; the real Anthropic backend numbers go in the paper.

**Gap to fill:**

- Run the Anthropic backend against the same corpus and add a row to the report. Numbers go straight into the chapter.
- ~~Optionally: a larger corpus (~100 cases) covering even more node-label patterns and floor-misnaming variants.~~ **DONE** — the corpus is now 100 cases; precision@1 stays 1.00 and the only failure mode is the `'room'`-token false positive on unresolvable queries (now 3/16), which is exactly the abstention gap the Anthropic backend is meant to close.

### 7. Evaluation chapter 4 — Describer rewrite safety

**Claim:** the LLM rewrite path is *safe by construction*:
deterministic floor always present, four invariants measurable.

**Setup:**

- `evaluate_describer_safety` runs `llm_describe_path` against
  representative probes generated from the same multi-floor office
  fixture. Full-plan + mid-traversal (with and without `situation=`)
  variants are exercised.
- Backend: `EchoBackend` (for the deterministic invariants — pass
  trivially on fallback) and `AnthropicBackend` (for the
  non-fallback path).

**Invariants (pass/fail per case, aggregate rate per backend):**

1. `references_preserved` — each rewritten step still surfaces a
   token from its deterministic node label
2. `step_indices_preserved` — rewrite emits one line per
   `base_step`
3. `prior_steps_untouched` — for `start_index > 0`, the rewrite
   does not surface labels that exist only in `path[:start_index]`
4. `situation_changes_output` — `situation=` produces either a
   different rewritten slice or a different backend prompt

**Already in the repo:** the full metric pipeline, deterministic
invariants tested with intentional violations (
`tests/test_eval_grounding.py::test_evaluate_describer_safety_dropping_reference_fails`
etc.).

**Gap to fill:**

- Small (20–50 case) human-eval addendum rating coherence and
  helpfulness on a 5-point scale, *optional*, not the main signal.
  Useful if the camera-ready needs a "humans agree the rewrites are
  more natural than the deterministic floor" sidebar.
- Real Anthropic-backend numbers (the EchoBackend always falls back,
  so its non-trivial invariant rates aren't meaningful).

### 8. Evaluation chapter 5 — Protocol conformance as engineering contribution

**Claim:** the plugin contracts are *testable*, not just declarative.
Six Protocols, six public conformance suites, every shipped in-tree
implementation passes them, with failure-mode depth (empty / large /
unicode prompts; atomic rollback; idempotent release; half-open
adjacency; etc.).

**Setup:**

- 6 protocols: `LLMBackend`, encoder `Backend`, `AlignedRgbSource`,
  `SchedulerProtocol`, `Transport`, `ConflictPolicy`.
- For each: a `run_<name>_conformance(...)` helper under
  `semantic_toponav.testing.conformance`.
- `tests/test_conformance_builtins.py` runs every in-tree
  implementation through every applicable suite (Hashing /
  Echo / StaticImageRgbSource / SharedScheduler / SchedulerClient /
  LocalTransport / HttpTransport / FCFS / priority).

**Metric:** number of failure-mode invariants per suite (e.g.
ConflictPolicy has 4: returns ClaimDecision, preempted ⊆ conflicts,
preempted no duplicates, no scheduler mutation). The contribution
is **the list of invariants the contract is testable against**, not
a numeric score.

**Framing:** systems papers often handwave plugin extensibility.
We argue that *contract testability* — the adapter author can run
one function call against their implementation and know whether
they conform — is the missing piece. Numbers live in
[`docs/conformance.md`](conformance.md).

**Gap to fill:**

- ~~A short "external adapter authoring" walkthrough showing a
  Mast3R-style `AlignedRgbSource` outside the repo passing the
  conformance suite.~~ **DONE** —
  [`docs/authoring_external_adapters.md`](authoring_external_adapters.md)
  walks an out-of-repo author through implementing a rerender-style
  `AlignedRgbSource` (no stored image) and passing
  `run_aligned_rgb_source_conformance` in one call;
  [`examples/external_adapter_conformance.py`](../examples/external_adapter_conformance.py)
  is the runnable version, guarded by
  [`tests/test_external_adapter_conformance.py`](../tests/test_external_adapter_conformance.py).
  Doubles as the onboarding doc for Phase C (`semantic-toponav-mast3r`).

### 9. Evaluation chapter 6 — Visual localization and topological navigation

**Claim:** the same graph the language path grounds into is also an
*image*-groundable map. A camera frame retrieves its node (node-level
VPR); a goal image plans a topological route with monotonic progress
(LM-Nav-style); and graph-context re-ranking (RoboHop-style) damps
perceptual aliasing — all with the encoder behind an `Backend` Protocol,
so torch stays optional and locomotion stays out of repo (decision D-16).
This is the *perception twin* of Chapter 3: image → node where Chapter 3
is language → node, reported with symmetric metrics.

**Setup:**

- `localize_by_image` (image → node, cosine over per-node embeddings,
  optional `neighbor_weight` / `neighbor_hops` graph-context re-rank);
  `plan_visual_route` / `VisualRouteFollower` (goal image → topological
  route, monotonic progress). Pointer:
  [`semantic_toponav/query/visual_localization.py`](../semantic_toponav/query/visual_localization.py),
  [`semantic_toponav/query/visual_navigation.py`](../semantic_toponav/query/visual_navigation.py).
- Two encoders behind the same `Backend` Protocol: deterministic
  `HashingBackend` (CI, no torch) and `CLIPBackend` (`[vlm]` extra, real
  semantics).
- Corpora: `visual_depot.yaml` (byte-identical frames → deterministic CI
  check), `visual_depot_drive.yaml` (16 distinct drive frames → real
  CLIP), and the engineered aliasing corpus from
  `semantic_toponav.eval.aliasing_visual_corpus` (deterministic, designed
  to surface the re-rank lift in aggregate).

**Metrics:** precision@1, recall@3, recall@5, false_positive_resolve_rate,
abstention_rate — the *same* shape as Chapter 3, so the language and
visual grounding arms report symmetric numbers (a standard VPR
`recall@K` protocol phrased like the resolver eval).

**Headline numbers:**

- Real CLIP on the 5-place Depot drive (manual `[vlm]` artifact):
  precision@1 = recall@3 = recall@5 = 1.00. Pointer:
  [`docs/visual_grounding_report_sample.md`](visual_grounding_report_sample.md).
- Neighbor re-rank aggregate ablation (deterministic, **reproduced in
  CI**): precision@1 / recall@3 / recall@5 = **0.00 → 1.00** on the
  engineered aliasing corpus where every genuine place has a
  higher-cosine look-alike elsewhere in the building (PR #85). Pointer:
  [`tests/test_visual_benchmark.py`](../tests/test_visual_benchmark.py),
  [`docs/eval_grounding.md`](eval_grounding.md).

**Already in the repo:** the `localize` / `visual-route` /
`eval-visual-grounding` CLI (with `--neighbor-weight` / `--neighbor-hops`),
both real and deterministic corpora, the aliasing benchmark, two demos,
and the navigation GIF (`docs/images/24_visual_navigation.gif`).

**Two-layer eval discipline (mirrors the language arm):** the metric
machinery is CI-covered deterministically via `HashingBackend`
(`tests/test_eval_visual_grounding.py`, `test_visual_localization.py`,
`test_visual_navigation.py`, `test_visual_benchmark.py`), while the
real-CLIP numbers are a manual release-prep artifact — the `[vlm]` extra
stays out of CI by design, exactly as the Anthropic resolver numbers do.

**Gap to fill:**

- The real-CLIP numbers are a manual `[vlm]` artifact by design (same
  posture as Chapter 3's Anthropic numbers); they are not CI-reproduced.
- A larger self-similar *real-image* corpus where neighbor re-rank lifts
  the aggregate under CLIP. The deterministic benchmark already proves
  the mechanism; a CLIP-scale version would strengthen the empirical
  claim. The natural heavy-deps source of per-node embeddings for such a
  map is the Mast3R `AlignedRgbSource` adapter (Phase C #3, post-paper).

---

## 10. Discussion / limitations

Threads to be honest about:

- Synthetic-eval bias: every coordination number comes from
  seed-driven generators. Real fleets have correlated request
  arrivals, heterogeneous robots, and stochastic execution times.
  We measure planning-layer correctness, not closed-loop SLA.
- Language grounding scope: the gold corpus tests retrieval against
  a topological graph, not free-form scene understanding. The LLM
  is a re-ranker / clarifier, not a perception system.
- Visual grounding scope (Chapter 6): `localize_by_image` is
  node-level VPR over a *pre-built* graph, not closed-loop visual
  navigation — the encoder is a `Backend` and the locomotion stays
  out of repo (ViNT / NoMaD / Nav2). The neighbor re-rank lift is
  proven in aggregate on an engineered aliasing corpus and per case
  on real CLIP; a large real-image self-similar benchmark is future
  work. Per-node embeddings come from offline prototypes, not yet a
  live Mast3R reconstruction (Phase C #3).
- Single-machine scheduler: `SharedScheduler` is process-local;
  the RPC shim (`SchedulerService` + `Transport`) demonstrates
  the contract over HTTP but multi-DC consensus is not part of v1.
- No closed-loop integration evaluation: the Nav2 BT plugin (the
  natural physical-execution outlet) is intentionally
  out-of-repo and arrives after v1.0.

## 11. Conclusion

Three sentences:

1. The middle layer between dense maps and motion executors is real,
   contract-able, and worth treating as a first-class research
   target.
2. With `semantic-toponav`, that contract is now: a graph schema,
   six v1-locked wire formats, six Protocol conformance suites, and
   a coordination + grounding eval harness that runs in CI.
3. The next obvious work is **ecosystem outside this repo** —
   Nav2 BT plugin, Foxglove panel, Mast3R adapter — not more
   in-tree features.

---

## Evidence index — claim → artifact

A small lookup table the paper-writing pass can hit when filling in
references. Every row points at code or fixtures already in the repo
(PRs #35–#61, all merged).

| Claim | Artifact |
|---|---|
| Atomic claim_many | `tests/test_coordination_scheduler.py`, conformance suite `run_scheduler_conformance` |
| Half-open interval adjacency | `tests/test_conformance_builtins.py`, `_intervals_overlap` doc |
| BnB matches exhaustive on small n | `tests/test_coordination_bnb.py::test_bnb_small_n_matches_exhaustive_joint` |
| Insertion repair ≥ naive append | `tests/test_coordination_repair.py::test_insert_finds_at_least_as_many_grants_as_naive_appending` |
| Closed `reason_code` enum | `schemas/plan_with_scheduler_result_v1.schema.json` + `tests/test_schema_v1_lock.py::test_reason_code_enum_matches_across_schemas` |
| Deterministic resolver precision@1 = 1.00 on shipped corpus | `eval-grounding tests/fixtures/grounding/multi_floor_office.yaml` |
| LLM cannot invent node ids | `tests/test_llm_resolve.py::test_unparseable_response_falls_back`, `tests/test_eval_grounding.py::test_evaluate_describer_safety_dropping_reference_fails` |
| Mid-traversal step number preservation | `tests/test_llm_describe.py::test_start_index_skips_completed_steps_and_preserves_numbering` |
| Calendar-aware safety (raise on weekday-filter without at_date) | `tests/test_time_aware.py::test_weekday_filter_without_at_date_raises` |
| Soft preferences node-default inheritance | `tests/test_preference_aware.py::test_node_default_applies_to_incident_edges` |
| Six conformance suites + failure-mode depth | `semantic_toponav/testing/conformance/`, `tests/test_conformance_builtins.py` |
| HTTP transport round-trips | `tests/test_coordination_http_transport.py` |
| Scheduler save/load round-trip | `tests/test_coordination_persistence.py` |
| Image→node localization (node-level VPR) | `localize_by_image`, `tests/test_visual_localization.py`, `eval-visual-grounding` |
| Neighbor re-rank lifts aggregate recall (RoboHop-style) | `tests/test_visual_benchmark.py` (0.00 → 1.00), `semantic_toponav/eval/visual_benchmark.py` |
| Goal-image topological route + monotonic progress (LM-Nav-style) | `plan_visual_route` / `VisualRouteFollower`, `tests/test_visual_navigation.py` |
| Real-CLIP grounding numbers (manual `[vlm]` artifact) | `docs/visual_grounding_report_sample.md` |

## Open holes — what to decide *before* writing

> **Status (2026-06-07).** The decisions below are still the author's to
> make, but the in-tree work is now done enough to *ground* them. This
> section adds a maturity/gating read of all six chapters and a
> recommended structure that falls out of it. Nothing here is committed —
> it is decision support, not a decision.

### Chapter maturity & gating

What is actually blocking each chapter, given the shipped repo:

| Chapter | Evidence shipped | Remaining gap | Gate type |
|---|---|---|---|
| 1 Fleet scheduling | every metric / CLI flag / fixture; figures are `eval-synthetic` invocations | larger n≤32 BnB sweep; incremental-admission script | **none** — coding-only, writable now |
| 2 Constraints ablation | every constraint + flag + unit test | one ~200-LOC ablation-table runner | **none** — coding-only, writable now |
| 3 Language grounding | 50-case corpus; deterministic numbers measured (p@1 1.00, fp_resolve 0.25, abstain 0.75) | **real Anthropic numbers** for the contribution framing | **external** — API key + budget + author run |
| 4 Describer safety | invariant pipeline + intentional-violation tests | Anthropic non-fallback numbers; optional human-eval | external + optional human-eval |
| 5 Protocol conformance | 6 protocols / 6 suites / all in-tree impls pass + failure depth | external-adapter authoring walkthrough | **none** — coding/docs-only, writable now |
| 6 Visual localize/nav | localize / route / aggregate re-rank (0.00 → 1.00 in CI, #85) + real-CLIP manual artifact | larger real-image self-similar corpus; Mast3R source | real-CLIP manual by design; rest deferred |

The split is clean: **Chapters 1, 2, 5 have no external gate** (every
figure is reproducible from CI today), while **Chapters 3 and 4 are
gated on the Anthropic backend run** and Chapter 6 carries a
by-design-manual real-CLIP artifact alongside its CI-reproduced
mechanism.

### Recommended structure (companion split)

The maturity read lines up with the long-hypothesised companion split,
and sharpens it now that Chapter 6 exists:

- **Paper A — the systems / contracts paper.** Chapters 1 (fleet
  scheduling), 2 (constraints ablation), 5 (protocol conformance), on
  top of the schema + system-overview. Every number is
  CI-reproducible; **no external gate** — it can be drafted immediately.
  The conformance-as-contribution angle is unusual and reads as
  *systems*. Natural venue: a robotics-systems conference (ICRA / IROS)
  or a software/tooling track.
- **Paper B — the grounding / perception paper.** Chapters 3 (language
  grounding), 4 (describer safety), 6 (visual localization). A coherent
  "grounding language *and* perception into a topological graph, safely"
  story. Gated on the Anthropic numbers for Chapters 3–4. Natural venue:
  CoRL or an LM-for-robotics (LM4Nav-style) workshop.

The practical consequence: **the Anthropic run is the critical path for
Paper B only.** Paper A is decoupled and can start now. A single
combined paper remains possible but risks six shallow chapters; the
split lets each land deeper.

### The four decisions (with the recommendation that follows)

1. **Venue.** Robotics-systems (RSS / IROS / ICRA / CoRL) vs OSS tooling
   track (FOSDEM-style) vs LLM-for-robotics workshop. *Recommendation:*
   if splitting, Paper A → systems (ICRA/IROS or tooling), Paper B →
   CoRL / LM4Nav workshop. The contract / conformance story is closer to
   systems; the grounding + visual chapters are closer to LM4Nav.
2. **Single paper vs companion paper.** *Recommendation:* **companion
   split A/B as above** — the gating structure already separates them,
   and six chapters in one work would be thin. Confirm before writing.
3. **Anthropic-backend numbers.** Get them before deciding Paper B's
   Chapter 3 headline framing; without them the LLM resolver story is
   "echo backend is illustrative" — fine for an outline, weak for a
   submission. *This is the one remaining task that moves a number and
   is the critical path for Paper B.* It needs an API key, budget, and
   an author run (manual, out of CI by design).
4. **Human eval scope.** 0 cases, 20–50 cases, or a full crowd panel for
   the describer rewrite. *Recommendation:* a 20–50 case helpfulness
   sidebar at most — the deterministic invariants already carry the
   safety claim; human-eval is purely the *helpfulness* side and should
   not gate submission.

Update this section as decisions are made.
