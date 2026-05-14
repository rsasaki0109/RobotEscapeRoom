# Map / log → topology

How to build a `TopologyGraph` from external data sources. Three
entry points: 2D occupancy grids, raw trajectories, and ROS-style
map_server bundles.

## Occupancy grid → topology

A skeletonization-based converter turns a 2D occupancy grid into a
topology graph automatically. Endpoints become `endpoint` nodes,
junctions become `intersection` nodes, and everything in between
becomes `corridor` edges with cost proportional to skeleton length.

```bash
pip install -e '.[viz,map]'
python examples/occupancy_to_topology.py
```

```python
import numpy as np
from semantic_toponav.conversion import topology_from_occupancy

grid = np.zeros((30, 60), dtype=bool)
grid[8:11, 4:55] = True       # horizontal corridor
grid[22:25, 4:55] = True      # second horizontal corridor
grid[8:25, 12:14] = True      # vertical link
graph = topology_from_occupancy(grid, resolution=0.25)
```

| occupancy grid + auto-generated topology | planned path overlay |
|-----------------------------------------|----------------------|
| ![grid](images/05_occupancy_graph.png) | ![path](images/06_occupancy_graph_with_path.png) |

### Door / threshold detection

`mark_doors_by_clearance` runs a distance transform on the binarized
grid and flags narrow-passage nodes and edges. Each node-with-cells
gets a `min_clearance` (meters) property; nodes and edges whose
clearance is below an explicit or auto-percentile threshold get
re-typed `door`.

```python
from semantic_toponav.conversion import (
    mark_doors_by_clearance, topology_from_occupancy,
)
graph = topology_from_occupancy(grid, resolution=0.05)
result = mark_doors_by_clearance(graph, grid, resolution=0.05,
                                 clearance_threshold=0.6)  # meters
print(result.node_ids, result.edge_ids)
```

### Region segmentation (room-aware labels)

`annotate_regions` runs connected-component labeling on free space and
stamps `region_id` on every node-with-cells. When `clearance_threshold`
(or `clearance_percentile`) is supplied the same distance transform
used by the door detector pinches narrow passages off, so each room
becomes a distinct component instead of one giant blob spanning the
whole floor.

```python
from semantic_toponav.conversion import (
    annotate_regions, topology_from_occupancy,
)
graph = topology_from_occupancy(grid, resolution=0.05)
result = annotate_regions(graph, grid, resolution=0.05,
                          clearance_threshold=0.6)  # pinch doorways
for rid, info in result.regions.items():
    print(rid, info.area_m2, info.centroid_world)
```

### Occupancy pipeline from the CLI

The same three steps are exposed as subcommands so you can go from a
ROS `map_server` bundle to a room-aware graph without writing Python.
In-place mutations write a `.bak` first (pass `--no-backup` to skip),
and either `--clearance-threshold METERS` or `--clearance-percentile P`
(but not both) pins the doorway-pinching cutoff.

```sh
semantic-toponav from-occupancy map.yaml --out office.yaml
semantic-toponav mark-doors office.yaml map.yaml \
    --clearance-threshold 0.6 --in-place
semantic-toponav annotate-regions office.yaml map.yaml \
    --clearance-threshold 0.6 --show-regions --in-place
```

### Compacting a noisy graph

Skeletonization sometimes produces tightly-clustered endpoint nodes
(a few cells apart) and multiple near-parallel edges between the same
pair of clusters. `compact` is a lossy pass that merges nearby posed
nodes into a single representative (centroid pose) and collapses
same-endpoint duplicate edges. Use `--keep-strategy` to control which
parallel edge survives, and `--edge-cost-tolerance` to refuse the
collapse when the candidate edges differ in length beyond your taste.

```sh
semantic-toponav compact office.yaml \
    --endpoint-tolerance 0.3 --in-place

semantic-toponav compact office.yaml \
    --endpoint-tolerance 0.3 --edge-cost-tolerance 1.0 \
    --keep-strategy shortest --out compacted.yaml
```

## Trajectory log → topology

When you don't have an occupancy grid but you do have logs of where
the robot went (or where users / pedestrians walked), you can induce
a topology directly from those tracks. Points are clustered greedily;
each dense cluster becomes a node; consecutive cluster transitions
become edges with a `traversal_count` property — higher counts mark
routes the robot took repeatedly.

```python
from semantic_toponav.conversion import topology_from_trajectories

graph = topology_from_trajectories(
    [traj_a, traj_b],   # each traj is a sequence of (x, y)
    eps=0.5,            # cluster radius in meters
    min_samples=3,      # drop sparser clusters as noise
)
```

```bash
python examples/trajectory_to_topology.py
```

![trajectory to topology](images/08_trajectory_topology.png)

Trajectories can also be loaded from CSV (stdlib only, no pandas):

```python
from semantic_toponav.conversion import load_trajectories_from_csv

trajs = load_trajectories_from_csv(
    "examples/sample_trajectories.csv",
    x_column="x",
    y_column="y",
    trajectory_column="trajectory_id",   # grouping column, optional
)
```

Both header-based (`x`, `y`, `trajectory_id`) and headerless / positional
(integer column indices) layouts are supported. Run
`python examples/load_csv_demo.py` for an end-to-end demo:

![csv to topology](images/13_csv_trajectory.png)

### Loading trajectories directly from a rosbag2 recording

If you have a ROS2 environment sourced, you can skip the CSV step
entirely and read trajectories straight out of a `ros2 bag record`
output:

```python
from semantic_toponav.conversion import (
    load_trajectories_from_rosbag,
    topology_from_trajectories,
)

trajs = load_trajectories_from_rosbag("my_run")    # directory or .db3 file
graph = topology_from_trajectories(trajs, eps=0.5, min_samples=3)
```

Supported topic types are `nav_msgs/msg/Odometry`,
`geometry_msgs/msg/PoseStamped`, and
`geometry_msgs/msg/PoseWithCovarianceStamped`; each topic becomes one
trajectory in the returned list. The loader imports `rosbag2_py` and
`rclpy` lazily, so the rest of the package keeps working without ROS2
installed.

## Loading ROS map_server bundles

`semantic-toponav` can load the standard `map_server` YAML + PGM/PNG/BMP
pair used by ROS Nav2:

```python
from semantic_toponav.conversion import load_occupancy_map, topology_from_occupancy

m = load_occupancy_map("examples/sample_map.yaml")
graph = topology_from_occupancy(m.free_mask, resolution=m.resolution, origin=m.origin)
```

`negate`, `free_thresh`, and `occupied_thresh` are honored. The bundled
`examples/sample_map.{yaml,pgm}` is small enough to skim and produces a
topology with rooms, a main corridor, and a planned route:

```bash
python examples/load_map_demo.py
```

![sample map topology](images/07_sample_map_topology.png)
