"""Aggregate evidence that neighbor-aware re-ranking lifts the numbers.

The per-case effect is covered in ``test_visual_localization.py`` on a
hand-built aliasing graph. These tests assert the *aggregate* claim the
Depot benchmark is too easy to show: on a deterministic, engineered
aliasing corpus, turning ``neighbor_weight`` on moves precision@1 /
recall@K from the floor to 1.00 — the gap closed for §26′ of plan.md.
"""

from __future__ import annotations

import pytest

from semantic_toponav.eval.grounding import evaluate_visual_localizer
from semantic_toponav.eval.visual_benchmark import (
    VectorTableBackend,
    aliasing_visual_corpus,
    neighbor_rerank_ablation,
    neighbor_rerank_ablation_markdown,
)


def test_raw_cosine_is_fooled_by_aliases() -> None:
    # With five distractors the genuine place falls past rank 5, so every
    # raw single-frame metric bottoms out.
    corpus, backend = aliasing_visual_corpus(n_clusters=8, n_distractors=5)
    ev = evaluate_visual_localizer(corpus, backend, neighbor_weight=0.0)
    assert ev.metrics.n_total == 8
    assert ev.metrics.precision_at_1 == 0.0
    assert ev.metrics.recall_at_3 == 0.0
    assert ev.metrics.recall_at_5 == 0.0


def test_neighbor_rerank_recovers_every_case() -> None:
    corpus, backend = aliasing_visual_corpus(n_clusters=8, n_distractors=5)
    ev = evaluate_visual_localizer(
        corpus, backend, neighbor_weight=0.5, neighbor_hops=1
    )
    assert ev.metrics.precision_at_1 == 1.0
    assert ev.metrics.recall_at_3 == 1.0
    assert ev.metrics.recall_at_5 == 1.0
    # Every top-1 is the cluster's genuine place, not a look-alike.
    for o in ev.outcomes:
        assert o.top1 == o.case.gold[0]
        assert o.top1.startswith("true_")


def test_ablation_reports_the_lift() -> None:
    corpus, backend = aliasing_visual_corpus(n_clusters=6, n_distractors=5)
    ab = neighbor_rerank_ablation(
        corpus, backend, neighbor_weight=0.5, encoder_name="bench"
    )
    assert ab.baseline.metrics.precision_at_1 == 0.0
    assert ab.reranked.metrics.precision_at_1 == 1.0
    assert ab.neighbor_weight == 0.5
    assert ab.neighbor_hops == 1
    # The reranked run must strictly beat the baseline on the headline.
    assert ab.reranked.metrics.precision_at_1 > ab.baseline.metrics.precision_at_1


def test_ablation_markdown_shape() -> None:
    corpus, backend = aliasing_visual_corpus(n_clusters=4, n_distractors=5)
    ab = neighbor_rerank_ablation(corpus, backend)
    md = neighbor_rerank_ablation_markdown(ab)
    assert "Neighbor-aware re-ranking ablation" in md
    assert "precision@1" in md
    assert "raw cosine" in md
    assert "+neighbor" in md
    # One header row + two data rows mention the metric columns.
    assert md.count("|") >= 3 * 4


def test_scales_with_cluster_count() -> None:
    # The lift is structural, not tuned to one size.
    for n in (1, 3, 12):
        corpus, backend = aliasing_visual_corpus(n_clusters=n, n_distractors=5)
        assert len(corpus.cases) == n
        off = evaluate_visual_localizer(corpus, backend, neighbor_weight=0.0)
        on = evaluate_visual_localizer(corpus, backend, neighbor_weight=0.5)
        assert off.metrics.precision_at_1 == 0.0
        assert on.metrics.precision_at_1 == 1.0


def test_fewer_distractors_still_flip_precision_at_1() -> None:
    # Below five distractors recall@K may already be saturated, but the
    # alias still wins raw top-1 and re-ranking still recovers it.
    corpus, backend = aliasing_visual_corpus(n_clusters=5, n_distractors=2)
    off = evaluate_visual_localizer(corpus, backend, neighbor_weight=0.0)
    on = evaluate_visual_localizer(corpus, backend, neighbor_weight=0.5)
    assert off.metrics.precision_at_1 == 0.0
    assert on.metrics.precision_at_1 == 1.0


def test_corpus_is_deterministic() -> None:
    c1, b1 = aliasing_visual_corpus(n_clusters=4, n_distractors=3)
    c2, b2 = aliasing_visual_corpus(n_clusters=4, n_distractors=3)
    e1 = evaluate_visual_localizer(c1, b1, neighbor_weight=0.5)
    e2 = evaluate_visual_localizer(c2, b2, neighbor_weight=0.5)
    assert [o.top1 for o in e1.outcomes] == [o.top1 for o in e2.outcomes]
    assert e1.metrics.to_dict() == e2.metrics.to_dict()


def test_vector_table_backend_rejects_unknown_key() -> None:
    backend = VectorTableBackend({"a": [1.0, 0.0]}, dim=2)
    assert backend.embed_image("a") == [1.0, 0.0]
    assert backend.dim == 2
    with pytest.raises(KeyError):
        backend.embed_image("missing")


def test_vector_table_backend_validates_dim() -> None:
    with pytest.raises(ValueError):
        VectorTableBackend({}, dim=1)


def test_invalid_corpus_sizes_raise() -> None:
    with pytest.raises(ValueError):
        aliasing_visual_corpus(n_clusters=0)
    with pytest.raises(ValueError):
        aliasing_visual_corpus(n_distractors=0)
