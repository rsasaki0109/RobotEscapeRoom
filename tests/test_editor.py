"""Tests for the editor-style CLI subcommands."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from semantic_toponav.cli.editor import _coerce_value, _parse_props
from semantic_toponav.cli.main import main
from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import TopologyEdge, TopologyNode

EXAMPLE_YAML = Path(__file__).resolve().parents[1] / "examples" / "indoor_office.yaml"


def _fresh_copy(tmp_path: Path) -> Path:
    target = tmp_path / "graph.yaml"
    shutil.copy(EXAMPLE_YAML, target)
    return target


# --------------------------- TopologyGraph mutations ---------------------------


def test_remove_edge_unhooks_adjacency() -> None:
    g = TopologyGraph()
    g.add_node(TopologyNode(id="a", label="A", type="room"))
    g.add_node(TopologyNode(id="b", label="B", type="room"))
    g.add_edge(TopologyEdge(id="ab", source="a", target="b", type="traversable"))
    assert [e.id for e in g.neighbors("a")] == ["ab"]
    g.remove_edge("ab")
    assert g.neighbors("a") == []
    assert not g.has_edge("ab")


def test_remove_node_removes_incident_edges() -> None:
    g = TopologyGraph()
    for nid in "abc":
        g.add_node(TopologyNode(id=nid, label=nid.upper(), type="room"))
    g.add_edge(TopologyEdge(id="ab", source="a", target="b", type="traversable"))
    g.add_edge(TopologyEdge(id="bc", source="b", target="c", type="traversable"))
    removed = g.remove_node("b")
    assert set(removed) == {"ab", "bc"}
    assert not g.has_node("b")
    assert g.edge_ids() == []
    assert g.neighbors("a") == []
    assert g.neighbors("c") == []


# --------------------------- _parse_props ---------------------------


def test_coerce_value_types() -> None:
    assert _coerce_value("true") is True
    assert _coerce_value("False") is False
    assert _coerce_value("42") == 42
    assert _coerce_value("1.5") == 1.5
    assert _coerce_value("hello") == "hello"


def test_parse_props_basic() -> None:
    assert _parse_props(["floor=2", "name=lab", "open=true"]) == {
        "floor": 2,
        "name": "lab",
        "open": True,
    }


def test_parse_props_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        _parse_props(["no_equals"])


# --------------------------- CLI: inspect ---------------------------


def test_inspect_default_lists_both(capsys) -> None:
    rc = main(["inspect", str(EXAMPLE_YAML)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Nodes" in out
    assert "Edges" in out


def test_inspect_type_filter(capsys) -> None:
    rc = main(["inspect", str(EXAMPLE_YAML), "--type", "elevator"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "elevator_1f" in out
    assert "entrance" not in out.split("Nodes")[1]  # filtered out of node list


# --------------------------- CLI: add-node / add-edge ---------------------------


def test_add_node_in_place(tmp_path) -> None:
    target = _fresh_copy(tmp_path)
    rc = main(
        [
            "add-node",
            str(target),
            "supply_closet",
            "--type",
            "room",
            "--label",
            "Supply Closet",
            "--x",
            "8.0",
            "--y",
            "-2.0",
            "--prop",
            "floor=1",
            "--in-place",
        ]
    )
    assert rc == 0
    g = load_graph(target)
    assert g.has_node("supply_closet")
    node = g.get_node("supply_closet")
    assert node.label == "Supply Closet"
    assert node.pose is not None
    assert node.pose.x == 8.0
    assert node.properties == {"floor": 1}


def test_add_edge_in_place(tmp_path) -> None:
    target = _fresh_copy(tmp_path)
    # First add a node we can connect to.
    rc = main(
        [
            "add-node",
            str(target),
            "supply_closet",
            "--type",
            "room",
            "--x",
            "8.0",
            "--y",
            "-2.0",
            "--in-place",
        ]
    )
    assert rc == 0
    rc = main(
        [
            "add-edge",
            str(target),
            "lobby_intersection",
            "supply_closet",
            "--type",
            "traversable",
            "--in-place",
        ]
    )
    assert rc == 0
    g = load_graph(target)
    assert g.has_edge("lobby_intersection__supply_closet")


def test_add_node_to_stdout_preserves_yaml(tmp_path, capsys) -> None:
    target = _fresh_copy(tmp_path)
    rc = main(
        [
            "add-node",
            str(target),
            "x",
            "--type",
            "room",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "id: x" in out  # YAML rendered
    # source file unchanged
    g = load_graph(target)
    assert not g.has_node("x")


def test_add_node_duplicate_id_errors(tmp_path, capsys) -> None:
    target = _fresh_copy(tmp_path)
    rc = main(
        [
            "add-node",
            str(target),
            "entrance",  # already exists
            "--type",
            "room",
            "--in-place",
        ]
    )
    err = capsys.readouterr().err
    assert rc != 0
    assert "duplicate" in err


def test_add_node_partial_pose_errors(tmp_path, capsys) -> None:
    target = _fresh_copy(tmp_path)
    rc = main(
        [
            "add-node",
            str(target),
            "x",
            "--type",
            "room",
            "--x",
            "1.0",
            "--in-place",
        ]
    )
    err = capsys.readouterr().err
    assert rc != 0
    assert "--x and --y must be provided together" in err


# --------------------------- CLI: rm-node / rm-edge ---------------------------


def test_rm_node_cascades_edges(tmp_path) -> None:
    target = _fresh_copy(tmp_path)
    rc = main(["rm-node", str(target), "stairs_1f", "--in-place"])
    assert rc == 0
    g = load_graph(target)
    assert not g.has_node("stairs_1f")
    # `lobby_to_stairs_1f` and `stairs_link` both touched stairs_1f.
    assert not g.has_edge("lobby_to_stairs_1f")
    assert not g.has_edge("stairs_link")


def test_rm_edge_in_place(tmp_path) -> None:
    target = _fresh_copy(tmp_path)
    rc = main(["rm-edge", str(target), "corridor_to_meeting_shortcut", "--in-place"])
    assert rc == 0
    g = load_graph(target)
    assert not g.has_edge("corridor_to_meeting_shortcut")


def test_rm_edge_unknown_errors(tmp_path, capsys) -> None:
    target = _fresh_copy(tmp_path)
    rc = main(["rm-edge", str(target), "nope", "--in-place"])
    err = capsys.readouterr().err
    assert rc != 0
    assert "unknown" in err


# --------------------------- CLI: backup / undo ---------------------------


def test_in_place_edit_creates_backup(tmp_path) -> None:
    target = _fresh_copy(tmp_path)
    original = target.read_text(encoding="utf-8")
    rc = main(["rm-edge", str(target), "corridor_to_meeting_shortcut", "--in-place"])
    assert rc == 0
    backup = target.with_name(target.name + ".bak")
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == original
    # Current file should be modified.
    assert target.read_text(encoding="utf-8") != original


def test_no_backup_flag_suppresses_backup(tmp_path) -> None:
    target = _fresh_copy(tmp_path)
    rc = main(
        [
            "rm-edge",
            str(target),
            "corridor_to_meeting_shortcut",
            "--in-place",
            "--no-backup",
        ]
    )
    assert rc == 0
    backup = target.with_name(target.name + ".bak")
    assert not backup.exists()


def test_undo_restores_previous_state(tmp_path) -> None:
    target = _fresh_copy(tmp_path)
    original = target.read_text(encoding="utf-8")
    main(["rm-edge", str(target), "corridor_to_meeting_shortcut", "--in-place"])
    assert target.read_text(encoding="utf-8") != original
    rc = main(["undo", str(target)])
    assert rc == 0
    assert target.read_text(encoding="utf-8") == original


def test_undo_is_reversible(tmp_path) -> None:
    target = _fresh_copy(tmp_path)
    original = target.read_text(encoding="utf-8")
    main(["rm-edge", str(target), "corridor_to_meeting_shortcut", "--in-place"])
    modified = target.read_text(encoding="utf-8")
    main(["undo", str(target)])
    assert target.read_text(encoding="utf-8") == original
    # Undo again redoes the edit.
    main(["undo", str(target)])
    assert target.read_text(encoding="utf-8") == modified


def test_undo_without_backup_errors(tmp_path, capsys) -> None:
    target = _fresh_copy(tmp_path)
    rc = main(["undo", str(target)])
    err = capsys.readouterr().err
    assert rc != 0
    assert "no backup" in err


# --------------------------- CLI: diff ---------------------------


def test_diff_against_backup_after_rm_edge(tmp_path, capsys) -> None:
    target = _fresh_copy(tmp_path)
    main(["rm-edge", str(target), "corridor_to_meeting_shortcut", "--in-place"])
    rc = main(["diff", str(target)])
    out = capsys.readouterr().out
    # rm-edge means the edge is *missing* in the new file => "- removed_edge"
    assert rc == 1  # diff means non-zero
    assert "- corridor_to_meeting_shortcut" in out
    assert "edges:" in out


def test_diff_identical_returns_zero(tmp_path, capsys) -> None:
    target = _fresh_copy(tmp_path)
    twin = tmp_path / "twin.yaml"
    twin.write_bytes(target.read_bytes())
    rc = main(["diff", str(target), str(twin)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "identical" in out


def test_diff_two_files_shows_added_node(tmp_path, capsys) -> None:
    base = _fresh_copy(tmp_path)
    new = tmp_path / "new.yaml"
    new.write_bytes(base.read_bytes())
    main(
        [
            "add-node",
            str(new),
            "supply_closet",
            "--type",
            "room",
            "--label",
            "Supply Closet",
            "--in-place",
            "--no-backup",
        ]
    )
    rc = main(["diff", str(base), str(new)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "+ supply_closet" in out
    assert "nodes:" in out


def test_diff_missing_other_errors(tmp_path, capsys) -> None:
    target = _fresh_copy(tmp_path)
    rc = main(["diff", str(target)])  # no .bak yet
    err = capsys.readouterr().err
    assert rc != 0
    assert "not found" in err


def test_out_and_in_place_mutually_exclusive(tmp_path, capsys) -> None:
    target = _fresh_copy(tmp_path)
    rc = main(
        [
            "rm-edge",
            str(target),
            "corridor_to_meeting_shortcut",
            "--in-place",
            "--out",
            str(tmp_path / "elsewhere.yaml"),
        ]
    )
    err = capsys.readouterr().err
    assert rc != 0
    assert "at most one" in err
