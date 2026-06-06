"""The BnB budget-sweep Chapter-1 figure must stay reproducible.

Guards `examples/eval_bnb_budget_sweep.py`: budget-bounded BnB is an
anytime planner — its best-so-far is never below greedy and never above the
optimum, it matches the exhaustive optimum when it completes, and it keeps
producing rows past the point where the exhaustive baseline is infeasible.
"""

from __future__ import annotations

from examples.eval_bnb_budget_sweep import (
    EXHAUSTIVE_N_LIMIT,
    SWEEP_K,
    build_clustered_scenario,
    run_sweep,
    sweep_markdown,
)


def test_one_row_per_fleet_size() -> None:
    rows = run_sweep()
    assert [r.k for r in rows] == SWEEP_K
    assert [r.n for r in rows] == [3 * k for k in SWEEP_K]


def test_optimum_is_two_k_and_greedy_is_k() -> None:
    for r in run_sweep():
        assert r.optimum == 2 * r.k
        assert r.greedy == r.k  # blocker-first submission order grants the blockers


def test_bnb_is_anytime_between_greedy_and_optimum() -> None:
    for r in run_sweep():
        # Never worse than the greedy baseline...
        assert r.bnb >= r.greedy
        # ...and never better than the true optimum.
        assert r.bnb <= r.optimum


def test_completed_runs_match_the_exhaustive_optimum() -> None:
    rows = run_sweep()
    completed = [r for r in rows if r.bnb_completed]
    assert completed, "expected at least one fleet small enough for BnB to complete"
    for r in completed:
        assert r.exhaustive == r.optimum
        assert r.bnb == r.optimum


def test_partial_runs_still_beat_greedy() -> None:
    partial = [r for r in run_sweep() if not r.bnb_completed]
    assert partial, "expected at least one fleet too large for BnB to complete"
    for r in partial:
        assert r.bnb > r.greedy  # anytime improvement under a tight budget


def test_exhaustive_drops_out_past_the_limit() -> None:
    for r in run_sweep():
        if r.n > EXHAUSTIVE_N_LIMIT:
            assert r.exhaustive is None
        else:
            assert r.exhaustive == r.optimum


def test_sweep_is_deterministic() -> None:
    a, b = run_sweep(), run_sweep()
    for x, y in zip(a, b, strict=True):
        assert (x.greedy, x.bnb, x.bnb_completed, x.bnb_nodes, x.exhaustive) == (
            y.greedy, y.bnb, y.bnb_completed, y.bnb_nodes, y.exhaustive
        )


def test_scenario_shape() -> None:
    graph, requests = build_clustered_scenario(3)
    assert len(requests) == 9  # 3 clusters x (1 blocker + 2 shorts)
    assert len(list(graph.nodes())) == 12  # 4 nodes per cluster


def test_markdown_renders_table() -> None:
    md = sweep_markdown(run_sweep())
    assert "Budget-bounded BnB" in md
    assert "anytime guarantee" in md
    assert "infeasible" in md  # the n=30 exhaustive cell
