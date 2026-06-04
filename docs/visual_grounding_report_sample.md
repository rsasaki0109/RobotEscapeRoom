# Visual grounding eval — committed sample report

A static snapshot of `eval-visual-grounding` run against **real CLIP**,
committed so reviewers and paper-writers can see the image→node numbers
without installing the `[vlm]` extra or downloading model weights. See
[`docs/eval_grounding.md`](eval_grounding.md#visual-grounding-image--node)
for the metric definitions and corpus format, and
[`docs/related_work.md`](related_work.md) for how this sits next to the
VPR benchmarks (AnyLoc / VPR-Bench / gmberton).

## Provenance

```text
git ref:    fix/clip-transformers5 @ 248b60b  (CLIPBackend transformers>=5 fix)
generated:  2026-06-05
encoder:    openai/clip-vit-base-patch32  (torch 2.12.0+cpu, transformers 5.10.2)
corpus:     tests/fixtures/grounding/visual_depot_drive.yaml  (16 drive frames)
command:    semantic-toponav eval-visual-grounding \
              tests/fixtures/grounding/visual_depot_drive.yaml --backend clip
```

This is a **manual release-prep artifact** — the `[vlm]` extra (torch +
CLIP weights) is intentionally out of CI, so these numbers are not
regenerated automatically. Regenerate by installing `.[vlm]` and running
the command above from a checkout at the same commit. The metric
machinery itself is exercised deterministically in CI by
`tests/test_eval_visual_grounding.py` (on the byte-identical
`visual_depot.yaml` fixture under `HashingBackend`).

## Visual localization (image → node)

The gallery stamps each place node with the embedding of one prototype
frame; the 16 **drive** frames (distinct photographs taken while moving
through each place — *not* the gallery frames) are then grounded back to
a node.

| encoder | n | precise | ambiguous | unresolvable | min_score | precision@1 | recall@3 | recall@5 | fp_resolve | abstain |
|---|---|---|---|---|---|---|---|---|---|---|
| openai/clip-vit-base-patch32 | 16 | 16 | 0 | 0 | 0.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.00 |

## How to read these numbers

- **precision@1 = 1.00** — every drive frame's top-1 node is the place
  it was taken in. CLIP's pretrained features separate the five Depot
  places cleanly enough that no held-out frame is mislabeled.
- **recall@3 = recall@5 = 1.00** — trivially implied by precision@1 here;
  they matter on harder corpora where the top-1 can miss but the right
  node is still in the shortlist.
- **no unresolvable cases** — this corpus has no out-of-map frames, so
  `min_score` / `fp_resolve` / `abstain` are inactive (all `0`). Add
  frames of a place absent from the gallery to exercise the abstention
  gate (see `visual_depot.yaml` for that pattern).
- **per-frame cosines** ranged 0.88–1.00 to the correct node, with a
  clear margin over the runner-up — the same fixes that drive the
  `examples/visual_navigation_demo.py` replay
  (`docs/images/24_visual_navigation.gif`).

This is a small, friendly five-place benchmark — the point is to show
the `localize_by_image` → `eval-visual-grounding` path works end-to-end
with a real encoder, not to claim a hard VPR result. Perceptual aliasing
(and the `neighbor_weight` / `neighbor_hops` re-rank that damps it) only
bites on larger, more self-similar maps.
