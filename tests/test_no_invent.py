"""Adversarial no-invent audit for the LLM-augmented resolver.

These tests prove the safety property `llm_resolve_goal` documents — the
LLM may re-rank the deterministic candidate pool but can never inject a
node id outside it — by replaying a catalog of adversarial LLM replies
and asserting a 0.00 leak rate. See
:mod:`semantic_toponav.eval.no_invent`.
"""

from __future__ import annotations

import pytest

from semantic_toponav.eval.no_invent import (
    NoInventReport,
    run_no_invent_audit,
    run_no_invent_conformance,
)
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode

QUERY = "executive office on 3F"


def _multi_floor_graph() -> TopologyGraph:
    """Small two-floor office with several 3F rooms (a contended pool)."""
    graph = TopologyGraph()
    specs = [
        ("entrance", "Entrance", "entrance", 1),
        ("corridor_1f", "1F Corridor", "corridor", 1),
        ("kitchen_1f", "Kitchen", "room", 1),
        ("elevator_1f", "Elevator (1F)", "elevator", 1),
        ("corridor_3f", "3F Corridor", "corridor", 3),
        ("exec_office_3f", "Executive Office", "room", 3),
        ("balcony_3f", "3F Balcony", "balcony", 3),
        ("elevator_3f", "Elevator (3F)", "elevator", 3),
        ("stairs_3f", "North Stairs (3F)", "stairs", 3),
    ]
    for i, (nid, label, ntype, floor) in enumerate(specs):
        graph.add_node(
            TopologyNode(
                id=nid, label=label, type=ntype,
                pose=Pose2D(float(i), 0.0), properties={"floor": floor},
            )
        )
    graph.add_edge(
        TopologyEdge(id="e1", source="entrance", target="corridor_1f",
                     type="traversable")
    )
    return graph


def test_audit_reports_zero_leak_rate() -> None:
    report = run_no_invent_audit(_multi_floor_graph(), QUERY)
    assert isinstance(report, NoInventReport)
    assert report.n_attacks >= 10
    assert report.leak_rate == 0.0
    assert report.all_safe
    # The pool is the 3F tier; the winner is the executive office.
    assert report.pool_ids[0] == "exec_office_3f"
    assert "kitchen_1f" not in report.pool_ids  # a real out-of-pool node


def test_no_attack_leaks_an_out_of_pool_id() -> None:
    report = run_no_invent_audit(_multi_floor_graph(), QUERY)
    pool = set(report.pool_ids)
    for v in report.verdicts:
        assert not v.leaked_ids, f"{v.attack} leaked {v.leaked_ids}"
    # Every id the resolver ever returned, across all attacks, is in-pool.
    for v in report.verdicts:
        assert pool.issuperset(set(v.leaked_ids))


def test_out_of_pool_picks_fall_back_preserving_order() -> None:
    report = run_no_invent_audit(_multi_floor_graph(), QUERY)
    by_attack = {v.attack: v for v in report.verdicts}
    # Hallucinated / injected / payload picks must fall back, order intact.
    for attack in (
        "hallucinated_out_of_graph",
        "valid_node_outside_pool",
        "prompt_injection",
        "payload_in_pick",
        "first_pick_wins_invented",
        "clarification_chosen_id_invented",
    ):
        v = by_attack[attack]
        assert v.used_fallback, f"{attack} did not fall back"
        assert v.order_preserved, f"{attack} reordered on fallback"


def test_valid_pick_with_decoy_reranks_without_leaking() -> None:
    report = run_no_invent_audit(_multi_floor_graph(), QUERY)
    v = {x.attack: x for x in report.verdicts}["valid_pick_with_invented_decoy"]
    # A legitimate in-pool pick is honored (no fallback) and the decoy id
    # in the same reply never reaches the output.
    assert not v.used_fallback
    assert not v.leaked_ids
    assert v.safe


def test_conformance_passes_and_returns_report() -> None:
    report = run_no_invent_conformance(_multi_floor_graph(), QUERY)
    assert report.leak_rate == 0.0


def test_audit_raises_on_unresolvable_query() -> None:
    with pytest.raises(ValueError, match="did not resolve"):
        run_no_invent_audit(_multi_floor_graph(), "zzzzz nonexistent qqqq")


def test_markdown_renders_table() -> None:
    from semantic_toponav.eval.no_invent import no_invent_audit_markdown

    report = run_no_invent_audit(_multi_floor_graph(), QUERY)
    md = no_invent_audit_markdown(report)
    assert "Leak rate: **0.00**" in md
    assert "| attack | fell back | leaked ids | safe |" in md
    assert "hallucinated_out_of_graph" in md
