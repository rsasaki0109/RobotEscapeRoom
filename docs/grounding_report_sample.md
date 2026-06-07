# Grounding eval — committed sample report

A static snapshot of `eval-grounding` output, committed so reviewers
and paper-writers can see the numbers without firing up a Python
environment. See [`docs/eval_grounding.md`](eval_grounding.md) for
the metric definitions and corpus format.

## Provenance

```text
git ref:    feat/ollama-backend (100-case corpus + local-model run)
generated:  2026-06-07
corpus:     tests/fixtures/grounding/multi_floor_office.yaml  (100 cases)
echo run:   semantic-toponav eval-grounding \
              tests/fixtures/grounding/multi_floor_office.yaml \
              --llm-backend echo --describer-safety
ollama run: semantic-toponav eval-grounding \
              tests/fixtures/grounding/multi_floor_office.yaml \
              --llm-backend ollama --llm-model qwen3.5:latest --describer-safety
```

Regenerate by running the same command from a checkout at the same
commit. Numbers drift only if the deterministic resolver, the
describer, or the gold corpus changes — all three are exercised by
`tests/test_eval_grounding.py` so any drift fails CI before it lands
here.

## Resolver grounding

| resolver | n | precise | ambiguous | unresolvable | precision@1 | recall@3 | recall@5 | clarify | fp_resolve | abstain |
|---|---|---|---|---|---|---|---|---|---|---|
| deterministic | 100 | 66 | 18 | 16 | 1.00 | 1.00 | 1.00 | 0.00 | 0.19 | 0.81 |
| echo | 100 | 66 | 18 | 16 | 1.00 | 1.00 | 1.00 | 0.94 | 0.19 | 0.81 |
| ollama (qwen3.5) | 100 | 66 | 18 | 16 | 1.00 | 1.00 | 1.00 | 0.94 | **0.06** | **0.94** |

### How to read these numbers

- **`precision@1`, `recall@3`, `recall@5`** are denominated against
  the *answerable* cases (precise + ambiguous = 84). Both resolvers
  hit 1.00: every answerable query lands its gold target in the
  top-1 slot. The bag-of-words + floor parser handles every
  linguistic pattern in the corpus — prefix/postfix/ordinal/word/
  abbreviated floor mentions, single-token labels, label fragments,
  comma-separated and verb-phrase forms, and bare-type queries —
  without surprise. The corpus expansions (22 → 50 → 100 cases)
  widened the linguistic surface; the ceiling held at every size.
- **`clarify`** is denominated against the *ambiguous* slice (18
  cases). The deterministic resolver never raises a
  `ClarificationQuestion` on its own (`resolve_goal` just returns a
  ranked list), so its `clarify_rate` is 0 by construction. The
  `echo` resolver lifts the rate to 0.94 = 17/18: every ambiguous
  case *except one* has a small enough deterministic top-1/top-2
  gap to fire `llm_resolve_goal`'s `ambiguity_threshold` check.
  The exception is `"a room"`, where the label-match on
  `meeting_room_2f` (+2) plus its type-match (+1) puts top-1 a full
  point above the type-only candidates — wider than the default
  gap threshold, so no clarification is raised even though the
  user intent ranges over all six rooms.
- **`fp_resolve`** and **`abstain`** are denominated against the
  *unresolvable* slice (16 cases) and sum to 1.0 by construction.
  Both resolvers leak three out of sixteen unresolvable queries
  (`fp_resolve = 0.19`) — `"server room"`, `"secret room"` and
  `"break room"`: in each, the leading token has no anchor in any
  label, but the trailing `'room'` token still pulls
  `meeting_room_2f` to the top.
  That's exactly the abstention axis the LLM-augmented path on a
  real cloud backend (`--llm-backend anthropic`) is expected to
  harden — recorded as open hole §3 in
  [`paper_outline.md`](paper_outline.md).

The `echo` numbers are *machinery-level*: `EchoBackend` falls back to
its `[echo] last_prompt_line` echo when no script is supplied, and
`_llm_pick_from_response` can't parse that. The pipeline correctly
falls back to the deterministic ranking, so the *grounded* metrics
(precision@1 / recall@k / fp_resolve / abstain) are identical to the
deterministic row. What changes is `clarify`, which fires from the
top-1/top-2 gap check independent of the LLM reply.

### The real-model row (Ollama, no API key)

The `ollama` row is a **real local model** (`qwen3.5:latest` via a
locally-run Ollama server — no API key, no cloud) and is where the
LLM-augmented path actually earns its keep. It holds `precision@1 =
recall@3 = recall@5 = 1.00` (no regression on answerable queries) while
cutting the **false-positive resolve rate from 0.19 to 0.06** — the model
correctly rejects 15 of the 16 unresolvable queries instead of letting
the `'room'` token drag `meeting_room_2f` to the top, lifting `abstain`
from 0.81 to 0.94. That is exactly the abstention axis the deterministic
floor cannot cover and the contribution Chapter 3 claims for the
LLM-augmented resolver — now measured against a real model rather than
asserted. Numbers are from a single local run at `temperature = 0`;
local sampling is not bit-exact across builds, so treat them as one run,
not a CI-pinned fixture (the metric machinery itself is pinned in
`tests/test_eval_grounding.py`).

## Describer rewrite safety

Backend: `echo`, n = 6 probes (full-plan + mid-traversal + situation
variants on two representative paths in the multi-floor office
graph).

| invariant | pass rate |
|---|---|
| `references_preserved` | 1.00 |
| `step_indices_preserved` | 1.00 |
| `prior_steps_untouched` | 1.00 |
| `situation_changes_output` | 1.00 |
| `all_invariants` | 1.00 |
| `fallback_rate` | 1.00 |

### How to read these numbers

- `fallback_rate = 1.00` because `EchoBackend` with no script
  cannot return a parseable `N. <text>` reply, so every rewrite
  falls back to the deterministic floor verbatim. Fallback rewrites
  pass invariants 1–3 trivially (the deterministic floor is already
  grounded and well-indexed). The `situation_changes_output`
  invariant inspects the *prompt* the backend received rather than
  the rewritten text, so it still measures whether the `situation=`
  kwarg flowed through the prompt builder.
- A real-backend run lifts `fallback_rate` off 1.00 and makes the
  other four invariants *load-bearing*: they measure whether the LLM
  actually preserved references, preserved step indices, respected the
  mid-traversal prefix, and reacted to the situation hint — see the
  real-model run below.

### Real-model run (Ollama `qwen3.5:latest`, no API key)

Backend: `ollama`, n = 6 probes, same paths.

| invariant | pass rate |
|---|---|
| `references_preserved` | 1.00 |
| `step_indices_preserved` | 1.00 |
| `prior_steps_untouched` | 1.00 |
| `situation_changes_output` | 1.00 |
| `all_invariants` | 1.00 |
| `fallback_rate` | **0.00** |

`fallback_rate = 0.00` means every rewrite came from the model itself
(no probe fell back to the deterministic floor), so the four invariants
are now **load-bearing** rather than trivially satisfied — and the local
model holds all of them at 1.00. That is the "safe by construction"
claim of Chapter 4, validated against a real model: the LLM rewrites the
plan into prose while preserving every node reference, the step
indexing, the untouched mid-traversal prefix, and reacting to the
`situation=` hint. Single local run at `temperature = 0`; not a
CI-pinned fixture.

## Notes

- This snapshot is regenerated manually as part of release prep, not
  by CI. Auto-regeneration would either invite churn (every PR
  touching the resolver re-writes the file) or hide a regression
  behind a green build. The unit tests in `tests/test_eval_grounding.py`
  catch any drift at the assertion level; this file's purpose is
  publishing the numbers, not protecting them.
- The real-model rows here come from a **local** Ollama model
  (`--llm-backend ollama`), so they need no API credentials and no
  per-PR cloud cost — reproduce them by running `ollama serve`,
  `ollama pull qwen3.5`, and the `ollama run` command above. A cloud
  `--llm-backend anthropic` run would land in the same tables; it is
  intentionally not committed (it would require credentials or a
  per-PR cost), but the local model already fills the real-backend
  numbers Chapters 3 and 4 needed.
