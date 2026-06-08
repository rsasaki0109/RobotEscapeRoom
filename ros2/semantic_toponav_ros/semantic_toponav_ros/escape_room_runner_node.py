"""ROS2 node: run the escape-room puzzle loop and republish semantic waypoints.

Subscribes to robot odometry; when T-0 reaches the current objective node it
runs on-arrival puzzle actions, replans, and publishes a fresh
``SemanticWaypointArray`` for Nav2 to follow.
"""

from __future__ import annotations

import math
import sys

import rclpy
from nav_msgs.msg import Odometry
from rclpy.node import Node
from std_msgs.msg import String

from semantic_toponav.escape_room.runner import (
    TRUE_EXIT,
    TurnPlan,
    World,
    complete_navigation,
    next_turn,
)
from semantic_toponav.graph.serialization import GraphLoadError, load_graph
from semantic_toponav.graph.types import GraphValidationError


class EscapeRoomRunnerNode(Node):
    def __init__(self) -> None:
        super().__init__("escape_room_runner")

        self.declare_parameter("graph_path", "")
        self.declare_parameter("odom_topic", "/odom")
        self.declare_parameter("waypoints_topic", "/semantic_toponav/waypoints")
        self.declare_parameter("status_topic", "/semantic_toponav/escape_room/status")
        self.declare_parameter("frame_id", "map")
        self.declare_parameter("arrival_radius", 0.45)
        self.declare_parameter("startup_delay_sec", 20.0)

        graph_path = self.get_parameter("graph_path").get_parameter_value().string_value
        if not graph_path:
            self.get_logger().error("parameter `graph_path` is required")
            raise SystemExit(2)

        try:
            self._graph = load_graph(graph_path)
            self._graph.validate()
        except (GraphLoadError, GraphValidationError) as exc:
            self.get_logger().error(f"failed to load graph: {exc}")
            raise SystemExit(2) from exc

        self._world = World()
        self._frame_id = self.get_parameter("frame_id").get_parameter_value().string_value
        self._arrival_radius = float(self.get_parameter("arrival_radius").value)
        self._active: TurnPlan | None = None
        self._target_node: str | None = None
        self._pose = (0.0, 0.0)
        self._started = False
        self._done = False

        waypoints_topic = (
            self.get_parameter("waypoints_topic").get_parameter_value().string_value
        )
        status_topic = (
            self.get_parameter("status_topic").get_parameter_value().string_value
        )
        odom_topic = self.get_parameter("odom_topic").get_parameter_value().string_value

        try:
            from semantic_toponav_msgs.msg import SemanticWaypointArray
        except ImportError as exc:
            self.get_logger().error(
                "escape_room_runner requires `semantic_toponav_msgs`. "
                f"Build and source the workspace. ({exc})"
            )
            raise SystemExit(2) from exc

        from semantic_toponav_ros.msg_conversions import semantic_waypoint_array_to_msg

        self._wp_msg_type = SemanticWaypointArray
        self._to_msg = semantic_waypoint_array_to_msg
        self._wp_pub = self.create_publisher(SemanticWaypointArray, waypoints_topic, 10)
        self._status_pub = self.create_publisher(String, status_topic, 10)
        self._odom_sub = self.create_subscription(Odometry, odom_topic, self._on_odom, 10)

        delay = float(self.get_parameter("startup_delay_sec").value)
        self.create_timer(delay, self._start_once)
        self.create_timer(0.2, self._check_arrival)

        self.get_logger().info(
            f"escape_room_runner loaded graph ({len(self._graph.node_ids())} nodes); "
            f"waiting {delay:.0f}s before first plan"
        )

    def _start_once(self) -> None:
        if self._started:
            return
        self._started = True
        self._dispatch_turn()

    def _on_odom(self, msg: Odometry) -> None:
        self._pose = (
            float(msg.pose.pose.position.x),
            float(msg.pose.pose.position.y),
        )

    def _node_xy(self, node_id: str) -> tuple[float, float] | None:
        node = self._graph.get_node(node_id)
        if node.pose is None:
            return None
        return float(node.pose.x), float(node.pose.y)

    def _publish_status(self, text: str) -> None:
        msg = String()
        msg.data = text
        self._status_pub.publish(msg)
        self.get_logger().info(text)

    def _publish_waypoints(self, turn: TurnPlan) -> None:
        path = turn.exit_path or (turn.objective.path if turn.objective else [])
        msg = self._to_msg(
            path,
            turn.waypoints,
            frame_id=self._frame_id,
            stamp=self.get_clock().now().to_msg(),
        )
        self._wp_pub.publish(msg)

    def _dispatch_turn(self) -> None:
        if self._done:
            return
        turn = next_turn(self._graph, self._world)
        self._active = turn

        if turn.status == "exit":
            self._target_node = TRUE_EXIT
            self._publish_status(
                f"[Turn {turn.turn}] exit run → {self._graph.get_node(TRUE_EXIT).label}"
            )
            self._publish_waypoints(turn)
            return

        if turn.status == "stuck":
            self._done = True
            self._target_node = None
            self._publish_status(f"[Turn {turn.turn}] stuck — no reachable objectives")
            return

        assert turn.objective is not None
        self._target_node = turn.objective.node
        label = self._graph.get_node(turn.objective.node).label
        self._publish_status(f"[Turn {turn.turn}] navigate → {label} ({turn.status})")
        self._publish_waypoints(turn)

    def _check_arrival(self) -> None:
        if self._done or not self._started or self._target_node is None:
            return
        target_xy = self._node_xy(self._target_node)
        if target_xy is None:
            return
        dx = self._pose[0] - target_xy[0]
        dy = self._pose[1] - target_xy[1]
        if math.hypot(dx, dy) > self._arrival_radius:
            return

        node = self._target_node
        if self._active and self._active.status == "exit":
            complete_navigation(self._graph, self._world, node)
            self._done = True
            self._target_node = None
            self._publish_status(
                f"[Turn {self._world.turn}] escaped via {self._graph.get_node(TRUE_EXIT).label}"
            )
            return

        event = complete_navigation(self._graph, self._world, node)
        for line in event.messages:
            self._publish_status(f"  {line}")

        if self._world.escaped or self._world.stuck:
            self._done = True
            self._target_node = None
            return

        self._target_node = None
        self._dispatch_turn()


def main(argv: list[str] | None = None) -> int:
    rclpy.init(args=argv)
    try:
        node = EscapeRoomRunnerNode()
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
