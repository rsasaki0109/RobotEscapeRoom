"""Tests for the deterministic HashingBackend encoder.

CLIPBackend is exercised only via its lazy-import guard — pulling
``transformers`` + ``torch`` into CI is out of scope for this suite.
"""

from __future__ import annotations

import math

import pytest

from semantic_toponav.encoders.backends import (
    Backend,
    CLIPBackend,
    HashingBackend,
)


def _is_unit(vec, *, tol: float = 1e-6) -> bool:
    return abs(math.sqrt(sum(x * x for x in vec)) - 1.0) <= tol


# --------------------------------- HashingBackend ---------------------------------


def test_hashing_backend_dim_round_trip() -> None:
    b = HashingBackend(dim=64)
    assert b.dim == 64
    assert len(b.embed_text("hello")) == 64


def test_hashing_backend_rejects_dim_below_4() -> None:
    with pytest.raises(ValueError):
        HashingBackend(dim=3)


def test_hashing_backend_text_is_deterministic() -> None:
    a = HashingBackend(dim=32).embed_text("kitchen")
    b = HashingBackend(dim=32).embed_text("kitchen")
    assert a == b


def test_hashing_backend_text_is_l2_normalized() -> None:
    vec = HashingBackend(dim=32).embed_text("anything")
    assert _is_unit(vec)


def test_hashing_backend_distinct_inputs_distinct_outputs() -> None:
    b = HashingBackend(dim=64)
    v1 = b.embed_text("kitchen")
    v2 = b.embed_text("bedroom")
    assert v1 != v2


def test_hashing_backend_embed_image_accepts_numpy() -> None:
    np = pytest.importorskip("numpy")
    b = HashingBackend(dim=32)
    img = np.zeros((4, 4), dtype=np.uint8)
    img[1, 1] = 255
    vec = b.embed_image(img)
    assert len(vec) == 32
    assert _is_unit(vec)


def test_hashing_backend_embed_image_accepts_bytes() -> None:
    b = HashingBackend(dim=32)
    vec = b.embed_image(b"\x00\x01\x02\x03")
    assert len(vec) == 32
    assert _is_unit(vec)


def test_hashing_backend_embed_image_rejects_int() -> None:
    with pytest.raises(TypeError):
        HashingBackend().embed_image(42)


def test_hashing_backend_embed_images_batch_matches_singletons() -> None:
    np = pytest.importorskip("numpy")
    b = HashingBackend(dim=32)
    imgs = [np.full((3, 3), v, dtype=np.uint8) for v in (10, 20, 30)]
    batch = b.embed_images(imgs)
    assert batch == [b.embed_image(im) for im in imgs]


def test_hashing_backend_array_shape_distinguishes_inputs() -> None:
    """Two arrays whose ``tobytes()`` would tie at first glance still differ
    once shape is folded into the hash."""
    np = pytest.importorskip("numpy")
    b = HashingBackend(dim=32)
    a = np.zeros((2, 3), dtype=np.uint8)
    bb = np.zeros((3, 2), dtype=np.uint8)
    assert b.embed_image(a) != b.embed_image(bb)


def test_hashing_backend_text_and_image_namespaces_disjoint() -> None:
    """Text and image inputs that share raw bytes should not collide."""
    np = pytest.importorskip("numpy")
    b = HashingBackend(dim=32)
    text_vec = b.embed_text("AB")
    img_vec = b.embed_image(np.frombuffer(b"AB", dtype=np.uint8))
    assert text_vec != img_vec


# --------------------------------- protocol ---------------------------------


def test_hashing_backend_satisfies_protocol() -> None:
    assert isinstance(HashingBackend(), Backend)


# --------------------------------- CLIPBackend ---------------------------------


def test_clip_backend_lazy_import_error_when_extras_missing() -> None:
    """Construction is cheap; the import guard fires on first use."""
    backend = CLIPBackend()
    assert backend.model_name == CLIPBackend.DEFAULT_MODEL

    transformers_available = True
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        transformers_available = False

    if not transformers_available:
        with pytest.raises(ImportError, match=r"\[vlm\] extra"):
            backend.embed_text("hello")
