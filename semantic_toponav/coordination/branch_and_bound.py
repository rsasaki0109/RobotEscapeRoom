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

    Returns
    -------
    BnBPlanResult
        ``chosen_order`` is the agent sequence the search picked,
        ``fleet_result`` is the live run of that sequence, and
        ``stats`` plus ``conflict_explanations`` give the operator a
        view into *why* the search picked what it picked.

    Notes
    -----
    Score function: ``(granted_count DESC, total_cost ASC)``. The
    search finds the lexicographic optimum under this score subject
    to its budget. With no budget pressure and the default ``"soft"``
    admission, the chosen ordering matches what
    :func:`plan_fleet_joint` would commit when ``n! ≤ max_permutations``.
    Under ``"hard"`` admission the score also implicitly penalizes
    deadline misses (they drop ``granted_count``), so the chosen
    ordering minimizes those first and total cost second.
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

    stats = BnBStats()
    explanations_by_agent: dict[str, ConflictExplanation] = {}

    # best_score is (granted, -cost). Higher is better. We seed with
    # (-1, 0) so the first complete leaf always beats it.
    best_score: tuple[int, float] = (-1, 0.0)
    best_order: tuple[str, ...] = tuple(r.agent_id for r in req_list)

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
        cost_so_far: float,
    ) -> None:
        """DFS over partial orderings."""
        nonlocal best_score, best_order

        if _budget_exhausted():
            return

        # Grants upper bound: even if every remaining request is
        # admitted, can we still beat the best?
        upper_grants = granted + len(remaining)
        if upper_grants < best_score[0]:
            stats.nodes_pruned_by_grants += 1
            return
        # Cost tie-break: if grants would only tie, the current cost
        # must already be strictly less than the best.
        if upper_grants == best_score[0] and cost_so_far >= -best_score[1]:
            stats.nodes_pruned_by_cost += 1
            return

        if not remaining:
            # Leaf: compare against best. Score is (granted, -cost).
            leaf_score = (granted, -cost_so_far)
            if leaf_score > best_score:
                best_score = leaf_score
                best_order = tuple(prefix)
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
            _explore(
                prefix + [req.agent_id],
                trial,
                new_remaining,
                granted + (1 if result.granted else 0),
                cost_so_far + path_cost,
            )

    _explore(
        prefix=[],
        prefix_snapshot=initial_snapshot,
        remaining=req_list,
        granted=0,
        cost_so_far=0.0,
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
    )
