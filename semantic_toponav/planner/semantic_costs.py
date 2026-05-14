"""Semantic-aware cost functions for topology-graph planning.

These are deliberately simple — they multiply or add a penalty based on
edge ``type``/``properties``. ``compose_costs`` combines them by applying
each function as a multiplier on the base cost.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime, time

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import TopologyEdge

CostFn = Callable[[TopologyEdge], float]

BLOCKED = math.inf

DEFAULT_FLOOR_PROPERTY = "floor"
DEFAULT_CLOSED_DURING_PROPERTY = "closed_during"
DEFAULT_CLOSED_ON_DATES_PROPERTY = "closed_on_dates"

_WEEKDAY_NAMES: dict[str, int] = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}


def default_edge_cost(edge: TopologyEdge) -> float:
    """Return the edge's declared cost."""
    return edge.cost


def avoid_restricted(edge: TopologyEdge) -> float:
    """Block restricted edges entirely.

    An edge is considered restricted if its ``type`` is ``"restricted"`` or
    if ``properties.restricted`` is truthy.
    """
    if edge.type == "restricted" or edge.properties.get("restricted"):
        return BLOCKED
    return edge.cost


def avoid_stairs(edge: TopologyEdge) -> float:
    """Heavily penalize stairs edges (accessibility mode)."""
    if edge.type in {"stairs_up", "stairs_down"}:
        return edge.cost + 50.0
    return edge.cost


def prefer_elevator(edge: TopologyEdge) -> float:
    """Make elevator connections cheaper than the default."""
    if edge.type == "elevator_connection":
        return max(0.0, edge.cost * 0.5)
    return edge.cost


def _endpoint_floors(
    graph: TopologyGraph, edge: TopologyEdge, floor_property: str
) -> tuple[object, object]:
    src = graph.get_node(edge.source).properties.get(floor_property)
    tgt = graph.get_node(edge.target).properties.get(floor_property)
    return src, tgt


def floor_change_penalty(
    graph: TopologyGraph,
    *,
    penalty: float = 10.0,
    floor_property: str = DEFAULT_FLOOR_PROPERTY,
) -> CostFn:
    """Add a per-floor penalty to edges that change floor.

    Returns a cost function suitable for ``plan_*`` and ``compose_costs``.
    Edges where either endpoint lacks the ``floor`` property are charged
    normally.
    """

    def cost_fn(edge: TopologyEdge) -> float:
        src_floor, tgt_floor = _endpoint_floors(graph, edge, floor_property)
        if src_floor is None or tgt_floor is None or src_floor == tgt_floor:
            return edge.cost
        return edge.cost + penalty * abs(int(src_floor) - int(tgt_floor))

    return cost_fn


def prefer_floor(
    graph: TopologyGraph,
    floor: int,
    *,
    off_floor_multiplier: float = 2.0,
    floor_property: str = DEFAULT_FLOOR_PROPERTY,
) -> CostFn:
    """Multiply edge cost when either endpoint is not on the preferred floor.

    Edges fully on ``floor`` are charged normally; edges that leave or
    enter another floor are scaled by ``off_floor_multiplier``.
    """

    def cost_fn(edge: TopologyEdge) -> float:
        src_floor, tgt_floor = _endpoint_floors(graph, edge, floor_property)
        if src_floor == floor and tgt_floor == floor:
            return edge.cost
        return edge.cost * off_floor_multiplier

    return cost_fn


def same_floor_only(
    graph: TopologyGraph,
    *,
    floor_property: str = DEFAULT_FLOOR_PROPERTY,
) -> CostFn:
    """Block every edge whose endpoints are on different floors."""

    def cost_fn(edge: TopologyEdge) -> float:
        src_floor, tgt_floor = _endpoint_floors(graph, edge, floor_property)
        if src_floor is None or tgt_floor is None:
            return edge.cost
        if src_floor != tgt_floor:
            return BLOCKED
        return edge.cost

    return cost_fn


def block_edges(edge_ids: Iterable[str]) -> CostFn:
    """Block a fixed set of edges by id.

    Useful for runtime state like "this corridor is closed for cleaning" or
    "the freight elevator is out of service" — the underlying graph stays
    intact and a different :func:`block_edges` call can be used on the next
    plan.

    Returns a cost function that yields ``math.inf`` for the listed edges
    and ``edge.cost`` otherwise.
    """
    blocked = set(edge_ids)

    def cost_fn(edge: TopologyEdge) -> float:
        if edge.id in blocked:
            return BLOCKED
        return edge.cost

    return cost_fn


def block_edge_types(edge_types: Iterable[str]) -> CostFn:
    """Block all edges whose ``type`` is in ``edge_types``.

    Example: ``block_edge_types({"elevator_connection"})`` to plan around an
    elevator outage without touching the graph.
    """
    blocked = set(edge_types)

    def cost_fn(edge: TopologyEdge) -> float:
        if edge.type in blocked:
            return BLOCKED
        return edge.cost

    return cost_fn


def _parse_hhmm(value: str) -> time:
    parts = value.split(":")
    if len(parts) == 2:
        h, m = parts
        return time(int(h), int(m))
    if len(parts) == 3:
        h, m, s = parts
        return time(int(h), int(m), int(s))
    raise ValueError(f"invalid time {value!r} (expected HH:MM or HH:MM:SS)")


def _as_time(value: time | datetime | str) -> time:
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        return _parse_hhmm(value)
    raise TypeError(
        f"at_time must be datetime, time, or 'HH:MM' string; got {type(value).__name__}"
    )


def _as_date(value: date | datetime | str | None) -> date | None:
    """Coerce ``at_date`` arguments to :class:`date` (or ``None``)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                f"at_date must be ISO 'YYYY-MM-DD'; got {value!r}"
            ) from exc
    raise TypeError(
        f"at_date must be date, datetime, or 'YYYY-MM-DD' string; "
        f"got {type(value).__name__}"
    )


def _parse_weekdays(raw: object) -> frozenset[int]:
    """Parse a weekday filter list into a frozenset of ints (Mon=0..Sun=6).

    Accepts ints in 0..6 or three-letter names (``"mon"``..``"sun"``,
    case-insensitive). Booleans are rejected even though they are ``int``
    subclasses, because ``True``/``False`` as a weekday is always a typo.
    """
    if not isinstance(raw, (list, tuple)) or not raw:
        raise ValueError(
            f"weekday filter must be a non-empty list of int 0..6 or "
            f"three-letter names; got {raw!r}"
        )
    out: set[int] = set()
    for entry in raw:
        if isinstance(entry, bool):
            raise ValueError(
                f"weekday entry must be int 0..6 or name, not bool ({entry!r})"
            )
        if isinstance(entry, int):
            if not 0 <= entry <= 6:
                raise ValueError(
                    f"weekday int must be in 0..6 (Mon=0..Sun=6), got {entry}"
                )
            out.add(entry)
        elif isinstance(entry, str):
            key = entry.strip().lower()[:3]
            if key not in _WEEKDAY_NAMES:
                raise ValueError(
                    f"unknown weekday {entry!r}; expected one of "
                    f"{sorted(_WEEKDAY_NAMES)} or int 0..6"
                )
            out.add(_WEEKDAY_NAMES[key])
        else:
            raise ValueError(
                f"weekday entry must be int 0..6 or three-letter name; "
                f"got {entry!r}"
            )
    return frozenset(out)


def _intervals_from_property(
    raw: object,
) -> list[tuple[time, time, frozenset[int] | None]]:
    """Coerce ``closed_during`` into ``[(start, end, weekdays_or_None), ...]``.

    ``raw`` is the value stored under the property key. Accepts ``None``
    (empty list) and a list of entries that are either two-element
    ``[start, end]`` (daily-recurring, backward compatible) or three-element
    ``[start, end, weekdays]`` where ``weekdays`` is a list of ints (Mon=0)
    or three-letter names. Endpoints may be a ``time`` or an ``HH:MM`` /
    ``HH:MM:SS`` string. Raises :class:`ValueError` for malformed input so
    typos in the graph file surface early.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(
            f"closed_during must be a list of [start, end] or "
            f"[start, end, weekdays] entries, got {type(raw).__name__}"
        )
    out: list[tuple[time, time, frozenset[int] | None]] = []
    for entry in raw:
        if not isinstance(entry, (list, tuple)) or len(entry) not in (2, 3):
            raise ValueError(
                f"each closed_during entry must be [start, end] or "
                f"[start, end, weekdays]; got {entry!r}"
            )
        start = entry[0] if isinstance(entry[0], time) else _parse_hhmm(str(entry[0]))
        end = entry[1] if isinstance(entry[1], time) else _parse_hhmm(str(entry[1]))
        weekdays: frozenset[int] | None = None
        if len(entry) == 3:
            weekdays = _parse_weekdays(entry[2])
        out.append((start, end, weekdays))
    return out


def _closed_on_dates_from_property(raw: object) -> frozenset[date]:
    """Coerce ``closed_on_dates`` into a frozenset of :class:`date` values."""
    if raw is None:
        return frozenset()
    if not isinstance(raw, list):
        raise ValueError(
            f"closed_on_dates must be a list of 'YYYY-MM-DD' entries, "
            f"got {type(raw).__name__}"
        )
    out: set[date] = set()
    for entry in raw:
        if isinstance(entry, datetime):
            out.add(entry.date())
        elif isinstance(entry, date):
            out.add(entry)
        elif isinstance(entry, str):
            try:
                out.add(date.fromisoformat(entry))
            except ValueError as exc:
                raise ValueError(
                    f"closed_on_dates entry {entry!r} is not ISO 'YYYY-MM-DD'"
                ) from exc
        else:
            raise ValueError(
                f"closed_on_dates entry must be date or 'YYYY-MM-DD' string; "
                f"got {type(entry).__name__}"
            )
    return frozenset(out)


def _in_interval(at: time, start: time, end: time) -> bool:
    """Return True iff ``at`` falls in the [start, end) interval.

    When ``end <= start`` the interval is taken to wrap midnight, so for
    example ``["22:00", "06:00"]`` matches ``23:30`` and ``05:00`` but
    not ``07:00`` or ``20:00``.
    """
    if start <= end:
        return start <= at < end
    return at >= start or at < end


def _is_closed(
    properties: Mapping[str, object],
    at: time,
    on_date: date | None,
    weekday: int | None,
    *,
    closed_during_key: str,
    closed_on_dates_key: str,
) -> bool:
    """Return True iff ``properties`` says this entity is closed now.

    Combines time-of-day windows (``closed_during``) with the optional
    calendar layer (``closed_on_dates`` full-day overrides, weekday
    filters on ``closed_during`` entries). Weekday-filtered entries are
    a contract: if one is present but ``weekday`` is ``None`` (because
    the caller did not provide ``at_date``), this raises rather than
    silently letting the planner route through what may be a closed
    edge.
    """
    if on_date is not None:
        closed_dates = _closed_on_dates_from_property(
            properties.get(closed_on_dates_key)
        )
        if on_date in closed_dates:
            return True

    for start, end, weekdays in _intervals_from_property(
        properties.get(closed_during_key)
    ):
        if weekdays is not None:
            if weekday is None:
                raise ValueError(
                    "closed_during entry has a weekday filter but no "
                    "at_date was supplied to time_aware; pass at_date= "
                    "(or use a datetime as at_time) or drop the weekday "
                    "filter from the graph"
                )
            if weekday not in weekdays:
                continue
        if _in_interval(at, start, end):
            return True
    return False


def time_aware(
    graph: TopologyGraph,
    *,
    at_time: time | datetime | str,
    at_date: date | datetime | str | None = None,
    closed_during_key: str = DEFAULT_CLOSED_DURING_PROPERTY,
    closed_on_dates_key: str = DEFAULT_CLOSED_ON_DATES_PROPERTY,
) -> CostFn:
    """Block edges (and edges touching closed nodes) at a given time.

    Reads ``closed_during`` from each edge AND from both endpoint nodes.
    Each entry is either two-element ``[start, end]`` (recurring every
    day, backward compatible) or three-element ``[start, end, weekdays]``
    where ``weekdays`` is a list of ints (Mon=0..Sun=6) or three-letter
    names (``"mon"``..``"sun"``). Endpoints are ``HH:MM`` or ``HH:MM:SS``
    strings; an interval whose end ``<=`` start wraps midnight.

    The calendar layer is opt-in via ``at_date``:

    * Without ``at_date`` (and ``at_time`` not a ``datetime``), only daily
      ``[start, end]`` entries are evaluated. A weekday-filtered entry in
      the graph raises :class:`ValueError` so the mismatch surfaces early.
    * With ``at_date`` (or when ``at_time`` is a ``datetime``, from which
      the date is derived), weekday-filtered entries match only on the
      listed weekdays, and the ``closed_on_dates`` property — a list of
      ISO ``YYYY-MM-DD`` strings — fully closes the node/edge on those
      dates regardless of the time window.

    A node that is closed at ``at_time`` (and ``at_date`` if provided)
    makes every incident edge unusable. Use ``--at-time HH:MM`` and
    optionally ``--at-date YYYY-MM-DD`` on the CLI, or compose with
    other cost functions via :func:`compose_costs`.
    """
    at = _as_time(at_time)

    if at_date is None and isinstance(at_time, datetime):
        on_date: date | None = at_time.date()
    else:
        on_date = _as_date(at_date)
    weekday = on_date.weekday() if on_date is not None else None

    closed_nodes: set[str] = set()
    for node in graph.nodes():
        if _is_closed(
            node.properties,
            at,
            on_date,
            weekday,
            closed_during_key=closed_during_key,
            closed_on_dates_key=closed_on_dates_key,
        ):
            closed_nodes.add(node.id)

    def cost_fn(edge: TopologyEdge) -> float:
        if _is_closed(
            edge.properties,
            at,
            on_date,
            weekday,
            closed_during_key=closed_during_key,
            closed_on_dates_key=closed_on_dates_key,
        ):
            return BLOCKED
        if edge.source in closed_nodes or edge.target in closed_nodes:
            return BLOCKED
        return edge.cost

    return cost_fn


def compose_costs(*cost_functions: CostFn) -> CostFn:
    """Compose multiple cost functions.

    The base cost is ``default_edge_cost``. Each additional function is
    applied as a *ratio against the edge's own cost*: if function ``f``
    returns ``v`` for an edge whose own cost is ``c``, the multiplier is
    ``v / c`` (or 1.0 if ``c == 0``). Multipliers compound, and any
    function returning ``inf`` blocks the edge.

    This keeps individual cost functions independent and composable.
    """

    def composed(edge: TopologyEdge) -> float:
        base = edge.cost
        multiplier = 1.0
        for fn in cost_functions:
            v = fn(edge)
            if math.isinf(v):
                return math.inf
            if base == 0:
                # Allow additive adjustments via absolute value when base is 0.
                multiplier *= 1.0 + v
            else:
                multiplier *= v / base
        return base * multiplier

    return composed
