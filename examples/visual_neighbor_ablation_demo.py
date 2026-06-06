"""Neighbor-aware re-ranking, measured in aggregate.

The text-free, torch-free companion to ``visual_localization_demo.py``.
That demo *shows* one robot grounding its camera against a gallery; this
one *measures* the value of the graph-context re-ranking knob
(``neighbor_weight`` / ``neighbor_hops``, PRs #77 / #79) over a whole map
at once.

Real-image benchmarks like the Depot drive are too small and too easy to
move the aggregate numbers, so the effect was previously only visible in
per-case unit tests. Here a deterministic, engineered aliasing corpus
(:func:`semantic_toponav.eval.aliasing_visual_corpus`) makes the lift
unmistakable: every genuine place has a higher-scoring look-alike
elsewhere in the building, so raw single-frame cosine is fooled on every
case — until neighbor aggregation lets each place's graph surroundings
vouch for it.

Run (no extras needed — pure Python, no torch)::

    python examples/visual_neighbor_ablation_demo.py
"""

from __future__ import annotations

from semantic_toponav.eval import (
    aliasing_visual_corpus,
    neighbor_rerank_ablation,
    neighbor_rerank_ablation_markdown,
)


def main() -> None:
    corpus, backend = aliasing_visual_corpus(n_clusters=8, n_distractors=5)
    print(
        f"corpus: {len(corpus.cases)} places, each with a look-alike "
        f"elsewhere in the map (embedding dim {backend.dim})\n"
    )

    ablation = neighbor_rerank_ablation(
        corpus, backend,
        neighbor_weight=0.5, neighbor_hops=1,
        encoder_name="aliasing-bench",
    )
    print(neighbor_rerank_ablation_markdown(ablation))

    b, r = ablation.baseline.metrics, ablation.reranked.metrics
    print(
        "Raw cosine is fooled on every case "
        f"(precision@1 {b.precision_at_1:.2f}); blending each candidate with "
        f"its graph neighbors recovers all of them "
        f"(precision@1 {r.precision_at_1:.2f})."
    )


if __name__ == "__main__":
    main()
