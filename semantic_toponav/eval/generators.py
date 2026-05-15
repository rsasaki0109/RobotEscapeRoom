"""Deterministic graph + fleet-request generators for synthetic evals.

Each generator is seeded — the same ``(generator, seed, parameters)``
always reproduces the same graph or request list. That lets the eval
suite compare strategies on identical inputs and lets CI assert that a
"smoke" run produces a stable signature.

The graphs here are intentionally *small and stylized*. They are not
trying to mimic real office floor-plans (the worked example
``examples/indoor_office.yaml`` already covers that); they isolate one
structural property at a time so the strategy-comparison numbers tell
us something interpretable:

* :func:`chain_graph` — nodes connected in a line. Only one route
  exists between any pair, so coordination must succeed by *timing*
  rather than route diversity. Stress-tests reservation rollback and
  ordering search.
* :func:`star_graph` — single hub plus leaves. Every request crosses
  the hub. The hub is the only contention point; ideal for showing
  fairness ordering versus pure FCFS.
* :func:`doorway_graph` — two rooms joined by a narrow doorway edge.
  Capacity is one agent at a time through the doorway. Canonical
  bottleneck scenario.
* :func:`multi_floor_office` — multi-floor topology with stairs +
  elevator transitions. Exercises ``floor_change_penalty`` and the
  interaction with reservations on floor-crossing edges.

Plus two request-side generators:

* :func:`generate_fleet_requests` — random ``start → goal`` pairs
  with optional priorities / deadlines.
* :func:`generate_static_reservations` — pre-existing holds dropped
  on a scheduler to simulate "the room already had someone in it
  before the planner ran".
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import time

from semantic_toponav.coordination.fleet import FleetRequest
from semantic_toponav.coordination.scheduler import ClaimRequest, SharedScheduler
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import TopologyEdge, TopologyNode


def _add_corridor_edge(
    graph: TopologyGraph,
    eid: str,
    a: str,
    b: str,
    *,
    cost: float = 1.0,
) -> None:
    """Convenience: add a bidirectional ``corridor`` edge a↔b."""
    graph.add_edge(
        TopologyEdge(
            id=eid,
            source=a,
            target=b,
            type="corridor",
            cost=cost,
            bidirectional=True,
        )
    )


def chain_graph(n_nodes: int, *, seed: int = 0) -> TopologyGraph:
    """Linear chain of ``n_nodes`` nodes connected by corridor edges.

    Nodes are labelled ``n0`` .. ``n{n_nodes-1}``; edges follow the
    pattern ``e0_1``, ``e1_2``, .... The seed is currently unused (the
    structure is fully determined by ``n_nodes``) but kept in the
    signature so every generator shares one shape.
    """
    if n_nodes < 2:
        raise ValueError(f"chain_graph requires n_nodes >= 2, got {n_nodes}")
    _ = seed  # reserved for future variation
    g = TopologyGraph()
    for i in range(n_nodes):
        g.add_node(
            TopologyNode(
                id=f"n{i}",
                label=f"Node {i}",
                type="room",
            )
        )
    for i in range(n_nodes - 1):
        _add_corridor_edge(g, f"e{i}_{i + 1}", f"n{i}", f"n{i + 1}")
    return g


def star_graph(n_leaves: int, *, seed: int = 0) -> TopologyGraph:
    """One hub plus ``n_leaves`` leaf nodes, each connected by one edge.

    Every path between two leaves goes through the hub, so every
    fleet request claims the hub. Use this to isolate hub-contention
    behavior of the coordination layer.
    """
    if n_leaves < 2:
        raise ValueError(f"star_graph requires n_leaves >= 2, got {n_leaves}")
    _ = seed
    g = TopologyGraph()
    g.add_node(TopologyNode(id="hub", label="Hub", type="hub"))
    for i in range(n_leaves):
        leaf = f"leaf{i}"
        g.add_node(TopologyNode(id=leaf, label=f"Leaf {i}", type="room"))
        _add_corridor_edge(g, f"e_hub_{leaf}", "hub", leaf)
    return g


def doorway_graph(
    *,
    n_rooms: int = 4,
    seed: int = 0,
) -> TopologyGraph:
    """Two clusters of rooms joined by a single doorway edge.

    Layout::

        room_a0 - room_a1 - ... - room_a{n-1} - door - room_b0 - ... - room_b{n-1}

    The doorway edge id is ``doorway`` and its type is ``door``. Every
    cross-cluster route must traverse it, so coordination behavior on a
    classic single-bottleneck scenario is exposed cleanly.
    """
    if n_rooms < 1:
        raise ValueError(f"doorway_graph requires n_rooms >= 1, got {n_rooms}")
    _ = seed
    g = TopologyGraph()
    # Side A
    for i in range(n_rooms):
        g.add_node(TopologyNode(id=f"room_a{i}", label=f"Room A{i}", type="room"))
    for i in range(n_rooms - 1):
        _add_corridor_edge(g, f"e_a{i}_{i + 1}", f"room_a{i}", f"room_a{i + 1}")
    g.add_node(TopologyNode(id="door_a", label="Door Side A", type="door"))
    g.add_node(TopologyNode(id="door_b", label="Door Side B", type="door"))
    _add_corridor_edge(g, f"e_a{n_rooms - 1}_door", f"room_a{n_rooms - 1}", "door_a")
    # The narrow doorway: typed "door" so semantic strategies can react.
    g.add_edge(
        TopologyEdge(
            id="doorway",
            source="door_a",
            target="door_b",
            type="door",
            cost=1.0,
            bidirectional=True,
        )
    )
    # Side B
    for i in range(n_rooms):
        g.add_node(TopologyNode(id=f"room_b{i}", label=f"Room B{i}", type="room"))
    _add_corridor_edge(g, "e_door_b0", "door_b", "room_b0")
    for i in range(n_rooms - 1):
        _add_corridor_edge(g, f"e_b{i}_{i + 1}", f"room_b{i}", f"room_b{i + 1}")
    return g


def multi_floor_office(
    *,
    n_floors: int = 2,
    rooms_per_floor: int = 3,
    seed: int = 0,
) -> TopologyGraph:
    """Multi-floor chain on each floor + elevator/stairs between floors.

    Each floor is a chain of ``rooms_per_floor`` nodes whose
    ``properties.floor`` is set to the floor index (1-based). Between
    consecutive floors two edges exist: an ``elevator`` edge with
    moderate cost and a ``stairs`` edge with higher cost — matches the
    ``prefer_elevator`` / ``floor_change_penalty`` cost-function
    semantics so eval results expose how those costs interact with
    reservations.
    """
    if n_floors < 1:
        raise ValueError(f"multi_floor_office requires n_floors >= 1, got {n_floors}")
    if rooms_per_floor < 1:
        raise ValueError(
            f"multi_floor_office requires rooms_per_floor >= 1, got {rooms_per_floor}"
        )
    _ = seed
    g = TopologyGraph()
    for f in range(1, n_floors + 1):
        for r in range(rooms_per_floor):
            g.add_node(
                TopologyNode(
                    id=f"f{f}_r{r}",
                    label=f"Floor {f} Room {r}",
                    type="room",
                    properties={"floor": f},
                )
            )
        for r in range(rooms_per_floor - 1):
            _add_corridor_edge(
                g,
                f"f{f}_e{r}_{r + 1}",
                f"f{f}_r{r}",
                f"f{f}_r{r + 1}",
            )
    # Floor transitions: between f and f+1, link the first room of each.
    for f in range(1, n_floors):
        elev_top = f"f{f}_r0"
        elev_bot = f"f{f + 1}_r0"
        g.add_edge(
            TopologyEdge(
                id=f"elevator_{f}_{f + 1}",
                source=elev_top,
                target=elev_bot,
                type="elevator",
                cost=2.0,
                bidirectional=True,
            )
        )
        g.add_edge(
            TopologyEdge(
                id=f"stairs_{f}_{f + 1}",
                source=elev_top,
                target=elev_bot,
                type="stairs",
                cost=5.0,
                bidirectional=True,
            )
        )
    return g


@dataclass(frozen=True)
class _PriorityProfile:
    """Internal: name -> tuple of priority weights used for sampling."""

    name: str
    choices: tuple[int, ...]


_PRIORITY_PROFILES = {
    "uniform": _PriorityProfile("uniform", (0, 0, 0, 0)),
    "mixed": _PriorityProfile("mixed", (0, 0, 1, 5)),
    "high": _PriorityProfile("high", (1, 2, 3, 5)),
}


def generate_fleet_requests(
    graph: TopologyGraph,
    n_agents: int,
    *,
    seed: int = 0,
    deadline_tightness: float = 0.0,
    priority_distribution: str = "uniform",
    hold_start: time = time(10, 0),
    hold_end: time = time(11, 0),
) -> list[FleetRequest]:
    """Draw ``n_agents`` random ``start → goal`` pairs from ``graph``.

    Parameters
    ----------
    deadline_tightness:
        ``0.0`` means no deadlines are set. ``1.0`` means every
        request gets a deadline equal to ``hold_end``. Values in
        between probabilistically attach a deadline (interpolated
        between ``hold_start`` and ``hold_end``) to each request.
    priority_distribution:
        One of ``"uniform"`` (all priority 0), ``"mixed"`` (most 0,
        some elevated), or ``"high"`` (all elevated). Used to drive
        the ``priority`` / ``joint`` strategies into different
        regimes during sweeps.
    hold_start, hold_end:
        Carried through only as bounds for sampled deadlines; they
        are *not* attached to the FleetRequest itself (the scheduler
        receives hold_start / hold_end through the runner).
    """
    if n_agents < 1:
        return []
    rng = random.Random(seed)
    profile = _PRIORITY_PROFILES.get(priority_distribution)
    if profile is None:
        raise ValueError(
            f"unknown priority_distribution {priority_distribution!r}; "
            f"choose from {list(_PRIORITY_PROFILES)}"
        )
    node_ids = list(graph._nodes.keys())  # noqa: SLF001 - generator-local access
    if len(node_ids) < 2:
        raise ValueError("graph needs at least 2 nodes to draw start/goal pairs")
    out: list[FleetRequest] = []
    start_minute = hold_start.hour * 60 + hold_start.minute
    end_minute = hold_end.hour * 60 + hold_end.minute
    window = max(end_minute - start_minute, 1)
    for i in range(n_agents):
        start = rng.choice(node_ids)
        goal = rng.choice([n for n in node_ids if n != start])
        priority = rng.choice(profile.choices)
        deadline: time | None = None
        if deadline_tightness > 0.0 and rng.random() < deadline_tightness:
            # Tighter tightness -> earlier deadline.
            offset = int(window * (1.0 - deadline_tightness * rng.random()))
            dl_minute = start_minute + max(1, offset)
            dl_minute = min(dl_minute, end_minute)
            deadline = time(dl_minute // 60, dl_minute % 60)
        out.append(
            FleetRequest(
                agent_id=f"a{i}",
                start=start,
                goal=goal,
                priority=priority,
                deadline=deadline,
            )
        )
    return out


def generate_static_reservations(
    graph: TopologyGraph,
    density: float,
    *,
    seed: int = 0,
    hold_start: time = time(10, 0),
    hold_end: time = time(11, 0),
    blocker_agent_id: str = "blocker",
) -> list[ClaimRequest]:
    """Build a list of pre-existing holds covering ``density`` of nodes.

    Returns :class:`ClaimRequest` entries; the caller decides whether
    to apply them to a real scheduler or to a clone. Picks node ids
    in deterministic shuffled order so the same ``seed`` gives the
    same blocker set.
    """
    if density <= 0.0:
        return []
    rng = random.Random(seed)
    node_ids = list(graph._nodes.keys())  # noqa: SLF001
    rng.shuffle(node_ids)
    k = max(1, int(len(node_ids) * min(density, 1.0)))
    return [
        ClaimRequest(
            agent_id=blocker_agent_id,
            resource_id=nid,
            start=hold_start,
            end=hold_end,
        )
        for nid in node_ids[:k]
    ]


def apply_reservations(
    scheduler: SharedScheduler,
    reservations: list[ClaimRequest],
) -> None:
    """Apply pre-built ``ClaimRequest`` entries to a scheduler.

    Helper kept here so the runner doesn't import scheduler internals
    just to set up its initial state.
    """
    for req in reservations:
        scheduler.claim(req)
