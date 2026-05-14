"""Shared CLI helpers for opt-in LLM-augmentation.

Both ``describe-path`` and ``resolve`` accept the same ``--llm-*``
flags. Centralising them here keeps the argparse setup uniform and
makes the backend construction logic testable in one place.

When ``--llm-backend`` is omitted, :func:`build_llm_backend_from_args`
returns ``None`` and the calling command is expected to run its
deterministic path (the existing :func:`describe_path` /
:func:`resolve_goal` behavior). That's how the new flags stay
fully optional.
"""

from __future__ import annotations

import argparse

from semantic_toponav.llm.backends import (
    AnthropicBackend,
    EchoBackend,
    LLMBackend,
)


def add_llm_args(p: argparse.ArgumentParser, *, with_style: bool = False) -> None:
    """Add the standard ``--llm-*`` argument set to ``p``.

    ``with_style=True`` adds ``--llm-style``, which only makes sense
    for narration commands (``describe-path``); the resolver doesn't
    rewrite prose, so it gets the smaller set.
    """
    p.add_argument(
        "--llm-backend",
        choices=["echo", "anthropic"],
        default=None,
        help=(
            "opt into LLM-augmented output: `echo` is a deterministic "
            "test/demo backend (no deps), `anthropic` calls the Anthropic "
            "API (requires the [llm] extra). When omitted, the command "
            "runs its deterministic path unchanged."
        ),
    )
    p.add_argument(
        "--llm-model",
        default=AnthropicBackend.DEFAULT_MODEL,
        help=(
            f"model id for --llm-backend anthropic "
            f"(default: {AnthropicBackend.DEFAULT_MODEL})"
        ),
    )
    p.add_argument(
        "--llm-api-key",
        default=None,
        help=(
            "Anthropic API key for --llm-backend anthropic. Defaults to "
            "the ANTHROPIC_API_KEY environment variable."
        ),
    )
    p.add_argument(
        "--llm-script",
        action="append",
        metavar="RESPONSE",
        help=(
            "scripted response for --llm-backend echo (repeatable). "
            "Useful for tests; ignored by other backends."
        ),
    )
    p.add_argument(
        "--llm-max-tokens",
        type=int,
        default=1024,
        help="max output tokens for --llm-backend anthropic (default: 1024)",
    )
    if with_style:
        p.add_argument(
            "--llm-style",
            default=None,
            metavar="HINT",
            help=(
                "natural-language style hint passed to the rewrite "
                "prompt (e.g. 'concise', 'friendly', 'verbose')"
            ),
        )


def build_llm_backend_from_args(args: argparse.Namespace) -> LLMBackend | None:
    """Construct an :class:`LLMBackend` from ``--llm-*`` args.

    Returns ``None`` when ``--llm-backend`` was not supplied — the
    caller is expected to run its deterministic path in that case.
    """
    kind = getattr(args, "llm_backend", None)
    if kind is None:
        return None
    if kind == "echo":
        script = getattr(args, "llm_script", None) or None
        return EchoBackend(script=script)
    if kind == "anthropic":
        return AnthropicBackend(
            model=getattr(args, "llm_model", AnthropicBackend.DEFAULT_MODEL),
            api_key=getattr(args, "llm_api_key", None),
            max_tokens=getattr(args, "llm_max_tokens", 1024),
        )
    raise ValueError(f"unknown --llm-backend {kind!r}")
