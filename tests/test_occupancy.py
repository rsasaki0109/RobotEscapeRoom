"""Tests for occupancy grid -> topology graph conversion.

Skipped when NumPy or scikit-image are not installed.
"""

from __future__ import annotations

import math

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("skimage")

from semantic_toponav.conversion.occupancy import topology_from_occupancy
from semantic_toponav.planner.astar import plan_astar


def test_straight_line_yields_two_endpoints_one_edge() -> None:
    grid = np.zeros((5, 15), dtype=bool)
    grid[2, 1:14] = True
    g = topology_from_occupancy(grid, resolution=1.0)
    assert len(g.node_ids()) == 2
    assert len(g.edge_ids()) == 1
    assert {n.type for n in g.nodes()} == {"endpoint"}


def test_l_shape_yields_two_endpoints_one_edge() -> None:
    grid = np.zeros((10, 10), dtype=bool)
    grid[2, 1:8] = True
    grid[2:8, 7] = True
    g = topology_from_occupancy(grid, resolution=1.0)
    assert len(g.node_ids()) == 2
    assert len(g.edge_ids()) == 1


def test_t_shape_has_one_junction_three_endpoints() -> None:
    grid = np.zeros((10, 11), dtype=bool)
    grid[3, 1:10] = True
    grid[3:9, 5] = True
    g = topology_from_occupancy(grid, resolution=1.0)
    types = [n.type for n in g.nodes()]
    assert types.count("intersection") == 1
    assert types.count("endpoint") == 3
    assert len(g.edge_ids()) == 3


def test_plus_shape_has_one_junction_four_endpoints() -> None:
    grid = np.zeros((11, 21), dtype=bool)
    grid[5:6, 2:19] = True
    grid[2:9, 10:11] = True
    g = topology_from_occupancy(grid, resolution=1.0)
    types = [n.type for n in g.nodes()]
    assert types.count("intersection") == 1
    assert types.count("endpoint") == 4
    assert len(g.edge_ids()) == 4


def test_edge_cost_reflects_pixel_length_times_resolution() -> None:
    grid = np.zeros((3, 11), dtype=bool)
    grid[1, 1:10] = True  # 9 cells -> 8 steps -> 8.0 * resolution
    g = topology_from_occupancy(grid, resolution=0.5)
    (edge,) = list(g.edges())
    assert math.isclose(edge.cost, 8 * 0.5, abs_tol=1e-6)


def test_resolution_and_origin_are_applied_to_pose() -> None:
    grid = np.zeros((3, 5), dtype=bool)
    grid[1, 1:4] = True
    g = topology_from_occupancy(grid, resolution=0.25, origin=(10.0, 20.0))
    # World y for a cell in a 3-row grid is origin.y + (H - 1 - row + 0.5) * res
    for node in g.nodes():
        assert node.pose is not None
        assert node.pose.x >= 10.0
        assert node.pose.y >= 20.0


def test_two_d_input_required() -> None:
    grid = np.zeros((3, 3, 2), dtype=bool)
    with pytest.raises(ValueError):
        topology_from_occupancy(grid)


def test_planning_works_on_converted_graph() -> None:
    grid = np.zeros((11, 21), dtype=bool)
    grid[5:6, 2:19] = True
    grid[2:9, 10:11] = True
    g = topology_from_occupancy(grid, resolution=1.0)
    endpoints = [n.id for n in g.nodes() if n.type == "endpoint"]
    assert len(endpoints) == 4
    path = plan_astar(g, endpoints[0], endpoints[-1])
    # Path passes through the single intersection.
    intersections = [n.id for n in g.nodes() if n.type == "intersection"]
    assert intersections[0] in path
