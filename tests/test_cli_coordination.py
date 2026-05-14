"""CLI integration tests for `semantic-toponav fleet-plan`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from semantic_toponav.cli.main import main

EXAMPLE_YAML = str(Path(__file__).resolve().parents[1] / "examples" / "indoor_office.yaml")


def test_fleet_plan_text_output_single_agent(capsys) -> None:
    rc = main(
        [
            "fleet-plan",
            EXAMPLE_YAML,
            "--agent",
            "r1:entrance:kitchen",
            "--hold-start",
            "10:00",
            "--hold-end",
            "11:00",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "[OK] r1" in out
    assert "kitchen" in out
    assert "all_granted: True" in out


def test_fleet_plan_two_agents_sequential(capsys) -> None:
    main(
        [
            "fleet-plan",
            EXAMPLE_YAML,
            "--agent",
            "r1:entrance:kitchen",
            "--agent",
            "r2:entrance:lab",
            "--hold-start",
            "10:00",
            "--hold-end",
            "11:00",
        ]
    )
    out = capsys.readouterr().out
    # Even if some agent fails on conflicts, the command still exits;
    # the text output captures both agent outcomes.
    assert "r1" in out
    assert "r2" in out


def test_fleet_plan_json_output_structure(capsys) -> None:
    rc = main(
        [
            "fleet-plan",
            EXAMPLE_YAML,
            "--agent",
            "r1:entrance:kitchen",
            "--hold-start",
            "10:00",
            "--hold-end",
            "11:00",
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert payload["all_granted"] is True
    assert len(payload["agents"]) == 1
    agent = payload["agents"][0]
    assert agent["agent_id"] == "r1"
    assert agent["path"][0] == "entrance"
    assert agent["path"][-1] == "kitchen"
    assert len(agent["claims"]) > 0


def test_fleet_plan_priority_policy_preempts(capsys) -> None:
    rc = main(
        [
            "fleet-plan",
            EXAMPLE_YAML,
            "--agent",
            "r1:entrance:kitchen",
            "--agent",
            "r2:entrance:kitchen:5",
            "--hold-start",
            "10:00",
            "--hold-end",
            "11:00",
            "--policy",
            "priority",
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)
    # Both agents should be granted under priority preemption.
    assert payload["all_granted"] is True
    assert rc == 0


def test_fleet_plan_missing_agent_arg_errors(capsys) -> None:
    rc = main(
        [
            "fleet-plan",
            EXAMPLE_YAML,
            "--hold-start",
            "10:00",
            "--hold-end",
            "11:00",
        ]
    )
    err = capsys.readouterr().err
    assert rc == 2
    assert "agent" in err.lower()


def test_fleet_plan_malformed_agent_spec_errors(capsys) -> None:
    # argparse raises SystemExit(2) when a --type callable rejects the value.
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "fleet-plan",
                EXAMPLE_YAML,
                "--agent",
                "missing-colons",
                "--hold-start",
                "10:00",
                "--hold-end",
                "11:00",
            ]
        )
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "AGENT_ID:START:GOAL" in err


def test_fleet_plan_hard_admission_rejects_tight_deadline(capsys) -> None:
    rc = main(
        [
            "fleet-plan",
            EXAMPLE_YAML,
            # entrance -> office_2f crosses several edges (>5 cost units),
            # well over a 10:02 deadline.
            "--agent",
            "r1:entrance:office_2f:0:10:02",
            "--hold-start",
            "10:00",
            "--hold-end",
            "11:00",
            "--admission",
            "hard",
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 1
    assert payload["agents"][0]["reason_code"] == "deadline_miss"
    assert payload["agents"][0]["granted"] is False


def test_fleet_plan_soft_admission_grants_same_request(capsys) -> None:
    main(
        [
            "fleet-plan",
            EXAMPLE_YAML,
            "--agent",
            "r1:entrance:office_2f:0:10:02",
            "--hold-start",
            "10:00",
            "--hold-end",
            "11:00",
            "--admission",
            "soft",
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)
    # Same request, soft admission -> granted, even though arrival is
    # well past the (informational) deadline.
    assert payload["agents"][0]["granted"] is True
    assert payload["agents"][0]["reason_code"] == "ok"


def test_fleet_plan_reason_code_appears_on_grant(capsys) -> None:
    main(
        [
            "fleet-plan",
            EXAMPLE_YAML,
            "--agent",
            "r1:entrance:kitchen",
            "--hold-start",
            "10:00",
            "--hold-end",
            "11:00",
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["agents"][0]["reason_code"] == "ok"


def test_fleet_plan_agent_spec_accepts_priority_and_deadline(capsys) -> None:
    rc = main(
        [
            "fleet-plan",
            EXAMPLE_YAML,
            "--agent",
            "r1:entrance:kitchen:3:10:45",
            "--hold-start",
            "10:00",
            "--hold-end",
            "11:00",
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert payload["agents"][0]["agent_id"] == "r1"


def test_fleet_plan_strategy_priority(capsys) -> None:
    main(
        [
            "fleet-plan",
            EXAMPLE_YAML,
            "--agent",
            "low:entrance:kitchen:0",
            "--agent",
            "high:entrance:lab:5",
            "--hold-start",
            "10:00",
            "--hold-end",
            "11:00",
            "--strategy",
            "priority",
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)
    # Reordering: high-priority agent goes first regardless of submission order.
    # All-granted is not guaranteed under FCFS — both agents share 'entrance'.
    assert payload["agents"][0]["agent_id"] == "high"


def test_fleet_plan_strategy_deadline_reorders(capsys) -> None:
    main(
        [
            "fleet-plan",
            EXAMPLE_YAML,
            "--agent",
            "late:entrance:kitchen:0:12:00",
            "--agent",
            "early:entrance:lab:0:10:30",
            "--hold-start",
            "10:00",
            "--hold-end",
            "11:00",
            "--strategy",
            "deadline",
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)
    # Earliest deadline runs first. Grant outcome is policy-dependent
    # and not asserted here.
    assert payload["agents"][0]["agent_id"] == "early"


def test_fleet_plan_strategy_joint(capsys) -> None:
    rc = main(
        [
            "fleet-plan",
            EXAMPLE_YAML,
            "--agent",
            "r1:entrance:kitchen",
            "--agent",
            "r2:entrance:lab",
            "--hold-start",
            "10:00",
            "--hold-end",
            "11:00",
            "--strategy",
            "joint",
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)
    # Joint optimizer should at least match greedy on this small case.
    assert len(payload["agents"]) == 2
    assert rc in (0, 1)


def test_fleet_plan_rollback_releases_partial(capsys) -> None:
    # Two agents requesting routes that will collide on shared resources.
    rc = main(
        [
            "fleet-plan",
            EXAMPLE_YAML,
            "--agent",
            "r1:entrance:office_2f",
            "--agent",
            "r2:entrance:lab",
            "--hold-start",
            "10:00",
            "--hold-end",
            "11:00",
            "--rollback-on-failure",
            "--format",
            "json",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)
    # rc is 1 if anyone failed.
    if not payload["all_granted"]:
        assert rc == 1
    else:
        assert rc == 0
