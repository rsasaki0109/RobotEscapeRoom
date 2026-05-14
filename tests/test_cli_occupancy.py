"""Tests for the occupancy-pipeline CLI subcommands."""

from __future__ import annotations

from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("skimage")
pytest.importorskip("scipy")

from skimage.io import imsave

from semantic_toponav.cli.main import main
from semantic_toponav.graph.serialization import load_graph


def _write_map(
    tmp_path: Path,
    *,
    img: np.ndarray,
    resolution: float = 1.0,
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
    yaml_name: str = "map.yaml",
    img_name: str = "map.pgm",
    negate: int = 0,
    free_thresh: float = 0.196,
    occupied_thresh: float = 0.65,
) -> Path:
    """Write a map_server bundle that interprets white pixels as free.

    The supplied ``img`` is treated as the free mask: ``True`` cells
    become white (255) in the PGM and load back as free under the
    default ROS interpretation (``negate=0``, ``occupied_thresh=0.65``).
    """
    pixels = np.where(img.astype(bool), 255, 0).astype(np.uint8)
    img_path = tmp_path / img_name
    imsave(str(img_path), pixels)
    yaml_path = tmp_path / yaml_name
    yaml_path.write_text(
        f"image: {img_name}\n"
        f"resolution: {resolution}\n"
        f"origin: [{origin[0]}, {origin[1]}, {origin[2]}]\n"
        f"negate: {negate}\n"
        f"occupied_thresh: {occupied_thresh}\n"
        f"free_thresh: {free_thresh}\n",
        encoding="utf-8",
    )
    return yaml_path


def _two_rooms_with_doorway() -> np.ndarray:
    """Two 7x7 rooms joined by a 1-cell-wide doorway. Returns the free mask."""
    h, w = 13, 21
    grid = np.zeros((h, w), dtype=bool)
    grid[2:9, 1:8] = True
    grid[2:9, 13:20] = True
    grid[5, 8:13] = True
    return grid


def _straight_corridor() -> np.ndarray:
    """A simple 1xN corridor — yields two endpoints + one edge."""
    grid = np.zeros((5, 15), dtype=bool)
    grid[2, 1:14] = True
    return grid


# --------------------------- from-occupancy ---------------------------


def test_from_occupancy_writes_graph(tmp_path: Path) -> None:
    map_yaml = _write_map(tmp_path, img=_straight_corridor())
    out_path = tmp_path / "graph.yaml"

    rc = main(["from-occupancy", str(map_yaml), "--out", str(out_path)])
    assert rc == 0
    assert out_path.exists()

    g = load_graph(out_path)
    assert len(g.node_ids()) == 2
    assert len(g.edge_ids()) == 1


def test_from_occupancy_respects_overrides(tmp_path: Path) -> None:
    map_yaml = _write_map(tmp_path, img=_straight_corridor())
    out_path = tmp_path / "graph.yaml"

    rc = main(
        [
            "from-occupancy",
            str(map_yaml),
            "--out",
            str(out_path),
            "--endpoint-type",
            "tip",
            "--edge-type",
            "hall",
            "--id-prefix",
            "demo_",
            "--frame-id",
            "world",
        ]
    )
    assert rc == 0

    g = load_graph(out_path)
    nodes = list(g.nodes())
    assert all(n.type == "tip" for n in nodes)
    assert all(n.id.startswith("demo_n_") for n in nodes)
    assert all(n.pose is not None and n.pose.frame_id == "world" for n in nodes)
    edges = list(g.edges())
    assert all(e.type == "hall" for e in edges)


def test_from_occupancy_creates_backup_when_output_exists(tmp_path: Path) -> None:
    map_yaml = _write_map(tmp_path, img=_straight_corridor())
    out_path = tmp_path / "graph.yaml"
    out_path.write_text("placeholder: true\n", encoding="utf-8")

    rc = main(["from-occupancy", str(map_yaml), "--out", str(out_path)])
    assert rc == 0
    assert (tmp_path / "graph.yaml.bak").exists()


def test_from_occupancy_no_backup_flag(tmp_path: Path) -> None:
    map_yaml = _write_map(tmp_path, img=_straight_corridor())
    out_path = tmp_path / "graph.yaml"
    out_path.write_text("placeholder: true\n", encoding="utf-8")

    rc = main(
        ["from-occupancy", str(map_yaml), "--out", str(out_path), "--no-backup"]
    )
    assert rc == 0
    assert not (tmp_path / "graph.yaml.bak").exists()


def test_from_occupancy_missing_map(tmp_path: Path, capsys) -> None:
    rc = main(
        ["from-occupancy", str(tmp_path / "nope.yaml"), "--out", str(tmp_path / "g.yaml")]
    )
    assert rc == 2
    assert "error" in capsys.readouterr().err


# --------------------------- mark-doors ---------------------------


def test_mark_doors_in_place_flags_doorway(tmp_path: Path) -> None:
    grid = _two_rooms_with_doorway()
    map_yaml = _write_map(tmp_path, img=grid)
    graph_path = tmp_path / "graph.yaml"

    rc = main(["from-occupancy", str(map_yaml), "--out", str(graph_path)])
    assert rc == 0

    rc = main(
        [
            "mark-doors",
            str(graph_path),
            str(map_yaml),
            "--clearance-threshold",
            "1.5",
            "--in-place",
            "--no-backup",
        ]
    )
    assert rc == 0

    g = load_graph(graph_path)
    door_edges = [e for e in g.edges() if e.type == "door"]
    assert door_edges, "expected the doorway edge to be re-typed"


def test_mark_doors_writes_to_out(tmp_path: Path) -> None:
    grid = _two_rooms_with_doorway()
    map_yaml = _write_map(tmp_path, img=grid)
    src_path = tmp_path / "src.yaml"
    out_path = tmp_path / "marked.yaml"

    main(["from-occupancy", str(map_yaml), "--out", str(src_path)])

    rc = main(
        [
            "mark-doors",
            str(src_path),
            str(map_yaml),
            "--clearance-threshold",
            "1.5",
            "--out",
            str(out_path),
            "--no-backup",
        ]
    )
    assert rc == 0
    assert out_path.exists()
    # The source file must be untouched.
    assert all(e.type != "door" for e in load_graph(src_path).edges())
    assert any(e.type == "door" for e in load_graph(out_path).edges())


def test_mark_doors_rejects_both_threshold_knobs(tmp_path: Path, capsys) -> None:
    grid = _two_rooms_with_doorway()
    map_yaml = _write_map(tmp_path, img=grid)
    graph_path = tmp_path / "g.yaml"
    main(["from-occupancy", str(map_yaml), "--out", str(graph_path)])

    rc = main(
        [
            "mark-doors",
            str(graph_path),
            str(map_yaml),
            "--clearance-threshold",
            "1.0",
            "--clearance-percentile",
            "30",
        ]
    )
    assert rc == 2
    assert "at most one" in capsys.readouterr().err


def test_mark_doors_to_stdout_default(tmp_path: Path, capsys) -> None:
    grid = _two_rooms_with_doorway()
    map_yaml = _write_map(tmp_path, img=grid)
    graph_path = tmp_path / "g.yaml"
    main(["from-occupancy", str(map_yaml), "--out", str(graph_path)])

    rc = main(
        [
            "mark-doors",
            str(graph_path),
            str(map_yaml),
            "--clearance-threshold",
            "1.5",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "nodes:" in out and "edges:" in out


def test_mark_doors_no_mark_edges_leaves_edges(tmp_path: Path) -> None:
    grid = _two_rooms_with_doorway()
    map_yaml = _write_map(tmp_path, img=grid)
    graph_path = tmp_path / "g.yaml"
    main(["from-occupancy", str(map_yaml), "--out", str(graph_path)])

    rc = main(
        [
            "mark-doors",
            str(graph_path),
            str(map_yaml),
            "--clearance-threshold",
            "1.5",
            "--no-mark-edges",
            "--in-place",
            "--no-backup",
        ]
    )
    assert rc == 0

    g = load_graph(graph_path)
    assert all(e.type != "door" for e in g.edges())


# --------------------------- annotate-regions ---------------------------


def test_annotate_regions_stamps_region_id(tmp_path: Path) -> None:
    grid = _two_rooms_with_doorway()
    map_yaml = _write_map(tmp_path, img=grid)
    graph_path = tmp_path / "g.yaml"
    main(["from-occupancy", str(map_yaml), "--out", str(graph_path)])

    rc = main(
        [
            "annotate-regions",
            str(graph_path),
            str(map_yaml),
            "--clearance-threshold",
            "1.5",
            "--in-place",
            "--no-backup",
        ]
    )
    assert rc == 0

    g = load_graph(graph_path)
    stamped = [n for n in g.nodes() if "region_id" in n.properties]
    assert stamped, "expected at least one node stamped with region_id"
    # Two-room geometry under pinching → at most one or two distinct ids.
    ids = {n.properties["region_id"] for n in stamped}
    assert ids <= {1, 2}


def test_annotate_regions_show_regions_prints_summary(
    tmp_path: Path, capsys
) -> None:
    grid = _two_rooms_with_doorway()
    map_yaml = _write_map(tmp_path, img=grid)
    graph_path = tmp_path / "g.yaml"
    main(["from-occupancy", str(map_yaml), "--out", str(graph_path)])
    capsys.readouterr()  # clear

    rc = main(
        [
            "annotate-regions",
            str(graph_path),
            str(map_yaml),
            "--clearance-threshold",
            "1.5",
            "--show-regions",
            "--in-place",
            "--no-backup",
        ]
    )
    assert rc == 0
    err = capsys.readouterr().err
    assert "region 1:" in err
    assert "centroid=" in err


def test_annotate_regions_min_area_filters(tmp_path: Path) -> None:
    # Two big rooms plus a single isolated free cell that should be filtered.
    grid = _two_rooms_with_doorway()
    grid[0, 0] = True
    map_yaml = _write_map(tmp_path, img=grid)
    graph_path = tmp_path / "g.yaml"
    main(["from-occupancy", str(map_yaml), "--out", str(graph_path)])

    rc = main(
        [
            "annotate-regions",
            str(graph_path),
            str(map_yaml),
            "--clearance-threshold",
            "1.5",
            "--min-region-area",
            "5",
            "--show-regions",
            "--in-place",
            "--no-backup",
        ]
    )
    assert rc == 0


def test_annotate_regions_to_stdout_default(tmp_path: Path, capsys) -> None:
    grid = _two_rooms_with_doorway()
    map_yaml = _write_map(tmp_path, img=grid)
    graph_path = tmp_path / "g.yaml"
    main(["from-occupancy", str(map_yaml), "--out", str(graph_path)])

    rc = main(["annotate-regions", str(graph_path), str(map_yaml)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "nodes:" in out


def test_annotate_regions_rejects_both_threshold_knobs(
    tmp_path: Path, capsys
) -> None:
    grid = _two_rooms_with_doorway()
    map_yaml = _write_map(tmp_path, img=grid)
    graph_path = tmp_path / "g.yaml"
    main(["from-occupancy", str(map_yaml), "--out", str(graph_path)])

    rc = main(
        [
            "annotate-regions",
            str(graph_path),
            str(map_yaml),
            "--clearance-threshold",
            "1.0",
            "--clearance-percentile",
            "30",
        ]
    )
    assert rc == 2
    assert "at most one" in capsys.readouterr().err
