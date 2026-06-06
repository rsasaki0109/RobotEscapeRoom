# Authoring an external adapter (and proving it conforms)

This is the hands-on companion to [`docs/conformance.md`](conformance.md).
That document is the reference — the list of Protocols and what each
conformance suite checks. This one is a walkthrough: it takes a single
plug point, the `AlignedRgbSource`, and shows an **out-of-repo** adapter
author the whole loop — write the class, run one function, know you
conform — that evaluation Chapter 5 argues is the missing piece in most
"pluggable" systems.

The runnable version of everything below is
[`examples/external_adapter_conformance.py`](../examples/external_adapter_conformance.py),
exercised in CI by
[`tests/test_external_adapter_conformance.py`](../tests/test_external_adapter_conformance.py).

## Why adapters live outside the repo

The core stays readable Python with no heavy runtime deps. Anything that
drags in torch, model weights, C++, or a GPU — a Mast3R rerender source,
an RGB-D fusion pipeline, an NATS transport — belongs in its own package
(`semantic-toponav-mast3r`, …) and only has to satisfy a `typing.Protocol`
to drop into the existing pipeline. The contract is the API boundary; the
conformance suite is how the adapter author verifies they are on the right
side of it without reading the planner internals.

So this walkthrough doubles as the onboarding doc for the future
`semantic-toponav-mast3r` package (Phase C): the source it ships is an
`AlignedRgbSource`, and the acceptance test it runs is the one below.

## The contract: `AlignedRgbSource`

[`semantic_toponav.encoders.AlignedRgbSource`](../semantic_toponav/encoders/rgb_source.py)
is a two-member Protocol. Given the same `(rmin, cmin, rmax, cmax)` bbox
the occupancy graph produced, return an RGB patch in that pixel frame:

```python
@runtime_checkable
class AlignedRgbSource(Protocol):
    @property
    def shape(self) -> tuple[int, int]:        # (height, width) in pixels
        ...
    def crop(self, bbox: Bbox) -> Any:          # RGB patch for that bbox
        ...
```

The patch may be anything
[`Backend.embed_image`](../semantic_toponav/encoders/backends.py) accepts —
an ndarray, a PIL image, raw bytes, or a path. The bundled
`StaticImageRgbSource` wraps a stored ndarray; a real rerender source has
no stored image at all.

## Step 1 — implement the source

The key realization for a rerender-style adapter: **you do not need a
stored image**. `crop` may *synthesize* the requested region on demand —
that is exactly what a Mast3R / NeRF source does. All the Protocol asks is
a stable `shape` and a reusable `crop`:

```python
class Mast3RStyleRgbSource:
    def __init__(self, height=64, width=96):
        self._height, self._width = height, width

    @property
    def shape(self) -> tuple[int, int]:
        return self._height, self._width          # stable for the lifetime

    def crop(self, bbox):
        rmin, cmin, rmax, cmax = bbox
        # ... rerender the reconstructed scene for this region and return
        # the pixels as an (h, w, 3) array in the occupancy frame ...
        return patch
```

The full (torch-free, deterministic) version is in the example file; a
real adapter swaps the gradient stand-in for a model call in `crop` and is
otherwise identical.

## Step 2 — run the conformance suite

The entire acceptance test is one call:

```python
from semantic_toponav.testing.conformance import (
    run_aligned_rgb_source_conformance,
)

run_aligned_rgb_source_conformance(Mast3RStyleRgbSource())
```

If it returns, you conform. If it raises `AssertionError`, the message
names exactly which invariant failed. Drop the same call into your own
package's `tests/` and it runs straight under pytest (the suite does not
import pytest itself).

For a source with alignment constraints — e.g. a rerender server that only
accepts certain tile sizes — pass a known-good bbox and, if your `crop`
returns something other than an ndarray/bytes/path, a compatible encoder:

```python
run_aligned_rgb_source_conformance(
    source, sample_bbox=(8, 8, 39, 55), backend=my_clip_backend
)
```

## What the suite guarantees

Passing
[`run_aligned_rgb_source_conformance`](../semantic_toponav/testing/conformance/aligned_rgb_source.py)
means your adapter holds these invariants — the ones
`embed_region_patches` silently relies on:

| invariant | why it matters |
|---|---|
| `shape` is a positive `(int, int)` tuple | callers size their bbox grid against it |
| `shape` is stable across reads | a shifting shape would break every cached bbox |
| `crop(bbox)` returns non-`None` | a missing region must raise, not return nothing |
| `crop` is reusable (same bbox twice) | the pipeline crops many regions; the source is not single-shot |
| the patch is `Backend.embed_image`-consumable | the crop feeds the encoder end-to-end without a glue layer |

That last one is the point of the end-to-end probe: the suite actually
embeds the cropped patch through a backend (`HashingBackend` by default,
no deps), so "it returned *something*" is not enough — it returned
something the encoder can consume.

## The same pattern, six times

`AlignedRgbSource` is one of six plug points. Every one ships a
`run_<name>_conformance` suite under
`semantic_toponav.testing.conformance` — `encoder_backend`, `llm_backend`,
`scheduler`, `transport`, `conflict_policy`, and `aligned_rgb_source`. The
authoring loop is identical for each: implement the Protocol, call the
suite, read the failure message if any. See [`conformance.md`](conformance.md)
for the full list and each suite's checks.
