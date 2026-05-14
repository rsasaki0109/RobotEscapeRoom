"""Exhaustive grant-set baseline: the theoretical upper bound on grants.

The greedy / joint / BnB planners all answer the same question in
different ways: *given a sequential admission policy, what is the
best agent ordering*. Their answers are bounded by an even simpler
question — *if every agent planned independently, what is the
largest grantable subset of those plans*?

That upper bound is a Maximum Independent Set on the conflict graph:
each agent's path is a vertex; two vertices share an edge when their
paths share at least one resource. The largest set of mutually
non-conflicting agents is the maximum independent set. Computing it
exactly is exponential in the worst case — but a fleet of 10 agents
is only 1024 subsets, well under a millisecond.

This module ships :func:`plan_fleet_exhaustive`, which:

1. Plans each agent independently against the *initial* scheduler
   snapshot (no sequential effect — every agent sees the same world).
2. Builds the conflict graph from the resulting paths.
3. Enumerates subsets in decreasing size, stopping at the first one
   that has no internal conflicts. Ties on size break on total path
   cost (lower wins), then on submission order.
4. Applies the chosen subset to the live scheduler.

The contract is *baseline*, not *production*: a real scheduler that
fixes path choices once can grant *strictly fewer* agents than this
function reports, but never more. Use the output to verify BnB is
actually finding good orderings — when BnB matches the exhaustive
grant count, no scheduling tweak inside the existing framework can
do better.

The default ``n_limit`` of 16 keeps the 2^n enumeration tractable
(65k subsets); callers that need to push past that are likely
better off with a proper MIS solver (ortools, pulp). The optional
``time_budget_ms`` cap returns the best subset found so far when
the wall-clock budget is exhausted.
"""

from __future__ import annotations

import time as _time_mod
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, time
from itertools import combinations
from typing import Literal

from semantic_toponav.coordination.fleet import (
    FleetPlanResult,
    FleetRequest,
    PlanWithSchedulerResult,
    _path_cost_total,
    plan_fleet,
    plan_with_scheduler,
)
from semantic_toponav.coordination.scheduler import SharedScheduler
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.planner.semantic_costs import CostFn


@dataclass
class ExhaustiveStats:
    """Per-call book-keeping for :func:`plan_fleet_exhaustive`.

    Attributes
    ----------
    n_agents:
        Size of the input fleet (set after the function runs;
        independent of how many agents were ultimately granted).
    n_independent_plans_granted:
        How many of the per-agent independent plans were themselves
        plannable. Anything below ``n_agents`` is an agent whose
        own path didn't exist even on an empty scheduler — those
        get dropped from the subset enumeration immediately.
    subsets_evaluated:
        Number of subsets actually visited in the enumeration loop
        (after the early-exit cut-off).
    completed:
        ``True`` when the enumeration finished organically, ``False``
        when it ran out of time budget.
    elapsed_ms:
        Wall-clock time spent inside the enumeration loop (not
        counting the per-agent independent plan step, which precedes
        it, or the final live-apply step).
    """

    n_agents: int = 0
    n_independent_plans_granted: int = 0
    subsets_evaluated: int = 0
    completed: bool = True
    elapsed_ms: float = 0.0


@dataclass
class ExhaustivePlanResult:
    """Outcome of :func:`plan_fleet_exhaustive`.

    Attributes
    ----------
    granted_agents:
        Agent ids in the chosen subset, in the order
        :func:`plan_fleet` later applied them. With the default cost
        tie-break this matches submission order within the subset.
    independent_paths:
        Mapping ``agent_id -> path`` from the per-agent independent
        plan step. Agents whose plan was rejected appear with an
        empty path; the conflict graph excludes them automatically.
    stats:
        Search statistics; see :class:`ExhaustiveStats`.
    fleet_result:
        The live :class:`FleetPlanResult` from applying the chosen
        subset's requests against the real scheduler. May grant
        *fewer* agents than ``granted_agents`` if the live scheduler
        had pre-existing holds the independent plan step didn't see;
        the typical use is to construct the call against an empty
        scheduler, in which case the live result matches the subset.
    """

    granted_agents: tuple[str, ...]
    independent_paths: dict[str, list[str]] = field(default_factory=dict)
    stats: ExhaustiveStats = field(default_factory=ExhaustiveStats)
    fleet_result: FleetPlanResult = field(default_factory=FleetPlanResult)


def _resources_on_path(
    path: list[str],
    *,
    claim_nodes: bool,
    claim_edges: bool,
) -> set[str]:
    """Resource identifiers (nodes + edge strings) the path would claim.

    Mirrors :meth:`SharedScheduler.claim_many`'s view of what each
    granted plan occupies. Edge identifiers use the same
    ``"a->b" / "b->a"`` shape ``plan_with_scheduler`` produces so
    overlap detection is exact.
    """
    out: set[str] = set()
    if claim_nodes:
        out.update(path)
    if claim_edges:
        for a, b in zip(path[:-1], path[1:], strict=True):
            # The scheduler treats edges as undirected for conflict
            # purposes (an agent traversing a->b excludes one going
            # b->a), so we canonicalize the pair.
            if a <= b:
                out.add(f"edge:{a}|{b}")
            else:
                out.add(f"edge:{b}|{a}")
    return out


def _build_conflict_graph(
    paths_by_agent: dict[str, list[str]],
    *,
    claim_nodes: bool,
    claim_edges: bool,
) -> dict[str, set[str]]:
    """Adjacency map: ``agent_id -> set(conflicting agent_ids)``."""
    resources_by_agent: dict[str, set[str]] = {
        aid: _resources_on_path(
            path, claim_nodes=claim_nodes, claim_edges=claim_edges
        )
        for aid, path in paths_by_agent.items()
    }
    adj: dict[str, set[str]] = {aid: set() for aid in resources_by_agent}
    agent_ids = list(resources_by_agent.keys())
    for i, a in enumerate(agent_ids):
        for b in agent_ids[i + 1:]:
            if resources_by_agent[a] & resources_by_agent[b]:
                adj[a].add(b)
                adj[b].add(a)
    return adj


def _subset_is_independent(
    subset: tuple[str, ...], adj: dict[str, set[str]]
) -> bool:
    """``True`` iff no two agents in the subset are adjacent (conflict)."""
    seen: set[str] = set()
    for agent in subset:
        if seen & adj[agent]:
            return False
        seen.add(agent)
    return True


def plan_fleet_exhaustive(
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
    n_limit: int = 16,
    time_budget_ms: float | None = None,
) -> ExhaustivePlanResult:
    """Compute the maximum grantable subset of agents and apply it.

    Plans each agent independently against the initial scheduler
    snapshot, builds the path-overlap conflict graph, and enumerates
    subsets in decreasing size order until the first conflict-free
    one is found. The result is the *theoretical upper bound* on
    grant rate for the fixed-path model.

    Parameters
    ----------
    graph, requests, scheduler, hold_start, hold_end, at_time,
    base_cost_fn, algorithm, claim_nodes, claim_edges, admission,
    minutes_per_cost_unit:
        Same as :func:`plan_fleet`. The independent plan step
        forwards each of these verbatim.
    n_limit:
        Upper bound on fleet size for which the 2^n enumeration is
        attempted. Default ``16`` (≈65k subsets, sub-millisecond on
        small graphs). For larger fleets, raise this only if you've
        measured the time budget cost; otherwise switch to a real
        MIS solver.
    time_budget_ms:
        Optional wall-clock cap on the enumeration step. When the
        budget is exhausted, returns the best subset found so far
        (could be empty if nothing was tried).

    Returns
    -------
    ExhaustivePlanResult
        ``granted_agents`` is the chosen subset's agent_ids in
        submission order; ``fleet_result`` is the live run of those
        requests; ``stats`` records what was explored and how long
        it took.

    Raises
    ------
    ValueError
        If the fleet size exceeds ``n_limit``. Make the limit
        explicit so callers can't accidentally try a 2^25 sweep.
    """
    req_list = list(requests)
    if not req_list:
        return ExhaustivePlanResult(
            granted_agents=(),
            stats=ExhaustiveStats(completed=True),
            fleet_result=FleetPlanResult(results=[]),
        )

    n = len(req_list)
    if n > n_limit:
        raise ValueError(
            f"plan_fleet_exhaustive: fleet size {n} exceeds n_limit={n_limit}. "
            f"2^n enumeration would be > {2**n_limit} subsets; use a real "
            f"MIS solver or raise n_limit explicitly."
        )

    # Step 1: plan each agent independently on the *initial* snapshot.
    # Clone once and re-use; we do not mutate the input scheduler in
    # this step (claims are computed but never applied to the live
    # state — they are inspected via the result's path).
    snapshot = scheduler.clone()
    independent_results: dict[str, PlanWithSchedulerResult] = {}
    independent_paths: dict[str, list[str]] = {}
    for req in req_list:
        # Important: each agent plans against the *fresh* clone of
        # the initial state so no agent's plan biases another's. We
        # do not claim anything here — :func:`plan_with_scheduler`
        # mutates its scheduler argument as a side effect, so we
        # re-clone per agent to keep the model "independent paths".
        trial = snapshot.clone()
        result = plan_with_scheduler(
            graph,
            req.agent_id,
            req.start,
            req.goal,
            trial,
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
        independent_results[req.agent_id] = result
        independent_paths[req.agent_id] = list(result.path) if result.granted else []

    stats = ExhaustiveStats(n_agents=n)
    plannable = [aid for aid, r in independent_results.items() if r.granted]
    stats.n_independent_plans_granted = len(plannable)

    # Step 2: conflict graph over the plannable agents only.
    plannable_paths = {aid: independent_paths[aid] for aid in plannable}
    adj = _build_conflict_graph(
        plannable_paths, claim_nodes=claim_nodes, claim_edges=claim_edges
    )

    # Step 3: enumerate subsets in decreasing size, find best.
    t0 = _time_mod.perf_counter()
    best_subset: tuple[str, ...] = ()
    best_cost: float = float("inf")

    def _budget_exhausted() -> bool:
        if time_budget_ms is None:
            return False
        elapsed = (_time_mod.perf_counter() - t0) * 1000.0
        if elapsed >= time_budget_ms:
            stats.completed = False
            return True
        return False

    # Generate subsets by decreasing size so we can short-circuit once
    # we know nothing larger is achievable.
    sizes = range(len(plannable), -1, -1)
    found_best_size = False
    for size in sizes:
        if size <= len(best_subset):
            # Nothing in this or smaller sizes can beat the best
            # (size monotone). Stop.
            break
        if found_best_size:
            break
        for subset in combinations(plannable, size):
            stats.subsets_evaluated += 1
            if _budget_exhausted():
                break
            if not _subset_is_independent(subset, adj):
                continue
            # Compute total cost over the subset's independent paths.
            subset_cost = sum(
                _path_cost_total(graph, independent_paths[aid])
                for aid in subset
            )
            if (
                len(subset) > len(best_subset)
                or (len(subset) == len(best_subset) and subset_cost < best_cost)
            ):
                best_subset = subset
                best_cost = subset_cost
                # Within the same size bucket, smaller cost wins.
                # We continue enumerating that bucket to find the
                # cheapest, then break out of the outer loop because
                # nothing smaller can grant more.
        if best_subset and len(best_subset) == size:
            found_best_size = True

    stats.elapsed_ms = (_time_mod.perf_counter() - t0) * 1000.0

    # Step 4: apply the chosen subset to the live scheduler in
    # submission order so the resulting FleetPlanResult is
    # deterministic and matches what plan_fleet would produce given
    # this filtered request list.
    in_subset = set(best_subset)
    ordered = [r for r in req_list if r.agent_id in in_subset]
    fleet_result = plan_fleet(
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
        rollback_on_failure=False,
        admission=admission,
        minutes_per_cost_unit=minutes_per_cost_unit,
    )

    return ExhaustivePlanResult(
        granted_agents=tuple(r.agent_id for r in ordered),
        independent_paths=independent_paths,
        stats=stats,
        fleet_result=fleet_result,
    )


