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


def test_resolve_with_vlm_backend_attaches_embedding_scores(capsys) -> None:
    """--vlm-backend hashing should populate embedding_scores in JSON
    output without stamped embeddings — empty dict is the expected
    no-op (graph has no embeddings stamped)."""
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
            "Top match: meeting_room\nReason: matches.",
            "--vlm-backend",
            "hashing",
            "--vlm-dim",
            "32",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    # No embeddings stamped -> scores dict exists but is empty.
    assert payload["llm"]["embedding_scores"] == {}


def test_resolve_llm_clarify_surfaces_question_in_json(capsys) -> None:
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
            "Clarify: which floor did you mean?",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["llm"]["clarification"] is not None
    assert "which floor" in payload["llm"]["clarification"]["question"]
    assert isinstance(payload["llm"]["clarification"]["candidate_ids"], list)


def test_resolve_clarify_with_threads_chosen_id(capsys) -> None:
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
            "Top match: meeting_room\nReason: chosen by user.",
            "--clarify-with",
            "meeting_room",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    # The pool was narrowed to the chosen id; only one candidate remains.
    assert len(payload["candidates"]) == 1
    assert payload["candidates"][0]["node_id"] == "meeting_room"


def test_resolve_clarify_free_appends_to_query(capsys) -> None:
    rc = main(
        [
            "resolve",
            EXAMPLE_YAML,
            "office",
            "--format",
            "json",
            "--llm-backend",
            "echo",
            "--llm-script",
            "Top match: office_2f\nReason: second floor.",
            "--clarify-free",
            "on the second floor",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert "second floor" in payload["query"]


def test_resolve_clarify_with_without_llm_warns(capsys) -> None:
    rc = main(
        [
            "resolve",
            EXAMPLE_YAML,
            "meeting room",
            "--clarify-with",
            "meeting_room",
        ]
    )
    err = capsys.readouterr().err
    assert rc == 0
    assert "ignored without --llm-backend" in err


def test_resolve_vlm_backend_without_llm_warns(capsys) -> None:
    """--vlm-backend without --llm-backend is a no-op; emit a warning."""
    rc = main(
        [
            "resolve",
            EXAMPLE_YAML,
            "meeting room",
            "--format",
            "json",
            "--vlm-backend",
            "hashing",
        ]
    )
    err = capsys.readouterr().err
    assert rc == 0
    assert "ignored without --llm-backend" in err
