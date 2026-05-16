"""Tests for the language-grounding eval (semantic_toponav.eval.grounding)."""

from __future__ import annotations

from pathlib import Path

import pytest

from semantic_toponav.eval.grounding import (
    DescriberSafetyCase,
    GroundingCase,
    GroundingCorpus,
    evaluate_describer_safety,
    evaluate_resolver,
    grounding_report_markdown,
    load_grounding_corpus,
)
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode
from semantic_toponav.llm.backends import EchoBackend

CORPUS_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "grounding" / "multi_floor_office.yaml"
)


# ---------------------------------------------------------------------------
# Corpus loader
# ---------------------------------------------------------------------------


def test_load_grounding_corpus_smoke() -> None:
    corpus = load_grounding_corpus(CORPUS_PATH)
    assert isinstance(corpus, GroundingCorpus)
    assert corpus.graph_path.endswith("multi_floor_office.yaml")
    # The fixture has 50+ cases spanning all three kinds.
    assert len(corpus.cases) >= 50
    kinds = {c.kind for c in corpus.cases}
    assert kinds == {"precise", "ambiguous", "unresolvable"}


def _tiny_graph_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "g.yaml"
    p.write_text(
        "version: 1\n"
        "metadata: {}\n"
        "nodes:\n"
        "  - {id: a, label: A, type: room}\n"
        "  - {id: b, label: B, type: room}\n"
        "edges: []\n"
    )
    return p


def test_corpus_validates_kind_field(tmp_path: Path) -> None:
    graph_path = _tiny_graph_yaml(tmp_path)
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        f"graph: {graph_path.name}\n"
        "cases:\n"
        "  - {query: foo, gold: a, kind: badkind}\n"
    )
    with pytest.raises(ValueError, match="kind"):
        load_grounding_corpus(bad)


def test_corpus_validates_precise_requires_one_gold(tmp_path: Path) -> None:
    graph_path = tmp_path / "g.yaml"
    graph_path.write_text(
        "version: 1\n"
        "metadata: {}\n"
        "nodes:\n"
        "  - {id: a, label: A, type: room}\n"
        "  - {id: b, label: B, type: room}\n"
        "edges: []\n"
    )
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        f"graph: {graph_path.name}\n"
        "cases:\n"
        "  - {query: foo, gold: [a, b], kind: precise}\n"
    )
    with pytest.raises(ValueError, match="precise"):
        load_grounding_corpus(bad)


def test_corpus_validates_gold_id_in_graph(tmp_path: Path) -> None:
    graph_path = tmp_path / "g.yaml"
    graph_path.write_text(
        "version: 1\n"
        "metadata: {}\n"
        "nodes:\n"
        "  - {id: a, label: A, type: room}\n"
        "edges: []\n"
    )
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        f"graph: {graph_path.name}\n"
        "cases:\n"
        "  - {query: foo, gold: nonexistent, kind: precise}\n"
    )
    with pytest.raises(ValueError, match="not a node"):
        load_grounding_corpus(bad)


def test_corpus_validates_unresolvable_has_no_gold(tmp_path: Path) -> None:
    graph_path = tmp_path / "g.yaml"
    graph_path.write_text(
        "version: 1\n"
        "metadata: {}\n"
        "nodes:\n"
        "  - {id: a, label: A, type: room}\n"
        "edges: []\n"
    )
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        f"graph: {graph_path.name}\n"
        "cases:\n"
        "  - {query: foo, gold: a, kind: unresolvable}\n"
    )
    with pytest.raises(ValueError, match="unresolvable"):
        load_grounding_corpus(bad)


# ---------------------------------------------------------------------------
# Deterministic resolver evaluation
# ---------------------------------------------------------------------------


def test_evaluate_resolver_deterministic_reports_metrics() -> None:
    corpus = load_grounding_corpus(CORPUS_PATH)
    ev = evaluate_resolver(corpus, resolver_name="deterministic")
    assert ev.resolver_name == "deterministic"
    assert ev.metrics.n_total == len(corpus.cases)
    # The deterministic resolver is decent at the precise queries
    # (label/floor matches), so precision@1 should be well above zero.
    assert ev.metrics.precision_at_1 > 0.5
    # Recall@5 must be at least recall@3.
    assert ev.metrics.recall_at_5 >= ev.metrics.recall_at_3
    # The deterministic resolver never emits a ClarificationQuestion
    # on its own, so clarification_rate is 0 by construction.
    assert ev.metrics.clarification_rate == 0.0


def test_evaluate_resolver_unresolvable_split_makes_sense() -> None:
    """For the unresolvable slice, fp_resolve + abstention should
    together account for every case (no double-counting)."""
    corpus = load_grounding_corpus(CORPUS_PATH)
    ev = evaluate_resolver(corpus, resolver_name="deterministic")
    # Float rounding tolerance.
    assert (
        ev.metrics.false_positive_resolve_rate
        + ev.metrics.abstention_rate
        == pytest.approx(1.0, abs=1e-9)
    )


def test_evaluate_resolver_outcomes_match_cases_in_order() -> None:
    corpus = load_grounding_corpus(CORPUS_PATH)
    ev = evaluate_resolver(corpus, resolver_name="deterministic")
    assert len(ev.outcomes) == len(corpus.cases)
    for outcome, case in zip(ev.outcomes, corpus.cases, strict=False):
        assert outcome.case is case


# ---------------------------------------------------------------------------
# Describer safety
# ---------------------------------------------------------------------------


def _three_room_graph() -> TopologyGraph:
    g = TopologyGraph()
    g.add_node(TopologyNode(id="a", label="Alpha", type="room", pose=Pose2D(0.0, 0.0)))
    g.add_node(TopologyNode(id="b", label="Beta", type="room", pose=Pose2D(1.0, 0.0)))
    g.add_node(TopologyNode(id="c", label="Gamma", type="room", pose=Pose2D(2.0, 0.0)))
    g.add_edge(TopologyEdge(id="ab", source="a", target="b", type="traversable"))
    g.add_edge(TopologyEdge(id="bc", source="b", target="c", type="traversable"))
    return g


def test_evaluate_describer_safety_well_formed_rewrite_passes_invariants() -> None:
    g = _three_room_graph()
    backend = EchoBackend(
        script=[
            "1. Begin at Alpha.\n2. Walk to Beta.\n3. Arrive at Gamma.\n",
        ]
    )
    cases = [DescriberSafetyCase(name="full", path=["a", "b", "c"])]
    ev = evaluate_describer_safety(g, backend, cases, backend_name="echo")
    assert ev.metrics.n_total == 1
    assert ev.metrics.references_preserved_rate == 1.0
    assert ev.metrics.step_indices_preserved_rate == 1.0
    assert ev.metrics.prior_steps_untouched_rate == 1.0
    assert ev.metrics.all_invariants_rate == 1.0
    assert ev.metrics.fallback_rate == 0.0


def test_evaluate_describer_safety_dropping_reference_fails() -> None:
    g = _three_room_graph()
    # The rewrite of step 2 omits the word "Beta" — invariant 1 fails.
    backend = EchoBackend(
        script=[
            "1. Begin at Alpha.\n2. Keep walking.\n3. Arrive at Gamma.\n",
        ]
    )
    cases = [DescriberSafetyCase(name="drop_ref", path=["a", "b", "c"])]
    ev = evaluate_describer_safety(g, backend, cases, backend_name="echo")
    assert ev.metrics.references_preserved_rate == 0.0
    # The other invariants still hold (step count is fine; full-plan run
    # has no prior steps to leak from; no situation hint to probe).
    assert ev.metrics.step_indices_preserved_rate == 1.0
    assert ev.metrics.prior_steps_untouched_rate == 1.0
    assert ev.metrics.all_invariants_rate == 0.0


def test_evaluate_describer_safety_fallback_passes_trivially() -> None:
    g = _three_room_graph()
    # An unparseable reply forces fallback to the deterministic floor.
    backend = EchoBackend(script=["nope, this is not a numbered list"])
    cases = [DescriberSafetyCase(name="fallback", path=["a", "b", "c"])]
    ev = evaluate_describer_safety(g, backend, cases, backend_name="echo")
    assert ev.metrics.fallback_rate == 1.0
    # Fallback runs pass invariants 1/2/3 trivially.
    assert ev.metrics.references_preserved_rate == 1.0
    assert ev.metrics.step_indices_preserved_rate == 1.0
    assert ev.metrics.prior_steps_untouched_rate == 1.0


def test_evaluate_describer_safety_mid_traversal_prior_leak_fails() -> None:
    g = _three_room_graph()
    # Mid-traversal at start_index=1: rewrite only steps 2..3 (visit
    # Beta, arrive at Gamma). The rewrite illegally references "Alpha"
    # (a node only in the prefix), which is prior-step leakage.
    backend = EchoBackend(
        script=[
            "2. Beta is right after Alpha.\n3. Arrive at Gamma.\n",
        ]
    )
    cases = [
        DescriberSafetyCase(name="leak", path=["a", "b", "c"], start_index=1)
    ]
    ev = evaluate_describer_safety(g, backend, cases, backend_name="echo")
    assert ev.metrics.prior_steps_untouched_rate == 0.0


def test_evaluate_describer_safety_mid_traversal_clean_passes() -> None:
    g = _three_room_graph()
    backend = EchoBackend(
        script=[
            "2. Walk over to Beta.\n3. Arrive at Gamma.\n",
        ]
    )
    cases = [
        DescriberSafetyCase(name="clean", path=["a", "b", "c"], start_index=1)
    ]
    ev = evaluate_describer_safety(g, backend, cases, backend_name="echo")
    assert ev.metrics.prior_steps_untouched_rate == 1.0
    assert ev.metrics.all_invariants_rate == 1.0


def test_evaluate_describer_safety_situation_changes_prompt() -> None:
    """The situation kwarg must produce a surface change in the prompt
    handed to the backend (we verify via the EchoBackend.calls log)."""
    g = _three_room_graph()
    backend = EchoBackend()
    cases = [
        DescriberSafetyCase(
            name="sit",
            path=["a", "b", "c"],
            start_index=1,
            situation="corridor closed for cleaning",
        )
    ]
    ev = evaluate_describer_safety(g, backend, cases, backend_name="echo")
    assert ev.metrics.situation_change_rate == 1.0


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def test_grounding_report_markdown_renders_both_sections() -> None:
    corpus = load_grounding_corpus(CORPUS_PATH)
    resolver_eval = evaluate_resolver(corpus, resolver_name="deterministic")
    g = _three_room_graph()
    backend = EchoBackend(
        script=["1. Begin at Alpha.\n2. Walk to Beta.\n3. Arrive at Gamma.\n"]
    )
    safety = evaluate_describer_safety(
        g, backend,
        [DescriberSafetyCase(name="ok", path=["a", "b", "c"])],
        backend_name="echo",
    )
    md = grounding_report_markdown([resolver_eval], safety_eval=safety)
    assert "## Resolver grounding" in md
    assert "deterministic" in md
    assert "precision@1" in md
    assert "## Describer rewrite safety" in md
    assert "references_preserved" in md
    # When no safety eval is supplied, the section says so.
    md_no_safety = grounding_report_markdown([resolver_eval], safety_eval=None)
    assert "skipped" in md_no_safety


def test_evaluate_resolver_handles_empty_corpus_gracefully() -> None:
    corpus = GroundingCorpus(
        graph_path="(empty)",
        graph=_three_room_graph(),
        cases=[],
    )
    ev = evaluate_resolver(corpus, resolver_name="empty")
    assert ev.metrics.n_total == 0
    assert ev.metrics.precision_at_1 == 0.0
    assert ev.metrics.abstention_rate == 0.0
    assert ev.outcomes == []


def test_unresolvable_case_top_k_recall_zero() -> None:
    """For an unresolvable case, recall@k denominator only counts
    answerable cases, so it should be 1.0 when those cases all hit."""
    corpus = GroundingCorpus(
        graph_path="(synthetic)",
        graph=_three_room_graph(),
        cases=[
            GroundingCase(query="alpha", gold=["a"], kind="precise"),
            GroundingCase(query="basement", gold=[], kind="unresolvable"),
        ],
    )
    ev = evaluate_resolver(corpus, resolver_name="deterministic")
    # The deterministic resolver should hit "alpha" → "a" cleanly.
    assert ev.metrics.precision_at_1 == 1.0
    # And the unresolvable case must abstain (the word "basement" is
    # nowhere in the labels), giving abstention_rate = 1.0.
    assert ev.metrics.abstention_rate == 1.0
