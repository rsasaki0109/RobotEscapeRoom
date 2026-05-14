"""Pluggable embedding backends for VLM / CLIP-style encoders.

This subpackage defines the :class:`Backend` protocol — a thin contract
covering ``embed_text`` / ``embed_image`` / ``embed_images`` — plus two
concrete implementations:

* :class:`HashingBackend` — deterministic SHA-based encoder. Zero deps,
  meant for tests and offline demos.
* :class:`CLIPBackend` — lazy HuggingFace ``CLIPModel`` wrapper. Requires
  the ``[vlm]`` extra (``transformers`` + ``torch`` + ``Pillow``).

Vectors returned by both backends are L2-normalized, so cosine similarity
collapses to a plain dot product — matching how
:func:`semantic_toponav.query.find_nodes_by_embedding` consumes them.
"""

from semantic_toponav.encoders.backends import (
    Backend,
    CLIPBackend,
    HashingBackend,
)

__all__ = [
    "Backend",
    "CLIPBackend",
    "HashingBackend",
]
