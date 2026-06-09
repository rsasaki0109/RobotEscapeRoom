"""Tests for per-room escape-room quest metadata."""

from semantic_toponav.escape_room.quests import (
    quest_complete,
    quest_fields,
    quest_for_room,
    room_at_progress,
)


def test_room_at_progress_prefers_destination_on_late_segment():
    route = ["holding_cell", "west_corridor", "server_room"]
    assert room_at_progress(route, 0.2) == "holding_cell"
    assert room_at_progress(route, 0.6) == "west_corridor"
    assert room_at_progress(route, 1.6) == "server_room"
    assert room_at_progress(route, 2.0) == "server_room"


def test_quest_fields_for_server_room():
    fields = quest_fields(
        ["holding_cell", "west_corridor", "server_room"],
        1.6,
        location="holding_cell",
        events=["T-0 online — Holding Cell"],
    )
    assert fields["room_id"] == "server_room"
    assert fields["quest_title"] == "Quest · Terminal I"
    assert fields["quest_mechanic"] == "resolve_goal"
    assert fields["quest_complete"] is False


def test_quest_complete_after_riddle():
    assert quest_complete(
        "server_room",
        ["T-0 online — Holding Cell", "riddle: riddle_1"],
    )
    assert quest_for_room("main_lab") is not None


def test_quest_fields_without_route_falls_back_to_location():
    fields = quest_fields([], 0.0, location="main_lab", events=[])
    assert fields["room_id"] == "main_lab"
    assert "quest_title" in fields
