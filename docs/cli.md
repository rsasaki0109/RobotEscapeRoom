# CLI reference

All `semantic-toponav` subcommands. The CLI is the canonical entry
point for scripts; the Python API mirrors every flag. Run any
subcommand with `--help` for the full per-command flag list.

## Planning

```text
semantic-toponav validate  GRAPH
semantic-toponav plan      GRAPH START GOAL [--algorithm astar|dijkstra]
                                            [--avoid-restricted] [--avoid-stairs]
                                            [--prefer-elevator]
                                            [--at-time HH:MM [--at-date YYYY-MM-DD]]
                                            [--prefer KEY[:WEIGHT] ...]
                                            [--prefer-unvisited [--visited-multiplier M]]
                                            [--prefer-familiar [--familiar-multiplier M]]
                                            [--avoid-recent SECONDS [--recent-multiplier M] [--now TS]]
                                            [--reservations FILE] [--block-edge ID] [--block-edge-type T]
                                            [--prefer-floor N] [--floor-change-penalty P] [--same-floor-only]
                                            [--format text|json]
semantic-toponav waypoints     GRAPH START GOAL [...same options...]
semantic-toponav describe-path GRAPH START GOAL [...same options...]
                                                [--llm-backend echo|anthropic [...llm flags...]]
semantic-toponav plot          GRAPH [--start S --goal G] [--avoid-*] [--save FILE]
                                     [--show] [--edge-ids] [--title STR]
semantic-toponav viewer        GRAPH [--start S --goal G] [--output FILE.html]
semantic-toponav live-viewer   GRAPH [--host HOST] [--port PORT]
                                     [--start S --goal G] [--poll-interval-ms MS]
```

`live-viewer` runs a local HTTP server that re-renders the page when
the graph YAML changes on disk — useful with the topology editor below.

## Multi-agent

```text
semantic-toponav fleet-plan GRAPH --agent SPEC [--agent SPEC ...]
                                  --hold-start HH:MM --hold-end HH:MM
                                  [--policy fcfs|priority]
                                  [--strategy greedy|priority|deadline|joint|bnb]
                                  [--bnb-objective min_cost|minimax_cost|max_fairness]
                                  [--admission soft|hard]
                                  [--minutes-per-cost-unit FLOAT]
```

`SPEC` is `agent_id:start:goal[:priority[:HH:MM_deadline]]`.

Two additional strategies are Python-API only — they are not reachable
through `fleet-plan`:

- `plan_fleet_exhaustive` — 2^n MIS enumeration as a theoretical
  grant-rate upper bound. Available via `eval-synthetic --strategy
  exhaustive` for measurement purposes.
- `plan_fleet_insert` — insertion-based repair when most of an
  ordering is already committed and only a handful of new requests
  need to be merged in. See [coordination.md](coordination.md) and
  [`semantic_toponav.coordination.plan_fleet_insert`](../semantic_toponav/coordination/repair.py).

## Evaluation

```text
semantic-toponav eval-synthetic [--scenario all|chain|star|doorway|multi_floor]...
                                [--n-agents N] [--seed S]
                                [--hold-start HH:MM] [--hold-end HH:MM]
                                [--deadline-tightness 0..1]
                                [--priority-distribution uniform|mixed|high]
                                [--strategy ...]...
                                [--bnb-objective min_cost|minimax_cost|max_fairness]
                                [--admission soft|hard]
                                [--minutes-per-cost-unit FLOAT]
                                [--out trials.jsonl] [--summary]
semantic-toponav eval-report trials.jsonl [--summary]
semantic-toponav eval-grounding CORPUS.yaml [--top-k N]
                                            [--ambiguity-threshold F]
                                            [--describer-safety]
                                            [--llm-backend echo|anthropic [...llm flags...]]
                                            [--out report.md]
semantic-toponav eval-visual-grounding CORPUS.yaml [--backend hashing|clip]
                                            [--dim N] [--clip-model NAME]
                                            [--top-k N] [--min-score F]
                                            [--out report.md]
```

`eval-grounding` drives `resolve_goal` and (optionally)
`llm_resolve_goal` against a YAML gold corpus tagged
`precise` / `ambiguous` / `unresolvable`, and — with
`--describer-safety` plus a backend — also runs four deterministic
invariants over `llm_describe_path`. Reference corpus:
[`tests/fixtures/grounding/multi_floor_office.yaml`](../tests/fixtures/grounding/multi_floor_office.yaml).

`eval-visual-grounding` is the perception twin: it stamps a gallery,
localizes query frames (`image -> node`), and reports precision@1 /
recall@K plus the abstention split for unseen-place frames. Reference
corpus: [`tests/fixtures/grounding/visual_depot.yaml`](../tests/fixtures/grounding/visual_depot.yaml).
Full details and metric definitions: [eval_grounding.md](eval_grounding.md).

## Visit history

```text
semantic-toponav record-visit  GRAPH NODE_ID [--now TS] [--in-place | --out FILE]
semantic-toponav record-path   GRAPH NODE_ID... [--now TS] [--in-place | --out FILE]
semantic-toponav clear-history GRAPH [NODE_ID...] [--in-place | --out FILE]
semantic-toponav history       GRAPH [NODE_ID...] [--all]
```

## Editing

```text
semantic-toponav inspect   GRAPH [--nodes] [--edges] [--type T]
semantic-toponav add-node  GRAPH ID --type T [--label L] [--x X --y Y [--yaw R]]
                                             [--prop KEY=VALUE ...] [--in-place | --out FILE]
semantic-toponav add-edge  GRAPH SRC TGT --type T [--id ID] [--cost C] [--one-way]
                                                  [--prop KEY=VALUE ...] [--in-place | --out FILE]
semantic-toponav rm-node   GRAPH ID [--in-place | --out FILE]   # cascades to incident edges
semantic-toponav rm-edge   GRAPH ID [--in-place | --out FILE]
semantic-toponav undo      GRAPH                                # revert via the most recent .bak
semantic-toponav diff      GRAPH [OTHER]                        # vs another file, or vs .bak
```

In-place mutating commands (`add-*` / `rm-*` / `mark-doors` /
`annotate-regions` / `compact` / `embed-regions` / `record-visit` /
`record-path` / `clear-history`) write a `GRAPH.bak` snapshot before
overwriting, so `undo` always has something to roll back to.

## Conversion pipelines

```text
semantic-toponav from-occupancy MAP.yaml [--out GRAPH.yaml]
semantic-toponav mark-doors    GRAPH MAP.yaml (--clearance-threshold M | --clearance-percentile P)
                                              [--in-place | --out FILE]
semantic-toponav annotate-regions GRAPH MAP.yaml [...same flags as mark-doors...]
                                                  [--show-regions]
semantic-toponav compact GRAPH [--endpoint-tolerance M] [--edge-cost-tolerance M]
                               [--keep-strategy shortest|first] [--in-place | --out FILE]
semantic-toponav embed-regions GRAPH MAP.yaml --backend hashing|clip
                                              [--dim N] [--image FILE] [--pad-cells N]
                                              [--in-place | --out FILE]
```

## Semantic queries

```text
semantic-toponav find      GRAPH [--type T] [--label-contains S] [--label-equals S]
                                 [--prop KEY=VALUE ...] [--format text|json]
semantic-toponav nearest   GRAPH (--from-pose X Y | --from-node ID)
                                 [...same filter flags as `find`...]
semantic-toponav resolve   GRAPH "natural language goal text"
                                 [--top-k N] [--format text|json]
                                 [--llm-backend echo|anthropic [...llm flags...]]
                                 [--vlm-backend hashing|clip] [--vlm-dim N]
                                 [--clarify-with NODE_ID] [--clarify-free TEXT]
semantic-toponav localize  GRAPH IMAGE [--backend hashing|clip] [--dim N]
                                 [--clip-model NAME] [--top-k N]
                                 [--neighbor-weight F] [--neighbor-hops N]
                                 [...same filter flags as `find`...]
semantic-toponav visual-route GRAPH START_IMAGE GOAL_NODE
                                 [--backend hashing|clip] [--dim N]
                                 [--clip-model NAME] [--top-k N]
                                 [--neighbor-weight F] [--neighbor-hops N]
                                 [--format text|json]
```

`localize` grounds a camera frame to the node it most likely depicts
(`image -> node`); the graph's nodes must already carry embeddings
(e.g. from `embed-regions`) stamped by the **same** encoder you pass
here. `visual-route` chains that with the planner: ground the start
frame, A* to `GOAL_NODE`, print the route + semantic waypoints — the
LM-Nav loop from the CLI. `--neighbor-weight > 0` re-ranks each fix
against its graph neighbors (radius `--neighbor-hops`) to damp
perceptual aliasing. See
[queries.md](queries.md#visual-localization--navigation).

## A scratch-graph mini-tutorial

```bash
echo 'version: 1
metadata: {name: scratch}
nodes: []
edges: []' > scratch.yaml

semantic-toponav add-node scratch.yaml a --type entrance --x 0 --y 0 --in-place
semantic-toponav add-node scratch.yaml b --type corridor --x 2 --y 0 --in-place
semantic-toponav add-node scratch.yaml c --type room     --x 4 --y 0 --in-place
semantic-toponav add-edge scratch.yaml a b --type traversable --in-place
semantic-toponav add-edge scratch.yaml b c --type traversable --in-place
semantic-toponav waypoints scratch.yaml a c
```
