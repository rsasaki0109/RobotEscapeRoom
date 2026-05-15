"""Shared in-memory reservation scheduler.

This is the runtime counterpart to
:class:`semantic_toponav.planner.reservations.ReservationTable`. The
table on disk is a static snapshot — useful as a configuration file,
but not as a live coordination point. :class:`SharedScheduler` keeps
the same data structure (a list of :class:`Reservation` entries) but
adds:

* ``claim`` — try to add a reservation atomically, returning a
  :class:`ClaimResult` that says whether the claim was granted and,
  if not, which existing reservations it conflicted with.
* ``release`` / ``release_all`` — drop a specific claim or every
  claim held by an agent (typical "I've finished my run, release my
  holds" call).
* ``table`` — produce a snapshot suitable for
  :func:`reservation_aware`, which is how the planner consumes
  scheduler state.

Interval overlap is computed minute-by-minute over the 24-hour clock,
which is simple to reason about and correct under the midnight-wrap
semantics shared with :func:`time_aware` (an interval whose ``end <=
start`` covers from ``start`` through ``23:59:59`` and then from
``00:00`` to ``end``). 1440 minutes per day keeps the cost trivially
small for any realistic claim count.

Each scheduler instance carries a :class:`ConflictPolicy` (defaults to
``first_come_first_served``). The policy decides whether a request
should be granted, denied, or — in the priority-based case —
granted *with preemption* of lower-priority claims that overlap. The
scheduler itself only enforces book-keeping; what counts as a
"conflict" is the policy's call.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import TYPE_CHECKING

from semantic_toponav.planner.reservations import (
    Reservation,
    ReservationTable,
)
from semantic_toponav.planner.semantic_costs import _as_time, _in_interval

if TYPE_CHECKING:
    from semantic_toponav.coordination.policies import ConflictPolicy


class SchedulerError(Exception):
    """Raised for invalid scheduler operations (e.g. empty agent id)."""


@dataclass(frozen=True)
class ClaimRequest:
    """A single attempt to reserve a resource.

    ``priority`` is consumed by :func:`priority_based`; the default
    policy ignores it. Higher numeric priority wins ties.
    """

    agent_id: str
    resource_id: str
    start: time
    end: time
    priority: int = 0


@dataclass
class ClaimResult:
    """Outcome of :meth:`SharedScheduler.claim`.

    Attributes
    ----------
    granted:
        ``True`` when the reservation was added (possibly after
        preempting lower-priority claims).
    reservation:
        The :class:`Reservation` entry that was inserted, present on
        ``granted=True``.
    conflicts:
        The existing reservations that overlapped the request.
        Present whether or not the claim was granted, so callers can
        log what stood in the way.
    preempted:
        Reservations that were *removed* because the policy chose to
        preempt them in favor of this request. Empty under FCFS;
        populated only when ``priority_based`` decides this request
        outranks the holders of the conflicting claims.
    """

    granted: bool = False
    reservation: Reservation | None = None
    conflicts: list[Reservation] = field(default_factory=list)
    preempted: list[Reservation] = field(default_factory=list)


def _intervals_overlap(
    a_start: time, a_end: time, b_start: time, b_end: time
) -> bool:
    """Return True iff the two time-of-day intervals overlap.

    Both intervals are half-open ``[start, end)`` and may wrap
    midnight (``end <= start``). The implementation walks each minute
    of the 24-hour clock and looks for one that lies inside both
    intervals; this is O(1440) per call but eliminates the corner
    cases that pairwise wrap-aware comparison would otherwise need to
    handle. The scheduler typically holds a handful of claims, so the
    fixed factor is negligible.
    """
    # Fast escape: zero-length interval overlaps nothing.
    if a_start == a_end or b_start == b_end:
        return False
    for minutes in range(0, 24 * 60):
        h, m = divmod(minutes, 60)
        t = time(h, m)
        if _in_interval(t, a_start, a_end) and _in_interval(t, b_start, b_end):
            return True
    return False


def _reservations_conflict(a: Reservation, b: Reservation) -> bool:
    if a.resource_id != b.resource_id:
        return False
    return _intervals_overlap(a.start, a.end, b.start, b.end)


class SharedScheduler:
    """Mutable, in-memory reservation scheduler.

    The scheduler is intentionally process-local. Wiring it into a
    real multi-process or multi-machine fleet is the caller's job
    (typical patterns: a service that serializes ``claim`` /
    ``release`` calls; a leader-elected coordinator). The contract
    here is the in-process surface that those patterns wrap.
    """

    def __init__(self, policy: ConflictPolicy | None = None) -> None:
        # Import locally to avoid a circular dependency between this
        # module and ``policies`` (which references ClaimRequest /
        # ClaimResult defined here).
        from semantic_toponav.coordination.policies import (
            first_come_first_served,
        )

        self._entries: list[Reservation] = []
        self._policy: ConflictPolicy = policy or first_come_first_served

    # ----- queries ------------------------------------------------------

    def __iter__(self):
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def reservations(self) -> list[Reservation]:
        """Return a shallow copy of all held reservations."""
        return list(self._entries)

    def claims_for(self, agent_id: str) -> list[Reservation]:
        """Reservations currently held by ``agent_id``."""
        return [r for r in self._entries if r.agent_id == agent_id]

    def conflicts(
        self,
        resource_id: str,
        start: time | datetime | str,
        end: time | datetime | str,
        *,
        exclude_agent: str | None = None,
    ) -> list[Reservation]:
        """Existing reservations that overlap ``[start, end)`` on ``resource_id``.

        Pass ``exclude_agent`` to skip claims an agent already holds —
        useful when a planner wants to "do I conflict with anyone
        *other than myself*".
        """
        s = _as_time(start)
        e = _as_time(end)
        out: list[Reservation] = []
        for r in self._entries:
            if r.resource_id != resource_id:
                continue
            if exclude_agent is not None and r.agent_id == exclude_agent:
                continue
            if _intervals_overlap(r.start, r.end, s, e):
                out.append(r)
        return out

    def table(self) -> ReservationTable:
        """Snapshot the current state as a :class:`ReservationTable`.

        Pass the result to
        :func:`semantic_toponav.planner.reservation_aware` to get a
        cost function for one specific ``at_time``. The snapshot is a
        fresh table; subsequent ``claim`` / ``release`` calls on the
        scheduler do not mutate it.
        """
        table = ReservationTable()
        table.extend(self._entries)
        return table

    # ----- mutations ----------------------------------------------------

    def claim(self, request: ClaimRequest) -> ClaimResult:
        """Try to add a claim. Returns a :class:`ClaimResult`.

        Whether the request succeeds — and whether existing claims
        get preempted — is delegated to the scheduler's configured
        :class:`ConflictPolicy`. The default FCFS policy denies any
        request that conflicts with an existing hold; the priority
        policy will preempt strictly lower-priority holders.
        """
        if not request.agent_id:
            raise SchedulerError("claim.agent_id must be a non-empty string")
        if not request.resource_id:
            raise SchedulerError("claim.resource_id must be a non-empty string")

        conflicts = self.conflicts(
            request.resource_id,
            request.start,
            request.end,
            exclude_agent=request.agent_id,
        )
        decision = self._policy(self, request, conflicts)

        # Remove preempted entries from the live table.
        if decision.preempted:
            removed_ids = {id(r) for r in decision.preempted}
            self._entries = [r for r in self._entries if id(r) not in removed_ids]

        if not decision.grant:
            return ClaimResult(
                granted=False,
                reservation=None,
                conflicts=conflicts,
                preempted=decision.preempted,
            )

        # Coalesce with the agent's existing identical claim if it
        # exists — re-claiming the same window should be idempotent.
        for existing in self._entries:
            if (
                existing.agent_id == request.agent_id
                and existing.resource_id == request.resource_id
                and existing.start == request.start
                and existing.end == request.end
            ):
                return ClaimResult(
                    granted=True,
                    reservation=existing,
                    conflicts=conflicts,
                    preempted=decision.preempted,
                )

        reservation = Reservation(
            resource_id=request.resource_id,
            start=request.start,
            end=request.end,
            agent_id=request.agent_id,
        )
        self._entries.append(reservation)
        return ClaimResult(
            granted=True,
            reservation=reservation,
            conflicts=conflicts,
            preempted=decision.preempted,
        )

    def claim_many(self, requests: Iterable[ClaimRequest]) -> list[ClaimResult]:
        """Apply a sequence of claims, stopping at the first denial.

        Atomic: on a denial, all previously-granted claims in this
        batch are rolled back so the scheduler ends up exactly as it
        started. Returns the list of results up to (and including)
        the failed claim — the caller can read ``granted=False`` to
        know which one tripped.
        """
        granted: list[Reservation] = []
        results: list[ClaimResult] = []
        for req in requests:
            result = self.claim(req)
            results.append(result)
            if not result.granted:
                # Roll back: drop each reservation we added in this
                # batch.
                for r in granted:
                    self._remove_exact(r)
                return results
            assert result.reservation is not None
            granted.append(result.reservation)
        return results

    def release(
        self,
        agent_id: str,
        resource_id: str,
        *,
        start: time | datetime | str | None = None,
        end: time | datetime | str | None = None,
    ) -> int:
        """Release matching claims; return how many were removed.

        Without ``start`` / ``end``, every claim by ``agent_id`` on
        ``resource_id`` is dropped. With them, only the claim whose
        interval matches exactly is dropped.
        """
        if not agent_id:
            raise SchedulerError("release.agent_id must be a non-empty string")
        before = len(self._entries)
        s = _as_time(start) if start is not None else None
        e = _as_time(end) if end is not None else None

        def _matches(r: Reservation) -> bool:
            if r.agent_id != agent_id or r.resource_id != resource_id:
                return False
            if s is not None and r.start != s:
                return False
            if e is not None and r.end != e:
                return False
            return True

        self._entries = [r for r in self._entries if not _matches(r)]
        return before - len(self._entries)

    def release_all(self, agent_id: str) -> int:
        """Release every claim held by ``agent_id``. Returns count removed."""
        if not agent_id:
            raise SchedulerError("release_all.agent_id must be a non-empty string")
        before = len(self._entries)
        self._entries = [r for r in self._entries if r.agent_id != agent_id]
        return before - len(self._entries)

    def clear(self) -> None:
        """Drop every reservation. Mostly useful for tests."""
        self._entries.clear()

    def clone(self) -> SharedScheduler:
        """Return an independent scheduler holding the same reservations.

        Used by trial-based planners (the joint optimizer in
        :mod:`semantic_toponav.coordination.joint`, for example) that
        want to evaluate "what if we ran this ordering?" without
        mutating the live coordination state. The new scheduler shares
        the same policy reference — policies are pure callables, so no
        copy is needed — but holds an independent list of
        :class:`Reservation` entries. Mutations on the clone (claims,
        releases) never propagate to the original.
        """
        new = SharedScheduler(policy=self._policy)
        new._entries = list(self._entries)
        return new

    # ----- internals ----------------------------------------------------

    def _remove_exact(self, target: Reservation) -> None:
        self._entries = [r for r in self._entries if r is not target]
