"""Pytest configuration shared across the test suite."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `pytest` to be run from the repository root without installing the
# package, so contributors can iterate quickly.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Expose the ROS2 adapter's pure-Python helpers (e.g. msg conversion) without
# requiring a sourced ROS environment. Only the dataclass-only modules will be
# importable; anything that touches rclpy/`semantic_toponav_msgs` is gated by
# lazy imports inside the helpers themselves.
ROS_PKG = ROOT / "ros2" / "semantic_toponav_ros"
if ROS_PKG.exists() and str(ROS_PKG) not in sys.path:
    sys.path.insert(0, str(ROS_PKG))
