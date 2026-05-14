# SemanticWaypointArray wire format (v1, stable)

This page documents the JSON wire format produced by
`waypoint_publisher_node` when `output_format` is `json` (the default).
The same payload is what `SemanticWaypoint.to_dict()` plus the surrounding
`path` list produce in pure Python — making consumers in either language
trivial.

The matching JSON Schema (Draft 2020-12) lives at
[`schemas/semantic_waypoint_array.schema.json`](../schemas/semantic_waypoint_array.schema.json).

> **Stability.** This wire format is marked **v1** and considered
> stable. Breaking changes will bump the `$id` to a new version path
> (e.g. `v2.json`) and ship alongside the existing v1 endpoint for at
> least one release. Additive changes (new optional fields, new
> `action` strings) may land in v1 — consumers should ignore unknown
> fields and accept unknown action values rather than rejecting them.

## Top-level shape

```json
{
  "path": ["entrance", "corridor_main", "meeting_room"],
  "waypoints": [
    { "node_id": "entrance",       /* ... */ },
    { "node_id": "corridor_main",  /* ... */ },
    { "node_id": "meeting_room",   /* ... */ }
  ]
}
```

- `path` — the ordered list of node ids the planner produced. Same
  length as `waypoints`. Consumers that only need ids can ignore the
  rest of the payload.
- `waypoints` — one fully-decorated waypoint per node in `path`, in
  the same order.

## SemanticWaypoint

| Field         | Type           | Required | Notes                                                                 |
|---------------|----------------|----------|-----------------------------------------------------------------------|
| `node_id`     | string         | yes      | Identifier of the source node.                                        |
| `node_label`  | string         | yes      | Human-readable label of the source node.                              |
| `node_type`   | string         | yes      | Semantic type (free-form: `room`, `corridor`, `elevator`, ...).       |
| `action`      | string         | yes      | One of the built-in actions; see below.                               |
| `instruction` | string         | yes      | Single-sentence directive for this waypoint.                          |
| `pose`        | object         | no       | Present only when the source node has a `pose`. See below.            |
| `properties`  | object         | yes      | Arbitrary JSON values copied from the source node's `properties`.     |

### `action` vocabulary

The deterministic generator emits one of:

`start` · `arrive` · `enter` · `proceed_through` · `navigate` ·
`take_elevator` · `use_stairs` · `pass_through`

The first waypoint is always `start` and the last is always `arrive`;
intermediates are picked by node type, falling back to `pass_through`.

**Forward compatibility:** consumers SHOULD accept unknown action
strings and either ignore them or fall back to a default behavior.
The vocabulary may grow in v1 minor revisions.

### `pose`

Optional. Mirrors `Pose2D`:

| Field      | Type   | Required | Notes                          |
|------------|--------|----------|--------------------------------|
| `x`        | number | yes      | Meters.                        |
| `y`        | number | yes      | Meters.                        |
| `yaw`      | number | yes      | Radians.                       |
| `frame_id` | string | yes      | Coordinate frame, default `"map"`. |

## Worked example

```json
{
  "path": ["entrance", "corridor_main", "meeting_room"],
  "waypoints": [
    {
      "node_id": "entrance",
      "node_label": "Entrance",
      "node_type": "entrance",
      "action": "start",
      "instruction": "Start at Entrance",
      "pose": { "x": 0.0, "y": 0.0, "yaw": 0.0, "frame_id": "map" },
      "properties": { "floor": 1 }
    },
    {
      "node_id": "corridor_main",
      "node_label": "Main Corridor",
      "node_type": "corridor",
      "action": "proceed_through",
      "instruction": "Proceed through Main Corridor",
      "pose": { "x": 4.0, "y": 0.0, "yaw": 0.0, "frame_id": "map" },
      "properties": { "floor": 1 }
    },
    {
      "node_id": "meeting_room",
      "node_label": "Meeting Room",
      "node_type": "room",
      "action": "arrive",
      "instruction": "Arrive at Meeting Room",
      "pose": { "x": 6.0, "y": 2.0, "yaw": 0.0, "frame_id": "map" },
      "properties": { "floor": 1, "capacity": 12 }
    }
  ]
}
```

## Validating against the schema

```bash
pip install jsonschema
python - <<'PY'
import json
from pathlib import Path
from jsonschema import validate

schema = json.loads(Path("schemas/semantic_waypoint_array.schema.json").read_text())
payload = json.loads(Path("my_output.json").read_text())
validate(instance=payload, schema=schema)
print("ok")
PY
```

The repository's own test suite checks that
`path_to_semantic_waypoints` plus the wrapping `{"path": ..., "waypoints": ...}`
payload always validate against this schema.

## Where this format is produced

- `SemanticWaypoint.to_dict()` (each list element)
- `waypoint_publisher_node` with `output_format=json` (the wrapped
  `{"path": ..., "waypoints": ...}` envelope, published on a
  `std_msgs/msg/String` topic)
- The `semantic-toponav plan ... --format json` CLI (not currently
  shipped; see `docs/experiments.md`).

## Where this format is *not* used

The typed ROS2 message (`semantic_toponav_msgs/SemanticWaypointArray`)
carries the same information but uses a different on-wire encoding
(CDR). The two are kept in sync at the field level — see
`ros2/semantic_toponav_ros/semantic_toponav_ros/msg_conversions.py`.
