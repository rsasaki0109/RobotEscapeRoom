"""ROS2 node: plan a route and publish semantic waypoints as JSON.

For the MVP we publish JSON inside `std_msgs/String` on
`/semantic_toponav/waypoints` to avoid requiring a custom message package.
Custom messages can replace this later without changing the planner.
"""

from __future__ import annotations

import json
import sys

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from semantic_toponav.graph.serialization import GraphLoadError, load_graph
from semantic_toponav.graph.types import GraphValidationError
from semantic_toponav.planner import (
    avoid_restricted,
    avoid_stairs,
    compose_costs,
    plan_astar,
    plan_dijkstra,
    prefer_elevator,
)
from semantic_toponav.planner.errors import NoPathError, PlanningError
from semantic_toponav.waypoint.semantic_waypoint import path_to_semantic_waypoints


def _build_cost_fn(*, avoid_restricted_flag, avoid_stairs_flag, prefer_elevator_flag):
    fns = []
    if avoid_restricted_flag:
        fns.append(avoid_restricted)
    if avoid_stairs_flag:
        fns.append(avoid_stairs)
    if prefer_elevator_flag:
        fns.append(prefer_elevator)
    if not fns:
        return None
    return compose_costs(*fns)


class WaypointPublisherNode(Node):
    """Plans once at startup and publishes the resulting semantic waypoints."""

    def __init__(self) -> None:
        super().__init__("waypoint_publisher")

        self.declare_parameter("graph_path", "")
        self.declare_parameter("start_node", "")
        self.declare_parameter("goal_node", "")
        self.declare_parameter("algorithm", "astar")
        self.declare_parameter("avoid_restricted", False)
        self.declare_parameter("avoid_stairs", False)
        self.declare_parameter("prefer_elevator", False)
        self.declare_parameter("topic", "/semantic_toponav/waypoints")

        graph_path = self.get_parameter("graph_path").get_parameter_value().string_value
        start = self.get_parameter("start_node").get_parameter_value().string_value
        goal = self.get_parameter("goal_node").get_parameter_value().string_value
        algorithm = self.get_parameter("algorithm").get_parameter_value().string_value
        topic = self.get_parameter("topic").get_parameter_value().string_value

        if not graph_path or not start or not goal:
            self.get_logger().error(
                "parameters `graph_path`, `start_node`, and `goal_node` are required"
            )
            raise SystemExit(2)

        try:
            graph = load_graph(graph_path)
            graph.validate()
        except (GraphLoadError, GraphValidationError) as exc:
            self.get_logger().error(f"failed to load graph: {exc}")
            raise SystemExit(2) from exc

        cost_fn = _build_cost_fn(
            avoid_restricted_flag=self.get_parameter("avoid_restricted").value,
            avoid_stairs_flag=self.get_parameter("avoid_stairs").value,
            prefer_elevator_flag=self.get_parameter("prefer_elevator").value,
        )

        try:
            if algorithm == "dijkstra":
                path = plan_dijkstra(graph, start, goal, cost_fn=cost_fn)
            else:
                path = plan_astar(graph, start, goal, cost_fn=cost_fn)
        except (PlanningError, NoPathError) as exc:
            self.get_logger().error(f"planning failed: {exc}")
            raise SystemExit(2) from exc

        waypoints = path_to_semantic_waypoints(graph, path)
        payload = {
            "path": path,
            "waypoints": [wp.to_dict() for wp in waypoints],
        }

        self._publisher = self.create_publisher(String, topic, 10)
        self._timer = self.create_timer(1.0, self._publish_once)
        self._message = json.dumps(payload, ensure_ascii=False)
        self.get_logger().info(
            f"planned {len(path)} nodes from {start!r} to {goal!r}; publishing on {topic}"
        )

    def _publish_once(self) -> None:
        msg = String()
        msg.data = self._message
        self._publisher.publish(msg)


def main(argv: list[str] | None = None) -> int:
    rclpy.init(args=argv)
    try:
        node = WaypointPublisherNode()
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
