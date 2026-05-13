"""Generate examples/sample_trajectories.csv.

Re-run this script to regenerate the bundled sample. The output CSV is
committed so the demo works without any extra dependencies.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

HERE = Path(__file__).parent
OUT = HERE / "sample_trajectories.csv"

random.seed(11)


def _line(p0, p1, n):
    x0, y0 = p0
    x1, y1 = p1
    return [
        (x0 + (x1 - x0) * t / (n - 1), y0 + (y1 - y0) * t / (n - 1)) for t in range(n)
    ]


def _walk(points, noise=0.05):
    return [(x + random.gauss(0, noise), y + random.gauss(0, noise)) for x, y in points]


def build() -> list[tuple[str, list[tuple[float, float]]]]:
    """Three synthetic robot runs over a T-shaped corridor."""
    horizontal = _line((0.0, 0.0), (12.0, 0.0), n=60)
    branch = _line((6.0, 0.0), (6.0, -6.0), n=40)

    return [
        ("run_1_forward", _walk(horizontal)),
        ("run_2_back", _walk(list(reversed(horizontal)))),
        ("run_3_to_branch", _walk(horizontal[:30] + branch)),
    ]


def main() -> None:
    runs = build()
    total = sum(len(pts) for _, pts in runs)
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["trajectory_id", "x", "y"])
        for run_id, pts in runs:
            for x, y in pts:
                w.writerow([run_id, f"{x:.4f}", f"{y:.4f}"])
    print(f"wrote {OUT.relative_to(HERE.parent)} ({len(runs)} trajectories, {total} points)")


if __name__ == "__main__":
    main()
