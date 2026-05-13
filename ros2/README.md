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
colcon build --packages-select semantic_toponav_ros
source install/setup.bash
```

The wrapper depends on `semantic-toponav` being importable in the same Python
environment. Either `pip install -e .` from the repository root, or add the
repository root to `PYTHONPATH`.

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

## Why JSON instead of custom messages

Custom ROS2 message packages add packaging overhead, slow down iteration,
and require additional build infrastructure. For the MVP we publish JSON
inside `std_msgs/String` so the wrapper stays a single Python package.

Custom messages (`SemanticWaypoint.msg`, `SemanticWaypointArray.msg`,
`TopologyNode.msg`, `TopologyEdge.msg`) are planned as a follow-up.

## What this wrapper does **not** do

- run Nav2 or any local planner
- avoid obstacles
- close a control loop
- handle recovery behaviors
- maintain a TF tree (the wrapper does not publish TF)

Those concerns belong to the local executor that the user already has.
