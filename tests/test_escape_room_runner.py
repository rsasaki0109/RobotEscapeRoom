"""Tests for the escape-room puzzle runner library."""

from __future__ import annotations

from pathlib import Path

from semantic_toponav.escape_room.runner import (
    TRUE_EXIT,
    World,
    complete_navigation,
    next_turn,
)
from semantic_toponav.graph.serialization import load_graph

GRAPH = Path(__file__).resolve().parents[1] / "examples" / "robot_escape_room.yaml"


def test_escape_room_runner_reaches_exit() -> None:
    graph = load_graph(str(GRAPH))
    world = World()
    for _ in range(40):
        turn = next_turn(graph, world)
        if turn.status == "exit":
            complete_navigation(graph, world, TRUE_EXIT)
            assert world.escaped
            return
        if turn.status == "stuck":
            raise AssertionError("escape room became stuck")
        assert turn.objective is not None
        complete_navigation(graph, world, turn.objective.node)
    raise AssertionError("did not escape within turn limit")
