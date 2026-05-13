# Tutorial: planning a three-floor route

This tutorial walks through the full `semantic-toponav` workflow against
the bundled `examples/multi_floor_office.yaml` graph — load, inspect,
plan, customize the planner with semantic costs, emit waypoints, and
visualize the result both as a static PNG and as an interactive HTML
page.

The graph is small (17 nodes, 18 edges, 3 floors) but exercises every
feature of the library: semantic node/edge types, floor properties,
vertical elevator/stairs columns, and rooms that you'd actually want a
robot to visit.

If you haven't already:

```bash
git clone https://github.com/rsasaki0109/semantic-toponav.git
cd semantic-toponav
pip install -e '.[viz,viz_web]'   # matplotlib + pyvis
```

## 1. Load the graph

```python
from semantic_toponav.graph.serialization import load_graph

graph = load_graph("examples/multi_floor_office.yaml")
print(len(graph.node_ids()), "nodes,", len(graph.edge_ids()), "edges")
# 17 nodes, 18 edges
```

`load_graph` accepts `.yaml`, `.yml`, or `.json`. Invalid files raise
`GraphLoadError` with the offending line. The same function loaded from
the CLI:

```bash
semantic-toponav validate examples/multi_floor_office.yaml
```

## 2. Inspect what's inside

```python
print(graph.get_node("entrance"))
# TopologyNode(id='entrance', label='Entrance', type='entrance',
#              pose=Pose2D(x=0.0, y=0.0, ...), properties={'floor': 1})

# All elevator nodes, in floor order.
for nid in sorted(graph.node_ids()):
    n = graph.get_node(nid)
    if n.type == "elevator":
        print(n.id, n.properties["floor"])
# elevator_1f 1
# elevator_2f 2
# elevator_3f 3
```

Floors are encoded as a plain integer property — the planner picks them
up automatically and the floor-aware cost helpers below read the same
key. No bespoke "floor type" abstraction is needed.

## 3. Plan a default A* route

Goal: go from the `entrance` (1F) to the `exec_office_3f` (3F).

```python
from semantic_toponav.planner import plan_astar

path = plan_astar(graph, "entrance", "exec_office_3f")
print(" -> ".join(path))
# entrance -> corridor_1f -> lobby_1f -> stairs_1f -> stairs_2f
#           -> stairs_3f -> corridor_3f -> exec_office_3f
```

Default A* picks the stairs column: each stairs step costs `2.0`, less
than the elevator's `3.0` per segment, so the cumulative cost is lower
even though the path is one node longer. The next section shows how to
flip that preference with a single line of code.

![default plan](images/09_mf_default.png)

## 4. Add a semantic preference

Suppose this robot has a cart and *must* use the elevator. Combine
`prefer_elevator` (drops the elevator cost multiplier) with a
floor-aware A* heuristic (adds vertical distance to the goal estimate):

```python
from semantic_toponav.planner import (
    compose_costs, prefer_elevator, floor_aware_heuristic,
)

path = plan_astar(
    graph, "entrance", "exec_office_3f",
    cost_fn=compose_costs(prefer_elevator),
    heuristic_fn=floor_aware_heuristic(floor_height=2.0),
)
print(" -> ".join(path))
# entrance -> corridor_1f -> elevator_1f -> elevator_2f -> elevator_3f
#           -> corridor_3f -> exec_office_3f
```

![prefer elevator](images/10_mf_elevator.png)

The same flags are available from the CLI:

```bash
semantic-toponav plan examples/multi_floor_office.yaml \
    entrance exec_office_3f --prefer-elevator
```

The full set of stock cost helpers lives in
[`docs/interfaces.md`](interfaces.md#semantic-cost-functions). Each one
returns a `(edge) -> float` multiplier; compose them with
`compose_costs(a, b, c)`.

## 5. What about floor-change penalties?

For a robot that should aggressively minimize floor changes, swap the
cost function for `floor_change_penalty`:

```python
from semantic_toponav.planner import floor_change_penalty

path = plan_astar(
    graph, "entrance", "meeting_room_2f",
    cost_fn=floor_change_penalty(graph, penalty=50.0),
)
print(" -> ".join(path))
# entrance -> corridor_1f -> lobby_1f -> stairs_1f -> stairs_2f
#           -> corridor_2f -> meeting_room_2f
```

The `penalty=50` makes any edge that crosses floors prohibitively
expensive *unless* it's the only way to reach the goal. Pushed high
enough this is equivalent to "stay on this floor"; tune it for your
robot's actual cost of riding the elevator (battery, time, social
factors).

![floor change penalty](images/12_mf_floor_penalty.png)

## 6. Emit semantic waypoints

A node-id list is a planning artifact, not an instruction. Turn it into
a sequence the executor can actually consume. Re-using the elevator
path from section 4 so we exercise the `take_elevator` action:

```python
from semantic_toponav.waypoint import path_to_semantic_waypoints

elevator_path = plan_astar(
    graph, "entrance", "exec_office_3f",
    cost_fn=compose_costs(prefer_elevator),
    heuristic_fn=floor_aware_heuristic(floor_height=2.0),
)
waypoints = path_to_semantic_waypoints(graph, elevator_path)
for wp in waypoints:
    print(wp.action.ljust(16), wp.instruction)
# start            Start at Entrance
# proceed_through  Proceed through 1F Corridor
# take_elevator    Take elevator at Elevator A (1F)
# take_elevator    Take elevator at Elevator A (2F)
# take_elevator    Take elevator at Elevator A (3F)
# proceed_through  Proceed through 3F Corridor
# arrive           Arrive at Executive Office
```

Each `SemanticWaypoint` also carries `pose`, `node_id`, and the node's
`properties` — everything a downstream Nav2 / Autoware / behavior-tree
consumer needs. The ROS2 adapter
([`ros2/semantic_toponav_ros`](../ros2/README.md)) publishes these via a
custom `SemanticWaypointArray` message and ships a `nav2_demo_node` that
forwards them to `NavigateThroughPoses`.

## 7. Visualize: matplotlib

For static figures and embedded README images:

```python
from semantic_toponav.visualization import plot_graph

plot_graph(
    graph, path=path,
    title="floor_change_penalty=50: entrance → meeting_room_2f",
    floor_offset=8.0,      # stack 2F above 1F, 3F above 2F
    save_path="route.png",
)
```

The `floor_offset` parameter is what makes the vertical elevator and
stairs columns visible in the multi-floor figures above — without it,
all three floors would overlap.

## 8. Visualize: interactive HTML

For exploration with hover tooltips and draggable nodes:

```python
from semantic_toponav.visualization import save_interactive_html

save_interactive_html(graph, "viewer.html", path=path)
```

Open `viewer.html` in any browser. Hovering a node surfaces its type,
pose, and `properties`; hovering an edge shows type, cost, and the
`bidirectional` flag. The pink overlay is the planned path.

```bash
python examples/web_viewer_demo.py
xdg-open examples/multi_floor_viewer.html
```

## 9. Going further

- **CLI cheat sheet:** `semantic-toponav --help`, then
  `semantic-toponav plan --help` / `waypoints --help` / `plot --help`.
- **Memory layer:** revisit-aware cost functions and visit history are
  documented in the [README's memory section](../README.md#visit-history-memory).
- **Trajectory ingestion:** turn recorded runs (CSV or rosbag2) into
  topology graphs via `topology_from_trajectories` — see
  [Loading trajectories](interfaces.md#loading-trajectories-from-csv).
- **ROS2 integration:** end-to-end node graph and a worked Nav2 example
  live in [`ros2/README.md`](../ros2/README.md).
- **Public API reference:** [`docs/interfaces.md`](interfaces.md).

Found a rough edge? File an issue — see [`CONTRIBUTING.md`](../CONTRIBUTING.md).
