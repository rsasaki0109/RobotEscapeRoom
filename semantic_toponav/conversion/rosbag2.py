"""Load 2D trajectory logs directly from a ROS2 ``rosbag2`` recording.

This is the rosbag2 counterpart of :mod:`semantic_toponav.conversion.csv_io`:
it produces the same ``list[list[(x, y)]]`` shape that
:func:`semantic_toponav.conversion.topology_from_trajectories` expects, so a
recorded run can be turned into a topology graph without going through CSV.

Supported message types (everything else on the bag is silently ignored):

- ``nav_msgs/msg/Odometry``                     -> ``pose.pose.position.{x,y}``
- ``geometry_msgs/msg/PoseStamped``             -> ``pose.position.{x,y}``
- ``geometry_msgs/msg/PoseWithCovarianceStamped`` -> ``pose.pose.position.{x,y}``

Each subscribed topic becomes one trajectory in the returned list, ordered
by topic name. ``rosbag2_py``, ``rclpy``, and the message packages are
imported lazily so this module can sit in the package without dragging a
ROS2 install into the regular test/import path.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

Point = tuple[float, float]

# Map from ROS2 message type name to a callable that pulls (x, y) out of an
# already-deserialized message instance. Add a row here to support a new type.
_POINT_EXTRACTORS: dict[str, Callable[[Any], Point]] = {
    "nav_msgs/msg/Odometry": lambda m: (
        float(m.pose.pose.position.x),
        float(m.pose.pose.position.y),
    ),
    "geometry_msgs/msg/PoseStamped": lambda m: (
        float(m.pose.position.x),
        float(m.pose.position.y),
    ),
    "geometry_msgs/msg/PoseWithCovarianceStamped": lambda m: (
        float(m.pose.pose.position.x),
        float(m.pose.pose.position.y),
    ),
}

SUPPORTED_MESSAGE_TYPES: tuple[str, ...] = tuple(_POINT_EXTRACTORS.keys())


class RosbagTrajectoryLoadError(Exception):
    """Raised when a rosbag2 trajectory recording cannot be loaded."""


def load_trajectories_from_rosbag(
    path: str | Path,
    *,
    topics: Iterable[str] | None = None,
    storage_id: str = "sqlite3",
    serialization_format: str = "cdr",
) -> list[list[Point]]:
    """Load 2D trajectories from a rosbag2 recording.

    Parameters
    ----------
    path:
        Path to the bag. May point at the directory produced by
        ``ros2 bag record`` (the recommended form, in which case
        ``metadata.yaml`` is read alongside the ``.db3`` files) or directly
        at a single ``.db3`` file.
    topics:
        Only read these topic names. ``None`` means "read every topic whose
        message type is in :data:`SUPPORTED_MESSAGE_TYPES`".
    storage_id, serialization_format:
        Passed through to ``rosbag2_py``. The defaults match what
        ``ros2 bag record`` produces.

    Returns
    -------
    list[list[(x, y)]]
        One trajectory per topic, in alphabetical topic order. Topics that
        produced no messages are dropped.
    """
    try:
        import rosbag2_py
        from rclpy.serialization import deserialize_message
        from rosidl_runtime_py.utilities import get_message
    except ImportError as exc:  # pragma: no cover - exercised only without ROS2
        raise RosbagTrajectoryLoadError(
            "loading rosbag2 recordings requires `rosbag2_py`, `rclpy`, and "
            "`rosidl_runtime_py` to be importable. Source a ROS2 environment "
            f"(e.g. `source /opt/ros/<distro>/setup.bash`) first. ({exc})"
        ) from exc

    bag_path = Path(path)
    if not bag_path.exists():
        raise RosbagTrajectoryLoadError(f"rosbag path not found: {bag_path}")

    storage_options = rosbag2_py.StorageOptions(
        uri=str(bag_path), storage_id=storage_id
    )
    converter_options = rosbag2_py.ConverterOptions(
        input_serialization_format=serialization_format,
        output_serialization_format=serialization_format,
    )

    reader = rosbag2_py.SequentialReader()
    try:
        reader.open(storage_options, converter_options)
    except Exception as exc:  # rosbag2_py raises a generic RuntimeError
        raise RosbagTrajectoryLoadError(
            f"failed to open rosbag at {bag_path}: {exc}"
        ) from exc

    type_by_topic: dict[str, str] = {
        t.name: t.type for t in reader.get_all_topics_and_types()
    }

    requested = set(topics) if topics is not None else None
    if requested is not None:
        unknown = requested - type_by_topic.keys()
        if unknown:
            raise RosbagTrajectoryLoadError(
                f"requested topics not present in {bag_path}: {sorted(unknown)}"
            )

    # Decide which topics we'll actually pull from.
    selected: dict[str, str] = {}
    for name, type_name in type_by_topic.items():
        if requested is not None and name not in requested:
            continue
        if type_name not in _POINT_EXTRACTORS:
            if requested is not None:
                raise RosbagTrajectoryLoadError(
                    f"topic {name!r} has unsupported message type {type_name!r}. "
                    f"Supported: {list(SUPPORTED_MESSAGE_TYPES)}"
                )
            continue
        selected[name] = type_name

    if not selected:
        return []

    # Cache the deserialization target class once per topic.
    msg_classes: dict[str, type] = {
        name: get_message(type_name) for name, type_name in selected.items()
    }

    points_by_topic: dict[str, list[Point]] = {name: [] for name in selected}
    while reader.has_next():
        topic, data, _stamp = reader.read_next()
        if topic not in selected:
            continue
        msg = deserialize_message(data, msg_classes[topic])
        extractor = _POINT_EXTRACTORS[selected[topic]]
        points_by_topic[topic].append(extractor(msg))

    return [points_by_topic[name] for name in sorted(points_by_topic) if points_by_topic[name]]
