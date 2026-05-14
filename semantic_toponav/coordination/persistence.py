"""Persist and restore :class:`SharedScheduler` state.

The reservation YAML/JSON format defined in
:mod:`semantic_toponav.planner.reservations` already round-trips
:class:`~semantic_toponav.planner.reservations.Reservation` lists.
This module is the thin glue that turns a *live* scheduler's
current claims into that file (and back) so callers can:

* checkpoint the scheduler before a restart and resume without
  losing in-flight holds,
* hand the file off to debugging tools that already speak the
  static reservation format,
* prime a fresh scheduler at startup with a known operational
  baseline ("the maintenance window holds we always honour").

The conflict policy is operational state, not data, so it does
*not* round-trip — callers pass ``policy=...`` to :func:`load_scheduler`
to override the default FCFS at restore time.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from semantic_toponav.coordination.scheduler import SharedScheduler
from semantic_toponav.planner.reservations import load_reservations

if TYPE_CHECKING:
    from semantic_toponav.coordination.policies import ConflictPolicy


def save_scheduler(scheduler: SharedScheduler, path: str | Path) -> int:
    """Persist ``scheduler``'s current reservations to ``path``.

    The wire format is identical to the one consumed by
    :func:`semantic_toponav.planner.load_reservations`, so the same
    file can be fed back into :func:`load_scheduler` *or* loaded as
    a static :class:`ReservationTable` by the offline planner.

    Parameters
    ----------
    scheduler:
        The live :class:`SharedScheduler` whose claims should be
        written.
    path:
        Output file path. Extension ``.yaml`` / ``.yml`` writes YAML;
        ``.json`` writes JSON. Any other extension raises ``ValueError``.

    Returns
    -------
    int
        Number of reservations written. Useful for ``assert
        save_scheduler(...) == len(scheduler)`` sanity checks.

    Raises
    ------
    ValueError
        If the path extension is not one of ``.yaml`` / ``.yml`` /
        ``.json``.
    """
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix not in {".yaml", ".yml", ".json"}:
        raise ValueError(
            f"unsupported scheduler save extension {suffix!r}; "
            "expected .yaml, .yml, or .json"
        )
    table = scheduler.table()
    data = table.to_dict()
    p.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".json":
        import json

        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    else:
        import yaml

        # Stable output: sort_keys=False keeps the reservations in
        # the order the scheduler holds them; default_flow_style=False
        # keeps the file human-readable.
        p.write_text(
            yaml.safe_dump(data, sort_keys=False, default_flow_style=False),
            encoding="utf-8",
        )
    return len(table)


def load_scheduler(
    path: str | Path,
    *,
    policy: ConflictPolicy | None = None,
) -> SharedScheduler:
    """Construct a fresh scheduler primed with the reservations at ``path``.

    The file format is the one written by :func:`save_scheduler`
    *or* by any static reservation file the offline planner already
    accepts — the two formats are intentionally identical.

    Parameters
    ----------
    path:
        Path to a YAML or JSON reservation file.
    policy:
        Conflict policy to install on the new scheduler. ``None``
        keeps the scheduler default (FCFS). The persisted file does
        *not* carry policy information — policy is operational state,
        not data — so this is the only way to restore a non-default
        policy.

    Returns
    -------
    SharedScheduler
        A brand-new scheduler with every reservation from the file
        appended in insertion order. The file's contents are *not*
        re-validated against the conflict policy — the assumption is
        that whatever wrote the file already satisfied its own
        invariants. Use :meth:`SharedScheduler.clear` followed by
        repeated :meth:`SharedScheduler.claim` calls if you need the
        policy to re-vet every entry on load.
    """
    table = load_reservations(path)
    s = SharedScheduler(policy=policy) if policy is not None else SharedScheduler()
    # SharedScheduler keeps its own list of entries; we append directly
    # rather than calling .claim() because the file is presumed already
    # consistent and we want a fast bulk load that preserves order.
    s._entries.extend(table.entries)  # noqa: SLF001 — private OK within package
    return s
