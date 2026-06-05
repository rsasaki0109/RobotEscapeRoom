"""CLI smoke tests for `localize` / `visual-route`.

Builds a tiny graph whose nodes carry HashingBackend embeddings (saved
to a temp YAML) plus byte "frames" on disk, so the commands run with no
torch. Byte-identical frame and gallery -> cosine ~1.0 keeps assertions
deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from semantic_toponav.cli.main import main
from semantic_toponav.encoders.backends import HashingBackend
from semantic_toponav.graph.serialization import save_graph
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode

CHAIN = ["bay", "hall", "lab"]
DIM = 32


@pytest.fixture
def visual_graph(tmp_path: Path) -> dict:
    backend = HashingBackend(dim=DIM)
    frames = {k: f"frame:{k}".encode() for k in CHAIN}
    paths = {}
    g = TopologyGraph()
    for i, k in enumerate(CHAIN):
        p = tmp_path / f"{k}.bin"
        p.write_bytes(frames[k])
        paths[k] = str(p)
        g.add_node(
            TopologyNode(
                id=k, label=k.title(), type="room", pose=Pose2D(float(i), 0.0),
                properties={"embedding": backend.embed_image(frames[k])},
            )
        )
    for a, b in zip(CHAIN, CHAIN[1:], strict=False):
        g.add_edge(TopologyEdge(id=f"{a}_{b}", source=a, target=b, type="traversable"))
    graph_path = tmp_path / "g.yaml"
    save_graph(g, str(graph_path))
    return {"graph": str(graph_path), "frames": paths}


def test_localize_text(visual_graph, capsys) -> None:
    rc = main(
        ["localize", visual_graph["graph"], visual_graph["frames"]["lab"],
         "--backend", "hashing", "--dim", str(DIM)]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "Localized -> lab" in out
    assert "Shortlist:" in out


def test_localize_json(visual_graph, capsys) -> None:
    rc = main(
        ["localize", visual_graph["graph"], visual_graph["frames"]["hall"],
         "--backend", "hashing", "--dim", str(DIM), "--format", "json"]
    )
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["best"]["id"] == "hall"
    assert len(payload["ranked"]) == 3


def test_localize_type_filter(visual_graph, capsys) -> None:
    rc = main(
        ["localize", visual_graph["graph"], visual_graph["frames"]["lab"],
         "--backend", "hashing", "--dim", str(DIM), "--type", "nonexistent"]
    )
    err = capsys.readouterr().err
    assert rc == 2
    assert "no node" in err.lower()


def test_localize_neighbor_weight_accepted(visual_graph, capsys) -> None:
    rc = main(
        ["localize", visual_graph["graph"], visual_graph["frames"]["lab"],
         "--backend", "hashing", "--dim", str(DIM), "--neighbor-weight", "0.3"]
    )
    capsys.readouterr()
    assert rc == 0


def test_visual_route_text(visual_graph, capsys) -> None:
    rc = main(
        ["visual-route", visual_graph["graph"], visual_graph["frames"]["bay"], "lab",
         "--backend", "hashing", "--dim", str(DIM)]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "Grounded start -> bay" in out
    assert "Route: bay -> hall -> lab" in out
    assert "Waypoints:" in out


def test_visual_route_json(visual_graph, capsys) -> None:
    rc = main(
        ["visual-route", visual_graph["graph"], visual_graph["frames"]["bay"], "lab",
         "--backend", "hashing", "--dim", str(DIM), "--format", "json"]
    )
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["start"]["id"] == "bay"
    assert payload["route"] == ["bay", "hall", "lab"]
    assert [w["node_id"] for w in payload["waypoints"]] == payload["route"]


def test_visual_route_unknown_goal_errors(visual_graph, capsys) -> None:
    rc = main(
        ["visual-route", visual_graph["graph"], visual_graph["frames"]["bay"], "nowhere",
         "--backend", "hashing", "--dim", str(DIM)]
    )
    err = capsys.readouterr().err
    assert rc == 2
    assert "nowhere" in err
