"""ROS2 node: forward semantic waypoints to Nav2 ``NavigateThroughPoses``.

This is a *worked example* of the integration boundary described in
``ros2/README.md`` — it shows how a downstream adapter would consume the
``semantic_toponav_msgs/SemanticWaypointArray`` produced by
``waypoint_publisher_node`` and feed the concrete poses into Nav2.

Nav2 is intentionally **not** a build/test dependency of this repository.
``nav2_msgs`` is imported lazily so the wrapper package still builds on
robots that do not have Nav2 installed. Running this node *does* require
``nav2_msgs`` to be on the workspace path.

The node accepts the first ``SemanticWaypointArray`` by default. Set
``continuous:=true`` to preempt Nav2 with each new waypoint stream (escape-room
replanning).
"""

from __future__ import annotations

import sys
from typing import Any

import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node

from semantic_toponav_ros.msg_conversions import yaw_to_quaternion


class Nav2DemoNode(Node):
    """Bridges ``SemanticWaypointArray`` → Nav2 ``NavigateThroughPoses``."""

    def __init__(self) -> None:
        super().__init__("nav2_demo")

        self.declare_parameter("waypoints_topic", "/semantic_toponav/waypoints")
        self.declare_parameter("action_name", "navigate_through_poses")
        self.declare_parameter("action_timeout_sec", 5.0)
        self.declare_parameter("default_frame_id", "map")
        self.declare_parameter("continuous", False)

        waypoints_topic = (
            self.get_parameter("waypoints_topic").get_parameter_value().string_value
        )
        action_name = (
            self.get_parameter("action_name").get_parameter_value().string_value
        )
        self._action_timeout = float(self.get_parameter("action_timeout_sec").value)
        self._default_frame_id = (
            self.get_parameter("default_frame_id").get_parameter_value().string_value
        )
        self._continuous = bool(self.get_parameter("continuous").value)

        try:
            from semantic_toponav_msgs.msg import SemanticWaypointArray
        except ImportError as exc:
            self.get_logger().error(
                "nav2_demo requires the `semantic_toponav_msgs` package. Build "
                "it with `colcon build --packages-select semantic_toponav_msgs` "
                f"and source the workspace. ({exc})"
            )
            raise SystemExit(2) from exc

        try:
            from nav2_msgs.action import NavigateThroughPoses
        except ImportError as exc:
            self.get_logger().error(
                "nav2_demo requires Nav2's `nav2_msgs` package on the "
                "workspace path. Install Nav2 (`apt install ros-<distro>-nav2-msgs` "
                f"or build from source) and source the workspace. ({exc})"
            )
            raise SystemExit(2) from exc

        self._NavigateThroughPoses = NavigateThroughPoses
        self._action_client = ActionClient(self, NavigateThroughPoses, action_name)
        self._action_name = action_name
        self._sent = False
        self._goal_handle: Any | None = None
        self._pending_poses: list[Any] | None = None

        self._subscription = self.create_subscription(
            SemanticWaypointArray, waypoints_topic, self._on_waypoints, 10
        )

        self.get_logger().info(
            f"nav2_demo ready: subscribing on {waypoints_topic}, "
            f"forwarding to action {action_name!r}"
            + (" (continuous replan)" if self._continuous else " (one-shot)")
        )

    # ----------------------------- callbacks ------------------------------

    def _on_waypoints(self, msg: Any) -> None:
        if self._sent and not self._continuous:
            return

        from geometry_msgs.msg import PoseStamped

        poses: list[Any] = []
        skipped = 0
        for wp in msg.waypoints:
            if not wp.has_pose:
                skipped += 1
                continue
            ps = PoseStamped()
            ps.header.stamp = self.get_clock().now().to_msg()
            ps.header.frame_id = wp.frame_id or self._default_frame_id
            ps.pose.position.x = float(wp.pose.x)
            ps.pose.position.y = float(wp.pose.y)
            ps.pose.position.z = 0.0
            qx, qy, qz, qw = yaw_to_quaternion(float(wp.pose.theta))
            ps.pose.orientation.x = qx
            ps.pose.orientation.y = qy
            ps.pose.orientation.z = qz
            ps.pose.orientation.w = qw
            poses.append(ps)

        if not poses:
            self.get_logger().warning(
                f"received SemanticWaypointArray with {len(msg.waypoints)} "
                f"waypoints but none carried a pose ({skipped} skipped); "
                "nothing to send to Nav2"
            )
            return

        if not self._action_client.wait_for_server(timeout_sec=self._action_timeout):
            self.get_logger().error(
                f"Nav2 action server {self._action_name!r} not available "
                f"after {self._action_timeout:.1f}s; is Nav2 running?"
            )
            return

        self._pending_poses = poses
        if self._continuous and self._goal_handle is not None:
            self.get_logger().info("preempting in-flight Nav2 goal for replan")
            cancel_future = self._goal_handle.cancel_goal_async()
            cancel_future.add_done_callback(self._on_cancel_done)
            return

        self._send_goal(poses, skipped)

    def _on_cancel_done(self, _: Any) -> None:
        if self._pending_poses is not None:
            self._send_goal(self._pending_poses, 0)

    def _send_goal(self, poses: list[Any], skipped: int) -> None:
        goal_msg = self._NavigateThroughPoses.Goal()
        goal_msg.poses = poses

        if not self._continuous:
            self._sent = True
        self._pending_poses = None
        self.get_logger().info(
            f"sending NavigateThroughPoses goal with {len(poses)} poses "
            f"({skipped} pose-less waypoint(s) skipped)"
        )
        send_future = self._action_client.send_goal_async(goal_msg)
        send_future.add_done_callback(self._on_goal_response)

    def _on_goal_response(self, future: Any) -> None:
        goal_handle = future.result()
        if goal_handle is None or not goal_handle.accepted:
            self.get_logger().error("Nav2 rejected the NavigateThroughPoses goal")
            self._goal_handle = None
            return
        self._goal_handle = goal_handle
        self.get_logger().info("Nav2 accepted the goal; awaiting result")
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self._on_result)

    def _on_result(self, future: Any) -> None:
        result = future.result()
        status = getattr(result, "status", None)
        self._goal_handle = None
        self.get_logger().info(f"NavigateThroughPoses finished with status={status}")


def main(argv: list[str] | None = None) -> int:
    rclpy.init(args=argv)
    try:
        node = Nav2DemoNode()
    except SystemExit as exc:
        rclpy.shutdown()
        return int(exc.code or 1)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
