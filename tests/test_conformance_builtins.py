"""Run the public conformance suites against every in-tree Protocol
implementation.

The point of this file is twofold:

1. Catch regressions where a built-in implementation drifts away from
   the documented Protocol contract (forgets to L2-normalize, returns
   bytes instead of str, …).
2. Serve as a worked example for adapter authors — anything they want
   to plug in (a Mast3R aligned-RGB source, a NATS-backed transport,
   a deadline-aware conflict policy) gets exactly the same checks.

Backends that need optional dependencies (CLIP for the encoder
suite, the ``anthropic`` SDK for the real LLM backend) are skipped
when those deps are absent — we never want pytest to fail simply
because the ``[vlm]`` extra wasn't installed.
"""

from __future__ import annotations

import pytest

from semantic_toponav.coordination.policies import (
    first_come_first_served,
    priority_based,
)
from semantic_toponav.coordination.rpc import (
    LocalTransport,
    SchedulerClient,
    SchedulerService,
)
from semantic_toponav.coordination.scheduler import SharedScheduler
from semantic_toponav.encoders import HashingBackend
from semantic_toponav.llm import EchoBackend
from semantic_toponav.testing.conformance import (
    run_conflict_policy_conformance,
    run_encoder_backend_conformance,
    run_llm_backend_conformance,
    run_scheduler_conformance,
    run_transport_conformance,
)

# ---- LLMBackend --------------------------------------------------------------


def test_echo_backend_is_conformant() -> None:
    run_llm_backend_conformance(EchoBackend())


def test_echo_backend_with_script_is_conformant() -> None:
    # A pre-loaded script must not interfere with the conformance probe.
    run_llm_backend_conformance(EchoBackend(script=["first", "second"]))


# ---- encoder Backend ---------------------------------------------------------


def test_hashing_backend_is_conformant() -> None:
    run_encoder_backend_conformance(HashingBackend(dim=32))


def test_hashing_backend_alternate_dim_is_conformant() -> None:
    # Custom dim — exercises the "embed_text length == backend.dim" path.
    run_encoder_backend_conformance(HashingBackend(dim=64))


# ---- AlignedRgbSource --------------------------------------------------------


def test_static_image_rgb_source_is_conformant() -> None:
    np = pytest.importorskip("numpy")
    from semantic_toponav.encoders import StaticImageRgbSource
    from semantic_toponav.testing.conformance import (
        run_aligned_rgb_source_conformance,
    )

    image = np.zeros((8, 8, 3), dtype="uint8")
    image[:4, :4] = [200, 0, 0]
    run_aligned_rgb_source_conformance(StaticImageRgbSource(image))


# ---- SchedulerProtocol -------------------------------------------------------


def test_shared_scheduler_is_conformant() -> None:
    run_scheduler_conformance(SharedScheduler)


def test_scheduler_client_via_local_transport_is_conformant() -> None:
    def factory() -> SchedulerClient:
        service = SchedulerService(SharedScheduler())
        transport = LocalTransport(service)
        return SchedulerClient(transport)

    run_scheduler_conformance(factory)


# ---- Transport ---------------------------------------------------------------


def test_local_transport_is_conformant() -> None:
    service = SchedulerService(SharedScheduler())
    transport = LocalTransport(service)
    run_transport_conformance(transport, service=service)


def test_http_transport_is_conformant() -> None:
    from semantic_toponav.coordination.http_transport import (
        HttpSchedulerServer,
        HttpTransport,
    )

    service = SchedulerService(SharedScheduler())
    with HttpSchedulerServer(service) as server:
        transport = HttpTransport(server.url)
        run_transport_conformance(transport, service=service)


# ---- ConflictPolicy ----------------------------------------------------------


def test_first_come_first_served_is_conformant() -> None:
    run_conflict_policy_conformance(first_come_first_served)


def test_priority_based_is_conformant() -> None:
    run_conflict_policy_conformance(priority_based)
