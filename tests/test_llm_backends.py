"""Tests for the LLM backend protocol + EchoBackend / AnthropicBackend."""

from __future__ import annotations

import pytest

from semantic_toponav.llm.backends import (
    AnthropicBackend,
    EchoBackend,
    LLMBackend,
)


def test_echo_backend_satisfies_protocol() -> None:
    b = EchoBackend()
    assert isinstance(b, LLMBackend)


def test_echo_returns_scripted_responses_in_order() -> None:
    b = EchoBackend(script=["alpha", "beta", "gamma"])
    assert b.generate("p1") == "alpha"
    assert b.generate("p2") == "beta"
    assert b.generate("p3") == "gamma"


def test_echo_falls_back_to_echo_after_script_exhausted() -> None:
    b = EchoBackend(script=["one"])
    assert b.generate("ignored") == "one"
    out = b.generate("first\nsecond\nlast meaningful line")
    assert out == "[echo] last meaningful line"


def test_echo_records_calls_with_system_message() -> None:
    b = EchoBackend()
    b.generate("hello", system="you are terse")
    assert b.calls == [{"prompt": "hello", "system": "you are terse"}]


def test_echo_empty_prompt() -> None:
    b = EchoBackend()
    assert b.generate("") == "[echo]"
    assert b.generate("   \n   ") == "[echo]"


def test_anthropic_backend_lazy_construction_does_not_require_extra() -> None:
    # Just constructing the backend should never hit the import path.
    b = AnthropicBackend(model="claude-sonnet-4-6", api_key="sk-test")
    assert b.model == "claude-sonnet-4-6"


def test_anthropic_backend_raises_helpful_error_when_sdk_missing(monkeypatch) -> None:
    pytest.importorskip("builtins")  # always passes; just to keep test layout consistent
    b = AnthropicBackend(api_key="sk-test")
    # Force the import to fail regardless of what's installed.
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError, match=r"\[llm\] extra"):
        b.generate("hi")


def test_anthropic_backend_generate_concatenates_text_blocks(monkeypatch) -> None:
    # Build a minimal stub anthropic module so generate() exercises the
    # response-block flattening logic without a real network call.
    class _Block:
        def __init__(self, text: str, type: str = "text") -> None:
            self.text = text
            self.type = type

    class _Response:
        def __init__(self) -> None:
            self.content = [
                _Block("hello "),
                _Block("world", type="text"),
                _Block("ignored", type="thinking"),
            ]

    class _Messages:
        def __init__(self) -> None:
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return _Response()

    class _AnthropicClient:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs
            self.messages = _Messages()

    class _StubModule:
        Anthropic = _AnthropicClient

    monkeypatch.setitem(__import__("sys").modules, "anthropic", _StubModule())

    b = AnthropicBackend(api_key="sk-test")
    out = b.generate("ping", system="be concise")
    assert out == "hello world"
    # Confirm the system instruction was forwarded.
    assert b._client.messages.kwargs["system"] == "be concise"
    assert b._client.messages.kwargs["messages"] == [
        {"role": "user", "content": "ping"}
    ]
