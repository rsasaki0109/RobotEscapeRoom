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
— 22 cases across all three kinds.

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
| resolver      | n  | precision@1 | recall@3 | recall@5 | clarify | fp_resolve | abstain |
| deterministic | 22 | 1.00        | 1.00     | 1.00     | 0.00    | 0.20       | 0.80    |
```

Reading: bag-of-words + floor parsing handles every *answerable*
query in the fixture (precision@1 = 1.0) but resolves one out of
five *unresolvable* queries as a false positive — that's the
`abstention` axis the LLM-augmented resolver is supposed to harden.
The ambiguous-case `clarify` rate is `0.00` for the deterministic
floor by construction; switching to `--llm-backend echo` lifts it
because `llm_resolve_goal` then checks the top-1/top-2 gap against
`--ambiguity-threshold` and raises `ClarificationQuestion` when the
gap is below it.
