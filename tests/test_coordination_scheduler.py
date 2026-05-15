"""Tests for the in-memory SharedScheduler + ClaimResult."""

from __future__ import annotations

from datetime import time

import pytest

from semantic_toponav.coordination.policies import priority_based
from semantic_toponav.coordination.scheduler import (
    ClaimRequest,
    SchedulerError,
    SharedScheduler,
    _intervals_overlap,
)


def test_intervals_overlap_basic_non_overlapping() -> None:
    assert not _intervals_overlap(time(9, 0), time(10, 0), time(10, 0), time(11, 0))
    assert not _intervals_overlap(time(9, 0), time(10, 0), time(11, 0), time(12, 0))


def test_intervals_overlap_overlapping() -> None:
    assert _intervals_overlap(time(9, 0), time(11, 0), time(10, 0), time(12, 0))
    assert _intervals_overlap(time(9, 0), time(12, 0), time(10, 0), time(11, 0))


def test_intervals_overlap_zero_length_never_overlaps() -> None:
    assert not _intervals_overlap(time(10, 0), time(10, 0), time(9, 0), time(11, 0))


def test_intervals_overlap_midnight_wrap() -> None:
    # [22:00, 06:00) wraps midnight; [05:00, 07:00) overlaps the wrap tail.
    assert _intervals_overlap(time(22, 0), time(6, 0), time(5, 0), time(7, 0))
    # [22:00, 06:00) does not overlap [10:00, 12:00).
    assert not _intervals_overlap(time(22, 0), time(6, 0), time(10, 0), time(12, 0))


def test_claim_first_grants() -> None:
    s = SharedScheduler()
    req = ClaimRequest(
        agent_id="r1",
        resource_id="corridor_main",
        start=time(10, 0),
        end=time(11, 0),
    )
    result = s.claim(req)
    assert result.granted is True
    assert result.reservation is not None
    assert result.reservation.agent_id == "r1"
    assert len(s) == 1


def test_claim_conflict_denied_under_fcfs() -> None:
    s = SharedScheduler()
    s.claim(
        ClaimRequest(
            agent_id="r1",
            resource_id="corridor_main",
            start=time(10, 0),
            end=time(11, 0),
        )
    )
    result = s.claim(
        ClaimRequest(
            agent_id="r2",
            resource_id="corridor_main",
            start=time(10, 30),
            end=time(11, 30),
        )
    )
    assert result.granted is False
    assert len(result.conflicts) == 1
    assert result.conflicts[0].agent_id == "r1"
    assert len(s) == 1  # denied claim is not stored


def test_claim_same_agent_same_window_is_idempotent() -> None:
    s = SharedScheduler()
    req = ClaimRequest(
        agent_id="r1",
        resource_id="corridor_main",
        start=time(10, 0),
        end=time(11, 0),
    )
    a = s.claim(req)
    b = s.claim(req)
    assert a.granted and b.granted
    assert len(s) == 1
    assert a.reservation is b.reservation


def test_claim_non_overlapping_windows_both_granted() -> None:
    s = SharedScheduler()
    s.claim(
        ClaimRequest(
            agent_id="r1",
            resource_id="corridor_main",
            start=time(10, 0),
            end=time(11, 0),
        )
    )
    second = s.claim(
        ClaimRequest(
            agent_id="r2",
            resource_id="corridor_main",
            start=time(11, 0),
            end=time(12, 0),
        )
    )
    assert second.granted is True
    assert len(s) == 2


def test_priority_policy_preempts_lower_priority() -> None:
    s = SharedScheduler(policy=priority_based)
    s.claim(
        ClaimRequest(
            agent_id="r1",
            resource_id="elevator_1f",
            start=time(10, 0),
            end=time(11, 0),
        )
    )
    high = s.claim(
        ClaimRequest(
            agent_id="r2",
            resource_id="elevator_1f",
            start=time(10, 30),
            end=time(11, 30),
            priority=5,
        )
    )
    assert high.granted is True
    assert len(high.preempted) == 1
    assert high.preempted[0].agent_id == "r1"
    # r1's claim is gone; r2's claim is the only one held.
    assert {r.agent_id for r in s.reservations()} == {"r2"}


def test_priority_policy_default_priority_does_not_preempt() -> None:
    s = SharedScheduler(policy=priority_based)
    s.claim(
        ClaimRequest(
            agent_id="r1",
            resource_id="elevator_1f",
            start=time(10, 0),
            end=time(11, 0),
        )
    )
    same = s.claim(
        ClaimRequest(
            agent_id="r2",
            resource_id="elevator_1f",
            start=time(10, 30),
            end=time(11, 30),
            priority=0,
        )
    )
    assert same.granted is False


def test_claim_many_atomic_rollback_on_denial() -> None:
    s = SharedScheduler()
    s.claim(
        ClaimRequest(
            agent_id="other",
            resource_id="corridor_2f",
            start=time(10, 0),
            end=time(11, 0),
        )
    )
    # r1 tries to claim three resources; the second one conflicts.
    reqs = [
        ClaimRequest(
            agent_id="r1",
            resource_id="entrance",
            start=time(10, 0),
            end=time(11, 0),
        ),
        ClaimRequest(
            agent_id="r1",
            resource_id="corridor_2f",  # conflicts
            start=time(10, 0),
            end=time(11, 0),
        ),
        ClaimRequest(
            agent_id="r1",
            resource_id="office_2f",
            start=time(10, 0),
            end=time(11, 0),
        ),
    ]
    results = s.claim_many(reqs)
    assert len(results) == 2
    assert results[0].granted is True
    assert results[1].granted is False
    # The first grant is rolled back so r1 holds nothing.
    assert s.claims_for("r1") == []


def test_release_specific_window() -> None:
    s = SharedScheduler()
    s.claim(
        ClaimRequest(
            agent_id="r1",
            resource_id="corridor_main",
            start=time(10, 0),
            end=time(11, 0),
        )
    )
    s.claim(
        ClaimRequest(
            agent_id="r1",
            resource_id="corridor_main",
            start=time(13, 0),
            end=time(14, 0),
        )
    )
    removed = s.release(
        "r1",
        "corridor_main",
        start=time(10, 0),
        end=time(11, 0),
    )
    assert removed == 1
    assert len(s.claims_for("r1")) == 1
    assert s.claims_for("r1")[0].start == time(13, 0)


def test_release_all_drops_agent_claims_only() -> None:
    s = SharedScheduler()
    s.claim(
        ClaimRequest(
            agent_id="r1",
            resource_id="entrance",
            start=time(10, 0),
            end=time(11, 0),
        )
    )
    s.claim(
        ClaimRequest(
            agent_id="r2",
            resource_id="lab",
            start=time(10, 0),
            end=time(11, 0),
        )
    )
    removed = s.release_all("r1")
    assert removed == 1
    assert {r.agent_id for r in s.reservations()} == {"r2"}


def test_table_snapshot_does_not_alias_internal_state() -> None:
    s = SharedScheduler()
    s.claim(
        ClaimRequest(
            agent_id="r1",
            resource_id="entrance",
            start=time(10, 0),
            end=time(11, 0),
        )
    )
    table = s.table()
    s.clear()
    # Snapshot still has the original entry; clearing the scheduler
    # doesn't reach into the returned snapshot.
    assert len(table.entries) == 1


def test_conflicts_excludes_own_agent() -> None:
    s = SharedScheduler()
    s.claim(
        ClaimRequest(
            agent_id="r1",
            resource_id="entrance",
            start=time(10, 0),
            end=time(11, 0),
        )
    )
    # Asking about r1's own window with exclude_agent="r1" returns nothing.
    out = s.conflicts(
        "entrance",
        time(10, 30),
        time(11, 30),
        exclude_agent="r1",
    )
    assert out == []
    # Without the exclusion, the existing claim shows up.
    out2 = s.conflicts(
        "entrance",
        time(10, 30),
        time(11, 30),
    )
    assert len(out2) == 1


def test_empty_agent_id_rejected() -> None:
    s = SharedScheduler()
    with pytest.raises(SchedulerError):
        s.claim(
            ClaimRequest(
                agent_id="",
                resource_id="entrance",
                start=time(10, 0),
                end=time(11, 0),
            )
        )
    with pytest.raises(SchedulerError):
        s.release("", "entrance")
    with pytest.raises(SchedulerError):
        s.release_all("")
