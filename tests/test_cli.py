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
