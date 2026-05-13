"""Tests for trajectory log -> topology graph conversion."""

from __future__ import annotations

import math
import random

from semantic_toponav.conversion import topology_from_trajectories


def _line(p0: tuple[float, float], p1: tuple[float, float], n: int = 40):
    x0, y0 = p0
    x1, y1 = p1
    return [
        (x0 + (x1 - x0) * t / (n - 1), y0 + (y1 - y0) * t / (n - 1)) for t in range(n)
    ]


def test_empty_input_returns_empty_graph() -> None:
    g = topology_from_trajectories([], eps=1.0, min_samples=1)
    assert g.node_ids() == []
    assert g.edge_ids() == []


def test_single_point_below_min_samples_drops_node() -> None:
    g = topology_from_trajectories([[(0.0, 0.0)]], eps=1.0, min_samples=2)
    assert g.node_ids() == []


def test_repeated_trajectory_increases_traversal_count() -> None:
    line = _line((0.0, 0.0), (5.0, 0.0), n=11)
    g = topology_from_trajectories([line, line], eps=1.5, min_samples=2)
    assert len(g.edge_ids()) >= 1
    for e in g.edges():
        assert e.properties["traversal_count"] == 2


def test_crossing_trajectories_share_an_intersection_node() -> None:
    horizontal = _line((0.0, 5.0), (10.0, 5.0), n=21)
    vertical = _line((5.0, 0.0), (5.0, 10.0), n=21)
    g = topology_from_trajectories([horizontal, vertical], eps=1.5, min_samples=2)
    # Identify the node nearest (5,5) — it should have a cluster_size > 5
    # because both trajectories deposit points there.
    near_center = min(
        g.nodes(),
        key=lambda n: math.hypot(n.pose.x - 5.0, n.pose.y - 5.0),
    )
    assert near_center.properties["cluster_size"] >= 5
    # The center node should have degree >= 3 (two arms in, two arms out, minus overlap).
    incident = list(g.neighbors(near_center.id))
    assert len(incident) >= 3


def test_eps_controls_node_density() -> None:
    line = _line((0.0, 0.0), (10.0, 0.0), n=41)
    coarse = topology_from_trajectories([line], eps=2.0, min_samples=2)
    fine = topology_from_trajectories([line], eps=0.5, min_samples=2)
    assert len(coarse.node_ids()) < len(fine.node_ids())


def test_node_pose_is_cluster_centroid() -> None:
    pts = [(0.0, 0.0)] * 5 + [(10.0, 0.0)] * 5
    random.seed(1)
    jittered = [(x + random.gauss(0, 0.01), y + random.gauss(0, 0.01)) for x, y in pts]
    g = topology_from_trajectories([jittered], eps=1.0, min_samples=3)
    assert len(g.node_ids()) == 2
    poses = sorted(((n.pose.x, n.pose.y) for n in g.nodes()))
    assert abs(poses[0][0] - 0.0) < 0.1
    assert abs(poses[1][0] - 10.0) < 0.1


def test_edge_cost_is_centroid_distance() -> None:
    pts = [(0.0, 0.0)] * 5 + [(3.0, 4.0)] * 5  # 5 -> 5 distance is 5
    g = topology_from_trajectories([pts], eps=1.0, min_samples=3)
    assert len(g.edge_ids()) == 1
    edge = next(iter(g.edges()))
    assert math.isclose(edge.cost, 5.0, abs_tol=0.05)


def test_min_samples_filters_noise() -> None:
    # Main line with many points + one isolated noise point.
    main = _line((0.0, 0.0), (5.0, 0.0), n=21)
    noisy = main + [(20.0, 20.0)]
    g = topology_from_trajectories([noisy], eps=1.5, min_samples=3)
    # The isolated noise point should not become a node.
    for n in g.nodes():
        assert not (abs(n.pose.x - 20.0) < 0.5 and abs(n.pose.y - 20.0) < 0.5)
