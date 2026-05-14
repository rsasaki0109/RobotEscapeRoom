# Protocol conformance suites

`semantic-toponav` exposes its plugin surface as a handful of
`typing.Protocol` classes (and one `Callable` type alias). Anyone
writing an adapter — a Mast3R-based `AlignedRgbSource`, an NATS
`Transport`, a deadline-aware `ConflictPolicy` — only has to satisfy
the Protocol to drop into the existing planner / coordinator code.

To make that promise testable, every Protocol ships a reusable
**conformance suite** under `semantic_toponav.testing.conformance`.
Each suite is a single function that takes an implementation (or a
zero-arg factory, where the contract requires a fresh instance per
check) and asserts the documented behavior.

```python
from semantic_toponav.testing.conformance import (
    run_aligned_rgb_source_conformance,
    run_conflict_policy_conformance,
    run_encoder_backend_conformance,
    run_llm_backend_conformance,
    run_scheduler_conformance,
    run_transport_conformance,
)
```

The suites raise `AssertionError` on failure, so they plug straight
into pytest. They do not import pytest themselves — adapter authors
can call them as runtime self-checks during initialization too.

## When to use them

Run the relevant suite against every adapter implementation you ship.
The in-tree implementations (`HashingBackend`, `EchoBackend`,
`StaticImageRgbSource`, `SharedScheduler`, `SchedulerClient`,
`LocalTransport`, `HttpTransport`, `first_come_first_served`,
`priority_based`) are themselves exercised through these suites in
`tests/test_conformance_builtins.py`; mirror that style.

The suites cover the public Protocol contract, not implementation
details. Your adapter still owns its own behavioral tests
(model-specific accuracy, transport-specific failure modes,
policy-specific tie-breaking) — conformance is the floor, not the
ceiling.

## Suite-by-suite reference

### `run_llm_backend_conformance(backend)`

Targets [`LLMBackend`](../semantic_toponav/llm/backends.py).
Asserts:

- `isinstance(backend, LLMBackend)` (structural check against the
  runtime-checkable Protocol).
- `generate(prompt)` returns `str`.
- `generate(prompt, system="...")` returns `str`.
- The backend is reusable across multiple calls.

Determinism is intentionally not required, so cloud backends like
`AnthropicBackend` can pass.

```python
from semantic_toponav.llm import EchoBackend
from semantic_toponav.testing.conformance import run_llm_backend_conformance

def test_my_backend() -> None:
    run_llm_backend_conformance(EchoBackend())
```

### `run_encoder_backend_conformance(backend)`

Targets the encoder
[`Backend`](../semantic_toponav/encoders/backends.py). Asserts:

- Structural conformance plus `dim > 0` (int).
- `embed_text` / `embed_image` return `list[float]` of length `dim`.
- Returned vectors are **L2-normalized** (within `1e-3`), so cosine
  similarity collapses to a dot product — this is what
  `find_nodes_by_embedding` relies on.
- `embed_images([a, b])` returns a length-2 list of normalized
  vectors.
- `embed_images([])` returns `[]`.

### `run_aligned_rgb_source_conformance(source, *, sample_bbox=None, backend=None)`

Targets [`AlignedRgbSource`](../semantic_toponav/encoders/rgb_source.py).
Asserts:

- Structural conformance.
- `shape` returns a `(height, width)` 2-tuple of positive ints.
- `crop(bbox)` returns a non-`None` patch for a valid bbox, and the
  source is reusable (calling `crop` again works).
- The cropped patch is consumable by an encoder `Backend` end-to-end
  (the suite defaults to `HashingBackend(dim=16)`; pass `backend=` if
  your crop returns something fancier than ndarray / bytes / path).

```python
import numpy as np
from semantic_toponav.encoders import StaticImageRgbSource
from semantic_toponav.testing.conformance import (
    run_aligned_rgb_source_conformance,
)

def test_my_source() -> None:
    image = np.zeros((128, 256, 3), dtype="uint8")
    run_aligned_rgb_source_conformance(StaticImageRgbSource(image))
```

For an adapter that only supports specific bbox sizes (e.g. a Mast3R
rerender service that rejects non-square crops), pass a known-good
bbox via `sample_bbox=`.

### `run_scheduler_conformance(factory)`

Targets [`SchedulerProtocol`](../semantic_toponav/coordination/rpc.py).
Takes a **zero-arg factory** because the suite needs a fresh
scheduler per subtest. Asserts:

- Empty initial state (`len == 0`, `reservations() == []`).
- Basic claim / release cycle (granted, denied-on-overlap, FCFS
  default).
- `release_all(unknown_agent)` returns `0` without raising.
- `claim_many` grants every request when none overlap.
- `conflicts` / `claims_for` / `table` return the right entries.
- `reservations()` returns a snapshot, not a live view — mutations
  after the call must not change the returned list.

```python
from semantic_toponav.coordination import SharedScheduler
from semantic_toponav.testing.conformance import run_scheduler_conformance

def test_my_scheduler() -> None:
    run_scheduler_conformance(SharedScheduler)
```

### `run_transport_conformance(transport, *, service)`

Targets [`Transport`](../semantic_toponav/coordination/rpc.py). Requires
the transport to be wired to a `SchedulerService` — pass the service
explicitly so the suite can confirm mutations land on the server side.

```python
from semantic_toponav.coordination import (
    LocalTransport, SchedulerService, SharedScheduler,
)
from semantic_toponav.testing.conformance import run_transport_conformance

def test_my_transport() -> None:
    service = SchedulerService(SharedScheduler())
    transport = LocalTransport(service)
    run_transport_conformance(transport, service=service)
```

For network transports, spin up the server inside the test and tear
it down after — `HttpSchedulerServer` doubles as a context manager,
which the in-tree test uses verbatim.

### `run_conflict_policy_conformance(policy, *, check_empty_conflicts_grants=True)`

Targets the
[`ConflictPolicy`](../semantic_toponav/coordination/policies.py)
callable type. Asserts:

- The callable returns a `ClaimDecision`.
- `decision.preempted` is always a subset of the `conflicts` argument
  (the scheduler refuses to evict reservations the policy never saw).
- The policy must not mutate its `conflicts` argument in place.
- Optional (default on): zero conflicts ⇒ `grant=True`. Both shipped
  policies satisfy this; policies that deny on other grounds
  (deadline, licensing, capacity) should pass
  `check_empty_conflicts_grants=False`.

## Adding new Protocols

The current bar (set in `project_roadmap_post_pr35.md`) before
introducing a new Protocol:

- At least 2 implementations OR isolation of a heavy optional dep.
- Core deterministic behavior works without the Protocol present.
- Conformance tests exist — i.e. a new `run_<name>_conformance`
  function in this subpackage.
- Small input/output that doesn't leak domain internals.
- Defined fallback on failure.

The conformance bullet is what this subpackage is for: ship the
suite alongside the Protocol, not after.
