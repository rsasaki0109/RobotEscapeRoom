#!/usr/bin/env bash
# Regenerate assets and launch escape-room Gazebo + Nav2 + semantic waypoints.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> regenerate meshes / Gazebo world / Nav2 map"
PYTHONPATH=. python3 examples/generate_escape_room_meshes.py
PYTHONPATH=. python3 examples/generate_escape_room_gazebo_world.py
PYTHONPATH=. python3 examples/generate_escape_room_nav2_map.py
PYTHONPATH=. python3 examples/export_escape_room_nav2_route.py

if ! command -v ros2 >/dev/null 2>&1; then
  echo "ros2 not found — source your ROS 2 underlay first." >&2
  exit 1
fi

WS="${SEMANTIC_TOPONAV_WS:-$ROOT/ros2}"
if [[ -f "$WS/install/setup.bash" ]]; then
  # shellcheck disable=SC1090
  source "$WS/install/setup.bash"
else
  echo "build workspace first: cd ros2 && colcon build --packages-select semantic_toponav_msgs semantic_toponav_ros" >&2
  exit 1
fi

pip install -e . -q

echo "==> launch Gazebo + ros_gz_bridge + Nav2"
exec ros2 launch semantic_toponav_ros escape_room_gz_nav2.launch.py "$@"
