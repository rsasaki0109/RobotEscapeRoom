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
```

## Multi-agent

```text
semantic-toponav fleet-plan GRAPH --agent SPEC [--agent SPEC ...]
                                  --hold-start HH:MM --hold-end HH:MM
                                  [--policy fcfs|priority]
                                  [--strategy greedy|priority|deadline|joint|bnb|exhaustive]
                                  [--bnb-objective min_cost|minimax_cost|max_fairness]
                                  [--admission soft|hard]
                                  [--minutes-per-cost-unit FLOAT]
```

`SPEC` is `agent_id:start:goal[:priority[:HH:MM_deadline]]`.

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
```

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
```

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
```

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
