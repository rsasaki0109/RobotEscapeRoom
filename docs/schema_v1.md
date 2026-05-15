# v1.0 schema lock

A handful of `semantic-toponav` types are exposed as wire-level
contracts: Nav2 / Autoware bridges, eval reports, external dashboards,
and out-of-repo adapter packages all depend on these shapes. To make
`semantic-toponav` safe to depend on from outside the repo we mark
the following types as **v1-stable**: their JSON shapes will not
change in a backward-incompatible way without bumping the schema
version.

Internal search algorithms, BnB pruning details, cost-function
composition, and storage backends are **not** part of the v1 lock —
they remain free to evolve.

## Locked surfaces

Each locked surface has:

- a Python dataclass with a `to_dict()` method returning a
  JSON-friendly dict
- a JSON Schema file under [`schemas/`](../schemas/) that callers can
  validate against
- a brief contract note below

| Surface | Dataclass | Schema file | Locked since |
|---|---|---|---|
| `SemanticWaypointArray` | `semantic_toponav.waypoint.SemanticWaypoint` (array of) | [`semantic_waypoint_array.schema.json`](../schemas/semantic_waypoint_array.schema.json) | v1.0 (pre-existing) |
| `PlanWithSchedulerResult` | `semantic_toponav.coordination.PlanWithSchedulerResult` | [`plan_with_scheduler_result_v1.schema.json`](../schemas/plan_with_scheduler_result_v1.schema.json) | v1.0 |
| `FleetPlanResult` | `semantic_toponav.coordination.FleetPlanResult` | [`fleet_plan_result_v1.schema.json`](../schemas/fleet_plan_result_v1.schema.json) | v1.0 |
| `ConflictExplanation` | `semantic_toponav.coordination.ConflictExplanation` | [`conflict_explanation_v1.schema.json`](../schemas/conflict_explanation_v1.schema.json) | v1.0 |
| `ResolveTrace` | `semantic_toponav.query.LLMResolveResult` | [`resolve_trace_v1.schema.json`](../schemas/resolve_trace_v1.schema.json) | v1.0 |
| Preference metadata | edge / node `properties.preferences: {key: number}` | see below | v1.0 |

### `SemanticWaypointArray`

Already documented in [`waypoint_schema.md`](waypoint_schema.md).
Carried into the v1 lock unchanged.

### `PlanWithSchedulerResult`

Per-agent admission record. `reason_code` is the **closed set**
`"ok" | "no_path" | "deadline_miss" | "reservation_conflict" |
"policy_rejected"` — adding a new code requires a new schema
version. Adapters, dashboards, and the Nav2 BT plugin (when it
lands) all dispatch on this field, so the closed-set guarantee is
load-bearing.

### `FleetPlanResult`

Wraps a list of `PlanWithSchedulerResult`. `all_granted` is a
convenience flag (true iff every entry has `granted == true`); it
is re-computable from `results` but locked into the shape so
downstream code can read it without recomputing.

### `ConflictExplanation`

CBS-lite "why was this agent blocked" record emitted by the
branch-and-bound search. `blocking_agents` is sorted deterministically
so byte-for-byte JSON output is reproducible across runs.

### `ResolveTrace`

`LLMResolveResult.to_dict()` shape. The language-grounding eval
suite (`docs/eval_grounding.md`) and any UI surface that wants to
diff the deterministic vs LLM-rewritten ranking consume this. Note
that `embedding_scores` is scalars only — **raw query vectors are
never serialized**, matching the design rule that the prompt
carries structured retrieval context rather than opaque numerics.

### Preference metadata

Edges and nodes may carry a `preferences` mapping under
`properties`:

```yaml
edges:
  - id: garden_path
    properties:
      preferences: {scenic: 0.9, crowded: 0.1}
```

The contract: every value is a `number`, keys are caller-defined
strings, and the planner reads them via `preference_aware(graph,
preferences={key: weight, ...})`. The score formula
(`clamp(1.0 - Σ(weight × value), 0.1, 10.0)`) and node-default
inheritance (skip untagged endpoints) are locked along with the
field shape — changing either is a v2 break.

## Freeze policy

For v1-locked surfaces:

- **Adding** an optional field with a default is allowed but
  discouraged — prefer waiting for a v2 bump if multiple additions
  are anticipated. Optional additions must round-trip through the
  matching JSON Schema's `additionalProperties: false` constraint,
  so the schema file must be updated in the same PR.
- **Removing** or **renaming** a field requires a v2 schema.
- **Changing** a field's type or the meaning of an enum value
  requires a v2 schema.
- **Tightening** a constraint (e.g. requiring a previously optional
  field) requires a v2 schema.
- **Loosening** a constraint (e.g. accepting a wider enum) is
  technically backward-compatible for *consumers* but breaks
  *producers* that exhaustively switch — treat it as a v2 break too.

For everything else (`BnBStats` details, search algorithms,
internal storage formats, eval-report shapes, conformance suite
internals): no stability promise. Touch at will.

## How adapters validate

```python
import json
from pathlib import Path
import jsonschema

from semantic_toponav.coordination import plan_with_scheduler

result = plan_with_scheduler(graph, "robotA", "lobby", "office_2f",
                             scheduler,
                             hold_start="10:00", hold_end="11:00")

schema = json.loads(
    Path("schemas/plan_with_scheduler_result_v1.schema.json").read_text()
)
jsonschema.validate(instance=result.to_dict(), schema=schema)
```

The same pattern works for the other four surfaces. The shipped
test suite (`tests/test_schema_v1_lock.py`) does exactly this for
every locked surface so any drift between the dataclass and its
schema file fails CI.
