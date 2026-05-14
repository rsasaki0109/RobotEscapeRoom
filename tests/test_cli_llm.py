"""CLI integration tests for the --llm-* opt-in flags."""

from __future__ import annotations

import json
from pathlib import Path

from semantic_toponav.cli.main import main

EXAMPLE_YAML = str(Path(__file__).resolve().parents[1] / "examples" / "indoor_office.yaml")


def test_describe_path_without_llm_unchanged(capsys) -> None:
    rc = main(["describe-path", EXAMPLE_YAML, "entrance", "meeting_room"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Instructions:" in out
    # No LLM section when --llm-backend omitted.
    assert "LLM rewrite" not in out


def test_describe_path_with_echo_backend_adds_rewrite_section(capsys) -> None:
    rc = main(
        [
            "describe-path",
            EXAMPLE_YAML,
            "entrance",
            "meeting_room",
            "--llm-backend",
            "echo",
            "--llm-script",
            "1. Walk in.\n2. Head into the corridor.\n3. Settle in the meeting room.",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "LLM rewrite:" in out
    assert "Walk in." in out
    assert "Settle in the meeting room." in out


def test_describe_path_with_echo_backend_falls_back_text_marker(capsys) -> None:
    rc = main(
        [
            "describe-path",
            EXAMPLE_YAML,
            "entrance",
            "meeting_room",
            "--llm-backend",
            "echo",
            # Default echo behavior won't produce numbered lines -> fallback.
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "LLM rewrite (fallback):" in out


def test_describe_path_json_output_includes_llm_block(capsys) -> None:
    rc = main(
        [
            "describe-path",
            EXAMPLE_YAML,
            "entrance",
            "meeting_room",
            "--format",
            "json",
            "--llm-backend",
            "echo",
            "--llm-script",
            "1. one\n2. two\n3. three",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert "llm" in payload
    assert payload["llm"]["used_fallback"] is False
    assert payload["llm"]["steps"] == ["one", "two", "three"]


def test_resolve_without_llm_unchanged(capsys) -> None:
    rc = main(["resolve", EXAMPLE_YAML, "kitchen"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "kitchen" in out
    assert "LLM rerank" not in out


def test_resolve_with_echo_backend_applies_rerank(capsys) -> None:
    rc = main(
        [
            "resolve",
            EXAMPLE_YAML,
            "second floor office",
            "--llm-backend",
            "echo",
            "--llm-script",
            "Top match: office_2f\nReason: it's the office on floor 2.",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "LLM rerank: applied" in out
    assert "office_2f" in out


def test_resolve_with_echo_backend_falls_back_for_bogus_pick(capsys) -> None:
    rc = main(
        [
            "resolve",
            EXAMPLE_YAML,
            "kitchen",
            "--llm-backend",
            "echo",
            "--llm-script",
            "Top match: not_a_real_node\nReason: hallucination.",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "LLM rerank: fallback" in out


def test_resolve_json_output_includes_llm_block(capsys) -> None:
    rc = main(
        [
            "resolve",
            EXAMPLE_YAML,
            "meeting room",
            "--format",
            "json",
            "--llm-backend",
            "echo",
            "--llm-script",
            "Top match: meeting_room\nReason: it's the meeting room.",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["llm"]["pick"] == "meeting_room"
    assert payload["llm"]["used_fallback"] is False
