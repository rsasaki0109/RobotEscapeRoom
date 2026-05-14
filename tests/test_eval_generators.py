"""Tests for the deterministic graph + request generators."""

from __future__ import annotations

from datetime import time

from semantic_toponav.coordination.scheduler import SharedScheduler
from semantic_toponav.eval.generators import (
    apply_reservations,
    chain_graph,
    doorway_graph,
    generate_fleet_requests,
    generate_static_reservations,
    multi_floor_office,
    star_graph,
)


def test_chain_graph_has_n_nodes_and_n_minus_one_edges() -> None:
    g = chain_graph(5)
    assert len(g._nodes) == 5
    assert len(g._edges) == 4


def test_chain_graph_is_deterministic() -> None:
    g1 = chain_graph(6, seed=0)
    g2 = chain_graph(6, seed=0)
    assert list(g1._nodes.keys()) == list(g2._nodes.keys())
    assert list(g1._edges.keys()) == list(g2._edges.keys())


def test_star_graph_has_hub_and_n_leaves() -> None:
    g = star_graph(4)
    assert "hub" in g._nodes
    leaves = [n for n in g._nodes if n.startswith("leaf")]
    assert len(leaves) == 4
    # Every edge touches the hub.
    for e in g._edges.values():
        assert "hub" in (e.source, e.target)


def test_doorway_graph_has_single_door_edge() -> None:
    g = doorway_graph(n_rooms=3)
    assert "doorway" in g._edges
    assert g._edges["doorway"].type == "door"
    # The door endpoints are typed 'door' nodes.
    e = g._edges["doorway"]
    assert g._nodes[e.source].type == "door"
    assert g._nodes[e.target].type == "door"


def test_multi_floor_office_stamps_floor_property() -> None:
    g = multi_floor_office(n_floors=2, rooms_per_floor=3)
    floors = {n.properties.get("floor") for n in g._nodes.values()}
    assert floors == {1, 2}
    # Each pair of floors gets one elevator + one stairs edge.
    elev = [e for e in g._edges.values() if e.type == "elevator"]
    stairs = [e for e in g._edges.values() if e.type == "stairs"]
    assert len(elev) == 1
    assert len(stairs) == 1


def test_generate_fleet_requests_deterministic_with_seed() -> None:
    g = star_graph(5)
    a = generate_fleet_requests(g, 5, seed=42)
    b = generate_fleet_requests(g, 5, seed=42)
    assert [(r.agent_id, r.start, r.goal) for r in a] == [
        (r.agent_id, r.start, r.goal) for r in b
    ]


def test_generate_fleet_requests_different_seed_changes_pairs() -> None:
    g = star_graph(8)
    a = generate_fleet_requests(g, 5, seed=1)
    b = generate_fleet_requests(g, 5, seed=2)
    # At least one pair should differ; flag if both seeds collide.
    assert any(
        (ra.start, ra.goal) != (rb.start, rb.goal) for ra, rb in zip(a, b, strict=True)
    )


def test_generate_fleet_requests_deadline_tightness_zero_means_no_deadlines() -> None:
    g = chain_graph(6)
    reqs = generate_fleet_requests(g, 5, seed=0, deadline_tightness=0.0)
    assert all(r.deadline is None for r in reqs)


def test_generate_fleet_requests_deadline_tightness_one_means_all_deadlines() -> None:
    g = chain_graph(6)
    reqs = generate_fleet_requests(
        g, 5, seed=0, deadline_tightness=1.0,
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    assert all(r.deadline is not None for r in reqs)


def test_generate_fleet_requests_priority_high_profile() -> None:
    g = chain_graph(6)
    reqs = generate_fleet_requests(
        g, 20, seed=0, priority_distribution="high"
    )
    # "high" profile has no zero-priority entries.
    assert all(r.priority > 0 for r in reqs)


def test_generate_static_reservations_density_zero_returns_empty() -> None:
    g = chain_graph(5)
    out = generate_static_reservations(g, density=0.0)
    assert out == []


def test_generate_static_reservations_density_half_blocks_half_nodes() -> None:
    g = chain_graph(6)
    out = generate_static_reservations(g, density=0.5, seed=7)
    assert len(out) == 3  # ceil/floor of 6 * 0.5
    # All claims target node IDs that exist in the graph.
    node_ids = set(g._nodes.keys())
    for c in out:
        assert c.resource_id in node_ids


def test_apply_reservations_actually_loads_them() -> None:
    g = chain_graph(5)
    reservations = generate_static_reservations(g, density=0.4, seed=0)
    s = SharedScheduler()
    apply_reservations(s, reservations)
    assert len(s) == len(reservations)


def test_generate_fleet_requests_n_zero_returns_empty() -> None:
    g = chain_graph(4)
    assert generate_fleet_requests(g, 0) == []


def test_invalid_priority_distribution_raises() -> None:
    g = chain_graph(4)
    import pytest

    with pytest.raises(ValueError):
        generate_fleet_requests(g, 3, priority_distribution="totally-invalid")
