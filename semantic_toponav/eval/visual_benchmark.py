"""Aggregate evidence for neighbor-aware visual re-ranking.

:func:`~semantic_toponav.query.localize_by_image`'s ``neighbor_weight`` /
``neighbor_hops`` knobs (PRs #77 / #79) damp perceptual-aliasing spikes by
blending each candidate's cosine with its scored graph neighbors, RoboHop
style. They are unit-tested per case on a hand-built aliasing graph
(``tests/test_visual_localization.py``), but the real-image Depot
benchmark (``visual_depot_drive.yaml``) is too small and too easy to move
the *aggregate* numbers — turning re-ranking on there changes nothing
visible, which under-sells the feature.

This module closes that gap with a **deterministic, torch-free corpus
engineered so the re-rank lift shows up in aggregate**:
:func:`evaluate_visual_localizer` reports precision@1 / recall@K of 0.00
with ``neighbor_weight=0.0`` and 1.00 once neighbor aggregation is on, on
the same corpus. It needs no images and no model — embeddings are placed
analytically via :class:`VectorTableBackend`, the perception analogue of
the ``_StubBackend`` in the unit tests, scaled up to a whole map.

Geometry (per cluster, in its own orthogonal 2-D subspace so clusters do
not interfere). The query is ``[1, 0]`` so a node's cosine to it is just
its first coordinate:

* ``true``   — the genuine place (cos 0.86), corroborated by one neighbor
  ``corrob`` (cos 0.84); ``corrob`` also touches a weak view ``weak``
  (cos 0.40) so the symmetric true<->corrob blend is broken and ``true``
  stays the unique winner after aggregation;
* ``dist_*`` — ``n_distractors`` look-alikes elsewhere in the building,
  each with a *higher* own cosine than ``true`` (so they win the raw
  single-frame ranking) but propped up only by a private low-scoring
  neighbor ``lone_*`` (cos 0.25), so neighbor aggregation collapses them.

Raw cosine ranks the distractors above ``true`` (precision@1 = 0, and with
the default five distractors ``true`` falls past rank 5 so recall@3 =
recall@5 = 0). Neighbor aggregation drags every isolated distractor down
to ~0.6 while ``true`` holds ~0.85, so it becomes the unique top-1 across
every cluster — precision@1 = recall@3 = recall@5 = 1.00.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from semantic_toponav.eval.grounding import (
    VisualGroundingCase,
    VisualGroundingCorpus,
    VisualLocalizerEvaluation,
    evaluate_visual_localizer,
)
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import TopologyEdge, TopologyNode

Vector = list[float]

# Own cosines (== first coordinate, since the query is [1, 0] per cluster).
_TRUE_COS = 0.86
_CORROB_COS = 0.84
_WEAK_COS = 0.40
_LONE_COS = 0.25
# Distractor own cosines are spread across (true, ~0.97]; every value stays
# strictly above _TRUE_COS so each look-alike wins the raw ranking.
_DIST_COS_HI = 0.97
_DIST_COS_LO = 0.87


class VectorTableBackend:
    """A :class:`~semantic_toponav.encoders.backends.Backend` that returns a
    fixed stored vector per lookup key.

    Both ``embed_text`` and ``embed_image`` treat their argument as an
    exact string key into ``table`` (built by :func:`aliasing_visual_corpus`
    so gallery node ids and query keys map to engineered unit vectors). It
    is the aggregate-scale sibling of the per-case ``_StubBackend`` in the
    visual-localization unit tests: it lets an eval engineer reproducible
    aliasing geometry with no images and no torch in the loop.
    """

    def __init__(self, table: dict[str, Vector], dim: int) -> None:
        if dim < 2:
            raise ValueError(f"dim must be >= 2, got {dim}")
        self._table = {k: list(v) for k, v in table.items()}
        self._dim = int(dim)

    @property
    def dim(self) -> int:
        return self._dim

    def _lookup(self, key: object) -> Vector:
        if not isinstance(key, str):
            raise TypeError(
                f"VectorTableBackend keys must be str, got {type(key).__name__}"
            )
        try:
            return list(self._table[key])
        except KeyError:
            raise KeyError(f"no engineered vector for key {key!r}") from None

    def embed_text(self, text: str) -> Vector:
        return self._lookup(text)

    def embed_image(self, image: object) -> Vector:
        return self._lookup(image)

    def embed_images(self, images) -> list[Vector]:  # noqa: ANN001
        return [self.embed_image(im) for im in images]


def _unit_in_block(dim: int, block: int, cos: float) -> Vector:
    """A unit vector whose only non-zero coordinates are ``block``'s 2-D
    subspace ``(2*block, 2*block+1)``, set to ``[cos, sqrt(1 - cos^2)]``.

    Its cosine with the per-cluster query ``[1, 0]`` (same subspace) is
    exactly ``cos``; with any other cluster's query it is 0 (orthogonal
    subspaces), so clusters never interfere.
    """
    vec = [0.0] * dim
    i = 2 * block
    vec[i] = cos
    vec[i + 1] = math.sqrt(max(0.0, 1.0 - cos * cos))
    return vec


def _distractor_cosines(n: int) -> list[float]:
    """``n`` own cosines spread across ``(_TRUE_COS, _DIST_COS_HI]``, all
    strictly above ``_TRUE_COS`` so every distractor wins the raw ranking."""
    if n <= 0:
        return []
    if n == 1:
        return [_DIST_COS_HI]
    step = (_DIST_COS_HI - _DIST_COS_LO) / (n - 1)
    return [_DIST_COS_HI - step * d for d in range(n)]


def aliasing_visual_corpus(
    *, n_clusters: int = 8, n_distractors: int = 5
) -> tuple[VisualGroundingCorpus, VectorTableBackend]:
    """Build the engineered aliasing corpus and its matching backend.

    Returns ``(corpus, backend)`` ready to hand to
    :func:`~semantic_toponav.eval.evaluate_visual_localizer`. There is one
    ``precise`` case per cluster (gold = that cluster's ``true`` node).

    With ``n_distractors >= 5`` the genuine place falls past rank 5 under
    raw cosine, so precision@1, recall@3 and recall@5 are all 0.00 at
    ``neighbor_weight=0.0`` and all 1.00 once aggregation is on — the
    cleanest aggregate demonstration of the lift. Smaller distractor counts
    still flip precision@1; they just leave recall@K already saturated.
    """
    if n_clusters < 1:
        raise ValueError(f"n_clusters must be >= 1, got {n_clusters}")
    if n_distractors < 1:
        raise ValueError(f"n_distractors must be >= 1, got {n_distractors}")

    dim = 2 * n_clusters
    graph = TopologyGraph()
    gallery: dict[str, str] = {}
    cases: list[VisualGroundingCase] = []
    table: dict[str, Vector] = {}
    dist_cos = _distractor_cosines(n_distractors)

    def _add(node_id: str, block: int, cos: float) -> None:
        graph.add_node(TopologyNode(id=node_id, label=node_id, type="place"))
        # node id doubles as its gallery lookup key
        gallery[node_id] = node_id
        table[node_id] = _unit_in_block(dim, block, cos)

    for c in range(n_clusters):
        true_id, corrob_id, weak_id = f"true_{c}", f"corrob_{c}", f"weak_{c}"
        _add(true_id, c, _TRUE_COS)
        _add(corrob_id, c, _CORROB_COS)
        _add(weak_id, c, _WEAK_COS)
        # true is corroborated by corrob; corrob's extra weak neighbor breaks
        # the symmetric true<->corrob blend so true stays the unique winner.
        graph.add_edge(
            TopologyEdge(id=f"e_true_{c}", source=true_id, target=corrob_id, type="adj")
        )
        graph.add_edge(
            TopologyEdge(id=f"e_weak_{c}", source=corrob_id, target=weak_id, type="adj")
        )

        for d, cos in enumerate(dist_cos):
            dist_id, lone_id = f"dist_{c}_{d}", f"lone_{c}_{d}"
            _add(dist_id, c, cos)
            _add(lone_id, c, _LONE_COS)
            # each look-alike is propped up only by a private low neighbor,
            # so neighbor aggregation collapses it below the genuine place.
            graph.add_edge(
                TopologyEdge(
                    id=f"e_dist_{c}_{d}", source=dist_id, target=lone_id, type="adj"
                )
            )

        query_key = f"query_{c}"
        table[query_key] = _unit_in_block(dim, c, 1.0)
        cases.append(
            VisualGroundingCase(image=query_key, gold=[true_id], kind="precise")
        )

    corpus = VisualGroundingCorpus(
        corpus_path="<aliasing-visual-corpus>",
        graph=graph,
        gallery=gallery,
        cases=cases,
    )
    return corpus, VectorTableBackend(table, dim)


@dataclass
class NeighborRerankAblation:
    """Two runs of the same corpus: raw cosine vs neighbor-aggregated."""

    baseline: VisualLocalizerEvaluation
    reranked: VisualLocalizerEvaluation
    neighbor_weight: float
    neighbor_hops: int


def neighbor_rerank_ablation(
    corpus: VisualGroundingCorpus,
    backend,  # noqa: ANN001 - any Backend
    *,
    neighbor_weight: float = 0.5,
    neighbor_hops: int = 1,
    top_k: int = 5,
    min_score: float = 0.0,
    encoder_name: str = "encoder",
) -> NeighborRerankAblation:
    """Run ``corpus`` twice — ``neighbor_weight=0`` then the given weight —
    and return both evaluations side by side.

    The baseline run is forced to ``neighbor_weight=0.0`` (raw single-frame
    cosine) regardless of the argument; ``neighbor_weight`` / ``neighbor_hops``
    parameterize the re-ranked run.
    """
    baseline = evaluate_visual_localizer(
        corpus, backend,
        encoder_name=f"{encoder_name} (raw)",
        top_k=top_k, min_score=min_score,
        neighbor_weight=0.0,
    )
    reranked = evaluate_visual_localizer(
        corpus, backend,
        encoder_name=f"{encoder_name} (+neighbor w={neighbor_weight})",
        top_k=top_k, min_score=min_score,
        neighbor_weight=neighbor_weight, neighbor_hops=neighbor_hops,
    )
    return NeighborRerankAblation(
        baseline=baseline,
        reranked=reranked,
        neighbor_weight=neighbor_weight,
        neighbor_hops=neighbor_hops,
    )


def neighbor_rerank_ablation_markdown(ablation: NeighborRerankAblation) -> str:
    """Render an ablation as a compact before/after markdown table."""
    b, r = ablation.baseline.metrics, ablation.reranked.metrics

    def _row(label: str, m) -> str:  # noqa: ANN001
        return (
            f"| {label} | {m.precision_at_1:.2f} | {m.recall_at_3:.2f} | "
            f"{m.recall_at_5:.2f} |"
        )

    return "\n".join(
        [
            "## Neighbor-aware re-ranking ablation (image -> node)",
            "",
            f"corpus: {ablation.baseline.metrics.n_total} cases, "
            f"neighbor_hops={ablation.neighbor_hops}",
            "",
            "| run | precision@1 | recall@3 | recall@5 |",
            "|---|---|---|---|",
            _row("raw cosine (neighbor_weight=0.0)", b),
            _row(f"+neighbor (weight={ablation.neighbor_weight})", r),
        ]
    ) + "\n"


__all__ = [
    "NeighborRerankAblation",
    "VectorTableBackend",
    "aliasing_visual_corpus",
    "neighbor_rerank_ablation",
    "neighbor_rerank_ablation_markdown",
]
