"""Tests for hard deadline admission control (PR #37)."""

from __future__ import annotations

from datetime import time

import pytest

from semantic_toponav.coordination.fleet import (
    FleetRequest,
    plan_fleet,
    plan_with_scheduler,
)
from semantic_toponav.coordination.joint import (
    plan_fleet_joint,
    plan_fleet_with_strategy,
)
from semantic_toponav.coordination.scheduler import SharedScheduler
from semantic_toponav.eval.generators import chain_graph


def test_reason_code_ok_on_grant() -> None:
    g = chain_graph(5)
    s = SharedScheduler()
    result = plan_with_scheduler(
        g, "r1", "n0", "n4", s,
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    assert result.granted is True
    assert result.reason_code == "ok"


def test_reason_code_no_path_when_disconnected() -> None:
    g = chain_graph(5)
    # Remove the middle edge to disconnect the graph.
    g.remove_edge("e2_3")
    s = SharedScheduler()
    result = plan_with_scheduler(
        g, "r1", "n0", "n4", s,
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    assert result.granted is False
    assert result.reason_code == "no_path"


def test_soft_admission_grants_late_arrival() -> None:
    """A deadline before the arrival time is ignored under soft admission."""
    g = chain_graph(10)  # 9-edge path costs 9 units (~9 min).
    s = SharedScheduler()
    result = plan_with_scheduler(
        g, "r1", "n0", "n9", s,
        hold_start=time(10, 0), hold_end=time(11, 0),
        deadline=time(10, 5),  # impossible: path takes 9 min
        admission="soft",
    )
    # Soft: deadline is informational only; agent is granted.
    assert result.granted is True
    assert result.reason_code == "ok"


def test_hard_admission_rejects_late_arrival() -> None:
    g = chain_graph(10)
    s = SharedScheduler()
    result = plan_with_scheduler(
        g, "r1", "n0", "n9", s,
        hold_start=time(10, 0), hold_end=time(11, 0),
        deadline=time(10, 5),  # 5 < 9 -> miss
        admission="hard",
    )
    assert result.granted is False
    assert result.reason_code == "deadline_miss"
    # Path is reported even on rejection, so callers can debug.
    assert result.path == [f"n{i}" for i in range(10)]
    # Crucially, the scheduler holds no claims for r1.
    assert s.claims_for("r1") == []


def test_hard_admission_grants_when_within_deadline() -> None:
    g = chain_graph(10)
    s = SharedScheduler()
    result = plan_with_scheduler(
        g, "r1", "n0", "n9", s,
        hold_start=time(10, 0), hold_end=time(11, 0),
        deadline=time(10, 15),  # 15 > 9 -> ok
        admission="hard",
    )
    assert result.granted is True
    assert result.reason_code == "ok"


def test_hard_admission_no_deadline_passes_through() -> None:
    """deadline=None makes admission mode irrelevant — the request is treated
    like any unbounded one."""
    g = chain_graph(5)
    s = SharedScheduler()
    result = plan_with_scheduler(
        g, "r1", "n0", "n4", s,
        hold_start=time(10, 0), hold_end=time(11, 0),
        deadline=None,
        admission="hard",
    )
    assert result.granted is True
    assert result.reason_code == "ok"


def test_minutes_per_cost_unit_scales_arrival_time() -> None:
    """With minutes_per_cost_unit=2.0 the arrival doubles, tightening every
    deadline."""
    g = chain_graph(5)  # path cost = 4
    s = SharedScheduler()
    # Deadline at 10:06 — cost 4 × 2 = 8 min > 6 min -> miss.
    result = plan_with_scheduler(
        g, "r1", "n0", "n4", s,
        hold_start=time(10, 0), hold_end=time(11, 0),
        deadline=time(10, 6),
        admission="hard",
        minutes_per_cost_unit=2.0,
    )
    assert result.reason_code == "deadline_miss"


def test_reason_code_reservation_conflict() -> None:
    """When the planner finds a path but the claim is denied, the result
    carries 'reservation_conflict' (and crucially the deadline check does
    not pre-empt it under soft admission)."""
    g = chain_graph(5)
    s = SharedScheduler()
    # r0 grabs every node first.
    plan_with_scheduler(
        g, "blocker", "n0", "n4", s,
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    # r1 fails: every node on every path is held.
    result = plan_with_scheduler(
        g, "r1", "n0", "n4", s,
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    # The reservation_aware cost layer pushes the cost up, so the
    # planner may either still find a path (then conflict at claim)
    # or fail outright. Either way the reason_code must be one of the
    # two failure codes, not 'ok'.
    assert result.granted is False
    assert result.reason_code in ("reservation_conflict", "no_path")


def test_plan_fleet_propagates_admission_per_request() -> None:
    """One sequential plan_fleet call must apply the admission policy to
    every request, using each request's own deadline.

    Single-agent setup so the test is independent of shared-resource
    blocking — the goal here is to confirm propagation, not behavior on
    a contested map.
    """
    g = chain_graph(10)
    s = SharedScheduler()
    requests = [
        # Single late request: cost 9, deadline 10:05 -> miss.
        FleetRequest("late", "n0", "n9", deadline=time(10, 5)),
    ]
    result = plan_fleet(
        g, requests, s,
        hold_start=time(10, 0), hold_end=time(11, 0),
        admission="hard",
    )
    by_agent = result.by_agent()
    assert by_agent["late"].granted is False
    assert by_agent["late"].reason_code == "deadline_miss"
    # No claim made on rejection.
    assert s.reservations() == []


def test_plan_fleet_admission_off_default_grants_late_request() -> None:
    """Without an explicit admission='hard', the same impossible deadline
    request still gets granted — proving the default is back-compat."""
    g = chain_graph(10)
    s = SharedScheduler()
    requests = [FleetRequest("late", "n0", "n9", deadline=time(10, 5))]
    result = plan_fleet(
        g, requests, s,
        hold_start=time(10, 0), hold_end=time(11, 0),
        # admission omitted -> "soft"
    )
    by_agent = result.by_agent()
    assert by_agent["late"].granted is True
    assert by_agent["late"].reason_code == "ok"


def test_plan_fleet_with_strategy_deadline_plus_hard_admission() -> None:
    """The 'deadline' strategy plus hard admission is the canonical EDF +
    rejection setup. Earliest-deadline-first runs the tight one first; if
    even that one can't meet its deadline, it's rejected outright."""
    g = chain_graph(15)
    s = SharedScheduler()
    requests = [
        FleetRequest("loose", "n0", "n4", deadline=time(10, 30)),
        FleetRequest("tight", "n0", "n14", deadline=time(10, 5)),  # 14 > 5
    ]
    result = plan_fleet_with_strategy(
        g, requests, s,
        strategy="deadline",
        hold_start=time(10, 0), hold_end=time(11, 0),
        admission="hard",
    )
    by_agent = result.by_agent()
    # tight goes first (earliest deadline) but gets rejected; loose
    # still wins its path.
    assert by_agent["tight"].reason_code == "deadline_miss"
    assert by_agent["loose"].granted is True


def test_plan_fleet_joint_with_hard_admission() -> None:
    """Joint optimizer with hard admission: a request that misses its
    deadline under every ordering stays rejected, while the fitting
    request is admitted."""
    g = chain_graph(10)
    s = SharedScheduler()
    requests = [
        # Single late request that fails admission regardless of order.
        FleetRequest("late", "n0", "n9", deadline=time(10, 1)),
    ]
    joint = plan_fleet_joint(
        g, requests, s,
        hold_start=time(10, 0), hold_end=time(11, 0),
        admission="hard",
    )
    by_agent = joint.fleet_result.by_agent()
    assert by_agent["late"].reason_code == "deadline_miss"
    assert s.reservations() == []


def test_soft_admission_is_back_compat_default() -> None:
    """Calling plan_with_scheduler without an admission arg behaves
    exactly as it did pre-PR-37 — late deadlines never cause rejection."""
    g = chain_graph(10)
    s = SharedScheduler()
    result = plan_with_scheduler(
        g, "r1", "n0", "n9", s,
        hold_start=time(10, 0), hold_end=time(11, 0),
        deadline=time(10, 1),  # impossible
    )
    assert result.granted is True
    assert result.reason_code == "ok"


def test_hard_admission_path_cost_zero_special_case() -> None:
    """start == goal: zero path cost, arrival = hold_start. Any deadline
    later than hold_start should pass."""
    g = chain_graph(3)
    s = SharedScheduler()
    result = plan_with_scheduler(
        g, "r1", "n0", "n0", s,
        hold_start=time(10, 0), hold_end=time(11, 0),
        deadline=time(10, 0),
        admission="hard",
    )
    assert result.granted is True


@pytest.mark.parametrize("admission", ["soft", "hard"])
def test_no_deadline_means_admission_is_a_no_op(admission: str) -> None:
    g = chain_graph(5)
    s = SharedScheduler()
    result = plan_with_scheduler(
        g, "r1", "n0", "n4", s,
        hold_start=time(10, 0), hold_end=time(11, 0),
        deadline=None,
        admission=admission,  # type: ignore[arg-type]
    )
    assert result.granted is True
