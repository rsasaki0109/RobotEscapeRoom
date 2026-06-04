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


# --- neighbor-aware re-ranking (RoboHop-style context aggregation) ----

from semantic_toponav.graph.types import TopologyEdge  # noqa: E402


class _StubBackend:
    """Returns a fixed query vector regardless of the image, so tests can
    engineer an exact perceptual-aliasing scenario with explicit node
    embeddings."""

    def __init__(self, query_vec: list[float]) -> None:
        self._q = list(query_vec)

    def embed_image(self, image) -> list[float]:  # noqa: ANN001
        return list(self._q)


def _alias_graph() -> TopologyGraph:
    """q=[1,0]. Node 'alias' has the highest *own* cosine but sits alone
    next to a low-scoring node; the true place 'b' scores a touch lower
    but is corroborated by a high-scoring neighbor 'c'."""
    g = TopologyGraph()
    embeds = {
        "alias": [0.92, 0.3919],   # cos(q) = 0.92 — spurious top-1
        "d": [0.30, 0.9539],       # cos = 0.30 — alias's only neighbor
        "b": [0.85, 0.5268],       # cos = 0.85 — true place
        "c": [0.88, 0.4750],       # cos = 0.88 — b's neighbor (corroborates)
    }
    for nid, vec in embeds.items():
        g.add_node(
            TopologyNode(id=nid, label=nid, type="room", pose=Pose2D(0, 0),
                         properties={"embedding": vec})
        )
    g.add_edge(TopologyEdge(id="alias_d", source="alias", target="d", type="t"))
    g.add_edge(TopologyEdge(id="b_c", source="b", target="c", type="t"))
    return g


def test_neighbor_weight_zero_keeps_alias_top1() -> None:
    g = _alias_graph()
    backend = _StubBackend([1.0, 0.0])
    result = localize_by_image(g, b"any", backend, neighbor_weight=0.0)
    # Pure single-frame cosine: the spurious isolated spike wins.
    assert result.node.id == "alias"


def test_neighbor_weight_demotes_isolated_alias() -> None:
    g = _alias_graph()
    backend = _StubBackend([1.0, 0.0])
    result = localize_by_image(g, b"any", backend, neighbor_weight=0.5)
    # Context aggregation: alias is dragged down by its low neighbor 'd',
    # while the b/c cluster lifts each other — top-1 leaves the alias.
    assert result.node.id != "alias"
    assert result.node.id in {"b", "c"}


def test_neighbor_weight_out_of_range_raises() -> None:
    g = _alias_graph()
    backend = _StubBackend([1.0, 0.0])
    with pytest.raises(ValueError):
        localize_by_image(g, b"any", backend, neighbor_weight=1.5)
    with pytest.raises(ValueError):
        localize_by_image(g, b"any", backend, neighbor_weight=-0.1)


def _multihop_graph() -> TopologyGraph:
    """q=[1,0]. 'alias' has the highest *own* cosine, kept afloat by one
    moderate isolated neighbor. The true place 'b' has a *weak* immediate
    neighbor 'c' (so 1-hop context can't save it) but strong corroboration
    two hops out via 'e' — so only a 2-hop aggregate demotes the alias."""
    g = TopologyGraph()
    embeds = {
        "alias": [0.90, 0.4359],   # cos 0.90 — own top-1
        "anbr": [0.50, 0.8660],    # cos 0.50 — alias's lone neighbor
        "b": [0.80, 0.6000],       # cos 0.80 — true place
        "c": [0.40, 0.9165],       # cos 0.40 — b's weak 1-hop neighbor
        "e": [0.88, 0.4750],       # cos 0.88 — 2 hops from b, corroborates
    }
    for nid, vec in embeds.items():
        g.add_node(
            TopologyNode(id=nid, label=nid, type="room", pose=Pose2D(0, 0),
                         properties={"embedding": vec})
        )
    g.add_edge(TopologyEdge(id="alias_anbr", source="alias", target="anbr", type="t"))
    g.add_edge(TopologyEdge(id="b_c", source="b", target="c", type="t"))
    g.add_edge(TopologyEdge(id="c_e", source="c", target="e", type="t"))
    return g


def test_one_hop_insufficient_two_hop_demotes_alias() -> None:
    g = _multihop_graph()
    backend = _StubBackend([1.0, 0.0])
    # 1 hop: b's only neighbor is the weak 'c', so the alias keeps top-1.
    h1 = localize_by_image(g, b"any", backend, neighbor_weight=0.5, neighbor_hops=1)
    assert h1.node.id == "alias"
    # 2 hops: 'e' two edges from b joins the average and lifts the true
    # cluster above the isolated alias.
    h2 = localize_by_image(g, b"any", backend, neighbor_weight=0.5, neighbor_hops=2)
    assert h2.node.id != "alias"
    assert h2.node.id in {"b", "c", "e"}


def test_neighbor_hops_below_one_raises() -> None:
    g = _multihop_graph()
    backend = _StubBackend([1.0, 0.0])
    with pytest.raises(ValueError):
        localize_by_image(g, b"any", backend, neighbor_weight=0.5, neighbor_hops=0)


def test_isolated_node_keeps_own_score() -> None:
    # A graph with no edges: aggregation has no neighbors to pull from, so
    # ranking is identical to the pure-cosine path.
    backend = HashingBackend(dim=64)
    g = _graph(backend)  # _graph adds no edges
    plain = localize_by_image(g, FRAME_ELEVATOR, backend)
    rer = localize_by_image(g, FRAME_ELEVATOR, backend, neighbor_weight=0.7)
    assert plain.node.id == rer.node.id == "elev"
    assert math.isclose(plain.score, rer.score, abs_tol=1e-9)
