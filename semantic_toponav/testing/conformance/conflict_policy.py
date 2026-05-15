"""Conformance suite for the ``ConflictPolicy`` callable type.

A policy is a plain callable

    policy(scheduler, request, conflicts) -> ClaimDecision

so there is no Protocol class to ``isinstance``-check against. The
suite verifies the call signature and the two invariants the scheduler
relies on when applying the decision:

* The returned :class:`ClaimDecision`'s ``preempted`` list is a subset
  of the ``conflicts`` the policy was shown — the scheduler refuses to
  evict reservations the policy never inspected.
* Calling the policy is read-only with respect to the
  ``conflicts`` list (it must not mutate the list in place).

The check that "no conflicts ⇒ grant=True" is exposed as an *opt-in*
extension (``check_empty_conflicts_grants=True``) because it is a
convention the two shipped policies satisfy, not a hard requirement
of the type. Custom policies that deny on other grounds (deadline,
licensing) can pass ``False``.
"""

from __future__ import annotations

from datetime import time

from semantic_toponav.coordination.policies import (
    ClaimDecision,
    ConflictPolicy,
)
from semantic_toponav.coordination.scheduler import (
    ClaimRequest,
    SharedScheduler,
)
from semantic_toponav.planner.reservations import Reservation


def run_conflict_policy_conformance(
    policy: ConflictPolicy,
    *,
    check_empty_conflicts_grants: bool = True,
) -> None:
    """Run the :class:`ConflictPolicy` conformance checks.

    Parameters
    ----------
    policy:
        The policy callable under test.
    check_empty_conflicts_grants:
        Whether to assert that ``policy(sched, request, []) ->
        grant=True``. Both built-in policies satisfy this; custom
        policies that veto on other grounds (e.g. SLA, licensing)
        should pass ``False`` and exercise their grant path in their
        own tests.
    """

    assert callable(policy), (
        f"ConflictPolicy must be callable, got {type(policy).__name__}"
    )

    sched = SharedScheduler()
    request = ClaimRequest(
        agent_id="probe",
        resource_id="r1",
        start=time(9, 0),
        end=time(9, 30),
        priority=0,
    )

    # ---- empty conflicts ---------------------------------------------------
    decision_empty = policy(sched, request, [])
    assert isinstance(decision_empty, ClaimDecision), (
        f"policy must return ClaimDecision, got "
        f"{type(decision_empty).__name__}"
    )
    if check_empty_conflicts_grants:
        assert decision_empty.grant is True, (
            f"policy denied a request with zero conflicts: {decision_empty!r}"
        )
    assert decision_empty.preempted == [], (
        "policy preempted reservations when it was shown zero conflicts — "
        "preempted must be a subset of conflicts"
    )

    # ---- non-empty conflicts ----------------------------------------------
    existing = Reservation(
        resource_id="r1",
        start=time(9, 15),
        end=time(9, 45),
        agent_id="holder",
    )
    conflicts_list = [existing]
    conflicts_snapshot = list(conflicts_list)
    decision = policy(sched, request, conflicts_list)

    assert isinstance(decision, ClaimDecision), (
        f"policy must return ClaimDecision, got {type(decision).__name__}"
    )
    assert isinstance(decision.preempted, list), (
        f"decision.preempted must be list, got "
        f"{type(decision.preempted).__name__}"
    )

    preempted_ids = {id(r) for r in decision.preempted}
    conflict_ids = {id(r) for r in conflicts_snapshot}
    assert preempted_ids.issubset(conflict_ids), (
        "decision.preempted contains reservations that were not in the "
        "conflicts argument — policies may only preempt entries they "
        "were shown"
    )

    assert conflicts_list == conflicts_snapshot, (
        "policy mutated the conflicts list in place — it must treat the "
        "argument as read-only"
    )

    # ---- preempted has no duplicates --------------------------------------
    # A policy that double-counts a conflict (e.g. concatenating lists by
    # mistake) silently asks the scheduler to evict the same reservation
    # twice. The scheduler tolerates it, but downstream agents see an
    # exaggerated preemption count. Reject it at conformance time.
    preempted_object_ids = [id(r) for r in decision.preempted]
    assert len(preempted_object_ids) == len(set(preempted_object_ids)), (
        f"decision.preempted contains duplicate entries: {decision.preempted!r}"
    )

    # ---- policy must not mutate the scheduler -----------------------------
    # The policy receives the live scheduler for inspection only — the
    # caller (SharedScheduler.claim) is the one that commits the decision.
    # A policy that mutates the scheduler in place double-applies the
    # effect once the caller writes the result back.
    sched_before_len = len(sched)
    sched_before_reservations = sched.reservations()
    policy(sched, request, conflicts_list)
    assert len(sched) == sched_before_len, (
        f"policy mutated scheduler size: {sched_before_len} -> {len(sched)}"
    )
    assert sched.reservations() == sched_before_reservations, (
        "policy mutated scheduler reservations — policies must be "
        "side-effect-free with respect to the scheduler argument"
    )
