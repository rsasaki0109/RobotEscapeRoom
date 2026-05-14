"""Multi-agent shared-resource reservations.

Where :func:`semantic_toponav.planner.time_aware` reads recurring closure
windows that live *on the graph* (a corridor that's swept at 06:00, an
office that's locked overnight), this module handles closures that live
*outside the graph*: another agent has claimed a corridor / elevator /
room for a specific interval, and the current planner needs to route
around that claim.

The :class:`ReservationTable` is a flat list of
``(resource_id, [start, end])`` entries. A ``resource_id`` may name a
node OR an edge — when the cost function is queried, the active set at
``at_time`` is computed once, and any edge whose own id (or whose source
/ target node id) is in that set is blocked.

Reservations share ``time_aware`` 's clock semantics:

- Intervals are time-of-day, ``HH:MM`` (or ``HH:MM:SS``) strings, lists,
  or :class:`datetime.time` / :class:`datetime.datetime` values.
- An interval whose ``end`` is ``<=`` ``start`` wraps midnight, so
  ``["22:00", "06:00"]`` is active from 22:00 through 05:59:59.
- ``end`` is exclusive; ``start`` is inclusive.

The cost function returned by :func:`reservation_aware` composes
cleanly with :func:`compose_costs`, so callers can stack
``avoid_restricted``, ``time_aware``, and ``reservation_aware`` in a
single plan.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Any

import yaml

from semantic_toponav.graph.types import TopologyEdge
from semantic_toponav.planner.semantic_costs import (
    BLOCKED,
    CostFn,
    _as_time,
    _in_interval,
    _parse_hhmm,
)

SCHEMA_VERSION = 1


class ReservationLoadError(Exception):
    """Raised when a reservation file cannot be parsed."""


@dataclass(frozen=True)
class Reservation:
    """A single claim that another agent (or process) holds on a resource.

    Attributes
    ----------
    resource_id:
        The node id or edge id being reserved. The cost function does
        not require the resource to exist in the graph — unknown ids are
        silently ignored, which matches how ``time_aware`` treats a
        ``closed_during`` property on an absent endpoint.
    start, end:
        Time-of-day interval the reservation covers. ``end <= start``
        wraps midnight.
    agent_id:
        Free-form owner string. Carried through to ``to_dict`` so an
        external scheduler can keep its bookkeeping next to the
        intervals, but the cost function itself ignores it.
    """

    resource_id: str
    start: time
    end: time
    agent_id: str | None = None


@dataclass
class ReservationTable:
    """A flat, replayable list of :class:`Reservation` entries.

    Mutable for incremental construction. The query path
    (:meth:`closed_at`) is read-only and allocates a fresh ``set`` per
    call so callers can hold onto it without worrying about table
    mutation.
    """

    entries: list[Reservation] = field(default_factory=list)

    # ----- construction -------------------------------------------------

    def add(
        self,
        resource_id: str,
        start: time | datetime | str,
        end: time | datetime | str,
        *,
        agent_id: str | None = None,
    ) -> Reservation:
        """Append a reservation and return the stored instance."""
        reservation = Reservation(
            resource_id=resource_id,
            start=_as_time(start),
            end=_as_time(end),
            agent_id=agent_id,
        )
        self.entries.append(reservation)
        return reservation

    def extend(self, reservations: Iterable[Reservation]) -> None:
        self.entries.extend(reservations)

    # ----- queries ------------------------------------------------------

    def __iter__(self) -> Iterator[Reservation]:
        return iter(self.entries)

    def __len__(self) -> int:
        return len(self.entries)

    def closed_at(self, at_time: time | datetime | str) -> set[str]:
        """Return the set of ``resource_id`` values active at ``at_time``."""
        at = _as_time(at_time)
        active: set[str] = set()
        for reservation in self.entries:
            if _in_interval(at, reservation.start, reservation.end):
                active.add(reservation.resource_id)
        return active

    # ----- serialization ------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": SCHEMA_VERSION,
            "reservations": [
                {
                    "resource_id": r.resource_id,
                    "start": r.start.strftime("%H:%M:%S"),
                    "end": r.end.strftime("%H:%M:%S"),
                    **({"agent_id": r.agent_id} if r.agent_id is not None else {}),
                }
                for r in self.entries
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReservationTable:
        if not isinstance(data, dict):
            raise ReservationLoadError("reservation document must be a mapping")
        version = data.get("version", 1)
        if version != SCHEMA_VERSION:
            raise ReservationLoadError(
                f"unsupported reservation schema version: {version} "
                f"(expected {SCHEMA_VERSION})"
            )
        raw = data.get("reservations", [])
        if not isinstance(raw, list):
            raise ReservationLoadError("'reservations' must be a list")

        table = cls()
        for i, entry in enumerate(raw):
            if not isinstance(entry, dict):
                raise ReservationLoadError(
                    f"reservation #{i} is not a mapping"
                )
            try:
                resource_id = entry["resource_id"]
                start_raw = entry["start"]
                end_raw = entry["end"]
            except KeyError as exc:
                raise ReservationLoadError(
                    f"reservation #{i} is missing required key {exc.args[0]!r}"
                ) from exc
            if not isinstance(resource_id, str) or not resource_id:
                raise ReservationLoadError(
                    f"reservation #{i}: 'resource_id' must be a non-empty string"
                )
            try:
                start = _coerce_time(start_raw)
                end = _coerce_time(end_raw)
            except (TypeError, ValueError) as exc:
                raise ReservationLoadError(
                    f"reservation #{i}: invalid time value ({exc})"
                ) from exc
            agent_id = entry.get("agent_id")
            if agent_id is not None and not isinstance(agent_id, str):
                raise ReservationLoadError(
                    f"reservation #{i}: 'agent_id' must be a string or omitted"
                )
            table.entries.append(
                Reservation(
                    resource_id=resource_id,
                    start=start,
                    end=end,
                    agent_id=agent_id,
                )
            )
        return table


def _coerce_time(value: object) -> time:
    if isinstance(value, time):
        return value
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, str):
        return _parse_hhmm(value)
    raise TypeError(
        f"time value must be str, time, or datetime; got {type(value).__name__}"
    )


def load_reservations(path: str | Path) -> ReservationTable:
    """Load a :class:`ReservationTable` from a YAML or JSON file."""
    p = Path(path)
    if not p.exists():
        raise ReservationLoadError(f"reservation file not found: {p}")

    suffix = p.suffix.lower()
    text = p.read_text(encoding="utf-8")
    try:
        if suffix in {".yaml", ".yml"}:
            data = yaml.safe_load(text)
        elif suffix == ".json":
            data = json.loads(text)
        else:
            raise ReservationLoadError(
                f"unsupported file extension {suffix!r}; "
                "expected .yaml, .yml, or .json"
            )
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        raise ReservationLoadError(f"failed to parse {p}: {exc}") from exc

    if data is None:
        raise ReservationLoadError(f"reservation file is empty: {p}")
    try:
        return ReservationTable.from_dict(data)
    except ReservationLoadError as exc:
        raise ReservationLoadError(f"{p}: {exc}") from exc


def reservation_aware(
    table: ReservationTable,
    *,
    at_time: time | datetime | str,
) -> CostFn:
    """Block edges whose id or endpoint is reserved at ``at_time``.

    The active set is computed once when this function is called, so
    repeatedly invoking the returned cost function over a planner run is
    cheap. To replan against a different clock value, call
    :func:`reservation_aware` again.

    Parameters
    ----------
    table:
        Source of truth for which resources are claimed.
    at_time:
        Time-of-day to evaluate. ``HH:MM`` / ``HH:MM:SS`` strings,
        :class:`datetime.time`, and :class:`datetime.datetime` are
        accepted.

    Returns
    -------
    CostFn
        Edge → cost. Returns ``math.inf`` for any edge whose own id, or
        whose source / target node id, appears in the active set.
    """
    closed = table.closed_at(at_time)
    # Fast no-op path keeps the planner branchless when nothing is held.
    if not closed:
        def cost_fn(edge: TopologyEdge) -> float:
            return edge.cost
        return cost_fn

    def cost_fn(edge: TopologyEdge) -> float:
        if edge.id in closed:
            return BLOCKED
        if edge.source in closed or edge.target in closed:
            return BLOCKED
        return edge.cost

    return cost_fn
