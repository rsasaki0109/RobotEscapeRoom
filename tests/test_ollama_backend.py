"""OllamaBackend unit tests — fully mocked, no server required.

The backend talks to a local Ollama server over HTTP. These tests patch
``urllib.request.urlopen`` so the suite runs in CI with no Ollama process:
they verify the request shape, response parsing, ``<think>`` stripping, the
friendly connection error, and the LLMBackend conformance suite.
"""

from __future__ import annotations

import json

import pytest

from semantic_toponav.llm import LLMBackend, OllamaBackend
from semantic_toponav.llm import backends as backends_mod
from semantic_toponav.testing.conformance import run_llm_backend_conformance


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._data = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *exc) -> bool:  # noqa: ANN002
        return False


def _patch_urlopen(monkeypatch, content: str, capture: dict | None = None):
    def fake_urlopen(req, timeout=None):  # noqa: ANN001
        if capture is not None:
            capture["url"] = req.full_url
            capture["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp({"message": {"role": "assistant", "content": content}})

    monkeypatch.setattr(backends_mod.urllib.request, "urlopen", fake_urlopen)


def test_satisfies_protocol() -> None:
    assert isinstance(OllamaBackend(), LLMBackend)


def test_generate_returns_clean_content(monkeypatch) -> None:
    _patch_urlopen(monkeypatch, "Top match: kitchen_1f")
    b = OllamaBackend(model="qwen3.5:latest")
    out = b.generate("the kitchen")
    assert out == "Top match: kitchen_1f"
    assert b.calls == [{"prompt": "the kitchen", "system": None}]


def test_strips_think_block(monkeypatch) -> None:
    _patch_urlopen(
        monkeypatch,
        "<think>the user wants the kitchen, which is kitchen_1f</think>\n"
        "Top match: kitchen_1f",
    )
    out = OllamaBackend().generate("the kitchen")
    assert "<think>" not in out
    assert out == "Top match: kitchen_1f"


def test_request_shape_carries_model_system_and_options(monkeypatch) -> None:
    capture: dict = {}
    _patch_urlopen(monkeypatch, "ok", capture=capture)
    b = OllamaBackend(model="gemma3:4b", host="http://localhost:11434")
    b.generate("hello", system="be terse")
    assert capture["url"] == "http://localhost:11434/api/chat"
    body = capture["body"]
    assert body["model"] == "gemma3:4b"
    assert body["stream"] is False
    assert body["think"] is False
    assert body["options"]["temperature"] == 0.0
    assert body["messages"] == [
        {"role": "system", "content": "be terse"},
        {"role": "user", "content": "hello"},
    ]


def test_no_system_omits_system_message(monkeypatch) -> None:
    capture: dict = {}
    _patch_urlopen(monkeypatch, "ok", capture=capture)
    OllamaBackend().generate("hello")
    roles = [m["role"] for m in capture["body"]["messages"]]
    assert roles == ["user"]


def test_connection_error_is_friendly(monkeypatch) -> None:
    import urllib.error

    def boom(req, timeout=None):  # noqa: ANN001
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(backends_mod.urllib.request, "urlopen", boom)
    with pytest.raises(RuntimeError, match="could not reach"):
        OllamaBackend().generate("hello")


def test_host_trailing_slash_normalized(monkeypatch) -> None:
    capture: dict = {}
    _patch_urlopen(monkeypatch, "ok", capture=capture)
    OllamaBackend(host="http://localhost:11434/").generate("hi")
    assert capture["url"] == "http://localhost:11434/api/chat"


def test_passes_llm_backend_conformance(monkeypatch) -> None:
    # A fixed valid reply satisfies the (determinism-agnostic) suite.
    _patch_urlopen(monkeypatch, "Top match: x")
    run_llm_backend_conformance(OllamaBackend())


def test_cli_builds_ollama_backend() -> None:
    from argparse import Namespace

    from semantic_toponav.cli.llm_cli import build_llm_backend_from_args

    args = Namespace(
        llm_backend="ollama", llm_model=None,
        llm_host="http://example:11434", llm_max_tokens=512,
    )
    backend = build_llm_backend_from_args(args)
    assert isinstance(backend, OllamaBackend)
    assert backend.model == OllamaBackend.DEFAULT_MODEL  # None -> default
    assert backend._host == "http://example:11434"


def test_cli_ollama_respects_explicit_model() -> None:
    from argparse import Namespace

    from semantic_toponav.cli.llm_cli import build_llm_backend_from_args

    args = Namespace(
        llm_backend="ollama", llm_model="gemma4:latest",
        llm_host=OllamaBackend.DEFAULT_HOST, llm_max_tokens=1024,
    )
    backend = build_llm_backend_from_args(args)
    assert backend.model == "gemma4:latest"
