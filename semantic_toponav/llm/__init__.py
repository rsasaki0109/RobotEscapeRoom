"""Pluggable LLM backends for natural-language augmentation layers.

This subpackage defines the :class:`LLMBackend` protocol — a thin
``generate(prompt, *, system=None) -> str`` contract — plus three
concrete implementations:

* :class:`EchoBackend` — scripted/echo backend with zero dependencies.
  Returns canned responses for tests and offline demos; falls back to
  echoing the last line of the prompt when the script is exhausted.
* :class:`AnthropicBackend` — lazy wrapper around the ``anthropic``
  Python SDK. Requires the ``[llm]`` extra. Used by
  :func:`semantic_toponav.waypoint.llm_describe.llm_describe_path` and
  :func:`semantic_toponav.query.llm_resolve.llm_resolve_goal` to rewrite
  deterministic navigation output into natural prose / refined ranking.
* :class:`OllamaBackend` — local LLM over the Ollama HTTP API, standard
  library only. The real-model path with no API key and no cloud.

The deterministic floors (:func:`describe_path`, :func:`resolve_goal`)
remain authoritative — the LLM layer is purely additive. Callers that
omit a backend see the same behavior they always had.
"""

from semantic_toponav.llm.backends import (
    AnthropicBackend,
    EchoBackend,
    LLMBackend,
    OllamaBackend,
)

__all__ = [
    "AnthropicBackend",
    "EchoBackend",
    "LLMBackend",
    "OllamaBackend",
]
