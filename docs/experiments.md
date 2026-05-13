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

## Shipped since the MVP

Quick index of features that started life on this page and have since
landed. Each links to the still-relevant follow-up work.

- Occupancy grid → topology + ROS `map_server` loader
- Trajectory log → topology + CSV loader + rosbag2 loader
- Visit-history memory layer + embedding-based place retrieval
- Multi-floor planning (`floor_change_penalty`, `prefer_floor`,
  `same_floor_only`, `floor_aware_heuristic`)
- Dynamic edge availability (`block_edges`, `block_edge_types`)
- Custom ROS2 messages (`semantic_toponav_msgs`) alongside JSON
- Worked Nav2 example (`nav2_demo_node` bridging `SemanticWaypointArray`
  to `NavigateThroughPoses`)
- CLI graph editor (`inspect / add-node / add-edge / rm-node /
  rm-edge / undo / diff`, with automatic `.bak` snapshots on every
  in-place mutation)
- Interactive HTML viewer (`semantic-toponav viewer`, plus the
  `to_pyvis_network` / `save_interactive_html` API)
- Local live-reloading viewer (`semantic-toponav live-viewer GRAPH`
  serves a single page that polls `/mtime.json` and reloads when the
  graph file on disk changes; pairs with the CLI editor for a
  development loop)
- Three-floor end-to-end tutorial at `docs/tutorial.md`
- Hybrid occupancy + trajectory pipeline
  (`annotate_graph_with_trajectories` + post-processing helpers
  `prune_low_traversal_edges` and `promote_unmapped_transitions` —
  snap recorded runs onto a skeleton-derived graph, drop edges that
  no one used, and promote frequent transitions that had no edge into
  new candidate edges)
- v1-stable JSON Schema for `SemanticWaypointArray`
  (`docs/waypoint_schema.md`,
  `schemas/semantic_waypoint_array.schema.json`)

See `docs/decisions.md` D-10 for the original "non-goals" list with
shipped / deferred markers.

## Future directions

What's still open. Each is a candidate for an experiment branch.

### Map construction

- **occupancy grid → topology** follow-ups: region segmentation for
  room-aware labels, lossier graph compaction when corridors carry
  many parallel skeleton branches, door/threshold detection.
- **trajectory log → topology** follow-ups: DBSCAN / k-medoids cluster
  alternatives, time-aware clustering for dwell detection. The basic
  fusion of the two pipelines now ships
  (`annotate_graph_with_trajectories` plus
  `prune_low_traversal_edges` and `promote_unmapped_transitions`);
  what's still open is iterating the snap/prune/promote cycle until
  convergence and validating the result on a real recorded run.
- **VLM / CLIP labeling of regions**: the retrieval / similarity layer
  (`find_nodes_by_embedding`, `nearest_node_by_embedding`) already
  ships. What's deferred is the *encoder* integration — wiring a
  concrete CLIP / SigLIP backbone in, batching, and a region segmenter
  that decides which patches to embed per node.

### Planning

- preference-aware planning (shortest vs scenic vs least-crowded)
- temporal graphs (time-of-day restrictions, scheduled closures)
- multi-agent / shared-resource planning (one elevator, several robots)

### Embodied AI

- LLM-augmented waypoint instructions on top of the deterministic
  `path_to_semantic_waypoints` output
- natural-language goal parsing ("meet me in the second-floor lab")
- topology graphs as scratchpad for embodied agents

### Tooling

- web-based graph *editor* (the viewer ships; the editor part —
  add/remove/move nodes from a browser — does not)
- Foxglove panel for live topology + path overlays (out-of-repo, would
  live as a separate npm package consuming the v1 JSON wire format;
  the in-repo `live-viewer` covers the local dev loop today)

### Integration

- **Nav2 behavior-tree plugin** that consumes `SemanticWaypointArray`
  natively (today the included `nav2_demo_node` is a one-shot worked
  example, not a BT plugin)
- Autoware adapter
- ROS1 bridge or shim for legacy deployments
