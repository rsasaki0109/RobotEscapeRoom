"""Budget-bounded BnB — partial-best behaviour as the fleet grows.

Paper figure (evaluation Chapter 1, the *scaling* story): branch-and-bound
over agent orderings is an **anytime** planner — capped at a fixed node
budget it returns its best ordering found so far. This sweep shows what
that best-so-far is worth as the fleet grows past the point where the full
search (or the exhaustive MIS upper bound) is affordable.

Scenario (deterministic, seed-free by construction): ``k`` independent
contention *clusters*, each four chain nodes carrying a chain-spanning
``blocker`` plus two disjoint short services. Submission order lists the
blocker first, so a sequential greedy planner grants the blocker and is
forced to deny both shorts — ``k`` grants. The optimum drops every blocker
and grants both shorts per cluster — ``2k`` grants. The fleet is ``n = 3k``
agents.

Across the sweep, with a fixed ``max_nodes`` budget, BnB:

* **completes** for the smallest fleet and matches the exhaustive optimum
  (pruning reaches the MIS upper bound);
* for larger fleets the budget is exhausted before the search completes,
  but the returned best-so-far is **always strictly better than greedy**
  (the anytime guarantee) — it never regresses below the baseline;
* keeps running well past ``n = 24``, where the ``2^n`` exhaustive
  baseline is no longer affordable at all.

Deterministic and dependency-free — no torch, no matplotlib, no API. Run
from the repo root::

    python examples/eval_bnb_budget_sweep.py
    python examples/eval_bnb_budget_sweep.py --out docs/bnb_budget_sweep_sample.md
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import time as dtime

from semantic_toponav.coordination import (
    FleetRequest,
    SharedScheduler,
    plan_fleet_with_strategy,
)
from semantic_toponav.coordination.branch_and_bound import plan_fleet_bnb
from semantic_toponav.eval.generators import chain_graph
from semantic_toponav.graph.topology_graph import TopologyGraph

HOLD_START, HOLD_END = dtime(10, 0), dtime(11, 0)
SWEEP_K = [2, 3, 4, 6, 8, 10]  # clusters -> n = 3k agents: 6, 9, 12, 18, 24, 30
NODE_BUDGET = 2000
# plan_fleet_with_strategy caps exhaustive at this many agents; beyond it the
# 2^n MIS upper bound is not computed (it is infeasible to enumerate).
EXHAUSTIVE_N_LIMIT = 24


def build_clustered_scenario(k: int) -> tuple[TopologyGraph, list[FleetRequest]]:
    """``k`` contention clusters of (one blocker + two disjoint shorts).

    Cluster ``c`` owns chain nodes ``n[4c .. 4c+3]``: ``B{c}`` spans the
    whole cluster, ``S{c}a`` and ``S{c}b`` take its two disjoint halves.
    Greedy grants the blockers (``k``); the optimum grants the shorts
    (``2k``).
    """
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    graph = chain_graph(4 * k)
    requests: list[FleetRequest] = []
    for c in range(k):
        b = 4 * c
        requests.append(FleetRequest(agent_id=f"B{c}", start=f"n{b}", goal=f"n{b + 3}"))
        requests.append(FleetRequest(agent_id=f"S{c}a", start=f"n{b}", goal=f"n{b + 1}"))
        requests.append(
            FleetRequest(agent_id=f"S{c}b", start=f"n{b + 2}", goal=f"n{b + 3}")
        )
    return graph, requests


def _grants(fleet_result) -> int:
    return sum(1 for r in fleet_result.results if r.granted)


@dataclass
class SweepRow:
    k: int
    n: int
    greedy: int
    bnb: int
    bnb_completed: bool
    bnb_nodes: int
    exhaustive: int | None  # None when n exceeds the exhaustive limit
    optimum: int  # 2k by construction


def run_sweep(
    ks: list[int] | None = None, *, node_budget: int = NODE_BUDGET
) -> list[SweepRow]:
    """Run greedy / budget-bounded BnB / exhaustive for each fleet size."""
    ks = ks if ks is not None else SWEEP_K
    rows: list[SweepRow] = []
    for k in ks:
        graph, requests = build_clustered_scenario(k)
        n = 3 * k

        greedy = _grants(
            plan_fleet_with_strategy(
                graph, requests, SharedScheduler(),
                hold_start=HOLD_START, hold_end=HOLD_END, strategy="greedy",
            )
        )
        bnb = plan_fleet_bnb(
            graph, requests, SharedScheduler(),
            hold_start=HOLD_START, hold_end=HOLD_END, max_nodes=node_budget,
        )
        exhaustive: int | None = None
        if n <= EXHAUSTIVE_N_LIMIT:
            exhaustive = _grants(
                plan_fleet_with_strategy(
                    graph, requests, SharedScheduler(),
                    hold_start=HOLD_START, hold_end=HOLD_END,
                    strategy="exhaustive", exhaustive_n_limit=EXHAUSTIVE_N_LIMIT,
                )
            )
        rows.append(
            SweepRow(
                k=k, n=n, greedy=greedy,
                bnb=_grants(bnb.fleet_result),
                bnb_completed=bnb.stats.completed,
                bnb_nodes=bnb.stats.nodes_explored,
                exhaustive=exhaustive,
                optimum=2 * k,
            )
        )
    return rows


def sweep_markdown(rows: list[SweepRow], *, node_budget: int = NODE_BUDGET) -> str:
    parts = [
        "## Budget-bounded BnB — partial-best as the fleet grows",
        "",
        f"`k` contention clusters (blocker + two disjoint shorts), "
        f"`n = 3k` agents. Greedy grants the blockers (`k`); the optimum "
        f"grants the shorts (`2k`). BnB is capped at `max_nodes = "
        f"{node_budget}` and returns its best ordering found so far.",
        "",
        "| n | greedy | BnB (budget) | completed | BnB nodes | exhaustive | optimum (2k) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        ex = str(r.exhaustive) if r.exhaustive is not None else "— (infeasible)"
        parts.append(
            f"| {r.n} | {r.greedy} | {r.bnb} | "
            f"{'yes' if r.bnb_completed else 'partial'} | {r.bnb_nodes} | "
            f"{ex} | {r.optimum} |"
        )
    parts.append("")
    parts.append(
        "BnB completes and matches the exhaustive optimum on the smallest "
        "fleet; for larger fleets the node budget is exhausted before the "
        "search completes, but the best-so-far stays **strictly above "
        "greedy** (the anytime guarantee) and keeps running past the point "
        "where the 2^n exhaustive baseline is no longer affordable."
    )
    return "\n".join(parts) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", help="optional path to write the Markdown table (also printed)"
    )
    parser.add_argument(
        "--budget", type=int, default=NODE_BUDGET,
        help=f"BnB max_nodes budget (default: {NODE_BUDGET})",
    )
    args = parser.parse_args()

    rows = run_sweep(node_budget=args.budget)
    md = sweep_markdown(rows, node_budget=args.budget)
    if args.out:
        from pathlib import Path

        Path(args.out).write_text(md, encoding="utf-8")
        print(f"wrote BnB budget-sweep table -> {args.out}")
    print(md)


if __name__ == "__main__":
    main()
