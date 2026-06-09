"""Robot Escape Room — planner-driven puzzle runner (library).

The CLI in ``examples/robot_escape_room.py`` and the ROS2
``escape_room_runner`` node both drive this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from semantic_toponav.graph.topology_graph import TopologyGraph
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
from semantic_toponav.waypoint.semantic_waypoint import SemanticWaypoint, path_to_semantic_waypoints

START = "holding_cell"
DECOY_EXIT = "emergency_exit"
TRUE_EXIT = "maintenance_exit"

ITEMS = {
    "keycard_blue": {"node": "main_lab", "hidden": True, "label": "\U0001F537 Blue Keycard"},
    "keycard_red": {"node": "security_office", "hidden": False, "label": "\U0001F534 Red Keycard"},
    "power_core": {"node": "storage_bay", "hidden": True, "label": "\U0001F50B Power Core"},
    "hatch_code": {"node": "control_room", "hidden": True, "label": "\U0001F5DD️ Hatch Code"},
}

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
    "control_room": {
        "id": "riddle_3",
        "clue": "The lit door above is welded shut. Your way out was never "
        "up — leave through the maintenance exit, far below.",
        "answer": "maintenance exit",
        "expect_node": "maintenance_exit",
        "reveals": "hatch_code",
    },
}

POWER_ITEM = "power_core"
UNPOWERED_TYPES = ("unpowered",)

ObjectiveKind = Literal["exit", "item", "riddle"]


@dataclass
class World:
    location: str = START
    items: set[str] = field(default_factory=set)
    known: set[str] = field(default_factory=lambda: {
        item for item, spec in ITEMS.items() if not spec["hidden"]
    })
    solved: set[str] = field(default_factory=set)
    turn: int = 0
    twist_seen: bool = False
    escaped: bool = False
    stuck: bool = False


@dataclass(frozen=True)
class Objective:
    hops: int
    node: str
    kind: ObjectiveKind
    detail: str
    path: list[str]


@dataclass(frozen=True)
class ArrivalEvent:
    node: str
    messages: tuple[str, ...]


@dataclass(frozen=True)
class TurnPlan:
    turn: int
    objective: Objective | None
    exit_path: list[str] | None
    waypoints: list[SemanticWaypoint]
    status: str


def _zero_heuristic(*_) -> float:
    return 0.0


def current_cost_fn(graph: TopologyGraph, world: World):
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


def plan(graph: TopologyGraph, world: World, goal: str) -> list[str] | None:
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


def objectives(graph: TopologyGraph, world: World) -> list[Objective]:
    out: list[Objective] = []
    for item, spec in ITEMS.items():
        if item in world.items or item not in world.known:
            continue
        path = plan(graph, world, spec["node"])
        if path is not None:
            out.append(
                Objective(len(path), spec["node"], "item", item, path)
            )
    for node, riddle in RIDDLES.items():
        if riddle["id"] in world.solved:
            continue
        path = plan(graph, world, node)
        if path is not None:
            out.append(
                Objective(len(path), node, "riddle", riddle["id"], path)
            )
    out.sort(key=lambda o: o.hops)
    return out


def solve_riddle(graph: TopologyGraph, world: World, node: str) -> list[str]:
    riddle = RIDDLES[node]
    lines = [f'Riddle terminal: "{riddle["clue"]}"']
    candidates = resolve_goal(graph, riddle["answer"], top_k=3)
    best = candidates[0] if candidates else None
    guess = f'"{riddle["answer"]}"'
    if best and best.node.id == riddle["expect_node"]:
        revealed = ITEMS[riddle["reveals"]]
        world.solved.add(riddle["id"])
        world.known.add(riddle["reveals"])
        lines.append(
            f"T-0 decodes {guess} → {best.node.label} (score {best.score:.1f})."
        )
        lines.append(
            f"Revealed: {revealed['label']} is hidden in "
            f"{graph.get_node(revealed['node']).label}."
        )
    else:
        got = best.node.label if best else "nothing"
        lines.append(f"T-0 grounds {guess} to {got} — wrong terminal, no reveal.")
    return lines


def grab_items(graph: TopologyGraph, world: World, node: str) -> list[str]:
    lines: list[str] = []
    for item, spec in ITEMS.items():
        if spec["node"] == node and item in world.known and item not in world.items:
            world.items.add(item)
            lines.append(f"Picked up {spec['label']}.")
            opened = [
                f"{graph.get_node(e.source).label} ↔ {graph.get_node(e.target).label}"
                for e in graph.edges()
                if e.properties.get("lock") == item
            ]
            if opened:
                lines.append(f"Unlocked: {', '.join(opened)}")
            if item == POWER_ITEM:
                lines.append("Power restored — the Dark Corridor lights up.")
    return lines


def arrive(graph: TopologyGraph, world: World, node: str) -> ArrivalEvent:
    messages: list[str] = []
    messages.extend(grab_items(graph, world, node))
    if node in RIDDLES and RIDDLES[node]["id"] not in world.solved:
        messages.extend(solve_riddle(graph, world, node))
        messages.extend(grab_items(graph, world, node))
    if not world.twist_seen and "riddle_3" in world.solved:
        world.twist_seen = True
        messages.append(
            f"Plot twist: the {graph.get_node(DECOY_EXIT).label} is a dead end — "
            "T-0 turns around and heads for the sublevel."
        )
    return ArrivalEvent(node=node, messages=tuple(messages))


def next_turn(graph: TopologyGraph, world: World) -> TurnPlan:
    """Advance one planning step without mutating ``world.location`` yet."""
    world.turn += 1
    exit_path = plan(graph, world, TRUE_EXIT)
    if exit_path is not None:
        wps = path_to_semantic_waypoints(graph, exit_path)
        world.escaped = True
        return TurnPlan(
            turn=world.turn,
            objective=None,
            exit_path=exit_path,
            waypoints=wps,
            status="exit",
        )

    opts = objectives(graph, world)
    if not opts:
        world.stuck = True
        return TurnPlan(
            turn=world.turn,
            objective=None,
            exit_path=None,
            waypoints=[],
            status="stuck",
        )

    obj = opts[0]
    wps = path_to_semantic_waypoints(graph, obj.path)
    label = graph.get_node(obj.node).label
    verb = "investigate" if obj.kind == "riddle" else "reach"
    return TurnPlan(
        turn=world.turn,
        objective=obj,
        exit_path=None,
        waypoints=wps,
        status=f"{verb} {label}",
    )


def complete_navigation(graph: TopologyGraph, world: World, node: str) -> ArrivalEvent:
    """Mark arrival at ``node`` and run on-arrival puzzle actions."""
    world.location = node
    return arrive(graph, world, node)


def laser_briefing(graph: TopologyGraph) -> tuple[str, ...]:
    reckless = plan_astar(graph, "west_corridor", "atrium")
    safe = plan_astar(graph, "west_corridor", "atrium", cost_fn=avoid_restricted)
    return (
        "Hazard scan — West Corridor → Central Atrium:",
        f"  reckless        : {' → '.join(reckless)}  (cuts the laser grid)",
        f"  avoid_restricted: {' → '.join(safe)}  (safe detour)",
    )


def mobility_briefing(graph: TopologyGraph) -> tuple[str, ...]:
    start, goal = "elevator_lobby", "top_landing"
    via_stairs = plan_astar(graph, start, goal, heuristic_fn=_zero_heuristic)
    via_lift = plan_astar(
        graph, start, goal, cost_fn=prefer_elevator, heuristic_fn=_zero_heuristic,
    )
    return (
        "Mobility scan — Elevator Lobby → 3F Landing:",
        f"  default (cheaper stairs): {' → '.join(via_stairs)}",
        f"  prefer_elevator         : {' → '.join(via_lift)}  (T-0 rides the lift)",
    )
