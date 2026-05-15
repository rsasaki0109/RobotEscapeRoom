"""Tests for :class:`DialogSession` — multi-turn LLM resolve driver."""

from __future__ import annotations

from pathlib import Path

import pytest

from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.llm.backends import EchoBackend
from semantic_toponav.query import (
    ClarificationAnswer,
    ClarificationQuestion,
    DialogSession,
    DialogTurn,
)

EXAMPLE_YAML = Path(__file__).resolve().parents[1] / "examples" / "indoor_office.yaml"


# ----- empty-state behaviour --------------------------------------------------


def test_session_starts_with_no_history() -> None:
    g = load_graph(EXAMPLE_YAML)
    session = DialogSession(g, EchoBackend())
    assert session.turns == []
    assert session.last_result() is None
    assert session.question() is None
    assert session.is_resolved() is False
    assert session.chosen() is None


def test_reply_before_start_raises() -> None:
    g = load_graph(EXAMPLE_YAML)
    session = DialogSession(g, EchoBackend())
    with pytest.raises(RuntimeError, match="before start"):
        session.reply(ClarificationAnswer(free_text="hint"))


# ----- single-turn confident resolve ------------------------------------------


def test_single_turn_confident_resolve_marks_session_resolved() -> None:
    """When the LLM picks confidently on the first turn, ``is_resolved`` is
    True immediately and no clarification is pending."""
    g = load_graph(EXAMPLE_YAML)
    # EchoBackend by default returns "[echo] <last line>". That last
    # line in the resolver prompt is "Reason: <one short sentence>",
    # which is unparseable as a Top match — so the result will fall
    # back to the deterministic order. To get a clean "resolved"
    # state, script the backend to name a real candidate.
    backend = EchoBackend(script=["Top match: kitchen\nReason: it's the kitchen"])
    session = DialogSession(g, backend, ambiguity_threshold=0.0)
    result = session.start("the kitchen")
    assert session.is_resolved() is True
    assert session.question() is None
    assert result.candidates[0].node_id == "kitchen"
    chosen = session.chosen()
    assert chosen is not None and chosen.node_id == "kitchen"


# ----- multi-turn flow --------------------------------------------------------


def test_clarification_then_chosen_id_reply_resolves_dialog() -> None:
    """Turn 1: LLM emits Clarify: → session has a pending question.
    Turn 2: caller picks one of the surfaced candidates by id → resolver
    narrows the pool to that single candidate and the LLM confirms."""
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend(
        script=[
            "Clarify: kitchen or lab?",                     # turn 1
            "Top match: lab\nReason: user picked the lab",  # turn 2
        ]
    )
    session = DialogSession(g, backend)
    session.start("the room")
    question = session.question()
    assert isinstance(question, ClarificationQuestion)
    assert session.is_resolved() is False

    # Reply: pick a candidate by id. The reply uses any node id in
    # the pool — DialogSession trusts only ids the resolver itself
    # produced, so we name one from the question's candidate list.
    chosen_id = question.candidates[0].node_id
    session.reply(ClarificationAnswer(chosen_id=chosen_id))
    assert session.is_resolved() is True


def test_free_text_hint_accumulates_across_turns() -> None:
    """Each ``ClarificationAnswer.free_text`` is appended to the running
    hint list and the effective query carries every accumulated hint."""
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend(
        script=[
            "Clarify: which one?",
            "Clarify: still ambiguous",
            "Top match: lab\nReason: ok",
        ]
    )
    session = DialogSession(g, backend)
    session.start("the room")
    session.reply(ClarificationAnswer(free_text="on the second floor"))
    session.reply(ClarificationAnswer(free_text="with the big window"))
    # Both hints appear in the running hint list.
    assert session.free_text_hints == [
        "on the second floor",
        "with the big window",
    ]
    # The third turn's effective query contains both hints.
    third_turn = session.turns[2]
    assert "on the second floor" in third_turn.effective_query
    assert "with the big window" in third_turn.effective_query


def test_reply_after_resolved_raises() -> None:
    """Once the session has resolved, further ``reply`` calls fail loudly —
    the caller should call :meth:`start` to begin a new dialog."""
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend(script=["Top match: kitchen\nReason: ok"])
    session = DialogSession(g, backend, ambiguity_threshold=0.0)
    session.start("the kitchen")
    assert session.is_resolved() is True
    with pytest.raises(RuntimeError, match="already resolved"):
        session.reply(ClarificationAnswer(free_text="oops"))


def test_start_clears_previous_session_state() -> None:
    """Re-using a session object: ``start`` wipes hints and turns."""
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend(
        script=[
            "Clarify: which?",
            "Top match: kitchen\nReason: ok",
            "Top match: lab\nReason: fresh start",
        ]
    )
    session = DialogSession(g, backend)
    session.start("the room")
    session.reply(ClarificationAnswer(free_text="left side"))
    # New start clears everything.
    session.start("the lab area")
    assert session.free_text_hints == []
    assert len(session.turns) == 1


# ----- turn history is informative -------------------------------------------


def test_turn_records_answer_and_effective_query() -> None:
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend(
        script=[
            "Clarify: A or B?",
            "Top match: kitchen\nReason: ok",
        ]
    )
    session = DialogSession(g, backend)
    session.start("the kitchen")
    answer = ClarificationAnswer(free_text="near the door")
    session.reply(answer)
    assert len(session.turns) == 2
    # First turn: bare query, no answer.
    first = session.turns[0]
    assert isinstance(first, DialogTurn)
    assert first.answer is None
    assert first.effective_query == "the kitchen"
    # Second turn: enriched query, answer recorded.
    second = session.turns[1]
    assert second.answer is answer
    assert "near the door" in second.effective_query


def test_turns_property_returns_a_copy() -> None:
    """Mutating the returned list must not corrupt the session's history."""
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend(script=["Top match: kitchen\nReason: ok"])
    session = DialogSession(g, backend, ambiguity_threshold=0.0)
    session.start("the kitchen")
    snapshot = session.turns
    snapshot.clear()
    assert len(session.turns) == 1


def test_free_text_hints_property_returns_a_copy() -> None:
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend(
        script=[
            "Clarify: which?",
            "Top match: kitchen\nReason: ok",
        ]
    )
    session = DialogSession(g, backend)
    session.start("the room")
    session.reply(ClarificationAnswer(free_text="left"))
    hints = session.free_text_hints
    hints.append("INJECTED")
    assert session.free_text_hints == ["left"]


# ----- effective query construction ------------------------------------------


def test_effective_query_format_for_zero_hints() -> None:
    """With no replies, the effective query is the original verbatim."""
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend(script=["Top match: kitchen\nReason: ok"])
    session = DialogSession(g, backend, ambiguity_threshold=0.0)
    session.start("the kitchen")
    assert session.turns[0].effective_query == "the kitchen"


def test_effective_query_concats_multiple_hints_in_order() -> None:
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend(
        script=[
            "Clarify: which?",
            "Clarify: still?",
            "Top match: kitchen\nReason: ok",
        ]
    )
    session = DialogSession(g, backend)
    session.start("the room")
    session.reply(ClarificationAnswer(free_text="first"))
    session.reply(ClarificationAnswer(free_text="second"))
    last = session.turns[-1]
    assert last.effective_query == "the room (first second)"


# ----- chosen_id propagation safety ------------------------------------------


def test_chosen_id_narrows_pool_for_current_turn_only() -> None:
    """A chosen_id in turn N narrows the pool for turn N's resolver call.
    Turn N+1's resolver still sees the full top-k (the pin only applies
    to the call it's attached to)."""
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend(
        script=[
            "Clarify: which?",
            # Turn 2 narrows to the chosen id; the LLM gets a single-
            # candidate pool. Echo's [echo] reply parses as unparseable,
            # so the resolver falls back to the (single-candidate)
            # deterministic order.
            "Top match: lab\nReason: pinned",
        ]
    )
    session = DialogSession(g, backend)
    session.start("the room")
    question = session.question()
    assert question is not None and len(question.candidates) >= 1
    pinned = question.candidates[0].node_id
    session.reply(ClarificationAnswer(chosen_id=pinned))
    # The narrowed turn's effective query is unchanged from the
    # previous turn (chosen_id doesn't append free text). The
    # candidate list contains only the pinned id.
    last = session.turns[-1].result
    assert len(last.candidates) == 1
    assert last.candidates[0].node_id == pinned
