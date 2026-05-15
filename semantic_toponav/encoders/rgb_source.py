"""Aligned-RGB sources for region patch embedding.

The :func:`semantic_toponav.conversion.vlm.embed_region_patches` helper
crops a bounding box out of the same occupancy grid the topology graph
was derived from, then hands the patch to an encoder. That works for
visualizing the layout, but for a real VLM the input you actually want
is *aligned RGB*: a real-world photo in the same coordinate frame as
the occupancy grid, so the bbox of region 17 in image-pixel space maps
to a real photograph of the room region 17 represents.

This module defines the contract that lets callers swap that source
out without changing the embedding pipeline.

* :class:`AlignedRgbSource` is a tiny :class:`typing.Protocol`: given
  the same ``(rmin, cmin, rmax, cmax)`` bbox the occupancy graph
  produces, return an RGB patch (any value
  :meth:`Backend.embed_image` accepts).
* :class:`StaticImageRgbSource` wraps a pre-aligned RGB ndarray (rows
  × cols × 3) that is already in the occupancy frame. Zero
  dependencies beyond NumPy. Good enough when the RGB image came from
  a top-down camera, an orthorectified drone capture, or any pipeline
  that has already done the alignment offline.

Heavier sources — Mast3R, NeRF-style multi-view rerenders, RGB-D
fusion — belong in separate packages (`semantic-toponav-mast3r` etc.)
and only need to implement this protocol. The core stays
torch-free.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

Bbox = tuple[int, int, int, int]
"""Inclusive ``(rmin, cmin, rmax, cmax)`` in image pixel coordinates —
the same shape :class:`semantic_toponav.conversion.occupancy.RegionInfo`
stores under ``bbox_cells``."""


@runtime_checkable
class AlignedRgbSource(Protocol):
    """Source of RGB pixels in the occupancy grid coordinate frame.

    Implementations may back the data with anything — an in-memory
    ndarray, a tiled image on disk, a Mast3R rerender service — as
    long as the bbox they receive is interpreted in the same pixel
    frame as the occupancy grid that produced the topology graph.

    ``shape`` is reported so callers (and
    :func:`embed_region_patches`) can verify the source is aligned to
    the right occupancy image before cropping.
    """

    @property
    def shape(self) -> tuple[int, int]:
        """``(height, width)`` of the source in pixels."""
        ...

    def crop(self, bbox: Bbox) -> Any:
        """Return the RGB patch covered by ``bbox``.

        Returned value must be something the downstream
        :meth:`semantic_toponav.encoders.backends.Backend.embed_image`
        accepts — a NumPy array, a PIL image, raw bytes, or a path.
        Callers should not assume a specific concrete type.
        """
        ...


class StaticImageRgbSource:
    """Wrap a pre-aligned RGB ndarray.

    The image must already be in the occupancy-grid coordinate frame:
    bbox ``(rmin, cmin, rmax, cmax)`` indexes the array the same way
    it indexes the occupancy grid. The most common way to produce one
    of these is to ortho-rectify (or just photograph top-down) the
    physical space the occupancy grid maps, then resample to match
    the grid resolution.

    Parameters
    ----------
    image:
        A NumPy array of shape ``(H, W, 3)`` (uint8 or float in
        ``[0, 1]``). Shape and dtype are validated at construction.
    """

    def __init__(self, image: Any) -> None:
        try:
            import numpy as np
        except ImportError as exc:
            raise ImportError(
                "StaticImageRgbSource requires numpy. Install with "
                "`pip install 'semantic-toponav[map]'`"
            ) from exc

        arr = np.asarray(image)
        if arr.ndim != 3 or arr.shape[2] != 3:
            raise ValueError(
                "StaticImageRgbSource expects an (H, W, 3) RGB image, "
                f"got shape {arr.shape}"
            )
        self._image = arr

    @property
    def shape(self) -> tuple[int, int]:
        return int(self._image.shape[0]), int(self._image.shape[1])

    @property
    def image(self) -> Any:
        """The underlying RGB ndarray. Exposed for callers that want
        to visualize / debug the aligned source — do not mutate."""
        return self._image

    def crop(self, bbox: Bbox) -> Any:
        rmin, cmin, rmax, cmax = bbox
        h, w = self.shape
        if rmin < 0 or cmin < 0 or rmax >= h or cmax >= w or rmax < rmin or cmax < cmin:
            raise ValueError(
                f"bbox {bbox} out of bounds for image shape {self.shape}"
            )
        return self._image[rmin:rmax + 1, cmin:cmax + 1]
