"""Robot Escape Room — the robot T-0 plays an escape game on a topology.

Run from the repository root:

    python examples/robot_escape_room.py

A robotics facility goes into lockdown and T-0 wakes up in the holding cell.
To reach the exit it has to work through four *different* puzzle mechanics,
each of which is a thin narrative skin over a real ``semantic-toponav``
planner feature:

    1. Keycard lock   — a ``locked`` door is blocked with ``block_edges``
                        until the matching item is collected.
    2. Riddle terminal— a clue is grounded to a node id with ``resolve_goal``;
                        solving it reveals where a hidden item is stashed.
    3. Power gate     — an ``unpowered`` corridor is blocked with
                        ``block_edge_types`` until the power core is held.
    4. Laser grid     — a ``restricted`` shortcut is routed around with
                        ``avoid_restricted``.
    5. Stairs vs lift — a parallel ``stairs_up`` chain sits beside the
                        elevator; ``prefer_elevator`` keeps T-0 on the
                        lift even though the stairs are cheaper.

On top of those there is a structural twist. A lit EMERGENCY EXIT sign points
up to Floor 3, so T-0 climbs toward it — but that door is welded shut
(``master_seal``, a lock whose key does not exist). The real way out is a
maintenance tunnel in the *sublevel*. A Floor-3 control-room riddle grounds
the truth and hands over the hatch code, flipping the route from
all-the-way-up to all-the-way-down.

The runner has no scripted route. Each turn it composes the *current* set of
cost rules, asks A* which objectives are reachable right now, walks to the
nearest one, acts on arrival (grab an item / solve a riddle), and re-plans.
Progress is therefore an emergent consequence of the planner reacting to a
changing world — an escape room that solves itself, one ``plan_astar`` call
at a time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.planner import (
    NoPathError,
    avoid_restricted,
    block_edge_types,
    block_edges,
    compose_costs,
    plan_astar,
    prefer_elevator,
)
from semantic_toponav.query import resolve_goal
from semantic_toponav.waypoint.semantic_waypoint import path_to_semantic_waypoints

GRAPH_PATH = Path(__file__).parent / "robot_escape_room.yaml"
START = "holding_cell"

# Set False before importing this module in record_escape_room.py so GIF
# generation stays quiet.
VERBOSE = True


def _say(msg: str) -> None:
    if VERBOSE:
        print(msg)


def _zero_heuristic(*_) -> float:
    """Disable pose heuristics so semantic edge costs decide the route."""
    return 0.0

# The sign says "this way out"; the real exit is somewhere else entirely.
DECOY_EXIT = "emergency_exit"   # lit Floor-3 sign — sealed shut, never opens
TRUE_EXIT = "maintenance_exit"  # the sublevel tunnel T-0 actually leaves by

# ---------------------------------------------------------------------------
# Puzzle / item definitions. Everything here is keyed by graph ids so the
# story stays decoupled from the planner.
# ---------------------------------------------------------------------------

# Items live at nodes. A ``hidden`` item is not a valid objective until a
# riddle has revealed its location; a visible item can be grabbed on sight.
ITEMS = {
    "keycard_blue": {"node": "main_lab", "hidden": True, "label": "\U0001F537 Blue Keycard"},
    "keycard_red": {"node": "security_office", "hidden": False, "label": "\U0001F534 Red Keycard"},
    "power_core": {"node": "storage_bay", "hidden": True, "label": "\U0001F50B Power Core"},
    "hatch_code": {"node": "control_room", "hidden": True, "label": "\U0001F5DD️ Hatch Code"},
}

# Riddle terminals. ``answer`` is the phrase T-0 decodes from the clue; it is
# grounded with resolve_goal and must resolve to ``expect_node`` to count as
# solved. Solving reveals the ``reveals`` item's location.
RIDDLES = {
    "server_room": {
        "id": "riddle_1",
        "clue": "Where the experiments run and the lab coats gather, your "
        "first card is hidden.",
        "answer": "main lab",
        "expect_node": "main_lab",
        "reveals": "keycard_blue",
    },
    "security_office": {
        "id": "riddle_2",
        "clue": "Past the locked door, the core sleeps among spare parts in "
        "the bay of stores.",
        "answer": "storage bay",
        "expect_node": "storage_bay",
        "reveals": "power_core",
    },
    # The twist. The Floor-3 emergency exit is a lie; the way out is below.
    "control_room": {
        "id": "riddle_3",
        "clue": "The lit door above is welded shut. Your way out was never "
        "up — leave through the maintenance exit, far below.",
        "answer": "maintenance exit",
        "expect_node": "maintenance_exit",
        "reveals": "hatch_code",
    },
}

# Power-restoring item -> edge types it brings back online.
POWER_ITEM = "power_core"
UNPOWERED_TYPES = ("unpowered",)


@dataclass
class World:
    location: str = START
    items: set[str] = field(default_factory=set)
    known: set[str] = field(default_factory=lambda: {
        item for item, spec in ITEMS.items() if not spec["hidden"]
    })
    solved: set[str] = field(default_factory=set)


def current_cost_fn(graph, world):
    """Compose the cost rules that apply given the current world state."""
    # Hard blocks first, then soft preferences. T-0 always prefers the
    # elevator over the cheaper stairs (accessibility mode).
    fns = [avoid_restricted, prefer_elevator]

    locked = [
        edge.id
        for edge in graph.edges()
        if edge.properties.get("lock") and edge.properties["lock"] not in world.items
    ]
    if locked:
        fns.append(block_edges(locked))

    if POWER_ITEM not in world.items:
        fns.append(block_edge_types(UNPOWERED_TYPES))

    return compose_costs(*fns)


def plan(graph, world, goal):
    """Plan from the current location to ``goal``; None if unreachable now."""
    # Zero heuristic — edge costs (stairs vs lift penalties) decide the
    # route; Euclidean pose distance would wrongly favour the lift shaft.
    try:
        return plan_astar(
            graph,
            world.location,
            goal,
            cost_fn=current_cost_fn(graph, world),
            heuristic_fn=_zero_heuristic,
        )
    except NoPathError:
        return None


def walk(graph, path):
    for wp in path_to_semantic_waypoints(graph, path):
        _say(f"      → {wp.instruction}")


def objectives(graph, world):
    """Reachable things worth visiting right now: known uncollected items and
    unsolved riddle terminals. Returns (hops, node, kind, path)."""
    out = []
    for item, spec in ITEMS.items():
        if item in world.items or item not in world.known:
            continue
        path = plan(graph, world, spec["node"])
        if path is not None:
            out.append((len(path), spec["node"], f"item:{item}", path))
    for node, riddle in RIDDLES.items():
        if riddle["id"] in world.solved:
            continue
        path = plan(graph, world, node)
        if path is not None:
            out.append((len(path), node, f"riddle:{riddle['id']}", path))
    out.sort(key=lambda o: o[0])
    return out


def solve_riddle(graph, world, node):
    """Ground the riddle answer to a node; reveal the hidden item if correct."""
    riddle = RIDDLES[node]
    _say(f'          \U0001F9E9 Riddle terminal: "{riddle["clue"]}"')
    candidates = resolve_goal(graph, riddle["answer"], top_k=3)
    best = candidates[0] if candidates else None
    guess = f'"{riddle["answer"]}"'
    if best and best.node.id == riddle["expect_node"]:
        revealed = ITEMS[riddle["reveals"]]
        world.solved.add(riddle["id"])
        world.known.add(riddle["reveals"])
        _say(f"          T-0 decodes {guess} → grounds to "
             f"{best.node.label} (score {best.score:.1f}).")
        _say(f"          \U0001F4A1 Revealed: {revealed['label']} is hidden "
             f"in the {graph.get_node(revealed['node']).label}.")
    else:
        got = best.node.label if best else "nothing"
        _say(f"          T-0 grounds {guess} to {got} — wrong terminal, no reveal.")


def grab_items(graph, world, node):
    """Collect any known, uncollected items sitting at ``node``."""
    for item, spec in ITEMS.items():
        if spec["node"] == node and item in world.known and item not in world.items:
            world.items.add(item)
            _say(f"          ✅ Picked up {spec['label']}.")
            opened = [
                f"{graph.get_node(e.source).label} ↔ {graph.get_node(e.target).label}"
                for e in graph.edges()
                if e.properties.get("lock") == item
            ]
            if opened:
                _say(f"             \U0001F513 Unlocked: {', '.join(opened)}")
            if item == POWER_ITEM:
                _say("             ⚡ Power restored — the Dark Corridor lights up.")


def arrive(graph, world, node):
    """Resolve every action available at a node on arrival.

    Grab first, then decode any riddle — and grab once more, so an item the
    riddle reveals *at this very node* (the control-room hatch code) is picked
    up on the same visit rather than forcing a redundant return trip.
    """
    grab_items(graph, world, node)
    if node in RIDDLES and RIDDLES[node]["id"] not in world.solved:
        solve_riddle(graph, world, node)
        grab_items(graph, world, node)


def laser_briefing(graph):
    """Show that ``avoid_restricted`` keeps T-0 off the laser grid.

    The same leg (West Corridor → Central Atrium) is planned twice, once with
    no safety rule and once with ``avoid_restricted``. A reckless planner cuts
    straight through the laser shortcut; the safe one detours around it.
    """
    reckless = plan_astar(graph, "west_corridor", "atrium")
    safe = plan_astar(graph, "west_corridor", "atrium", cost_fn=avoid_restricted)
    _say("  \U0001F4E1 Hazard scan — West Corridor → Central Atrium:")
    _say(f"     reckless        : {' → '.join(reckless)}  (\U0001F480 cuts the laser grid)")
    _say(f"     avoid_restricted: {' → '.join(safe)}  (safe detour)")
    _say("")


def mobility_briefing(graph):
    """Show that ``prefer_elevator`` overrides cheaper stairs.

    Stairs edges cost 1.0 per hop vs 1.5 for the lift, so a bare A* call
    climbs the stairwell. Adding ``prefer_elevator`` discounts the lift enough
    that T-0 rides it anyway.
    """
    start, goal = "elevator_lobby", "top_landing"
    via_stairs = plan_astar(graph, start, goal, heuristic_fn=_zero_heuristic)
    via_lift = plan_astar(
        graph, start, goal, cost_fn=prefer_elevator, heuristic_fn=_zero_heuristic,
    )
    _say("  \U0001F6D7 Mobility scan — Elevator Lobby → 3F Landing:")
    _say(f"     default (cheaper stairs): {' → '.join(via_stairs)}")
    _say(f"     prefer_elevator         : {' → '.join(via_lift)}  (T-0 rides the lift)")
    _say("")


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
    laser_briefing(graph)
    mobility_briefing(graph)

    twist_seen = False
    for turn in range(1, 50):
        # Make a break for it the moment the *real* exit is reachable.
        exit_path = plan(graph, world, TRUE_EXIT)
        if exit_path is not None:
            print(f"[Turn {turn}] \U0001F6AA The way out is open — T-0 runs for it!")
            walk(graph, exit_path)
            floor = graph.get_node(TRUE_EXIT).properties.get("floor")
            print()
            print("=" * 66)
            print("  \U0001F389  FREEDOM. T-0 has escaped — through the sublevel, "
                  f"not the Floor-3 sign (exit on floor {floor}).")
            print(f"  Items: {len(world.items)}/{len(ITEMS)}  |  "
                  f"Riddles: {len(world.solved)}/{len(RIDDLES)}  |  Turns: {turn}")
            print("=" * 66)
            return

        opts = objectives(graph, world)
        if not opts:
            print(f"[Turn {turn}] \U0001F480 Nothing reachable and no way out. T-0 is stuck.")
            return

        _, node, kind, path = opts[0]
        label = graph.get_node(node).label
        verb = "investigate" if kind.startswith("riddle") else "reach"
        print(f"[Turn {turn}] \U0001F9ED {len(opts)} lead(s); nearest is to "
              f"{verb} the {label}:")
        walk(graph, path)
        world.location = node
        arrive(graph, world, node)

        # Call out the misdirection the moment the control room reveals it.
        if not twist_seen and "riddle_3" in world.solved:
            twist_seen = True
            print(f"          \U0001F500 Plot twist: the {graph.get_node(DECOY_EXIT).label} "
                  f"is a dead end — T-0 turns around and heads for the sublevel.")
        print()

    print("Gave up after too many turns — the room may be unsolvable as configured.")


if __name__ == "__main__":
    main()
