"""Tests for the CSV trajectory loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from semantic_toponav.conversion import (
    CsvTrajectoryLoadError,
    load_trajectories_from_csv,
    topology_from_trajectories,
)

REPO = Path(__file__).resolve().parents[1]
SAMPLE = REPO / "examples" / "sample_trajectories.csv"


def _write(tmp_path: Path, content: str, name: str = "traj.csv") -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# --------------------------- bundled sample ---------------------------


def test_load_bundled_sample() -> None:
    trajs = load_trajectories_from_csv(SAMPLE)
    assert len(trajs) == 3
    for traj in trajs:
        assert len(traj) > 0
        for p in traj:
            assert len(p) == 2
            assert isinstance(p[0], float)


def test_bundled_sample_round_trips_through_converter() -> None:
    trajs = load_trajectories_from_csv(SAMPLE)
    g = topology_from_trajectories(trajs, eps=1.5, min_samples=2)
    assert len(g.node_ids()) > 0
    assert len(g.edge_ids()) > 0


# --------------------------- header-based loading ---------------------------


def test_header_single_trajectory(tmp_path: Path) -> None:
    p = _write(tmp_path, "x,y\n0,0\n1,0\n2,0\n")
    trajs = load_trajectories_from_csv(p)
    assert trajs == [[(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]]


def test_header_multiple_trajectories_grouped_by_id(tmp_path: Path) -> None:
    csv = "trajectory_id,x,y\nA,0,0\nA,1,0\nB,5,5\nA,2,0\nB,6,5\n"
    p = _write(tmp_path, csv)
    trajs = load_trajectories_from_csv(p)
    assert len(trajs) == 2
    # Group order should follow first-appearance: A then B.
    assert trajs[0] == [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
    assert trajs[1] == [(5.0, 5.0), (6.0, 5.0)]


def test_header_custom_column_names(tmp_path: Path) -> None:
    p = _write(tmp_path, "run,pos_x,pos_y\nA,1,2\nA,3,4\n")
    trajs = load_trajectories_from_csv(
        p, x_column="pos_x", y_column="pos_y", trajectory_column="run"
    )
    assert trajs == [[(1.0, 2.0), (3.0, 4.0)]]


def test_header_missing_traj_column_falls_back_to_single(tmp_path: Path) -> None:
    p = _write(tmp_path, "x,y\n0,0\n1,1\n")
    trajs = load_trajectories_from_csv(p)  # default traj column not present
    assert trajs == [[(0.0, 0.0), (1.0, 1.0)]]


def test_header_missing_x_raises(tmp_path: Path) -> None:
    p = _write(tmp_path, "trajectory_id,not_x,y\nA,0,0\n")
    with pytest.raises(CsvTrajectoryLoadError):
        load_trajectories_from_csv(p)


def test_non_numeric_raises(tmp_path: Path) -> None:
    p = _write(tmp_path, "x,y\nhello,world\n")
    with pytest.raises(CsvTrajectoryLoadError):
        load_trajectories_from_csv(p)


def test_extra_columns_are_ignored(tmp_path: Path) -> None:
    csv = "timestamp,x,y,z,trajectory_id\n0,1,2,9,A\n1,3,4,9,A\n"
    p = _write(tmp_path, csv)
    trajs = load_trajectories_from_csv(p)
    assert trajs == [[(1.0, 2.0), (3.0, 4.0)]]


def test_empty_file(tmp_path: Path) -> None:
    p = _write(tmp_path, "")
    assert load_trajectories_from_csv(p) == []


def test_header_only_no_rows(tmp_path: Path) -> None:
    p = _write(tmp_path, "x,y\n")
    assert load_trajectories_from_csv(p) == []


# --------------------------- positional loading ---------------------------


def test_positional_default_columns(tmp_path: Path) -> None:
    p = _write(tmp_path, "0,0\n1,0\n2,0\n")
    trajs = load_trajectories_from_csv(
        p,
        x_column=0,
        y_column=1,
        trajectory_column=None,
        has_header=False,
    )
    assert trajs == [[(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]]


def test_positional_with_traj_column(tmp_path: Path) -> None:
    csv = "A,0,0\nA,1,0\nB,5,5\n"
    p = _write(tmp_path, csv)
    trajs = load_trajectories_from_csv(
        p,
        x_column=1,
        y_column=2,
        trajectory_column=0,
        has_header=False,
    )
    assert len(trajs) == 2
    assert trajs[0] == [(0.0, 0.0), (1.0, 0.0)]
    assert trajs[1] == [(5.0, 5.0)]


def test_positional_blank_lines_skipped(tmp_path: Path) -> None:
    p = _write(tmp_path, "0,0\n\n1,1\n")
    trajs = load_trajectories_from_csv(
        p,
        x_column=0,
        y_column=1,
        trajectory_column=None,
        has_header=False,
    )
    assert trajs == [[(0.0, 0.0), (1.0, 1.0)]]


def test_positional_requires_int_columns(tmp_path: Path) -> None:
    p = _write(tmp_path, "0,0\n")
    with pytest.raises(CsvTrajectoryLoadError):
        load_trajectories_from_csv(p, x_column="x", has_header=False)


def test_header_requires_string_columns(tmp_path: Path) -> None:
    p = _write(tmp_path, "x,y\n0,0\n")
    with pytest.raises(CsvTrajectoryLoadError):
        load_trajectories_from_csv(p, x_column=0, has_header=True)


# --------------------------- error cases ---------------------------


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(CsvTrajectoryLoadError):
        load_trajectories_from_csv(tmp_path / "no.csv")


def test_alternate_delimiter(tmp_path: Path) -> None:
    p = _write(tmp_path, "x;y\n0;0\n1;1\n")
    trajs = load_trajectories_from_csv(p, delimiter=";")
    assert trajs == [[(0.0, 0.0), (1.0, 1.0)]]
