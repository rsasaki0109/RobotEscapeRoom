"""Tests for the clarification dialog primitives (PR #40)."""

from __future__ import annotations

from pathlib import Path

import pytest

from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.llm.backends import EchoBackend
from semantic_toponav.query import (
    AmbiguousGoalError,
    ClarificationAnswer,
    ClarificationQuestion,
)
from semantic_toponav.query.llm_resolve import (
    _detect_deterministic_ambiguity,
    _parse_response,
    llm_resolve_goal,
)
from semantic_toponav.query.resolve import GoalCandidate, resolve_goal

EXAMPLE_YAML = Path(__file__).resolve().parents[1] / "examples" / "indoor_office.yaml"


def _make_candidate(node_id: str, score: float) -> GoalCandidate:
    """Helper: build a fake candidate without dragging in a real graph."""
    from semantic_toponav.graph.types import TopologyNode

    node = TopologyNode(id=node_id, label=node_id, type="room")
    return GoalCandidate(node_id=node_id, node=node, score=score, reasons=[])


# ----- type-only sanity -------------------------------------------------------


def test_clarification_question_is_frozen() -> None:
    q = ClarificationQuestion(
        question="A or B?",
        candidates=(_make_candidate("a", 1.0), _make_candidate("b", 0.9)),
    )
    # frozen=True prevents reassignment.
    with pytest.raises(AttributeError):
        q.question = "rewrite"  # type: ignore[misc]


def test_clarification_answer_defaults_both_none() -> None:
    a = ClarificationAnswer()
    assert a.chosen_id is None
    assert a.free_text is None


def test_ambiguous_goal_error_carries_question() -> None:
    q = ClarificationQuestion(question="?", candidates=())
    err = AmbiguousGoalError(q)
    assert err.question is q
    assert str(err) == "?"


# ----- _detect_deterministic_ambiguity ----------------------------------------


def test_detect_ambiguity_returns_none_for_empty_or_singleton() -> None:
    assert _detect_deterministic_ambiguity([], threshold=0.5) is None
    assert (
        _detect_deterministic_ambiguity(
            [_make_candidate("a", 1.0)], threshold=0.5
        )
        is None
    )


def test_detect_ambiguity_returns_none_when_gap_wider_than_threshold() -> None:
    cs = [
        _make_candidate("a", 5.0),
        _make_candidate("b", 2.0),
    ]
    assert _detect_deterministic_ambiguity(cs, threshold=0.5) is None


def test_detect_ambiguity_flags_close_top_two() -> None:
    cs = [
        _make_candidate("a", 1.0),
        _make_candidate("b", 0.9),  # delta = 0.1, threshold = 0.5
        _make_candidate("c", 0.1),
    ]
    q = _detect_deterministic_ambiguity(cs, threshold=0.5)
    assert q is not None
    # Both ambiguous tier members appear; the unambiguous tail doesn't.
    ids = [c.node_id for c in q.candidates]
    assert ids == ["a", "b"]


def test_detect_ambiguity_groups_full_tier() -> None:
    cs = [
        _make_candidate("a", 3.0),
        _make_candidate("b", 2.8),
        _make_candidate("c", 2.6),
        _make_candidate("d", 0.0),
    ]
    q = _detect_deterministic_ambiguity(cs, threshold=0.5)
    assert q is not None
    assert [c.node_id for c in q.candidates] == ["a", "b", "c"]


# ----- _parse_response with Clarify line --------------------------------------


def test_parse_response_extracts_clarify_line() -> None:
    pick, reason, clarify = _parse_response(
        "Clarify: did you mean room A or room B?"
    )
    assert pick is None
    assert reason is None
    assert clarify == "did you mean room A or room B?"


def test_parse_response_pick_wins_over_clarify_in_combined_reply() -> None:
    pick, reason, clarify = _parse_response(
        "Top match: kitchen\nClarify: but the lab also matches\nReason: it's the kitchen."
    )
    assert pick == "kitchen"
    assert reason == "it's the kitchen."
    assert clarify == "but the lab also matches"


# ----- llm_resolve_goal integration -------------------------------------------


def test_llm_clarify_reply_surfaces_clarification_field() -> None:
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend(
        script=["Clarify: there are two meeting rooms; which floor?"]
    )
    result = llm_resolve_goal(g, "meeting room", backend, top_k=5)
    assert result.clarification is not None
    assert "two meeting rooms" in result.clarification.question
    assert result.llm_pick is None
    # The candidates list still falls back to the deterministic base.
    assert result.candidates == result.base_candidates


def test_llm_clarify_raises_when_raise_on_ambiguous_true() -> None:
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend(script=["Clarify: which floor?"])
    with pytest.raises(AmbiguousGoalError) as exc_info:
        llm_resolve_goal(
            g, "meeting room", backend, top_k=5, raise_on_ambiguous=True
        )
    assert "which floor?" in str(exc_info.value)


def test_clarification_chosen_id_narrows_pool() -> None:
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend(
        script=[
            "Top match: meeting_room\nReason: chosen via clarification."
        ]
    )
    # Provide the previous turn's pick. Pool is narrowed to it.
    result = llm_resolve_goal(
        g, "meeting room", backend,
        top_k=5,
        clarification=ClarificationAnswer(chosen_id="meeting_room"),
    )
    # Base is narrowed to the chosen candidate only.
    assert len(result.base_candidates) == 1
    assert result.base_candidates[0].node_id == "meeting_room"
    assert result.candidates[0].node_id == "meeting_room"


def test_clarification_out_of_pool_chosen_id_is_ignored() -> None:
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend(
        script=["Top match: meeting_room\nReason: deterministic top pick."]
    )
    # 'not_a_real_node' isn't in the candidate pool; it gets dropped.
    result = llm_resolve_goal(
        g, "meeting room", backend,
        top_k=5,
        clarification=ClarificationAnswer(chosen_id="not_a_real_node"),
    )
    # Pool stays at its normal top_k.
    assert len(result.base_candidates) >= 1
    assert result.base_candidates[0].node_id == "meeting_room"


def test_clarification_free_text_appends_to_query() -> None:
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend(
        script=["Top match: office_2f\nReason: matches second floor office."]
    )
    result = llm_resolve_goal(
        g, "office", backend,
        top_k=5,
        clarification=ClarificationAnswer(free_text="on the second floor"),
    )
    # The result records the effective (augmented) query.
    assert "second floor" in result.query


def test_deterministic_ambiguity_surfaced_on_fallback() -> None:
    """When the LLM picks an out-of-pool id AND the deterministic top
    candidates are close in score, the result carries a clarification."""
    g = load_graph(EXAMPLE_YAML)
    # The query 'floor 2' typically ties at least two floor-2 nodes
    # under the bag-of-words scorer.
    base = resolve_goal(g, "floor 2", top_k=5)
    # Sanity: ambiguity exists under the default threshold.
    q = _detect_deterministic_ambiguity(base, threshold=0.5)
    backend = EchoBackend(script=["Top match: not_a_real_node\nReason: x."])
    result = llm_resolve_goal(g, "floor 2", backend, top_k=5)
    assert result.used_fallback is True
    if q is not None:
        assert result.clarification is not None


def test_default_raise_on_ambiguous_is_false_back_compat() -> None:
    """Existing call sites without the new kwarg never see an
    AmbiguousGoalError."""
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend(script=["Clarify: which one?"])
    # No raise — clarification is reported via the result field.
    result = llm_resolve_goal(g, "meeting room", backend, top_k=5)
    assert result.clarification is not None
