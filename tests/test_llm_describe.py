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
