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

It also defines :class:`AlignedRgbSource` — the contract for swapping
the patch source used by
:func:`semantic_toponav.conversion.vlm.embed_region_patches` from the
raw occupancy grid to an aligned real-world RGB image (Mast3R-style
adapters live in separate packages and only need to implement this
protocol). :class:`StaticImageRgbSource` is the zero-dependency
reference implementation that wraps a pre-aligned ``(H, W, 3)`` ndarray.
"""

from semantic_toponav.encoders.backends import (
    Backend,
    CLIPBackend,
    HashingBackend,
)
from semantic_toponav.encoders.rgb_source import (
    AlignedRgbSource,
    Bbox,
    StaticImageRgbSource,
)

__all__ = [
    "AlignedRgbSource",
    "Backend",
    "Bbox",
    "CLIPBackend",
    "HashingBackend",
    "StaticImageRgbSource",
]
