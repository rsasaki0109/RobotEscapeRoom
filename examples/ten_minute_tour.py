"""Ten-minute tour: Plan + Resolve + Coordinate on one graph.

Run from the repository root:

    python examples/ten_minute_tour.py

A single-file walkthrough of the three axes the project ships:

1. **Resolve** — turn a free-text goal ("the kitchen") into a node id
   on the topology graph.  Demonstrates the three case kinds from the
   grounding corpus: precise, ambiguous, unresolvable.
2. **Plan** — run A* between two nodes, then render the path as a
   numbered list of waypoint steps (`path_to_steps`).  Shows the
   deterministic floor that every LLM-augmented surface in the
   library sits on top of.
3. **Coordinate** — give the same graph to a small fleet of three
   agents whose paths overlap, run `plan_fleet_with_strategy` once
   in submission order (`greedy`) and once with branch-and-bound
   reordering (`bnb`), and print the grants/denials so the strategy
   gap is visible.

All output goes to stdout — no plotting, no LLM credentials, no
heavy dependencies.  Runs in well under a second on a normal laptop.

The graph used throughout is `examples/multi_floor_office.yaml`,
the same fixture the grounding eval is denominated against
(`docs/eval_grounding.md`).
"""

from __future__ import annotations

from datetime import time as dtime
from pathlib import Path

from semantic_toponav.coordination import (
    FleetRequest,
    SharedScheduler,
    plan_fleet_with_strategy,
)
from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.planner.astar import plan_astar
from semantic_toponav.query.resolve import resolve_goal
from semantic_toponav.waypoint.describe import path_to_steps

GRAPH_PATH = Path(__file__).parent / "multi_floor_office.yaml"

SECTION_RULE = "=" * 64


def _section(title: str) -> None:
    print()
    print(SECTION_RULE)
    print(title)
    print(SECTION_RULE)


def _demo_resolve(graph) -> str:
    """Section 1: free-text → node id, across the three case kinds.

    Returns the node id chosen for the precise query, used as the
    goal in the planner section that follows.
    """
    _section("1. Resolve — free text to a topology node id")

    queries = [
        ("the kitchen", "precise — unique by label, no floor hint needed"),
        ("the corridor", "ambiguous — every floor has one; floor hint missing"),
        ("the basement", "unresolvable — no basement floor in this graph"),
    ]
    chosen: str | None = None
    for text, note in queries:
        print(f"\nquery: {text!r}   ({note})")
        candidates = resolve_goal(graph, text, top_k=3)
        if not candidates:
            print("  → no candidates (the resolver abstains)")
            continue
        for rank, cand in enumerate(candidates, start=1):
            print(
                f"  {rank}. node={cand.node_id!r}  score={cand.score:.1f}  "
                f"reasons={cand.reasons}"
            )
        if chosen is None:
            chosen = candidates[0].node_id

    assert chosen is not None
    print(
        "\nThe LLM-augmented path (`llm_resolve_goal`) sits on top of "
        "this same\nshortlist — it only re-ranks within these "
        "candidates and never invents\nnew node ids.  See "
        "`docs/eval_grounding.md` and PR #69's expanded\ngold corpus "
        "(50 cases) for the headline measurements."
    )
    return chosen


def _demo_plan(graph, goal: str) -> None:
    """Section 2: A* + waypoint rendering on the resolved goal."""
    _section("2. Plan — A* path + waypoint steps")

    start = "entrance"
    print(f"start = {start!r}   goal = {goal!r}")
    path = plan_astar(graph, start, goal)
    print(f"\npath = {path}")

    steps = path_to_steps(graph, path)
    print("\npath_to_steps (the deterministic floor LLM rewrites sit on):")
    for step in steps:
        print(f"  {step.index}. {step.text}")


def _demo_coordinate(graph) -> None:
    """Section 3: 3-agent fleet, greedy vs bnb on the same scheduler hold."""
    _section("3. Coordinate — fleet admission, greedy vs bnb")

    # Three agents whose paths overlap on corridor_1f / lobby_1f /
    # kitchen_1f.  In submission order, the first agent claims the
    # contested middle section and locks the other two out.  BnB
    # reorders the queue and lets the two short-haul agents in.
    requests = [
        FleetRequest(
            agent_id="alpha (long-haul: entrance→kitchen)",
            start="entrance",
            goal="kitchen_1f",
        ),
        FleetRequest(
            agent_id="beta  (corridor→lab)",
            start="corridor_1f",
            goal="lab_1f",
        ),
        FleetRequest(
            agent_id="gamma (lobby→kitchen)",
            start="lobby_1f",
            goal="kitchen_1f",
        ),
    ]
    print("requests:")
    for req in requests:
        print(
            f"  - {req.agent_id}: {req.start!r} → {req.goal!r}  "
            f"priority={req.priority}"
        )

    for strategy in ("greedy", "bnb"):
        # Fresh scheduler per strategy so the hold window is empty.
        scheduler = SharedScheduler()
        result = plan_fleet_with_strategy(
            graph,
            requests,
            scheduler,
            strategy=strategy,
            hold_start=dtime(10, 0),
            hold_end=dtime(11, 0),
        )
        granted = [r.agent_id for r in result.results if r.granted]
        denied = [
            (r.agent_id, r.reason_code)
            for r in result.results if not r.granted
        ]
        print(f"\nstrategy = {strategy}  granted = {len(granted)}/{len(requests)}")
        for aid in granted:
            print(f"  ✓ {aid}")
        for aid, reason in denied:
            print(f"  ✗ {aid}   reason_code={reason!r}")

    print(
        "\n`greedy` locks the long-haul agent in first and the two "
        "short-haul\nagents lose to reservation conflicts.  `bnb` "
        "reorders so the short-haul\nagents fit in disjoint segments "
        "and the long-haul is the one denied.\n"
        "Same hold window, same graph, same requests — only the "
        "*ordering policy* changed."
    )


def main() -> None:
    print("Loading", GRAPH_PATH.relative_to(Path.cwd()) if GRAPH_PATH.is_absolute() else GRAPH_PATH)
    graph = load_graph(GRAPH_PATH)
    print(
        f"  {len(list(graph.nodes()))} nodes, "
        f"{len(list(graph.edges()))} edges"
    )

    goal = _demo_resolve(graph)
    _demo_plan(graph, goal)
    _demo_coordinate(graph)

    print()
    print(SECTION_RULE)
    print("Done. Next reads:")
    print("  - docs/eval_grounding.md     (Resolve metrics + corpus)")
    print("  - docs/paper_outline.md      (overall claims + chapters)")
    print("  - docs/schema_v1.md          (v1.0 locked wire schemas)")
    print(SECTION_RULE)


if __name__ == "__main__":
    main()
