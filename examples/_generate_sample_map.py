"""Generate examples/sample_map.pgm + sample_map.yaml.

Re-run this script to regenerate the bundled sample map. The output files
are committed so users don't need scikit-image just to read the bundled
example.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from skimage.io import imsave

HERE = Path(__file__).parent

# 80 x 50 pixel-space layout. Resolution will be 0.05 m/pixel below, so
# the world is 4.0 m x 2.5 m.
H, W = 50, 80


def build() -> np.ndarray:
    """White (255) is free, black (0) is occupied — ROS map_server convention."""
    img = np.zeros((H, W), dtype=np.uint8)  # start all occupied

    def carve(r0: int, r1: int, c0: int, c1: int) -> None:
        img[r0:r1, c0:c1] = 255

    # Main horizontal corridor.
    carve(22, 28, 4, 76)
    # Two doorways into upper rooms.
    carve(6, 22, 12, 22)   # upper-left room
    carve(6, 22, 32, 48)   # upper-mid room
    carve(6, 22, 58, 72)   # upper-right room
    # Two doorways into lower rooms.
    carve(28, 44, 12, 26)  # lower-left room
    carve(28, 44, 38, 50)  # lower-mid room
    carve(28, 44, 60, 76)  # lower-right room

    # Add a narrow connector between upper-mid and lower-mid (interior door).
    carve(20, 30, 40, 42)

    return img


def main() -> None:
    img = build()
    pgm = HERE / "sample_map.pgm"
    yml = HERE / "sample_map.yaml"

    imsave(str(pgm), img)

    yml.write_text(
        """image: sample_map.pgm
resolution: 0.05
origin: [-2.0, -1.25, 0.0]
negate: 0
occupied_thresh: 0.65
free_thresh: 0.196
""",
        encoding="utf-8",
    )

    print(f"wrote {pgm.relative_to(HERE.parent)} ({img.shape[1]}x{img.shape[0]})")
    print(f"wrote {yml.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
