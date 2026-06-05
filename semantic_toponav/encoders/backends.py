"""Concrete embedding backends.

The :class:`Backend` protocol is the contract every encoder satisfies —
text in, vector out (and image in, vector out). Two concrete backends
ship in this module:

* :class:`HashingBackend` — deterministic SHA-based encoder. Same input
  always maps to the same unit-length vector. No external dependencies,
  works in CI, and gives existing similarity helpers
  (:func:`semantic_toponav.query.find_nodes_by_embedding`,
  :func:`semantic_toponav.query.nearest_node_by_embedding`) something
  exercisable end-to-end without a real model in the loop.
* :class:`CLIPBackend` — lazy wrapper around
  ``transformers.CLIPModel``. The HuggingFace model + processor are
  loaded on first call to keep import cost out of the CLI bootstrap;
  vectors are L2-normalized so cosine similarity == dot product.

Both backends accept an image as a NumPy array, a filesystem path, or
raw ``bytes`` (and ``PIL.Image`` for CLIP). Callers that already have
patches cropped from an occupancy / floor-plan image (typically via
:func:`semantic_toponav.conversion.vlm.embed_region_patches`) can pass
them directly without round-tripping through disk.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# A vector is any iterable of floats; we normalize callers to a Python list
# so YAML / JSON round-tripping stays trivial.
Vector = list[float]


@runtime_checkable
class Backend(Protocol):
    """Minimal contract for an embedding encoder.

    All three return-shapes are L2-normalized so callers can compute
    cosine similarity by dot product. Implementations are not required
    to share a vector space — pairing a query vector from one backend
    with stored vectors from another will produce nonsense — so callers
    should pin the backend identity alongside the stored vectors.
    """

    @property
    def dim(self) -> int:
        """Dimensionality of the output vector."""
        ...

    def embed_text(self, text: str) -> Vector:
        """Encode a single string."""
        ...

    def embed_image(self, image: Any) -> Vector:
        """Encode a single image (NumPy array, path, bytes, or PIL)."""
        ...

    def embed_images(self, images: Sequence[Any]) -> list[Vector]:
        """Batch-encode images. Same semantics as repeated ``embed_image``."""
        ...


def _l2_normalize(vec: Sequence[float]) -> Vector:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return [float(x) for x in vec]
    return [float(x) / norm for x in vec]


class HashingBackend:
    """Deterministic SHA-based encoder. Zero external dependencies.

    Every input is hashed (text via UTF-8 bytes, image via the
    underlying ``tobytes()`` for NumPy arrays, or via the raw bytes of
    the file when a path is passed) and the digest is expanded into a
    fixed-dimension vector by repeated SHA-256 rounds. The result is
    L2-normalized so dot product == cosine similarity.

    Same input → identical vector across runs and across processes.
    Different inputs map to *near-orthogonal* vectors with very high
    probability, which is enough for unit tests that check "did the
    nearest-neighbor over a stamped graph actually return the
    right node".

    This is intentionally NOT a meaningful semantic encoder — it does
    not understand "stairs" or "kitchen". Use :class:`CLIPBackend` for
    that. The hashing backend exists so the rest of the toolchain
    (CLI, region patching, similarity queries) can be exercised
    without dragging in PyTorch.
    """

    def __init__(self, dim: int = 32) -> None:
        if dim < 4:
            raise ValueError(f"dim must be >= 4, got {dim}")
        self._dim = int(dim)

    @property
    def dim(self) -> int:
        return self._dim

    # ----- public API -------------------------------------------------------

    def embed_text(self, text: str) -> Vector:
        if not isinstance(text, str):
            raise TypeError(f"embed_text expects str, got {type(text).__name__}")
        return self._embed_bytes(b"text:" + text.encode("utf-8"))

    def embed_image(self, image: Any) -> Vector:
        return self._embed_bytes(b"image:" + self._coerce_to_bytes(image))

    def embed_images(self, images: Sequence[Any]) -> list[Vector]:
        return [self.embed_image(im) for im in images]

    # ----- internals --------------------------------------------------------

    @staticmethod
    def _coerce_to_bytes(image: Any) -> bytes:
        # NumPy / array-like with .tobytes(): use shape + dtype + raw buffer
        # so two arrays of different shapes don't collide just because their
        # raw bytes happen to match.
        if hasattr(image, "tobytes") and hasattr(image, "shape"):
            shape = repr(tuple(image.shape)).encode("utf-8")
            dtype = repr(getattr(image, "dtype", "unknown")).encode("utf-8")
            return shape + b"|" + dtype + b"|" + image.tobytes()
        if isinstance(image, (bytes, bytearray, memoryview)):
            return bytes(image)
        if isinstance(image, (str, Path)):
            return Path(image).read_bytes()
        raise TypeError(
            "HashingBackend.embed_image: unsupported image type "
            f"{type(image).__name__}; expected numpy array, path, or bytes"
        )

    def _embed_bytes(self, data: bytes) -> Vector:
        floats: list[float] = []
        counter = 0
        while len(floats) < self._dim:
            digest = hashlib.sha256(data + counter.to_bytes(4, "big")).digest()
            for k in range(0, len(digest), 4):
                if len(floats) >= self._dim:
                    break
                # Map each 4-byte chunk into [-1, 1).
                value = int.from_bytes(digest[k:k + 4], "big") / (1 << 32)
                floats.append(value * 2.0 - 1.0)
            counter += 1
        return _l2_normalize(floats)


class CLIPBackend:
    """Lazy wrapper around a HuggingFace CLIP model.

    Requires the ``[vlm]`` extra (``transformers`` + ``torch`` +
    ``Pillow``). The model and processor are loaded on the first
    ``embed_*`` call, not at construction, so building a backend just
    to forward it through ``argparse`` does not pay the model-download
    cost.

    Vectors are L2-normalized (cosine similarity == dot product),
    consistent with :class:`HashingBackend` and the existing
    :func:`semantic_toponav.query.find_nodes_by_embedding` helper.
    """

    DEFAULT_MODEL = "openai/clip-vit-base-patch32"

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        *,
        device: str = "cpu",
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._torch: Any = None
        self._model: Any = None
        self._processor: Any = None

    @property
    def dim(self) -> int:
        self._ensure_loaded()
        return int(self._model.config.projection_dim)

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed_text(self, text: str) -> Vector:
        if not isinstance(text, str):
            raise TypeError(f"embed_text expects str, got {type(text).__name__}")
        self._ensure_loaded()
        with self._torch.no_grad():
            inputs = self._processor(
                text=[text], return_tensors="pt", padding=True
            ).to(self._device)
            feats = self._feature_tensor(
                self._model.get_text_features(**inputs), text=True
            )
            feats = feats / feats.norm(dim=-1, keepdim=True)
            return [float(x) for x in feats[0].cpu().tolist()]

    def embed_image(self, image: Any) -> Vector:
        return self.embed_images([image])[0]

    def embed_images(self, images: Sequence[Any]) -> list[Vector]:
        self._ensure_loaded()
        pil_images = [self._to_pil(img) for img in images]
        if not pil_images:
            return []
        with self._torch.no_grad():
            inputs = self._processor(
                images=pil_images, return_tensors="pt"
            ).to(self._device)
            feats = self._feature_tensor(
                self._model.get_image_features(**inputs), text=False
            )
            feats = feats / feats.norm(dim=-1, keepdim=True)
            return [[float(x) for x in row] for row in feats.cpu().tolist()]

    # ----- internals --------------------------------------------------------

    def _feature_tensor(self, out: Any, *, text: bool) -> Any:
        """Extract the projected embedding tensor from a CLIP feature call.

        ``transformers < 5`` returns a plain tensor from
        ``get_image_features`` / ``get_text_features``; ``>= 5`` returns a
        ``BaseModelOutputWithPooling`` whose ``pooler_output`` (or
        ``image_embeds`` / ``text_embeds``) holds the projection-dim
        vector. Accept either so the backend tracks the pinned model
        across the supported ``transformers>=4.30`` range.
        """
        if isinstance(out, self._torch.Tensor):
            return out
        preferred = "text_embeds" if text else "image_embeds"
        for attr in (preferred, "pooler_output"):
            val = getattr(out, attr, None)
            if val is not None:
                return val
        raise TypeError(
            "CLIPBackend: unexpected feature output "
            f"{type(out).__name__}; cannot find an embedding tensor"
        )

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        try:
            import torch
            from transformers import CLIPModel, CLIPProcessor
        except ImportError as exc:
            raise ImportError(
                "CLIPBackend requires the [vlm] extra. Install with "
                "`pip install 'semantic-toponav[vlm]'`"
            ) from exc
        self._torch = torch
        self._model = CLIPModel.from_pretrained(self._model_name).to(self._device)
        self._model.eval()
        self._processor = CLIPProcessor.from_pretrained(self._model_name)

    def _to_pil(self, image: Any) -> Any:
        try:
            from PIL import Image
        except ImportError as exc:
            raise ImportError(
                "CLIPBackend requires Pillow. Install with "
                "`pip install 'semantic-toponav[vlm]'`"
            ) from exc
        if isinstance(image, (str, Path)):
            return Image.open(image).convert("RGB")
        if isinstance(image, Image.Image):
            return image.convert("RGB")
        if hasattr(image, "shape"):
            import numpy as np

            arr = image
            if arr.dtype == bool:
                arr = arr.astype(np.uint8) * 255
            elif arr.dtype != np.uint8:
                arr = np.clip(arr * 255.0 if arr.max() <= 1.0 else arr, 0, 255).astype(
                    np.uint8
                )
            if arr.ndim == 2:
                arr = np.stack([arr, arr, arr], axis=-1)
            return Image.fromarray(arr).convert("RGB")
        if isinstance(image, (bytes, bytearray)):
            import io

            return Image.open(io.BytesIO(bytes(image))).convert("RGB")
        raise TypeError(
            "CLIPBackend.embed_image: unsupported image type "
            f"{type(image).__name__}; expected numpy array, path, PIL.Image, or bytes"
        )
