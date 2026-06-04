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


def localize_by_image(
    graph: TopologyGraph,
    image: Any,
    backend: Backend,
    *,
    top_k: int = 5,
    embedding_property: str = DEFAULT_EMBEDDING_PROPERTY,
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
        If ``top_k < 1`` (from :func:`find_nodes_by_embedding`), or the
        query vector's dimension does not match a candidate embedding.
    """
    query_vec = backend.embed_image(image)
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
    if not ranked:
        raise NoMatchError(
            "no node satisfies the filters and has an "
            f"{embedding_property!r} property to localize against"
        )
    best_node, best_score = ranked[0]
    return VisualLocalization(node=best_node, score=best_score, ranked=ranked)
