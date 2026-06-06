"""Concrete LLM backends.

The :class:`LLMBackend` protocol is the contract every augmentation
layer (``llm_describe_path``, ``llm_resolve_goal``) talks to: a single
``generate(prompt, *, system=None) -> str`` method. Two concrete
backends ship in this module:

* :class:`EchoBackend` — scripted / echo backend with zero
  dependencies. Lets tests pin a sequence of responses without dragging
  in a real model client, and falls back to a deterministic echo when
  the script runs out so it's still usable in offline demos.
* :class:`AnthropicBackend` — lazy wrapper around the official
  ``anthropic`` SDK. The client is constructed on first call so just
  importing this module does not require the ``[llm]`` extra.
* :class:`OllamaBackend` — talks to a locally running `Ollama
  <https://ollama.com>`_ server over its HTTP API using only the
  standard library (``urllib``). No API key, no cloud, no extra
  dependency — the real-model path you can run on your own machine.

All three record the prompts they receive so callers (and tests) can
introspect what was actually sent. The deterministic ``describe_path``
and ``resolve_goal`` floors are unchanged; this subpackage only adds a
*rewrite / refine* layer on top.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LLMBackend(Protocol):
    """Minimal contract for an LLM text generator.

    All backends accept an optional ``system`` instruction (Anthropic's
    SDK takes a dedicated ``system`` parameter; OpenAI-style backends
    typically encode it as the first message — implementations decide).
    Return text is the model's response as a plain string — no message
    envelope, no token metadata. Callers parse the string themselves.
    """

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        """Generate a single response for ``prompt``."""
        ...


class EchoBackend:
    """Deterministic LLM backend with no external dependencies.

    Designed for two use cases:

    1. **Tests**: pass a ``script`` of canned responses; ``generate``
       returns them in order. Once exhausted, the backend falls back to
       its echo behavior so a test that under-counts the calls still
       gets a meaningful (but deterministic) string instead of an
       exception.
    2. **Offline demos**: no script needed — every call returns
       ``f"[echo] {last_nonblank_line_of_prompt}"``.

    Each call is recorded in ``calls`` (a list of
    ``{"prompt": str, "system": str | None}`` dicts) so callers can
    assert on exactly what got sent to the model. This is how the
    augmentation-bridge unit tests verify their prompts.
    """

    def __init__(self, script: list[str] | None = None) -> None:
        self._script: list[str] = list(script) if script else []
        self._index = 0
        self.calls: list[dict[str, Any]] = []

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        self.calls.append({"prompt": prompt, "system": system})
        if self._index < len(self._script):
            response = self._script[self._index]
            self._index += 1
            return response
        return self._echo(prompt)

    @staticmethod
    def _echo(prompt: str) -> str:
        stripped = prompt.strip()
        if not stripped:
            return "[echo]"
        last = stripped.splitlines()[-1].strip()
        return f"[echo] {last}"


class AnthropicBackend:
    """Lazy wrapper around the official ``anthropic`` Python SDK.

    Requires the ``[llm]`` extra (``anthropic>=0.34``). The client is
    constructed on first call to keep import cost and credential checks
    out of the CLI bootstrap path.

    The SDK reads ``ANTHROPIC_API_KEY`` from the environment by
    default; pass ``api_key`` explicitly to override. ``model`` defaults
    to a fast Sonnet build sufficient for short rewrite prompts.
    """

    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        api_key: str | None = None,
        max_tokens: int = 1024,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._max_tokens = max_tokens
        self._client: Any = None
        self.calls: list[dict[str, Any]] = []

    @property
    def model(self) -> str:
        return self._model

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        self.calls.append({"prompt": prompt, "system": system})
        self._ensure_client()
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system is not None:
            kwargs["system"] = system
        response = self._client.messages.create(**kwargs)
        # SDK returns a structured Message; the content is a list of
        # blocks. We concatenate all text-typed blocks so callers always
        # see plain text regardless of how the model framed its reply.
        parts: list[str] = []
        for block in getattr(response, "content", []) or []:
            block_type = getattr(block, "type", None)
            if block_type == "text":
                parts.append(getattr(block, "text", ""))
        return "".join(parts).strip()

    def _ensure_client(self) -> None:
        if self._client is not None:
            return
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "AnthropicBackend requires the [llm] extra. Install with "
                "`pip install 'semantic-toponav[llm]'`"
            ) from exc
        if self._api_key is not None:
            self._client = anthropic.Anthropic(api_key=self._api_key)
        else:
            self._client = anthropic.Anthropic()


# Qwen / DeepSeek-style reasoning models wrap their chain-of-thought in
# <think>...</think>. The resolver / describer parsers want the final
# answer only, so we strip those blocks before returning.
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class OllamaBackend:
    """Local LLM backend over the `Ollama <https://ollama.com>`_ HTTP API.

    Talks to a server you run yourself (``ollama serve``, default
    ``http://localhost:11434``) using only the standard library — no API
    key, no cloud round-trip, no extra dependency. This is the real-model
    path for grounding / describer evals when a paid cloud key is not
    wanted: pull a model (e.g. ``ollama pull qwen3.5``) and point the eval
    at it with ``--llm-backend ollama --llm-model qwen3.5:latest``.

    ``temperature`` defaults to ``0.0`` for the most reproducible output a
    local model offers (sampling is not bit-exact across builds, so treat
    the numbers as a single run, not a fixed fixture). ``think`` is sent as
    ``False`` to ask reasoning models to skip the chain-of-thought; any
    ``<think>...</think>`` block that still appears is stripped so the
    resolver / describer line parsers see only the final answer.
    """

    DEFAULT_MODEL = "qwen3.5:latest"
    DEFAULT_HOST = "http://localhost:11434"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        host: str = DEFAULT_HOST,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        think: bool = False,
        timeout: float = 120.0,
    ) -> None:
        self._model = model
        self._host = host.rstrip("/")
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._think = think
        self._timeout = timeout
        self.calls: list[dict[str, Any]] = []

    @property
    def model(self) -> str:
        return self._model

    def generate(self, prompt: str, *, system: str | None = None) -> str:
        self.calls.append({"prompt": prompt, "system": system})
        messages: list[dict[str, str]] = []
        if system is not None:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "think": self._think,
            "options": {
                "temperature": self._temperature,
                "num_predict": self._max_tokens,
            },
        }
        data = self._post("/api/chat", body)
        content = data.get("message", {}).get("content", "")
        return _THINK_BLOCK.sub("", content).strip()

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._host}{path}"
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"OllamaBackend could not reach {url}: {exc}. Is the Ollama "
                f"server running (`ollama serve`) and the model pulled "
                f"(`ollama pull {self._model}`)?"
            ) from exc
