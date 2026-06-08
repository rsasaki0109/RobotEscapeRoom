"""Robot Escape Room — the robot T-0 plays an escape game on a topology.

Run from the repository root:

    python examples/robot_escape_room.py
"""

from __future__ import annotations

from pathlib import Path

from semantic_toponav.escape_room.runner import (
    DECOY_EXIT,
    ITEMS,
    RIDDLES,
    START,
    TRUE_EXIT,
    World,
    complete_navigation,
    laser_briefing,
    mobility_briefing,
    next_turn,
    objectives,
)
from semantic_toponav.graph.serialization import load_graph

GRAPH_PATH = Path(__file__).parent / "robot_escape_room.yaml"
VERBOSE = True


def _say(msg: str) -> None:
    if VERBOSE:
        print(msg)


def walk(waypoints) -> None:
    for wp in waypoints:
        _say(f"      → {wp.instruction}")


def main() -> None:
    graph = load_graph(GRAPH_PATH)
    world = World()

    print("=" * 66)
    print("  \U0001F916  ROBOT ESCAPE ROOM — T-0 vs. the lockdown")
    print("=" * 66)
    print(f"  Map: {len(graph.node_ids())} rooms, {len(graph.edge_ids())} doors.")
    print(f"  T-0 boots up in the {graph.get_node(START).label}. Find the exit.")
    print(f"  \U0001F6AA A lit EMERGENCY EXIT sign points up to the "
          f"{graph.get_node(DECOY_EXIT).label} — surely that is the way out?")
    print()
    for line in laser_briefing(graph):
        _say(f"  \U0001F4E1 {line}")
    _say("")
    for line in mobility_briefing(graph):
        _say(f"  \U0001F6D7 {line}")
    _say("")

    for _ in range(49):
        opts_count = len(objectives(graph, world))
        turn = next_turn(graph, world)
        if turn.status == "exit":
            print(f"[Turn {turn.turn}] \U0001F6AA The way out is open — T-0 runs for it!")
            walk(turn.waypoints)
            complete_navigation(graph, world, TRUE_EXIT)
            floor = graph.get_node(TRUE_EXIT).properties.get("floor")
            print()
            print("=" * 66)
            print("  \U0001F389  FREEDOM. T-0 has escaped — through the sublevel, "
                  f"not the Floor-3 sign (exit on floor {floor}).")
            print(f"  Items: {len(world.items)}/{len(ITEMS)}  |  "
                  f"Riddles: {len(world.solved)}/{len(RIDDLES)}  |  Turns: {turn.turn}")
            print("=" * 66)
            return

        if turn.status == "stuck":
            print(f"[Turn {turn.turn}] \U0001F480 Nothing reachable and no way out. T-0 is stuck.")
            return

        assert turn.objective is not None
        label = graph.get_node(turn.objective.node).label
        verb = "investigate" if turn.objective.kind == "riddle" else "reach"
        print(f"[Turn {turn.turn}] \U0001F9ED {opts_count} lead(s); nearest is to "
              f"{verb} the {label}:")
        walk(turn.waypoints)
        event = complete_navigation(graph, world, turn.objective.node)
        for line in event.messages:
            _say(f"          {line}")
        print()

    print("Gave up after too many turns — the room may be unsolvable as configured.")


if __name__ == "__main__":
    main()
