"""Launch escape-room Gazebo sim + dynamic puzzle replanning + Nav2."""

from __future__ import annotations

import os
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, SetEnvironmentVariable
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def generate_launch_description() -> LaunchDescription:
    repo = _repo_root()
    pkg_share = Path(get_package_share_directory("semantic_toponav_ros"))

    world = repo / "examples/meshes/escape_room/gazebo/escape_room.world"
    map_yaml = repo / "examples/meshes/escape_room/gazebo/nav2/escape_room.yaml"
    urdf = repo / "examples/meshes/escape_room/gazebo/models/t0_robot/t0_robot.urdf"
    graph = repo / "examples/robot_escape_room.yaml"
    nav2_params = pkg_share / "config/escape_room/nav2_params.yaml"
    gazebo_models = repo / "examples/meshes/escape_room/gazebo/models"

    declare_escape_room = DeclareLaunchArgument("escape_room", default_value="true")
    declare_goal = DeclareLaunchArgument("goal_node", default_value="maintenance_exit")
    declare_start = DeclareLaunchArgument("start_node", default_value="holding_cell")
    declare_prefer_elevator = DeclareLaunchArgument("prefer_elevator", default_value="true")
    declare_avoid_restricted = DeclareLaunchArgument("avoid_restricted", default_value="true")
    declare_startup_delay = DeclareLaunchArgument("startup_delay_sec", default_value="20.0")

    gz_resource_path = SetEnvironmentVariable(
        name="GZ_SIM_RESOURCE_PATH",
        value=[str(gazebo_models), ":", os.environ.get("GZ_SIM_RESOURCE_PATH", "")],
    )

    gz_sim = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([FindPackageShare("ros_gz_sim"), "launch", "gz_sim.launch.py"])
        ),
        launch_arguments={"gz_args": f"-r {world}"}.items(),
    )

    bridge = Node(
        package="ros_gz_bridge",
        executable="parameter_bridge",
        arguments=[
            "/clock@rosgraph_msgs/msg/Clock[gz.msgs.Clock",
            "/cmd_vel@geometry_msgs/msg/Twist]gz.msgs.Twist",
            "/odom@nav_msgs/msg/Odometry[gz.msgs.Odometry",
            "/tf@tf2_msgs/msg/TFMessage[gz.msgs.Pose_V",
            "/scan@sensor_msgs/msg/LaserScan[gz.msgs.LaserScan",
        ],
        output="screen",
        parameters=[{"use_sim_time": True}],
    )

    map_odom = Node(
        package="tf2_ros",
        executable="static_transform_publisher",
        arguments=["0", "0", "0", "0", "0", "0", "map", "odom"],
        parameters=[{"use_sim_time": True}],
    )

    rsp = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        output="screen",
        parameters=[
            {"use_sim_time": True},
            {"robot_description": urdf.read_text(encoding="utf-8")},
        ],
    )

    nav2 = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([FindPackageShare("nav2_bringup"), "launch", "bringup_launch.py"])
        ),
        launch_arguments={
            "map": str(map_yaml),
            "use_sim_time": "true",
            "params_file": str(nav2_params),
            "autostart": "true",
            "use_localization": "false",
        }.items(),
    )

    nav2_demo = Node(
        package="semantic_toponav_ros",
        executable="nav2_demo",
        output="screen",
        parameters=[
            {"use_sim_time": True},
            {"waypoints_topic": "/semantic_toponav/waypoints"},
            {"action_name": "navigate_through_poses"},
            {"action_timeout_sec": 120.0},
            {"default_frame_id": "map"},
            {"continuous": LaunchConfiguration("escape_room")},
        ],
    )

    escape_room_runner = Node(
        package="semantic_toponav_ros",
        executable="escape_room_runner",
        output="screen",
        condition=IfCondition(LaunchConfiguration("escape_room")),
        parameters=[
            {"use_sim_time": True},
            {"graph_path": str(graph)},
            {"frame_id": "map"},
            {"startup_delay_sec": LaunchConfiguration("startup_delay_sec")},
            {"arrival_radius": 0.45},
        ],
    )

    waypoint_publisher = Node(
        package="semantic_toponav_ros",
        executable="waypoint_publisher",
        output="screen",
        condition=UnlessCondition(LaunchConfiguration("escape_room")),
        parameters=[
            {"use_sim_time": True},
            {"graph_path": str(graph)},
            {"start_node": LaunchConfiguration("start_node")},
            {"goal_node": LaunchConfiguration("goal_node")},
            {"output_format": "msg"},
            {"frame_id": "map"},
            {"prefer_elevator": LaunchConfiguration("prefer_elevator")},
            {"avoid_restricted": LaunchConfiguration("avoid_restricted")},
        ],
    )

    return LaunchDescription(
        [
            declare_escape_room,
            declare_goal,
            declare_start,
            declare_prefer_elevator,
            declare_avoid_restricted,
            declare_startup_delay,
            gz_resource_path,
            gz_sim,
            bridge,
            map_odom,
            rsp,
            nav2,
            nav2_demo,
            escape_room_runner,
            waypoint_publisher,
        ]
    )
