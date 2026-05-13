"""Embedding-based semantic queries over a TopologyGraph.

Nodes carry an optional embedding vector in their ``properties`` dict
(default key: ``"embedding"``). These helpers compute cosine similarity
between a query vector and each candidate's embedding, with the same
predicate-filter surface as :func:`semantic_toponav.query.find_nodes`.

The implementation uses only :mod:`math` from the standard library so the
core package stays dependency-free. Real CLIP / SigLIP / sentence-encoder
embeddings can be attached to nodes ahead of time (and serialized through
the YAML/JSON loader, since ``properties`` accepts arbitrary values).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import TopologyNode
from semantic_toponav.query.find import NoMatchError, _matches

DEFAULT_EMBEDDING_PROPERTY = "embedding"


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity in ``[-1, 1]`` between two equal-length vectors.

    Raises ``ValueError`` for mismatched dimensions or a zero-norm input.
    """
    if len(a) != len(b):
        raise ValueError(
            f"embedding dimension mismatch: {len(a)} vs {len(b)}"
        )
    dot = 0.0
    na = 0.0
    nb = 0.0
    for ai, bi in zip(a, b, strict=False):
        fa = float(ai)
        fb = float(bi)
        dot += fa * fb
        na += fa * fa
        nb += fb * fb
    if na == 0.0 or nb == 0.0:
        raise ValueError("cannot compute cosine similarity for a zero vector")
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _candidate_embedding(
    node: TopologyNode, *, embedding_property: str
) -> Sequence[float] | None:
    vec = node.properties.get(embedding_property)
    if vec is None:
        return None
    if not hasattr(vec, "__len__") or not hasattr(vec, "__iter__"):
        return None
    return vec  # type: ignore[return-value]


def find_nodes_by_embedding(
    graph: TopologyGraph,
    query: Sequence[float],
    *,
    top_k: int = 5,
    embedding_property: str = DEFAULT_EMBEDDING_PROPERTY,
    type: str | None = None,
    label_contains: str | None = None,
    label_equals: str | None = None,
    properties: dict[str, Any] | None = None,
) -> list[tuple[TopologyNode, float]]:
    """Return the top-k matches by cosine similarity to ``query``.

    Same predicate filters as :func:`find_nodes` may be applied first to
    narrow the candidate set (e.g. only ``type="room"``).

    Returns a list of ``(node, similarity)`` tuples sorted by descending
    similarity. Nodes without an embedding under ``embedding_property``
    are skipped. Raises ``ValueError`` on dimension mismatch between
    ``query`` and any candidate embedding.
    """
    if top_k < 1:
        raise ValueError(f"top_k must be >= 1, got {top_k}")

    query_len = len(query)
    scored: list[tuple[TopologyNode, float]] = []
    for node in graph.nodes():
        if not _matches(
            node,
            type=type,
            label_contains=label_contains,
            label_equals=label_equals,
            properties=properties,
        ):
            continue
        vec = _candidate_embedding(node, embedding_property=embedding_property)
        if vec is None:
            continue
        if len(vec) != query_len:
            raise ValueError(
                f"node {node.id!r} embedding has dim {len(vec)}; expected {query_len}"
            )
        scored.append((node, cosine_similarity(query, vec)))

    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_k]


def nearest_node_by_embedding(
    graph: TopologyGraph,
    query: Sequence[float],
    *,
    embedding_property: str = DEFAULT_EMBEDDING_PROPERTY,
    type: str | None = None,
    label_contains: str | None = None,
    label_equals: str | None = None,
    properties: dict[str, Any] | None = None,
) -> TopologyNode:
    """Single highest-similarity node matching the filters.

    Convenience wrapper over :func:`find_nodes_by_embedding`. Raises
    :class:`NoMatchError` if no matching node has an embedding.
    """
    matches = find_nodes_by_embedding(
        graph,
        query,
        top_k=1,
        embedding_property=embedding_property,
        type=type,
        label_contains=label_contains,
        label_equals=label_equals,
        properties=properties,
    )
    if not matches:
        raise NoMatchError(
            "no node satisfies the filters and has an "
            f"{embedding_property!r} property"
        )
    return matches[0][0]
