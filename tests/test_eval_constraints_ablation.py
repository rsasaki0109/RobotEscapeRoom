"""The constraints-ablation Chapter-2 figure must stay reproducible.

Guards `examples/eval_constraints_ablation.py`: every constraint
configuration honors its constraint on the fixed office query, the soft
and time-of-day variants migrate the route onto the scenic corridor, the
floor penalty surfaces in the plan cost, the compose config keeps the
route on the elevator, and a weekday-filtered closure queried without a
date raises rather than silently ignoring the filter.
"""

from __future__ import annotations

from examples.eval_constraints_ablation import (
    CONFIGS,
    ablation_markdown,
    run_ablation,
)


def _rows():
    return {r.name: r for r in run_ablation()}


def test_every_config_produces_one_row() -> None:
    rows = run_ablation()
    assert len(rows) == len(CONFIGS) == 9


def test_baseline_takes_main_corridor_and_elevator() -> None:
    r = _rows()["baseline"]
    assert r.route == "f2_b→f2_a→f1_a→f1_b→f1_d"
    assert r.plan_cost == "5.0"


def test_every_constraint_is_honored() -> None:
    rows = _rows()
    # Each constraint config reports "yes" or the calendar-safety "raised".
    for name, r in rows.items():
        if name == "baseline":
            assert r.honored == "—"
        elif name.startswith("calendar-safety"):
            assert r.honored.startswith("raised ✓")
        else:
            assert r.honored == "yes", (name, r.honored)


def test_time_and_preference_configs_reroute_to_scenic() -> None:
    rows = _rows()
    scenic = "f2_b→f2_a→f1_a→f1_c→f1_d"
    for name in (
        "time_aware (daily)",
        "time_aware + at_date (weekday)",
        "time_aware + closed_on_dates",
        "preference (edge-level)",
        "preference (node inheritance)",
    ):
        assert rows[name].route == scenic, name


def test_floor_penalty_surfaces_in_plan_cost() -> None:
    r = _rows()["floor_change_penalty"]
    # Same physical route as baseline, but the +10 floor-change penalty
    # lifts the plan cost from 5.0 to 15.0.
    assert r.route == "f2_b→f2_a→f1_a→f1_b→f1_d"
    assert r.plan_cost == "15.0"


def test_compose_keeps_route_on_elevator_not_stairs() -> None:
    r = _rows()["compose: prefer_elevator + block stairs"]
    assert "f1_a→f2_a" not in r.route or "stairs" not in r.route
    # elevator is discounted, so the cross-floor leg costs 1.0, not 2.0.
    assert r.plan_cost == "4.0"
    assert r.honored == "yes"


def test_calendar_safety_raises_without_date() -> None:
    r = _rows()["calendar-safety (no at_date)"]
    assert r.route == "—"
    assert r.honored.startswith("raised ✓")
    assert "ValueError" in r.honored


def test_ablation_is_deterministic() -> None:
    a, b = _rows(), _rows()
    for name in a:
        assert (a[name].route, a[name].plan_cost, a[name].honored) == (
            b[name].route, b[name].plan_cost, b[name].honored
        )


def test_markdown_lists_every_config() -> None:
    md = ablation_markdown(run_ablation())
    assert "Semantic-constraints ablation" in md
    for cfg in CONFIGS:
        assert cfg.name in md
