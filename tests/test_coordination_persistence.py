"""Tests for save_scheduler / load_scheduler — SharedScheduler persistence."""

from __future__ import annotations

import json
from datetime import time
from pathlib import Path

import pytest
import yaml

from semantic_toponav.coordination import (
    ClaimRequest,
    SharedScheduler,
    load_scheduler,
    priority_based,
    save_scheduler,
)


def _populated_scheduler() -> SharedScheduler:
    s = SharedScheduler()
    s.claim(
        ClaimRequest(
            agent_id="r1", resource_id="corridor",
            start=time(10, 0), end=time(10, 30),
        )
    )
    s.claim(
        ClaimRequest(
            agent_id="r2", resource_id="kitchen",
            start=time(11, 0), end=time(12, 0),
            priority=3,
        )
    )
    return s


# ----- save -----------------------------------------------------------------


def test_save_returns_reservation_count(tmp_path: Path) -> None:
    s = _populated_scheduler()
    n = save_scheduler(s, tmp_path / "state.yaml")
    assert n == 2 == len(s)


def test_save_yaml_writes_human_readable_file(tmp_path: Path) -> None:
    s = _populated_scheduler()
    out = tmp_path / "state.yaml"
    save_scheduler(s, out)
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert len(data["reservations"]) == 2
    assert {r["agent_id"] for r in data["reservations"]} == {"r1", "r2"}


def test_save_json_writes_indented_json(tmp_path: Path) -> None:
    s = _populated_scheduler()
    out = tmp_path / "state.json"
    save_scheduler(s, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert len(data["reservations"]) == 2


def test_save_creates_parent_directory(tmp_path: Path) -> None:
    s = _populated_scheduler()
    out = tmp_path / "nested" / "deeper" / "state.yaml"
    save_scheduler(s, out)
    assert out.exists()


def test_save_rejects_unsupported_extension(tmp_path: Path) -> None:
    s = _populated_scheduler()
    with pytest.raises(ValueError, match="unsupported scheduler save extension"):
        save_scheduler(s, tmp_path / "state.txt")


def test_save_empty_scheduler_writes_empty_list(tmp_path: Path) -> None:
    s = SharedScheduler()
    out = tmp_path / "state.yaml"
    n = save_scheduler(s, out)
    assert n == 0
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["reservations"] == []


# ----- load -----------------------------------------------------------------


def test_load_round_trip_yaml(tmp_path: Path) -> None:
    src = _populated_scheduler()
    out = tmp_path / "state.yaml"
    save_scheduler(src, out)
    restored = load_scheduler(out)
    assert len(restored) == len(src)
    # Reservation equality compares all fields; agent_id and times must match.
    by_agent = {r.agent_id: r for r in restored.reservations()}
    assert by_agent["r1"].resource_id == "corridor"
    assert by_agent["r1"].start == time(10, 0)
    assert by_agent["r1"].end == time(10, 30)
    assert by_agent["r2"].resource_id == "kitchen"
    assert by_agent["r2"].start == time(11, 0)


def test_load_round_trip_json(tmp_path: Path) -> None:
    src = _populated_scheduler()
    out = tmp_path / "state.json"
    save_scheduler(src, out)
    restored = load_scheduler(out)
    assert {r.resource_id for r in restored.reservations()} == {
        "corridor", "kitchen",
    }


def test_load_preserves_insertion_order(tmp_path: Path) -> None:
    s = SharedScheduler()
    for resource in ("a", "b", "c", "d"):
        s.claim(
            ClaimRequest(
                agent_id="r1", resource_id=resource,
                start=time(10, 0), end=time(11, 0),
            )
        )
    out = tmp_path / "state.yaml"
    save_scheduler(s, out)
    restored = load_scheduler(out)
    assert [r.resource_id for r in restored.reservations()] == [
        "a", "b", "c", "d",
    ]


def test_load_starts_with_default_fcfs_policy(tmp_path: Path) -> None:
    """No policy argument → restored scheduler uses default FCFS."""
    src = _populated_scheduler()
    out = tmp_path / "state.yaml"
    save_scheduler(src, out)
    restored = load_scheduler(out)
    # FCFS denies any overlapping claim. Re-claim the same window and
    # verify the new request is denied.
    result = restored.claim(
        ClaimRequest(
            agent_id="r3", resource_id="corridor",
            start=time(10, 15), end=time(10, 20),
        )
    )
    assert result.granted is False


def test_load_with_priority_policy_overrides_default(tmp_path: Path) -> None:
    """policy=priority_based override is honored on restore."""
    src = _populated_scheduler()
    out = tmp_path / "state.yaml"
    save_scheduler(src, out)
    restored = load_scheduler(out, policy=priority_based)
    # priority_based preempts the holder when a higher-priority request
    # arrives. r1 holds corridor with default priority 0; a request with
    # priority 5 must succeed and evict r1.
    result = restored.claim(
        ClaimRequest(
            agent_id="r3", resource_id="corridor",
            start=time(10, 15), end=time(10, 20),
            priority=5,
        )
    )
    assert result.granted is True
    assert any(r.agent_id == "r1" for r in result.preempted)


def test_load_accepts_static_reservation_file(tmp_path: Path) -> None:
    """The save format is identical to the static reservation format
    used by the offline planner — files written by either side must
    load through either entry point."""
    out = tmp_path / "static.yaml"
    out.write_text(
        """version: 1
reservations:
  - {resource_id: hub, start: "09:00", end: "10:00", agent_id: ext_robot}
""",
        encoding="utf-8",
    )
    restored = load_scheduler(out)
    assert len(restored) == 1
    r = restored.reservations()[0]
    assert r.agent_id == "ext_robot"
    assert r.resource_id == "hub"


# ----- format equivalence ---------------------------------------------------


def test_yaml_and_json_round_trips_match(tmp_path: Path) -> None:
    """Saving the same scheduler to YAML and to JSON must restore the
    same set of reservations regardless of format."""
    src = _populated_scheduler()
    yaml_path = tmp_path / "state.yaml"
    json_path = tmp_path / "state.json"
    save_scheduler(src, yaml_path)
    save_scheduler(src, json_path)
    yaml_restored = load_scheduler(yaml_path)
    json_restored = load_scheduler(json_path)
    yaml_set = {
        (r.agent_id, r.resource_id, r.start, r.end)
        for r in yaml_restored.reservations()
    }
    json_set = {
        (r.agent_id, r.resource_id, r.start, r.end)
        for r in json_restored.reservations()
    }
    assert yaml_set == json_set
