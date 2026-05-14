# Cost composition

The planner takes a `cost_fn` callable that maps each edge to a
non-negative number (or `math.inf` to block it). Composable cost
helpers let you express runtime intent — "the freight elevator is
down", "kitchen is closed after 22:00", "another agent has booked the
main corridor", "this is an accessibility-aware plan" — without
mutating the graph.

## Dynamic edge availability

Block specific edges or whole edge types at plan time:

```python
from semantic_toponav.planner import (
    plan_astar, block_edges, block_edge_types, compose_costs, prefer_elevator,
)

path = plan_astar(
    graph, "entrance", "exec_office_3f",
    cost_fn=compose_costs(
        prefer_elevator,
        block_edges(["elevator_link_freight"]),
        block_edge_types({"stairs_up"}),
    ),
)
```

```bash
semantic-toponav plan multi_floor_office.yaml entrance exec_office_3f \
    --block-edge-type stairs_up \
    --block-edge e_corridor_2f_to_office_2f
```

Both flags are repeatable. A blocked edge returns `math.inf` from the
cost function and `NoPathError` is raised if blocking removes the
last route.

## Time-of-day restrictions

Attach a `closed_during` property to an edge (or a node — closure
propagates to its incident edges) listing recurring HH:MM windows
when it's unavailable. An interval whose end is `<=` start wraps
midnight, so `["22:00", "06:00"]` is interpreted as the overnight
window.

```yaml
edges:
  - id: corridor_clean
    source: lobby
    target: corridor_main
    type: traversable
    properties:
      closed_during: [["14:00", "15:00"]]
nodes:
  - id: kitchen
    label: Kitchen
    type: room
    properties:
      closed_during: [["22:00", "06:00"]]
```

```bash
semantic-toponav plan office.yaml entrance kitchen --at-time 23:30
```

```python
from semantic_toponav.planner import plan_astar, time_aware
path = plan_astar(graph, "entrance", "kitchen",
                  cost_fn=time_aware(graph, at_time="23:30"))
```

`time_aware` composes with the other cost functions via `compose_costs`.

## Static multi-agent reservations

For the static "another agent has already booked this resource" case
(the online `SharedScheduler` is in [coordination.md](coordination.md)),
a reservation file is a flat list of `(resource_id, [start, end])`
entries. `resource_id` may name either a node OR an edge.

```yaml
# reservations.yaml
version: 1
reservations:
  - {resource_id: corridor_main, start: "10:00", end: "10:03", agent_id: robot_a}
  - {resource_id: elevator_E1,   start: "10:01", end: "10:05", agent_id: robot_a}
  - {resource_id: kitchen,       start: "12:00", end: "12:15", agent_id: robot_b}
```

```bash
semantic-toponav plan office.yaml entrance lab_1f \
    --reservations reservations.yaml --at-time 10:02
```

```python
from semantic_toponav.planner import (
    plan_astar, load_reservations, reservation_aware,
)

table = load_reservations("reservations.yaml")
path = plan_astar(graph, "entrance", "lab_1f",
                  cost_fn=reservation_aware(table, at_time="10:02"))
```

Reservations and time-of-day closures compose freely via
`compose_costs`, so an `--at-time` query can simultaneously honor
static cleaning windows on the graph and live claims from a shared
scheduler.

## Multi-floor navigation

When nodes carry a `floor` property, three additional cost helpers
and one A* heuristic become available:

```python
from semantic_toponav.planner import (
    plan_astar, floor_change_penalty, prefer_floor, same_floor_only,
    floor_aware_heuristic, compose_costs, prefer_elevator,
)

graph = load_graph("examples/multi_floor_office.yaml")

# Stay on floor 1 unless absolutely necessary.
path = plan_astar(graph, "entrance", "exec_office_3f",
                  cost_fn=floor_change_penalty(graph, penalty=50))

# Strictly within-floor planning.
path = plan_astar(graph, "kitchen_1f", "lab_1f",
                  cost_fn=same_floor_only(graph))

# Accessibility: prefer elevators with a floor-aware heuristic.
path = plan_astar(graph, "entrance", "exec_office_3f",
                  cost_fn=compose_costs(prefer_elevator),
                  heuristic_fn=floor_aware_heuristic(floor_height=2.0))
```

The same flags are wired into the CLI: `--prefer-floor N`,
`--floor-change-penalty P`, `--same-floor-only`.

```bash
python examples/run_multi_floor_demo.py
```

| default | elevator preference |
|---|---|
| ![mf default](images/09_mf_default.png) | ![mf elevator](images/10_mf_elevator.png) |
