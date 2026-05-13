# `semantic_toponav_ros` — ROS2 adapter

A thin wrapper that exposes the `semantic_toponav` Python core as ROS2 nodes.
The core has no ROS dependency; only this directory does.

## Integration boundary

```
+---------------------------------------+
|     LLM / task planner / operator     |
+----------------|----------------------+
                 v  goal (semantic, e.g. "office_2f")
+---------------------------------------+
|   semantic-toponav (this repository)  |
|   - topology graph                    |  <-- "where and why"
|   - semantic cost functions           |
|   - semantic waypoints                |
+----------------|----------------------+
                 v  poses + semantic actions
+---------------------------------------+
|     Nav2 / Autoware / MPPI / policy   |  <-- "how to move locally"
|   - obstacle avoidance                |
|   - local control                     |
|   - recovery behaviors                |
+---------------------------------------+
```

`semantic-toponav` produces a sequence of semantic waypoints — each may carry
an optional `pose`. A small adapter takes those poses and feeds them into the
local executor (Nav2's `nav2_msgs/NavigateThroughPoses`, or an equivalent in
Autoware). This repository does **not** implement that local executor.

## Nodes

| node | binary | purpose |
|------|--------|---------|
| `graph_loader_node` | `graph_loader` | load and validate a topology graph at startup |
| `waypoint_publisher_node` | `waypoint_publisher` | plan a route and publish semantic waypoints |

### Build

```bash
# inside a ROS2 workspace
colcon build --packages-select semantic_toponav_msgs semantic_toponav_ros
source install/setup.bash
```

The wrapper depends on `semantic-toponav` being importable in the same Python
environment. Either `pip install -e .` from the repository root, or add the
repository root to `PYTHONPATH`. The `semantic_toponav_msgs` package is only
required if you switch `waypoint_publisher_node` to `output_format:=msg`
(see below).

### Run

Load and validate a graph:

```bash
ros2 run semantic_toponav_ros graph_loader \
  --ros-args -p graph_path:=$PWD/examples/indoor_office.yaml
```

Plan a route and publish semantic waypoints as JSON on
`/semantic_toponav/waypoints`:

```bash
ros2 run semantic_toponav_ros waypoint_publisher \
  --ros-args \
    -p graph_path:=$PWD/examples/indoor_office.yaml \
    -p start_node:=entrance \
    -p goal_node:=office_2f \
    -p avoid_stairs:=true \
    -p prefer_elevator:=true
```

Inspect the topic:

```bash
ros2 topic echo /semantic_toponav/waypoints
```

The payload is a JSON document with `path` and `waypoints` (the same
structure as `semantic-toponav waypoints --format json`).

### Publishing typed messages instead of JSON

Pass `output_format:=msg` (and build `semantic_toponav_msgs` alongside the
wrapper) to publish a `semantic_toponav_msgs/SemanticWaypointArray` instead
of `std_msgs/String`:

```bash
ros2 run semantic_toponav_ros waypoint_publisher \
  --ros-args \
    -p graph_path:=$PWD/examples/indoor_office.yaml \
    -p start_node:=entrance \
    -p goal_node:=office_2f \
    -p output_format:=msg \
    -p frame_id:=map
```

The custom message layout mirrors the Python dataclasses one-for-one and is
documented under [`semantic_toponav_msgs/msg/`](semantic_toponav_msgs/msg/).
Field-dict conversion helpers (testable without a sourced ROS environment)
live in
[`semantic_toponav_ros/semantic_toponav_ros/msg_conversions.py`](semantic_toponav_ros/semantic_toponav_ros/msg_conversions.py).

## Nav2 integration — MVP

For the first iteration the contract with Nav2 is intentionally minimal:

1. `waypoint_publisher_node` plans on the topology graph.
2. It publishes `path` + `waypoints` (each with optional `pose`) as JSON on
   `/semantic_toponav/waypoints`.
3. A user-provided adapter subscribes to that topic, extracts poses, and
   sends them to Nav2 (typically `NavigateThroughPoses`).

The adapter is intentionally **not** included in this repository. It depends
on the user's Nav2 stack and is small enough to write per deployment. A
worked example will live under `ros2/semantic_toponav_ros/semantic_toponav_ros/nav2_demo_node.py`
in a follow-up.

## JSON vs custom messages

| | `output_format:=json` (default) | `output_format:=msg` |
|---|---|---|
| Wire type | `std_msgs/String` containing a JSON document | `semantic_toponav_msgs/SemanticWaypointArray` |
| Extra build deps | none | requires building `semantic_toponav_msgs` |
| Introspection | `ros2 topic echo` shows raw JSON | `ros2 topic echo` shows typed fields; works with `ros2 bag` filters |
| Schema enforcement | client-side JSON parsing | enforced by the message definition |

The JSON form is the zero-dependency MVP. The custom-message form is the
recommended option once your workspace is set up — it gives you typed
fields, `ros2 bag` introspection, and downstream subscribers that don't
have to parse JSON.

Message definitions:

| `.msg` | mirrors Python dataclass |
|---|---|
| `SemanticWaypoint.msg` | `semantic_toponav.waypoint.SemanticWaypoint` |
| `SemanticWaypointArray.msg` | a `path: list[str]` + `waypoints` pair |
| `TopologyNode.msg` | `semantic_toponav.graph.types.TopologyNode` |
| `TopologyEdge.msg` | `semantic_toponav.graph.types.TopologyEdge` |
| `TopologyGraph.msg` | a full `TopologyGraph` snapshot |

Heterogeneous `properties` dicts (which can carry strings, ints, lists, etc.)
are serialized as a JSON document inside a `properties_json` field on each
message rather than as parallel key/value arrays. Optional `Pose2D` values
travel as `(has_pose: bool, frame_id: string, pose: geometry_msgs/Pose2D)`.

## What this wrapper does **not** do

- run Nav2 or any local planner
- avoid obstacles
- close a control loop
- handle recovery behaviors
- maintain a TF tree (the wrapper does not publish TF)

Those concerns belong to the local executor that the user already has.
