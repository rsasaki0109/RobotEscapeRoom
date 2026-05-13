"""Verify that path_to_semantic_waypoints output matches the published JSON schema."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.planner import plan_astar
from semantic_toponav.waypoint.semantic_waypoint import (
    path_to_semantic_waypoints,
)

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "schemas"
    / "semantic_waypoint_array.schema.json"
)
EXAMPLE_YAML = (
    Path(__file__).resolve().parents[1] / "examples" / "indoor_office.yaml"
)


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _build_payload(start: str, goal: str) -> dict:
    graph = load_graph(EXAMPLE_YAML)
    path = plan_astar(graph, start, goal)
    waypoints = path_to_semantic_waypoints(graph, path)
    return {"path": path, "waypoints": [wp.to_dict() for wp in waypoints]}


def test_schema_file_is_valid_jsonschema() -> None:
    schema = _load_schema()
    jsonschema.Draft202012Validator.check_schema(schema)


def test_real_payload_matches_schema() -> None:
    schema = _load_schema()
    payload = _build_payload("entrance", "meeting_room")
    jsonschema.validate(instance=payload, schema=schema)


def test_payload_round_trip_is_json_serializable() -> None:
    payload = _build_payload("entrance", "lab")
    # Surviving json.dumps -> loads round-trip is itself part of the contract.
    again = json.loads(json.dumps(payload))
    assert again == payload


def test_empty_path_payload_validates() -> None:
    schema = _load_schema()
    payload = {"path": [], "waypoints": []}
    jsonschema.validate(instance=payload, schema=schema)


def test_payload_with_unknown_top_level_field_rejected() -> None:
    schema = _load_schema()
    payload = _build_payload("entrance", "meeting_room")
    payload["unknown"] = "extra"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=payload, schema=schema)


def test_payload_with_invalid_action_rejected() -> None:
    schema = _load_schema()
    payload = _build_payload("entrance", "meeting_room")
    payload["waypoints"][0]["action"] = "fly"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=payload, schema=schema)
