# Experiments and Future Directions

A running log of experiments and the longer-horizon directions for the
project.

## Current

### Indoor office topology

`examples/indoor_office.yaml` (12 nodes, 13 edges across two floors) is the
default test bed. It includes:

- a restricted shortcut (`corridor_main -> meeting_room` of type `restricted`)
- a stairs route (`stairs_1f <-> stairs_2f`, type `stairs_up`)
- an elevator route (`elevator_1f <-> elevator_2f`, type `elevator_connection`)

This is enough to show that semantic cost functions actually change the
chosen route:

| Cost configuration | Route |
|--------------------|-------|
| default | `entrance -> corridor_main -> meeting_room` (uses restricted shortcut) |
| `avoid_restricted` | `entrance -> corridor_main -> lobby_intersection -> meeting_room` |
| default (to 2F) | `entrance -> ... -> stairs_1f -> stairs_2f -> ... -> office_2f` |
| `avoid_stairs + prefer_elevator` | `entrance -> ... -> elevator_1f -> elevator_2f -> ... -> office_2f` |

Reproduce with `python examples/run_indoor_demo.py`.

### Heuristic admissibility

When semantic edge costs (~1.0) are much smaller than geometric distances
between node poses, the default Euclidean A* heuristic over-estimates and
A* may return suboptimal paths. Switching to Dijkstra recovers optimality.
See `docs/decisions.md` (D-7).

## Future directions

These are deliberately not in the MVP. Each is a candidate for an
experiment branch.

### Map construction

- **occupancy grid → topology graph conversion**: implemented in
  `semantic_toponav.conversion.topology_from_occupancy` via
  skeletonization + junction-cluster merging. ROS map_server YAML+PGM
  bundles can be loaded with `semantic_toponav.conversion.load_occupancy_map`
  (see `examples/load_map_demo.py`). Open follow-ups: region segmentation
  for room-aware labels, lossier graph compaction when corridors have
  many parallel skeleton branches, and door/threshold detection.
- **trajectory log → topology**: implemented in
  `semantic_toponav.conversion.topology_from_trajectories`. Greedy
  clustering + consecutive-transition edge induction; edges carry a
  ``traversal_count`` for downstream cost shaping. See
  `examples/trajectory_to_topology.py`. Open follow-ups: DBSCAN /
  k-medoids alternatives, time-aware clustering for dwell detection,
  reading trajectories from rosbag or CSV.
- VLM-based semantic labeling of map regions
- **CLIP / SigLIP embedding per node for place recognition**: the
  retrieval layer is implemented (`find_nodes_by_embedding`,
  `nearest_node_by_embedding`, `cosine_similarity`) and stores vectors
  under `node.properties["embedding"]` — encoder integration is out of
  scope and attached externally. See `examples/embedding_demo.py`.

### Planning

- **multi-floor planning with floor-aware heuristics**: implemented.
  `examples/multi_floor_office.yaml` provides a 3-floor topology and the
  planner exposes ``floor_change_penalty``, ``prefer_floor``,
  ``same_floor_only`` cost factories plus a ``floor_aware_heuristic``
  for A*. See ``examples/run_multi_floor_demo.py``.
- **dynamic graph updates** (closed corridor, busy elevator): implemented
  via the `block_edges` and `block_edge_types` cost factories plus the
  `--block-edge` / `--block-edge-type` CLI flags. The graph itself is
  not mutated, so each plan call can use a different availability set.
- preference-aware planning (shortest vs scenic vs least-crowded)
- temporal graphs (time-of-day restrictions)

### Embodied AI

- LLM-augmented waypoint instructions
- natural-language goal parsing ("meet me in the second-floor lab")
- memory graph (episodic memory of past visits)
- topology graphs as scratchpad for embodied agents

### Tooling

- web-based graph viewer/editor
- CLI graph editor with undo/diff
- visualization helpers (matplotlib/plotly)

### Integration

- custom ROS2 messages (`SemanticWaypoint.msg`, ...)
- Nav2 behavior-tree plugin
- Autoware adapter
- Foxglove panel for topology graphs
