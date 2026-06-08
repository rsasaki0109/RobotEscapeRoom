# Robot Escape Room — Gazebo / gz-sim world

Generated from ``escape_room_scene.obj`` + 315 interior collision boxes.

## Regenerate

```bash
PYTHONPATH=. python3 examples/generate_escape_room_meshes.py
PYTHONPATH=. python3 examples/generate_escape_room_gazebo_world.py
```

## Run (Gazebo Harmonic / gz-sim)

```bash
export GZ_SIM_RESOURCE_PATH="$(pwd)/examples/meshes/escape_room/gazebo/models:$GZ_SIM_RESOURCE_PATH"
gz sim examples/meshes/escape_room/gazebo/escape_room.world
```

Robot **T-0** spawns at the holding cell `(0.0, 0.0, 0.05)`
in the `map` frame. Drive with `/cmd_vel` (DiffDrive plugin).

## Nav2 + ros_gz_bridge (full stack)

One-shot launch (Gazebo Harmonic + Nav2 + semantic waypoints):

```bash
pip install -e .
cd ros2 && colcon build --packages-select semantic_toponav_msgs semantic_toponav_ros
source install/setup.bash
cd ..
PYTHONPATH=. python3 examples/generate_escape_room_nav2_map.py
./scripts/run_escape_room_gz_nav2.sh
```

Or manually:

```bash
ros2 launch semantic_toponav_ros escape_room_gz_nav2.launch.py \
  goal_node:=maintenance_exit prefer_elevator:=true avoid_restricted:=true
```

Requires ROS 2 Jazzy/Humble with ``nav2_bringup``, ``ros_gz_sim``, and
``ros_gz_bridge``.

## Record Gazebo MP4

```bash
./scripts/record_escape_room_gz_sim.sh
# → docs/images/robot_escape_room_gz.mp4
```

## Nav2 GeoJSON only

Export the escape-room topology for Nav2 Route Server:

```bash
python examples/export_escape_room_nav2_route.py
```

Then load `examples/data/nav2/escape_room_graph.geojson` in Nav2, or publish
semantic waypoints via `ros2 run semantic_toponav_ros waypoint_publisher` with
`graph_path:=$PWD/examples/robot_escape_room.yaml`.

## Files

| Path | Purpose |
|---|---|
| `escape_room.world` | World with ground, sun, facility + T-0 robot |
| `models/escape_room_facility/model.sdf` | Visual mesh + collision boxes |
| `models/escape_room_facility/meshes/escape_room_scene.obj` | Furnished interior mesh |
| `models/t0_robot/model.sdf` | Diff-drive T-0 robot (gz-sim) |
| `models/t0_robot/t0_robot.urdf` | Same robot for ROS 2 / Nav2 |
