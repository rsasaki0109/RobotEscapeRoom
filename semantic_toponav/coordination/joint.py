"""Joint multi-agent fleet optimization on top of sequential greedy.

:func:`plan_fleet` runs the requests in caller-supplied order: each
agent sees the holds left by earlier ones, and the first agent always
wins on contended resources. That's the simplest correct policy, but
on tight maps it leaves grants on the table — reversing two agents'
order can be the difference between "both succeed" and "second one
hits a wall of holds and fails".

This module adds two layered improvements:

* :func:`plan_fleet_joint` — try multiple orderings, run each one
  against a *cloned* scheduler so it does not mutate the live state,
  score the trials (more grants is better; ties broken by lower total
  edge cost across granted paths), and apply the best trial's
  ordering to the real scheduler. For small fleets it enumerates
  every permutation; for large fleets it falls back to a fixed set of
  candidate orderings (insertion order, reverse, priority-DESC,
  deadline-ASC). Either way, exactly one ordering is committed.
* :func:`plan_fleet_with_strategy` — single dispatcher that takes
  ``strategy = "greedy" | "priority" | "deadline" | "joint"`` and
  reorders the requests before calling :func:`plan_fleet` (or, for
  ``joint``, calls :func:`plan_fleet_joint`). Keeps callers from
  having to remember which function is which.

Both helpers stay strictly above the planner core; they only sort the
agents and clone the scheduler. No planner internals change.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, time
from typing import Literal

from semantic_toponav.coordination.fleet import (
    FleetPlanResult,
    FleetRequest,
    PlanWithSchedulerResult,
    plan_fleet,
)
from semantic_toponav.coordination.scheduler import SharedScheduler
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.planner.semantic_costs import CostFn, _as_time

Strategy = Literal["greedy", "priority", "deadline", "joint"]


@dataclass
class JointPlanTrial:
    """One trial run inside :func:`plan_fleet_joint`.

    Attributes
    ----------
    order:
        The agent_id sequence used for this trial, in the order the
        scheduler saw the requests.
    granted_count:
        Number of agents whose plan was granted on the cloned
        scheduler.
    total_cost:
        Sum of edge costs across every granted path. Lower is better.
        Failed agents contribute zero — comparing two trials with the
        same ``granted_count`` then prefers the one whose granted
        agents took cheaper paths.
    results:
        Per-agent results from the cloned trial (not the live run).
    """

    order: tuple[str, ...]
    granted_count: int
    total_cost: float
    results: list[PlanWithSchedulerResult]


@dataclass
class JointPlanResult:
    """Outcome of :func:`plan_fleet_joint`.

    Attributes
    ----------
    chosen_order:
        The agent_id sequence that won the trial selection. The live
        scheduler was mutated by running this ordering for real.
    trials_evaluated:
        How many orderings were tried. Equals ``n!`` when the fleet
        was small enough to enumerate; otherwise the number of
        candidate orderings sampled.
    enumerated:
        ``True`` when every permutation of the input was tried,
        ``False`` when only sampled candidate orderings were used.
    fleet_result:
        The live :class:`FleetPlanResult` from re-running the chosen
        ordering on the real scheduler.
    """

    chosen_order: tuple[str, ...]
    trials_evaluated: int
    enumerated: bool
    fleet_result: FleetPlanResult


def _path_total_cost(graph: TopologyGraph, path: Sequence[str]) -> float:
    """Sum of edge costs along ``path``.

    Walks the path in order and looks up the matching edge for each
    consecutive pair. Returns 0.0 for an empty or single-node path.
    Falls back to a cost contribution of 0 when the edge is missing
    (the planner already validated reachability, so this is defensive
    rather than expected).
    """
    if len(path) < 2:
        return 0.0
    total = 0.0
    for a, b in zip(path[:-1], path[1:], strict=True):
        for edge in graph.neighbors(a):
            if graph.other_end(edge, a) == b:
                total += float(edge.cost)
                break
    return total


def _score_trial(
    graph: TopologyGraph,
    order: tuple[str, ...],
    results: list[PlanWithSchedulerResult],
) -> tuple[int, float]:
    """Return ``(granted_count, total_cost)`` for an ordering.

    The pair lets callers sort by ``-granted_count`` first (more
    grants is strictly better) and then by ``total_cost`` ascending
    (cheaper paths win ties). ``order`` is consumed only to keep the
    helper's signature symmetric with what the caller already carries
    around; the score itself only depends on the result list.
    """
    granted = [r for r in results if r.granted]
    cost = sum(_path_total_cost(graph, r.path) for r in granted)
    return len(granted), cost


def _reorder_by_priority(requests: Sequence[FleetRequest]) -> list[FleetRequest]:
    """Priority-DESC, stable: ties keep insertion order."""
    return sorted(requests, key=lambda r: -r.priority)


def _reorder_by_deadline(requests: Sequence[FleetRequest]) -> list[FleetRequest]:
    """Deadline-ASC (EDF). Requests with no deadline sort last; they
    are treated as "no urgency known" and yield to agents that have
    explicit cutoffs. Within the no-deadline bucket and within any
    same-deadline bucket, insertion order is preserved.
    """
    def _key(req: FleetRequest) -> tuple[int, int, int]:
        if req.deadline is None:
            return (1, 0, 0)
        t = _as_time(req.deadline)
        return (0, t.hour, t.minute * 60 + t.second)

    return sorted(requests, key=_key)


def _candidate_orderings(
    requests: Sequence[FleetRequest],
) -> list[list[FleetRequest]]:
    """Distinct heuristic orderings used when n! exceeds the cap.

    Always includes the original order; conditionally adds reverse,
    priority-DESC, deadline-ASC. Each ordering is appended only once
    even when multiple heuristics agree — duplicates would just waste
    a trial.
    """
    seen: set[tuple[str, ...]] = set()
    out: list[list[FleetRequest]] = []

    def _push(order: list[FleetRequest]) -> None:
        key = tuple(r.agent_id for r in order)
        if key not in seen:
            seen.add(key)
            out.append(order)

    _push(list(requests))
    _push(list(reversed(requests)))
    _push(_reorder_by_priority(requests))
    _push(_reorder_by_deadline(requests))
    return out


def plan_fleet_joint(
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
    max_permutations: int = 120,
    admission: Literal["soft", "hard"] = "soft",
    minutes_per_cost_unit: float = 1.0,
) -> JointPlanResult:
    """Search across agent orderings, pick the best, apply it for real.

    Parameters
    ----------
    graph, requests, scheduler:
        Same as :func:`plan_fleet`.
    hold_start, hold_end, at_time, base_cost_fn, algorithm,
    claim_nodes, claim_edges:
        Forwarded verbatim to each trial's :func:`plan_fleet` call.
    max_permutations:
        When ``n! <= max_permutations`` (default ``120`` = ``5!``),
        every permutation is tried. Otherwise only a fixed set of
        heuristic orderings is sampled (insertion / reverse /
        priority-DESC / deadline-ASC). The cap keeps the planner
        polynomial in n even for big fleets while still beating pure
        greedy on the small fleets where joint optimization is most
        valuable.

    Returns
    -------
    JointPlanResult
        Carries the chosen ordering, the number of trials evaluated,
        whether the full permutation set was enumerated, and the live
        :class:`FleetPlanResult` from the real run.

    Notes
    -----
    Every trial uses :meth:`SharedScheduler.clone`, so the live
    scheduler is unmodified during search. The winning ordering is
    then committed by calling :func:`plan_fleet` on the real
    scheduler once. There is no "partial commit" — search results are
    informational; the live state only changes through the final
    apply step.
    """
    req_list = list(requests)
    if not req_list:
        return JointPlanResult(
            chosen_order=(),
            trials_evaluated=0,
            enumerated=True,
            fleet_result=FleetPlanResult(results=[]),
        )

    n = len(req_list)
    # math.factorial would import a whole module for one branch; cheap
    # loop is fine.
    n_factorial = 1
    for i in range(2, n + 1):
        n_factorial *= i

    if n_factorial <= max_permutations:
        orderings: Iterable[list[FleetRequest]] = (
            list(p) for p in itertools.permutations(req_list)
        )
        enumerated = True
        trials_total = n_factorial
    else:
        orderings = iter(_candidate_orderings(req_list))
        enumerated = False
        trials_total = 0  # counted lazily below

    best: JointPlanTrial | None = None
    trials_seen = 0
    for order in orderings:
        trial_scheduler = scheduler.clone()
        trial_result = plan_fleet(
            graph,
            order,
            trial_scheduler,
            hold_start=hold_start,
            hold_end=hold_end,
            at_time=at_time,
            base_cost_fn=base_cost_fn,
            algorithm=algorithm,
            claim_nodes=claim_nodes,
            claim_edges=claim_edges,
            rollback_on_failure=False,
            admission=admission,
            minutes_per_cost_unit=minutes_per_cost_unit,
        )
        granted, cost = _score_trial(graph, tuple(r.agent_id for r in order), trial_result.results)
        trial = JointPlanTrial(
            order=tuple(r.agent_id for r in order),
            granted_count=granted,
            total_cost=cost,
            results=trial_result.results,
        )
        trials_seen += 1
        if best is None:
            best = trial
            continue
        # More grants wins; tie broken by lower total cost.
        if trial.granted_count > best.granted_count or (
            trial.granted_count == best.granted_count
            and trial.total_cost < best.total_cost
        ):
            best = trial

    if enumerated:
        trials_total = trials_seen

    assert best is not None  # guaranteed: req_list is non-empty
    chosen_order = best.order
    # Apply the winning ordering to the *real* scheduler so the caller
    # sees the live mutations they would have got from plan_fleet.
    by_id = {r.agent_id: r for r in req_list}
    final_requests = [by_id[aid] for aid in chosen_order]
    fleet_result = plan_fleet(
        graph,
        final_requests,
        scheduler,
        hold_start=hold_start,
        hold_end=hold_end,
        at_time=at_time,
        base_cost_fn=base_cost_fn,
        algorithm=algorithm,
        claim_nodes=claim_nodes,
        claim_edges=claim_edges,
        rollback_on_failure=False,
        admission=admission,
        minutes_per_cost_unit=minutes_per_cost_unit,
    )

    return JointPlanResult(
        chosen_order=chosen_order,
        trials_evaluated=trials_total if enumerated else trials_seen,
        enumerated=enumerated,
        fleet_result=fleet_result,
    )


def plan_fleet_with_strategy(
    graph: TopologyGraph,
    requests: Iterable[FleetRequest],
    scheduler: SharedScheduler,
    *,
    hold_start: time | datetime | str,
    hold_end: time | datetime | str,
    strategy: Strategy = "greedy",
    at_time: time | datetime | str | None = None,
    base_cost_fn: CostFn | None = None,
    algorithm: Literal["astar", "dijkstra"] = "astar",
    claim_nodes: bool = True,
    claim_edges: bool = True,
    rollback_on_failure: bool = False,
    max_permutations: int = 120,
    admission: Literal["soft", "hard"] = "soft",
    minutes_per_cost_unit: float = 1.0,
) -> FleetPlanResult:
    """Run :func:`plan_fleet` under a named ordering strategy.

    Strategies:

    * ``"greedy"`` — call :func:`plan_fleet` directly with the input
      order. Same as the sequential greedy baseline.
    * ``"priority"`` — sort by ``priority`` DESC before running.
      Useful when higher-priority agents should grab their resources
      first regardless of submission order.
    * ``"deadline"`` — sort by ``deadline`` ASC (EDF). Requests with
      no deadline sort to the back.
    * ``"joint"`` — call :func:`plan_fleet_joint`, returning the
      *live* fleet result from the winning ordering (the
      :class:`JointPlanResult` envelope is dropped to keep the return
      type uniform). Use :func:`plan_fleet_joint` directly when you
      need the chosen-order / trial-count metadata.

    Returns
    -------
    FleetPlanResult
        The same shape every strategy returns, so callers can switch
        strategies without touching downstream code.
    """
    req_list = list(requests)

    if strategy == "greedy":
        ordered = req_list
    elif strategy == "priority":
        ordered = _reorder_by_priority(req_list)
    elif strategy == "deadline":
        ordered = _reorder_by_deadline(req_list)
    elif strategy == "joint":
        joint = plan_fleet_joint(
            graph,
            req_list,
            scheduler,
            hold_start=hold_start,
            hold_end=hold_end,
            at_time=at_time,
            base_cost_fn=base_cost_fn,
            algorithm=algorithm,
            claim_nodes=claim_nodes,
            claim_edges=claim_edges,
            max_permutations=max_permutations,
            admission=admission,
            minutes_per_cost_unit=minutes_per_cost_unit,
        )
        return joint.fleet_result
    else:  # pragma: no cover - unreachable under Literal typing
        raise ValueError(f"unknown strategy {strategy!r}")

    return plan_fleet(
        graph,
        ordered,
        scheduler,
        hold_start=hold_start,
        hold_end=hold_end,
        at_time=at_time,
        base_cost_fn=base_cost_fn,
        algorithm=algorithm,
        claim_nodes=claim_nodes,
        claim_edges=claim_edges,
        rollback_on_failure=rollback_on_failure,
        admission=admission,
        minutes_per_cost_unit=minutes_per_cost_unit,
    )
