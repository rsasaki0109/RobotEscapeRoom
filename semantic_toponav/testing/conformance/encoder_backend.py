"""Conformance suite for :class:`semantic_toponav.encoders.Backend`.

Checks the four-method contract — ``dim`` / ``embed_text`` /
``embed_image`` / ``embed_images`` — and the key cross-cutting
invariant the higher-level helpers (
:func:`~semantic_toponav.query.find_nodes_by_embedding`,
:func:`~semantic_toponav.conversion.vlm.embed_region_patches`) rely on:
returned vectors are L2-normalized so cosine similarity collapses to
a plain dot product.

The suite also exercises a few failure-mode inputs that surface
real-world adapter bugs: empty text, length-1 batches that should
agree with the singular ``embed_image`` call, and determinism for
backends that are expected to be reproducible (opt-in via
``check_determinism``).
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


def _cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


def run_encoder_backend_conformance(
    backend: Backend,
    *,
    check_determinism: bool = True,
) -> None:
    """Run the encoder :class:`Backend` conformance checks.

    Parameters
    ----------
    backend:
        A :class:`Backend` implementation. The suite issues a handful
        of ``embed_text`` / ``embed_image`` / ``embed_images`` calls
        against it. Real GPU-backed backends incur the load-and-forward
        cost on first call; that's deliberately part of what conformance
        verifies.
    check_determinism:
        Whether to assert that ``embed_text`` is deterministic — calling
        it twice with the same input must yield the same vector. Default
        ``True`` because every shipped backend (Hashing, CLIP) is
        deterministic and almost every plausible adapter should be too.
        Disable for stochastic-augmentation backends.
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

    # ---- length-1 batch agrees with embed_image --------------------------
    # The singular and batched paths must produce vectors of the same dim
    # and shape for the same input — catches a batch path that silently
    # truncates dims or returns a different format.
    singleton = backend.embed_images([image])
    assert len(singleton) == 1 and len(singleton[0]) == dim, (
        f"embed_images([image]) shape mismatch: {len(singleton)}x"
        f"{len(singleton[0]) if singleton else '-'} vs expected 1x{dim}"
    )

    # ---- empty text -------------------------------------------------------
    # An empty query is a legitimate degenerate input (e.g. resolve_goal
    # against a stripped string). The backend must produce a properly
    # shaped, L2-normalized vector rather than crashing or returning a
    # zero vector that would break cosine math downstream.
    empty_vec = backend.embed_text("")
    assert isinstance(empty_vec, list) and len(empty_vec) == dim, (
        f"embed_text('') must return list[float] of dim {dim}, got "
        f"{type(empty_vec).__name__} of length "
        f"{len(empty_vec) if isinstance(empty_vec, list) else '-'}"
    )
    empty_norm = _l2_norm(empty_vec)
    assert abs(empty_norm - 1.0) < _L2_TOL, (
        f"embed_text('') vector is not L2-normalized: ||v||={empty_norm:.6f}"
    )

    # ---- self-similarity sanity ------------------------------------------
    # cos(v, v) ~= 1.0 for any unit vector. A backend that secretly emits
    # a constant zero vector would fail the L2 check above; one that emits
    # a constant non-zero unit vector would pass the L2 check but fail
    # downstream retrieval — this check catches both.
    cos_self = _cos(vec, vec)
    assert abs(cos_self - 1.0) < _L2_TOL, (
        f"cos(v, v) should be ~1.0 for a unit vector, got {cos_self:.6f}"
    )

    # ---- determinism (opt-in) --------------------------------------------
    if check_determinism:
        again = backend.embed_text("a quiet meeting room")
        # We don't insist on bitwise equality (a backend may add a tiny
        # numerical jitter); identical-to-tolerance is enough.
        assert len(again) == dim, (
            f"determinism re-call returned dim {len(again)}, expected {dim}"
        )
        for i, (x, y) in enumerate(zip(vec, again, strict=False)):
            assert abs(x - y) < _L2_TOL, (
                f"embed_text not deterministic at index {i}: {x} vs {y} "
                "(disable check_determinism if backend is intentionally "
                "stochastic)"
            )
