#!/usr/bin/env bash
# Record docs/images/robot_escape_room_gz.mp4 from the Gazebo escape-room world.
#
# Requires: ROS 2 Jazzy/Humble, gz-sim (Harmonic), ros_gz_bridge, ffmpeg, Pillow.
#
#   ./scripts/record_escape_room_gz_sim.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FRAMES="${FRAMES_DIR:-/tmp/gz_escape_room_frames}"
OUT="$ROOT/docs/images/robot_escape_room_gz.mp4"
WORLD="$ROOT/examples/meshes/escape_room/gazebo/escape_room.world"
MODELS="$ROOT/examples/meshes/escape_room/gazebo/models"

if ! command -v ros2 >/dev/null 2>&1; then
  echo "ros2 not found — source your ROS 2 underlay first." >&2
  exit 1
fi
if ! command -v gz >/dev/null 2>&1; then
  echo "gz (Gazebo Harmonic) not found." >&2
  exit 1
fi

echo "==> regenerate Gazebo world + timeline"
PYTHONPATH=. python3 examples/generate_escape_room_meshes.py
PYTHONPATH=. python3 examples/generate_escape_room_gazebo_world.py
PYTHONPATH=. python3 examples/export_escape_room_foxglove_mcap.py

WS="${SEMANTIC_TOPONAV_WS:-$ROOT/ros2}"
if [[ -f "$WS/install/setup.bash" ]]; then
  # shellcheck disable=SC1090
  source "$WS/install/setup.bash"
fi

export GZ_SIM_RESOURCE_PATH="${MODELS}:${GZ_SIM_RESOURCE_PATH:-}"
export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"

echo "==> start gz-sim (headless server + rendering)"
gz sim -s -r --headless-rendering "$WORLD" &
GZ_PID=$!
cleanup() {
  kill "$GZ_PID" 2>/dev/null || true
  kill "$BRIDGE_PID" 2>/dev/null || true
}
trap cleanup EXIT
sleep 5

echo "==> start ros_gz_bridge (odom, cmd_vel, camera)"
ros2 run ros_gz_bridge parameter_bridge \
  /cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist \
  /odom@nav_msgs/msg/Odometry[gz.msgs.Odometry \
  /escape_room/camera@sensor_msgs/msg/Image[gz.msgs.Image &
BRIDGE_PID=$!
sleep 3

echo "==> drive T-0 + capture overview camera"
rm -rf "$FRAMES"
python3 examples/record_escape_room_gz_mp4.py "$FRAMES" "$OUT"

echo "==> done"
ls -lh "$OUT"
