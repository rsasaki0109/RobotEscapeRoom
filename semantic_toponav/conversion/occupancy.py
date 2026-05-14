"""Convert a 2D occupancy grid into a TopologyGraph.

Algorithm:

1. Binarize the input grid using ``free_threshold``.
2. Skeletonize the free space (one-pixel-thick medial axis).
3. Classify skeleton pixels by 8-neighborhood degree:

   - degree == 1 -> endpoint (graph node, default type ``endpoint``)
   - degree >= 3 -> junction (graph node, default type ``intersection``)
   - degree == 2 -> interior (lives inside an edge, not a node)

4. Cluster adjacent endpoint/junction pixels with 8-connectivity. Each
   connected component becomes **one** node located at the cluster's
   centroid (snapped to a cluster pixel). This avoids the "many tiny nodes
   per intersection" artifact that raw skeletonization produces.
5. Trace skeleton paths between clusters; emit one edge per traced segment,
   with cost equal to the segment's pixel-step length scaled by
   ``resolution``.

The function follows the ROS map convention by default: image row 0 is the
*top* of the grid, world ``y`` points *up*, and ``origin`` denotes the world
position of the bottom-left cell.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode


@dataclass
class DoorDetectionResult:
    """Summary returned by :func:`mark_doors_by_clearance`."""

    node_ids: list[str] = field(default_factory=list)
    edge_ids: list[str] = field(default_factory=list)


@dataclass
class RegionInfo:
    """Per-region metadata returned by :func:`annotate_regions`."""

    region_id: int
    area_cells: int
    area_m2: float
    centroid_world: tuple[float, float]
    bbox_cells: tuple[int, int, int, int]


@dataclass
class RegionAnnotationResult:
    """Summary returned by :func:`annotate_regions`."""

    regions: dict[int, RegionInfo] = field(default_factory=dict)
    node_ids: list[str] = field(default_factory=list)
    doorway_node_ids: list[str] = field(default_factory=list)

_NEIGHBOR_OFFSETS = [
    (dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy, dx) != (0, 0)
]


def _cell_to_world(
    row: int,
    col: int,
    *,
    height: int,
    resolution: float,
    origin: tuple[float, float],
) -> tuple[float, float]:
    x = origin[0] + (col + 0.5) * resolution
    y = origin[1] + (height - 1 - row + 0.5) * resolution
    return x, y


def _binarize(grid: Any, free_threshold: float):
    import numpy as np

    arr = np.asarray(grid)
    if arr.ndim != 2:
        raise ValueError(f"occupancy grid must be 2D, got shape {arr.shape}")
    if arr.dtype == bool:
        return arr.copy()
    return arr >= free_threshold


def _count_skeleton_neighbors(skel):
    import numpy as np

    s = skel.astype(np.int32)
    h, w = s.shape
    total = np.zeros_like(s)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            shifted = np.zeros_like(s)
            dst_y = slice(max(0, dy), h + min(0, dy))
            dst_x = slice(max(0, dx), w + min(0, dx))
            src_y = slice(max(0, -dy), h + min(0, -dy))
            src_x = slice(max(0, -dx), w + min(0, -dx))
            shifted[dst_y, dst_x] = s[src_y, src_x]
            total += shifted
    return total * s


def _cluster_node_pixels(node_mask, counts):
    """Label connected components of node pixels and pick a representative each.

    Returns ``(cluster_labels, cluster_info)``:
      - ``cluster_labels``: int array, 0 where no node, positive cluster id otherwise
      - ``cluster_info``: dict ``cluster_id -> {"rep": (row, col), "is_junction": bool}``
    """
    import numpy as np
    from skimage.measure import label

    cluster_labels = label(node_mask.astype(np.uint8), connectivity=2)
    info: dict[int, dict[str, Any]] = {}
    for cid in range(1, int(cluster_labels.max()) + 1):
        pixels = np.argwhere(cluster_labels == cid)
        if pixels.size == 0:
            continue
        cy, cx = pixels.mean(axis=0)
        cy_r, cx_r = int(round(cy)), int(round(cx))
        # Snap to an actual cluster pixel near the centroid.
        if not (
            0 <= cy_r < cluster_labels.shape[0]
            and 0 <= cx_r < cluster_labels.shape[1]
            and cluster_labels[cy_r, cx_r] == cid
        ):
            cy_r, cx_r = int(pixels[0][0]), int(pixels[0][1])
        is_junction = bool((counts[pixels[:, 0], pixels[:, 1]] >= 3).any())
        info[int(cid)] = {"rep": (cy_r, cx_r), "is_junction": is_junction}
    return cluster_labels, info


def _trace_segments(skel, cluster_labels) -> list[tuple[int, int, list[tuple[int, int]]]]:
    """Trace skeleton paths between distinct clusters.

    Returns a list of ``(start_cluster_id, end_cluster_id, pixel_sequence)``
    triples. Each pixel sequence begins at a pixel inside the start cluster
    and ends at a pixel inside the end cluster. Self-loops (cycle returning
    to the same cluster) are dropped.
    """
    import numpy as np

    h, w = skel.shape
    visited_first_step: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    segments: list[tuple[int, int, list[tuple[int, int]]]] = []

    cluster_pixels = np.argwhere(cluster_labels > 0)
    for cy, cx in cluster_pixels:
        cid = int(cluster_labels[cy, cx])
        cy_i, cx_i = int(cy), int(cx)
        for dy, dx in _NEIGHBOR_OFFSETS:
            ny, nx = cy_i + dy, cx_i + dx
            if not (0 <= ny < h and 0 <= nx < w):
                continue
            if not skel[ny, nx]:
                continue
            if int(cluster_labels[ny, nx]) == cid:
                continue  # stay-in-cluster step
            step_key = ((cy_i, cx_i), (ny, nx))
            if step_key in visited_first_step:
                continue

            segment = [(cy_i, cx_i), (ny, nx)]
            prev = (cy_i, cx_i)
            cur = (ny, nx)

            while int(cluster_labels[cur[0], cur[1]]) == 0:
                next_pixel = None
                for dy2, dx2 in _NEIGHBOR_OFFSETS:
                    cand = (cur[0] + dy2, cur[1] + dx2)
                    if not (0 <= cand[0] < h and 0 <= cand[1] < w):
                        continue
                    if not skel[cand[0], cand[1]]:
                        continue
                    if cand == prev:
                        continue
                    next_pixel = cand
                    break
                if next_pixel is None:
                    break
                prev = cur
                cur = next_pixel
                segment.append(cur)

            end_cid = int(cluster_labels[cur[0], cur[1]])
            if end_cid == 0 or end_cid == cid:
                # Hit a dead-end or looped back to the same cluster — skip.
                continue

            visited_first_step.add(((cy_i, cx_i), (ny, nx)))
            visited_first_step.add(((cur[0], cur[1]), segment[-2]))
            segments.append((cid, end_cid, segment))

    return segments


def _segment_length(segment: list[tuple[int, int]], resolution: float) -> float:
    total = 0.0
    for (y0, x0), (y1, x1) in zip(segment, segment[1:], strict=False):
        total += math.hypot(y1 - y0, x1 - x0)
    return total * resolution


def topology_from_occupancy(
    grid: Any,
    *,
    resolution: float = 1.0,
    origin: tuple[float, float] = (0.0, 0.0),
    free_threshold: float = 0.5,
    endpoint_type: str = "endpoint",
    junction_type: str = "intersection",
    edge_type: str = "corridor",
    id_prefix: str = "",
    frame_id: str = "map",
) -> TopologyGraph:
    """Build a TopologyGraph from a 2D occupancy grid.

    Parameters follow common ROS map conventions: ``origin`` is the world
    position of the bottom-left cell and ``resolution`` is the cell size in
    meters. When the grid is not boolean, values ``>= free_threshold`` are
    treated as traversable.

    Requires NumPy and scikit-image. Install with
    ``pip install 'semantic-toponav[map]'``.
    """
    try:
        from skimage.morphology import skeletonize
    except ImportError as exc:
        raise ImportError(
            "topology_from_occupancy requires scikit-image. Install with "
            "`pip install 'semantic-toponav[map]'`"
        ) from exc

    free = _binarize(grid, free_threshold)
    skel = skeletonize(free)
    counts = _count_skeleton_neighbors(skel)
    node_mask = ((counts == 1) | (counts >= 3)) & skel
    cluster_labels, cluster_info = _cluster_node_pixels(node_mask, counts)

    h, _w = skel.shape
    graph = TopologyGraph()
    cluster_node_id: dict[int, str] = {}

    for cid, meta in cluster_info.items():
        ry, rx = meta["rep"]
        node_type = junction_type if meta["is_junction"] else endpoint_type
        node_id = f"{id_prefix}n_{ry}_{rx}"
        x, y = _cell_to_world(
            ry, rx, height=h, resolution=resolution, origin=origin
        )
        graph.add_node(
            TopologyNode(
                id=node_id,
                label=node_id,
                type=node_type,
                pose=Pose2D(x=x, y=y, yaw=0.0, frame_id=frame_id),
                properties={"row": ry, "col": rx, "cluster_id": cid},
            )
        )
        cluster_node_id[cid] = node_id

    for start_cid, end_cid, segment in _trace_segments(skel, cluster_labels):
        source = cluster_node_id[start_cid]
        target = cluster_node_id[end_cid]
        # Sort source/target to make duplicate detection symmetric for
        # bidirectional edges (so two segments between the same pair don't
        # collide on id but also don't get mistaken for one).
        cost = _segment_length(segment, resolution)
        edge_id = f"{id_prefix}e_c{start_cid}_c{end_cid}"
        if graph.has_edge(edge_id) or graph.has_edge(
            f"{id_prefix}e_c{end_cid}_c{start_cid}"
        ):
            suffix = 2
            while graph.has_edge(f"{edge_id}_v{suffix}"):
                suffix += 1
            edge_id = f"{edge_id}_v{suffix}"
        graph.add_edge(
            TopologyEdge(
                id=edge_id,
                source=source,
                target=target,
                type=edge_type,
                cost=cost,
                bidirectional=True,
                properties={"pixel_length": len(segment)},
            )
        )

    return graph


def _world_to_cell(
    x: float,
    y: float,
    *,
    height: int,
    resolution: float,
    origin: tuple[float, float],
) -> tuple[int, int]:
    """Inverse of :func:`_cell_to_world` (round to nearest cell)."""
    col = int(round((x - origin[0]) / resolution - 0.5))
    row = int(round(height - 0.5 - (y - origin[1]) / resolution))
    return row, col


def mark_doors_by_clearance(
    graph: TopologyGraph,
    grid: Any,
    *,
    resolution: float = 1.0,
    origin: tuple[float, float] = (0.0, 0.0),
    free_threshold: float = 0.5,
    clearance_threshold: float | None = None,
    clearance_percentile: float = 30.0,
    door_node_type: str = "door",
    door_edge_type: str = "door",
    clearance_property: str = "min_clearance",
    mark_edges: bool = True,
    edge_samples: int = 32,
    row_property: str = "row",
    col_property: str = "col",
) -> DoorDetectionResult:
    """Re-type narrow-passage nodes and edges as doors based on clearance.

    Workflow:

    1. Binarize ``grid`` and compute a Euclidean distance transform —
       each free cell's distance to the nearest non-free cell, in meters
       (cells \\* ``resolution``).
    2. For every node carrying ``row`` and ``col`` properties (stamped by
       :func:`topology_from_occupancy`), look up its clearance and record
       it under ``properties[clearance_property]``.
    3. For every edge whose endpoints both have poses, sample
       ``edge_samples`` points along the straight line between them in
       world coordinates, look up the clearance at each, and take the
       minimum. Record it under ``properties[clearance_property]``.
    4. Resolve ``clearance_threshold`` (use it directly if given,
       otherwise auto-pick the ``clearance_percentile`` of the combined
       node + edge clearance distribution).
    5. Nodes with clearance strictly below the threshold get their
       ``type`` changed to ``door_node_type``; edges (when ``mark_edges``
       is ``True``) get ``door_edge_type``.

    The straight-line sample approximates the underlying skeleton path,
    which is reasonable for short edges. For long curved corridors, an
    edge's minimum clearance may understate the truly traversable width
    — treat the auto-threshold output as a *candidate* set and tune
    ``clearance_threshold`` for production graphs.

    Requires NumPy and SciPy (transitively available with the
    ``[map]`` extra). Mutates the graph in place.
    """
    try:
        import numpy as np
        from scipy.ndimage import distance_transform_edt
    except ImportError as exc:
        raise ImportError(
            "mark_doors_by_clearance requires numpy and scipy. Install with "
            "`pip install 'semantic-toponav[map]'`"
        ) from exc

    free = _binarize(grid, free_threshold)
    if free.ndim != 2:
        raise ValueError(f"grid must be 2D, got shape {free.shape}")
    result = DoorDetectionResult()
    if not free.any():
        return result

    clearance_cells = distance_transform_edt(free)
    h, w = free.shape

    def _clearance_at(ry: int, rx: int) -> float:
        if 0 <= ry < h and 0 <= rx < w:
            return float(clearance_cells[ry, rx]) * resolution
        return 0.0

    node_clearance: dict[str, float] = {}
    for node in graph.nodes():
        ry = node.properties.get(row_property)
        rx = node.properties.get(col_property)
        if isinstance(ry, int) and isinstance(rx, int):
            c = _clearance_at(ry, rx)
            node_clearance[node.id] = c
            node.properties[clearance_property] = c

    edge_clearance: dict[str, float] = {}
    if mark_edges and edge_samples >= 2:
        for edge in graph.edges():
            src = graph.get_node(edge.source).pose
            tgt = graph.get_node(edge.target).pose
            if src is None or tgt is None:
                continue
            min_c = math.inf
            for i in range(edge_samples):
                t = i / (edge_samples - 1)
                x = src.x + (tgt.x - src.x) * t
                y = src.y + (tgt.y - src.y) * t
                ry, rx = _world_to_cell(
                    x, y, height=h, resolution=resolution, origin=origin
                )
                c = _clearance_at(ry, rx)
                if c < min_c:
                    min_c = c
            if math.isinf(min_c):
                continue
            edge_clearance[edge.id] = min_c
            edge.properties[clearance_property] = min_c

    samples: list[float] = list(node_clearance.values()) + list(edge_clearance.values())
    if not samples:
        return result

    if clearance_threshold is None:
        threshold = float(np.percentile(np.asarray(samples, dtype=float), clearance_percentile))
    else:
        threshold = float(clearance_threshold)

    for node_id, c in node_clearance.items():
        if c < threshold:
            graph.get_node(node_id).type = door_node_type
            result.node_ids.append(node_id)

    for edge_id, c in edge_clearance.items():
        if c < threshold:
            graph.get_edge(edge_id).type = door_edge_type
            result.edge_ids.append(edge_id)

    return result


def annotate_regions(
    graph: TopologyGraph,
    grid: Any,
    *,
    resolution: float = 1.0,
    origin: tuple[float, float] = (0.0, 0.0),
    free_threshold: float = 0.5,
    clearance_threshold: float | None = None,
    clearance_percentile: float | None = None,
    min_region_area: int = 0,
    region_property: str = "region_id",
    row_property: str = "row",
    col_property: str = "col",
) -> RegionAnnotationResult:
    """Stamp connected-component region ids onto graph nodes.

    Workflow:

    1. Binarize ``grid`` with ``free_threshold``.
    2. Optionally pinch off narrow passages: when ``clearance_threshold``
       (or ``clearance_percentile`` for an auto value) is supplied, cells
       whose Euclidean clearance to the nearest wall is below the
       threshold are treated as walls, so rooms separated by doorways
       become distinct components.
    3. Label the remaining free mask with 4-connectivity. Components
       smaller than ``min_region_area`` cells are dropped as noise.
    4. For every node carrying ``row`` and ``col`` properties, look up
       the region id at that cell and write it under
       ``properties[region_property]``. Nodes whose cell falls inside a
       pinched-off doorway (no region) are recorded in
       ``doorway_node_ids`` and do **not** get a region id stamped.

    The integer region ids are 1-based and stable for a given input
    grid (consecutive ids from the underlying labeler). The walls in the
    label array are 0 and never appear in :attr:`regions`.

    Requires NumPy and scikit-image (and SciPy when clearance pinching
    is enabled). Mutates the graph in place.
    """
    try:
        import numpy as np
        from skimage.measure import label, regionprops
    except ImportError as exc:
        raise ImportError(
            "annotate_regions requires numpy and scikit-image. Install with "
            "`pip install 'semantic-toponav[map]'`"
        ) from exc

    free = _binarize(grid, free_threshold)
    if free.ndim != 2:
        raise ValueError(f"grid must be 2D, got shape {free.shape}")
    result = RegionAnnotationResult()
    if not free.any():
        return result

    h, w = free.shape

    mask = free
    if clearance_threshold is not None or clearance_percentile is not None:
        try:
            from scipy.ndimage import distance_transform_edt
        except ImportError as exc:
            raise ImportError(
                "annotate_regions with clearance pinching requires scipy. "
                "Install with `pip install 'semantic-toponav[map]'`"
            ) from exc
        clearance_cells = distance_transform_edt(free)
        clearance_m = clearance_cells * resolution
        if clearance_threshold is None:
            free_values = clearance_m[free]
            threshold = float(
                np.percentile(free_values, float(clearance_percentile))
            )
        else:
            threshold = float(clearance_threshold)
        mask = free & (clearance_m >= threshold)

    labels = label(mask.astype(np.uint8), connectivity=1)

    keep_ids: dict[int, int] = {}
    next_id = 1
    for props in regionprops(labels):
        if props.area < min_region_area:
            continue
        keep_ids[int(props.label)] = next_id
        cy, cx = props.centroid
        wx, wy = _cell_to_world(
            int(round(cy)), int(round(cx)),
            height=h, resolution=resolution, origin=origin,
        )
        minr, minc, maxr, maxc = props.bbox
        result.regions[next_id] = RegionInfo(
            region_id=next_id,
            area_cells=int(props.area),
            area_m2=float(props.area) * resolution * resolution,
            centroid_world=(wx, wy),
            bbox_cells=(int(minr), int(minc), int(maxr) - 1, int(maxc) - 1),
        )
        next_id += 1

    for node in graph.nodes():
        ry = node.properties.get(row_property)
        rx = node.properties.get(col_property)
        if not (isinstance(ry, int) and isinstance(rx, int)):
            continue
        if not (0 <= ry < h and 0 <= rx < w):
            continue
        raw = int(labels[ry, rx])
        mapped = keep_ids.get(raw, 0) if raw > 0 else 0
        if mapped == 0:
            result.doorway_node_ids.append(node.id)
            continue
        node.properties[region_property] = mapped
        result.node_ids.append(node.id)

    return result
