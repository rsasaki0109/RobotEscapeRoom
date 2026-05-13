"""ROS2 node: load a topology graph and surface basic info via logs.

The node owns no planning logic of its own. All graph parsing and validation
is delegated to the `semantic_toponav` Python core, which has no ROS deps.
"""

from __future__ import annotations

import sys

import rclpy
from rclpy.node import Node

from semantic_toponav.graph.serialization import GraphLoadError, load_graph
from semantic_toponav.graph.types import GraphValidationError


class GraphLoaderNode(Node):
    """Reads `graph_path` and `frame_id` parameters and loads the graph at startup."""

    def __init__(self) -> None:
        super().__init__("graph_loader")
        self.declare_parameter("graph_path", "")
        self.declare_parameter("frame_id", "map")

        graph_path = self.get_parameter("graph_path").get_parameter_value().string_value
        self._frame_id = self.get_parameter("frame_id").get_parameter_value().string_value

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
