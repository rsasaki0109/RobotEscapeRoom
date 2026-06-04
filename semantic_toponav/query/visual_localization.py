"""Visual localization: ground a camera image to a topology node.

This is the perception counterpart to the text-driven
:mod:`semantic_toponav.query.llm_resolve` path. Where ``llm_resolve``
turns a *language* goal into a node id, :func:`localize_by_image` turns
an *image* — typically the current frame from a robot's forward camera —
into the topology node it most likely depicts, by embedding the frame
with a CLIP-style encoder and ranking it against the per-node embeddings
already stamped on the graph (e.g. by
:func:`semantic_toponav.conversion.vlm.embed_region_patches`, or from
CLIP text/image prototypes attached offline).

It is a thin, honest composition of two existing pieces:

* :meth:`semantic_toponav.encoders.backends.Backend.embed_image` —
  image bytes / array / path / PIL → unit vector;
* :func:`semantic_toponav.query.embedding.find_nodes_by_embedding` —
  cosine-similarity ranking of the query vector against node embeddings.

So the whole module stays dependency-free at import time. The *encoder*
is pluggable: pass a :class:`~semantic_toponav.encoders.backends.CLIPBackend`
for real semantic grounding (needs the ``[vlm]`` extra), or the
deterministic :class:`~semantic_toponav.encoders.backends.HashingBackend`
for tests / CI without torch in the loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from semantic_toponav.encoders.backends import Backend
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import TopologyNode
from semantic_toponav.query.embedding import (
    DEFAULT_EMBEDDING_PROPERTY,
    find_nodes_by_embedding,
)
from semantic_toponav.query.find import NoMatchError


@dataclass
class VisualLocalization:
    """Result of grounding one image against the graph.

    Attributes
    ----------
    node:
        The single best-matching node (highest cosine similarity).
    score:
        Cosine similarity of ``node`` to the query image, in
        ``[-1, 1]``. With L2-normalized encoders (both bundled
        backends qualify) this is the dot product.
    ranked:
        Up to ``top_k`` ``(node, similarity)`` tuples sorted by
        descending similarity — the localization shortlist. ``node`` /
        ``score`` mirror ``ranked[0]``.
    """

    node: TopologyNode
    score: float
    ranked: list[tuple[TopologyNode, float]] = field(default_factory=list)


def _khop_node_ids(
    graph: TopologyGraph, start_id: str, hops: int
) -> set[str]:
    """Node ids within ``hops`` graph edges of ``start_id`` (exclusive).

    A breadth-first expansion over the (undirected) adjacency; ``start_id``
    itself is excluded from the result.
    """
    seen = {start_id}
    frontier = {start_id}
    for _ in range(hops):
        nxt: set[str] = set()
        for nid in frontier:
            for edge in graph.neighbors(nid):
                other = graph.other_end(edge, nid)
                if other not in seen:
                    seen.add(other)
                    nxt.add(other)
        frontier = nxt
        if not frontier:
            break
    seen.discard(start_id)
    return seen


def _neighbor_reranked(
    graph: TopologyGraph,
    scored: list[tuple[TopologyNode, float]],
    weight: float,
    hops: int,
    top_k: int,
) -> list[tuple[TopologyNode, float]]:
    """Blend each node's own cosine with the mean of its scored ``hops``-hop
    neighborhood, then re-sort.

    ``effective = (1 - weight) * own + weight * mean(neighborhood own)``.

    Only nodes within ``hops`` edges that survived the same candidate
    filters (i.e. appear in ``scored``) contribute; a node with no scored
    neighbor keeps its own score unchanged, so the aggregation never
    penalizes a genuine but isolated match. This is the cheap, in-graph
    analogue of RoboHop's descriptor aggregation over graph neighbors — it
    damps an isolated perceptual-aliasing spike, since a true place is
    corroborated by its surroundings while a spurious one usually is not.
    ``hops > 1`` widens the corroboration radius (RoboHop's multi-layer
    aggregation): support several hops away — past a weak immediate
    neighbor — can still lift a true place.
    """
    own = {node.id: score for node, score in scored}
    reranked: list[tuple[TopologyNode, float]] = []
    for node, score in scored:
        neighbor_scores = [
            own[other]
            for other in _khop_node_ids(graph, node.id, hops)
            if other in own
        ]
        if neighbor_scores:
            context = sum(neighbor_scores) / len(neighbor_scores)
            effective = (1.0 - weight) * score + weight * context
        else:
            effective = score
        reranked.append((node, effective))
    reranked.sort(key=lambda pair: pair[1], reverse=True)
    return reranked[:top_k]


def localize_by_image(
    graph: TopologyGraph,
    image: Any,
    backend: Backend,
    *,
    top_k: int = 5,
    embedding_property: str = DEFAULT_EMBEDDING_PROPERTY,
    neighbor_weight: float = 0.0,
    neighbor_hops: int = 1,
    type: str | None = None,
    label_contains: str | None = None,
    label_equals: str | None = None,
    properties: dict[str, Any] | None = None,
) -> VisualLocalization:
    """Ground ``image`` to the node it most likely depicts.

    Embeds ``image`` with ``backend`` and ranks it against every node
    that carries an embedding under ``embedding_property`` by cosine
    similarity. The same predicate filters as
    :func:`semantic_toponav.query.find_nodes` may be applied first to
    narrow the candidate set (e.g. ``type="room"`` to ignore corridors
    and doorways).

    Parameters
    ----------
    graph:
        Topology graph whose nodes carry embeddings (not mutated).
    image:
        The query frame. Anything ``backend.embed_image`` accepts —
        a NumPy array, filesystem path, raw ``bytes``, or ``PIL.Image``.
    backend:
        Encoder satisfying the
        :class:`~semantic_toponav.encoders.backends.Backend` protocol.
        Must be the *same* backend identity used to stamp the node
        embeddings — cross-backend vectors are not comparable.
    top_k:
        Size of the returned shortlist. Must be ``>= 1``.
    embedding_property:
        Node property key the embeddings live under. Defaults to
        ``"embedding"``.
    neighbor_weight:
        Context-aggregation strength in ``[0, 1]``. ``0.0`` (default) is
        pure single-frame cosine ranking. When ``> 0``, each node's score
        becomes ``(1 - w) * own + w * mean(scored 1-hop neighbors)``
        before ranking, so a true place corroborated by its graph
        neighbors outranks an isolated perceptual-aliasing spike. With
        ``w > 0`` the returned ``score`` / ``ranked`` similarities are
        these context-aggregated values, not raw cosines.
    neighbor_hops:
        Radius (in graph edges) of the neighborhood aggregated when
        ``neighbor_weight > 0``. ``1`` (default) is immediate neighbors;
        larger values widen the corroboration radius so support several
        hops away — past a weak immediate neighbor — still counts. Must
        be ``>= 1``. Ignored when ``neighbor_weight == 0``.
    type, label_contains, label_equals, properties:
        Optional candidate filters, forwarded to
        :func:`find_nodes_by_embedding`.

    Returns
    -------
    VisualLocalization
        Best match plus the ranked shortlist.

    Raises
    ------
    NoMatchError
        If no node satisfies the filters and carries an embedding.
    ValueError
        If ``top_k < 1``, ``neighbor_weight`` is outside ``[0, 1]``,
        ``neighbor_hops < 1``, or the query vector's dimension does not
        match a candidate embedding.
    """
    if not 0.0 <= neighbor_weight <= 1.0:
        raise ValueError(
            f"neighbor_weight must be in [0, 1], got {neighbor_weight}"
        )
    if neighbor_hops < 1:
        raise ValueError(f"neighbor_hops must be >= 1, got {neighbor_hops}")
    query_vec = backend.embed_image(image)
    if neighbor_weight == 0.0:
        ranked = find_nodes_by_embedding(
            graph,
            query_vec,
            top_k=top_k,
            embedding_property=embedding_property,
            type=type,
            label_contains=label_contains,
            label_equals=label_equals,
            properties=properties,
        )
    else:
        # Score every candidate (not just top_k) so a node's neighbors
        # are available to aggregate, then re-rank and slice.
        all_scored = find_nodes_by_embedding(
            graph,
            query_vec,
            top_k=max(1, sum(1 for _ in graph.nodes())),
            embedding_property=embedding_property,
            type=type,
            label_contains=label_contains,
            label_equals=label_equals,
            properties=properties,
        )
        ranked = _neighbor_reranked(
            graph, all_scored, neighbor_weight, neighbor_hops, top_k
        )
    if not ranked:
        raise NoMatchError(
            "no node satisfies the filters and has an "
            f"{embedding_property!r} property to localize against"
        )
    best_node, best_score = ranked[0]
    return VisualLocalization(node=best_node, score=best_score, ranked=ranked)
