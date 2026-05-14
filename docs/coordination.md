# Multi-agent coordination

Where `reservation_aware` in [cost_composition.md](cost_composition.md)
consumes a *static* snapshot, this page covers the *online*
coordination layer in `semantic_toponav.coordination`: an in-memory
scheduler that hands out and revokes claims at runtime, a pluggable
conflict policy, optimal ordering search, an MIS upper-bound
baseline, an RPC shim that wires the same contract over a real wire,
and a synthetic eval suite that measures how well each strategy
does.

## SharedScheduler + plan_fleet

The simplest correct policy is sequential greedy: each agent sees
the holds left by the earlier ones, so the assignment is
deterministic in the request order.

```python
from semantic_toponav.coordination import (
    SharedScheduler, FleetRequest, plan_fleet, plan_with_scheduler,
    priority_based,
)

scheduler = SharedScheduler()  # or SharedScheduler(policy=priority_based)

# One agent at a time:
result = plan_with_scheduler(
    graph, agent_id="r1", start="entrance", goal="kitchen",
    scheduler=scheduler, hold_start="10:00", hold_end="11:00",
)
# result.granted, result.path, result.claims (per-resource Reservations)

# Or a fleet, planned sequentially against the same scheduler:
fleet = plan_fleet(
    graph,
    [FleetRequest("r1", "entrance", "kitchen"),
     FleetRequest("r2", "entrance", "lab"),
     FleetRequest("r3", "entrance", "office_2f", priority=5)],
    scheduler,
    hold_start="10:00", hold_end="11:00",
)
print(fleet.all_granted, fleet.by_agent())
```

Under the `priority_based` policy, a request with `priority > 0` is
allowed to plan as if no reservations existed and then preempts any
conflicting holds at claim time — useful when an emergency / oncall
agent has to route over already-booked resources.

CLI form for dry-runs:

```bash
semantic-toponav fleet-plan examples/indoor_office.yaml \
    --agent r1:entrance:kitchen \
    --agent r2:entrance:lab \
    --agent r3:entrance:office_2f:5 \
    --hold-start 10:00 --hold-end 11:00 \
    --policy priority
```

## Joint fleet optimization

Sequential greedy commits to the caller's order. `plan_fleet_joint`
clones the scheduler, tries multiple orderings on the copy, scores
each by `(granted_count, total_path_cost)`, and applies the winning
ordering to the real scheduler. Small fleets (`n! ≤ max_permutations`,
default `120` = `5!`) are enumerated; larger fleets fall back to a
fixed set of heuristic orderings (insertion / reverse / priority-DESC
/ deadline-ASC):

```python
from semantic_toponav.coordination import (
    plan_fleet_joint, plan_fleet_with_strategy,
)

joint = plan_fleet_joint(
    graph,
    [FleetRequest("r1", "entrance", "kitchen"),
     FleetRequest("r2", "entrance", "lab"),
     FleetRequest("r3", "entrance", "office_2f", deadline="11:00")],
    scheduler,
    hold_start="10:00", hold_end="12:00",
)
print(joint.chosen_order, joint.trials_evaluated, joint.enumerated)

# Or one dispatcher across all strategies:
res = plan_fleet_with_strategy(
    graph, requests, scheduler,
    strategy="deadline",  # "greedy" | "priority" | "deadline" | "joint" | "bnb" | "exhaustive"
    hold_start="10:00", hold_end="12:00",
)
```

The CLI exposes the same via `--strategy`, and the `--agent` syntax
gains an optional `:HH:MM` deadline suffix:

```bash
semantic-toponav fleet-plan examples/indoor_office.yaml \
    --agent r1:entrance:kitchen:0:11:00 \
    --agent r2:entrance:lab:0:10:30 \
    --hold-start 10:00 --hold-end 12:00 \
    --strategy deadline
```

## Branch-and-bound + fairness objectives

`plan_fleet_bnb` is the pruned cousin of `plan_fleet_joint`: a DFS
over partial agent orderings with three pruners (grants upper bound,
cost lower bound, `max_nodes` / `time_budget_ms` budget) so the call
stays bounded even on adversarial inputs.

```python
from semantic_toponav.coordination import plan_fleet_bnb

result = plan_fleet_bnb(
    graph, requests, scheduler,
    hold_start="10:00", hold_end="11:00",
    admission="hard",
    max_nodes=10_000,
    objective="min_cost",   # or "minimax_cost" / "max_fairness"
)
# result.chosen_order, result.stats, result.per_agent_costs,
# result.conflict_explanations  # CBS-lite "who blocked whom"
```

Three objectives are available:

- `"min_cost"` (default) — minimize total path cost across granted
  agents. Matches the joint planner's tie-break.
- `"minimax_cost"` — minimize the maximum per-agent path cost.
  Picks egalitarian orderings: one agent doing all the long routes
  is penalized even when total cost ties.
- `"max_fairness"` — maximize Jain's fairness index over per-agent
  path costs. Total cost is the final tie-break.

CLI parity: `--strategy bnb --bnb-objective max_fairness` on both
`fleet-plan` and `eval-synthetic`.

## Hard deadline admission control

`FleetRequest.deadline` started as a sort key for the `deadline`
strategy. With `admission="hard"`, it also functions as a *hard*
constraint: a request whose projected arrival time (`hold_start +
path_cost × minutes_per_cost_unit`) exceeds its deadline is rejected
with `reason_code="deadline_miss"` and *zero* claims on the scheduler.

```python
result = plan_with_scheduler(
    graph, "robot42", "lobby", "office_2f", scheduler,
    hold_start="10:00", hold_end="11:00",
    deadline="10:05",
    admission="hard",
    minutes_per_cost_unit=1.0,
)
# result.granted == False, result.reason_code == "deadline_miss"
# scheduler.claims_for("robot42") == []
```

`PlanWithSchedulerResult.reason_code` is `"ok" | "no_path" |
"deadline_miss" | "reservation_conflict" | "policy_rejected"` — use
it for switch / dispatch rather than parsing `failure_reason`. The
default `admission="soft"` preserves pre-PR-37 behavior.

## Exhaustive MIS baseline

`plan_fleet_exhaustive` answers a more fundamental question than the
sequential planners: *if every agent planned independently, what is
the largest grantable subset of those plans?* That's the maximum
independent set on the path-overlap conflict graph — a strict upper
bound on grants for fixed paths.

```python
from semantic_toponav.coordination import plan_fleet_exhaustive

result = plan_fleet_exhaustive(
    graph, requests, scheduler,
    hold_start="10:00", hold_end="11:00",
    n_limit=16,  # 2^n enumeration guard
)
# result.granted_agents, result.per_agent_costs (via fleet_result),
# result.stats.subsets_evaluated
```

Cap defaults to 16 (≈65k subsets, sub-millisecond on small graphs).
Use this to validate BnB is finding the optimum: when BnB matches
exhaustive grant count, no scheduling tweak inside the existing
framework can do better. CLI: `--strategy exhaustive`.

## Real-time scheduler RPC

`SharedScheduler` is process-local. Production deployments wire it
behind a long-running service so multiple planner processes share
one logical scheduler. The transport-agnostic shim:

```python
from semantic_toponav.coordination import (
    LocalTransport, SchedulerClient, SchedulerService, SharedScheduler,
)

backing = SharedScheduler()
service = SchedulerService(backing)
client = SchedulerClient(LocalTransport(service))  # swap for HTTP / NATS / gRPC

result = plan_fleet(graph, requests, client,
                    hold_start="10:00", hold_end="11:00")
# Mutations applied through the wire show up on the backing scheduler.
```

A stdlib-only HTTP reference is bundled:

```python
from semantic_toponav.coordination import (
    HttpSchedulerServer, HttpTransport, SchedulerClient, SchedulerService,
)

with HttpSchedulerServer(SchedulerService(SharedScheduler())) as server:
    client = SchedulerClient(HttpTransport(server.url))
    client.ping()
```

The wire protocol is JSON `POST /` with `{"op": ..., ...}` payloads;
the contract handles `claim`, `claim_many`, `release`, `release_all`,
`reservations`, `claims_for`, `conflicts`, `table`, and `ping`. Build
your own transport by implementing the one-method `Transport`
protocol (`send(dict) -> dict`).

The strategy dispatcher's `greedy`, `priority`, and `deadline` modes
work transparently against the client; `joint` / `bnb` / `exhaustive`
require a local scheduler because they call `SharedScheduler.clone()`
(cloning state over the wire would defeat the point).

## Synthetic evaluation suite

Functional tests prove the planner *runs*; the synthetic eval suite
measures *how well* each strategy does. Four canonical graphs
(chain, star, doorway, multi-floor) plus deterministic, seed-driven
fleet generators feed `plan_fleet_with_strategy` and emit a pivoted
markdown table:

```bash
semantic-toponav eval-synthetic \
    --scenario all --n-agents 3 --seed 0 \
    --hold-start 10:00 --hold-end 11:00 --summary

# All six strategies + the MIS upper bound:
semantic-toponav eval-synthetic --scenario doorway --n-agents 4 \
    --strategy greedy --strategy joint --strategy bnb \
    --strategy exhaustive --bnb-objective max_fairness

# Persist + reprint later without re-running:
semantic-toponav eval-synthetic --scenario all --n-agents 4 \
    --out trials.jsonl
semantic-toponav eval-report trials.jsonl --summary
```

The metrics block reports grant rate, total path cost, coordination
makespan, max wait, Jain's fairness, conflict count, deadline misses
(under `--admission hard`), and per-strategy latency p50 / max.
Python API mirror: `from semantic_toponav.eval import Scenario,
run_sweep, trials_to_markdown_table`.
