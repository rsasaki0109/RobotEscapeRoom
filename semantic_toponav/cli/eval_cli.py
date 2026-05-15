"""``eval-synthetic`` / ``eval-report`` CLI subcommands.

* ``eval-synthetic`` constructs one scenario per ``--scenario`` flag
  using the deterministic generators, runs every requested
  ``--strategy`` against each, and prints (or writes to ``--out``) a
  pivoted markdown summary plus the JSONL transcript.
* ``eval-report`` rehydrates a JSONL file produced earlier and
  reprints the markdown summary. No planner runs.

The default sweep uses every scenario at one fleet size and every
strategy. Run twice with different ``--seed`` to verify the
generators are deterministic.
"""

from __future__ import annotations

import argparse
import sys
from datetime import time as dtime
from pathlib import Path

from semantic_toponav.eval.generators import (
    chain_graph,
    doorway_graph,
    generate_fleet_requests,
    multi_floor_office,
    star_graph,
)
from semantic_toponav.eval.report import (
    jsonl_to_trials,
    summarize_sweep,
    trials_to_jsonl,
    trials_to_markdown_table,
)
from semantic_toponav.eval.runner import Scenario, run_sweep

_SCENARIO_BUILDERS = {
    "chain": lambda seed: chain_graph(8, seed=seed),
    "star": lambda seed: star_graph(6, seed=seed),
    "doorway": lambda seed: doorway_graph(n_rooms=3, seed=seed),
    "multi_floor": lambda seed: multi_floor_office(
        n_floors=2, rooms_per_floor=3, seed=seed
    ),
}

_ALL_SCENARIOS = tuple(_SCENARIO_BUILDERS.keys())


def _parse_hhmm(raw: str) -> dtime:
    h, m = raw.split(":")
    return dtime(int(h), int(m))


def _build_scenarios(
    names: list[str], n_agents: int, seed: int, hold_start: dtime, hold_end: dtime,
    deadline_tightness: float, priority_distribution: str,
) -> list[Scenario]:
    out: list[Scenario] = []
    for i, name in enumerate(names):
        builder = _SCENARIO_BUILDERS[name]
        graph = builder(seed)
        requests = generate_fleet_requests(
            graph,
            n_agents,
            seed=seed + i,
            deadline_tightness=deadline_tightness,
            priority_distribution=priority_distribution,
            hold_start=hold_start,
            hold_end=hold_end,
        )
        out.append(
            Scenario(
                name=name,
                graph=graph,
                requests=requests,
                hold_start=hold_start,
                hold_end=hold_end,
                metadata={
                    "seed": str(seed),
                    "n_agents": str(n_agents),
                    "deadline_tightness": str(deadline_tightness),
                    "priority_distribution": priority_distribution,
                },
            )
        )
    return out


def cmd_eval_synthetic(args: argparse.Namespace) -> int:
    scenarios_arg = args.scenario or ["all"]
    if "all" in scenarios_arg:
        names = list(_ALL_SCENARIOS)
    else:
        names = scenarios_arg
        unknown = [n for n in names if n not in _SCENARIO_BUILDERS]
        if unknown:
            print(
                f"error: unknown scenario(s) {unknown}; "
                f"choose from {list(_SCENARIO_BUILDERS)} or 'all'",
                file=sys.stderr,
            )
            return 2

    try:
        hold_start = _parse_hhmm(args.hold_start)
        hold_end = _parse_hhmm(args.hold_end)
    except (ValueError, IndexError) as exc:
        print(f"error: bad hold window ({exc})", file=sys.stderr)
        return 2

    strategies = list(args.strategy) if args.strategy else None
    scenarios = _build_scenarios(
        names,
        args.n_agents,
        args.seed,
        hold_start,
        hold_end,
        args.deadline_tightness,
        args.priority_distribution,
    )

    kwargs = {
        "admission": args.admission,
        "minutes_per_cost_unit": args.minutes_per_cost_unit,
    }
    trials = (
        run_sweep(scenarios, strategies, **kwargs)
        if strategies
        else run_sweep(scenarios, **kwargs)
    )

    if args.out:
        n = trials_to_jsonl(trials, args.out)
        print(f"wrote {n} trial rows -> {args.out}")

    print(trials_to_markdown_table(trials))

    if args.summary:
        summary = summarize_sweep(trials)
        print("### summary")
        print("| strategy | trials | mean grant_rate | mean total_cost | "
              "mean latency_ms | max latency_ms |")
        print("|---|---|---|---|---|---|")
        for s, stats in summary.items():
            print(
                f"| {s} | {int(stats['trials'])} | "
                f"{stats['mean_grant_rate']:.2f} | "
                f"{stats['mean_total_cost']:.1f} | "
                f"{stats['mean_latency_ms']:.1f} | "
                f"{stats['max_latency_ms']:.1f} |"
            )

    return 0


def cmd_eval_report(args: argparse.Namespace) -> int:
    path = Path(args.jsonl)
    if not path.exists():
        print(f"error: file not found: {args.jsonl}", file=sys.stderr)
        return 2
    trials = jsonl_to_trials(path)
    print(trials_to_markdown_table(trials))
    if args.summary:
        summary = summarize_sweep(trials)
        print("### summary")
        for s, stats in summary.items():
            print(f"- {s}: trials={int(stats['trials'])} "
                  f"grant_rate={stats['mean_grant_rate']:.2f} "
                  f"cost={stats['mean_total_cost']:.1f} "
                  f"latency_ms p50≈{stats['mean_latency_ms']:.1f}")
    return 0


def register_subcommands(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "eval-synthetic",
        help=(
            "run the synthetic eval suite: build deterministic scenarios "
            "(chain/star/doorway/multi_floor), run greedy/priority/"
            "deadline/joint, print a markdown table."
        ),
    )
    p.add_argument(
        "--scenario",
        action="append",
        choices=list(_ALL_SCENARIOS) + ["all"],
        help="scenario to include (repeatable; default: all)",
    )
    p.add_argument(
        "--n-agents", type=int, default=4,
        help="agents per scenario (default: 4)",
    )
    p.add_argument("--seed", type=int, default=0, help="generator seed (default: 0)")
    p.add_argument(
        "--hold-start", default="10:00",
        help="time-of-day claims begin (default: 10:00)",
    )
    p.add_argument(
        "--hold-end", default="11:00",
        help="time-of-day claims end (default: 11:00)",
    )
    p.add_argument(
        "--deadline-tightness", type=float, default=0.0,
        help="0.0 = no deadlines, 1.0 = every request has hold_end as deadline",
    )
    p.add_argument(
        "--priority-distribution",
        choices=["uniform", "mixed", "high"],
        default="uniform",
        help="priority sampling profile (default: uniform / all 0)",
    )
    p.add_argument(
        "--strategy",
        action="append",
        choices=["greedy", "priority", "deadline", "joint", "bnb", "exhaustive"],
        help=(
            "strategy to test (repeatable; default: greedy/priority/"
            "deadline/joint — bnb and exhaustive opt-in. exhaustive is the "
            "MIS grant-rate upper bound and only works for n_agents <= 16)"
        ),
    )
    p.add_argument(
        "--admission",
        choices=["soft", "hard"],
        default="soft",
        help=(
            "deadline admission control (default: soft). 'hard' refuses to "
            "admit agents whose projected arrival would exceed their "
            "deadline — those agents appear in the deadline_misses metric "
            "column."
        ),
    )
    p.add_argument(
        "--minutes-per-cost-unit",
        type=float,
        default=1.0,
        help="minutes of traversal per raw edge-cost unit (default: 1.0)",
    )
    p.add_argument(
        "--out", help="optional JSONL path to persist trials for eval-report"
    )
    p.add_argument(
        "--summary", action="store_true",
        help="also print a per-strategy aggregate summary",
    )
    p.set_defaults(func=cmd_eval_synthetic)

    q = sub.add_parser(
        "eval-report",
        help="rehydrate a JSONL produced by eval-synthetic --out and reprint",
    )
    q.add_argument("jsonl", help="path to a JSONL file from eval-synthetic --out")
    q.add_argument(
        "--summary", action="store_true",
        help="print the per-strategy aggregate summary",
    )
    q.set_defaults(func=cmd_eval_report)
