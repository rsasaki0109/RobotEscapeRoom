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

## Robot Escape Room MCAP

`robot_escape_room_demo.mcap` replays the full puzzle loop — every route is a
live A* plan over the escape-room cost stack (no scripted path).

```bash
pip install -e '.[foxglove]'
PYTHONPATH=. python3 examples/export_escape_room_foxglove_mcap.py
scripts/foxglove_hero/build_escape_room_gif.sh
```

| Topic | Schema | Purpose |
|---|---|---|
| `/semantic_toponav/escape_room/status` | `semantic_toponav.EscapeRoomStatus` | Turn caption + puzzle events (matches README hero subtitles) |
| `/semantic_toponav/scene` | `foxglove.SceneUpdate` | Furnished interior cubes + route + robot marker |
| `/semantic_toponav/waypoints` | `semantic_toponav.WaypointArray` | Semantic waypoints per frame |

Open `docs/foxglove/robot_escape_room_demo.mcap` in Foxglove Studio and add
the **Semantic TopoNav Escape Room** panel from
[`semantic-toponav-foxglove-panel`](https://github.com/rsasaki0109/semantic-toponav-foxglove-panel)
(v0.4.0+) to read turn captions and puzzle events beside the 3D scene.
Alternatively, add a Raw Messages panel on
`/semantic_toponav/escape_room/status` to read turn narrative alongside
the 3D scene.
