"""Record an MP4 from the escape-room Gazebo sim (open-loop /cmd_vel replay).

Drives T-0 along the Foxglove timeline with a simple odom feedback controller,
captures the overview camera, and writes ``docs/images/robot_escape_room_gz.mp4``.

When Gazebo rendering is unavailable (no GPU / blank camera), falls back to the
CPU overview renderer that matches the Gazebo ``overview_camera`` pose.

    python3 examples/record_escape_room_gz_mp4.py /tmp/gzframes
    python3 examples/record_escape_room_gz_mp4.py --offline /tmp/gzframes
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIMELINE_PATH = ROOT / "docs/foxglove/robot_escape_room_timeline.json"
GRAPH_PATH = ROOT / "examples" / "robot_escape_room.yaml"
DEFAULT_OUT = ROOT / "docs" / "images" / "robot_escape_room_gz.mp4"
HZ = 12


def _target_xy(graph, frame: dict) -> tuple[float, float]:
    route = frame.get("route") or []
    progress = float(frame.get("progress", 0.0))
    if len(route) < 2:
        node_id = route[0] if route else frame.get("location", "holding_cell")
        n = graph.get_node(node_id)
        return float(n.pose.x), float(n.pose.y)
    segment = min(int(progress), len(route) - 2)
    local = max(0.0, min(1.0, progress - segment))
    a = graph.get_node(route[segment])
    b = graph.get_node(route[segment + 1])
    ax, ay = float(a.pose.x), float(a.pose.y)
    bx, by = float(b.pose.x), float(b.pose.y)
    return ax + (bx - ax) * local, ay + (by - ay) * local


def _encode_mp4(frames_dir: Path, out_mp4: Path, n: int) -> None:
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-y", "-framerate", str(HZ),
            "-i", str(frames_dir / "f%04d.png"),
            "-vf", "scale=1280:-2:flags=lanczos,format=yuv420p",
            "-movflags", "+faststart", "-crf", "22",
            str(out_mp4),
        ],
        check=True,
    )
    print(f"wrote {out_mp4 if out_mp4.is_absolute() else out_mp4} ({n} frames)")


def _frames_look_blank(frames_dir: Path) -> bool:
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return False

    paths = sorted(frames_dir.glob("f*.png"))
    if len(paths) < 2:
        return True
    sample = [paths[0], paths[len(paths) // 2], paths[-1]]
    arrays = [np.array(Image.open(p).convert("RGB")) for p in sample]
    if arrays[0].std() >= 55:
        return False
    return np.allclose(arrays[0], arrays[1], atol=3) and np.allclose(arrays[1], arrays[2], atol=3)


def render_offline_frames(frames_dir: Path, timeline: list[dict], graph) -> int:
    sys.path.insert(0, str(ROOT / "examples"))
    from escape_room_mesh_render import render_overview_facility

    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("f*.png"):
        old.unlink()
    for i, frame in enumerate(timeline):
        img = render_overview_facility(graph, frame, width=1280, height=720)
        img.convert("RGB").save(frames_dir / f"f{i:04d}.png")
    print(f"rendered {len(timeline)} overview frames offline (CPU)")
    return len(timeline)


def capture_gz_frames(frames_dir: Path, timeline: list[dict], graph) -> int:
    import rclpy
    from geometry_msgs.msg import Twist
    from nav_msgs.msg import Odometry
    from rclpy.node import Node
    from sensor_msgs.msg import Image

    def _yaw_from_odom(msg: Odometry) -> float:
        q = msg.pose.pose.orientation
        siny = 2.0 * (q.w * q.z + q.x * q.y)
        cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        return math.atan2(siny, cosy)

    class GzRecorder(Node):
        def __init__(self) -> None:
            super().__init__("escape_room_gz_recorder")
            self._idx = 0
            self._odom: Odometry | None = None
            self._saved = 0
            self._ticks_done = False
            self._ticks_done_at: float | None = None
            self._cmd_pub = self.create_publisher(Twist, "/cmd_vel", 10)
            self.create_subscription(Odometry, "/odom", self._on_odom, 10)
            self.create_subscription(Image, "/escape_room/camera", self._on_image, 10)
            self.create_timer(1.0 / HZ, self._tick)
            self.get_logger().info(f"recording {len(timeline)} timeline frames @ {HZ} Hz")

        def _on_odom(self, msg: Odometry) -> None:
            self._odom = msg

        def _on_image(self, msg: Image) -> None:
            if self._saved >= len(timeline):
                return
            path = frames_dir / f"f{self._saved:04d}.png"
            if path.exists():
                return
            if msg.encoding not in {"rgb8", "bgr8"}:
                self.get_logger().warning(f"unsupported image encoding {msg.encoding!r}")
                return
            from PIL import Image as PILImage

            row = msg.step
            img = PILImage.frombytes("RGB", (msg.width, msg.height), bytes(msg.data), "raw", "RGB", row, 1)
            if msg.encoding == "bgr8":
                r, g, b = img.split()
                img = PILImage.merge("RGB", (b, g, r))
            img.save(path)
            self._saved += 1
            if self._saved % 20 == 0:
                self.get_logger().info(f"captured {self._saved} frames")

        def _tick(self) -> None:
            if self._saved >= len(timeline):
                self.get_logger().info(f"done — saved {self._saved} frames")
                rclpy.shutdown()
                return

            if self._idx >= len(timeline):
                if not self._ticks_done:
                    self._ticks_done = True
                    self._ticks_done_at = self.get_clock().now().nanoseconds / 1e9
                    self.get_logger().info(
                        f"timeline complete — waiting for frames ({self._saved}/{len(timeline)})"
                    )
                elif (
                    self._ticks_done_at is not None
                    and self.get_clock().now().nanoseconds / 1e9 - self._ticks_done_at > 45.0
                ):
                    self.get_logger().error(
                        f"timeout — only captured {self._saved}/{len(timeline)} frames"
                    )
                    rclpy.shutdown()
                    return
                frame = timeline[-1]
            else:
                frame = timeline[self._idx]
                self._idx += 1

            tx, ty = _target_xy(graph, frame)
            twist = Twist()
            if self._odom is not None:
                ox = float(self._odom.pose.pose.position.x)
                oy = float(self._odom.pose.pose.position.y)
                yaw = _yaw_from_odom(self._odom)
                dx, dy = tx - ox, ty - oy
                dist = math.hypot(dx, dy)
                target_yaw = math.atan2(dy, dx)
                err = math.atan2(math.sin(target_yaw - yaw), math.cos(target_yaw - yaw))
                if abs(err) > 0.35:
                    twist.linear.x = 0.08
                    twist.angular.z = max(-1.2, min(1.2, 1.5 * err))
                else:
                    twist.linear.x = max(0.0, min(0.4, dist))
                    twist.angular.z = max(-0.8, min(0.8, 0.8 * err))
            else:
                twist.linear.x = 0.2
            self._cmd_pub.publish(twist)

    frames_dir.mkdir(parents=True, exist_ok=True)
    rclpy.init()
    node = GzRecorder()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return len(list(frames_dir.glob("f*.png")))


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--offline"]
    offline_only = "--offline" in sys.argv[1:]
    frames_dir = Path(args[0] if args else "/tmp/gzframes")
    out_mp4 = Path(args[1]) if len(args) > 1 else DEFAULT_OUT

    sys.path.insert(0, str(ROOT))
    from semantic_toponav.graph.serialization import load_graph

    timeline = json.loads(TIMELINE_PATH.read_text(encoding="utf-8"))["frames"]
    graph = load_graph(str(GRAPH_PATH))

    n = 0
    if offline_only:
        n = render_offline_frames(frames_dir, timeline, graph)
    else:
        try:
            n = capture_gz_frames(frames_dir, timeline, graph)
        except Exception as exc:
            print(f"gz capture failed ({exc}) — using offline overview renderer", file=sys.stderr)
        if n == 0 or _frames_look_blank(frames_dir):
            if n > 0:
                print("gz camera frames look blank — using offline overview renderer", file=sys.stderr)
            n = render_offline_frames(frames_dir, timeline, graph)

    if n == 0:
        print("no frames captured", file=sys.stderr)
        return 1

    _encode_mp4(frames_dir, out_mp4, n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
