"""Authoring an out-of-repo adapter — and proving it conforms.

Paper figure (evaluation Chapter 5, the *engineering contribution*):
``semantic-toponav`` exposes its plugin points as ``typing.Protocol``
classes, and every Protocol ships a reusable **conformance suite**. The
claim is that an adapter author — writing a Mast3R rerender source, an
RGB-D fusion pipeline, an NATS transport — can run *one function* against
their implementation and know whether it plugs in, without reading the
planner internals.

This example plays the role of that external author. It implements an
:class:`~semantic_toponav.encoders.AlignedRgbSource` the way the future
``semantic-toponav-mast3r`` package would — a *rerender source* that does
not wrap a stored image but synthesizes the requested region on demand —
and then runs the shipped
:func:`~semantic_toponav.testing.conformance.run_aligned_rgb_source_conformance`
suite against it. If the suite returns, the adapter is wire-compatible
with :func:`~semantic_toponav.conversion.vlm.embed_region_patches`.

The adapter here is deliberately torch-free (it fakes the rerender with a
deterministic gradient) so the walkthrough runs in CI; a real adapter
would call out to its model in ``crop`` and otherwise look identical. See
[`docs/authoring_external_adapters.md`](../docs/authoring_external_adapters.md)
for the step-by-step.

Run from the repo root::

    python examples/external_adapter_conformance.py
"""

from __future__ import annotations

import numpy as np

from semantic_toponav.encoders.rgb_source import Bbox
from semantic_toponav.testing.conformance import (
    run_aligned_rgb_source_conformance,
)


class Mast3RStyleRgbSource:
    """An out-of-repo ``AlignedRgbSource`` backed by on-demand rerendering.

    Unlike the bundled ``StaticImageRgbSource`` (which wraps a stored
    ndarray), a real Mast3R / NeRF source has no full image in memory: it
    *rerenders* the requested region of the reconstructed scene each time
    ``crop`` is called. This stand-in keeps that shape — there is no stored
    image, only a fixed scene ``shape`` and a ``crop`` that synthesizes
    pixels for the asked-for bbox — but fakes the rerender with a cheap,
    deterministic gradient so the example needs no GPU or torch.

    To satisfy the Protocol an implementation must:

    * report a stable ``(height, width)`` ``shape``;
    * return, from ``crop(bbox)``, an RGB patch that
      ``Backend.embed_image`` accepts (here an ``(h, w, 3)`` uint8 ndarray);
    * be reusable — ``crop`` may be called repeatedly for the same bbox.
    """

    def __init__(self, height: int = 64, width: int = 96) -> None:
        if height <= 0 or width <= 0:
            raise ValueError(f"scene shape must be positive, got {(height, width)}")
        self._height = int(height)
        self._width = int(width)

    @property
    def shape(self) -> tuple[int, int]:
        # Stable for the object's lifetime — the suite reads it twice.
        return self._height, self._width

    def crop(self, bbox: Bbox) -> np.ndarray:
        rmin, cmin, rmax, cmax = bbox
        h, w = self.shape
        if not (0 <= rmin <= rmax < h and 0 <= cmin <= cmax < w):
            raise ValueError(f"bbox {bbox} out of bounds for scene shape {self.shape}")
        # Stand in for a rerender: a deterministic RGB gradient over the
        # requested region. A real adapter would query its model here and
        # return the rerendered pixels in the same occupancy frame.
        rows = np.arange(rmin, rmax + 1)[:, None]
        cols = np.arange(cmin, cmax + 1)[None, :]
        r = ((rows * 255) // max(1, h - 1)) * np.ones_like(cols)
        g = ((cols * 255) // max(1, w - 1)) * np.ones_like(rows)
        b = (((rows + cols) * 255) // max(1, h + w - 2)) * np.ones_like(r)
        return np.stack([r, g, b], axis=-1).astype(np.uint8)


def main() -> None:
    source = Mast3RStyleRgbSource(height=64, width=96)
    print(
        f"authored adapter: {type(source).__name__} "
        f"(scene shape {source.shape}, rerender-on-crop, no stored image)"
    )

    # The whole acceptance test the adapter author runs: one call.
    run_aligned_rgb_source_conformance(source)
    print(
        "run_aligned_rgb_source_conformance: PASS — the adapter is "
        "wire-compatible with embed_region_patches (shape stable, crop "
        "returns a reusable Backend-consumable patch)."
    )

    # A custom bbox is supported too — e.g. a rerender server that only
    # accepts certain tile sizes would pass its known-good bbox here.
    run_aligned_rgb_source_conformance(source, sample_bbox=(8, 8, 39, 55))
    print("run_aligned_rgb_source_conformance(sample_bbox=…): PASS")


if __name__ == "__main__":
    main()
