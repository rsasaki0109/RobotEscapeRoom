"""Insertion-based repair planner for fleet orderings.

:func:`plan_fleet_bnb` searches *all* orderings of a fleet from a
clean slate. That is the right tool when the fleet is being planned
fresh, but it is wasteful when most of the ordering is already
committed and only one or two new requests need to be merged in.

:func:`plan_fleet_insert` is the repair primitive for that case. It
takes:

* ``committed`` — the current fleet ordering as a sequence of
  :class:`FleetRequest` entries.
* ``new_requests`` — one or more new entries to merge into that
  ordering.

For each new request it tries every insertion position in the
current ordering, evaluates the merged result on a clone of the live
scheduler, and keeps the locally-best position under the same
objective tie-break BnB uses. Repeating that across the new requests
is greedy *between* insertions and exact *within* each insertion —
O(k · (n+k)) plan-and-score steps versus O((n+k)!) for a full
re-search.

The final ordering is applied to the live scheduler so the result is
a drop-in replacement for a :func:`plan_fleet_bnb` result and can be
consumed by the same callers.

When to reach for it:

* Incremental admission: a new request arrives after the original
  fleet was committed; you want to slot it in without re-permuting
  the existing agents.
* Tight time budget: a full BnB call would exceed the operator's
  wall-clock window but a small insertion search will not.

When NOT to reach for it:

* The committed ordering is itself suboptimal — insertion can only
  improve at the seams. Re-run :func:`plan_fleet_bnb` from scratch
  if you need to re-examine the existing ordering too.
* Large ``new_requests`` (e.g. > ~3 of them): the greedy chain may
  miss orderings that a full BnB would find. Use BnB instead.
"""

from __future__ import annotations

import time as _time_mod
from collections.abc import Iterable, Sequence
from datetime import datetime, time
from typing import Literal

from semantic_toponav.coordination.branch_and_bound import (
    BnBPlanResult,
    BnBStats,
    Objective,
    _jain_index,
)
from semantic_toponav.coordination.fleet import (
    FleetRequest,
    _path_cost_total,
    plan_fleet,
)
from semantic_toponav.coordination.scheduler import SharedScheduler
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.planner.semantic_costs import CostFn


def _evaluate_ordering(
    graph: TopologyGraph,
    ordering: list[FleetRequest],
    scheduler: SharedScheduler,
    *,
    hold_start: time | datetime | str,
    hold_end: time | datetime | str,
    at_time: time | datetime | str | None,
    base_cost_fn: CostFn | None,
    algorithm: Literal["astar", "dijkstra"],
    claim_nodes: bool,
    claim_edges: bool,
    admission: Literal["soft", "hard"],
    minutes_per_cost_unit: float,
) -> tuple[int, dict[str, float]]:
    """Plan ``ordering`` on a *clone* of ``scheduler`` and report (granted, per_agent_costs)."""
    trial = scheduler.clone()
    result = plan_fleet(
        graph,
        ordering,
        trial,
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
    granted = 0
    per_agent_costs: dict[str, float] = {}
    for one in result.results:
        if one.granted:
            granted += 1
            per_agent_costs[one.agent_id] = _path_cost_total(graph, one.path)
    return granted, per_agent_costs


def _score(
    granted: int,
    per_agent_costs: dict[str, float],
    objective: Objective,
) -> tuple:
    """Same comparison key shape :func:`plan_fleet_bnb` uses."""
    costs = list(per_agent_costs.values())
    total = sum(costs)
    if objective == "min_cost":
        return (granted, -total)
    if objective == "minimax_cost":
        max_c = max(costs) if costs else 0.0
        return (granted, -max_c, -total)
    # max_fairness
    return (granted, _jain_index(costs), -total)


def plan_fleet_insert(
    graph: TopologyGraph,
    committed: Sequence[FleetRequest],
    new_requests: Iterable[FleetRequest],
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
    objective: Objective = "min_cost",
) -> BnBPlanResult:
    """Insert ``new_requests`` into ``committed`` at the locally-best positions.

    For each new request, every insertion position in the running
    ordering is evaluated against the same objective tie-break BnB
    uses (grants ↓, then objective-specific cost tie-break). The
    locally-best position wins; the new request is committed there
    and the next new request is tried against the resulting ordering.

    Parameters
    ----------
    graph, scheduler:
        Same as :func:`plan_fleet_bnb`. The live ``scheduler`` is
        snapshotted via ``clone`` at the start; the chosen merged
        ordering is applied to the live scheduler at the end. Any
        pre-existing claims are honored.
    committed:
        The current fleet ordering. Must be the ordering whose claims
        (if any) live on ``scheduler`` — the planner re-runs it from
        scratch on a fresh clone so the committed entries must be
        re-claimable. Passing an empty ``committed`` is equivalent to
        sequentially scoring each insertion against an empty fleet.
    new_requests:
        One or more :class:`FleetRequest` entries to merge in. Each
        is inserted greedily — the chain is exact *within* each
        insertion (every position is tried) but greedy *between*
        insertions (an earlier insertion is not revisited after a
        later one lands). For more than ~3 new requests, prefer a
        full :func:`plan_fleet_bnb` re-search.
    hold_start, hold_end, at_time, base_cost_fn, algorithm,
    claim_nodes, claim_edges, admission, minutes_per_cost_unit,
    objective:
        Forwarded to the underlying :func:`plan_fleet` evaluation.

    Returns
    -------
    BnBPlanResult
        Drop-in compatible with :func:`plan_fleet_bnb`'s result.
        ``chosen_order`` is the merged ordering, ``fleet_result`` is
        the live run of that ordering on ``scheduler``,
        ``per_agent_costs`` is the granted-agent path-cost map, and
        ``stats.nodes_explored`` is the number of trial orderings
        scored. ``conflict_explanations`` is empty — insertion-based
        repair does not run the explanatory BnB inner loop.

    Notes
    -----
    Side effect: at exit, ``scheduler`` reflects the claims of the
    merged ordering. Like :func:`plan_fleet_bnb`, the final apply uses
    ``rollback_on_failure=False`` so denied agents simply leave the
    scheduler at whatever state the granted prefix produced.
    """
    committed_list = list(committed)
    new_list = list(new_requests)

    stats = BnBStats(objective=objective, completed=True)
    t0 = _time_mod.perf_counter()

    # Validate: no duplicate agent_ids between committed and new (would
    # corrupt the merged ordering).
    seen: dict[str, str] = {r.agent_id: "committed" for r in committed_list}
    for r in new_list:
        if r.agent_id in seen:
            raise ValueError(
                f"agent_id {r.agent_id!r} appears in both committed and "
                f"new_requests — duplicate ids cannot be merged"
            )
        seen[r.agent_id] = "new"

    current: list[FleetRequest] = list(committed_list)

    NEG_INF = -float("inf")
    for req in new_list:
        best_position: int = len(current)
        if objective == "min_cost":
            best_score: tuple = (-1, NEG_INF)
        else:
            best_score = (-1, NEG_INF, NEG_INF)
        best_costs: dict[str, float] = {}
        # Try every insertion position 0..len(current).
        for pos in range(len(current) + 1):
            stats.nodes_explored += 1
            trial_ordering = current[:pos] + [req] + current[pos:]
            granted, per_agent_costs = _evaluate_ordering(
                graph,
                trial_ordering,
                scheduler,
                hold_start=hold_start,
                hold_end=hold_end,
                at_time=at_time,
                base_cost_fn=base_cost_fn,
                algorithm=algorithm,
                claim_nodes=claim_nodes,
                claim_edges=claim_edges,
                admission=admission,
                minutes_per_cost_unit=minutes_per_cost_unit,
            )
            score = _score(granted, per_agent_costs, objective)
            if score > best_score:
                best_score = score
                best_position = pos
                best_costs = per_agent_costs
        current = current[:best_position] + [req] + current[best_position:]
        # best_costs is the snapshot for the merged-so-far ordering; we
        # keep the latest after the final insertion as the result's
        # per_agent_costs.
        final_costs = best_costs

    if not new_list:
        # No work — score the committed ordering once so we can return a
        # meaningful BnBPlanResult.
        _, final_costs = _evaluate_ordering(
            graph,
            current,
            scheduler,
            hold_start=hold_start,
            hold_end=hold_end,
            at_time=at_time,
            base_cost_fn=base_cost_fn,
            algorithm=algorithm,
            claim_nodes=claim_nodes,
            claim_edges=claim_edges,
            admission=admission,
            minutes_per_cost_unit=minutes_per_cost_unit,
        )

    stats.elapsed_ms = (_time_mod.perf_counter() - t0) * 1000.0
    chosen_order = tuple(r.agent_id for r in current)

    fleet_result = plan_fleet(
        graph,
        current,
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
        conflict_explanations=[],
        fleet_result=fleet_result,
        per_agent_costs=final_costs,
    )


__all__ = ["plan_fleet_insert"]
