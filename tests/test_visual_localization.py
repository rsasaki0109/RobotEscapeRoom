"""Tests for image-grounded visual localization.

These run entirely on the deterministic :class:`HashingBackend`, so no
torch / CLIP model is needed. The trick: ``HashingBackend.embed_image``
maps identical input bytes to an identical unit vector, so stamping a
node with the embedding of patch *k* and then localizing with the same
patch *k* must return that node at cosine similarity ~1.0.
"""

from __future__ import annotations

import math

import pytest

from semantic_toponav.encoders.backends import HashingBackend
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyNode
from semantic_toponav.query import (
    NoMatchError,
    VisualLocalization,
    localize_by_image,
)

# Distinct, recognizable "camera frames" — raw bytes are enough for the
# hashing backend, keeping this suite numpy-free.
FRAME_KITCHEN = b"frame:kitchen:stainless-counters-and-a-sink"
FRAME_CORRIDOR = b"frame:corridor:long-hallway-with-doors"
FRAME_ELEVATOR = b"frame:elevator:metallic-doors-and-buttons"
FRAME_UNSEEN = b"frame:rooftop:never-stamped-on-any-node"


def _node(backend, id_, label, type_, frame=None, *, prop="embedding"):
    props = {}
    if frame is not None:
        props[prop] = backend.embed_image(frame)
    return TopologyNode(
        id=id_, label=label, type=type_, pose=Pose2D(0, 0), properties=props
    )


def _graph(backend) -> TopologyGraph:
    g = TopologyGraph()
    g.add_node(_node(backend, "kitchen", "Kitchen", "room", FRAME_KITCHEN))
    g.add_node(_node(backend, "hall", "Hallway", "corridor", FRAME_CORRIDOR))
    g.add_node(_node(backend, "elev", "Elevator", "room", FRAME_ELEVATOR))
    return g


def test_localizes_to_matching_node() -> None:
    backend = HashingBackend(dim=64)
    g = _graph(backend)
    result = localize_by_image(g, FRAME_ELEVATOR, backend)
    assert isinstance(result, VisualLocalization)
    assert result.node.id == "elev"
    assert math.isclose(result.score, 1.0, abs_tol=1e-9)


def test_best_mirrors_ranked_head() -> None:
    backend = HashingBackend(dim=64)
    g = _graph(backend)
    result = localize_by_image(g, FRAME_KITCHEN, backend)
    assert result.ranked[0][0].id == result.node.id
    assert result.ranked[0][1] == result.score


def test_ranked_is_sorted_descending() -> None:
    backend = HashingBackend(dim=64)
    g = _graph(backend)
    result = localize_by_image(g, FRAME_CORRIDOR, backend, top_k=3)
    scores = [s for _, s in result.ranked]
    assert scores == sorted(scores, reverse=True)
    assert result.node.id == "hall"


def test_top_k_caps_shortlist() -> None:
    backend = HashingBackend(dim=64)
    g = _graph(backend)
    result = localize_by_image(g, FRAME_KITCHEN, backend, top_k=2)
    assert len(result.ranked) == 2


def test_unseen_frame_still_ranks_but_low() -> None:
    backend = HashingBackend(dim=64)
    g = _graph(backend)
    result = localize_by_image(g, FRAME_UNSEEN, backend)
    # A never-stamped frame is near-orthogonal to every node, so the top
    # score should be far below a genuine match.
    assert result.score < 0.5


def test_type_filter_restricts_candidates() -> None:
    backend = HashingBackend(dim=64)
    g = _graph(backend)
    # The elevator frame matches the 'elev' room best overall, but a
    # corridor-only query must fall back to the single corridor node.
    result = localize_by_image(g, FRAME_ELEVATOR, backend, type="corridor")
    assert result.node.id == "hall"


def test_custom_embedding_property() -> None:
    backend = HashingBackend(dim=64)
    g = TopologyGraph()
    g.add_node(
        _node(backend, "kitchen", "Kitchen", "room", FRAME_KITCHEN, prop="clip_vec")
    )
    result = localize_by_image(
        g, FRAME_KITCHEN, backend, embedding_property="clip_vec"
    )
    assert result.node.id == "kitchen"


def test_no_embeddings_raises() -> None:
    backend = HashingBackend(dim=64)
    g = TopologyGraph()
    g.add_node(
        TopologyNode(id="x", label="X", type="room", pose=Pose2D(0, 0))
    )
    with pytest.raises(NoMatchError):
        localize_by_image(g, FRAME_KITCHEN, backend)


def test_invalid_top_k_raises() -> None:
    backend = HashingBackend(dim=64)
    g = _graph(backend)
    with pytest.raises(ValueError):
        localize_by_image(g, FRAME_KITCHEN, backend, top_k=0)
