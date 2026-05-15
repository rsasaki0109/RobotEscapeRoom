"""Conformance suite for :class:`semantic_toponav.llm.LLMBackend`.

The contract is intentionally narrow — one ``generate(prompt, *,
system=None) -> str`` method — so the suite is short. It verifies:

* Structural :func:`isinstance` against the runtime-checkable Protocol.
* ``generate`` returns a ``str`` (never bytes, never a richer envelope).
* The optional ``system`` kwarg is accepted both as ``None`` and as a
  non-empty string.
* Multiple calls succeed (i.e. the backend is reusable, not single-shot).

Determinism is intentionally *not* asserted: a real cloud backend like
:class:`~semantic_toponav.llm.AnthropicBackend` is not deterministic,
and forcing scripted determinism would prevent that backend from
passing.
"""

from __future__ import annotations

from semantic_toponav.llm.backends import LLMBackend


def run_llm_backend_conformance(backend: LLMBackend) -> None:
    """Run the :class:`LLMBackend` conformance checks.

    Parameters
    ----------
    backend:
        An :class:`LLMBackend` implementation. The suite issues a small
        number of cheap ``generate`` calls against it, so a backend
        wired to a paid model will incur a few requests' worth of
        cost — prefer testing such backends against an offline stub.
    """

    assert isinstance(backend, LLMBackend), (
        f"{type(backend).__name__} does not satisfy the LLMBackend Protocol "
        "(missing generate)"
    )

    out = backend.generate("conformance: hello")
    assert isinstance(out, str), (
        f"generate returned {type(out).__name__}, expected str"
    )

    with_system = backend.generate(
        "conformance: with system",
        system="You are a terse conformance probe.",
    )
    assert isinstance(with_system, str), (
        f"generate(system=...) returned {type(with_system).__name__}, "
        "expected str"
    )

    # Reusable across multiple calls.
    second = backend.generate("conformance: second call")
    assert isinstance(second, str), (
        "backend stopped returning str on the second call — generate must "
        "remain callable repeatedly"
    )
