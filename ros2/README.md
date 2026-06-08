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
| `graph_loader_node` | `graph_loader` | load and validate a topology graph at startup, and publish it as a latched `TopologyGraph` |
| `waypoint_publisher_node` | `waypoint_publisher` | plan a route and publish semantic waypoints |
| `nav2_demo_node` | `nav2_demo` | worked example: forward semantic waypoints to Nav2's `NavigateThroughPoses` action |
| `escape_room_runner_node` | `escape_room_runner` | run the escape-room puzzle loop; republish waypoints on each arrival |

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

Load, validate, and publish a graph as a latched
`semantic_toponav_msgs/TopologyGraph` on `/semantic_toponav/graph`:

```bash
ros2 run semantic_toponav_ros graph_loader \
  --ros-args -p graph_path:=$PWD/examples/indoor_office.yaml
```

The publisher uses `TRANSIENT_LOCAL` durability, so subscribers that connect
after the node starts still receive the most recent snapshot. To suppress
publishing (load and validate only), pass `-p publish_graph:=false`.

Inspect the topic:

```bash
ros2 topic echo /semantic_toponav/graph --once --qos-durability transient_local
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

The contract with Nav2 is intentionally minimal:

1. `waypoint_publisher_node` plans on the topology graph.
2. It publishes `path` + `waypoints` (each with optional `pose`) on
   `/semantic_toponav/waypoints` — either as a `SemanticWaypointArray`
   (`output_format:=msg`) or as a JSON `std_msgs/String` (default).
3. An adapter subscribes, extracts poses, and sends them to Nav2 (typically
   `NavigateThroughPoses`).

A reference implementation of step 3 ships as
[`nav2_demo_node`](semantic_toponav_ros/semantic_toponav_ros/nav2_demo_node.py).
It expects the typed `SemanticWaypointArray` form, converts each pose-bearing
waypoint into a `geometry_msgs/PoseStamped` (the planar yaw → quaternion
conversion uses [`yaw_to_quaternion`](semantic_toponav_ros/semantic_toponav_ros/msg_conversions.py)),
and sends a one-shot goal to the Nav2 action server. Pose-less waypoints
(start/abstract/pass-through) are skipped.

```bash
# Terminal 1: publish the typed waypoint array.
ros2 run semantic_toponav_ros waypoint_publisher \
  --ros-args \
    -p graph_path:=$PWD/examples/indoor_office.yaml \
    -p start_node:=entrance \
    -p goal_node:=office_2f \
    -p output_format:=msg

# Terminal 2: bridge it into Nav2.
ros2 run semantic_toponav_ros nav2_demo \
  --ros-args \
    -p waypoints_topic:=/semantic_toponav/waypoints \
    -p action_name:=navigate_through_poses
```

`nav2_demo_node` requires `nav2_msgs` to be on the workspace path; the
repository does **not** declare it as a build dependency so that the
adapter package still builds on robots without Nav2. The node fails fast
with a clear error message if `nav2_msgs` is not importable at runtime.

## Escape room — Gazebo + Nav2 end-to-end

The furnished escape-room facility ships with a one-shot launch that wires
**Gazebo Harmonic → ros_gz_bridge → Nav2 → semantic waypoints → T-0**:

```bash
# from repository root
pip install -e .
cd ros2 && colcon build --packages-select semantic_toponav_msgs semantic_toponav_ros
source install/setup.bash
cd ..
PYTHONPATH=. python3 examples/generate_escape_room_meshes.py
PYTHONPATH=. python3 examples/generate_escape_room_gazebo_world.py
PYTHONPATH=. python3 examples/generate_escape_room_nav2_map.py
./scripts/run_escape_room_gz_nav2.sh
```

After ~20 s the **escape-room runner** drives the full puzzle loop: T-0 picks
the nearest item/riddle objective, Nav2 follows the semantic waypoints, and on
arrival the runner resolves puzzles and replans until T-0 reaches the sublevel
exit. Status strings publish on `/semantic_toponav/escape_room/status`.

For a single static route instead, disable the puzzle runner:

```bash
ros2 launch semantic_toponav_ros escape_room_gz_nav2.launch.py escape_room:=false \\
  goal_node:=maintenance_exit
```

Requires ROS 2 Humble/Jazzy with `nav2_bringup`, `ros_gz_sim`, and
`ros_gz_bridge`. T-0 publishes `/scan` (360° GPU lidar); the Nav2 map
rasterizes interior walls from furnished collision boxes. See
[`examples/meshes/escape_room/gazebo/README.md`](../examples/meshes/escape_room/gazebo/README.md).

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
