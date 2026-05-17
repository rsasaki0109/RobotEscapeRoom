# Grounding eval — committed sample report

A static snapshot of `eval-grounding` output, committed so reviewers
and paper-writers can see the numbers without firing up a Python
environment. See [`docs/eval_grounding.md`](eval_grounding.md) for
the metric definitions and corpus format.

## Provenance

```text
git ref:    feat/grounding-corpus-expansion @ 16be17bad650
generated:  2026-05-17
corpus:     tests/fixtures/grounding/multi_floor_office.yaml  (50 cases)
command:    semantic-toponav eval-grounding \
              tests/fixtures/grounding/multi_floor_office.yaml \
              --llm-backend echo --describer-safety
```

Regenerate by running the same command from a checkout at the same
commit. Numbers drift only if the deterministic resolver, the
describer, or the gold corpus changes — all three are exercised by
`tests/test_eval_grounding.py` so any drift fails CI before it lands
here.

## Resolver grounding

| resolver | n | precise | ambiguous | unresolvable | precision@1 | recall@3 | recall@5 | clarify | fp_resolve | abstain |
|---|---|---|---|---|---|---|---|---|---|---|
| deterministic | 50 | 33 | 9 | 8 | 1.00 | 1.00 | 1.00 | 0.00 | 0.25 | 0.75 |
| echo | 50 | 33 | 9 | 8 | 1.00 | 1.00 | 1.00 | 0.89 | 0.25 | 0.75 |

### How to read these numbers

- **`precision@1`, `recall@3`, `recall@5`** are denominated against
  the *answerable* cases (precise + ambiguous = 42). Both resolvers
  hit 1.00: every answerable query lands its gold target in the
  top-1 slot. The bag-of-words + floor parser handles every
  linguistic pattern in the corpus — prefix/postfix/ordinal/word/
  abbreviated floor mentions, single-token labels, label fragments,
  and bare-type queries — without surprise. The corpus expansion
  (22 → 50 cases in PR #69) widened the linguistic surface; the
  ceiling held.
- **`clarify`** is denominated against the *ambiguous* slice (9
  cases). The deterministic resolver never raises a
  `ClarificationQuestion` on its own (`resolve_goal` just returns a
  ranked list), so its `clarify_rate` is 0 by construction. The
  `echo` resolver lifts the rate to 0.89 = 8/9: every ambiguous
  case *except one* has a small enough deterministic top-1/top-2
  gap to fire `llm_resolve_goal`'s `ambiguity_threshold` check.
  The exception is `"a room"`, where the label-match on
  `meeting_room_2f` (+2) plus its type-match (+1) puts top-1 a full
  point above the type-only candidates — wider than the default
  gap threshold, so no clarification is raised even though the
  user intent ranges over all six rooms.
- **`fp_resolve`** and **`abstain`** are denominated against the
  *unresolvable* slice (8 cases) and sum to 1.0 by construction.
  Both resolvers leak two out of eight unresolvable queries
  (`fp_resolve = 0.25`):
  - `"server room"` false-positives to `meeting_room_2f` via the
    `'room'` label token.
  - `"secret room"` does the same — `'secret'` has no anchor in any
    label, but the `'room'` token still pulls `meeting_room_2f` to
    the top.
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
- A real-backend run (`--llm-backend anthropic`) will have
  `fallback_rate << 1.00` and the other four invariants become
  *load-bearing* signals: they measure whether the LLM actually
  preserved references, preserved step indices, respected the
  mid-traversal prefix, and reacted to the situation hint. Those
  numbers are an explicit open hole — see `paper_outline.md` §7.

## Notes

- This snapshot is regenerated manually as part of release prep, not
  by CI. Auto-regeneration would either invite churn (every PR
  touching the resolver re-writes the file) or hide a regression
  behind a green build. The unit tests in `tests/test_eval_grounding.py`
  catch any drift at the assertion level; this file's purpose is
  publishing the numbers, not protecting them.
- A real-backend version of this report (with
  `--llm-backend anthropic`) is intentionally not committed: it
  would require shipping API credentials in CI or accepting a
  per-PR cost. The path to producing it locally is the same
  command above with `--llm-backend anthropic`.
