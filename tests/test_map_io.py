"""Tests for the ROS map_server YAML/PGM reader."""

from __future__ import annotations

from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("skimage")

from skimage.io import imsave

from semantic_toponav.conversion import (
    MapLoadError,
    load_occupancy_map,
    topology_from_occupancy,
)

REPO = Path(__file__).resolve().parents[1]
SAMPLE_YAML = REPO / "examples" / "sample_map.yaml"


def _write_map(
    tmp_path: Path,
    *,
    img: np.ndarray,
    resolution: float = 0.05,
    origin: list[float] | None = None,
    negate: int = 0,
    free_thresh: float = 0.196,
    occupied_thresh: float = 0.65,
    yaml_name: str = "map.yaml",
    img_name: str = "map.pgm",
) -> Path:
    img_path = tmp_path / img_name
    imsave(str(img_path), img)
    yaml_path = tmp_path / yaml_name
    origin = origin if origin is not None else [0.0, 0.0, 0.0]
    yaml_path.write_text(
        "image: {img}\n"
        "resolution: {res}\n"
        "origin: [{ox}, {oy}, {oyaw}]\n"
        "negate: {neg}\n"
        "occupied_thresh: {occ}\n"
        "free_thresh: {free}\n".format(
            img=img_name,
            res=resolution,
            ox=origin[0],
            oy=origin[1],
            oyaw=origin[2] if len(origin) >= 3 else 0.0,
            neg=negate,
            occ=occupied_thresh,
            free=free_thresh,
        ),
        encoding="utf-8",
    )
    return yaml_path


def test_load_bundled_sample_map() -> None:
    m = load_occupancy_map(SAMPLE_YAML)
    assert m.shape == (50, 80)
    assert m.resolution == 0.05
    assert m.origin == (-2.0, -1.25)
    assert m.free_mask.dtype == bool
    assert m.free_mask.any()


def test_white_pixels_become_free(tmp_path: Path) -> None:
    img = np.full((10, 20), 255, dtype=np.uint8)
    img[:, :10] = 0  # left half occupied
    yml = _write_map(tmp_path, img=img)
    m = load_occupancy_map(yml)
    # Right half should be free.
    assert m.free_mask[:, 10:].all()
    # Left half should be occupied.
    assert not m.free_mask[:, :10].any()


def test_negate_inverts_meaning(tmp_path: Path) -> None:
    img = np.full((10, 20), 255, dtype=np.uint8)
    img[:, :10] = 0
    yml = _write_map(tmp_path, img=img, negate=1)
    m = load_occupancy_map(yml)
    # With negate=1, white pixels are treated as occupied.
    assert not m.free_mask[:, 10:].any()
    assert m.free_mask[:, :10].all()


def test_origin_and_resolution_are_preserved(tmp_path: Path) -> None:
    img = np.full((5, 5), 255, dtype=np.uint8)
    yml = _write_map(tmp_path, img=img, resolution=0.1, origin=[3.5, -1.5, 0.5])
    m = load_occupancy_map(yml)
    assert m.resolution == 0.1
    assert m.origin == (3.5, -1.5)
    assert m.origin_yaw == 0.5


def test_missing_yaml_raises(tmp_path: Path) -> None:
    with pytest.raises(MapLoadError):
        load_occupancy_map(tmp_path / "nope.yaml")


def test_missing_image_raises(tmp_path: Path) -> None:
    yml = tmp_path / "map.yaml"
    yml.write_text(
        "image: missing.pgm\nresolution: 0.05\norigin: [0.0, 0.0, 0.0]\n",
        encoding="utf-8",
    )
    with pytest.raises(MapLoadError):
        load_occupancy_map(yml)


def test_missing_required_key_raises(tmp_path: Path) -> None:
    img = np.full((5, 5), 255, dtype=np.uint8)
    img_path = tmp_path / "map.pgm"
    imsave(str(img_path), img)
    yml = tmp_path / "map.yaml"
    yml.write_text("image: map.pgm\nresolution: 0.05\n", encoding="utf-8")  # no origin
    with pytest.raises(MapLoadError):
        load_occupancy_map(yml)


def test_loaded_map_round_trips_through_converter() -> None:
    m = load_occupancy_map(SAMPLE_YAML)
    g = topology_from_occupancy(
        m.free_mask, resolution=m.resolution, origin=m.origin
    )
    assert len(g.node_ids()) > 0
    assert len(g.edge_ids()) > 0
    # Poses should land inside the world bounds.
    h, w = m.shape
    x_max = m.origin[0] + w * m.resolution
    y_max = m.origin[1] + h * m.resolution
    for n in g.nodes():
        assert n.pose is not None
        assert m.origin[0] <= n.pose.x <= x_max
        assert m.origin[1] <= n.pose.y <= y_max
