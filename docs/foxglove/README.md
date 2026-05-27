# Foxglove Replay

`semantic_toponav_demo.mcap` is a local Foxglove Studio replay generated
from the shipped `examples/multi_floor_office.yaml` graph and real
semantic-toponav calls:

- `resolve_goal("executive office on 3F")`
- `plan_astar(..., compose_costs(prefer_elevator))`
- `path_to_semantic_waypoints(...)`

## Open

1. Install Foxglove Studio.
2. Open `docs/foxglove/semantic_toponav_demo.mcap`.
3. Add a 3D panel and use `map` as the fixed frame.
4. Add Raw Messages panels for the semantic topics if you want to inspect
   planner state alongside the 3D scene.

## Topics

| Topic | Schema | Purpose |
|---|---|---|
| `/semantic_toponav/scene` | `foxglove.SceneUpdate` | Static topology, floor outlines, route, robot marker |
| `/semantic_toponav/markers` | `visualization_msgs/MarkerArray` | Foxglove 3D-panel-compatible route, node, floor, and robot markers |
| `/tf` | `foxglove.FrameTransforms` | `map -> base_link` transform stream |
| `/semantic_toponav/pose` | `foxglove.PoseInFrame` | Robot pose in the map frame |
| `/semantic_toponav/resolve_trace` | `semantic_toponav.ResolveTrace` | Query grounding candidates and reasons |
| `/semantic_toponav/route` | `semantic_toponav.Route` | Planned route over node ids |
| `/semantic_toponav/waypoints` | `semantic_toponav.WaypointArray` | Generated semantic waypoints and current index |
| `/semantic_toponav/admission` | `semantic_toponav.Admission` | Demo reservation/admission result |

## Regenerate

```bash
pip install -e '.[foxglove]'
python examples/export_foxglove_mcap.py
```

The README GIF is recorded from a Foxglove Studio replay of this MCAP.
