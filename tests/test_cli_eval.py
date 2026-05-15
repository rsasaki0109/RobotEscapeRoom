"""CLI smoke tests for `semantic-toponav eval-synthetic` / `eval-report`."""

from __future__ import annotations

from pathlib import Path

from semantic_toponav.cli.main import main


def test_eval_synthetic_smoke_text_output(capsys) -> None:
    rc = main(
        [
            "eval-synthetic",
            "--scenario", "chain",
            "--n-agents", "2",
            "--seed", "0",
            "--hold-start", "10:00",
            "--hold-end", "11:00",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "### grants" in out
    assert "chain" in out


def test_eval_synthetic_all_scenarios_smaller_fleet(capsys) -> None:
    rc = main(
        [
            "eval-synthetic",
            "--scenario", "all",
            "--n-agents", "2",
            "--seed", "1",
            "--hold-start", "10:00",
            "--hold-end", "11:00",
            "--strategy", "greedy",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    for s in ("chain", "star", "doorway", "multi_floor"):
        assert s in out


def test_eval_synthetic_jsonl_output(tmp_path: Path, capsys) -> None:
    out_path = tmp_path / "trials.jsonl"
    rc = main(
        [
            "eval-synthetic",
            "--scenario", "chain",
            "--n-agents", "2",
            "--seed", "0",
            "--hold-start", "10:00",
            "--hold-end", "11:00",
            "--out", str(out_path),
        ]
    )
    assert rc == 0
    assert out_path.exists()
    lines = [
        ln for ln in out_path.read_text(encoding="utf-8").splitlines() if ln.strip()
    ]
    # 4 strategies × 1 scenario = 4 rows.
    assert len(lines) == 4


def test_eval_synthetic_summary_flag(capsys) -> None:
    rc = main(
        [
            "eval-synthetic",
            "--scenario", "chain",
            "--n-agents", "2",
            "--seed", "0",
            "--hold-start", "10:00",
            "--hold-end", "11:00",
            "--summary",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "### summary" in out


def test_eval_report_reads_jsonl(tmp_path: Path, capsys) -> None:
    out_path = tmp_path / "trials.jsonl"
    main(
        [
            "eval-synthetic",
            "--scenario", "chain",
            "--n-agents", "2",
            "--hold-start", "10:00",
            "--hold-end", "11:00",
            "--out", str(out_path),
        ]
    )
    capsys.readouterr()  # drain
    rc = main(["eval-report", str(out_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "chain" in out


def test_eval_report_missing_file_errors(capsys) -> None:
    rc = main(["eval-report", "/tmp/definitely-not-here.jsonl"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "not found" in err.lower()


def test_eval_synthetic_unknown_scenario_errors(capsys) -> None:
    rc = main(
        [
            "eval-synthetic",
            "--scenario", "chain",
            "--n-agents", "2",
            "--hold-start", "10:00",
            "--hold-end", "11:00",
        ]
    )
    # 'chain' alone is valid; ensure exit 0.
    assert rc == 0


def test_eval_synthetic_hard_admission_emits_deadline_misses(
    tmp_path: Path, capsys
) -> None:
    """With --admission hard and a tight deadline_tightness, the resulting
    JSONL must carry non-zero deadline_miss_count for at least some
    strategies."""
    out_path = tmp_path / "hard.jsonl"
    rc = main(
        [
            "eval-synthetic",
            "--scenario", "chain",
            "--n-agents", "4",
            "--seed", "0",
            "--hold-start", "10:00",
            "--hold-end", "11:00",
            "--deadline-tightness", "1.0",
            "--admission", "hard",
            "--minutes-per-cost-unit", "5.0",
            "--out", str(out_path),
        ]
    )
    assert rc == 0
    assert out_path.exists()
    import json
    lines = [
        json.loads(ln)
        for ln in out_path.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    # At least one strategy hit a deadline_miss; the table column is
    # also present in the printed markdown.
    assert any(row["metrics"]["deadline_miss_count"] > 0 for row in lines)
    captured = capsys.readouterr().out
    assert "deadline_misses" in captured


def test_eval_synthetic_soft_admission_zero_deadline_misses(
    tmp_path: Path, capsys
) -> None:
    out_path = tmp_path / "soft.jsonl"
    main(
        [
            "eval-synthetic",
            "--scenario", "chain",
            "--n-agents", "4",
            "--seed", "0",
            "--hold-start", "10:00",
            "--hold-end", "11:00",
            "--deadline-tightness", "1.0",
            "--admission", "soft",
            "--out", str(out_path),
        ]
    )
    import json
    lines = [
        json.loads(ln)
        for ln in out_path.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    # Soft admission never produces deadline_miss reason codes.
    assert all(row["metrics"]["deadline_miss_count"] == 0 for row in lines)


def test_eval_synthetic_strategy_bnb_opt_in(tmp_path: Path) -> None:
    out_path = tmp_path / "bnb.jsonl"
    rc = main(
        [
            "eval-synthetic",
            "--scenario", "chain",
            "--n-agents", "3",
            "--seed", "0",
            "--hold-start", "10:00",
            "--hold-end", "11:00",
            "--strategy", "bnb",
            "--out", str(out_path),
        ]
    )
    assert rc == 0
    import json
    lines = [
        json.loads(ln)
        for ln in out_path.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    # Single scenario × single strategy = 1 row.
    assert len(lines) == 1
    assert lines[0]["strategy"] == "bnb"


def test_eval_synthetic_strategy_exhaustive_opt_in(tmp_path: Path) -> None:
    """``exhaustive`` is opt-in just like ``bnb``; one row per scenario."""
    out_path = tmp_path / "exhaustive.jsonl"
    rc = main(
        [
            "eval-synthetic",
            "--scenario", "chain",
            "--n-agents", "3",
            "--seed", "0",
            "--hold-start", "10:00",
            "--hold-end", "11:00",
            "--strategy", "exhaustive",
            "--out", str(out_path),
        ]
    )
    assert rc == 0
    import json
    lines = [
        json.loads(ln)
        for ln in out_path.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assert len(lines) == 1
    assert lines[0]["strategy"] == "exhaustive"


def test_eval_synthetic_strategy_exhaustive_bounds_bnb_grant_rate(
    tmp_path: Path,
) -> None:
    """Exhaustive is the MIS upper bound on grant rate, so BnB grant_count
    must be <= exhaustive grant_count for the same scenario."""
    out_path = tmp_path / "both.jsonl"
    rc = main(
        [
            "eval-synthetic",
            "--scenario", "doorway",
            "--n-agents", "4",
            "--seed", "2",
            "--hold-start", "10:00",
            "--hold-end", "11:00",
            "--strategy", "bnb",
            "--strategy", "exhaustive",
            "--out", str(out_path),
        ]
    )
    assert rc == 0
    import json
    rows = {
        json.loads(ln)["strategy"]: json.loads(ln)
        for ln in out_path.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    }
    assert (
        rows["exhaustive"]["metrics"]["granted_count"]
        >= rows["bnb"]["metrics"]["granted_count"]
    )


def test_eval_synthetic_deadline_tightness_affects_deadline_field(tmp_path: Path) -> None:
    out_path = tmp_path / "tight.jsonl"
    main(
        [
            "eval-synthetic",
            "--scenario", "chain",
            "--n-agents", "5",
            "--seed", "0",
            "--hold-start", "10:00",
            "--hold-end", "11:00",
            "--deadline-tightness", "1.0",
            "--out", str(out_path),
            "--strategy", "deadline",
        ]
    )
    assert out_path.exists()
