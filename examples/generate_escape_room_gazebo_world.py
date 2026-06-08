"""Generate a Gazebo / gz-sim world for the Robot Escape Room facility.

Visual mesh: ``escape_room_scene.obj`` (furnished interior export).
Collision: furnished interior boxes (walls, floors, props).

    PYTHONPATH=. python3 examples/generate_escape_room_gazebo_world.py
"""

from __future__ import annotations

import shutil
import sys
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "examples"))

from escape_room_interior import foxglove_furnished_cubes
from escape_room_meshes import SCENE_OBJ

from semantic_toponav.graph.serialization import load_graph

GRAPH = ROOT / "examples" / "robot_escape_room.yaml"
GAZEBO_DIR = ROOT / "examples" / "meshes" / "escape_room" / "gazebo"
MODEL_DIR = GAZEBO_DIR / "models" / "escape_room_facility"
ROBOT_DIR = GAZEBO_DIR / "models" / "t0_robot"
WORLD_PATH = GAZEBO_DIR / "escape_room.world"
SPAWN = (0.0, 0.0, 0.05)  # holding_cell centre, wheel radius clearance


def _pose(x: float, y: float, z: float) -> str:
    return f"{x:.4f} {y:.4f} {z:.4f} 0 0 0"


def _write_model_config() -> None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    (MODEL_DIR / "model.config").write_text(
        textwrap.dedent(
            """\
            <?xml version="1.0"?>
            <model>
              <name>escape_room_facility</name>
              <version>1.0</version>
              <sdf version="1.8">model.sdf</sdf>
              <author>
                <name>RobotEscapeRoom</name>
                <email>semantic-toponav@example.com</email>
              </author>
              <description>Furnished escape-room facility mesh + interior collision boxes.</description>
            </model>
            """
        ),
        encoding="utf-8",
    )


def _write_model_sdf(graph: Any) -> None:
    mesh_dst = MODEL_DIR / "meshes" / "escape_room_scene.obj"
    mesh_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SCENE_OBJ, mesh_dst)

    model = ET.Element("sdf", version="1.8")
    m = ET.SubElement(model, "model", name="escape_room_facility")
    ET.SubElement(m, "static").text = "true"
    link = ET.SubElement(m, "link", name="facility")

    visual = ET.SubElement(link, "visual", name="mesh")
    vgeom = ET.SubElement(visual, "geometry")
    mesh = ET.SubElement(vgeom, "mesh")
    ET.SubElement(mesh, "uri").text = "meshes/escape_room_scene.obj"
    ET.SubElement(mesh, "scale").text = "1 1 1"

    for idx, cube in enumerate(foxglove_furnished_cubes(graph, set())):
        sx, sy, sz = cube.size
        if sx < 1e-4 or sy < 1e-4 or sz < 1e-4:
            continue
        col = ET.SubElement(link, "collision", name=f"box_{idx}")
        ET.SubElement(col, "pose").text = _pose(*cube.center)
        cgeom = ET.SubElement(col, "geometry")
        box = ET.SubElement(cgeom, "box")
        ET.SubElement(box, "size").text = f"{sx:.4f} {sy:.4f} {sz:.4f}"

    tree = ET.ElementTree(model)
    ET.indent(tree, space="  ")
    tree.write(MODEL_DIR / "model.sdf", encoding="unicode", xml_declaration=True)


def _write_robot_model() -> None:
    ROBOT_DIR.mkdir(parents=True, exist_ok=True)
    (ROBOT_DIR / "model.config").write_text(
        textwrap.dedent(
            """\
            <?xml version="1.0"?>
            <model>
              <name>t0_robot</name>
              <version>1.0</version>
              <sdf version="1.8">model.sdf</sdf>
              <author>
                <name>RobotEscapeRoom</name>
                <email>semantic-toponav@example.com</email>
              </author>
              <description>T-0 diff-drive robot for escape-room Gazebo sim.</description>
            </model>
            """
        ),
        encoding="utf-8",
    )
    (ROBOT_DIR / "model.sdf").write_text(
        textwrap.dedent(
            """\
            <?xml version="1.0"?>
            <sdf version="1.8">
              <model name="t0_robot">
                <link name="base_link">
                  <pose>0 0 0.06 0 0 0</pose>
                  <inertial>
                    <mass>8.0</mass>
                    <inertia>
                      <ixx>0.08</ixx><iyy>0.12</iyy><izz>0.14</izz>
                    </inertia>
                  </inertial>
                  <collision name="body">
                    <geometry><box><size>0.36 0.28 0.12</size></box></geometry>
                  </collision>
                  <visual name="body">
                    <geometry><box><size>0.36 0.28 0.12</size></box></geometry>
                    <material>
                      <ambient>0.15 0.55 0.85 1</ambient>
                      <diffuse>0.25 0.75 1.0 1</diffuse>
                    </material>
                  </visual>
                  <visual name="nose">
                    <pose>0.18 0 0 0 0 0</pose>
                    <geometry><box><size>0.04 0.08 0.04</size></box></geometry>
                    <material>
                      <ambient>0.9 0.9 0.2 1</ambient>
                      <diffuse>1 1 0.35 1</diffuse>
                    </material>
                  </visual>
                  <sensor name="lidar" type="gpu_lidar">
                    <pose>0.12 0 0.06 0 0 0</pose>
                    <topic>scan</topic>
                    <gz_frame_id>laser_link</gz_frame_id>
                    <update_rate>10</update_rate>
                    <lidar>
                      <scan>
                        <horizontal>
                          <samples>720</samples>
                          <resolution>1</resolution>
                          <min_angle>-3.14159265</min_angle>
                          <max_angle>3.14159265</max_angle>
                        </horizontal>
                      </scan>
                      <range>
                        <min>0.12</min>
                        <max>12.0</max>
                        <resolution>0.01</resolution>
                      </range>
                    </lidar>
                    <always_on>1</always_on>
                    <visualize>true</visualize>
                  </sensor>
                </link>

                <link name="left_wheel">
                  <pose>0 0.14 0.05 1.5707 0 0</pose>
                  <inertial><mass>0.5</mass></inertial>
                  <collision name="collision">
                    <geometry><cylinder><radius>0.05</radius><length>0.04</length></cylinder></geometry>
                  </collision>
                  <visual name="visual">
                    <geometry><cylinder><radius>0.05</radius><length>0.04</length></cylinder></geometry>
                    <material><ambient>0.1 0.1 0.1 1</ambient><diffuse>0.15 0.15 0.15 1</diffuse></material>
                  </visual>
                </link>
                <joint name="left_wheel_joint" type="revolute">
                  <parent>base_link</parent><child>left_wheel</child>
                  <axis><xyz>0 1 0</xyz></axis>
                </joint>

                <link name="right_wheel">
                  <pose>0 -0.14 0.05 1.5707 0 0</pose>
                  <inertial><mass>0.5</mass></inertial>
                  <collision name="collision">
                    <geometry><cylinder><radius>0.05</radius><length>0.04</length></cylinder></geometry>
                  </collision>
                  <visual name="visual">
                    <geometry><cylinder><radius>0.05</radius><length>0.04</length></cylinder></geometry>
                    <material><ambient>0.1 0.1 0.1 1</ambient><diffuse>0.15 0.15 0.15 1</diffuse></material>
                  </visual>
                </link>
                <joint name="right_wheel_joint" type="revolute">
                  <parent>base_link</parent><child>right_wheel</child>
                  <axis><xyz>0 1 0</xyz></axis>
                </joint>

                <link name="caster">
                  <pose>-0.14 0 0.03 0 0 0</pose>
                  <inertial><mass>0.2</mass></inertial>
                  <collision name="collision">
                    <geometry><sphere><radius>0.03</radius></sphere></geometry>
                  </collision>
                  <visual name="visual">
                    <geometry><sphere><radius>0.03</radius></sphere></geometry>
                    <material><ambient>0.2 0.2 0.2 1</ambient><diffuse>0.3 0.3 0.3 1</diffuse></material>
                  </visual>
                </link>
                <joint name="caster_joint" type="ball">
                  <parent>base_link</parent><child>caster</child>
                </joint>

                <plugin
                  filename="libgz-sim-diff-drive-system.so"
                  name="gz::sim::systems::DiffDrive">
                  <left_joint>left_wheel_joint</left_joint>
                  <right_joint>right_wheel_joint</right_joint>
                  <wheel_separation>0.28</wheel_separation>
                  <wheel_radius>0.05</wheel_radius>
                  <topic>/cmd_vel</topic>
                  <odom_topic>odom</odom_topic>
                  <tf_topic>tf</tf_topic>
                  <frame_id>odom</frame_id>
                  <child_frame_id>base_link</child_frame_id>
                  <publish_odom_tf>true</publish_odom_tf>
                  <odom_publish_frequency>30</odom_publish_frequency>
                </plugin>
              </model>
            </sdf>
            """
        ),
        encoding="utf-8",
    )
    (ROBOT_DIR / "t0_robot.urdf").write_text(
        textwrap.dedent(
            """\
            <?xml version="1.0"?>
            <robot name="t0_robot">
              <link name="base_footprint"/>
              <link name="base_link">
                <visual>
                  <geometry><box size="0.36 0.28 0.12"/></geometry>
                  <material name="blue"><color rgba="0.25 0.75 1.0 1"/></material>
                </visual>
                <collision>
                  <geometry><box size="0.36 0.28 0.12"/></geometry>
                </collision>
                <inertial>
                  <mass value="8.0"/>
                  <inertia ixx="0.08" ixy="0" ixz="0" iyy="0.12" iyz="0" izz="0.14"/>
                </inertial>
              </link>
              <joint name="base_footprint_joint" type="fixed">
                <parent link="base_footprint"/><child link="base_link"/>
                <origin xyz="0 0 0.05" rpy="0 0 0"/>
              </joint>
              <link name="left_wheel">
                <visual>
                  <origin xyz="0 0 0" rpy="1.5707 0 0"/>
                  <geometry><cylinder radius="0.05" length="0.04"/></geometry>
                  <material name="black"><color rgba="0.15 0.15 0.15 1"/></material>
                </visual>
                <collision>
                  <origin xyz="0 0 0" rpy="1.5707 0 0"/>
                  <geometry><cylinder radius="0.05" length="0.04"/></geometry>
                </collision>
              </link>
              <joint name="left_wheel_joint" type="continuous">
                <parent link="base_link"/><child link="left_wheel"/>
                <origin xyz="0 0.14 0.05" rpy="0 0 0"/>
                <axis xyz="0 1 0"/>
              </joint>
              <link name="right_wheel">
                <visual>
                  <origin xyz="0 0 0" rpy="1.5707 0 0"/>
                  <geometry><cylinder radius="0.05" length="0.04"/></geometry>
                  <material name="black"><color rgba="0.15 0.15 0.15 1"/></material>
                </visual>
                <collision>
                  <origin xyz="0 0 0" rpy="1.5707 0 0"/>
                  <geometry><cylinder radius="0.05" length="0.04"/></geometry>
                </collision>
              </link>
              <joint name="right_wheel_joint" type="continuous">
                <parent link="base_link"/><child link="right_wheel"/>
                <origin xyz="0 -0.14 0.05" rpy="0 0 0"/>
                <axis xyz="0 1 0"/>
              </joint>
              <link name="laser_link"/>
              <joint name="laser_joint" type="fixed">
                <parent link="base_link"/><child link="laser_link"/>
                <origin xyz="0.12 0 0.06" rpy="0 0 0"/>
              </joint>
            </robot>
            """
        ),
        encoding="utf-8",
    )


def _write_world() -> None:
    sx, sy, sz = SPAWN
    world_xml = textwrap.dedent(
        f"""\
        <?xml version="1.0"?>
        <sdf version="1.8">
          <world name="escape_room">
            <gravity>0 0 -9.8</gravity>
            <physics name="default" type="ode">
              <max_step_size>0.004</max_step_size>
              <real_time_factor>1</real_time_factor>
            </physics>

            <plugin filename="libgz-sim-sensors-system.so"
                    name="gz::sim::systems::Sensors">
              <render_engine>ogre2</render_engine>
            </plugin>

            <light name="sun" type="directional">
              <pose>0 0 10 0 0 0</pose>
              <diffuse>0.9 0.9 0.85 1</diffuse>
              <specular>0.3 0.3 0.3 1</specular>
              <direction>-0.3 0.2 -1</direction>
            </light>

            <model name="ground">
              <static>true</static>
              <link name="link">
                <collision name="collision">
                  <geometry>
                    <plane>
                      <normal>0 0 1</normal>
                      <size>120 120</size>
                    </plane>
                  </geometry>
                </collision>
                <visual name="visual">
                  <geometry>
                    <plane>
                      <normal>0 0 1</normal>
                      <size>120 120</size>
                    </plane>
                  </geometry>
                  <material>
                    <ambient>0.15 0.16 0.18 1</ambient>
                    <diffuse>0.22 0.24 0.28 1</diffuse>
                  </material>
                </visual>
              </link>
            </model>

            <include>
              <uri>model://escape_room_facility</uri>
              <pose>0 0 0 0 0 0</pose>
            </include>

            <include>
              <uri>model://t0_robot</uri>
              <name>t0</name>
              <pose>{sx:.4f} {sy:.4f} {sz:.4f} 0 0 0</pose>
            </include>

            <model name="overview_camera">
              <static>true</static>
              <link name="link">
                <pose>14 -10 24 0 0.65 0.85</pose>
                <sensor name="camera" type="camera">
                  <camera>
                    <horizontal_fov>1.05</horizontal_fov>
                    <image><width>1280</width><height>720</height></image>
                    <clip><near>0.1</near><far>200</far></clip>
                  </camera>
                  <topic>/escape_room/camera</topic>
                  <update_rate>12</update_rate>
                </sensor>
              </link>
            </model>
          </world>
        </sdf>
        """
    )
    GAZEBO_DIR.mkdir(parents=True, exist_ok=True)
    WORLD_PATH.write_text(world_xml, encoding="utf-8")


def _write_readme(cube_count: int) -> None:
    readme = GAZEBO_DIR / "README.md"
    readme.write_text(
        textwrap.dedent(
            f"""\
            # Robot Escape Room — Gazebo / gz-sim world

            Generated from ``escape_room_scene.obj`` + {cube_count} interior collision boxes.

            ## Regenerate

            ```bash
            PYTHONPATH=. python3 examples/generate_escape_room_meshes.py
            PYTHONPATH=. python3 examples/generate_escape_room_gazebo_world.py
            ```

            ## Run (Gazebo Harmonic / gz-sim)

            ```bash
            export GZ_SIM_RESOURCE_PATH="$(pwd)/examples/meshes/escape_room/gazebo/models:$GZ_SIM_RESOURCE_PATH"
            gz sim examples/meshes/escape_room/gazebo/escape_room.world
            ```

            Robot **T-0** spawns at the holding cell `({SPAWN[0]:.1f}, {SPAWN[1]:.1f}, {SPAWN[2]:.2f})`
            in the `map` frame. Drive with `/cmd_vel` (DiffDrive plugin).

            ## Nav2 + ros_gz_bridge (full stack)

            One-shot launch (Gazebo Harmonic + Nav2 + semantic waypoints):

            ```bash
            pip install -e .
            cd ros2 && colcon build --packages-select semantic_toponav_msgs semantic_toponav_ros
            source install/setup.bash
            cd ..
            PYTHONPATH=. python3 examples/generate_escape_room_nav2_map.py
            ./scripts/run_escape_room_gz_nav2.sh
            ```

            Or manually:

            ```bash
            ros2 launch semantic_toponav_ros escape_room_gz_nav2.launch.py \\
              goal_node:=maintenance_exit prefer_elevator:=true avoid_restricted:=true
            ```

            Requires ROS 2 Jazzy/Humble with ``nav2_bringup``, ``ros_gz_sim``, and
            ``ros_gz_bridge``.

            ## Record Gazebo MP4

            ```bash
            ./scripts/record_escape_room_gz_sim.sh
            # → docs/images/robot_escape_room_gz.mp4
            ```

            ## Nav2 GeoJSON only

            Export the escape-room topology for Nav2 Route Server:

            ```bash
            python examples/export_escape_room_nav2_route.py
            ```

            Then load `examples/data/nav2/escape_room_graph.geojson` in Nav2, or publish
            semantic waypoints via `ros2 run semantic_toponav_ros waypoint_publisher` with
            `graph_path:=$PWD/examples/robot_escape_room.yaml`.

            ## Files

            | Path | Purpose |
            |---|---|
            | `escape_room.world` | World with ground, sun, facility + T-0 robot |
            | `models/escape_room_facility/model.sdf` | Visual mesh + collision boxes |
            | `models/escape_room_facility/meshes/escape_room_scene.obj` | Furnished interior mesh |
            | `models/t0_robot/model.sdf` | Diff-drive T-0 robot (gz-sim) |
            | `models/t0_robot/t0_robot.urdf` | Same robot for ROS 2 / Nav2 |
            """
        ),
        encoding="utf-8",
    )


def main() -> None:
    graph = load_graph(GRAPH)
    _write_model_config()
    _write_model_sdf(graph)
    _write_robot_model()
    _write_world()
    n = len(foxglove_furnished_cubes(graph, set()))
    _write_readme(n)
    print(f"wrote Gazebo world -> {WORLD_PATH.relative_to(ROOT)}")
    print(f"model -> {MODEL_DIR.relative_to(ROOT)} ({n} collision boxes)")


if __name__ == "__main__":
    main()
