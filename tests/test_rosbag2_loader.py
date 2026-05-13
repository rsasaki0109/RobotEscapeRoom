"""Tests for the rosbag2 trajectory loader.

These tests are gated on a working ROS2 Python environment — they need
``rosbag2_py`` to *write* a small fixture bag and our loader to read it
back. When those packages aren't importable (the default in the project's
GitHub Actions matrix), the whole module is skipped.
"""

from __future__ import annotations

from pathlib import Path

import pytest

rosbag2_py = pytest.importorskip("rosbag2_py")
rclpy_serialization = pytest.importorskip("rclpy.serialization")
pytest.importorskip("nav_msgs.msg")
pytest.importorskip("geometry_msgs.msg")

from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped  # noqa: E402
from nav_msgs.msg import Odometry  # noqa: E402

from semantic_toponav.conversion import (  # noqa: E402
    RosbagTrajectoryLoadError,
    load_trajectories_from_rosbag,
    topology_from_trajectories,
)


def _write_bag(
    path: Path,
    entries: list[tuple[str, str, list]],
) -> Path:
    """Write a small sqlite3 rosbag2 at ``path``.

    ``entries`` is a list of ``(topic_name, type_name, messages)`` tuples,
    where ``messages`` are already-built ROS2 message instances and
    ``type_name`` is the slash-form ROS type (e.g.
    ``"nav_msgs/msg/Odometry"``).
    """
    serialize_message = rclpy_serialization.serialize_message
    writer = rosbag2_py.SequentialWriter()
    storage_options = rosbag2_py.StorageOptions(uri=str(path), storage_id="sqlite3")
    converter_options = rosbag2_py.ConverterOptions(
        input_serialization_format="cdr", output_serialization_format="cdr"
    )
    writer.open(storage_options, converter_options)
    for topic_id, (topic_name, type_name, _) in enumerate(entries, start=1):
        try:
            metadata = rosbag2_py.TopicMetadata(
                id=topic_id,
                name=topic_name,
                type=type_name,
                serialization_format="cdr",
            )
        except TypeError:
            # Older rosbag2_py releases (e.g. humble) take no `id` argument.
            metadata = rosbag2_py.TopicMetadata(
                name=topic_name,
                type=type_name,
                serialization_format="cdr",
            )
        writer.create_topic(metadata)
    stamp = 0
    for topic_name, _type_name, messages in entries:
        for msg in messages:
            writer.write(topic_name, serialize_message(msg), stamp)
            stamp += 10_000_000  # 10 ms per message, in nanoseconds
    # SequentialWriter has no explicit close in ROS2 jazzy; deletion flushes.
    del writer
    return path


def _odom(x: float, y: float) -> Odometry:
    msg = Odometry()
    msg.pose.pose.position.x = float(x)
    msg.pose.pose.position.y = float(y)
    return msg


def _pose_stamped(x: float, y: float) -> PoseStamped:
    msg = PoseStamped()
    msg.pose.position.x = float(x)
    msg.pose.position.y = float(y)
    return msg


def _pose_cov_stamped(x: float, y: float) -> PoseWithCovarianceStamped:
    msg = PoseWithCovarianceStamped()
    msg.pose.pose.position.x = float(x)
    msg.pose.pose.position.y = float(y)
    return msg


# -------------------------- happy paths --------------------------


def test_load_odometry(tmp_path: Path) -> None:
    bag = _write_bag(
        tmp_path / "bag_odom",
        [
            (
                "/odom",
                "nav_msgs/msg/Odometry",
                [_odom(0.0, 0.0), _odom(1.0, 0.0), _odom(2.0, 0.0)],
            )
        ],
    )
    trajs = load_trajectories_from_rosbag(bag)
    assert trajs == [[(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]]


def test_load_pose_stamped(tmp_path: Path) -> None:
    bag = _write_bag(
        tmp_path / "bag_pose",
        [
            (
                "/robot_pose",
                "geometry_msgs/msg/PoseStamped",
                [_pose_stamped(5.0, -1.0), _pose_stamped(5.5, -1.0)],
            )
        ],
    )
    trajs = load_trajectories_from_rosbag(bag)
    assert trajs == [[(5.0, -1.0), (5.5, -1.0)]]


def test_load_pose_with_covariance(tmp_path: Path) -> None:
    bag = _write_bag(
        tmp_path / "bag_amcl",
        [
            (
                "/amcl_pose",
                "geometry_msgs/msg/PoseWithCovarianceStamped",
                [_pose_cov_stamped(3.0, 3.0), _pose_cov_stamped(3.0, 3.5)],
            )
        ],
    )
    trajs = load_trajectories_from_rosbag(bag)
    assert trajs == [[(3.0, 3.0), (3.0, 3.5)]]


def test_multiple_topics_become_multiple_trajectories(tmp_path: Path) -> None:
    bag = _write_bag(
        tmp_path / "bag_two",
        [
            ("/odom_a", "nav_msgs/msg/Odometry", [_odom(0.0, 0.0), _odom(1.0, 0.0)]),
            ("/odom_b", "nav_msgs/msg/Odometry", [_odom(10.0, 10.0)]),
        ],
    )
    trajs = load_trajectories_from_rosbag(bag)
    # Topics are returned in alphabetical order.
    assert trajs == [[(0.0, 0.0), (1.0, 0.0)], [(10.0, 10.0)]]


def test_topic_filter_keeps_only_requested(tmp_path: Path) -> None:
    bag = _write_bag(
        tmp_path / "bag_filter",
        [
            ("/odom_a", "nav_msgs/msg/Odometry", [_odom(0.0, 0.0)]),
            ("/odom_b", "nav_msgs/msg/Odometry", [_odom(9.0, 9.0)]),
        ],
    )
    trajs = load_trajectories_from_rosbag(bag, topics=["/odom_b"])
    assert trajs == [[(9.0, 9.0)]]


def test_unsupported_message_types_are_silently_skipped(tmp_path: Path) -> None:
    # A bag with one supported topic + one unsupported (TF). Default behavior
    # should drop the unsupported topic and return only the supported one.
    pytest.importorskip("tf2_msgs.msg")
    from tf2_msgs.msg import TFMessage

    bag = _write_bag(
        tmp_path / "bag_mixed",
        [
            ("/odom", "nav_msgs/msg/Odometry", [_odom(1.0, 2.0)]),
            ("/tf", "tf2_msgs/msg/TFMessage", [TFMessage()]),
        ],
    )
    trajs = load_trajectories_from_rosbag(bag)
    assert trajs == [[(1.0, 2.0)]]


# --------------------------- error paths ---------------------------


def test_missing_bag_raises(tmp_path: Path) -> None:
    with pytest.raises(RosbagTrajectoryLoadError):
        load_trajectories_from_rosbag(tmp_path / "does_not_exist")


def test_requested_topic_not_in_bag_raises(tmp_path: Path) -> None:
    bag = _write_bag(
        tmp_path / "bag_missing",
        [("/odom", "nav_msgs/msg/Odometry", [_odom(0.0, 0.0)])],
    )
    with pytest.raises(RosbagTrajectoryLoadError):
        load_trajectories_from_rosbag(bag, topics=["/not_there"])


def test_requested_topic_with_unsupported_type_raises(tmp_path: Path) -> None:
    pytest.importorskip("tf2_msgs.msg")
    from tf2_msgs.msg import TFMessage

    bag = _write_bag(
        tmp_path / "bag_unsupported_request",
        [("/tf", "tf2_msgs/msg/TFMessage", [TFMessage()])],
    )
    with pytest.raises(RosbagTrajectoryLoadError):
        load_trajectories_from_rosbag(bag, topics=["/tf"])


# --------------------- integration with converter ---------------------


def test_rosbag_pipeline_through_topology_converter(tmp_path: Path) -> None:
    """A small recorded run should fall through the same converter the CSV
    pipeline uses and produce a non-empty topology graph."""
    # Two passes along the same corridor, one rectangular loop.
    msgs = (
        [_odom(x, 0.0) for x in range(0, 6)]
        + [_odom(x, 0.0) for x in range(5, -1, -1)]
        + [_odom(0.0, y) for y in range(0, 4)]
        + [_odom(x, 3.0) for x in range(0, 6)]
    )
    bag = _write_bag(
        tmp_path / "bag_loop",
        [("/odom", "nav_msgs/msg/Odometry", msgs)],
    )
    trajs = load_trajectories_from_rosbag(bag)
    assert len(trajs) == 1
    graph = topology_from_trajectories(trajs, eps=1.5, min_samples=2)
    assert len(graph.node_ids()) > 0
    assert len(graph.edge_ids()) > 0
