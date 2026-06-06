"""The external-adapter walkthrough (Chapter 5) must stay correct.

Guards `examples/external_adapter_conformance.py`: the out-of-repo
Mast3R-style ``AlignedRgbSource`` it authors must pass the shipped
conformance suite, satisfy the Protocol, and feed the encoder end-to-end —
so the walkthrough never documents an adapter that does not actually plug
in.
"""

from __future__ import annotations

import numpy as np

from examples.external_adapter_conformance import Mast3RStyleRgbSource, main
from semantic_toponav.encoders import HashingBackend
from semantic_toponav.encoders.rgb_source import AlignedRgbSource
from semantic_toponav.testing.conformance import (
    run_aligned_rgb_source_conformance,
)


def test_adapter_satisfies_the_protocol() -> None:
    assert isinstance(Mast3RStyleRgbSource(), AlignedRgbSource)


def test_adapter_passes_conformance() -> None:
    # Returns (does not raise) == conforms.
    run_aligned_rgb_source_conformance(Mast3RStyleRgbSource())


def test_adapter_passes_conformance_with_custom_bbox() -> None:
    run_aligned_rgb_source_conformance(
        Mast3RStyleRgbSource(height=64, width=96), sample_bbox=(8, 8, 39, 55)
    )


def test_shape_is_stable_and_positive() -> None:
    src = Mast3RStyleRgbSource(height=40, width=72)
    assert src.shape == (40, 72)
    assert src.shape == src.shape  # stable across reads


def test_crop_returns_consumable_patch() -> None:
    src = Mast3RStyleRgbSource()
    patch = src.crop((0, 0, 15, 15))
    assert isinstance(patch, np.ndarray)
    assert patch.shape == (16, 16, 3)
    assert patch.dtype == np.uint8
    # End-to-end: the encoder consumes it.
    vec = HashingBackend(dim=16).embed_image(patch)
    assert len(vec) == 16


def test_crop_rejects_out_of_bounds_bbox() -> None:
    src = Mast3RStyleRgbSource(height=32, width=32)
    for bad in [(0, 0, 32, 10), (0, 0, 10, 32), (5, 5, 4, 10)]:
        try:
            src.crop(bad)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for bbox {bad}")


def test_main_runs() -> None:
    main()  # prints PASS lines; must not raise
