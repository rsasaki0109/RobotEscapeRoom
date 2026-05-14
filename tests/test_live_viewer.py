"""Tests for the live-reloading HTTP graph viewer."""

from __future__ import annotations

import json
import shutil
import threading
import time
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("pyvis")

from semantic_toponav.visualization.live import make_server

EXAMPLE_YAML = Path(__file__).resolve().parents[1] / "examples" / "indoor_office.yaml"


def _start_server(graph_path: Path) -> tuple[object, str, threading.Thread]:
    """Start an HTTPServer on an ephemeral port and return (server, base_url, thread)."""
    server = make_server(graph_path, host="127.0.0.1", port=0, interval_ms=200)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{port}", thread


def _stop_server(server, thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2.0)


def _get(url: str) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=2.0) as resp:
        return resp.status, resp.read()


def test_index_returns_html_with_live_reload_snippet(tmp_path) -> None:
    graph = tmp_path / "g.yaml"
    shutil.copy(EXAMPLE_YAML, graph)
    server, base, thread = _start_server(graph)
    try:
        status, body = _get(base + "/")
        assert status == 200
        text = body.decode("utf-8")
        assert "/mtime.json" in text
        # pyvis HTML always contains a <body> tag; live snippet sits just
        # before </body>.
        assert "<body>" in text
        assert "</body>" in text
    finally:
        _stop_server(server, thread)


def test_mtime_endpoint_reports_current_mtime(tmp_path) -> None:
    graph = tmp_path / "g.yaml"
    shutil.copy(EXAMPLE_YAML, graph)
    server, base, thread = _start_server(graph)
    try:
        _, body = _get(base + "/mtime.json")
        payload = json.loads(body)
        assert "mtime" in payload
        assert payload["mtime"] == pytest.approx(graph.stat().st_mtime, abs=0.5)
    finally:
        _stop_server(server, thread)


def test_mtime_changes_when_file_is_rewritten(tmp_path) -> None:
    graph = tmp_path / "g.yaml"
    shutil.copy(EXAMPLE_YAML, graph)
    server, base, thread = _start_server(graph)
    try:
        _, body = _get(base + "/mtime.json")
        first = json.loads(body)["mtime"]
        time.sleep(0.05)
        # Touch the file with a new mtime.
        graph.write_text(graph.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        _, body = _get(base + "/mtime.json")
        second = json.loads(body)["mtime"]
        assert second > first
    finally:
        _stop_server(server, thread)


def test_index_picks_up_file_changes(tmp_path) -> None:
    graph = tmp_path / "g.yaml"
    shutil.copy(EXAMPLE_YAML, graph)
    server, base, thread = _start_server(graph)
    try:
        _, first = _get(base + "/")
        # Replace with a tiny graph (one node).
        graph.write_text(
            "frame_id: map\nnodes:\n  - id: solo\n    label: Solo\n    type: room\nedges: []\n",
            encoding="utf-8",
        )
        _, second = _get(base + "/")
        # The new HTML should contain the new node id, the old should not.
        assert b"solo" in second
        # Original example doesn't have "solo" — sanity check on the assumption.
        assert b"solo" not in first
    finally:
        _stop_server(server, thread)


def test_unknown_path_404s(tmp_path) -> None:
    graph = tmp_path / "g.yaml"
    shutil.copy(EXAMPLE_YAML, graph)
    server, base, thread = _start_server(graph)
    try:
        try:
            urllib.request.urlopen(base + "/nope", timeout=2.0)
            raise AssertionError("expected HTTP 404")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
    finally:
        _stop_server(server, thread)


def test_bad_graph_file_serves_error_page_instead_of_crashing(tmp_path) -> None:
    graph = tmp_path / "g.yaml"
    graph.write_text("not: a graph: at all\n", encoding="utf-8")
    server, base, thread = _start_server(graph)
    try:
        status, body = _get(base + "/")
        assert status == 200  # the server keeps running
        text = body.decode("utf-8")
        assert "error" in text.lower()
    finally:
        _stop_server(server, thread)
