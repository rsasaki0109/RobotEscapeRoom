"""Tests for the LLM-augmented path narration."""

from __future__ import annotations

from pathlib import Path

from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode
from semantic_toponav.llm.backends import EchoBackend
from semantic_toponav.waypoint.llm_describe import llm_describe_path

EXAMPLE_YAML = Path(__file__).resolve().parents[1] / "examples" / "indoor_office.yaml"


def _tiny_graph() -> TopologyGraph:
    g = TopologyGraph()
    g.add_node(TopologyNode(id="a", label="Alpha", type="room", pose=Pose2D(0.0, 0.0)))
    g.add_node(TopologyNode(id="b", label="Beta", type="room", pose=Pose2D(1.0, 0.0)))
    g.add_edge(TopologyEdge(id="ab", source="a", target="b", type="traversable"))
    return g


def test_empty_path_yields_empty_result() -> None:
    g = _tiny_graph()
    backend = EchoBackend()
    result = llm_describe_path(g, [], backend)
    assert result.steps == []
    assert result.base_steps == []
    assert backend.calls == []  # no LLM call when there's nothing to rewrite


def test_well_formed_response_replaces_deterministic_text() -> None:
    g = _tiny_graph()
    scripted = "1. Begin your journey at the Alpha room.\n2. Walk over to the Beta room.\n"
    backend = EchoBackend(script=[scripted])
    result = llm_describe_path(g, ["a", "b"], backend)
    assert not result.used_fallback
    assert result.steps == [
        "Begin your journey at the Alpha room.",
        "Walk over to the Beta room.",
    ]
    assert result.raw_response == scripted
    assert len(result.base_steps) == 2


def test_unparseable_response_falls_back_to_deterministic() -> None:
    g = _tiny_graph()
    backend = EchoBackend(script=["sure thing, sounds great!"])
    result = llm_describe_path(g, ["a", "b"], backend)
    assert result.used_fallback
    # Fallback text is the deterministic step text.
    assert result.steps == ["Start at Alpha", "Arrive at Beta"]


def test_response_with_wrong_step_count_falls_back() -> None:
    g = _tiny_graph()
    # Only 1 numbered line when 2 were expected -> reject.
    backend = EchoBackend(script=["1. Just go from Alpha to Beta."])
    result = llm_describe_path(g, ["a", "b"], backend)
    assert result.used_fallback
    assert len(result.steps) == 2


def test_response_with_wrong_numbering_falls_back() -> None:
    g = _tiny_graph()
    backend = EchoBackend(script=["1. ok\n3. skipped one"])
    result = llm_describe_path(g, ["a", "b"], backend)
    assert result.used_fallback


def test_prompt_includes_node_context_and_style_hint() -> None:
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend()
    llm_describe_path(
        g,
        ["entrance", "corridor_main", "lobby_intersection", "meeting_room"],
        backend,
        style="concise",
    )
    assert len(backend.calls) == 1
    prompt = backend.calls[0]["prompt"]
    assert "Target style: concise" in prompt
    assert "type=corridor" in prompt
    assert "label='Entrance'" in prompt
    # The output-format instruction is present.
    assert "N. <text>" in prompt


def test_prompt_includes_edge_type_for_elevator_transit() -> None:
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend()
    path = ["entrance", "corridor_main", "elevator_1f", "elevator_2f", "corridor_2f", "office_2f"]
    llm_describe_path(g, path, backend)
    prompt = backend.calls[0]["prompt"]
    assert "edge_type=elevator_connection" in prompt


def test_default_system_instruction_forwarded() -> None:
    g = _tiny_graph()
    backend = EchoBackend()
    llm_describe_path(g, ["a", "b"], backend)
    sys_msg = backend.calls[0]["system"]
    assert sys_msg is not None
    assert "navigation-instruction" in sys_msg


def test_custom_system_instruction_overrides_default() -> None:
    g = _tiny_graph()
    backend = EchoBackend()
    llm_describe_path(g, ["a", "b"], backend, system="be terse")
    assert backend.calls[0]["system"] == "be terse"


def test_base_steps_are_preserved_on_fallback() -> None:
    g = _tiny_graph()
    backend = EchoBackend(script=["bogus"])
    result = llm_describe_path(g, ["a", "b"], backend)
    assert result.used_fallback
    # The deterministic floor is always present.
    assert [s.text for s in result.base_steps] == ["Start at Alpha", "Arrive at Beta"]


def _three_room_graph() -> TopologyGraph:
    g = TopologyGraph()
    g.add_node(TopologyNode(id="a", label="Alpha", type="room", pose=Pose2D(0.0, 0.0)))
    g.add_node(TopologyNode(id="b", label="Beta", type="room", pose=Pose2D(1.0, 0.0)))
    g.add_node(TopologyNode(id="c", label="Gamma", type="room", pose=Pose2D(2.0, 0.0)))
    g.add_edge(TopologyEdge(id="ab", source="a", target="b", type="traversable"))
    g.add_edge(TopologyEdge(id="bc", source="b", target="c", type="traversable"))
    return g


def test_start_index_zero_matches_default_behavior() -> None:
    g = _three_room_graph()
    backend = EchoBackend(script=["1. one\n2. two\n3. three\n"])
    explicit = llm_describe_path(g, ["a", "b", "c"], backend, start_index=0)
    backend2 = EchoBackend(script=["1. one\n2. two\n3. three\n"])
    default = llm_describe_path(g, ["a", "b", "c"], backend2)
    assert explicit.steps == default.steps
    assert [s.text for s in explicit.base_steps] == [s.text for s in default.base_steps]
    assert [s.index for s in explicit.base_steps] == [s.index for s in default.base_steps]


def test_start_index_skips_completed_steps_and_preserves_numbering() -> None:
    g = _three_room_graph()
    # Two remaining steps (visit B, arrive at C). Their indices in the full
    # plan are 2 and 3 — the LLM is expected to keep those numbers.
    backend = EchoBackend(script=["2. Walk over to the Beta room.\n3. Settle into Gamma.\n"])
    result = llm_describe_path(g, ["a", "b", "c"], backend, start_index=1)
    assert not result.used_fallback
    assert result.steps == ["Walk over to the Beta room.", "Settle into Gamma."]
    assert [s.index for s in result.base_steps] == [2, 3]
    # The completed "Start at Alpha" step is not handed to the LLM.
    prompt = backend.calls[0]["prompt"]
    assert "Start at Alpha" not in prompt
    assert "Beta" in prompt
    assert "Gamma" in prompt
    # The mid-traversal framing is included in the prompt.
    assert "already completed" in prompt


def test_start_index_response_with_old_one_based_numbering_falls_back() -> None:
    g = _three_room_graph()
    # The LLM ignored the mid-traversal instruction and renumbered from 1.
    backend = EchoBackend(script=["1. one\n2. two\n"])
    result = llm_describe_path(g, ["a", "b", "c"], backend, start_index=1)
    assert result.used_fallback
    # Fallback covers exactly the remaining slice (no synthetic step count).
    assert len(result.steps) == 2
    assert [s.index for s in result.base_steps] == [2, 3]


def test_start_index_past_last_node_returns_empty_without_backend_call() -> None:
    g = _three_room_graph()
    backend = EchoBackend()
    result = llm_describe_path(g, ["a", "b", "c"], backend, start_index=3)
    assert result.steps == []
    assert result.base_steps == []
    assert backend.calls == []


def test_start_index_at_last_node_rewrites_only_the_final_step() -> None:
    g = _three_room_graph()
    backend = EchoBackend(script=["3. You have arrived at Gamma.\n"])
    result = llm_describe_path(g, ["a", "b", "c"], backend, start_index=2)
    assert not result.used_fallback
    assert result.steps == ["You have arrived at Gamma."]
    assert [s.index for s in result.base_steps] == [3]


def test_negative_start_index_raises() -> None:
    g = _three_room_graph()
    backend = EchoBackend()
    try:
        llm_describe_path(g, ["a", "b", "c"], backend, start_index=-1)
    except ValueError as exc:
        assert "start_index" in str(exc)
    else:
        raise AssertionError("expected ValueError for negative start_index")
    assert backend.calls == []


def test_situation_hint_is_injected_into_prompt() -> None:
    g = _three_room_graph()
    backend = EchoBackend()
    llm_describe_path(
        g,
        ["a", "b", "c"],
        backend,
        start_index=1,
        situation="Corridor through Beta is now blocked; expect a detour later.",
    )
    prompt = backend.calls[0]["prompt"]
    assert "Current situation:" in prompt
    assert "Corridor through Beta is now blocked" in prompt


def test_situation_hint_omitted_when_none() -> None:
    g = _three_room_graph()
    backend = EchoBackend()
    llm_describe_path(g, ["a", "b", "c"], backend)
    prompt = backend.calls[0]["prompt"]
    assert "Current situation:" not in prompt
    # And the partial-plan framing is also omitted on a from-the-start call.
    assert "already completed" not in prompt


def test_mid_traversal_supports_style_and_custom_system() -> None:
    g = _three_room_graph()
    backend = EchoBackend()
    llm_describe_path(
        g,
        ["a", "b", "c"],
        backend,
        start_index=1,
        style="concise",
        system="be terse",
    )
    assert backend.calls[0]["system"] == "be terse"
    assert "Target style: concise" in backend.calls[0]["prompt"]
