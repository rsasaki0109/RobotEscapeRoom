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
- Failure-mode prompts (empty string, ~8KB body, non-ASCII content
  including CJK / accented Latin / emoji) all return `str`, and the
  backend remains usable after them — guards against adapters that
  latch into a broken state on degenerate input.

Determinism is intentionally not required, so cloud backends like
`AnthropicBackend` can pass.

```python
from semantic_toponav.llm import EchoBackend
from semantic_toponav.testing.conformance import run_llm_backend_conformance

def test_my_backend() -> None:
    run_llm_backend_conformance(EchoBackend())
```

### `run_encoder_backend_conformance(backend, *, check_determinism=True)`

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
- `embed_images([image])` agrees with `embed_image(image)` in dim
  and shape — singular and batched paths must not diverge.
- `embed_text("")` returns a normalized dim-correct vector rather
  than crashing or emitting an all-zero vector that would break
  cosine math downstream.
- `cos(v, v) ≈ 1.0` for the unit vectors returned — catches a
  backend that secretly emits a constant non-zero unit vector
  (which would pass the L2 check but produce useless retrieval).
- When `check_determinism=True` (default), `embed_text` returns the
  same vector when called twice on the same input. Disable for
  stochastic-augmentation backends.

### `run_aligned_rgb_source_conformance(source, *, sample_bbox=None, backend=None)`

Targets [`AlignedRgbSource`](../semantic_toponav/encoders/rgb_source.py).
Asserts:

- Structural conformance.
- `shape` returns a `(height, width)` 2-tuple of positive ints.
- `shape` is stable across reads — calling it twice yields the same
  tuple. A source whose dimensions drift between calls would silently
  invalidate every cached bbox.
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
- `release` is idempotent: calling it twice on the same
  `(agent, resource)` removes once and reports `0` the second time;
  `release` on an unknown pair returns `0` (does not raise).
- `claim_many` is atomic on denial — a batch that hits a conflict
  partway through rolls back any reservations granted earlier in the
  same batch, and the result list ends at the denial. `claim_many([])`
  is a no-op that returns `[]`.
- Half-open adjacency: a claim on `[09:00, 09:30)` does not conflict
  with a follow-up on `[09:30, 10:00)` — important for fleet
  schedulers that pipeline back-to-back hand-offs.
- `conflicts(unknown_resource, ...)` returns `[]` rather than leaking
  entries from other resources.

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
Round-trips `ping`, `claim`, and `release` to verify both directions
of the wire, plus a second `ping` to catch single-shot transports
that die after one message.

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
- `decision.preempted` contains no duplicate entries — a double-counted
  conflict would silently inflate downstream preemption metrics.
- The policy must not mutate its `conflicts` argument in place.
- The policy must not mutate the `scheduler` argument either — it sees
  the live scheduler for inspection only; the caller commits the
  decision. A policy that writes through the scheduler would
  double-apply the effect.
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
