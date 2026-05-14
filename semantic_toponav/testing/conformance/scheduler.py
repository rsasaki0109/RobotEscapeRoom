"""Conformance suite for :class:`semantic_toponav.coordination.SchedulerProtocol`.

Both :class:`~semantic_toponav.coordination.SharedScheduler` (the
in-process reference) and :class:`~semantic_toponav.coordination.SchedulerClient`
(an RPC proxy that talks over a :class:`Transport`) must satisfy this
contract. Future schedulers — a leader-elected coordinator, a
serverless coordination service, an external solver — should pass
this suite too.

Many checks require a *fresh* scheduler (the surface is intentionally
stateful: claims accumulate), so the suite takes a zero-arg factory
rather than a single instance. Each subtest calls the factory to get
a clean scheduler.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import time

from semantic_toponav.coordination.rpc import SchedulerProtocol
from semantic_toponav.coordination.scheduler import ClaimRequest
from semantic_toponav.planner.reservations import (
    Reservation,
    ReservationTable,
)


def _req(
    agent_id: str,
    resource_id: str,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    priority: int = 0,
) -> ClaimRequest:
    return ClaimRequest(
        agent_id=agent_id,
        resource_id=resource_id,
        start=time(*start),
        end=time(*end),
        priority=priority,
    )


def run_scheduler_conformance(
    factory: Callable[[], SchedulerProtocol],
) -> None:
    """Run the :class:`SchedulerProtocol` conformance checks.

    Parameters
    ----------
    factory:
        Zero-arg callable returning a fresh :class:`SchedulerProtocol`
        instance. Called once per subtest. For
        :class:`SharedScheduler` this is simply ``SharedScheduler``;
        for an RPC client wrap construction so a fresh server-side
        scheduler is spun up each call.
    """

    # ---- structural --------------------------------------------------------
    sched = factory()
    assert isinstance(sched, SchedulerProtocol), (
        f"{type(sched).__name__} does not satisfy SchedulerProtocol "
        "(check claim / claim_many / release / release_all / reservations "
        "/ claims_for / conflicts / table / __len__)"
    )

    # ---- empty initial state ----------------------------------------------
    sched = factory()
    assert len(sched) == 0, f"fresh scheduler has size {len(sched)}, expected 0"
    assert sched.reservations() == [], (
        f"fresh scheduler reservations() is {sched.reservations()!r}, "
        "expected []"
    )
    assert sched.claims_for("robotA") == [], (
        "fresh scheduler claims_for(unknown agent) must be []"
    )

    # ---- basic claim / release cycle --------------------------------------
    sched = factory()
    res = sched.claim(_req("robotA", "elev_1", (9, 0), (9, 30)))
    assert res.granted is True, (
        f"first claim on empty scheduler was denied: {res!r}"
    )
    assert res.reservation is not None, (
        "granted claim must include the inserted Reservation"
    )
    assert isinstance(res.reservation, Reservation), (
        f"reservation field must be Reservation, got "
        f"{type(res.reservation).__name__}"
    )
    assert len(sched) == 1, f"scheduler size after one claim is {len(sched)}"

    # FCFS-style block: a second claim overlapping the first is denied.
    conflict_res = sched.claim(_req("robotB", "elev_1", (9, 15), (9, 45)))
    assert conflict_res.granted is False, (
        "overlapping claim from a different agent was granted under the "
        "default policy — schedulers must default to FCFS"
    )
    assert len(conflict_res.conflicts) >= 1, (
        f"denied claim should list at least one conflicting reservation, "
        f"got {conflict_res.conflicts!r}"
    )

    # release returns the count of removed entries
    removed = sched.release("robotA", "elev_1")
    assert removed == 1, f"release removed {removed} entries, expected 1"
    assert len(sched) == 0, (
        f"scheduler size after release is {len(sched)}, expected 0"
    )

    # ---- release_all -------------------------------------------------------
    sched = factory()
    sched.claim(_req("robotA", "elev_1", (9, 0), (9, 30)))
    sched.claim(_req("robotA", "door_2", (10, 0), (10, 5)))
    assert sched.release_all("robotA") == 2, (
        "release_all must remove every entry owned by the agent"
    )
    assert sched.release_all("ghost") == 0, (
        "release_all on an unknown agent must return 0, not raise"
    )

    # ---- claim_many --------------------------------------------------------
    sched = factory()
    results = list(sched.claim_many([
        _req("robotA", "elev_1", (9, 0), (9, 30)),
        _req("robotA", "door_2", (10, 0), (10, 5)),
    ]))
    assert len(results) == 2, (
        f"claim_many returned {len(results)} results for 2 requests"
    )
    assert all(r.granted for r in results), (
        f"both non-overlapping claims should be granted: {results!r}"
    )
    assert len(sched) == 2, f"scheduler size after claim_many is {len(sched)}"

    # ---- conflicts / claims_for / table -----------------------------------
    sched = factory()
    sched.claim(_req("robotA", "elev_1", (9, 0), (9, 30)))
    overlapping = sched.conflicts("elev_1", time(9, 15), time(9, 45))
    assert len(overlapping) == 1, (
        f"conflicts() found {len(overlapping)} entries for an overlapping "
        "window, expected 1"
    )

    excluded = sched.conflicts(
        "elev_1", time(9, 15), time(9, 45), exclude_agent="robotA"
    )
    assert excluded == [], (
        "conflicts(exclude_agent=owner) must skip the owner's own claims"
    )

    own = sched.claims_for("robotA")
    assert len(own) == 1, f"claims_for(robotA) found {len(own)}, expected 1"
    assert own[0].resource_id == "elev_1", (
        f"claims_for returned an unexpected reservation: {own[0]!r}"
    )

    snapshot = sched.table()
    assert isinstance(snapshot, ReservationTable), (
        f"table() must return a ReservationTable, got {type(snapshot).__name__}"
    )
    assert len(snapshot.entries) == len(sched), (
        f"table snapshot has {len(snapshot.entries)} entries; scheduler "
        f"len is {len(sched)}"
    )

    # ---- reservations() returns a snapshot --------------------------------
    snap1 = sched.reservations()
    sched.claim(_req("robotB", "door_2", (11, 0), (11, 5)))
    assert len(snap1) == 1, (
        "reservations() must return a snapshot list, not a live view — "
        "mutating the scheduler should not change a previously returned "
        f"list (snap1 grew to {len(snap1)})"
    )
