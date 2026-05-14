"""Branch-and-bound joint fleet planner.

:func:`plan_fleet_joint` enumerates every permutation when the fleet
is small (``n! ≤ max_permutations``) and falls back to four heuristic
orderings when it isn't. That's a good baseline but it has two ceilings:

1. The enumeration ceiling — ``5! = 120`` is the default cutoff; beyond
   that, the search degrades to four candidate orderings even though
   many fleets of size 6–10 still have a tractable optimum.
2. The "no early termination" ceiling — even when an ordering is
   obviously worse than the current best (cheaper paths impossible,
   or grants already lost), the joint planner still completes the
   trial.

This module's :func:`plan_fleet_bnb` is the pruned cousin. Conceptually
it is the same DFS over partial orderings that an exhaustive search
would do — but with three branches cut before recursing:

* **Grants upper bound.** If the partial ordering's granted count plus
  the number of remaining requests is already less than the best
  ordering's grants, no completion of this branch can beat the best
  on grants. Prune.
* **Cost lower bound.** If the partial ordering's grants would tie the
  best but its current total path cost is already worse, no completion
  can beat the best on the cost tie-break. Prune.
* **Search budget.** ``max_nodes`` and ``time_budget_ms`` are hard
  caps so the call stays bounded on adversarial inputs; partial best
  is still returned if the budget is exhausted.

The trial state is a :meth:`SharedScheduler.clone`, so the live
scheduler is mutated only once at the end (when the chosen ordering
is applied for real). For every request that fails admission inside
the search, a :class:`ConflictExplanation` is recorded — this is the
*lightweight* analogue of CBS conflict-tree nodes: enough information
to point at which prior agents' holds blocked the new one, without
the high-level / low-level two-layer structure CBS uses for full MAPF.
The explanations compose with the eval suite's ``deadline_miss_count``
to localize where joint admission is failing.
"""

from __future__ import annotations

import time as _time_mod
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Literal

from semantic_toponav.coordination.fleet import (
    FleetPlanResult,
    FleetRequest,
    PlanWithSchedulerResult,
    ReasonCode,
    _path_cost_total,
    plan_fleet,
    plan_with_scheduler,
)
from semantic_toponav.coordination.scheduler import SharedScheduler
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.planner.semantic_costs import CostFn

Objective = Literal["min_cost", "minimax_cost", "max_fairness"]


def _jain_index(values: list[float]) -> float:
    """Jain's fairness index over non-negative values; 1.0 on empty/zero."""
    if not values:
        return 1.0
    total = sum(values)
    if total == 0.0:
        return 1.0
    num = total * total
    denom = len(values) * sum(v * v for v in values)
    if denom == 0.0:
        return 1.0
    return num / denom


@dataclass(frozen=True)
class ConflictExplanation:
    """Lightweight "why was this agent blocked" record.

    Filled when a request's planning succeeds (a path exists) but the
    admission or claim step refuses it inside the search. Mirrors the
    structured ``reason_code`` from :class:`PlanWithSchedulerResult`
    and adds the agents that were already holding resources on the
    blocked agent's path so the caller can read "agent X was blocked
    by holds from agents A, B".

    The "lightweight CBS" framing: where CBS' conflict-tree node
    carries enough state to spawn two split-and-resolve children
    (forcing one agent to avoid a contested resource), here we only
    *describe* the conflict. The branch-and-bound search already
    handles split / explore at the ordering level; this object is
    for surface-level diagnostics, not for the algorithm's own use.
    """

    blocked_agent_id: str
    reason_code: ReasonCode
    blocking_agents: tuple[str, ...]
    blocking_resources: tuple[str, ...]
    detail: str = ""


@dataclass
class BnBStats:
    """Per-call book-keeping for :func:`plan_fleet_bnb`.

    Attributes
    ----------
    nodes_explored:
        How many partial-ordering DFS nodes were expanded (each
        expansion runs one :func:`plan_with_scheduler` call inside the
        clone).
    nodes_pruned_by_grants:
        Subtrees skipped because the grants upper bound made them
        unable to beat the current best.
    nodes_pruned_by_cost:
        Subtrees skipped because the cost lower bound tied the grants
        but already exceeded the best total cost.
    completed:
        ``True`` if the DFS finished organically, ``False`` if it
        ran out of node or time budget mid-search.
    elapsed_ms:
        Wall-clock time spent in the search (not including the final
        live-apply step).
    """

    nodes_explored: int = 0
    nodes_pruned_by_grants: int = 0
    nodes_pruned_by_cost: int = 0
    completed: bool = True
    elapsed_ms: float = 0.0
    objective: Objective = "min_cost"


@dataclass
class BnBPlanResult:
    """Outcome of :func:`plan_fleet_bnb`.

    Attributes
    ----------
    chosen_order:
        The agent_id sequence the search committed to the live
        scheduler. May be a partial ordering only if ``stats.completed``
        is False (very tight budgets); the implementation still
        applies the best ordering it found, padding with the remaining
        requests in submission order.
    stats:
        Search statistics; see :class:`BnBStats`.
    conflict_explanations:
        :class:`ConflictExplanation` entries collected during search.
        One per (partial_ordering, blocked_agent) pair when admission
        denied the request. Deduplicated by blocked agent — only the
        first explanation per agent across all explored prefixes is
        kept, since the goal is "give the caller a starting point",
        not "enumerate every block path".
    fleet_result:
        The live :class:`FleetPlanResult` from running the chosen
        ordering on the real scheduler.
    """

    chosen_order: tuple[str, ...]
    stats: BnBStats = field(default_factory=BnBStats)
    conflict_explanations: list[ConflictExplanation] = field(default_factory=list)
    fleet_result: FleetPlanResult = field(default_factory=FleetPlanResult)
    per_agent_costs: dict[str, float] = field(default_factory=dict)


def _resources_held_by(
    scheduler: SharedScheduler, resource_ids: list[str]
) -> dict[str, list[str]]:
    """For each resource in ``resource_ids``, return the agents holding it.

    Returns a dict ``{resource_id: [agent_id, ...]}``. Only resources
    with at least one current holder appear in the result. Useful when
    building :class:`ConflictExplanation` records — the search knows
    which resources the blocked agent's path traversed; the scheduler
    knows who's currently holding them.
    """
    out: dict[str, list[str]] = {}
    holders_by_resource: dict[str, list[str]] = {}
    for r in scheduler.reservations():
        holders_by_resource.setdefault(r.resource_id, []).append(r.agent_id)
    for rid in resource_ids:
        if rid in holders_by_resource:
            out[rid] = holders_by_resource[rid]
    return out


def plan_fleet_bnb(
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
    admission: Literal["soft", "hard"] = "soft",
    minutes_per_cost_unit: float = 1.0,
    max_nodes: int = 10_000,
    time_budget_ms: float | None = None,
    objective: Objective = "min_cost",
) -> BnBPlanResult:
    """Branch-and-bound search over agent orderings.

    Parameters
    ----------
    graph, requests, scheduler:
        Same as :func:`plan_fleet`.
    hold_start, hold_end, at_time, base_cost_fn, algorithm,
    claim_nodes, claim_edges, admission, minutes_per_cost_unit:
        Forwarded verbatim to each trial's
        :func:`plan_with_scheduler` call.
    max_nodes:
        Upper bound on the number of DFS nodes the search will
        expand. Default ``10_000`` covers n ≤ 8 without budget loss
        on most realistic graphs (full ``8! = 40_320`` is well above
        this, but pruning typically cuts off > 90%).
    time_budget_ms:
        Optional wall-clock cap. When set, the search returns the
        best ordering found so far once the budget elapses. Combine
        with ``max_nodes`` for hard real-time use.
    objective:
        How leaves are scored after the grants tie. Choices:

        * ``"min_cost"`` (default) — minimize the sum of granted-agent
          path costs. Matches the joint planner's tie-break.
        * ``"minimax_cost"`` — minimize the maximum per-agent path
          cost among the granted set. Picks egalitarian orderings:
          one agent doing all the long routes is penalized even when
          total cost is the same.
        * ``"max_fairness"`` — maximize Jain's fairness index over
          per-granted-agent path costs. Total cost is still the final
          tie-break.

    Returns
    -------
    BnBPlanResult
        ``chosen_order`` is the agent sequence the search picked,
        ``fleet_result`` is the live run of that sequence,
        ``per_agent_costs`` is the granted-agent path-cost map the
        winner produced (empty for agents that were denied), and
        ``stats`` plus ``conflict_explanations`` give the operator a
        view into *why* the search picked what it picked.

    Notes
    -----
    Score function with ``objective="min_cost"`` is
    ``(granted_count DESC, total_cost ASC)``. With ``"minimax_cost"``
    it is ``(granted_count DESC, max_cost ASC, total_cost ASC)``;
    with ``"max_fairness"`` it is
    ``(granted_count DESC, jain_fairness DESC, total_cost ASC)``.

    The cost lower-bound prune is active for ``"min_cost"`` and
    ``"minimax_cost"`` (path costs are non-negative so partial sums
    and partial max only grow as more agents are added). For
    ``"max_fairness"`` the bound is dropped: Jain's index can swing
    in either direction as the granted set grows, so any partial
    fairness estimate would mis-prune. The grants upper bound is
    always active.
    """
    req_list = list(requests)
    if not req_list:
        return BnBPlanResult(
            chosen_order=(),
            stats=BnBStats(completed=True),
            fleet_result=FleetPlanResult(results=[]),
        )

    by_id: dict[str, FleetRequest] = {r.agent_id: r for r in req_list}
    initial_snapshot = scheduler.clone()
    t0 = _time_mod.perf_counter()

    stats = BnBStats(objective=objective)
    explanations_by_agent: dict[str, ConflictExplanation] = {}

    # Score tuples are objective-specific; see _score_leaf below. The
    # seed is shaped per objective so the first real leaf strictly
    # beats it under tuple comparison.
    NEG_INF = -float("inf")
    if objective == "min_cost":
        best_score: tuple = (-1, NEG_INF)
    elif objective in ("minimax_cost", "max_fairness"):
        best_score = (-1, NEG_INF, NEG_INF)
    else:  # pragma: no cover - guarded by Literal type
        raise ValueError(f"unknown objective {objective!r}")
    best_order: tuple[str, ...] = tuple(r.agent_id for r in req_list)
    best_per_agent_costs: dict[str, float] = {}

    def _score_leaf(
        granted: int, per_agent_costs: dict[str, float]
    ) -> tuple:
        costs = list(per_agent_costs.values())
        total = sum(costs)
        if objective == "min_cost":
            return (granted, -total)
        if objective == "minimax_cost":
            max_c = max(costs) if costs else 0.0
            return (granted, -max_c, -total)
        # max_fairness
        return (granted, _jain_index(costs), -total)

    def _budget_exhausted() -> bool:
        if stats.nodes_explored >= max_nodes:
            stats.completed = False
            return True
        if time_budget_ms is not None:
            elapsed = (_time_mod.perf_counter() - t0) * 1000.0
            if elapsed >= time_budget_ms:
                stats.completed = False
                return True
        return False

    def _attempt(
        request: FleetRequest, trial_scheduler: SharedScheduler
    ) -> tuple[PlanWithSchedulerResult, float]:
        """Plan one agent on the trial clone. Returns (result, path_cost)."""
        result = plan_with_scheduler(
            graph,
            request.agent_id,
            request.start,
            request.goal,
            trial_scheduler,
            hold_start=hold_start,
            hold_end=hold_end,
            at_time=at_time,
            base_cost_fn=base_cost_fn,
            algorithm=algorithm,
            priority=request.priority,
            claim_nodes=claim_nodes,
            claim_edges=claim_edges,
            deadline=request.deadline,
            admission=admission,
            minutes_per_cost_unit=minutes_per_cost_unit,
        )
        cost = _path_cost_total(graph, result.path) if result.granted else 0.0
        return result, cost

    def _record_explanation(
        request: FleetRequest,
        result: PlanWithSchedulerResult,
        snapshot_before: SharedScheduler,
    ) -> None:
        """Capture a ConflictExplanation for a blocked agent.

        Only stored on first sight per agent_id — subsequent prefixes
        that block the same agent don't enrich the diagnostic, they
        just dilute it.
        """
        if request.agent_id in explanations_by_agent:
            return
        # The result's path may be empty (no_path) or non-empty
        # (deadline_miss / reservation_conflict). Either way, look up
        # which resources on that path the snapshot was holding.
        held_lookup = _resources_held_by(snapshot_before, list(result.path))
        blocking_agents: set[str] = set()
        blocking_resources: list[str] = []
        for rid, holders in held_lookup.items():
            blocking_resources.append(rid)
            for h in holders:
                if h != request.agent_id:
                    blocking_agents.add(h)
        explanations_by_agent[request.agent_id] = ConflictExplanation(
            blocked_agent_id=request.agent_id,
            reason_code=result.reason_code,
            blocking_agents=tuple(sorted(blocking_agents)),
            blocking_resources=tuple(blocking_resources),
            detail=result.failure_reason or "",
        )

    def _explore(
        prefix: list[str],
        prefix_snapshot: SharedScheduler,
        remaining: list[FleetRequest],
        granted: int,
        per_agent_costs: dict[str, float],
    ) -> None:
        """DFS over partial orderings."""
        nonlocal best_score, best_order, best_per_agent_costs

        if _budget_exhausted():
            return

        # Grants upper bound: even if every remaining request is
        # admitted, can we still beat the best?
        upper_grants = granted + len(remaining)
        if upper_grants < best_score[0]:
            stats.nodes_pruned_by_grants += 1
            return
        # Cost tie-break: when grants would only tie, the partial cost
        # signal must still allow beating the best. We branch by
        # objective so the bound stays valid:
        #
        #   min_cost     — partial sum >= best total → no completion
        #                  can have strictly lower total. Prune.
        #   minimax_cost — partial max >= best max → max only grows.
        #                  Prune.
        #   max_fairness — fairness is non-monotone; skip.
        if upper_grants == best_score[0]:
            partial_total = sum(per_agent_costs.values())
            if objective == "min_cost":
                if partial_total >= -best_score[1]:
                    stats.nodes_pruned_by_cost += 1
                    return
            elif objective == "minimax_cost":
                partial_max = (
                    max(per_agent_costs.values()) if per_agent_costs else 0.0
                )
                if partial_max >= -best_score[1]:
                    stats.nodes_pruned_by_cost += 1
                    return

        if not remaining:
            leaf_score = _score_leaf(granted, per_agent_costs)
            if leaf_score > best_score:
                best_score = leaf_score
                best_order = tuple(prefix)
                best_per_agent_costs = dict(per_agent_costs)
            return

        for i, req in enumerate(remaining):
            stats.nodes_explored += 1
            if _budget_exhausted():
                return
            # Snapshot before the attempt so the explanation builder
            # can see who held the conflicting resources.
            snapshot_before = prefix_snapshot.clone()
            trial = prefix_snapshot.clone()
            result, path_cost = _attempt(req, trial)
            if not result.granted:
                _record_explanation(req, result, snapshot_before)
            new_remaining = remaining[:i] + remaining[i + 1:]
            next_costs = dict(per_agent_costs)
            if result.granted:
                next_costs[req.agent_id] = path_cost
            _explore(
                prefix + [req.agent_id],
                trial,
                new_remaining,
                granted + (1 if result.granted else 0),
                next_costs,
            )

    _explore(
        prefix=[],
        prefix_snapshot=initial_snapshot,
        remaining=req_list,
        granted=0,
        per_agent_costs={},
    )

    stats.elapsed_ms = (_time_mod.perf_counter() - t0) * 1000.0

    # If the budget was exhausted before any leaf was scored, fall
    # back to submission order so the live scheduler still gets a
    # real result.
    if best_score[0] < 0:
        best_order = tuple(r.agent_id for r in req_list)

    # Pad chosen_order with any requests the budget never reached so
    # the final apply step is well-defined.
    seen = set(best_order)
    padded = list(best_order) + [r.agent_id for r in req_list if r.agent_id not in seen]
    chosen_order = tuple(padded)

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

    return BnBPlanResult(
        chosen_order=chosen_order,
        stats=stats,
        conflict_explanations=list(explanations_by_agent.values()),
        fleet_result=fleet_result,
        per_agent_costs=best_per_agent_costs,
    )
