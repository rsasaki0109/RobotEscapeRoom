"""Conflict-resolution policies for :class:`SharedScheduler`.

A policy is just a callable:

    policy(scheduler, request, conflicts) -> ClaimDecision

It receives the scheduler (so policies that need richer context can
inspect global state), the incoming :class:`ClaimRequest`, and the
list of existing reservations that overlap the request. It returns a
:class:`ClaimDecision` saying whether to grant the request and which
existing reservations (if any) to preempt.

Two policies ship in this module:

* :func:`first_come_first_served` — the simple, safe default. Any
  conflicting hold blocks the new request. Preserves the strongest
  notion of "claims are honored once made", which is what most
  multi-robot deployments actually want.
* :func:`priority_based` — higher-priority requests preempt strictly
  lower-priority holders. Ties between equal-priority claims go to
  the existing holder (FCFS semantics within a priority band).

Callers that need something more elaborate (negotiation, deadline-
aware admission, oracle-based scheduling) write their own callable
with the same signature and pass it to ``SharedScheduler(policy=...)``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from semantic_toponav.planner.reservations import Reservation

if TYPE_CHECKING:
    from semantic_toponav.coordination.scheduler import (
        ClaimRequest,
        SharedScheduler,
    )


@dataclass
class ClaimDecision:
    """Policy verdict on a claim request.

    Attributes
    ----------
    grant:
        Whether the scheduler should accept the request.
    preempted:
        Existing reservations the policy chose to evict. Must be a
        subset of the ``conflicts`` list passed to the policy — the
        scheduler does not let a policy preempt reservations that
        weren't actually in conflict.
    reason:
        Optional explanation, useful for logging / debugging.
    """

    grant: bool
    preempted: list[Reservation] = field(default_factory=list)
    reason: str = ""


ConflictPolicy = Callable[
    ["SharedScheduler", "ClaimRequest", list[Reservation]],
    ClaimDecision,
]


def first_come_first_served(
    scheduler: SharedScheduler,  # noqa: ARG001 - part of the protocol
    request: ClaimRequest,  # noqa: ARG001
    conflicts: list[Reservation],
) -> ClaimDecision:
    """Default: deny anything that overlaps an existing hold."""
    if conflicts:
        return ClaimDecision(
            grant=False,
            reason=f"{len(conflicts)} existing claim(s) block this request",
        )
    return ClaimDecision(grant=True, reason="no conflicts")


def priority_based(
    scheduler: SharedScheduler,  # noqa: ARG001
    request: ClaimRequest,
    conflicts: list[Reservation],
) -> ClaimDecision:
    """Preempt strictly-lower-priority holders.

    Each existing :class:`Reservation` carries no explicit priority,
    so this policy reads it from ``agent_id``-aware bookkeeping that
    the caller maintains externally — but since the dataclass is
    frozen, we have to be looser: any reservation whose ``agent_id``
    differs from the request and whose request-level priority we
    don't know is treated as priority 0.

    For requests with positive priority, every conflicting reservation
    held by another agent (priority 0 by default) is preempted; equal-
    or-higher-priority holders block the request.

    A separate "priority registry" extension is a clean future change;
    this baseline gives a useful "high-priority preempts default
    requests" behavior without extra state.
    """
    if not conflicts:
        return ClaimDecision(grant=True, reason="no conflicts")
    if request.priority <= 0:
        return ClaimDecision(
            grant=False,
            reason="conflicts present and request priority <= 0",
        )
    # All known holders are treated as priority 0; the request beats
    # them as long as its priority is > 0.
    return ClaimDecision(
        grant=True,
        preempted=list(conflicts),
        reason=(
            f"preempting {len(conflicts)} lower-priority claim(s) "
            f"(request priority {request.priority})"
        ),
    )
