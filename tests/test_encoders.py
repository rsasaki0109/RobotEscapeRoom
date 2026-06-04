"""Tests for the deterministic HashingBackend encoder.

CLIPBackend is exercised only via its lazy-import guard — pulling
``transformers`` + ``torch`` into CI is out of scope for this suite.
"""

from __future__ import annotations

import math
import types

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


def test_feature_tensor_handles_both_transformers_return_shapes() -> None:
    """`transformers < 5` returns a tensor from get_*_features; `>= 5`
    returns a BaseModelOutputWithPooling. The backend must accept either.

    This guards the version-robustness deterministically without torch —
    the real embed path (covered below) only runs where the [vlm] extra
    is installed, so CI without torch would otherwise miss an API break.
    """
    backend = CLIPBackend()

    class _Tensor:
        pass

    backend._torch = types.SimpleNamespace(Tensor=_Tensor)

    # transformers<5: a plain tensor flows through unchanged.
    t = _Tensor()
    assert backend._feature_tensor(t, text=False) is t

    # transformers>=5: image path prefers image_embeds, else pooler_output.
    out = types.SimpleNamespace(image_embeds="IMG", pooler_output="POOL")
    assert backend._feature_tensor(out, text=False) == "IMG"
    out_pool = types.SimpleNamespace(image_embeds=None, pooler_output="POOL")
    assert backend._feature_tensor(out_pool, text=False) == "POOL"

    # text path prefers text_embeds.
    out_txt = types.SimpleNamespace(text_embeds="TXT", pooler_output="POOL")
    assert backend._feature_tensor(out_txt, text=True) == "TXT"

    # An output object exposing no embedding attribute is an error.
    with pytest.raises(TypeError, match="embedding tensor"):
        backend._feature_tensor(types.SimpleNamespace(), text=False)


def test_clip_backend_real_embed_smoke() -> None:
    """Real CLIP embed path — runs only where the [vlm] extra is present.

    Skipped in default CI (no torch). Where torch + transformers are
    installed it actually loads the model and embeds, so an upstream API
    change (e.g. the transformers 5.x get_*_features return-type shift)
    is caught instead of silently skipped.
    """
    np = pytest.importorskip("numpy")
    pytest.importorskip("torch")
    pytest.importorskip("transformers")

    backend = CLIPBackend()
    img = (np.random.default_rng(0).random((8, 8, 3)) * 255).astype(np.uint8)
    vec = backend.embed_image(img)
    assert len(vec) == backend.dim
    assert math.isclose(math.sqrt(sum(x * x for x in vec)), 1.0, abs_tol=1e-3)

    tvec = backend.embed_text("a loading bay")
    assert len(tvec) == backend.dim
    assert math.isclose(math.sqrt(sum(x * x for x in tvec)), 1.0, abs_tol=1e-3)
