"""Tests for the memory-related CLI subcommands and planner flags."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from semantic_toponav.cli.main import main
from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.memory import last_visited, visit_count

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
MULTI_FLOOR = EXAMPLES / "multi_floor_office.yaml"


@pytest.fixture
def graph_copy(tmp_path: Path) -> Path:
    """Copy the multi-floor graph into tmp so mutations don't leak."""
    dst = tmp_path / "graph.yaml"
    shutil.copy(MULTI_FLOOR, dst)
    return dst


# ----------------------------- record-visit -----------------------------


def test_record_visit_in_place_updates_file(graph_copy: Path) -> None:
    rc = main(
        ["record-visit", str(graph_copy), "entrance", "--now", "1000", "--in-place"]
    )
    assert rc == 0
    g = load_graph(graph_copy)
    assert visit_count(g, "entrance") == 1
    assert last_visited(g, "entrance") == 1000.0


def test_record_visit_to_out_file(graph_copy: Path, tmp_path: Path) -> None:
    out = tmp_path / "after.yaml"
    rc = main(
        [
            "record-visit",
            str(graph_copy),
            "entrance",
            "--now",
            "1234.5",
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    assert out.exists()
    g = load_graph(out)
    assert visit_count(g, "entrance") == 1
    # Original file must not have changed.
    g_orig = load_graph(graph_copy)
    assert visit_count(g_orig, "entrance") == 0


def test_record_visit_unknown_node_errors(graph_copy: Path, capsys) -> None:
    rc = main(["record-visit", str(graph_copy), "missing", "--in-place"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "unknown node" in err


def test_record_visit_prints_yaml_to_stdout_by_default(graph_copy: Path, capsys) -> None:
    rc = main(["record-visit", str(graph_copy), "entrance", "--now", "10"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "visit_count: 1" in out
    # Source file is untouched.
    assert visit_count(load_graph(graph_copy), "entrance") == 0


# ----------------------------- record-path -----------------------------


def test_record_path_marks_every_node(graph_copy: Path) -> None:
    rc = main(
        [
            "record-path",
            str(graph_copy),
            "entrance",
            "lobby_1f",
            "stairs_1f",
            "--now",
            "5000",
            "--in-place",
        ]
    )
    assert rc == 0
    g = load_graph(graph_copy)
    for nid in ("entrance", "lobby_1f", "stairs_1f"):
        assert visit_count(g, nid) == 1
        assert last_visited(g, nid) == 5000.0


# ----------------------------- clear-history -----------------------------


def test_clear_history_all_nodes(graph_copy: Path) -> None:
    main(
        [
            "record-path",
            str(graph_copy),
            "entrance",
            "lobby_1f",
            "--now",
            "10",
            "--in-place",
        ]
    )
    rc = main(["clear-history", str(graph_copy), "--in-place"])
    assert rc == 0
    g = load_graph(graph_copy)
    assert visit_count(g, "entrance") == 0
    assert last_visited(g, "lobby_1f") is None


def test_clear_history_subset(graph_copy: Path) -> None:
    main(
        [
            "record-path",
            str(graph_copy),
            "entrance",
            "lobby_1f",
            "--now",
            "10",
            "--in-place",
        ]
    )
    rc = main(["clear-history", str(graph_copy), "entrance", "--in-place"])
    assert rc == 0
    g = load_graph(graph_copy)
    assert visit_count(g, "entrance") == 0
    assert visit_count(g, "lobby_1f") == 1


# ----------------------------- history -----------------------------


def test_history_shows_only_visited_by_default(graph_copy: Path, capsys) -> None:
    main(["record-visit", str(graph_copy), "entrance", "--now", "42", "--in-place"])
    rc = main(["history", str(graph_copy)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "entrance" in out
    assert "42" in out
    # Unvisited nodes hidden by default.
    assert "lobby_1f" not in out


def test_history_all_flag_includes_unvisited(graph_copy: Path, capsys) -> None:
    rc = main(["history", str(graph_copy), "--all"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "entrance" in out
    assert "lobby_1f" in out


def test_history_empty_message_when_no_visits(graph_copy: Path, capsys) -> None:
    rc = main(["history", str(graph_copy)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "no visit history" in out


# ----------------------------- plan + memory flags -----------------------------


def test_plan_prefer_unvisited_reroutes(graph_copy: Path, capsys) -> None:
    # Walk via the stairs route first.
    main(
        [
            "record-path",
            str(graph_copy),
            "entrance",
            "corridor_1f",
            "lobby_1f",
            "stairs_1f",
            "stairs_2f",
            "stairs_3f",
            "corridor_3f",
            "exec_office_3f",
            "--now",
            "1000",
            "--in-place",
        ]
    )
    rc = main(
        [
            "plan",
            str(graph_copy),
            "entrance",
            "exec_office_3f",
            "--prefer-unvisited",
            "--visited-multiplier",
            "10",
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    path = json.loads(out)["path"]
    # The penalized stairs route gets avoided, so an elevator hop appears.
    assert any("elevator" in nid for nid in path)


def test_plan_avoid_recent_uses_injected_now(graph_copy: Path, capsys) -> None:
    main(
        [
            "record-path",
            str(graph_copy),
            "entrance",
            "corridor_1f",
            "lobby_1f",
            "stairs_1f",
            "stairs_2f",
            "stairs_3f",
            "corridor_3f",
            "exec_office_3f",
            "--now",
            "1000",
            "--in-place",
        ]
    )
    rc = main(
        [
            "plan",
            str(graph_copy),
            "entrance",
            "exec_office_3f",
            "--avoid-recent",
            "60",
            "--recent-multiplier",
            "10",
            "--now",
            "1010",
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    path = json.loads(out)["path"]
    assert any("elevator" in nid for nid in path)


def test_plan_avoid_recent_old_visits_ignored(graph_copy: Path, capsys) -> None:
    main(
        [
            "record-path",
            str(graph_copy),
            "entrance",
            "corridor_1f",
            "lobby_1f",
            "stairs_1f",
            "stairs_2f",
            "stairs_3f",
            "corridor_3f",
            "exec_office_3f",
            "--now",
            "1000",
            "--in-place",
        ]
    )
    rc = main(
        [
            "plan",
            str(graph_copy),
            "entrance",
            "exec_office_3f",
            "--avoid-recent",
            "60",
            "--recent-multiplier",
            "10",
            "--now",
            "9999",
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    path = json.loads(out)["path"]
    # Visits are far outside the window, so the stairs route comes back.
    assert any("stairs" in nid for nid in path)


def test_plan_prefer_familiar_retraces(graph_copy: Path, capsys) -> None:
    # Bias the recorded route toward the elevator branch.
    main(
        [
            "record-path",
            str(graph_copy),
            "entrance",
            "corridor_1f",
            "lobby_1f",
            "elevator_1f",
            "elevator_3f",
            "corridor_3f",
            "exec_office_3f",
            "--now",
            "1000",
            "--in-place",
        ]
    )
    rc = main(
        [
            "plan",
            str(graph_copy),
            "entrance",
            "exec_office_3f",
            "--prefer-familiar",
            "--familiar-multiplier",
            "0.1",
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    path = json.loads(out)["path"]
    assert any("elevator" in nid for nid in path)


def test_waypoints_accepts_memory_flags(graph_copy: Path, capsys) -> None:
    rc = main(
        [
            "waypoints",
            str(graph_copy),
            "entrance",
            "exec_office_3f",
            "--prefer-unvisited",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "Semantic Waypoints" in out
