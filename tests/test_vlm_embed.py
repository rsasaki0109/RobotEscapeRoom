"""Tests for :func:`embed_region_patches` and the ``embed-regions`` CLI.

Gated on the ``[map]`` extra (NumPy + scikit-image + scipy) so that the
helper bbox plumbing through ``annotate_regions`` stays exercised, but
the actual encoder used is the deterministic :class:`HashingBackend` so
no CLIP / torch dependency is required.
"""

from __future__ import annotations

from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("skimage")
pytest.importorskip("scipy")

from skimage.io import imsave  # noqa: E402

from semantic_toponav.cli.main import main  # noqa: E402
from semantic_toponav.conversion.occupancy import (  # noqa: E402
    annotate_regions,
    topology_from_occupancy,
)
from semantic_toponav.conversion.vlm import embed_region_patches  # noqa: E402
from semantic_toponav.encoders.backends import HashingBackend  # noqa: E402
from semantic_toponav.graph.serialization import load_graph  # noqa: E402

# --------------------------- helpers ---------------------------


def _two_disjoint_rooms() -> np.ndarray:
    grid = np.zeros((11, 21), dtype=bool)
    grid[2:9, 1:8] = True
    grid[2:9, 13:20] = True
    return grid


def _single_room() -> np.ndarray:
    grid = np.zeros((9, 11), dtype=bool)
    grid[2:7, 2:9] = True
    return grid


def _write_map(
    tmp_path: Path,
    *,
    img: np.ndarray,
    yaml_name: str = "map.yaml",
    img_name: str = "map.pgm",
) -> Path:
    pixels = np.where(img.astype(bool), 255, 0).astype(np.uint8)
    img_path = tmp_path / img_name
    imsave(str(img_path), pixels)
    yaml_path = tmp_path / yaml_name
    yaml_path.write_text(
        f"image: {img_name}\n"
        f"resolution: 1.0\n"
        f"origin: [0.0, 0.0, 0.0]\n"
        f"negate: 0\n"
        f"occupied_thresh: 0.65\n"
        f"free_thresh: 0.196\n",
        encoding="utf-8",
    )
    return yaml_path


# --------------------------- embed_region_patches ---------------------------


def test_embed_single_region_stamps_all_member_nodes() -> None:
    grid = _single_room()
    graph = topology_from_occupancy(grid, resolution=1.0)
    regions = annotate_regions(graph, grid, resolution=1.0)
    assert len(regions.regions) == 1

    backend = HashingBackend(dim=16)
    result = embed_region_patches(graph, grid, regions, backend)

    assert len(result.region_embeddings) == 1
    assert result.backend_dim == 16
    # Every stamped node carries the region's vector.
    (only_rid, only_vec) = next(iter(result.region_embeddings.items()))
    assert result.node_ids
    for node_id in result.node_ids:
        assert graph.get_node(node_id).properties["embedding"] == only_vec
        assert graph.get_node(node_id).properties["region_id"] == only_rid


def test_embed_two_rooms_produce_distinct_vectors() -> None:
    grid = _two_disjoint_rooms()
    graph = topology_from_occupancy(grid, resolution=1.0)
    regions = annotate_regions(graph, grid, resolution=1.0)
    assert len(regions.regions) == 2

    # Use different per-room content so the patches differ when cropped.
    image = grid.astype(np.uint8) * 255
    image[3, 3] = 42  # mark the left room
    image[3, 16] = 200  # mark the right room
    backend = HashingBackend(dim=32)
    result = embed_region_patches(graph, image, regions, backend)

    assert len(result.region_embeddings) == 2
    v1, v2 = result.region_embeddings.values()
    assert v1 != v2


def test_embed_skips_nodes_without_region_id() -> None:
    grid = _single_room()
    graph = topology_from_occupancy(grid, resolution=1.0)
    regions = annotate_regions(graph, grid, resolution=1.0)

    # Drop region_id from one node to simulate an unannotated graph node.
    target = next(iter(graph.nodes()))
    target.properties.pop("region_id", None)

    backend = HashingBackend(dim=16)
    result = embed_region_patches(graph, grid, regions, backend)
    assert target.id not in result.node_ids
    assert "embedding" not in target.properties


def test_embed_include_filter_only_writes_requested_regions() -> None:
    grid = _two_disjoint_rooms()
    graph = topology_from_occupancy(grid, resolution=1.0)
    regions = annotate_regions(graph, grid, resolution=1.0)
    rid_keep, _rid_drop = sorted(regions.regions.keys())

    backend = HashingBackend(dim=16)
    result = embed_region_patches(
        graph, grid, regions, backend, include=[rid_keep]
    )
    assert list(result.region_embeddings.keys()) == [rid_keep]
    for node in graph.nodes():
        if node.properties.get("region_id") == rid_keep:
            assert "embedding" in node.properties
        else:
            # Other-region nodes must not receive a vector.
            assert "embedding" not in node.properties


def test_embed_pad_cells_expands_bbox() -> None:
    grid = _single_room()
    graph = topology_from_occupancy(grid, resolution=1.0)
    regions = annotate_regions(graph, grid, resolution=1.0)
    backend = HashingBackend(dim=16)

    a = embed_region_patches(graph, grid, regions, backend, pad_cells=0)
    # Reset for a fair comparison.
    for node in graph.nodes():
        node.properties.pop("embedding", None)
    b = embed_region_patches(graph, grid, regions, backend, pad_cells=2)

    # The crop region differs in size, so the hashing vector must differ.
    [va] = a.region_embeddings.values()
    [vb] = b.region_embeddings.values()
    assert va != vb


def test_embed_empty_regions_returns_empty_result() -> None:
    grid = np.zeros((4, 4), dtype=bool)
    graph = topology_from_occupancy(grid, resolution=1.0)
    regions = annotate_regions(graph, grid, resolution=1.0)
    assert regions.regions == {}
    result = embed_region_patches(
        graph, np.zeros((4, 4), dtype=np.uint8), regions, HashingBackend()
    )
    assert result.region_embeddings == {}
    assert result.node_ids == []


def test_embed_rejects_non_2d_3d_image() -> None:
    grid = _single_room()
    graph = topology_from_occupancy(grid, resolution=1.0)
    regions = annotate_regions(graph, grid, resolution=1.0)
    backend = HashingBackend(dim=16)
    bogus = np.zeros((2, 2, 3, 3), dtype=np.uint8)
    with pytest.raises(ValueError):
        embed_region_patches(graph, bogus, regions, backend)


def test_embed_round_trips_through_find_nodes_by_embedding() -> None:
    """A node stamped with a region embedding should round-trip cleanly
    through the existing similarity helpers — confirming the
    ``embedding`` property name is the right one."""
    from semantic_toponav.query import find_nodes_by_embedding

    grid = _two_disjoint_rooms()
    graph = topology_from_occupancy(grid, resolution=1.0)
    regions = annotate_regions(graph, grid, resolution=1.0)
    image = grid.astype(np.uint8) * 255
    image[3, 3] = 7
    image[3, 16] = 200
    backend = HashingBackend(dim=32)
    result = embed_region_patches(graph, image, regions, backend)
    rid_a, rid_b = sorted(result.region_embeddings.keys())

    # Query with one region's vector; the top match must be from the same region.
    query_vec = result.region_embeddings[rid_a]
    matches = find_nodes_by_embedding(graph, query_vec, top_k=1)
    top_node, top_score = matches[0]
    assert top_node.properties["region_id"] == rid_a
    assert top_score == pytest.approx(1.0, abs=1e-6)


# --------------------------- CLI ---------------------------


def test_cli_embed_regions_stamps_in_place(tmp_path: Path) -> None:
    grid = _two_disjoint_rooms()
    map_yaml = _write_map(tmp_path, img=grid)
    graph_path = tmp_path / "graph.yaml"

    rc = main(["from-occupancy", str(map_yaml), "--out", str(graph_path), "--no-backup"])
    assert rc == 0

    rc = main([
        "embed-regions",
        str(graph_path),
        str(map_yaml),
        "--backend", "hashing",
        "--dim", "32",
        "--in-place",
        "--no-backup",
    ])
    assert rc == 0

    graph = load_graph(graph_path)
    stamped = [n for n in graph.nodes() if "embedding" in n.properties]
    assert stamped, "expected at least one node to receive an embedding"
    for node in stamped:
        vec = node.properties["embedding"]
        assert len(vec) == 32
        assert all(isinstance(x, float) for x in vec)


def test_cli_embed_regions_include_filter(tmp_path: Path) -> None:
    grid = _two_disjoint_rooms()
    map_yaml = _write_map(tmp_path, img=grid)
    graph_path = tmp_path / "graph.yaml"

    rc = main(["from-occupancy", str(map_yaml), "--out", str(graph_path), "--no-backup"])
    assert rc == 0

    rc = main([
        "embed-regions",
        str(graph_path),
        str(map_yaml),
        "--backend", "hashing",
        "--include-region", "1",
        "--in-place",
        "--no-backup",
    ])
    assert rc == 0

    graph = load_graph(graph_path)
    stamped = [
        n for n in graph.nodes()
        if "embedding" in n.properties
    ]
    assert stamped
    for node in stamped:
        assert node.properties["region_id"] == 1


def test_cli_embed_regions_rejects_mismatched_image(tmp_path: Path) -> None:
    grid = _two_disjoint_rooms()
    map_yaml = _write_map(tmp_path, img=grid)
    graph_path = tmp_path / "graph.yaml"
    rc = main(["from-occupancy", str(map_yaml), "--out", str(graph_path), "--no-backup"])
    assert rc == 0

    # Write a deliberately wrong-shape image.
    wrong_image = tmp_path / "wrong.pgm"
    imsave(str(wrong_image), np.zeros((4, 4), dtype=np.uint8))

    rc = main([
        "embed-regions",
        str(graph_path),
        str(map_yaml),
        "--image", str(wrong_image),
        "--backend", "hashing",
        "--in-place",
        "--no-backup",
    ])
    assert rc == 2


def test_cli_embed_regions_both_threshold_knobs_rejected(tmp_path: Path) -> None:
    grid = _single_room()
    map_yaml = _write_map(tmp_path, img=grid)
    graph_path = tmp_path / "graph.yaml"
    rc = main(["from-occupancy", str(map_yaml), "--out", str(graph_path), "--no-backup"])
    assert rc == 0

    rc = main([
        "embed-regions",
        str(graph_path),
        str(map_yaml),
        "--clearance-threshold", "1.0",
        "--clearance-percentile", "50",
        "--in-place",
        "--no-backup",
    ])
    assert rc == 2
