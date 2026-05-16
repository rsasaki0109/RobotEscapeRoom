# Paper outline — internal working document

> This is the working outline that the `semantic-toponav` evaluation
> and design decisions are organized against. It is **not** the paper
> itself — it tracks what claims the paper will make, where the
> evidence for each claim already lives in the repo, and which gaps
> still need filling before submission. The 5-chapter evaluation
> structure follows the recommendation captured in
> [`STATUS_FOR_ADVICE.md`](../STATUS_FOR_ADVICE.md) §7.

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
2. The LLM-grounding path is *safe by construction*: deterministic
   floor first, LLM cannot invent node ids, rewrite invariants
   measurable (Chapters 3–4).
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
9. **Discussion / limitations**
10. **Conclusion**

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
| LLM navigation agents | SayCan, NavGPT, LM-Nav, Voyager | Architectural cousins; ours adds (a) deterministic floor + LLM-cannot-invent safety, (b) multi-agent admission |
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

- A larger-scale sweep (n_agents up to 32 with `bnb` budget-bounded) to show the BnB partial-best behavior under tight time budgets
- A dedicated incremental-admission scenario script (`examples/eval_incremental_admission.py`) wrapping `plan_fleet_insert` so the repair figure is reproducible without hand-stitching

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

- An ablation runner that emits a one-row-per-config Markdown table.
  Could be a thin wrapper on top of `plan_fleet_with_strategy` —
  estimated ~200 LOC; build only if the camera-ready figure requires it.

### 6. Evaluation chapter 3 — Language grounding

**Claim:** the deterministic floor (`resolve_goal`) is competitive on
narrow, label-aware queries; the LLM-augmented path adds value
mostly on *abstention* (correctly recognizing unresolvable queries)
and *clarification* (asking instead of guessing on ambiguous ones).

**Setup:**

- Gold corpus: `tests/fixtures/grounding/multi_floor_office.yaml` (22 cases, 13 precise / 4 ambiguous / 5 unresolvable). Pointer: [`docs/eval_grounding.md`](eval_grounding.md).
- Both resolvers (`deterministic`, `llm_resolve_goal` over `EchoBackend` / `AnthropicBackend`) run via `eval-grounding` CLI.

**Metrics:** precision@1, recall@3, recall@5, clarification_rate, false_positive_resolve_rate, abstention_rate.

**Headline numbers (already measured, deterministic resolver, 22-case fixture):**

- precision@1 = 1.00
- recall@3 = recall@5 = 1.00
- clarification_rate = 0.00 (deterministic resolver doesn't emit `ClarificationQuestion` on its own)
- false_positive_resolve_rate = 0.20
- abstention_rate = 0.80

**The story this tells:** bag-of-words + floor parsing handles every *answerable* query in the fixture. The remaining axis where the LLM-augmented resolver should win is **abstention** — we expect the LLM-augmented `false_positive_resolve_rate` to drop below 0.20. With `EchoBackend` it actually rises to 1.00 (echo-fallback can't tell "no candidate" from "any candidate"), so the EchoBackend numbers are illustrative of the *machinery*, not of the *contribution*; the real Anthropic backend numbers go in the paper.

**Gap to fill:**

- Run the Anthropic backend against the same corpus and add a row to the report. Numbers go straight into the chapter.
- Optionally: a larger corpus (~100 cases) covering more node-label patterns, ambiguous synonyms, and floor-misnaming. The 22-case fixture is enough for the existence claim; a larger corpus strengthens it.

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

- A short "external adapter authoring" walkthrough showing a
  Mast3R-style `AlignedRgbSource` outside the repo passing the
  conformance suite. This is doubly useful — it doubles as the
  ecosystem onboarding doc when Phase C (`semantic-toponav-mast3r`
  package) lands.

---

## 9. Discussion / limitations

Threads to be honest about:

- Synthetic-eval bias: every coordination number comes from
  seed-driven generators. Real fleets have correlated request
  arrivals, heterogeneous robots, and stochastic execution times.
  We measure planning-layer correctness, not closed-loop SLA.
- Language grounding scope: the gold corpus tests retrieval against
  a topological graph, not free-form scene understanding. The LLM
  is a re-ranker / clarifier, not a perception system.
- Single-machine scheduler: `SharedScheduler` is process-local;
  the RPC shim (`SchedulerService` + `Transport`) demonstrates
  the contract over HTTP but multi-DC consensus is not part of v1.
- No closed-loop integration evaluation: the Nav2 BT plugin (the
  natural physical-execution outlet) is intentionally
  out-of-repo and arrives after v1.0.

## 10. Conclusion

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

## Open holes — what to decide *before* writing

1. **Venue.** Robotics-systems (RSS / IROS / ICRA / CoRL) vs OSS
   tooling track (FOSDEM-style) vs LLM-for-robotics workshop. The
   contract / conformance story is closer to systems; the grounding
   chapter is closer to LM4Nav workshops.
2. **Single paper vs companion paper.** All five evaluation chapters
   in one work risks each being shallow. Splitting (e.g.
   "coordination + schema" and "grounding + describer safety" as
   two papers) is plausible.
3. **Anthropic-backend numbers**: get them before deciding chapter
   3's headline framing. Without them the LLM resolver story is
   "echo backend is illustrative" — fine for an outline, weak for a
   conference submission.
4. **Human eval scope**: 0 cases, 20 cases, or a full crowd-sourced
   panel for the describer rewrite. The deterministic invariants
   already make the safety claim; the human eval is purely the
   *helpfulness* side.

Update this section as decisions are made.
