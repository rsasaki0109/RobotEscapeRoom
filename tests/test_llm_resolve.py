"""Tests for the LLM-augmented goal resolver."""

from __future__ import annotations

from pathlib import Path

from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.llm.backends import EchoBackend
from semantic_toponav.query.llm_resolve import llm_resolve_goal

EXAMPLE_YAML = Path(__file__).resolve().parents[1] / "examples" / "indoor_office.yaml"


def test_empty_query_short_circuits_without_calling_backend() -> None:
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend()
    result = llm_resolve_goal(g, "", backend)
    assert result.candidates == []
    assert result.base_candidates == []
    assert backend.calls == []


def test_valid_pick_moves_node_to_front() -> None:
    g = load_graph(EXAMPLE_YAML)
    # Deterministic resolver returns multiple floor-2 candidates;
    # ask the LLM to pick office_2f, which scores lower than the
    # corridor on the deterministic floor (corridor outranks alphabetically).
    backend = EchoBackend(
        script=["Top match: office_2f\nReason: matches the office on floor 2."]
    )
    result = llm_resolve_goal(g, "second floor office", backend, top_k=5)
    assert not result.used_fallback
    assert result.candidates[0].node_id == "office_2f"
    assert result.llm_pick == "office_2f"
    assert result.llm_reason == "matches the office on floor 2."
    # The reason gets appended to the picked candidate's reasons list.
    joined = " | ".join(result.candidates[0].reasons)
    assert "LLM: matches the office" in joined


def test_pick_not_in_candidate_pool_falls_back() -> None:
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend(
        script=["Top match: completely_made_up_node\nReason: I hallucinated."]
    )
    result = llm_resolve_goal(g, "kitchen", backend)
    assert result.used_fallback
    assert result.llm_pick == "completely_made_up_node"
    # Deterministic order preserved.
    assert result.candidates == result.base_candidates


def test_unparseable_response_falls_back() -> None:
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend(script=["sure I think the kitchen is great"])
    result = llm_resolve_goal(g, "kitchen", backend)
    assert result.used_fallback
    assert result.llm_pick is None


def test_response_tolerates_alternative_phrasings() -> None:
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend(
        script=["Best: meeting_room\nReason: clearly the meeting room."]
    )
    result = llm_resolve_goal(g, "meeting room", backend)
    assert not result.used_fallback
    assert result.candidates[0].node_id == "meeting_room"


def test_prompt_contains_candidate_block_and_query() -> None:
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend()
    llm_resolve_goal(g, "second floor office", backend, top_k=5)
    prompt = backend.calls[0]["prompt"]
    assert "User query: second floor office" in prompt
    # The deterministic candidates appear in the candidate block.
    assert "office_2f" in prompt
    assert "Top match:" in prompt
    assert "Reason:" in prompt


def test_default_system_instruction_warns_against_invention() -> None:
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend()
    llm_resolve_goal(g, "meeting room", backend)
    sys_msg = backend.calls[0]["system"]
    assert sys_msg is not None
    assert "never invent" in sys_msg.lower()


def test_top_k_limits_candidates_shown_to_llm() -> None:
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend()
    llm_resolve_goal(g, "floor 2", backend, top_k=2)
    prompt = backend.calls[0]["prompt"]
    candidate_lines = [line for line in prompt.splitlines() if line.startswith("- ")]
    assert len(candidate_lines) == 2


def test_base_candidates_are_preserved_when_pick_succeeds() -> None:
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend(
        script=["Top match: kitchen\nReason: it's the kitchen."]
    )
    result = llm_resolve_goal(g, "kitchen", backend)
    # base_candidates carries the deterministic order, candidates the
    # LLM-reordered one. They should differ in this case only if the
    # pick wasn't already at position 0; here the deterministic top is
    # already 'kitchen', so the orders match.
    assert {c.node_id for c in result.candidates} == {
        c.node_id for c in result.base_candidates
    }


def test_no_match_returns_empty_without_calling_backend() -> None:
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend()
    result = llm_resolve_goal(g, "the secret garden", backend)
    assert result.candidates == []
    assert backend.calls == []
