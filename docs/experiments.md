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

- Occupancy grid → topology + ROS `map_server` loader, plus a
  post-processing door / threshold detector
  (`mark_doors_by_clearance`) that uses a distance transform of the
  binarized grid to flag narrow-passage nodes (typed `door`) and
  edges whose straight-line minimum clearance falls below an explicit
  or auto-percentile threshold, and a connected-component region
  annotator (`annotate_regions`) that labels free-space components
  with optional doorway pinching (so each pinched room becomes a
  distinct `region_id` stamped onto every node) — pairs naturally
  with the door detector for room-aware graphs. The whole pipeline
  is also reachable from the CLI without writing Python:
  `semantic-toponav from-occupancy MAP.yaml --out g.yaml`,
  `semantic-toponav mark-doors GRAPH MAP.yaml --in-place`, and
  `semantic-toponav annotate-regions GRAPH MAP.yaml --in-place` (with
  `--clearance-threshold` / `--clearance-percentile` / `--min-region-area`
  knobs and automatic `.bak` snapshots on overwrite).
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
- Deterministic, edge-aware path narration
  (`semantic-toponav describe-path GRAPH FROM TO`, plus the
  `describe_path` / `path_to_steps` API) — turns a plan into numbered
  step-by-step instructions with edge-type-aware phrasing for
  elevators / stairs / restricted edges and explicit floor-change
  call-outs. Intended as the deterministic floor under any later
  LLM-augmented instruction layer.
- Deterministic natural-language goal resolution
  (`semantic-toponav resolve GRAPH "second floor office"`, plus the
  `resolve_goal` / `GoalCandidate` API) — bag-of-words scorer with
  label/type token matches and floor-reference parsing (`2F` /
  `floor 2` / `second floor` / `2nd floor`), with deterministic
  tie-breaking. The text-only sibling of the embedding-based
  `find_nodes_by_embedding`. Intended as the offline floor under any
  later LLM resolver.
- Time-of-day edge / node restrictions
  (`time_aware(graph, at_time=...)`, plus the `--at-time HH:MM` CLI
  flag) — edges (and edges incident to closed nodes) carry an
  optional `closed_during: [[start, end], ...]` property of recurring
  HH:MM windows; intervals whose end is `<=` start wrap midnight.
  Composes with the existing `block_edges` / `prefer_elevator` /
  `floor_change_penalty` family.
- Three-floor end-to-end tutorial at `docs/tutorial.md`
- Hybrid occupancy + trajectory pipeline
  (`annotate_graph_with_trajectories` + post-processing helpers
  `prune_low_traversal_edges` and `promote_unmapped_transitions` —
  snap recorded runs onto a skeleton-derived graph, drop edges that
  no one used, and promote frequent transitions that had no edge into
  new candidate edges), plus the high-level
  `fuse_trajectories_iteratively` wrapper that loops the cycle until
  the topology is stable (with a max-iterations cap so oscillating
  thresholds can't run forever)
- v1-stable JSON Schema for `SemanticWaypointArray`
  (`docs/waypoint_schema.md`,
  `schemas/semantic_waypoint_array.schema.json`)
- Lossy graph compaction (`compact_graph`, plus the
  `semantic-toponav compact GRAPH` CLI subcommand) — merges posed
  nodes within an Euclidean tolerance into a centroid representative
  and collapses parallel duplicate edges between the same endpoints.
  Knobs: `--endpoint-tolerance METERS` for node merging,
  `--edge-cost-tolerance COST` to refuse the collapse when candidates
  differ in length, `--keep-strategy shortest|longest|first` for which
  edge survives. Targets the parallel-skeleton-branch artifact that
  `topology_from_occupancy` leaves behind in wide corridors.

See `docs/decisions.md` D-10 for the original "non-goals" list with
shipped / deferred markers.

## Future directions

What's still open. Each is a candidate for an experiment branch.

### Map construction

- **occupancy grid → topology** follow-ups: door / threshold detection
  ships (`mark_doors_by_clearance`), region segmentation for
  room-aware labels ships (`annotate_regions`, see below), and lossy
  parallel-skeleton compaction now ships (`compact_graph`, see the
  "Shipped since the MVP" entry). What's still open is more aggressive
  geometric pruning — collapsing two genuinely-parallel paths through
  a wide corridor into one rather than dedup'ing same-endpoint
  duplicates.
- **trajectory log → topology** follow-ups: DBSCAN / k-medoids cluster
  alternatives, time-aware clustering for dwell detection. The basic
  fusion of the two pipelines now ships
  (`annotate_graph_with_trajectories` plus
  `prune_low_traversal_edges` and `promote_unmapped_transitions`),
  and so does the iterative wrapper that loops snap → prune → promote
  to convergence (`fuse_trajectories_iteratively`, returning an
  :class:`IterativeFusionResult` with per-iteration history and a
  converged flag, oscillation-safe via `max_iterations`). What's
  still open is validating the result on a real recorded run.
- **VLM / CLIP labeling of regions**: the retrieval / similarity layer
  (`find_nodes_by_embedding`, `nearest_node_by_embedding`) already
  ships. What's deferred is the *encoder* integration — wiring a
  concrete CLIP / SigLIP backbone in, batching, and a region segmenter
  that decides which patches to embed per node.

### Planning

- preference-aware planning (shortest vs scenic vs least-crowded)
- temporal graphs — recurring HH:MM-window restrictions ship
  (`time_aware` + `--at-time`); what's still open is date-aware /
  calendar-aware scheduling (holidays, specific dates) and
  agent-routing under joint time + resource constraints.
- multi-agent / shared-resource planning (one elevator, several robots)

### Embodied AI

- LLM-augmented waypoint instructions on top of the deterministic
  `describe_path` output (the deterministic narration ships; the LLM
  rewriting layer that would consume those steps does not)
- natural-language goal parsing — a deterministic resolver ships
  (`resolve_goal` + `semantic-toponav resolve`). What's deferred is
  the LLM layer that would take *its* top-k candidates plus the
  user's full utterance and disambiguate / refine the choice.
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
