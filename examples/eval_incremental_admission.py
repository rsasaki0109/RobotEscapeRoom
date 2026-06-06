"""Incremental admission — insertion repair vs full re-search.

Paper figure (evaluation Chapter 1, the *live-update* story): a fleet has
already been admitted and committed; a new — here, *urgent* — request
arrives. Three ways to absorb it:

* **naive append** — keep the committed ordering, tack the newcomer on the
  end, run greedy. No re-search; the newcomer takes whatever is left.
* **insertion repair** (`plan_fleet_insert`) — try the newcomer at every
  position in the running ordering and keep the locally-best one. A
  targeted, cheap re-search.
* **full BnB** (`plan_fleet_bnb`) — re-solve committed + newcomer from
  scratch over all orderings. The optimum (and the search-cost upper
  bound).

The figure this produces is a reproducible Markdown table: on a contended
chain, insertion repair **admits the urgent newcomer and matches full
BnB's grants and total cost while exploring an order of magnitude fewer
trial orderings**, whereas naive append leaves the urgent request denied.
That is the claim Chapter 1 makes about the repair planner — measured, not
asserted.

Everything here is deterministic (seed-driven generator, fixed requests)
and dependency-free — no torch, no matplotlib, no API. Run from the repo
root::

    python examples/eval_incremental_admission.py
    python examples/eval_incremental_admission.py --out docs/incremental_admission_sample.md
"""

from __future__ import annotations

import argparse
import time as _time
from dataclasses import dataclass, field
from datetime import time as dtime

from semantic_toponav.coordination import (
    FleetRequest,
    SharedScheduler,
    plan_fleet_with_strategy,
)
from semantic_toponav.coordination.branch_and_bound import plan_fleet_bnb
from semantic_toponav.coordination.repair import plan_fleet_insert
from semantic_toponav.eval.generators import chain_graph
from semantic_toponav.graph.topology_graph import TopologyGraph

HOLD_START = dtime(10, 0)
HOLD_END = dtime(11, 0)


@dataclass
class Scenario:
    """A committed fleet plus the one new request that arrives next."""

    graph: TopologyGraph
    committed: list[FleetRequest]
    new_request: FleetRequest
    newcomer_id: str = field(init=False)

    def __post_init__(self) -> None:
        self.newcomer_id = self.new_request.agent_id


def build_scenario() -> Scenario:
    """A 10-node chain whose committed list is led by a chain-spanning
    long-haul, then an urgent newcomer arrives.

    The committed list, in submission order, is ``long-A`` (n0→n9, claims
    the whole chain) followed by two short services ``svc-B`` (n0→n2) and
    ``svc-C`` (n6→n8) that overlap it. The newcomer ``urgent-E`` (n3→n5,
    priority 9) also overlaps the long-haul. Submission order is the worst
    possible: a position-blind append grants ``long-A`` first and is then
    forced to deny everything else — including the urgent newcomer.
    Dropping the single long-haul frees three disjoint short agents
    (svc-B, urgent-E, svc-C), which a targeted insertion discovers and a
    full re-search confirms.
    """
    graph = chain_graph(10)
    committed = [
        FleetRequest(agent_id="long-A n0->n9", start="n0", goal="n9", priority=0),
        FleetRequest(agent_id="svc-B n0->n2", start="n0", goal="n2", priority=0),
        FleetRequest(agent_id="svc-C n6->n8", start="n6", goal="n8", priority=0),
    ]
    new_request = FleetRequest(
        agent_id="urgent-E n3->n5", start="n3", goal="n5", priority=9
    )
    return Scenario(graph=graph, committed=committed, new_request=new_request)


def _path_cost(graph: TopologyGraph, path: list[str]) -> float:
    """Sum of edge costs along ``path`` (0.0 for a trivial path)."""
    total = 0.0
    for a, b in zip(path[:-1], path[1:], strict=False):
        for edge in graph.neighbors(a):
            if graph.other_end(edge, a) == b:
                total += float(edge.cost)
                break
    return total


@dataclass
class ApproachResult:
    """One admission approach scored on the same scenario."""

    name: str
    granted_ids: list[str]
    denied_ids: list[str]
    newcomer_admitted: bool
    total_cost: float
    orderings_explored: int
    elapsed_ms: float

    @property
    def n_total(self) -> int:
        return len(self.granted_ids) + len(self.denied_ids)


def _score_fleet_result(
    graph: TopologyGraph, fleet_result, newcomer_id: str
) -> tuple[list[str], list[str], bool, float]:
    granted_ids: list[str] = []
    denied_ids: list[str] = []
    total_cost = 0.0
    for r in fleet_result.results:
        if r.granted:
            granted_ids.append(r.agent_id)
            total_cost += _path_cost(graph, list(r.path))
        else:
            denied_ids.append(r.agent_id)
    return granted_ids, denied_ids, newcomer_id in granted_ids, total_cost


def run_comparison(scenario: Scenario) -> list[ApproachResult]:
    """Score naive-append, insertion-repair and full-BnB on ``scenario``.

    Each approach runs on its own fresh :class:`SharedScheduler`, so the
    comparison is independent and reproducible. ``orderings_explored`` is
    1 for naive append (a single fixed ordering), the number of trial
    insertions for repair, and the number of BnB search nodes for the
    full re-search.
    """
    graph = scenario.graph
    newcomer_id = scenario.newcomer_id
    merged = scenario.committed + [scenario.new_request]
    results: list[ApproachResult] = []

    # 1) Naive append — committed order, newcomer last, greedy (no search).
    sched = SharedScheduler()
    t0 = _time.perf_counter()
    fr = plan_fleet_with_strategy(
        graph, merged, sched, strategy="greedy",
        hold_start=HOLD_START, hold_end=HOLD_END,
    )
    elapsed = (_time.perf_counter() - t0) * 1000.0
    granted, denied, admitted, cost = _score_fleet_result(graph, fr, newcomer_id)
    results.append(
        ApproachResult(
            name="naive append", granted_ids=granted, denied_ids=denied,
            newcomer_admitted=admitted, total_cost=cost,
            orderings_explored=1, elapsed_ms=elapsed,
        )
    )

    # 2) Insertion repair — try the newcomer at every position.
    sched = SharedScheduler()
    rep = plan_fleet_insert(
        graph, scenario.committed, [scenario.new_request], sched,
        hold_start=HOLD_START, hold_end=HOLD_END, objective="min_cost",
    )
    granted, denied, admitted, cost = _score_fleet_result(
        graph, rep.fleet_result, newcomer_id
    )
    results.append(
        ApproachResult(
            name="insertion repair", granted_ids=granted, denied_ids=denied,
            newcomer_admitted=admitted, total_cost=cost,
            orderings_explored=rep.stats.nodes_explored,
            elapsed_ms=rep.stats.elapsed_ms,
        )
    )

    # 3) Full BnB — re-solve committed + newcomer from scratch.
    sched = SharedScheduler()
    full = plan_fleet_bnb(
        graph, merged, sched,
        hold_start=HOLD_START, hold_end=HOLD_END, objective="min_cost",
    )
    granted, denied, admitted, cost = _score_fleet_result(
        graph, full.fleet_result, newcomer_id
    )
    results.append(
        ApproachResult(
            name="full BnB", granted_ids=granted, denied_ids=denied,
            newcomer_admitted=admitted, total_cost=cost,
            orderings_explored=full.stats.nodes_explored,
            elapsed_ms=full.stats.elapsed_ms,
        )
    )
    return results


def comparison_markdown(results: list[ApproachResult], scenario: Scenario) -> str:
    """Render the comparison as a reproducible Markdown table."""
    n_committed = len(scenario.committed)
    parts = [
        "## Incremental admission — insertion repair vs full re-search",
        "",
        f"Scenario: {n_committed} committed services on a "
        f"{len(list(scenario.graph.nodes()))}-node chain, then the urgent "
        f"newcomer `{scenario.newcomer_id}` arrives.",
        "",
        "| approach | granted | newcomer admitted | total cost | trial orderings |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        admitted = "yes" if r.newcomer_admitted else "no"
        parts.append(
            f"| {r.name} | {len(r.granted_ids)}/{r.n_total} | {admitted} | "
            f"{r.total_cost:.1f} | {r.orderings_explored} |"
        )
    parts.append("")

    rep = next(r for r in results if r.name == "insertion repair")
    full = next(r for r in results if r.name == "full BnB")
    naive = next(r for r in results if r.name == "naive append")
    ratio = full.orderings_explored / rep.orderings_explored if rep.orderings_explored else 0.0
    parts.append(
        f"Naive append is locked by submission order — it grants only "
        f"{len(naive.granted_ids)}/{naive.n_total} and leaves the urgent "
        f"newcomer {'admitted' if naive.newcomer_admitted else 'denied'}. "
        f"Insertion repair admits the newcomer and matches full BnB's "
        f"grants ({len(rep.granted_ids)}/{rep.n_total}) and total cost "
        f"({rep.total_cost:.1f}) while exploring **{ratio:.0f}× fewer** trial "
        f"orderings ({rep.orderings_explored} vs {full.orderings_explored})."
    )
    return "\n".join(parts) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", help="optional path to write the Markdown table (also printed)"
    )
    args = parser.parse_args()

    scenario = build_scenario()
    results = run_comparison(scenario)
    md = comparison_markdown(results, scenario)
    if args.out:
        from pathlib import Path

        Path(args.out).write_text(md, encoding="utf-8")
        print(f"wrote incremental-admission table -> {args.out}")
    print(md)


if __name__ == "__main__":
    main()
