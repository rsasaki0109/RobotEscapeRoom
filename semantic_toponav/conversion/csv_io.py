"""Load 2D trajectory logs from a CSV file.

Uses only :mod:`csv` from the standard library — no pandas, no numpy.

Two layout styles are supported, selected via ``has_header``:

- ``has_header=True`` (default): columns are referenced by name (strings).
- ``has_header=False``: columns are referenced by zero-based integer index.

If ``trajectory_column`` resolves to a valid column, rows are grouped by
that column's value (preserving the order in which each group first
appears). If it is ``None``, all rows form a single trajectory.
"""

from __future__ import annotations

import csv
from pathlib import Path


class CsvTrajectoryLoadError(Exception):
    """Raised when a trajectory CSV cannot be parsed."""


def load_trajectories_from_csv(
    path: str | Path,
    *,
    x_column: str | int = "x",
    y_column: str | int = "y",
    trajectory_column: str | int | None = "trajectory_id",
    has_header: bool = True,
    delimiter: str = ",",
) -> list[list[tuple[float, float]]]:
    """Load one or more 2D trajectories from a CSV file.

    Returns a list of trajectories; each trajectory is a list of
    ``(x, y)`` tuples in the order they appear in the file.
    """
    p = Path(path)
    if not p.exists():
        raise CsvTrajectoryLoadError(f"csv file not found: {p}")

    with p.open(encoding="utf-8", newline="") as fh:
        rows: list[dict[str, str]] | list[list[str]]
        if has_header:
            rows = list(csv.DictReader(fh, delimiter=delimiter))
            if rows is None:
                rows = []
            return _load_with_header(rows, x_column, y_column, trajectory_column, p)
        else:
            rows = list(csv.reader(fh, delimiter=delimiter))
            return _load_positional(rows, x_column, y_column, trajectory_column, p)


def _load_with_header(
    rows: list[dict[str, str]],
    x_column: str | int,
    y_column: str | int,
    trajectory_column: str | int | None,
    path: Path,
) -> list[list[tuple[float, float]]]:
    if not rows:
        return []

    if not isinstance(x_column, str) or not isinstance(y_column, str):
        raise CsvTrajectoryLoadError(
            f"{path}: x_column / y_column must be strings when has_header=True"
        )

    header = rows[0].keys()
    if x_column not in header:
        raise CsvTrajectoryLoadError(
            f"{path}: required column {x_column!r} not in header {list(header)}"
        )
    if y_column not in header:
        raise CsvTrajectoryLoadError(
            f"{path}: required column {y_column!r} not in header {list(header)}"
        )

    traj_key: str | None = None
    if trajectory_column is not None:
        if not isinstance(trajectory_column, str):
            raise CsvTrajectoryLoadError(
                f"{path}: trajectory_column must be a string when has_header=True"
            )
        if trajectory_column in header:
            traj_key = trajectory_column

    groups: dict[str, list[tuple[float, float]]] = {}
    order: list[str] = []
    for i, row in enumerate(rows, start=1):
        try:
            x = float(row[x_column])
            y = float(row[y_column])
        except (TypeError, ValueError) as exc:
            raise CsvTrajectoryLoadError(
                f"{path}: row {i}: cannot parse x/y as float ({exc})"
            ) from exc
        key = row.get(traj_key, "0") if traj_key else "0"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((x, y))
    return [groups[k] for k in order]


def _load_positional(
    rows: list[list[str]],
    x_column: str | int,
    y_column: str | int,
    trajectory_column: str | int | None,
    path: Path,
) -> list[list[tuple[float, float]]]:
    if not rows:
        return []
    if not isinstance(x_column, int) or not isinstance(y_column, int):
        raise CsvTrajectoryLoadError(
            f"{path}: x_column / y_column must be ints when has_header=False"
        )
    traj_idx: int | None = None
    if trajectory_column is not None:
        if not isinstance(trajectory_column, int):
            raise CsvTrajectoryLoadError(
                f"{path}: trajectory_column must be an int when has_header=False"
            )
        traj_idx = trajectory_column

    groups: dict[str, list[tuple[float, float]]] = {}
    order: list[str] = []
    for i, row in enumerate(rows, start=1):
        if not row or all(not cell.strip() for cell in row):
            continue  # skip blank lines
        try:
            x = float(row[x_column])
            y = float(row[y_column])
        except (IndexError, TypeError, ValueError) as exc:
            raise CsvTrajectoryLoadError(
                f"{path}: row {i}: cannot parse x/y at column "
                f"{x_column}/{y_column} ({exc})"
            ) from exc
        if traj_idx is not None and traj_idx < len(row):
            key = row[traj_idx]
        else:
            key = "0"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append((x, y))
    return [groups[k] for k in order]
