"""Tests for embedding-based semantic queries."""

from __future__ import annotations

import math

import pytest

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyNode
from semantic_toponav.query import (
    NoMatchError,
    cosine_similarity,
    find_nodes_by_embedding,
    nearest_node_by_embedding,
)


def _node(id_, label, type_, embedding=None, **properties):
    props = dict(properties)
    if embedding is not None:
        props["embedding"] = list(embedding)
    return TopologyNode(
        id=id_, label=label, type=type_, pose=Pose2D(0, 0), properties=props
    )


def _three_node_graph() -> TopologyGraph:
    g = TopologyGraph()
    g.add_node(_node("a", "Alpha", "room", embedding=[1.0, 0.0, 0.0]))
    g.add_node(_node("b", "Beta", "room", embedding=[0.0, 1.0, 0.0]))
    g.add_node(_node("c", "Gamma", "corridor", embedding=[0.0, 0.0, 1.0]))
    return g


# ----------------------------- cosine_similarity -----------------------------


def test_cosine_identical_is_one() -> None:
    assert math.isclose(cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]), 1.0)


def test_cosine_opposite_is_minus_one() -> None:
    assert math.isclose(cosine_similarity([1.0, 0.0], [-1.0, 0.0]), -1.0)


def test_cosine_orthogonal_is_zero() -> None:
    assert math.isclose(cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0, abs_tol=1e-9)


def test_cosine_dimension_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0])


def test_cosine_zero_vector_raises() -> None:
    with pytest.raises(ValueError):
        cosine_similarity([0.0, 0.0], [1.0, 0.0])


# ----------------------------- find_nodes_by_embedding -----------------------


def test_find_returns_highest_first() -> None:
    g = _three_node_graph()
    results = find_nodes_by_embedding(g, [1.0, 0.1, 0.0], top_k=3)
    assert [r[0].id for r in results] == ["a", "b", "c"]
    assert results[0][1] > results[1][1] > results[2][1]


def test_find_respects_top_k() -> None:
    g = _three_node_graph()
    results = find_nodes_by_embedding(g, [1.0, 0.0, 0.0], top_k=2)
    assert len(results) == 2


def test_find_with_type_filter() -> None:
    g = _three_node_graph()
    results = find_nodes_by_embedding(g, [0.0, 0.0, 1.0], top_k=5, type="room")
    ids = [r[0].id for r in results]
    assert "c" not in ids  # c is a corridor
    assert set(ids) == {"a", "b"}


def test_find_with_property_filter() -> None:
    g = TopologyGraph()
    g.add_node(_node("a", "A", "room", embedding=[1.0, 0.0], floor=1))
    g.add_node(_node("b", "B", "room", embedding=[1.0, 0.0], floor=2))
    results = find_nodes_by_embedding(
        g, [1.0, 0.0], top_k=5, properties={"floor": 1}
    )
    assert [r[0].id for r in results] == ["a"]


def test_find_skips_nodes_without_embedding() -> None:
    g = TopologyGraph()
    g.add_node(_node("a", "A", "room", embedding=[1.0, 0.0]))
    g.add_node(_node("b", "B", "room"))  # no embedding
    results = find_nodes_by_embedding(g, [1.0, 0.0], top_k=5)
    assert [r[0].id for r in results] == ["a"]


def test_find_dimension_mismatch_raises() -> None:
    g = _three_node_graph()
    with pytest.raises(ValueError):
        find_nodes_by_embedding(g, [1.0, 0.0], top_k=3)  # wrong dim


def test_find_empty_when_no_candidates() -> None:
    g = TopologyGraph()
    g.add_node(_node("a", "A", "room"))  # no embedding
    assert find_nodes_by_embedding(g, [1.0], top_k=5) == []


def test_find_top_k_minimum() -> None:
    g = _three_node_graph()
    with pytest.raises(ValueError):
        find_nodes_by_embedding(g, [1.0, 0.0, 0.0], top_k=0)


# ----------------------------- nearest_node_by_embedding ---------------------


def test_nearest_returns_top_match() -> None:
    g = _three_node_graph()
    node = nearest_node_by_embedding(g, [1.0, 0.1, 0.0])
    assert node.id == "a"


def test_nearest_with_filter() -> None:
    g = _three_node_graph()
    # Highest overall would be 'a' (room) but we constrain to corridor.
    node = nearest_node_by_embedding(g, [1.0, 0.0, 0.0], type="corridor")
    assert node.id == "c"


def test_nearest_raises_when_no_candidate() -> None:
    g = TopologyGraph()
    g.add_node(_node("a", "A", "room"))  # no embedding
    with pytest.raises(NoMatchError):
        nearest_node_by_embedding(g, [1.0])


def test_nearest_custom_embedding_property() -> None:
    g = TopologyGraph()
    g.add_node(
        TopologyNode(
            id="a", label="A", type="room", pose=Pose2D(0, 0),
            properties={"clip_vec": [1.0, 0.0]},
        )
    )
    node = nearest_node_by_embedding(
        g, [1.0, 0.0], embedding_property="clip_vec"
    )
    assert node.id == "a"
