"""Tests for occupancy grid -> topology graph conversion.

Skipped when NumPy or scikit-image are not installed.
"""

from __future__ import annotations

import math

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("skimage")

pytest.importorskip("scipy")

from semantic_toponav.conversion.occupancy import (
    annotate_regions,
    mark_doors_by_clearance,
    topology_from_occupancy,
)
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


# --------------------------- mark_doors_by_clearance ---------------------------


def _two_rooms_with_doorway() -> tuple[np.ndarray, float]:
    """Two 7x7 rooms connected by a 1-cell-wide 5-cell-long doorway."""
    h, w = 13, 21
    grid = np.zeros((h, w), dtype=bool)
    grid[2:9, 1:8] = True    # left room
    grid[2:9, 13:20] = True  # right room
    grid[5, 8:13] = True     # narrow doorway
    return grid, 1.0


def test_door_detection_marks_edge_through_narrow_passage() -> None:
    grid, resolution = _two_rooms_with_doorway()
    g = topology_from_occupancy(grid, resolution=resolution)
    out = mark_doors_by_clearance(
        g, grid, resolution=resolution, clearance_threshold=1.5
    )
    # The single edge between the two endpoints goes through the doorway.
    assert out.edge_ids, "expected the doorway edge to be flagged"
    for eid in out.edge_ids:
        assert g.get_edge(eid).type == "door"
        # The recorded min_clearance is the doorway's clearance (~1.0m).
        assert g.get_edge(eid).properties["min_clearance"] < 1.5


def test_door_detection_records_min_clearance_property() -> None:
    grid, resolution = _two_rooms_with_doorway()
    g = topology_from_occupancy(grid, resolution=resolution)
    mark_doors_by_clearance(g, grid, resolution=resolution)
    # Every node with row/col gets a min_clearance entry.
    for n in g.nodes():
        if "row" in n.properties and "col" in n.properties:
            assert "min_clearance" in n.properties
            assert n.properties["min_clearance"] >= 0.0
    # Every edge with both endpoints posed gets one too.
    for e in g.edges():
        assert "min_clearance" in e.properties


def test_door_detection_explicit_threshold_loose_flags_everything() -> None:
    grid, resolution = _two_rooms_with_doorway()
    g = topology_from_occupancy(grid, resolution=resolution)
    out = mark_doors_by_clearance(
        g, grid, resolution=resolution, clearance_threshold=100.0
    )
    # With a ludicrously loose threshold every node-with-cells and every
    # edge gets flagged.
    nodes_with_cells = [n for n in g.nodes() if "row" in n.properties]
    assert len(out.node_ids) == len(nodes_with_cells)
    assert len(out.edge_ids) == len(g.edge_ids())


def test_door_detection_strict_threshold_returns_empty() -> None:
    grid, resolution = _two_rooms_with_doorway()
    g = topology_from_occupancy(grid, resolution=resolution)
    out = mark_doors_by_clearance(
        g, grid, resolution=resolution, clearance_threshold=0.0
    )
    assert out.node_ids == []
    assert out.edge_ids == []


def test_door_detection_skips_nodes_without_cell_properties() -> None:
    grid, resolution = _two_rooms_with_doorway()
    g = topology_from_occupancy(grid, resolution=resolution)
    target = next(iter(g.node_ids()))
    g.get_node(target).properties.pop("row", None)
    g.get_node(target).properties.pop("col", None)
    out = mark_doors_by_clearance(g, grid, resolution=resolution)
    # The stripped node must not appear in node_ids and must not get a
    # node-level clearance recorded.
    assert target not in out.node_ids
    assert "min_clearance" not in g.get_node(target).properties


def test_door_detection_empty_grid_returns_empty() -> None:
    grid = np.zeros((10, 10), dtype=bool)
    g = topology_from_occupancy(grid)
    out = mark_doors_by_clearance(g, grid, resolution=1.0)
    assert out.node_ids == []
    assert out.edge_ids == []
    assert g.node_ids() == []


def test_door_detection_mark_edges_false_skips_edge_marking() -> None:
    grid, resolution = _two_rooms_with_doorway()
    g = topology_from_occupancy(grid, resolution=resolution)
    out = mark_doors_by_clearance(
        g, grid, resolution=resolution, mark_edges=False, clearance_threshold=1.5
    )
    assert out.edge_ids == []
    # Edges still don't carry a min_clearance entry when sampling is skipped.
    for e in g.edges():
        assert "min_clearance" not in e.properties


def test_door_detection_resolution_scales_clearance() -> None:
    grid, resolution = _two_rooms_with_doorway()
    g_coarse = topology_from_occupancy(grid, resolution=1.0)
    g_fine = topology_from_occupancy(grid, resolution=0.1)
    coarse = mark_doors_by_clearance(
        g_coarse, grid, resolution=1.0, clearance_threshold=1.0
    )
    fine = mark_doors_by_clearance(
        g_fine, grid, resolution=0.1, clearance_threshold=1.0
    )
    # At the finer resolution, clearance values (in meters) are 10x
    # smaller so a 1.0 m threshold flags many more edges/nodes.
    assert (len(coarse.node_ids) + len(coarse.edge_ids)) <= (
        len(fine.node_ids) + len(fine.edge_ids)
    )


def test_door_detection_auto_threshold_marks_a_subset() -> None:
    grid, resolution = _two_rooms_with_doorway()
    g = topology_from_occupancy(grid, resolution=resolution)
    out = mark_doors_by_clearance(g, grid, resolution=resolution)
    total = sum(1 for _ in g.nodes()) + sum(1 for _ in g.edges())
    flagged = len(out.node_ids) + len(out.edge_ids)
    assert 0 < flagged <= total


# ------------------------------ annotate_regions ------------------------------


def _empty_graph():
    from semantic_toponav.graph.topology_graph import TopologyGraph
    return TopologyGraph()


def test_regions_single_room_one_region() -> None:
    grid = np.zeros((9, 11), dtype=bool)
    grid[2:7, 2:9] = True
    g = topology_from_occupancy(grid, resolution=1.0)
    out = annotate_regions(g, grid, resolution=1.0)
    assert len(out.regions) == 1
    (rid,) = out.regions.keys()
    assert out.regions[rid].area_cells == 5 * 7
    assert math.isclose(out.regions[rid].area_m2, 35.0)


def test_regions_empty_grid_returns_empty() -> None:
    grid = np.zeros((6, 6), dtype=bool)
    g = topology_from_occupancy(grid)
    out = annotate_regions(g, grid, resolution=1.0)
    assert out.regions == {}
    assert out.node_ids == []
    assert out.doorway_node_ids == []


def test_regions_two_disconnected_rooms_yield_two_regions() -> None:
    grid = np.zeros((11, 21), dtype=bool)
    grid[2:9, 1:8] = True   # left room
    grid[2:9, 13:20] = True  # right room (no doorway)
    g = topology_from_occupancy(grid, resolution=1.0)
    out = annotate_regions(g, grid, resolution=1.0)
    assert len(out.regions) == 2
    # Each room is 7x7 = 49 cells.
    assert {r.area_cells for r in out.regions.values()} == {49}


def test_regions_pinching_separates_two_rooms_through_doorway() -> None:
    grid, resolution = _two_rooms_with_doorway()
    g = topology_from_occupancy(grid, resolution=resolution)
    out = annotate_regions(
        g, grid, resolution=resolution, clearance_threshold=1.5
    )
    # Without pinching the doorway connects both rooms → 1 region.
    # With a 1.5 m threshold the 1-cell-wide passage (clearance ~1.0)
    # is pinched off, so we get the two rooms as separate regions.
    assert len(out.regions) == 2


def test_regions_without_pinching_yields_single_region() -> None:
    grid, resolution = _two_rooms_with_doorway()
    g = topology_from_occupancy(grid, resolution=resolution)
    out = annotate_regions(g, grid, resolution=resolution)
    # No pinching → corridor connects both rooms.
    assert len(out.regions) == 1


def test_regions_stamps_region_id_on_graph_nodes() -> None:
    grid = np.zeros((11, 21), dtype=bool)
    grid[2:9, 1:8] = True
    grid[2:9, 13:20] = True
    g = topology_from_occupancy(grid, resolution=1.0)
    out = annotate_regions(g, grid, resolution=1.0)
    nodes_with_cells = [n for n in g.nodes() if "row" in n.properties]
    assert nodes_with_cells, "expected nodes derived from cells"
    for node in nodes_with_cells:
        if node.id in out.node_ids:
            assert node.properties["region_id"] in out.regions


def test_regions_nodes_in_pinched_doorway_become_doorways() -> None:
    grid, resolution = _two_rooms_with_doorway()
    g = topology_from_occupancy(grid, resolution=resolution)
    out = annotate_regions(
        g, grid, resolution=resolution, clearance_threshold=1.5
    )
    # The narrow doorway gets pinched out. Endpoint nodes sit in the
    # rooms (so they end up in regions); any node that happens to land
    # on a pinched cell would go to doorway_node_ids.
    assert len(out.regions) == 2
    for node_id in out.doorway_node_ids:
        assert "region_id" not in g.get_node(node_id).properties


def test_regions_min_area_filters_noise() -> None:
    grid = np.zeros((9, 14), dtype=bool)
    grid[2:7, 2:6] = True  # 5x4 = 20-cell room
    grid[5, 9] = True      # single-cell speck
    out = annotate_regions(
        _empty_graph(), grid, resolution=1.0, min_region_area=2
    )
    assert len(out.regions) == 1
    (info,) = out.regions.values()
    assert info.area_cells == 20


def test_regions_resolution_scales_area() -> None:
    grid = np.zeros((8, 8), dtype=bool)
    grid[2:6, 2:6] = True  # 4x4 cells
    out_fine = annotate_regions(
        _empty_graph(), grid, resolution=0.5
    )
    (info,) = out_fine.regions.values()
    assert math.isclose(info.area_m2, 16 * 0.25)


def test_regions_centroid_within_bbox() -> None:
    grid = np.zeros((9, 11), dtype=bool)
    grid[2:7, 2:9] = True
    out = annotate_regions(
        _empty_graph(), grid, resolution=1.0
    )
    (info,) = out.regions.values()
    rmin, cmin, rmax, cmax = info.bbox_cells
    assert rmin == 2 and cmin == 2
    assert rmax == 6 and cmax == 8
    # centroid lives somewhere within the bbox in world coords
    cx, cy = info.centroid_world
    assert 2.0 <= cx <= 9.0
    assert 2.0 <= cy <= 7.0


def test_regions_auto_threshold_from_percentile() -> None:
    grid, resolution = _two_rooms_with_doorway()
    g = topology_from_occupancy(grid, resolution=resolution)
    out = annotate_regions(
        g, grid, resolution=resolution, clearance_percentile=50.0
    )
    # The 50th percentile of free-cell clearance lands well above the
    # 1.0 m doorway clearance, so pinching kicks in and gives 2 rooms.
    assert len(out.regions) == 2
