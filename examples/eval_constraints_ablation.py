"""Semantic-constraints ablation — one row per constraint configuration.

Paper figure (evaluation Chapter 2): the *same* planner + the *same* graph
absorb time-of-day, calendar, soft-preference, and floor-aware constraints
— and refuse to silently route around a calendar it was not told how to
read. Each row is one constraint configuration applied to a fixed route
query on a small multi-floor office; the table shows where the route went,
the plan cost the constraint made A* minimize, and whether the constraint
was honored.

The office is a two-floor graph with a *diamond* on floor 1 — a cheap
"main" corridor (`f1_a → f1_b → f1_d`, cost 2) and a longer "scenic" one
(`f1_a → f1_c → f1_d`, cost 3) — joined to floor 2 by an elevator (cost 2)
and stairs (cost 5). The fixed query is `f2_b → f1_d`. With no constraints
the planner takes the main corridor over the elevator; each constraint then
bends that choice:

* a time-of-day closure on the main corridor reroutes onto the scenic one;
* the weekday / calendar-date variants show the same closure gated by the
  opt-in calendar layer;
* a soft scenic preference (edge-level, then node-level inheritance)
  migrates the route onto the scenic corridor even with nothing closed;
* a floor-change penalty surfaces in the plan cost;
* `compose_costs(prefer_elevator, block stairs)` keeps the route on the
  elevator;
* and a weekday-filtered closure queried *without* a date raises rather
  than silently ignoring the filter (the "explicit error > silent skip"
  guarantee).

Deterministic and dependency-free — no torch, no matplotlib, no API. Run
from the repo root::

    python examples/eval_constraints_ablation.py
    python examples/eval_constraints_ablation.py --out docs/constraints_ablation_sample.md
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import time as dtime

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import TopologyEdge, TopologyNode
from semantic_toponav.planner import (
    NoPathError,
    block_edge_types,
    compose_costs,
    default_edge_cost,
    floor_change_penalty,
    plan_astar,
    prefer_elevator,
    preference_aware,
    time_aware,
)
from semantic_toponav.planner.semantic_costs import CostFn

START, GOAL = "f2_b", "f1_d"
CLOSED_EDGE = "e_main1"  # f1_a -> f1_b, the cheap main-corridor leg
WEEKDAY = "2026-06-08"  # a Monday — inside the weekday-filtered closure
CLOSED_DATE = "2026-06-08"


def build_office() -> TopologyGraph:
    """Two-floor office: a floor-1 diamond (main vs scenic), elevator +
    stairs to floor 2. Carries no constraints — each config injects its
    own onto a fresh copy.
    """
    g = TopologyGraph()
    floors = {
        "f1_a": 1, "f1_b": 1, "f1_c": 1, "f1_d": 1,
        "f2_a": 2, "f2_b": 2,
    }
    for nid, fl in floors.items():
        g.add_node(
            TopologyNode(id=nid, label=nid, type="room", properties={"floor": fl})
        )

    def edge(eid: str, a: str, b: str, cost: float, etype: str = "corridor") -> None:
        g.add_edge(TopologyEdge(id=eid, source=a, target=b, type=etype, cost=cost))

    # Floor 1 diamond: main (a-b-d, total 2) vs scenic (a-c-d, total 3).
    edge("e_main1", "f1_a", "f1_b", 1.0)
    edge("e_main2", "f1_b", "f1_d", 1.0)
    edge("e_scenic1", "f1_a", "f1_c", 1.0)
    edge("e_scenic2", "f1_c", "f1_d", 2.0)
    # Floor 2 chain.
    edge("e_f2", "f2_a", "f2_b", 1.0)
    # Floor transition: elevator (cheap) vs stairs (dear).
    edge("e_elev", "f1_a", "f2_a", 2.0, etype="elevator_connection")
    edge("e_stairs", "f1_a", "f2_a", 5.0, etype="stairs")
    return g


def _edges_on_path(graph: TopologyGraph, path: list[str]) -> list[TopologyEdge]:
    """The edges A* actually traversed, in order."""
    out: list[TopologyEdge] = []
    for a, b in zip(path[:-1], path[1:], strict=False):
        for e in graph.neighbors(a):
            if graph.other_end(e, a) == b:
                out.append(e)
                break
    return out


# --- constraint configurations -------------------------------------------
#
# Each builder receives a *fresh* office graph, may mutate its properties
# (e.g. inject a closure), and returns the cost function to plan with.

@dataclass
class AblationConfig:
    name: str
    constraint: str
    build: Callable[[TopologyGraph], CostFn]
    honored: Callable[[list[str], list[TopologyEdge]], bool] | None = None
    expect_raise: bool = False


def _cfg_baseline(g: TopologyGraph) -> CostFn:
    return default_edge_cost


def _cfg_time_daily(g: TopologyGraph) -> CostFn:
    g.get_edge(CLOSED_EDGE).properties["closed_during"] = [["10:00", "12:00"]]
    return time_aware(g, at_time=dtime(11, 0))


def _cfg_time_weekday(g: TopologyGraph) -> CostFn:
    g.get_edge(CLOSED_EDGE).properties["closed_during"] = [
        ["10:00", "12:00", ["mon", "tue", "wed", "thu", "fri"]]
    ]
    return time_aware(g, at_time=dtime(11, 0), at_date=WEEKDAY)


def _cfg_time_dates(g: TopologyGraph) -> CostFn:
    g.get_edge(CLOSED_EDGE).properties["closed_on_dates"] = [CLOSED_DATE]
    return time_aware(g, at_time=dtime(9, 0), at_date=CLOSED_DATE)


def _cfg_pref_edge(g: TopologyGraph) -> CostFn:
    for eid in ("e_scenic1", "e_scenic2"):
        g.get_edge(eid).properties["preferences"] = {"scenic": 1.0}
    return preference_aware(
        g, preferences={"scenic": 1.0}, use_node_defaults=False
    )


def _cfg_pref_node(g: TopologyGraph) -> CostFn:
    # Tag only the node; incident scenic edges inherit the score.
    g.get_node("f1_c").properties["preferences"] = {"scenic": 1.0}
    return preference_aware(
        g, preferences={"scenic": 1.0}, use_node_defaults=True
    )


def _cfg_floor_penalty(g: TopologyGraph) -> CostFn:
    return floor_change_penalty(g, penalty=10.0)


def _cfg_compose(g: TopologyGraph) -> CostFn:
    return compose_costs(prefer_elevator, block_edge_types(["stairs"]))


def _cfg_calendar_unsafe(g: TopologyGraph) -> CostFn:
    # A weekday-filtered closure queried WITHOUT a date must raise.
    g.get_edge(CLOSED_EDGE).properties["closed_during"] = [
        ["10:00", "12:00", ["mon", "tue", "wed", "thu", "fri"]]
    ]
    return time_aware(g, at_time=dtime(11, 0))  # no at_date -> raises


def _avoids_closed(path: list[str], edges: list[TopologyEdge]) -> bool:
    return all(e.id != CLOSED_EDGE for e in edges)


def _uses_scenic(path: list[str], edges: list[TopologyEdge]) -> bool:
    return "f1_c" in path


def _no_stairs(path: list[str], edges: list[TopologyEdge]) -> bool:
    return all(e.type != "stairs" for e in edges)


def _route_found(path: list[str], edges: list[TopologyEdge]) -> bool:
    return len(path) >= 2


CONFIGS: list[AblationConfig] = [
    AblationConfig("baseline", "none", _cfg_baseline, None),
    AblationConfig("time_aware (daily)", "main corridor closed 10:00–12:00", _cfg_time_daily, _avoids_closed),
    AblationConfig("time_aware + at_date (weekday)", "closure filtered Mon–Fri, queried on a Monday", _cfg_time_weekday, _avoids_closed),
    AblationConfig("time_aware + closed_on_dates", "main corridor closed all day on a date", _cfg_time_dates, _avoids_closed),
    AblationConfig("preference (edge-level)", "soft scenic preference on scenic edges", _cfg_pref_edge, _uses_scenic),
    AblationConfig("preference (node inheritance)", "scenic tag on node f1_c, inherited by edges", _cfg_pref_node, _uses_scenic),
    AblationConfig("floor_change_penalty", "+10 per floor change", _cfg_floor_penalty, _route_found),
    AblationConfig("compose: prefer_elevator + block stairs", "elevator discounted, stairs blocked", _cfg_compose, _no_stairs),
    AblationConfig("calendar-safety (no at_date)", "weekday filter queried without a date", _cfg_calendar_unsafe, None, expect_raise=True),
]


@dataclass
class AblationRow:
    name: str
    constraint: str
    route: str
    plan_cost: str
    honored: str


def _plan_cost(cost_fn: CostFn, edges: list[TopologyEdge]) -> float:
    return sum(cost_fn(e) for e in edges)


def run_ablation(configs: list[AblationConfig] | None = None) -> list[AblationRow]:
    """Run every constraint configuration on a fresh office graph."""
    configs = configs if configs is not None else CONFIGS
    rows: list[AblationRow] = []
    for cfg in configs:
        graph = build_office()
        # Building the cost fn or planning with it may raise the
        # weekday-without-date ValueError — for the calendar-safety row that
        # *is* the measured behavior (explicit error > silent skip).
        try:
            cost_fn = cfg.build(graph)
            path = plan_astar(graph, START, GOAL, cost_fn=cost_fn)
        except ValueError as exc:
            rows.append(
                AblationRow(
                    name=cfg.name, constraint=cfg.constraint,
                    route="—", plan_cost="—",
                    honored=f"raised ✓ ({type(exc).__name__})" if cfg.expect_raise
                    else f"raised ✗ ({exc})",
                )
            )
            continue
        except NoPathError:
            rows.append(
                AblationRow(
                    name=cfg.name, constraint=cfg.constraint,
                    route="no route", plan_cost="∞",
                    honored="denied (no path under constraint)",
                )
            )
            continue

        edges = _edges_on_path(graph, path)
        cost = _plan_cost(cost_fn, edges)
        if cfg.honored is None:
            honored = "—"
        else:
            honored = "yes" if cfg.honored(path, edges) else "NO"
        rows.append(
            AblationRow(
                name=cfg.name, constraint=cfg.constraint,
                route="→".join(path), plan_cost=f"{cost:.1f}",
                honored=honored,
            )
        )
    return rows


def ablation_markdown(rows: list[AblationRow]) -> str:
    parts = [
        "## Semantic-constraints ablation",
        "",
        f"Two-floor office, fixed query `{START} → {GOAL}`. The baseline "
        f"takes the main corridor over the elevator; each constraint bends "
        f"that choice. `plan cost` is the cost the constraint made A* "
        f"minimize.",
        "",
        "| config | constraint | route | plan cost | honored |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        parts.append(
            f"| {r.name} | {r.constraint} | `{r.route}` | {r.plan_cost} | {r.honored} |"
        )
    parts.append("")
    parts.append(
        "Soft preferences migrate the route onto the scenic corridor; "
        "time-of-day closures reroute it there too; the weekday / date "
        "variants gate the closure through the opt-in calendar layer; and a "
        "weekday-filtered closure queried without a date **raises** rather "
        "than silently ignoring the filter."
    )
    return "\n".join(parts) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", help="optional path to write the Markdown table (also printed)"
    )
    args = parser.parse_args()

    rows = run_ablation()
    md = ablation_markdown(rows)
    if args.out:
        from pathlib import Path

        Path(args.out).write_text(md, encoding="utf-8")
        print(f"wrote constraints-ablation table -> {args.out}")
    print(md)


if __name__ == "__main__":
    main()
