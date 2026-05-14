"""Smoke tests for the CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from semantic_toponav.cli.main import main

EXAMPLE_YAML = str(Path(__file__).resolve().parents[1] / "examples" / "indoor_office.yaml")


def test_validate_command(capsys) -> None:
    rc = main(["validate", EXAMPLE_YAML])
    out = capsys.readouterr().out
    assert rc == 0
    assert "ok" in out


def test_validate_command_missing_file(capsys, tmp_path) -> None:
    rc = main(["validate", str(tmp_path / "no.yaml")])
    err = capsys.readouterr().err
    assert rc != 0
    assert "error" in err


def test_plan_text(capsys) -> None:
    rc = main(["plan", EXAMPLE_YAML, "entrance", "meeting_room"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "entrance" in out
    assert "meeting_room" in out


def test_plan_json(capsys) -> None:
    rc = main(["plan", EXAMPLE_YAML, "entrance", "meeting_room", "--format", "json"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["path"][0] == "entrance"
    assert payload["path"][-1] == "meeting_room"


def test_plan_with_avoid_restricted_changes_path(capsys) -> None:
    rc = main(
        [
            "plan",
            EXAMPLE_YAML,
            "entrance",
            "meeting_room",
            "--avoid-restricted",
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert "lobby_intersection" in payload["path"]


def test_waypoints_text(capsys) -> None:
    rc = main(["waypoints", EXAMPLE_YAML, "entrance", "meeting_room"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Semantic Waypoints" in out
    assert "Start at Entrance" in out


def test_waypoints_json(capsys) -> None:
    rc = main(["waypoints", EXAMPLE_YAML, "entrance", "office_2f", "--format", "json"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert "waypoints" in payload
    assert payload["waypoints"][0]["node_id"] == "entrance"


def test_resolve_text(capsys) -> None:
    rc = main(["resolve", EXAMPLE_YAML, "second", "floor", "office"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "office_2f" in out
    assert "floor 2 matches" in out
    assert "label matches 'office'" in out


def test_resolve_json(capsys) -> None:
    rc = main(["resolve", EXAMPLE_YAML, "kitchen", "--format", "json"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["query"] == "kitchen"
    assert payload["candidates"][0]["node_id"] == "kitchen"
    assert payload["candidates"][0]["score"] >= 2.0


def test_resolve_no_match_prints_message(capsys) -> None:
    rc = main(["resolve", EXAMPLE_YAML, "the", "secret", "garden"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "no matches" in out


def test_resolve_top_k_limits(capsys) -> None:
    rc = main(["resolve", EXAMPLE_YAML, "floor", "2", "--top-k", "2", "--format", "json"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert len(payload["candidates"]) == 2


def test_describe_path_text(capsys) -> None:
    rc = main(["describe-path", EXAMPLE_YAML, "entrance", "meeting_room"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Instructions" in out
    assert "Start at Entrance" in out
    # The default plan takes the restricted shortcut.
    assert "restricted" in out.lower()


def test_describe_path_json(capsys) -> None:
    rc = main(
        [
            "describe-path",
            EXAMPLE_YAML,
            "entrance",
            "office_2f",
            "--avoid-stairs",
            "--prefer-elevator",
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["path"][0] == "entrance"
    assert payload["path"][-1] == "office_2f"
    assert isinstance(payload["steps"], list)
    assert payload["steps"][0]["text"].startswith("Start at Entrance")
    # An elevator transit step must appear when riding the elevator.
    elev_steps = [s for s in payload["steps"] if "Take the elevator from" in s["text"]]
    assert len(elev_steps) == 1
    # And a floor-change call-out alongside.
    assert any("Floor change" in s["text"] for s in payload["steps"])


def test_plot_saves_image(tmp_path) -> None:
    pytest.importorskip("matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    target = tmp_path / "fig.png"
    rc = main(
        [
            "plot",
            EXAMPLE_YAML,
            "--start",
            "entrance",
            "--goal",
            "meeting_room",
            "--avoid-restricted",
            "--save",
            str(target),
        ]
    )
    assert rc == 0
    assert target.exists()
    assert target.stat().st_size > 0


def test_plot_rejects_start_without_goal(capsys) -> None:
    pytest.importorskip("matplotlib")
    rc = main(["plot", EXAMPLE_YAML, "--start", "entrance"])
    err = capsys.readouterr().err
    assert rc != 0
    assert "must be provided together" in err


def test_viewer_writes_html(tmp_path, capsys) -> None:
    pytest.importorskip("pyvis")
    target = tmp_path / "viewer.html"
    rc = main(["viewer", EXAMPLE_YAML, "--output", str(target)])
    assert rc == 0
    assert target.exists()
    contents = target.read_text(encoding="utf-8")
    assert contents.startswith("<")
    assert "vis-network" in contents or "DataSet" in contents
    out = capsys.readouterr().out
    assert "saved" in out


def test_viewer_with_start_and_goal_highlights_path(tmp_path, capsys) -> None:
    pytest.importorskip("pyvis")
    target = tmp_path / "viewer.html"
    rc = main(
        [
            "viewer",
            EXAMPLE_YAML,
            "--start",
            "entrance",
            "--goal",
            "meeting_room",
            "--output",
            str(target),
        ]
    )
    assert rc == 0
    assert target.exists()
    out = capsys.readouterr().out
    assert "highlighted path" in out
    assert "entrance" in out


def test_viewer_rejects_start_without_goal(capsys) -> None:
    pytest.importorskip("pyvis")
    rc = main(["viewer", EXAMPLE_YAML, "--start", "entrance"])
    err = capsys.readouterr().err
    assert rc != 0
    assert "must be provided together" in err
