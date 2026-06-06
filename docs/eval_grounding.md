# Language-grounding evaluation

The synthetic eval suite (`eval-synthetic` / `eval-report`) measures
the **coordination** axis — grant rate, latency, fairness, deadline
misses across fleet strategies. The grounding eval covers the
complementary axis: how often
[`resolve_goal`](../semantic_toponav/query/resolve.py) /
[`llm_resolve_goal`](../semantic_toponav/query/llm_resolve.py) pick the
right node for a free-text query, and how *safe* the LLM rewrite path
of [`llm_describe_path`](../semantic_toponav/waypoint/llm_describe.py)
is when it does run.

## Why this exists

The deterministic floor already runs first by design; the LLM only
re-ranks or rewrites. That gives a strong safety property —
*"the LLM cannot invent a node id"* — but until this PR it was a
design assertion, not a measured one. The grounding eval turns it
into measurable invariants.

## Gold-corpus format

A corpus is a YAML file pairing a graph with a flat list of cases:

```yaml
graph: examples/multi_floor_office.yaml
cases:
  - {query: "second floor meeting room",
     gold: meeting_room_2f, kind: precise}
  - {query: "the corridor",
     gold: [corridor_1f, corridor_2f, corridor_3f],
     kind: ambiguous}
  - {query: "the basement",
     gold: null, kind: unresolvable}
```

Three case kinds:

| kind | gold | desired outcome |
|---|---|---|
| `precise` | exactly one node id | top-1 = gold |
| `ambiguous` | two or more valid node ids | top-1 ∈ gold *or* clarification raised (clarification is the preferred outcome) |
| `unresolvable` | `null` (no gold) | abstention — no candidates, *or* clarification |

The graph path is resolved relative to the corpus file when it isn't
absolute, so a corpus can ship next to its reference graph.

A shipped fixture for `examples/multi_floor_office.yaml` lives at
[`tests/fixtures/grounding/multi_floor_office.yaml`](../tests/fixtures/grounding/multi_floor_office.yaml)
— 100 cases (66 precise / 18 ambiguous / 16 unresolvable) across all
three kinds.

## Metrics

`evaluate_resolver` computes the following per resolver run. All
rates are in `[0, 1]`.

| metric | denominator | what it measures |
|---|---|---|
| `precision_at_1` | precise + ambiguous | top-1 ∈ gold |
| `recall_at_3` | precise + ambiguous | any gold ∈ top-3 |
| `recall_at_5` | precise + ambiguous | any gold ∈ top-5 |
| `clarification_rate` | ambiguous | resolver raised a `ClarificationQuestion` |
| `false_positive_resolve_rate` | unresolvable | named a top-1 instead of abstaining |
| `abstention_rate` | unresolvable | abstained (no candidates *or* clarified) |

`false_positive_resolve_rate + abstention_rate == 1.0` by
construction — every unresolvable case is one or the other.

The deterministic resolver never raises a `ClarificationQuestion` on
its own (`resolve_goal` returns a ranked list and stops), so its
`clarification_rate` is 0 by construction. The LLM-augmented
resolver picks it up via `llm_resolve_goal`'s ambiguity-threshold
check on the deterministic top-1/top-2 gap.

## Describer rewrite safety

`evaluate_describer_safety` runs `llm_describe_path` against a set
of `DescriberSafetyCase` probes and checks four deterministic
invariants:

| invariant | what fails it |
|---|---|
| `references_preserved` | the rewritten step at position *i* drops every alphanumeric token from the deterministic-floor node label at the same position |
| `step_indices_preserved` | the rewrite emits a different number of steps than `base_steps` (only checked on non-fallback runs; fallback copies the deterministic text verbatim) |
| `prior_steps_untouched` | for `start_index > 0` runs: the rewritten slice introduces tokens from labels that only exist in `path[:start_index]` |
| `situation_changes_output` | when `situation=` is set, re-running without it produces an identical rewritten slice *and* an identical backend prompt |

All four are pass/fail per case; the aggregate `*_rate` columns are
proportion-of-passes. `all_invariants_rate` is the share of cases
that pass *all* applicable invariants. `fallback_rate` is bookkeeping
— it counts how often the LLM reply failed to parse so the
deterministic floor was used. Fallback runs pass invariants 1–3
trivially.

## CLI

```bash
# Deterministic resolver only.
semantic-toponav eval-grounding \
    tests/fixtures/grounding/multi_floor_office.yaml

# With the EchoBackend (no deps) — useful in CI and for tests.
semantic-toponav eval-grounding \
    tests/fixtures/grounding/multi_floor_office.yaml \
    --llm-backend echo --describer-safety

# With a local Ollama model (no API key, no cloud) — the real-model
# path. Run `ollama serve` and `ollama pull qwen3.5` first. For a large
# model on CPU, raise the per-request timeout: `--llm-timeout 600`.
semantic-toponav eval-grounding \
    tests/fixtures/grounding/multi_floor_office.yaml \
    --llm-backend ollama --llm-model qwen3.5:latest --describer-safety \
    --out grounding_report.md

# With AnthropicBackend (requires the [llm] extra + ANTHROPIC_API_KEY).
semantic-toponav eval-grounding \
    tests/fixtures/grounding/multi_floor_office.yaml \
    --llm-backend anthropic --describer-safety \
    --out grounding_report.md
```

`--out` writes the markdown report to a file *in addition* to
stdout, so the same invocation feeds CI artifacts and an
interactive read at once.

## Python API

```python
from semantic_toponav.eval.grounding import (
    evaluate_describer_safety, evaluate_resolver,
    grounding_report_markdown, load_grounding_corpus,
    DescriberSafetyCase,
)
from semantic_toponav.llm.backends import EchoBackend

corpus = load_grounding_corpus(
    "tests/fixtures/grounding/multi_floor_office.yaml"
)
deterministic = evaluate_resolver(corpus, resolver_name="deterministic")
backend = EchoBackend()
llm = evaluate_resolver(
    corpus, resolver_name="echo", backend=backend
)
safety = evaluate_describer_safety(
    corpus.graph, backend,
    [
        DescriberSafetyCase(name="kitchen-to-lab",
                            path=["kitchen_1f", "corridor_1f", "lobby_1f", "lab_1f"]),
        DescriberSafetyCase(name="mid",
                            path=["kitchen_1f", "corridor_1f", "lobby_1f", "lab_1f"],
                            start_index=2),
        DescriberSafetyCase(name="situation",
                            path=["kitchen_1f", "corridor_1f", "lobby_1f", "lab_1f"],
                            start_index=2,
                            situation="running 5 minutes behind schedule"),
    ],
    backend_name="echo",
)
print(grounding_report_markdown([deterministic, llm], safety_eval=safety))
```

## Reference numbers

Running the corpus shipped with the repo against the deterministic
resolver:

```
| resolver      | n   | precision@1 | recall@3 | recall@5 | clarify | fp_resolve | abstain |
| deterministic | 100 | 1.00        | 1.00     | 1.00     | 0.00    | 0.19       | 0.81    |
```

A committed full sample including the EchoBackend row + describer
safety invariants lives at
[`docs/grounding_report_sample.md`](grounding_report_sample.md) —
regenerated manually as part of release prep, with a provenance
header noting the commit it came from.

Reading: bag-of-words + floor parsing handles every *answerable*
query in the fixture (precision@1 = 1.0) — the 22 → 50 → 100
expansions widened the linguistic surface (ordinal/word/abbreviated
floor mentions, single-token labels, label fragments, comma-separated
and verb-phrase forms, bare-type queries) without dropping the
precision ceiling. The resolver still leaks three out of sixteen
*unresolvable* queries as false positives (`server room`,
`secret room`, `break room` — all pulled in by the `'room'` token
matching `meeting_room_2f`'s label). That's the
`abstention` axis the LLM-augmented resolver hardens: a **real local
model** (`--llm-backend ollama`, `qwen3.5`, no API key) cuts
`fp_resolve` from 0.19 to **0.06** (it rejects 15 of 16 unresolvable
queries) and lifts `abstain` to 0.94 while keeping `precision@1` at
1.00 — the contribution measured, not asserted (committed numbers in
[`grounding_report_sample.md`](grounding_report_sample.md)).
The ambiguous-case `clarify` rate is `0.00` for the deterministic
floor by construction; switching to `--llm-backend echo` lifts it to
0.94 (17/18) because `llm_resolve_goal` then checks the top-1/top-2
gap against `--ambiguity-threshold` and raises `ClarificationQuestion`
when the gap is below it. The one non-clarified ambiguous case is
`"a room"`, where `meeting_room_2f`'s label-match opens a top-1/top-2
gap wider than the default threshold.

## Visual grounding (image → node)

The same measurement substrate has a **perception twin** for
`localize_by_image`: instead of *language → node*, it scores
*image → node*. This is node-level Visual Place Recognition — the
standard VPR `recall@K` protocol — phrased with the same
`precise` / `unresolvable` corpus kinds so the language and visual
arms report symmetric numbers.

A visual corpus carries a **gallery** (node → reference frame; the
"map" stamped offline) plus **cases** (query frame → gold node):

```yaml
# graph: optional — synthesised as a nodes-only graph from the gallery
gallery:
  - {node: bay, image: depot_views/proto_bay.jpg}
  - {node: drum, image: depot_views/proto_drum.jpg}
cases:
  - {image: depot_views/proto_bay.jpg, gold: bay, kind: precise}
  - {image: depot_views/frame00.jpg, gold: null, kind: unresolvable}
```

`evaluate_visual_localizer` stamps the gallery with the encoder under
test, localizes each query, and reports `precision@1`, `recall@3/5`,
and — for `unresolvable` frames (a place not in the gallery) — the
split between **abstention** and **false-positive resolve**, gated by
`--min-score` on the top-1 cosine. The encoder must be the *same
identity* for gallery and queries.

CLI:

```bash
# Deterministic, torch-free (HashingBackend) — runs in CI.
semantic-toponav eval-visual-grounding \
    tests/fixtures/grounding/visual_depot.yaml --backend hashing --min-score 0.5

# Real semantic grounding (needs the [vlm] extra + CLIP weights).
semantic-toponav eval-visual-grounding corpus.yaml --backend clip --min-score 0.2
```

The shipped `visual_depot.yaml` fixture is designed for deterministic
CI: precise cases reuse the gallery frame (byte-identical → cosine
~1.0 under `HashingBackend`), and unresolvable drive frames stay below
the gate. So the reference numbers below validate the *metric
machinery*, not CLIP's real recall:

```
| encoder         | n | precise | unresolvable | min_score | precision@1 | recall@3 | recall@5 | fp_resolve | abstain |
| hashing(dim=64) | 7 | 5       | 2            | 0.50      | 1.00        | 1.00     | 1.00     | 0.00       | 1.00    |
```

For real `recall@K`, point the cases at distinct on-route frames and run
`--backend clip`. That corpus ships as
[`tests/fixtures/grounding/visual_depot_drive.yaml`](../tests/fixtures/grounding/visual_depot_drive.yaml)
(the `frame*.jpg` drive sequence labelled by `route_meta.json`), and a
committed real-CLIP snapshot lives at
[`docs/visual_grounding_report_sample.md`](visual_grounding_report_sample.md):
on this five-place benchmark `openai/clip-vit-base-patch32` grounds every
drive frame at **precision@1 = recall@3 = recall@5 = 1.00**. Those
numbers are a **manual** artifact — the `[vlm]` extra (torch + weights)
is out of CI by design — while the metric machinery is still covered
deterministically by `tests/test_eval_visual_grounding.py` under
`HashingBackend`. See [`related_work.md`](related_work.md) for how this
sits next to AnyLoc, VPR-Bench, and the gmberton benchmark.

### Neighbor-aware re-ranking (`--neighbor-weight` / `--neighbor-hops`)

`eval-visual-grounding` forwards `--neighbor-weight` / `--neighbor-hops`
to `localize_by_image`, so the RoboHop-style graph-context re-rank can be
measured *in aggregate*, not just per case. Each candidate's cosine is
blended with its scored graph neighbors before ranking, damping an
isolated perceptual-aliasing spike — a true place is corroborated by its
surroundings, a look-alike usually is not.

The five-place Depot corpus is too easy to move the aggregate numbers
when this is toggled (CLIP already separates the places), so the lift is
demonstrated deterministically on an engineered aliasing corpus built by
`semantic_toponav.eval.aliasing_visual_corpus`. There, raw cosine is
fooled on every case and neighbor aggregation recovers all of them —
**precision@1 / recall@3 / recall@5 go 0.00 → 1.00**, reproduced in CI by
`tests/test_visual_benchmark.py` and printable via
`examples/visual_neighbor_ablation_demo.py`. See
[`docs/visual_grounding_report_sample.md`](visual_grounding_report_sample.md#neighbor-aware-re-ranking--aggregate-ablation-deterministic-in-ci)
for the ablation table.
