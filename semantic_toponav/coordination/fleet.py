"""Multi-agent path planning bound to a live :class:`SharedScheduler`.

Two entry points:

* :func:`plan_with_scheduler` — plan one agent against the current
  scheduler state, attempt to reserve every node and edge along the
  resulting path, and return a result that records the path, the
  reservations actually granted, and (on failure) what stood in the
  way.
* :func:`plan_fleet` — apply :func:`plan_with_scheduler` to a list of
  :class:`FleetRequest` entries in the given order. Sequential greedy
  is the simplest correct strategy: each agent sees the holds left by
  the previous ones, so the same input always yields the same plan
  regardless of which thread submits first. Callers that need a
  fairer global optimum write their own scheduler or sort the
  requests before calling.

These helpers stay strictly above the planner core. They build a
``reservation_aware`` cost function from the scheduler's snapshot,
forward to ``plan_astar`` / ``plan_dijkstra``, then call
``scheduler.claim_many`` to seal the path's resources. The cost-
function composition stays open: callers pass any extra ``base_cost``
they want stacked on top of the reservation layer
(``avoid_restricted``, ``avoid_stairs``, ``prefer_elevator``, etc).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Literal

from semantic_toponav.coordination.scheduler import (
    ClaimRequest,
    SharedScheduler,
)
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.planner.astar import plan_astar
from semantic_toponav.planner.dijkstra import plan_dijkstra
from semantic_toponav.planner.errors import NoPathError, PlanningError
from semantic_toponav.planner.reservations import (
    Reservation,
    reservation_aware,
)
from semantic_toponav.planner.semantic_costs import (
    CostFn,
    _as_time,
    compose_costs,
)


@dataclass
class FleetRequest:
    """One agent's planning request inside a fleet call.

    Attributes
    ----------
    agent_id, start, goal:
        Plain identifiers, forwarded to :func:`plan_with_scheduler`.
    priority:
        Forwarded as the priority on every claim this agent makes.
        Read by the ``priority_based`` policy; ignored by FCFS.
    deadline:
        Optional time-of-day acting as a sort key for the
        ``deadline`` / EDF strategy in
        :func:`semantic_toponav.coordination.plan_fleet_with_strategy`.
        Has no effect on the scheduler claims themselves (which use
        ``hold_start`` / ``hold_end``); it is a hint about *when* this
        request needs to be admitted relative to others.
    """

    agent_id: str
    start: str
    goal: str
    priority: int = 0
    deadline: time | str | None = None


ReasonCode = Literal[
    "ok",
    "no_path",
    "deadline_miss",
    "reservation_conflict",
    "policy_rejected",
]


@dataclass
class PlanWithSchedulerResult:
    """Outcome of :func:`plan_with_scheduler` for one agent.

    Attributes
    ----------
    granted:
        Boolean shorthand. ``True`` iff the path was planned *and*
        every resource on it was successfully claimed.
    reason_code:
        Structured outcome code. Always set:

        * ``"ok"`` — granted.
        * ``"no_path"`` — A* / Dijkstra reported no path.
        * ``"deadline_miss"`` — admission was ``"hard"`` and the
          projected arrival time would have exceeded the request's
          deadline; the scheduler was *not* mutated.
        * ``"reservation_conflict"`` — a path was found but the
          atomic claim attempt was denied. Partial claims have already
          been rolled back by :meth:`SharedScheduler.claim_many`.
        * ``"policy_rejected"`` — reserved for future custom policies.

        Use this for switch / dispatch logic; ``failure_reason`` is
        the matching human-readable detail.
    failure_reason:
        Free-form string suitable for logging. ``None`` when granted.
    conflicts:
        Existing reservations that blocked the request, present on
        ``reservation_conflict``.
    """

    agent_id: str
    path: list[str] = field(default_factory=list)
    claims: list[Reservation] = field(default_factory=list)
    granted: bool = False
    failure_reason: str | None = None
    conflicts: list[Reservation] = field(default_factory=list)
    reason_code: ReasonCode = "ok"

    def to_dict(self) -> dict[str, object]:
        """JSON-serializable form. v1-stable — see ``schemas/plan_with_scheduler_result_v1.schema.json``."""
        return {
            "agent_id": self.agent_id,
            "path": list(self.path),
            "claims": [_reservation_to_dict(r) for r in self.claims],
            "granted": bool(self.granted),
            "failure_reason": self.failure_reason,
            "conflicts": [_reservation_to_dict(r) for r in self.conflicts],
            "reason_code": self.reason_code,
        }


@dataclass
class FleetPlanResult:
    """Outcome of :func:`plan_fleet` across all agents."""

    results: list[PlanWithSchedulerResult] = field(default_factory=list)

    @property
    def all_granted(self) -> bool:
        return bool(self.results) and all(r.granted for r in self.results)

    def by_agent(self) -> dict[str, PlanWithSchedulerResult]:
        return {r.agent_id: r for r in self.results}

    def to_dict(self) -> dict[str, object]:
        """JSON-serializable form. v1-stable — see ``schemas/fleet_plan_result_v1.schema.json``."""
        return {
            "results": [r.to_dict() for r in self.results],
            "all_granted": bool(self.all_granted),
        }


def _reservation_to_dict(r: Reservation) -> dict[str, object]:
    """Render a :class:`Reservation` as a v1-stable JSON object.

    Mirrors the time-format used by the rest of the v1 wire surfaces
    (``HH:MM:SS``) so cross-schema round-trips don't drift.
    """
    return {
        "resource_id": r.resource_id,
        "start": r.start.isoformat(timespec="seconds"),
        "end": r.end.isoformat(timespec="seconds"),
        "agent_id": r.agent_id,
    }


def _path_resources(
    graph: TopologyGraph,
    path: list[str],
    *,
    claim_nodes: bool,
    claim_edges: bool,
) -> list[str]:
    """Return the resource ids the agent will occupy along ``path``.

    Order matches traversal order, with duplicates removed (an agent
    that revisits a node only needs to claim it once for the
    coordinator).
    """
    out: list[str] = []
    seen: set[str] = set()

    def _push(rid: str) -> None:
        if rid not in seen:
            seen.add(rid)
            out.append(rid)

    if claim_nodes:
        for nid in path:
            _push(nid)
    if claim_edges:
        for a, b in zip(path[:-1], path[1:], strict=True):
            edge = None
            for e in graph.neighbors(a):
                if graph.other_end(e, a) == b:
                    edge = e
                    break
            if edge is not None:
                _push(edge.id)
    return out


def _path_cost_total(graph: TopologyGraph, path: list[str]) -> float:
    """Sum the raw edge cost along ``path`` (no cost-fn composition)."""
    if len(path) < 2:
        return 0.0
    total = 0.0
    for a, b in zip(path[:-1], path[1:], strict=True):
        for edge in graph.neighbors(a):
            if graph.other_end(edge, a) == b:
                total += float(edge.cost)
                break
    return total


def _time_to_minute(t: time) -> int:
    """``time(h, m, s)`` → minute-of-day. Seconds round down."""
    return t.hour * 60 + t.minute


def plan_with_scheduler(
    graph: TopologyGraph,
    agent_id: str,
    start: str,
    goal: str,
    scheduler: SharedScheduler,
    *,
    hold_start: time | datetime | str,
    hold_end: time | datetime | str,
    at_time: time | datetime | str | None = None,
    base_cost_fn: CostFn | None = None,
    algorithm: Literal["astar", "dijkstra"] = "astar",
    priority: int = 0,
    claim_nodes: bool = True,
    claim_edges: bool = True,
    deadline: time | datetime | str | None = None,
    admission: Literal["soft", "hard"] = "soft",
    minutes_per_cost_unit: float = 1.0,
) -> PlanWithSchedulerResult:
    """Plan + claim atomically against the live scheduler.

    Parameters
    ----------
    graph, start, goal, algorithm:
        Forwarded to the planner.
    agent_id:
        Owner string recorded on every reservation this call makes.
    scheduler:
        Coordination state. ``scheduler.table()`` is snapshotted to
        build the cost layer, then ``scheduler.claim_many`` seals the
        path's resources.
    hold_start, hold_end:
        Time-of-day window the claims cover. Forwarded to every
        :class:`ClaimRequest` made on the agent's behalf.
    at_time:
        Time-of-day used by ``reservation_aware`` when scoring edges.
        Defaults to ``hold_start`` so the planner evaluates against
        the start of the held window (which is what the agent will
        actually traverse first).
    base_cost_fn:
        Optional extra cost function (``avoid_restricted``,
        ``prefer_elevator``, etc.) stacked *under* the reservation
        layer via :func:`compose_costs`.
    priority:
        Per-claim priority — read by :func:`priority_based`, ignored
        by FCFS.
    claim_nodes, claim_edges:
        Disable to reserve only edges or only nodes. The default
        claims both, which matches the simple "an agent occupies the
        full path for the duration of the hold" semantics.
    deadline:
        Optional time-of-day after which the agent's arrival is
        considered late. Only consulted when ``admission="hard"``.
    admission:
        ``"soft"`` (default) keeps the pre-PR-37 behavior: ``deadline``
        is purely a sort hint for the deadline strategy and never
        blocks a grant. ``"hard"`` enables admission control: if the
        projected arrival time (``hold_start + path_cost ×
        minutes_per_cost_unit``) exceeds ``deadline``, the request
        is rejected with ``reason_code="deadline_miss"`` and no
        resources are claimed.
    minutes_per_cost_unit:
        Conversion factor from raw edge-cost units to minutes of
        traversal. The default ``1.0`` matches the example graphs
        (cost ≈ minutes). Adjust when an edge's cost has a different
        physical meaning (e.g. heuristic distance in metres).

    Returns
    -------
    PlanWithSchedulerResult
        On success, ``granted=True`` with ``path`` and ``claims``
        populated and ``reason_code="ok"``. On failure,
        ``granted=False`` with a structured ``reason_code`` and a
        human-readable ``failure_reason``. Partial claims are always
        rolled back by :meth:`SharedScheduler.claim_many`, so a
        denied call leaves the scheduler exactly as it was before.
    """
    if at_time is None:
        at_time = hold_start

    # Priority > 0 requests are allowed to plan as if no reservations
    # existed; the priority policy will preempt the conflicting holders
    # at claim time. With FCFS this is unreachable anyway, so the
    # bypass only fires for the priority pathway. Keeping it gated on
    # request.priority > 0 means the default FCFS behavior is
    # unchanged: low-priority planners still see (and route around)
    # every existing claim.
    if priority > 0:
        cost_fn: CostFn = (
            base_cost_fn if base_cost_fn is not None else (lambda e: e.cost)
        )
    else:
        table = scheduler.table()
        reservation_layer = reservation_aware(table, at_time=at_time)
        cost_fn = (
            compose_costs(base_cost_fn, reservation_layer)
            if base_cost_fn is not None
            else reservation_layer
        )

    try:
        if algorithm == "dijkstra":
            path = plan_dijkstra(graph, start, goal, cost_fn=cost_fn)
        else:
            path = plan_astar(graph, start, goal, cost_fn=cost_fn)
    except (PlanningError, NoPathError) as exc:
        return PlanWithSchedulerResult(
            agent_id=agent_id,
            granted=False,
            failure_reason=f"planning failed: {exc}",
            reason_code="no_path",
        )

    # Hard deadline admission: check projected arrival against the
    # request's deadline *before* attempting to claim. Rejecting here
    # means the scheduler is never mutated on a deadline miss, which
    # is the property tests rely on.
    if admission == "hard" and deadline is not None:
        path_cost = _path_cost_total(graph, path)
        hold_start_min = _time_to_minute(_as_time(hold_start))
        arrival_min = hold_start_min + path_cost * minutes_per_cost_unit
        deadline_min = _time_to_minute(_as_time(deadline))
        if arrival_min > deadline_min:
            return PlanWithSchedulerResult(
                agent_id=agent_id,
                path=path,
                granted=False,
                failure_reason=(
                    f"deadline miss: arrival ≈ {arrival_min:.0f}min "
                    f"> deadline {deadline_min}min "
                    f"(path cost {path_cost:.2f}, "
                    f"{minutes_per_cost_unit} min/unit)"
                ),
                reason_code="deadline_miss",
            )

    resources = _path_resources(
        graph,
        path,
        claim_nodes=claim_nodes,
        claim_edges=claim_edges,
    )

    s = _as_time(hold_start)
    e = _as_time(hold_end)
    requests = [
        ClaimRequest(
            agent_id=agent_id,
            resource_id=rid,
            start=s,
            end=e,
            priority=priority,
        )
        for rid in resources
    ]
    results = scheduler.claim_many(requests)
    if results and not results[-1].granted:
        failed = results[-1]
        return PlanWithSchedulerResult(
            agent_id=agent_id,
            path=path,
            granted=False,
            failure_reason=(
                f"claim denied on {requests[len(results) - 1].resource_id!r}"
            ),
            conflicts=list(failed.conflicts),
            reason_code="reservation_conflict",
        )

    claims = [r.reservation for r in results if r.reservation is not None]
    return PlanWithSchedulerResult(
        agent_id=agent_id,
        path=path,
        claims=claims,
        granted=True,
        reason_code="ok",
    )


def plan_fleet(
    graph: TopologyGraph,
    requests: Iterable[FleetRequest],
    scheduler: SharedScheduler,
    *,
    hold_start: time | datetime | str,
    hold_end: time | datetime | str,
    at_time: time | datetime | str | None = None,
    base_cost_fn: CostFn | None = None,
    algorithm: Literal["astar", "dijkstra"] = "astar",
    claim_nodes: bool = True,
    claim_edges: bool = True,
    rollback_on_failure: bool = False,
    admission: Literal["soft", "hard"] = "soft",
    minutes_per_cost_unit: float = 1.0,
) -> FleetPlanResult:
    """Plan a list of agents sequentially against one scheduler.

    Each request is handled by :func:`plan_with_scheduler`; the
    scheduler accumulates each agent's holds before the next request
    runs, so later agents naturally route around earlier ones.

    ``rollback_on_failure=True`` releases every claim made in this
    fleet call when any single agent's plan is denied. This is the
    "all-or-nothing" mode for callers that prefer a clean failure
    over a partial assignment. The default keeps successful claims so
    the caller can decide what to do with the partial state.
    """
    out_results: list[PlanWithSchedulerResult] = []
    issued_by_agent: dict[str, list[Reservation]] = {}

    for req in requests:
        result = plan_with_scheduler(
            graph,
            req.agent_id,
            req.start,
            req.goal,
            scheduler,
            hold_start=hold_start,
            hold_end=hold_end,
            at_time=at_time,
            base_cost_fn=base_cost_fn,
            algorithm=algorithm,
            priority=req.priority,
            claim_nodes=claim_nodes,
            claim_edges=claim_edges,
            deadline=req.deadline,
            admission=admission,
            minutes_per_cost_unit=minutes_per_cost_unit,
        )
        out_results.append(result)
        if result.granted:
            issued_by_agent[req.agent_id] = list(result.claims)
        elif rollback_on_failure:
            for agent_id, _claims in issued_by_agent.items():
                scheduler.release_all(agent_id)
            # Roll back this agent's partial state too (claim_many
            # already rolled back inside plan_with_scheduler, but
            # release_all is idempotent and keeps the post-condition
            # uniform).
            scheduler.release_all(req.agent_id)
            break

    return FleetPlanResult(results=out_results)
