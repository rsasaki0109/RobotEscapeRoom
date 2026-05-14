"""Online multi-agent coordination on top of the reservation table.

Where :mod:`semantic_toponav.planner.reservations` accepts a *static*
:class:`ReservationTable` (read from disk, evaluated once at plan
time), this subpackage adds the *online* layer: a shared, in-memory
:class:`SharedScheduler` that hands out and revokes claims at runtime,
a pluggable :class:`ConflictPolicy` (first-come-first-served by
default; ``priority_based`` preempts lower-priority holds), and two
convenience entry points:

* :func:`plan_with_scheduler` — plan a single agent against the live
  scheduler state, automatically retrying with the conflicting
  resources blocked when the first attempt overlaps an existing claim.
* :func:`plan_fleet` — run a list of ``(agent_id, start, goal)``
  requests sequentially against one scheduler, accumulating each
  agent's claims so the next agent sees them. Sequential greedy is
  the simplest correct policy and gives the same answer as a single
  batch reservation file when the order is fixed.

The scheduler stays a thin in-memory object — no persistence, no
network. Production users wire it into whatever messaging / RPC layer
they prefer; this module just provides the contract.
"""

from semantic_toponav.coordination.branch_and_bound import (
    BnBPlanResult,
    BnBStats,
    ConflictExplanation,
    Objective,
    plan_fleet_bnb,
)
from semantic_toponav.coordination.exhaustive import (
    ExhaustivePlanResult,
    ExhaustiveStats,
    plan_fleet_exhaustive,
)
from semantic_toponav.coordination.fleet import (
    FleetPlanResult,
    FleetRequest,
    PlanWithSchedulerResult,
    plan_fleet,
    plan_with_scheduler,
)
from semantic_toponav.coordination.http_transport import (
    HttpSchedulerServer,
    HttpTransport,
)
from semantic_toponav.coordination.joint import (
    JointPlanResult,
    JointPlanTrial,
    Strategy,
    plan_fleet_joint,
    plan_fleet_with_strategy,
)
from semantic_toponav.coordination.persistence import (
    load_scheduler,
    save_scheduler,
)
from semantic_toponav.coordination.policies import (
    ClaimDecision,
    ConflictPolicy,
    first_come_first_served,
    priority_based,
)
from semantic_toponav.coordination.repair import plan_fleet_insert
from semantic_toponav.coordination.rpc import (
    LocalTransport,
    RpcError,
    SchedulerClient,
    SchedulerProtocol,
    SchedulerService,
    Transport,
)
from semantic_toponav.coordination.scheduler import (
    ClaimRequest,
    ClaimResult,
    SchedulerError,
    SharedScheduler,
)

__all__ = [
    "BnBPlanResult",
    "BnBStats",
    "ClaimDecision",
    "ClaimRequest",
    "ClaimResult",
    "ConflictExplanation",
    "ConflictPolicy",
    "ExhaustivePlanResult",
    "ExhaustiveStats",
    "FleetPlanResult",
    "FleetRequest",
    "HttpSchedulerServer",
    "HttpTransport",
    "JointPlanResult",
    "JointPlanTrial",
    "LocalTransport",
    "Objective",
    "PlanWithSchedulerResult",
    "RpcError",
    "SchedulerClient",
    "SchedulerError",
    "SchedulerProtocol",
    "SchedulerService",
    "SharedScheduler",
    "Strategy",
    "Transport",
    "first_come_first_served",
    "load_scheduler",
    "plan_fleet",
    "plan_fleet_bnb",
    "plan_fleet_exhaustive",
    "plan_fleet_insert",
    "plan_fleet_joint",
    "plan_fleet_with_strategy",
    "plan_with_scheduler",
    "priority_based",
    "save_scheduler",
]
