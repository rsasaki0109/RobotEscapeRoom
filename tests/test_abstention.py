"""Abstention-taxonomy benchmark tests.

Exercises `run_abstention_benchmark` on the committed taxonomy corpus over
the multi-floor office graph. The deterministic resolver is fully
reproducible, so the per-category rates are asserted exactly — they encode
the headline finding: the bag-of-words floor leaks on `out_of_map` /
`false_premise` exactly where a stray token (`room`, `kitchen`) pulls a
candidate up. See :mod:`semantic_toponav.eval.abstention`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from semantic_toponav.eval.abstention import (
    AbstentionReport,
    abstention_comparison_markdown,
    abstention_report_markdown,
    load_abstention_corpus,
    load_abstention_transcript,
    run_abstention_benchmark,
)
from semantic_toponav.graph.serialization import load_graph

ROOT = Path(__file__).resolve().parents[1]
GRAPH = str(ROOT / "examples" / "multi_floor_office.yaml")
CORPUS = str(ROOT / "tests" / "fixtures" / "grounding" / "abstention_taxonomy.yaml")
TRANSCRIPT = str(
    ROOT / "tests" / "fixtures" / "grounding" / "abstention_llm_transcript.yaml"
)


@pytest.fixture
def report() -> AbstentionReport:
    graph = load_graph(GRAPH)
    cases = load_abstention_corpus(CORPUS)
    return run_abstention_benchmark(graph, cases)


@pytest.fixture
def llm_report() -> AbstentionReport:
    graph = load_graph(GRAPH)
    cases = load_abstention_corpus(CORPUS)
    backend = load_abstention_transcript(TRANSCRIPT)
    return run_abstention_benchmark(graph, cases, backend=backend)


def test_corpus_has_all_four_categories() -> None:
    cases = load_abstention_corpus(CORPUS)
    cats = {c.category for c in cases}
    assert cats == {"answerable", "unresolvable", "false_premise", "out_of_map"}
    assert len(cases) == 24


def test_answerable_never_abstains(report: AbstentionReport) -> None:
    m = report.by_category["answerable"]
    assert m.abstain_rate == 0.0  # the control: every real place resolves


def test_unresolvable_always_abstains(report: AbstentionReport) -> None:
    m = report.by_category["unresolvable"]
    assert m.abstain_rate == 1.0
    assert m.false_positive_resolve_rate == 0.0


def test_token_leak_categories_show_false_positives(report: AbstentionReport) -> None:
    # The deterministic floor leaks where a stray token overlaps a real
    # label — this is the abstention axis the LLM path is meant to harden.
    fp = report.by_category["false_premise"].false_positive_resolve_rate
    om = report.by_category["out_of_map"].false_positive_resolve_rate
    assert fp == pytest.approx(1 / 6, abs=1e-6)   # "basement kitchen"
    assert om == pytest.approx(2 / 6, abs=1e-6)   # "server room", "break room"


def test_specific_leaks_are_the_token_overlaps(report: AbstentionReport) -> None:
    leaks = {
        o.case.query: o.top1
        for o in report.outcomes
        if o.case.category in ("false_premise", "out_of_map") and not o.abstained
    }
    assert leaks == {
        "the basement kitchen": "kitchen_1f",
        "the server room": "meeting_room_2f",
        "the break room": "meeting_room_2f",
    }


def test_markdown_lists_categories_and_leaks(report: AbstentionReport) -> None:
    md = abstention_report_markdown(report)
    assert "| `out_of_map` |" in md
    assert "False-positive resolves" in md
    assert "the server room" in md


def test_unknown_category_rejected(tmp_path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("cases:\n  - {query: x, category: bogus}\n")
    with pytest.raises(ValueError, match="category must be one of"):
        load_abstention_corpus(bad)


# --- LLM-augmented path: the abstention-aware prompt closes the leaks ------


def test_llm_path_closes_token_leaks(llm_report: AbstentionReport) -> None:
    # Every should-abstain category drops to zero false-positive resolves
    # once the model is allowed to decline; answerable stays fully resolved.
    assert llm_report.by_category["answerable"].abstain_rate == 0.0
    for cat in ("unresolvable", "false_premise", "out_of_map"):
        assert llm_report.by_category[cat].false_positive_resolve_rate == 0.0
        assert llm_report.by_category[cat].abstain_rate == 1.0


def test_llm_path_abstains_on_the_exact_leak_queries(
    llm_report: AbstentionReport,
) -> None:
    # The three queries the deterministic floor wrongly resolved now abstain.
    abstained = {o.case.query for o in llm_report.outcomes if o.abstained}
    assert {
        "the basement kitchen",
        "the server room",
        "the break room",
    } <= abstained


def test_transcript_backend_only_called_on_nonempty_pools() -> None:
    # The empty-pool cases short-circuit to abstention without the backend;
    # only the 9 non-empty-pool queries reach the transcript.
    graph = load_graph(GRAPH)
    cases = load_abstention_corpus(CORPUS)
    backend = load_abstention_transcript(TRANSCRIPT)
    run_abstention_benchmark(graph, cases, backend=backend)
    assert len(backend.calls) == 9


def test_transcript_drift_fails_loudly(tmp_path) -> None:
    # A transcript missing a non-empty-pool query must raise, not echo.
    graph = load_graph(GRAPH)
    cases = load_abstention_corpus(CORPUS)
    thin = tmp_path / "thin.yaml"
    thin.write_text("responses:\n  \"the kitchen\": \"Top match: kitchen_1f\"\n")
    backend = load_abstention_transcript(thin)
    with pytest.raises(KeyError, match="no recorded reply"):
        run_abstention_benchmark(graph, cases, backend=backend)


def test_comparison_markdown_shows_before_after(
    report: AbstentionReport, llm_report: AbstentionReport
) -> None:
    md = abstention_comparison_markdown(report, llm_report)
    assert "fp_resolve (deterministic)" in md
    assert "fp_resolve (LLM)" in md
    assert "Leaks closed by the LLM path" in md
    # The out_of_map row carries deterministic 0.33 → LLM 0.00.
    assert "| `out_of_map` | 6 | 0.33 | 0.00 |" in md
    for q in ("the basement kitchen", "the server room", "the break room"):
        assert q in md
