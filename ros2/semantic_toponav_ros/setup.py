from setuptools import find_packages, setup

package_name = "semantic_toponav_ros"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools", "semantic-toponav"],
    zip_safe=True,
    maintainer="semantic-toponav contributors",
    maintainer_email="opensource@example.com",
    description="ROS2 adapter for semantic-toponav.",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": [
            "graph_loader = semantic_toponav_ros.graph_loader_node:main",
            "waypoint_publisher = semantic_toponav_ros.waypoint_publisher_node:main",
        ],
    },
)
