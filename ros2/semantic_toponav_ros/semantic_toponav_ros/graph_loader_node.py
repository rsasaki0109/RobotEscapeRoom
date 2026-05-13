"""ROS2 node: load a topology graph and publish it as a latched message.

The node owns no planning logic of its own. All graph parsing and validation
is delegated to the `semantic_toponav` Python core, which has no ROS deps.

When ``publish_graph`` is true (the default) the validated graph is published
once on ``topic`` as a ``semantic_toponav_msgs/TopologyGraph`` with
``TRANSIENT_LOCAL`` durability, so subscribers that connect after the publish
still receive the latest snapshot.
"""

from __future__ import annotations

import sys

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from semantic_toponav.graph.serialization import GraphLoadError, load_graph
from semantic_toponav.graph.types import GraphValidationError


def _latched_qos() -> QoSProfile:
    """Return a depth-1 transient-local QoS for one-shot static publishers."""
    return QoSProfile(
        depth=1,
        history=HistoryPolicy.KEEP_LAST,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )


class GraphLoaderNode(Node):
    """Loads a topology graph at startup and (optionally) publishes it once."""

    def __init__(self) -> None:
        super().__init__("graph_loader")
        self.declare_parameter("graph_path", "")
        self.declare_parameter("frame_id", "map")
        self.declare_parameter("topic", "/semantic_toponav/graph")
        self.declare_parameter("publish_graph", True)

        graph_path = self.get_parameter("graph_path").get_parameter_value().string_value
        self._frame_id = self.get_parameter("frame_id").get_parameter_value().string_value
        topic = self.get_parameter("topic").get_parameter_value().string_value
        publish_graph = self.get_parameter("publish_graph").value

        if not graph_path:
            self.get_logger().error("parameter `graph_path` is required")
            raise SystemExit(2)

        try:
            self._graph = load_graph(graph_path)
            self._graph.validate()
        except (GraphLoadError, GraphValidationError) as exc:
            self.get_logger().error(f"failed to load graph: {exc}")
            raise SystemExit(2) from exc

        self.get_logger().info(
            f"loaded graph from {graph_path}: "
            f"{len(self._graph.node_ids())} nodes, "
            f"{len(self._graph.edge_ids())} edges "
            f"(frame_id={self._frame_id})"
        )

        self._publisher = None
        if publish_graph:
            self._setup_graph_publisher(topic)

    # --------------------------- graph publishing --------------------------

    def _setup_graph_publisher(self, topic: str) -> None:
        try:
            from semantic_toponav_msgs.msg import TopologyGraph as TopologyGraphMsg
        except ImportError as exc:
            self.get_logger().error(
                "publish_graph=true requires the `semantic_toponav_msgs` "
                "package. Build it with `colcon build --packages-select "
                f"semantic_toponav_msgs` and source the workspace. ({exc})"
            )
            raise SystemExit(2) from exc

        from semantic_toponav_ros.msg_conversions import topology_graph_to_msg

        self._publisher = self.create_publisher(
            TopologyGraphMsg, topic, _latched_qos()
        )
        msg = topology_graph_to_msg(
            self._graph,
            frame_id=self._frame_id,
            stamp=self.get_clock().now().to_msg(),
        )
        self._publisher.publish(msg)
        self.get_logger().info(
            f"published TopologyGraph on {topic} "
            f"({len(msg.nodes)} nodes, {len(msg.edges)} edges)"
        )

    @property
    def graph(self):
        return self._graph

    @property
    def frame_id(self) -> str:
        return self._frame_id


def main(argv: list[str] | None = None) -> int:
    rclpy.init(args=argv)
    try:
        node = GraphLoaderNode()
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
