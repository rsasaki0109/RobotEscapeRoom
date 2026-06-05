"""Tests for the visual-grounding eval arm (image -> node).

Runs entirely on the deterministic HashingBackend, so no torch / CLIP is
needed. The bundled fixture reuses the gallery frames as precise queries
(byte-identical -> cosine ~1.0) and off-gallery drive frames as
unresolvable queries (weak top-1 -> abstain under min_score=0.5).
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from semantic_toponav.encoders.backends import HashingBackend
from semantic_toponav.eval.grounding import (
    VisualGroundingCorpus,
    evaluate_visual_localizer,
    load_visual_grounding_corpus,
    visual_grounding_report_markdown,
)

FIXTURE = Path(__file__).parent / "fixtures" / "grounding" / "visual_depot.yaml"


def test_loads_corpus_and_synthesises_graph() -> None:
    corpus = load_visual_grounding_corpus(FIXTURE)
    assert isinstance(corpus, VisualGroundingCorpus)
    assert set(corpus.gallery) == {"bay", "brick", "drum", "crate", "util"}
    # No `graph:` key -> nodes-only graph synthesised from the gallery.
    assert {n.id for n in corpus.graph.nodes()} == set(corpus.gallery)
    # Image paths resolved to absolute and exist.
    assert all(Path(p).is_absolute() and Path(p).exists() for p in corpus.gallery.values())
    assert len(corpus.cases) == 7


def test_evaluate_visual_localizer_metrics() -> None:
    corpus = load_visual_grounding_corpus(FIXTURE)
    backend = HashingBackend(dim=64)
    ev = evaluate_visual_localizer(
        corpus, backend, encoder_name="hashing", top_k=5, min_score=0.5
    )
    m = ev.metrics
    assert (m.n_precise, m.n_ambiguous, m.n_unresolvable) == (5, 0, 2)
    assert math.isclose(m.precision_at_1, 1.0)
    assert math.isclose(m.recall_at_3, 1.0)
    assert math.isclose(m.recall_at_5, 1.0)
    # Off-gallery frames stay below the gate -> all abstain, none resolve.
    assert math.isclose(m.abstention_rate, 1.0)
    assert math.isclose(m.false_positive_resolve_rate, 0.0)


def test_precise_cases_self_localize() -> None:
    corpus = load_visual_grounding_corpus(FIXTURE)
    ev = evaluate_visual_localizer(corpus, HashingBackend(dim=64))
    precise = [o for o in ev.outcomes if o.case.kind == "precise"]
    assert all(o.correct_at_1 for o in precise)
    assert all(math.isclose(o.top1_score, 1.0, abs_tol=1e-9) for o in precise)


def test_min_score_zero_counts_weak_top1_as_resolve() -> None:
    # With no abstention gate, every unresolvable frame's (weak) top-1
    # counts as a false-positive resolve.
    corpus = load_visual_grounding_corpus(FIXTURE)
    ev = evaluate_visual_localizer(corpus, HashingBackend(dim=64), min_score=0.0)
    assert math.isclose(ev.metrics.false_positive_resolve_rate, 1.0)
    assert math.isclose(ev.metrics.abstention_rate, 0.0)


def test_report_markdown_has_table() -> None:
    corpus = load_visual_grounding_corpus(FIXTURE)
    ev = evaluate_visual_localizer(corpus, HashingBackend(dim=64), encoder_name="hashing")
    md = visual_grounding_report_markdown([ev])
    assert "Visual localization (image -> node)" in md
    assert "precision@1" in md and "abstain" in md
    assert "| hashing |" in md


def test_report_markdown_empty() -> None:
    md = visual_grounding_report_markdown([])
    assert "no visual evaluations" in md


def test_top_k_below_one_raises() -> None:
    corpus = load_visual_grounding_corpus(FIXTURE)
    with pytest.raises(ValueError):
        evaluate_visual_localizer(corpus, HashingBackend(dim=64), top_k=0)


def test_loader_rejects_missing_gallery(tmp_path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("cases: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="gallery"):
        load_visual_grounding_corpus(bad)


def test_loader_rejects_gold_not_in_gallery(tmp_path) -> None:
    bad = tmp_path / "bad.yaml"
    img = FIXTURE.parent.parent.parent.parent / "examples/data/depot_views/proto_bay.jpg"
    bad.write_text(
        "gallery:\n"
        f"  - {{node: bay, image: {img}}}\n"
        "cases:\n"
        f"  - {{image: {img}, gold: nowhere, kind: precise}}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not a graph node"):
        load_visual_grounding_corpus(bad)


def test_loader_rejects_unresolvable_with_gold(tmp_path) -> None:
    bad = tmp_path / "bad.yaml"
    img = FIXTURE.parent.parent.parent.parent / "examples/data/depot_views/proto_bay.jpg"
    bad.write_text(
        "gallery:\n"
        f"  - {{node: bay, image: {img}}}\n"
        "cases:\n"
        f"  - {{image: {img}, gold: bay, kind: unresolvable}}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unresolvable"):
        load_visual_grounding_corpus(bad)
