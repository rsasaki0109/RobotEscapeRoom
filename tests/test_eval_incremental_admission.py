"""The incremental-admission Chapter-1 figure must stay reproducible.

Guards the deterministic outcome of `examples/eval_incremental_admission.py`
so the paper figure (naive append vs insertion repair vs full BnB) does not
silently drift: insertion repair admits the urgent newcomer and matches the
full BnB optimum at a fraction of the search, while naive append is locked
by submission order. Wall-clock (`elapsed_ms`) is deliberately not asserted.
"""

from __future__ import annotations

from examples.eval_incremental_admission import (
    build_scenario,
    comparison_markdown,
    run_comparison,
)


def _by_name(results):
    return {r.name: r for r in results}


def test_naive_append_is_locked_by_submission_order() -> None:
    results = _by_name(run_comparison(build_scenario()))
    naive = results["naive append"]
    # The chain-spanning long-haul is granted first and blocks everyone.
    assert naive.granted_ids == ["long-A n0->n9"]
    assert naive.newcomer_admitted is False
    assert naive.orderings_explored == 1


def test_insertion_repair_recovers_the_optimum() -> None:
    scenario = build_scenario()
    results = _by_name(run_comparison(scenario))
    rep, full = results["insertion repair"], results["full BnB"]

    # Repair admits the urgent newcomer plus the two short services.
    assert rep.newcomer_admitted is True
    assert set(rep.granted_ids) == {
        "urgent-E n3->n5", "svc-B n0->n2", "svc-C n6->n8"
    }
    # It matches the full re-search on grants and total cost...
    assert len(rep.granted_ids) == len(full.granted_ids) == 3
    assert rep.total_cost == full.total_cost
    assert set(rep.granted_ids) == set(full.granted_ids)


def test_repair_beats_naive_and_is_cheaper_to_search_than_bnb() -> None:
    results = _by_name(run_comparison(build_scenario()))
    naive, rep, full = (
        results["naive append"], results["insertion repair"], results["full BnB"]
    )
    # naive < insert == bnb on grants...
    assert len(naive.granted_ids) < len(rep.granted_ids)
    assert len(rep.granted_ids) == len(full.granted_ids)
    # ...and insertion explores strictly fewer trial orderings than BnB.
    assert rep.orderings_explored < full.orderings_explored


def test_comparison_is_deterministic() -> None:
    a = _by_name(run_comparison(build_scenario()))
    b = _by_name(run_comparison(build_scenario()))
    for name in a:
        assert a[name].granted_ids == b[name].granted_ids
        assert a[name].total_cost == b[name].total_cost
        assert a[name].orderings_explored == b[name].orderings_explored


def test_markdown_renders_all_three_approaches() -> None:
    scenario = build_scenario()
    md = comparison_markdown(run_comparison(scenario), scenario)
    assert "Incremental admission" in md
    assert "naive append" in md
    assert "insertion repair" in md
    assert "full BnB" in md
    assert "trial orderings" in md
    assert "× fewer" in md
