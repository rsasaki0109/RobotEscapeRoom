"""Tests for eval/report.py — JSONL round-trip + markdown table formatting."""

from __future__ import annotations

import json
from pathlib import Path

from semantic_toponav.coordination.fleet import FleetPlanResult, PlanWithSchedulerResult
from semantic_toponav.eval.metrics import TrialMetrics
from semantic_toponav.eval.report import (
    jsonl_to_trials,
    summarize_sweep,
    trials_to_jsonl,
    trials_to_markdown_table,
)
from semantic_toponav.eval.runner import TrialResult


def _make_trial(scenario: str, strategy: str, *, granted: int = 2) -> TrialResult:
    return TrialResult(
        scenario_name=scenario,
        strategy=strategy,  # type: ignore[arg-type]
        metrics=TrialMetrics(
            granted_count=granted,
            grant_rate=granted / 4.0,
            total_path_cost=10.0 + granted,
            coord_makespan_minutes=5.0,
            mean_wait_minutes=0.0,
            max_wait_minutes=0.0,
            jain_fairness=1.0,
            conflict_count=0,
            latency_ms=12.5,
        ),
        fleet_result=FleetPlanResult(
            results=[
                PlanWithSchedulerResult(agent_id=f"a{i}", granted=i < granted, path=["x"] * 3)
                for i in range(4)
            ]
        ),
        metadata={"seed": "0"},
    )


def test_jsonl_roundtrip_preserves_metrics(tmp_path: Path) -> None:
    trials = [
        _make_trial("chain", "greedy"),
        _make_trial("chain", "joint", granted=3),
    ]
    path = tmp_path / "trials.jsonl"
    n = trials_to_jsonl(trials, path)
    assert n == 2

    reloaded = jsonl_to_trials(path)
    assert len(reloaded) == 2
    assert reloaded[0].metrics == trials[0].metrics
    assert reloaded[1].scenario_name == "chain"
    assert reloaded[1].strategy == "joint"


def test_jsonl_row_is_valid_json(tmp_path: Path) -> None:
    path = tmp_path / "trial.jsonl"
    trials_to_jsonl([_make_trial("chain", "greedy")], path)
    with path.open() as fh:
        line = fh.readline()
    parsed = json.loads(line)
    assert parsed["scenario"] == "chain"
    assert parsed["strategy"] == "greedy"
    assert "metrics" in parsed
    assert "agents" in parsed


def test_markdown_table_contains_canonical_columns() -> None:
    trials = [
        _make_trial("chain", "greedy"),
        _make_trial("chain", "joint", granted=3),
    ]
    md = trials_to_markdown_table(trials)
    # Header section labels
    assert "### grants" in md
    assert "### rate" in md
    assert "### latency_ms" in md
    # Strategies in canonical order.
    assert "| chain | 2 | 3 |" in md  # greedy=2, joint=3


def test_markdown_table_empty_returns_placeholder() -> None:
    md = trials_to_markdown_table([])
    assert "(no trials)" in md


def test_markdown_table_handles_missing_cells() -> None:
    # Only greedy was run on "chain"; only joint was run on "star".
    trials = [
        _make_trial("chain", "greedy"),
        _make_trial("star", "joint", granted=4),
    ]
    md = trials_to_markdown_table(trials)
    # Both strategies appear; missing cells fall back to em-dash.
    assert "greedy" in md
    assert "joint" in md
    assert "—" in md


def test_summarize_sweep_groups_by_strategy() -> None:
    trials = [
        _make_trial("chain", "greedy", granted=2),
        _make_trial("star", "greedy", granted=3),
        _make_trial("chain", "joint", granted=4),
    ]
    summary = summarize_sweep(trials)
    assert set(summary.keys()) == {"greedy", "joint"}
    assert summary["greedy"]["trials"] == 2
    assert summary["joint"]["trials"] == 1


def test_jsonl_roundtrip_then_markdown_works(tmp_path: Path) -> None:
    trials = [_make_trial("chain", "greedy")]
    path = tmp_path / "x.jsonl"
    trials_to_jsonl(trials, path)
    md = trials_to_markdown_table(jsonl_to_trials(path))
    assert "chain" in md
    assert "greedy" in md
