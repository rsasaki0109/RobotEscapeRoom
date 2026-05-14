"""Tests for the deterministic natural-language goal resolver."""

from __future__ import annotations

from pathlib import Path

from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import TopologyNode
from semantic_toponav.query.resolve import GoalCandidate, resolve_goal

EXAMPLE_YAML = Path(__file__).resolve().parents[1] / "examples" / "indoor_office.yaml"


def _top_ids(cands: list[GoalCandidate]) -> list[str]:
    return [c.node_id for c in cands]


def test_empty_query_returns_empty() -> None:
    g = load_graph(EXAMPLE_YAML)
    assert resolve_goal(g, "") == []
    assert resolve_goal(g, "   ") == []


def test_pure_stopword_query_returns_empty() -> None:
    g = load_graph(EXAMPLE_YAML)
    # "go to the" -> all stopwords, no floor reference -> nothing to score on.
    assert resolve_goal(g, "go to the") == []


def test_label_match_wins(capsys=None) -> None:
    g = load_graph(EXAMPLE_YAML)
    cands = resolve_goal(g, "meeting room")
    assert cands[0].node_id == "meeting_room"
    # Two label hits: 'meeting' (+2) + 'room' (+2) = 4.
    assert cands[0].score >= 4.0
    # Other rooms score lower (type 'room' match only).
    assert all(c.score < cands[0].score for c in cands[1:])


def test_single_word_label_match() -> None:
    g = load_graph(EXAMPLE_YAML)
    cands = resolve_goal(g, "kitchen")
    assert cands[0].node_id == "kitchen"


def test_stopwords_do_not_dilute_match() -> None:
    g = load_graph(EXAMPLE_YAML)
    a = _top_ids(resolve_goal(g, "kitchen"))
    b = _top_ids(resolve_goal(g, "go to the kitchen please"))
    assert a == b


def test_label_match_outranks_type_match() -> None:
    g = load_graph(EXAMPLE_YAML)
    # "room" hits every node of type='room' as a type match (+1), but
    # Meeting Room is the only one whose label contains "room" (+2).
    cands = resolve_goal(g, "room")
    assert cands[0].node_id == "meeting_room"


def test_floor_reference_2f_filters_to_floor_2() -> None:
    g = load_graph(EXAMPLE_YAML)
    cands = resolve_goal(g, "2F", top_k=10)
    ids = _top_ids(cands)
    # Every floor-2 node should appear; no floor-1 node should.
    floor2 = {"corridor_2f", "office_2f", "elevator_2f", "stairs_2f"}
    assert set(ids) == floor2


def test_floor_reference_floor_2_phrasing() -> None:
    g = load_graph(EXAMPLE_YAML)
    cands = resolve_goal(g, "floor 2", top_k=10)
    assert set(_top_ids(cands)) == {"corridor_2f", "office_2f", "elevator_2f", "stairs_2f"}


def test_floor_reference_ordinal_word() -> None:
    g = load_graph(EXAMPLE_YAML)
    cands = resolve_goal(g, "second floor", top_k=10)
    assert set(_top_ids(cands)) == {"corridor_2f", "office_2f", "elevator_2f", "stairs_2f"}


def test_floor_reference_numeric_ordinal() -> None:
    g = load_graph(EXAMPLE_YAML)
    cands = resolve_goal(g, "2nd floor", top_k=10)
    assert set(_top_ids(cands)) == {"corridor_2f", "office_2f", "elevator_2f", "stairs_2f"}


def test_floor_plus_label_keyword_picks_unique_match() -> None:
    g = load_graph(EXAMPLE_YAML)
    cands = resolve_goal(g, "second floor office")
    assert cands[0].node_id == "office_2f"


def test_floor_mismatch_demotes_other_floor_nodes() -> None:
    g = load_graph(EXAMPLE_YAML)
    # The elevator landing on floor 2 must outrank the one on floor 1
    # because the query explicitly asks for floor 2.
    cands = resolve_goal(g, "elevator on the 2nd floor")
    assert cands[0].node_id == "elevator_2f"
    if len(cands) > 1:
        assert cands[0].score > cands[1].score


def test_unknown_subject_with_known_floor_falls_back_to_floor_match() -> None:
    g = load_graph(EXAMPLE_YAML)
    # No lab on floor 2 -> floor-2 nodes still surface on floor match alone.
    cands = resolve_goal(g, "2nd floor lab", top_k=10)
    assert cands  # not empty
    # The 1F lab must NOT be the top hit — its floor mismatches.
    assert cands[0].node_id != "lab"


def test_no_matching_node_returns_empty() -> None:
    g = load_graph(EXAMPLE_YAML)
    assert resolve_goal(g, "the secret garden") == []


def test_top_k_limits_results() -> None:
    g = load_graph(EXAMPLE_YAML)
    cands = resolve_goal(g, "floor 2", top_k=2)
    assert len(cands) == 2


def test_top_k_zero_or_negative_returns_empty() -> None:
    g = load_graph(EXAMPLE_YAML)
    assert resolve_goal(g, "kitchen", top_k=0) == []
    assert resolve_goal(g, "kitchen", top_k=-3) == []


def test_reasons_explain_each_match() -> None:
    g = load_graph(EXAMPLE_YAML)
    cands = resolve_goal(g, "second floor office")
    top = cands[0]
    joined = " | ".join(top.reasons).lower()
    assert "floor 2 matches" in joined
    assert "label matches 'office'" in joined


def test_candidates_filter_restricts_pool() -> None:
    g = load_graph(EXAMPLE_YAML)
    # Only score elevators; "elevator" then ranks them but nothing else
    # creeps in.
    elevators = [n for n in g.nodes() if n.type == "elevator"]
    cands = resolve_goal(g, "elevator", candidates=elevators)
    assert set(_top_ids(cands)) <= {"elevator_1f", "elevator_2f"}


def test_tie_break_is_lexicographic_by_id() -> None:
    g = TopologyGraph()
    # Two rooms with the same label tokens; the resolver should fall
    # back on node_id ordering.
    g.add_node(TopologyNode(id="b_room", label="Cafe", type="room"))
    g.add_node(TopologyNode(id="a_room", label="Cafe", type="room"))
    cands = resolve_goal(g, "cafe")
    assert [c.node_id for c in cands] == ["a_room", "b_room"]


def test_determinism_across_calls() -> None:
    g = load_graph(EXAMPLE_YAML)
    a = [(c.node_id, c.score) for c in resolve_goal(g, "second floor office")]
    b = [(c.node_id, c.score) for c in resolve_goal(g, "second floor office")]
    assert a == b
