"""Visit-history memory layer for the semantic topology graph.

Stores per-node visit counts and timestamps in ``node.properties`` so they
serialize cleanly via the YAML/JSON loader. The cost factories in
:mod:`semantic_toponav.memory.costs` consume that history at plan time to
bias the planner toward (or away from) familiar nodes.
"""

from semantic_toponav.memory.costs import (
    avoid_recently_visited,
    prefer_familiar,
    prefer_unvisited,
)
from semantic_toponav.memory.visit import (
    DEFAULT_LAST_VISITED_KEY,
    DEFAULT_VISIT_COUNT_KEY,
    clear_history,
    last_visited,
    record_path,
    record_visit,
    time_since_visit,
    visit_count,
)

__all__ = [
    "DEFAULT_LAST_VISITED_KEY",
    "DEFAULT_VISIT_COUNT_KEY",
    "avoid_recently_visited",
    "clear_history",
    "last_visited",
    "prefer_familiar",
    "prefer_unvisited",
    "record_path",
    "record_visit",
    "time_since_visit",
    "visit_count",
]
