"""Per-room quest labels for the escape-room hero / Foxglove replay."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoomQuest:
    title: str
    objective: str
    mechanic: str


# One visible quest per graph node T-0 can stand in during the play-through.
ROOM_QUESTS: dict[str, RoomQuest] = {
    "holding_cell": RoomQuest(
        "Quest · Boot",
        "Confirm systems online in the holding cell",
        "start",
    ),
    "west_corridor": RoomQuest(
        "Quest · Patrol",
        "Scout the west corridor toward the server wing",
        "plan",
    ),
    "server_room": RoomQuest(
        "Quest · Terminal I",
        "Ground the clue — where is the blue keycard?",
        "resolve_goal",
    ),
    "main_lab": RoomQuest(
        "Quest · Blue lock",
        "Collect the blue keycard for Security",
        "block_edges",
    ),
    "security_office": RoomQuest(
        "Quest · Terminal II",
        "Decode the terminal → find the power core",
        "resolve_goal",
    ),
    "atrium": RoomQuest(
        "Quest · Route",
        "Pick a safe path through the central atrium",
        "avoid_restricted",
    ),
    "storage_bay": RoomQuest(
        "Quest · Power",
        "Recover the power core for the dark corridor",
        "block_edge_types",
    ),
    "dark_corridor": RoomQuest(
        "Quest · Blackout",
        "Cross the corridor once power is restored",
        "block_edge_types",
    ),
    "elevator_lobby": RoomQuest(
        "Quest · Mobility",
        "Ride the lift (prefer_elevator) toward 3F",
        "prefer_elevator",
    ),
    "stairwell_1f": RoomQuest(
        "Quest · Stairs",
        "Cheaper stairs chain — T-0 still picks the lift",
        "prefer_elevator",
    ),
    "stairwell_2f": RoomQuest(
        "Quest · Mid climb",
        "2F stairwell hop toward the decoy exit",
        "plan",
    ),
    "mid_landing": RoomQuest(
        "Quest · 2F landing",
        "Transfer to the elevator shaft or stairwell",
        "plan",
    ),
    "stairwell_3f": RoomQuest(
        "Quest · Top climb",
        "3F stairwell — the lit exit sign lies ahead",
        "plan",
    ),
    "top_landing": RoomQuest(
        "Quest · Decoy lure",
        "Follow the EMERGENCY EXIT sign upward",
        "plan",
    ),
    "control_room": RoomQuest(
        "Quest · Terminal III",
        "Ground the truth — maintenance exit is below",
        "resolve_goal",
    ),
    "emergency_exit": RoomQuest(
        "Quest · Decoy",
        "EMERGENCY EXIT welded shut — replan downward",
        "block_edges",
    ),
    "basement_tunnel": RoomQuest(
        "Quest · Sublevel",
        "Crawl the maintenance tunnel with the hatch code",
        "block_edges",
    ),
    "maintenance_exit": RoomQuest(
        "Quest · Escape",
        "Reach the real exit on B1",
        "exit",
    ),
}

_QUEST_DONE: dict[str, tuple[str, ...]] = {
    "holding_cell": ("T-0 online",),
    "server_room": ("riddle: riddle_1",),
    "main_lab": ("item: keycard_blue",),
    "security_office": ("riddle: riddle_2", "item: keycard_red"),
    "storage_bay": ("item: power_core",),
    "dark_corridor": ("item: power_core",),
    "elevator_lobby": ("riddle: riddle_1",),
    "control_room": ("riddle: riddle_3", "twist:"),
    "emergency_exit": ("twist:",),
    "basement_tunnel": ("item: hatch_code",),
    "maintenance_exit": ("ESCAPED",),
}


def room_at_progress(
    route: list[str],
    progress: float,
    *,
    fallback: str = "holding_cell",
) -> str:
    """Graph node id for the room T-0 is currently in along ``route``."""
    if not route:
        return fallback
    if len(route) < 2:
        return route[0]
    segment = min(int(progress), len(route) - 2)
    local = max(0.0, progress - segment)
    if segment >= len(route) - 2 and local >= 0.85:
        return route[-1]
    if local >= 0.5:
        return route[segment + 1]
    return route[segment]


def quest_for_room(room_id: str) -> RoomQuest | None:
    return ROOM_QUESTS.get(room_id)


def quest_complete(room_id: str, events: list[str]) -> bool:
    markers = _QUEST_DONE.get(room_id)
    if not markers:
        return False
    joined = "\n".join(events)
    return any(m in joined for m in markers)


def quest_fields(
    route: list[str],
    progress: float,
    *,
    location: str,
    events: list[str],
) -> dict[str, str | bool]:
    room_id = room_at_progress(route, progress, fallback=location or "holding_cell")
    quest = quest_for_room(room_id)
    if quest is None:
        return {"room_id": room_id}
    return {
        "room_id": room_id,
        "quest_title": quest.title,
        "quest_detail": quest.objective,
        "quest_mechanic": quest.mechanic,
        "quest_complete": quest_complete(room_id, events),
    }
