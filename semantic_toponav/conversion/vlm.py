"""Bridge between :func:`annotate_regions` and a VLM / CLIP encoder.

:func:`annotate_regions` returns a :class:`RegionAnnotationResult` whose
``regions`` map carries an :class:`RegionInfo` per labeled component —
crucially, ``bbox_cells`` (inclusive ``(min_row, min_col, max_row,
max_col)`` in image pixel coordinates). That is exactly the patch
anchor an image encoder wants: crop the image to the bbox, embed the
patch, and stamp the resulting vector onto every node carrying the
matching ``region_id`` property.

The result is that every room (or whatever connected component the
labeler isolated) ends up with a semantic vector attached to all of its
nodes, which the existing
:func:`semantic_toponav.query.find_nodes_by_embedding` /
:func:`~semantic_toponav.query.nearest_node_by_embedding` helpers can
query against — closing the loop on "natural-language → topology node"
without a separate encoder integration.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from semantic_toponav.conversion.occupancy import (
    RegionAnnotationResult,
    RegionInfo,
)
from semantic_toponav.encoders.backends import Backend, Vector
from semantic_toponav.graph.topology_graph import TopologyGraph


@dataclass
class RegionEmbeddingResult:
    """Summary returned by :func:`embed_region_patches`.

    Attributes
    ----------
    region_embeddings:
        ``region_id -> vector`` for every region that produced an
        embedding. Skipped regions (empty bbox, out-of-bounds clip,
        ``include`` filter excluded them) are absent from this map.
    node_ids:
        Ids of nodes that received an embedding stamp on this run.
        A single node appears at most once here.
    backend_dim:
        Dimensionality reported by the backend at write time. Stored
        so callers can sanity-check what got persisted.
    """

    region_embeddings: dict[int, Vector] = field(default_factory=dict)
    node_ids: list[str] = field(default_factory=list)
    backend_dim: int = 0


def _resolve_bbox(
    info: RegionInfo,
    *,
    height: int,
    width: int,
    pad_cells: int,
) -> tuple[int, int, int, int] | None:
    """Clamp ``info.bbox_cells`` to image bounds + apply ``pad_cells``.

    Returns ``None`` if the resulting box is empty after clipping.
    """
    rmin, cmin, rmax, cmax = info.bbox_cells
    rmin = max(0, rmin - pad_cells)
    cmin = max(0, cmin - pad_cells)
    rmax = min(height - 1, rmax + pad_cells)
    cmax = min(width - 1, cmax + pad_cells)
    if rmax < rmin or cmax < cmin:
        return None
    return rmin, cmin, rmax, cmax


def embed_region_patches(
    graph: TopologyGraph,
    image: Any,
    regions: RegionAnnotationResult,
    backend: Backend,
    *,
    embedding_property: str = "embedding",
    region_id_property: str = "region_id",
    pad_cells: int = 0,
    include: Iterable[int] | None = None,
) -> RegionEmbeddingResult:
    """Embed each region's image patch and stamp it onto its member nodes.

    Parameters
    ----------
    graph:
        Topology graph. Mutated in place: nodes carrying
        ``properties[region_id_property]`` receive the corresponding
        region's vector under ``properties[embedding_property]``.
        Nodes without a region id (e.g. nodes pinched into a doorway
        by :func:`annotate_regions`) are left alone.
    image:
        Source image. Either a 2D / 3D NumPy array (rows × cols [×
        channels]) or any value the backend's ``embed_image`` accepts
        directly — but cropping requires array semantics, so a pure
        path is only useful when ``len(regions.regions) == 1`` and you
        want the whole image as the patch (in which case
        :meth:`Backend.embed_image` is called once, no crop).
    regions:
        Output of :func:`annotate_regions` — provides each region's
        bounding box in image pixel coordinates.
    backend:
        Encoder. Any object that satisfies the
        :class:`~semantic_toponav.encoders.backends.Backend` protocol.
    embedding_property:
        Property key under which the vector is stamped on each node.
        Defaults to ``"embedding"`` to match the convention used by
        :func:`semantic_toponav.query.find_nodes_by_embedding`.
    region_id_property:
        Property key the graph nodes use to record their region. Must
        match what was used when :func:`annotate_regions` ran.
    pad_cells:
        Optional padding added to every bbox before cropping. Useful
        for giving CLIP a little context around the room boundary.
        Clipped to image bounds. ``0`` means crop the bbox exactly.
    include:
        Optional iterable of region ids to embed. ``None`` (default)
        embeds every region present in ``regions.regions``.

    Returns
    -------
    RegionEmbeddingResult
        Per-region vectors plus the ids of stamped nodes.
    """
    try:
        import numpy as np
    except ImportError as exc:
        raise ImportError(
            "embed_region_patches requires numpy. Install with "
            "`pip install 'semantic-toponav[map]'`"
        ) from exc

    arr = np.asarray(image)
    if arr.ndim not in (2, 3):
        raise ValueError(
            f"image must be 2D or 3D, got shape {arr.shape}"
        )
    height, width = arr.shape[:2]

    include_set: set[int] | None = set(include) if include is not None else None

    patches: list[Any] = []
    kept_ids: list[int] = []
    for rid, info in sorted(regions.regions.items()):
        if include_set is not None and rid not in include_set:
            continue
        box = _resolve_bbox(info, height=height, width=width, pad_cells=pad_cells)
        if box is None:
            continue
        rmin, cmin, rmax, cmax = box
        patches.append(arr[rmin:rmax + 1, cmin:cmax + 1])
        kept_ids.append(rid)

    result = RegionEmbeddingResult(backend_dim=int(backend.dim))
    if not patches:
        return result

    vectors = backend.embed_images(patches)
    if len(vectors) != len(patches):
        raise RuntimeError(
            f"backend returned {len(vectors)} vectors for {len(patches)} patches"
        )

    for rid, vec in zip(kept_ids, vectors, strict=True):
        result.region_embeddings[rid] = [float(x) for x in vec]

    for node in graph.nodes():
        rid = node.properties.get(region_id_property)
        if not isinstance(rid, int):
            continue
        vec = result.region_embeddings.get(rid)
        if vec is None:
            continue
        node.properties[embedding_property] = list(vec)
        result.node_ids.append(node.id)

    return result
