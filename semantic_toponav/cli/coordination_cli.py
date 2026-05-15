"""``fleet-plan`` subcommand for the ``semantic-toponav`` CLI.

Runs :func:`plan_fleet` against a fresh :class:`SharedScheduler`, then
prints each agent's plan + granted claims. Useful as a one-shot
"what does the joint assignment look like if I send these N requests
in this order, holding each path for [hold_start, hold_end)?".

The CLI deliberately doesn't try to persist the scheduler — every
invocation builds an empty scheduler, runs the requests, and exits.
Production deployments wire :class:`SharedScheduler` into a long-
running service; this command is for inspection / dry-runs.
"""

from __future__ import annotations

import argparse
import json
import sys

from semantic_toponav.coordination.fleet import (
    FleetRequest,
)
from semantic_toponav.coordination.joint import (
    plan_fleet_with_strategy,
)
from semantic_toponav.coordination.policies import (
    first_come_first_served,
    priority_based,
)
from semantic_toponav.coordination.scheduler import SharedScheduler
from semantic_toponav.graph.serialization import GraphLoadError, load_graph
from semantic_toponav.graph.types import GraphValidationError


def _parse_agent_spec(raw: str) -> FleetRequest:
    """Parse ``AGENT_ID:START:GOAL[:PRIORITY[:DEADLINE]]``.

    ``PRIORITY`` is an integer (default 0). ``DEADLINE`` is an
    ``HH:MM`` time-of-day used as a sort key for ``--strategy
    deadline``; it never feeds the scheduler claims themselves. The
    inner colon of ``HH:MM`` is reassembled here because the raw spec
    is already colon-delimited.
    """
    parts = raw.split(":")
    # Possible shapes:
    #   3 -> ID:START:GOAL
    #   4 -> ID:START:GOAL:PRIORITY
    #   6 -> ID:START:GOAL:PRIORITY:HH:MM
    if len(parts) not in (3, 4, 6):
        raise argparse.ArgumentTypeError(
            f"--agent expects AGENT_ID:START:GOAL[:PRIORITY[:HH:MM]]; got {raw!r}"
        )
    agent_id, start, goal = parts[0], parts[1], parts[2]
    priority_raw = parts[3] if len(parts) >= 4 else "0"
    deadline_raw: str | None = (
        f"{parts[4]}:{parts[5]}" if len(parts) == 6 else None
    )
    if not agent_id or not start or not goal:
        raise argparse.ArgumentTypeError(
            f"--agent {raw!r}: agent_id, start, goal must all be non-empty"
        )
    try:
        priority = int(priority_raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"--agent {raw!r}: priority must be an integer ({exc})"
        ) from exc
    return FleetRequest(
        agent_id=agent_id,
        start=start,
        goal=goal,
        priority=priority,
        deadline=deadline_raw,
    )


def cmd_fleet_plan(args: argparse.Namespace) -> int:
    try:
        graph = load_graph(args.graph)
    except (GraphLoadError, GraphValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not args.agent:
        print("error: at least one --agent ID:START:GOAL is required", file=sys.stderr)
        return 2

    policy = first_come_first_served if args.policy == "fcfs" else priority_based
    scheduler = SharedScheduler(policy=policy)

    result = plan_fleet_with_strategy(
        graph,
        args.agent,
        scheduler,
        hold_start=args.hold_start,
        hold_end=args.hold_end,
        at_time=args.at_time,
        strategy=args.strategy,
        algorithm=args.algorithm,
        claim_nodes=not args.claim_edges_only,
        claim_edges=not args.claim_nodes_only,
        rollback_on_failure=args.rollback_on_failure,
        admission=args.admission,
        minutes_per_cost_unit=args.minutes_per_cost_unit,
    )

    if args.format == "json":
        payload = {
            "all_granted": result.all_granted,
            "agents": [
                {
                    "agent_id": r.agent_id,
                    "granted": r.granted,
                    "reason_code": r.reason_code,
                    "path": list(r.path),
                    "failure_reason": r.failure_reason,
                    "claims": [
                        {
                            "resource_id": c.resource_id,
                            "start": c.start.strftime("%H:%M:%S"),
                            "end": c.end.strftime("%H:%M:%S"),
                        }
                        for c in r.claims
                    ],
                    "conflicts": [
                        {
                            "resource_id": c.resource_id,
                            "agent_id": c.agent_id,
                            "start": c.start.strftime("%H:%M:%S"),
                            "end": c.end.strftime("%H:%M:%S"),
                        }
                        for c in r.conflicts
                    ],
                }
                for r in result.results
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if result.all_granted else 1

    for r in result.results:
        tag = "OK" if r.granted else "FAIL"
        print(f"[{tag}] {r.agent_id}")
        if r.path:
            print(f"  path: {' -> '.join(r.path)}")
        if r.granted:
            print(f"  claims: {len(r.claims)} resource(s)")
        else:
            print(f"  reason: {r.failure_reason}")
            if r.conflicts:
                for c in r.conflicts:
                    print(
                        f"    conflict on {c.resource_id!r} held by "
                        f"{c.agent_id!r} ({c.start.strftime('%H:%M')}"
                        f"-{c.end.strftime('%H:%M')})"
                    )
    print()
    print(f"all_granted: {result.all_granted}")
    return 0 if result.all_granted else 1


def register_subcommands(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "fleet-plan",
        help=(
            "plan a multi-agent fleet against a fresh SharedScheduler. "
            "Each --agent gets one path; later agents see earlier holds."
        ),
    )
    p.add_argument("graph", help="path to YAML or JSON topology graph file")
    p.add_argument(
        "--agent",
        type=_parse_agent_spec,
        action="append",
        metavar="ID:START:GOAL[:PRIORITY]",
        help=(
            "agent request (repeatable). Example: --agent r1:entrance:office_2f. "
            "Append :N to set the per-claim priority (default 0; only used by "
            "--policy priority)."
        ),
    )
    p.add_argument(
        "--hold-start",
        required=True,
        metavar="HH:MM",
        help="time-of-day at which each agent's holds begin (inclusive)",
    )
    p.add_argument(
        "--hold-end",
        required=True,
        metavar="HH:MM",
        help="time-of-day at which each agent's holds end (exclusive)",
    )
    p.add_argument(
        "--at-time",
        metavar="HH:MM",
        help=(
            "time-of-day the planner evaluates against (defaults to "
            "--hold-start). Only matters when the graph has time_aware "
            "windows of its own."
        ),
    )
    p.add_argument(
        "--policy",
        choices=["fcfs", "priority"],
        default="fcfs",
        help="conflict policy (default: fcfs)",
    )
    p.add_argument(
        "--strategy",
        choices=["greedy", "priority", "deadline", "joint"],
        default="greedy",
        help=(
            "agent ordering strategy (default: greedy). priority sorts by "
            "--agent :PRIORITY descending; deadline sorts by :HH:MM ascending "
            "(EDF); joint tries multiple orderings and picks the one that "
            "grants the most agents."
        ),
    )
    p.add_argument(
        "--algorithm",
        choices=["astar", "dijkstra"],
        default="astar",
        help="planner algorithm (default: astar)",
    )
    p.add_argument(
        "--claim-nodes-only",
        action="store_true",
        help="reserve only nodes along each path (skip edge claims)",
    )
    p.add_argument(
        "--claim-edges-only",
        action="store_true",
        help="reserve only edges along each path (skip node claims)",
    )
    p.add_argument(
        "--rollback-on-failure",
        action="store_true",
        help=(
            "release every claim made by this call if any agent's plan is "
            "denied (all-or-nothing mode)"
        ),
    )
    p.add_argument(
        "--admission",
        choices=["soft", "hard"],
        default="soft",
        help=(
            "deadline admission control (default: soft). 'hard' refuses to "
            "claim resources for an agent whose projected arrival "
            "(hold_start + path_cost × minutes_per_cost_unit) exceeds its "
            "deadline; the result carries reason_code='deadline_miss'. 'soft' "
            "treats deadline as a sort key only and never blocks a grant."
        ),
    )
    p.add_argument(
        "--minutes-per-cost-unit",
        type=float,
        default=1.0,
        help="minutes of traversal per raw edge-cost unit (default: 1.0)",
    )
    p.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="output format (default: text)",
    )
    p.set_defaults(func=cmd_fleet_plan)
