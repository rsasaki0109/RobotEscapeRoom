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

- occupancy grid → topology graph conversion (skeletonization, region
  segmentation)
- trajectory log → topology graph (cluster waypoints, merge revisits)
- VLM-based semantic labeling of map regions
- CLIP embedding per node for place recognition

### Planning

- multi-floor planning with floor-aware heuristics
- dynamic graph updates (closed corridor, busy elevator)
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
