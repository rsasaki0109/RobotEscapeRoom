"""Tests for :class:`AlignedRgbSource` and its
:class:`StaticImageRgbSource` reference implementation, plus the
``rgb_source`` plug-point on :func:`embed_region_patches`.

Goal: prove the embedding pipeline can be redirected from the
occupancy grid to a real-world RGB image *without changing anything
in the encoder layer* — so downstream packages (the planned
``semantic-toponav-mast3r`` adapter, top-down cameras, NeRF
rerenders, …) only have to implement the protocol.
"""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("skimage")
pytest.importorskip("scipy")

from semantic_toponav.conversion.occupancy import (  # noqa: E402
    annotate_regions,
    topology_from_occupancy,
)
from semantic_toponav.conversion.vlm import embed_region_patches  # noqa: E402
from semantic_toponav.encoders import (  # noqa: E402
    AlignedRgbSource,
    HashingBackend,
    StaticImageRgbSource,
)

# --------------------------- helpers ---------------------------


def _two_disjoint_rooms() -> np.ndarray:
    grid = np.zeros((11, 21), dtype=bool)
    grid[2:9, 1:8] = True
    grid[2:9, 13:20] = True
    return grid


def _aligned_rgb(grid: np.ndarray) -> np.ndarray:
    """Build an RGB image in the same coordinate frame as ``grid``."""
    h, w = grid.shape
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    rgb[..., 0] = grid.astype(np.uint8) * 200
    rgb[..., 1] = grid.astype(np.uint8) * 80
    rgb[..., 2] = (~grid).astype(np.uint8) * 50
    return rgb


# --------------------------- StaticImageRgbSource ---------------------------


def test_static_source_reports_shape() -> None:
    rgb = np.zeros((7, 11, 3), dtype=np.uint8)
    src = StaticImageRgbSource(rgb)
    assert src.shape == (7, 11)


def test_static_source_satisfies_protocol() -> None:
    src = StaticImageRgbSource(np.zeros((4, 4, 3), dtype=np.uint8))
    assert isinstance(src, AlignedRgbSource)


def test_static_source_rejects_non_rgb_shape() -> None:
    with pytest.raises(ValueError):
        StaticImageRgbSource(np.zeros((4, 4), dtype=np.uint8))
    with pytest.raises(ValueError):
        StaticImageRgbSource(np.zeros((4, 4, 4), dtype=np.uint8))


def test_static_source_crop_matches_numpy_slicing() -> None:
    rgb = np.arange(7 * 11 * 3, dtype=np.uint8).reshape(7, 11, 3)
    src = StaticImageRgbSource(rgb)
    patch = src.crop((1, 2, 4, 9))
    np.testing.assert_array_equal(patch, rgb[1:5, 2:10])


def test_static_source_rejects_out_of_bounds_bbox() -> None:
    src = StaticImageRgbSource(np.zeros((5, 5, 3), dtype=np.uint8))
    with pytest.raises(ValueError):
        src.crop((0, 0, 10, 10))
    with pytest.raises(ValueError):
        src.crop((-1, 0, 2, 2))
    with pytest.raises(ValueError):
        src.crop((3, 3, 1, 1))


# --------------------------- embed_region_patches plumbing ---------------------------


def test_embed_uses_rgb_source_when_provided() -> None:
    grid = _two_disjoint_rooms()
    rgb = _aligned_rgb(grid)
    # Make the RGB version distinguishable from the occupancy version
    # for at least one region — stamp a high-saturation marker into
    # the left room only.
    rgb[3, 3] = (255, 0, 0)

    graph = topology_from_occupancy(grid, resolution=1.0)
    regions = annotate_regions(graph, grid, resolution=1.0)
    backend = HashingBackend(dim=32)

    occ_result = embed_region_patches(graph, grid, regions, backend)
    assert occ_result.source == "occupancy"

    # Reset stamped properties so the second pass is fair.
    for node in graph.nodes():
        node.properties.pop("embedding", None)

    src = StaticImageRgbSource(rgb)
    rgb_result = embed_region_patches(
        graph, grid, regions, backend, rgb_source=src
    )
    assert rgb_result.source == "rgb_source"

    # The two pipelines saw different pixel content, so at least one
    # region's vector must differ. (Empty / fully-zero patches would
    # collide; we picked a marker pixel to avoid that.)
    diffs = [
        rgb_result.region_embeddings[rid] != occ_result.region_embeddings[rid]
        for rid in occ_result.region_embeddings
    ]
    assert any(diffs), (
        "rgb_source path produced identical vectors to the occupancy "
        "path — the plug-point is not actually being used"
    )


def test_embed_rejects_misaligned_rgb_source() -> None:
    grid = _two_disjoint_rooms()
    graph = topology_from_occupancy(grid, resolution=1.0)
    regions = annotate_regions(graph, grid, resolution=1.0)
    backend = HashingBackend(dim=16)

    # Wrong-shape source — must be rejected up front.
    wrong = StaticImageRgbSource(np.zeros((5, 5, 3), dtype=np.uint8))
    with pytest.raises(ValueError, match="does not match image shape"):
        embed_region_patches(graph, grid, regions, backend, rgb_source=wrong)


def test_embed_with_rgb_source_still_stamps_member_nodes() -> None:
    grid = _two_disjoint_rooms()
    graph = topology_from_occupancy(grid, resolution=1.0)
    regions = annotate_regions(graph, grid, resolution=1.0)
    backend = HashingBackend(dim=16)

    src = StaticImageRgbSource(_aligned_rgb(grid))
    result = embed_region_patches(
        graph, grid, regions, backend, rgb_source=src
    )
    # Every region was stamped; every kept node carries the vector.
    assert len(result.region_embeddings) == len(regions.regions)
    assert result.node_ids
    for node_id in result.node_ids:
        emb = graph.get_node(node_id).properties["embedding"]
        assert len(emb) == 16


def test_embed_rgb_source_honors_include_filter() -> None:
    grid = _two_disjoint_rooms()
    graph = topology_from_occupancy(grid, resolution=1.0)
    regions = annotate_regions(graph, grid, resolution=1.0)
    backend = HashingBackend(dim=16)
    src = StaticImageRgbSource(_aligned_rgb(grid))

    keep, _drop = sorted(regions.regions.keys())
    result = embed_region_patches(
        graph,
        grid,
        regions,
        backend,
        include=[keep],
        rgb_source=src,
    )
    assert list(result.region_embeddings.keys()) == [keep]


def test_custom_rgb_source_satisfies_protocol() -> None:
    """A user-written source (think Mast3R adapter) only needs to
    expose ``shape`` and ``crop`` — no inheritance required."""

    class ConstantPatchSource:
        def __init__(self, height: int, width: int) -> None:
            self._h = height
            self._w = width
            self._patch = np.full((3, 3, 3), 128, dtype=np.uint8)
            self.calls: list[tuple[int, int, int, int]] = []

        @property
        def shape(self) -> tuple[int, int]:
            return self._h, self._w

        def crop(self, bbox: tuple[int, int, int, int]) -> np.ndarray:
            self.calls.append(bbox)
            return self._patch

    grid = _two_disjoint_rooms()
    graph = topology_from_occupancy(grid, resolution=1.0)
    regions = annotate_regions(graph, grid, resolution=1.0)
    backend = HashingBackend(dim=16)

    src = ConstantPatchSource(grid.shape[0], grid.shape[1])
    assert isinstance(src, AlignedRgbSource)

    result = embed_region_patches(
        graph, grid, regions, backend, rgb_source=src
    )
    # Source was actually consulted once per kept region.
    assert len(src.calls) == len(result.region_embeddings) == len(regions.regions)
