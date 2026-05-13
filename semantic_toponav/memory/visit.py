"""Record and query per-node visit history on a :class:`TopologyGraph`.

Visit data lives in ``node.properties`` so it round-trips through the
YAML/JSON serializer with no schema change:

- ``visit_count`` (int)         — total times this node has been visited
- ``last_visited`` (float)      — UNIX timestamp of the most recent visit

Both property keys are configurable for callers that already use a
different convention.
"""

from __future__ import annotations

import time
from collections.abc import Iterable

from semantic_toponav.graph.topology_graph import TopologyGraph

DEFAULT_VISIT_COUNT_KEY = "visit_count"
DEFAULT_LAST_VISITED_KEY = "last_visited"


def record_visit(
    graph: TopologyGraph,
    node_id: str,
    *,
    now: float | None = None,
    count_key: str = DEFAULT_VISIT_COUNT_KEY,
    timestamp_key: str = DEFAULT_LAST_VISITED_KEY,
) -> float:
    """Mark ``node_id`` as visited at time ``now``.

    Increments ``visit_count`` and overwrites ``last_visited``. Returns the
    timestamp that was stored (so the caller can use the same value to
    record neighboring events).

    ``now`` defaults to ``time.time()``. Passing a fixed value makes the
    function deterministic for tests and demos.
    """
    if now is None:
        now = time.time()
    node = graph.get_node(node_id)
    node.properties[count_key] = int(node.properties.get(count_key, 0)) + 1
    node.properties[timestamp_key] = float(now)
    return float(now)


def record_path(
    graph: TopologyGraph,
    path: Iterable[str],
    *,
    now: float | None = None,
    count_key: str = DEFAULT_VISIT_COUNT_KEY,
    timestamp_key: str = DEFAULT_LAST_VISITED_KEY,
) -> float:
    """Record a visit for every node in ``path`` with a single timestamp.

    Useful right after the robot finishes executing a plan — call once
    with the path that was actually traversed.
    """
    if now is None:
        now = time.time()
    for node_id in path:
        record_visit(
            graph,
            node_id,
            now=now,
            count_key=count_key,
            timestamp_key=timestamp_key,
        )
    return float(now)


def clear_history(
    graph: TopologyGraph,
    node_ids: Iterable[str] | None = None,
    *,
    count_key: str = DEFAULT_VISIT_COUNT_KEY,
    timestamp_key: str = DEFAULT_LAST_VISITED_KEY,
) -> None:
    """Drop visit history for the given nodes (default: every node)."""
    targets = list(node_ids) if node_ids is not None else graph.node_ids()
    for node_id in targets:
        props = graph.get_node(node_id).properties
        props.pop(count_key, None)
        props.pop(timestamp_key, None)


def visit_count(
    graph: TopologyGraph,
    node_id: str,
    *,
    count_key: str = DEFAULT_VISIT_COUNT_KEY,
) -> int:
    """Return the number of recorded visits for ``node_id`` (0 if none)."""
    return int(graph.get_node(node_id).properties.get(count_key, 0))


def last_visited(
    graph: TopologyGraph,
    node_id: str,
    *,
    timestamp_key: str = DEFAULT_LAST_VISITED_KEY,
) -> float | None:
    """Return the last-visited timestamp, or ``None`` if never visited."""
    value = graph.get_node(node_id).properties.get(timestamp_key)
    return None if value is None else float(value)


def time_since_visit(
    graph: TopologyGraph,
    node_id: str,
    *,
    now: float | None = None,
    timestamp_key: str = DEFAULT_LAST_VISITED_KEY,
) -> float | None:
    """Seconds since the last visit, or ``None`` if the node is unvisited."""
    ts = last_visited(graph, node_id, timestamp_key=timestamp_key)
    if ts is None:
        return None
    if now is None:
        now = time.time()
    return float(now) - ts
