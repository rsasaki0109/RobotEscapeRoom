"""Conformance suite for :class:`semantic_toponav.encoders.AlignedRgbSource`.

Adapter authors (Mast3R rerenders, RGB-D fusion pipelines,
orthorectified drone capture) need to know whether their source plugs
cleanly into
:func:`~semantic_toponav.conversion.vlm.embed_region_patches`. This
suite asserts the documented surface — ``shape`` and ``crop(bbox)`` —
plus an end-to-end sanity probe through
:class:`~semantic_toponav.encoders.HashingBackend` (which has no
runtime deps and accepts any ``hasattr(image, 'tobytes')`` array).
"""

from __future__ import annotations

from semantic_toponav.encoders.backends import Backend, HashingBackend
from semantic_toponav.encoders.rgb_source import AlignedRgbSource, Bbox


def run_aligned_rgb_source_conformance(
    source: AlignedRgbSource,
    *,
    sample_bbox: Bbox | None = None,
    backend: Backend | None = None,
) -> None:
    """Run the :class:`AlignedRgbSource` conformance checks.

    Parameters
    ----------
    source:
        The source under test.
    sample_bbox:
        Optional bbox to use for the crop checks. If ``None`` (default)
        the suite derives one from ``source.shape``: the top-left
        quadrant, or the full image when the source is smaller than
        4x4. Adapters with non-trivial alignment constraints (e.g. a
        Mast3R rerender server that only accepts specific bbox sizes)
        should pass a known-good bbox here.
    backend:
        Optional encoder to verify that the cropped patch is consumable
        end-to-end. Defaults to :class:`HashingBackend`, which has no
        external dependencies but requires the patch to expose
        ``tobytes`` / ``shape`` / be ``bytes`` / be a path. If your
        crop returns something fancier (a PIL image, a torch tensor)
        pass a compatible backend — or pass ``backend=None`` to skip
        the end-to-end probe entirely.
    """

    assert isinstance(source, AlignedRgbSource), (
        f"{type(source).__name__} does not satisfy the AlignedRgbSource "
        "Protocol (missing shape or crop)"
    )

    shape = source.shape
    assert isinstance(shape, tuple) and len(shape) == 2, (
        f"shape must be a (height, width) 2-tuple, got {shape!r}"
    )
    height, width = shape
    assert isinstance(height, int) and isinstance(width, int), (
        f"shape entries must be int, got {(type(height).__name__, type(width).__name__)}"
    )
    assert height > 0 and width > 0, (
        f"shape must be positive, got {shape!r}"
    )

    # shape must be stable across reads — a source whose dimensions
    # change between calls would silently break every cached bbox.
    shape_again = source.shape
    assert shape_again == shape, (
        f"shape changed across reads: {shape!r} -> {shape_again!r} — "
        "AlignedRgbSource dimensions must be stable for the lifetime "
        "of the object"
    )

    if sample_bbox is None:
        # Top-left quadrant, or the full image when the source is tiny.
        rmax = max(0, height // 2 - 1) if height >= 4 else height - 1
        cmax = max(0, width // 2 - 1) if width >= 4 else width - 1
        sample_bbox = (0, 0, rmax, cmax)

    rmin, cmin, rmax, cmax = sample_bbox
    assert 0 <= rmin <= rmax < height, (
        f"sample_bbox rows {rmin}..{rmax} out of [0, {height}); pass a valid one"
    )
    assert 0 <= cmin <= cmax < width, (
        f"sample_bbox cols {cmin}..{cmax} out of [0, {width}); pass a valid one"
    )

    patch = source.crop(sample_bbox)
    assert patch is not None, (
        f"crop({sample_bbox!r}) returned None; must return an image patch"
    )

    # Calling crop again with the same bbox must keep returning a usable
    # patch — i.e. the source is not single-shot. We don't require
    # identical bytes (rerender servers may be non-deterministic).
    second = source.crop(sample_bbox)
    assert second is not None, (
        f"crop({sample_bbox!r}) returned None on the second call; the "
        "source must be reusable"
    )

    if backend is None:
        backend = HashingBackend(dim=16)
    try:
        vec = backend.embed_image(patch)
    except (TypeError, ValueError) as exc:
        raise AssertionError(
            "crop's return value is not consumable by the encoder Backend "
            f"({type(backend).__name__}): {exc}. Adapters must return "
            "something Backend.embed_image accepts (ndarray, PIL, bytes, "
            "or a filesystem path)."
        ) from exc
    assert isinstance(vec, list) and len(vec) == backend.dim, (
        f"end-to-end embed of cropped patch produced unexpected vector "
        f"shape: {len(vec)} dims, backend.dim={backend.dim}"
    )
