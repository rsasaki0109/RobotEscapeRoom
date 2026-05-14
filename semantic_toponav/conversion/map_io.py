"""Load ROS map_server YAML + image bundles.

The format follows the convention used by ``nav2_map_server`` /
``map_server``:

.. code-block:: yaml

    image: my_map.pgm
    resolution: 0.05
    origin: [-7.5, -7.5, 0.0]
    negate: 0
    occupied_thresh: 0.65
    free_thresh: 0.196
    # optional: mode: trinary | scale | raw

For our purposes we only need the boolean *free-space mask*, the
resolution, and the world-space origin of the bottom-left cell.

Pixel semantics (matching map_server):

- Each image pixel is converted to an occupancy probability ``p`` in ``[0, 1]``.
- With ``negate=0`` (default): ``p = (255 - pixel) / 255``.
- With ``negate=1``: ``p = pixel / 255``.
- Cells with ``p < free_thresh`` are *free*. Everything else (occupied or
  unknown) is treated as non-traversable for the purposes of the converter.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class MapLoadError(Exception):
    """Raised when a map_server YAML bundle cannot be parsed."""


@dataclass
class OccupancyMap:
    """Container for a loaded ROS map_server map."""

    free_mask: Any  # 2D bool numpy array
    resolution: float
    origin: tuple[float, float]
    origin_yaw: float = 0.0
    metadata: dict[str, Any] = None  # type: ignore[assignment]

    @property
    def shape(self) -> tuple[int, int]:
        return tuple(self.free_mask.shape)  # type: ignore[return-value]


def load_occupancy_map(yaml_path: str | Path) -> OccupancyMap:
    """Load a ROS map_server YAML + image into an :class:`OccupancyMap`.

    Requires NumPy and scikit-image. Install with
    ``pip install 'semantic-toponav[map]'``.
    """
    try:
        import numpy as np
        from skimage.io import imread
    except ImportError as exc:
        raise ImportError(
            "load_occupancy_map requires NumPy + scikit-image. Install with "
            "`pip install 'semantic-toponav[map]'`"
        ) from exc

    p = Path(yaml_path)
    if not p.exists():
        raise MapLoadError(f"map yaml not found: {p}")

    try:
        meta = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise MapLoadError(f"failed to parse {p}: {exc}") from exc
    if not isinstance(meta, dict):
        raise MapLoadError(f"{p}: top-level YAML must be a mapping")

    try:
        image_name = str(meta["image"])
        resolution = float(meta["resolution"])
        origin_xyz = list(meta["origin"])
    except KeyError as exc:
        raise MapLoadError(f"{p}: missing required key {exc}") from exc

    if len(origin_xyz) < 2:
        raise MapLoadError(
            f"{p}: 'origin' must have at least [x, y]; got {origin_xyz!r}"
        )
    origin_xy = (float(origin_xyz[0]), float(origin_xyz[1]))
    origin_yaw = float(origin_xyz[2]) if len(origin_xyz) >= 3 else 0.0

    negate = int(meta.get("negate", 0))
    free_thresh = float(meta.get("free_thresh", 0.196))
    occupied_thresh = float(meta.get("occupied_thresh", 0.65))

    image_path = (p.parent / image_name).resolve()
    if not image_path.exists():
        raise MapLoadError(f"image referenced by {p.name} not found: {image_path}")

    img = imread(str(image_path))
    if img.ndim == 3:
        # Convert to grayscale by averaging channels.
        img = img.mean(axis=-1)
    pixel_float = img.astype(np.float32) / 255.0
    if negate:
        occ = pixel_float
    else:
        occ = 1.0 - pixel_float

    free_mask = occ < free_thresh

    return OccupancyMap(
        free_mask=free_mask,
        resolution=resolution,
        origin=origin_xy,
        origin_yaw=origin_yaw,
        metadata={
            "negate": negate,
            "free_thresh": free_thresh,
            "occupied_thresh": occupied_thresh,
            "image": image_name,
        },
    )
