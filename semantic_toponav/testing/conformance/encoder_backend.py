"""Conformance suite for :class:`semantic_toponav.encoders.Backend`.

Checks the four-method contract — ``dim`` / ``embed_text`` /
``embed_image`` / ``embed_images`` — and the key cross-cutting
invariant the higher-level helpers (
:func:`~semantic_toponav.query.find_nodes_by_embedding`,
:func:`~semantic_toponav.conversion.vlm.embed_region_patches`) rely on:
returned vectors are L2-normalized so cosine similarity collapses to
a plain dot product.
"""

from __future__ import annotations

import math
from typing import Any

from semantic_toponav.encoders.backends import Backend

_L2_TOL = 1e-3
"""Tolerance for the L2-norm check. CLIP / float-precision drift is
well under this; the assertion catches a backend that simply forgot
to normalize."""


def _l2_norm(vec: Any) -> float:
    return math.sqrt(sum(float(x) * float(x) for x in vec))


def _make_tiny_rgb_image() -> Any:
    """Return a 4x4x3 uint8 RGB ndarray — small but valid for every
    image encoder shipped here (HashingBackend treats it as raw bytes;
    CLIPBackend up-resamples to its expected input size)."""
    import numpy as np

    return np.arange(48, dtype="uint8").reshape(4, 4, 3)


def run_encoder_backend_conformance(backend: Backend) -> None:
    """Run the encoder :class:`Backend` conformance checks.

    Parameters
    ----------
    backend:
        A :class:`Backend` implementation. The suite issues two
        ``embed_text`` calls, one ``embed_image`` call, and one
        ``embed_images`` call. Real GPU-backed backends incur the
        load-and-forward cost on first call; that's deliberately part
        of what conformance verifies.
    """

    assert isinstance(backend, Backend), (
        f"{type(backend).__name__} does not satisfy the encoder Backend "
        "Protocol (missing dim / embed_text / embed_image / embed_images)"
    )

    dim = backend.dim
    assert isinstance(dim, int), f"dim must be int, got {type(dim).__name__}"
    assert dim > 0, f"dim must be > 0, got {dim}"

    # ---- text path -------------------------------------------------------
    vec = backend.embed_text("a quiet meeting room")
    assert isinstance(vec, list), (
        f"embed_text must return list, got {type(vec).__name__}"
    )
    assert len(vec) == dim, (
        f"embed_text returned {len(vec)} dims, but backend.dim == {dim}"
    )
    assert all(isinstance(x, float) for x in vec), (
        "embed_text vector must contain only floats (use [float(x) for ...])"
    )
    norm = _l2_norm(vec)
    assert abs(norm - 1.0) < _L2_TOL, (
        f"embed_text vector is not L2-normalized: ||v||={norm:.6f}"
    )

    # ---- image path ------------------------------------------------------
    image = _make_tiny_rgb_image()
    img_vec = backend.embed_image(image)
    assert isinstance(img_vec, list), (
        f"embed_image must return list, got {type(img_vec).__name__}"
    )
    assert len(img_vec) == dim, (
        f"embed_image returned {len(img_vec)} dims, but dim == {dim}"
    )
    img_norm = _l2_norm(img_vec)
    assert abs(img_norm - 1.0) < _L2_TOL, (
        f"embed_image vector is not L2-normalized: ||v||={img_norm:.6f}"
    )

    # ---- batch path ------------------------------------------------------
    batch = backend.embed_images([image, image])
    assert isinstance(batch, list), (
        f"embed_images must return list, got {type(batch).__name__}"
    )
    assert len(batch) == 2, (
        f"embed_images returned {len(batch)} vectors for 2 inputs"
    )
    for row in batch:
        assert len(row) == dim, (
            f"embed_images row has {len(row)} dims, dim == {dim}"
        )
        row_norm = _l2_norm(row)
        assert abs(row_norm - 1.0) < _L2_TOL, (
            f"embed_images row is not L2-normalized: ||v||={row_norm:.6f}"
        )

    # ---- empty batch -----------------------------------------------------
    empty = backend.embed_images([])
    assert empty == [], (
        f"embed_images([]) must return [], got {empty!r}"
    )
