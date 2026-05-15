"""Reusable conformance suites for the public Protocols.

Each Protocol shipped by semantic-toponav (:class:`LLMBackend`,
encoder :class:`Backend`, :class:`AlignedRgbSource`,
:class:`SchedulerProtocol`, :class:`Transport`, the
``ConflictPolicy`` callable type) exposes a ``run_<name>_conformance``
helper here. The helpers are plain functions that take an
implementation (or a zero-arg factory, where the contract requires a
fresh instance per check) and run a small battery of assertions
covering the documented contract.

The intended usage from an external adapter package is::

    from semantic_toponav.testing.conformance import (
        run_aligned_rgb_source_conformance,
    )

    def test_my_mast3r_source_is_conformant() -> None:
        src = MyMast3RRgbSource(...)
        run_aligned_rgb_source_conformance(src)

The helpers raise :class:`AssertionError` on failure, so they plug
straight into pytest. They do not import pytest themselves, which keeps
the suite usable as a runtime self-check for adapter authors too.

The in-tree implementations are exercised against these helpers in
``tests/test_conformance_builtins.py``.
"""

from semantic_toponav.testing.conformance.aligned_rgb_source import (
    run_aligned_rgb_source_conformance,
)
from semantic_toponav.testing.conformance.conflict_policy import (
    run_conflict_policy_conformance,
)
from semantic_toponav.testing.conformance.encoder_backend import (
    run_encoder_backend_conformance,
)
from semantic_toponav.testing.conformance.llm_backend import (
    run_llm_backend_conformance,
)
from semantic_toponav.testing.conformance.scheduler import (
    run_scheduler_conformance,
)
from semantic_toponav.testing.conformance.transport import (
    run_transport_conformance,
)

__all__ = [
    "run_aligned_rgb_source_conformance",
    "run_conflict_policy_conformance",
    "run_encoder_backend_conformance",
    "run_llm_backend_conformance",
    "run_scheduler_conformance",
    "run_transport_conformance",
]
