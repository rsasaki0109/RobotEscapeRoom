# Semantic queries + LLM / VLM / memory

How natural-language-style intents become concrete graph operations.
Four layers, each opt-in:

1. **Deterministic resolvers** — `find_nodes`, `nearest_node_*`,
   `resolve_goal`. No dependencies, always available.
2. **Embedding-based retrieval** — pre-stamped CLIP / SigLIP /
   sentence-encoder vectors via cosine similarity. Core has no model
   dep; the optional `[vlm]` extra adds a CLIP backend.
3. **LLM rewrite** — re-rank the deterministic top-k and rewrite
   path descriptions in prose. Out-of-pool LLM picks are silently
   dropped; the safety property "the LLM cannot invent node ids"
   always holds.
4. **Multi-turn dialog** — `DialogSession` accumulates clarification
   answers across replies so ambiguous goals narrow rather than
   reset on each turn.

Visit-history memory composes orthogonally with all four.

## Deterministic queries

```python
from semantic_toponav.query import (
    find_nodes, nearest_node_by_pose, nearest_node_by_graph_distance,
)

elevators = find_nodes(graph, type="elevator")
office_2f_nodes = find_nodes(graph, properties={"floor": 2})

nearest = nearest_node_by_pose(graph, (0.0, 0.0), type="elevator")
node, path = nearest_node_by_graph_distance(graph, "entrance", type="room")
```

```bash
semantic-toponav find    examples/indoor_office.yaml --type elevator
semantic-toponav nearest examples/indoor_office.yaml --from-node entrance --type room
semantic-toponav resolve examples/indoor_office.yaml "second floor office"
```

`resolve` tokenizes the query, parses floor references (`2F` / `floor
2` / `second floor` / `2nd floor`), and ranks nodes by label / type
token overlap plus floor match — useful as the offline floor under a
later LLM resolver.

## Embedding-based retrieval

Nodes can carry an arbitrary embedding vector under
`properties["embedding"]`. Attach CLIP / SigLIP / sentence-encoder
vectors ahead of time and the library will rank candidates by cosine
similarity — no model dependency in the core:

```python
from semantic_toponav.query import (
    find_nodes_by_embedding, nearest_node_by_embedding,
)

matches = find_nodes_by_embedding(graph, query_vec, top_k=5, type="room")
goal = nearest_node_by_embedding(graph, query_vec, type="room")
```

`python examples/embedding_demo.py` runs a self-contained demo using
deterministic toy embeddings.

### VLM / CLIP encoder integration

Vectors don't have to be hand-rolled. The `semantic_toponav.encoders`
subpackage exposes a `Backend` protocol with two concrete encoders:

- `HashingBackend` — deterministic SHA-derived encoder. Zero
  dependencies. Same input always produces the same L2-normalized
  vector — useful for tests, demos, and as a smoke backend when the
  heavier deps aren't available.
- `CLIPBackend` — lazy `transformers.CLIPModel` wrapper. Requires
  the `[vlm]` extra; model + processor load on the first `embed_*`
  call.

The natural pair is `embed_region_patches`, which crops one image
patch per `annotate_regions` component, embeds it, and stamps the
result onto every graph node carrying that region id:

```python
from semantic_toponav.conversion.occupancy import annotate_regions
from semantic_toponav.conversion.vlm import embed_region_patches
from semantic_toponav.encoders import HashingBackend, CLIPBackend

regions = annotate_regions(graph, occ.free_mask, resolution=occ.resolution)
backend = CLIPBackend()  # or HashingBackend(dim=64) for tests
embed_region_patches(graph, occ.free_mask, regions, backend)
# Every node now carries node.properties["embedding"].
```

CLI:

```bash
semantic-toponav embed-regions graph.yaml map.yaml \
    --backend hashing --dim 64 --in-place
semantic-toponav embed-regions graph.yaml map.yaml \
    --backend clip --image rendered.png --pad-cells 2 --in-place
```

### Aligned-RGB plug point (Mast3R-style adapters)

By default `embed_region_patches` crops a patch out of the same
occupancy grid the topology graph was derived from — fine for tests,
but a real VLM wants a *real-world* photograph of each region, not
an outline of free space. The `AlignedRgbSource` protocol is the
swap-in point:

```python
from semantic_toponav.encoders import AlignedRgbSource, StaticImageRgbSource

# Reference implementation: a pre-aligned (H, W, 3) ndarray in the
# same coordinate frame as the occupancy grid.
src = StaticImageRgbSource(rgb_image)
embed_region_patches(graph, occ.free_mask, regions, backend, rgb_source=src)
```

The protocol surface is tiny on purpose — `shape` plus `crop(bbox)`
— so heavier sources (a Mast3R rerender server, an RGB-D fusion
pipeline, a tiled drone capture) can live in a *separate* package
without dragging torch into the readable-Python core:

```python
class Mast3RRgbSource:
    """Sketch — lives in semantic-toponav-mast3r, not this repo."""

    def __init__(self, model, occupancy_shape: tuple[int, int]) -> None:
        self._model = model
        self._shape = occupancy_shape

    @property
    def shape(self) -> tuple[int, int]:
        return self._shape

    def crop(self, bbox: tuple[int, int, int, int]):
        # Render an aligned RGB patch from the Mast3R reconstruction
        # at the bbox the occupancy region occupies, return ndarray /
        # PIL / bytes — anything Backend.embed_image accepts.
        ...
```

`embed_region_patches` enforces `rgb_source.shape == image.shape[:2]`
so a misaligned source fails loudly at call time rather than
silently producing useless embeddings. The result's `source` field
records whether the run consumed `"occupancy"` or `"rgb_source"`
patches.

## LLM-augmented describe-path / resolve

The deterministic `describe_path` / `resolve_goal` always run first;
an optional LLM layer can rewrite the narration into natural prose
or re-rank the top-k candidates by reading their labels. The LLM is
never allowed to invent a step or a node id — unparseable replies or
out-of-pool picks transparently fall back to the deterministic
output.

```python
from semantic_toponav.llm import EchoBackend, AnthropicBackend
from semantic_toponav.waypoint import llm_describe_path
from semantic_toponav.query import llm_resolve_goal

# Tests / offline demos: EchoBackend takes a scripted list of replies.
backend = EchoBackend(script=[
    "1. Walk in through the entrance.\n2. Head down the main corridor.\n"
    "3. Step into the meeting room.",
])
result = llm_describe_path(graph, ["entrance", "corridor_main", "meeting_room"], backend)
print(result.steps, result.used_fallback)

# Real backend: requires the [llm] extra and ANTHROPIC_API_KEY.
backend = AnthropicBackend()
res = llm_resolve_goal(graph, "the conference room on the second floor", backend, top_k=5)
print(res.candidates[0].node_id, res.llm_reason)
```

CLI (opt-in via `--llm-backend`):

```bash
semantic-toponav describe-path examples/indoor_office.yaml entrance meeting_room \
    --llm-backend echo \
    --llm-script "1. Walk in.\n2. Head into the corridor.\n3. Settle into the meeting room."

semantic-toponav describe-path examples/indoor_office.yaml entrance meeting_room \
    --llm-backend anthropic --llm-style friendly

semantic-toponav resolve examples/indoor_office.yaml "the conference room on the second floor" \
    --llm-backend anthropic
```

### Visual grounding via region embeddings

When `embed-regions` has stamped region-level embeddings onto the
graph, `llm_resolve_goal` can take an optional `query_encoder` and
compute per-candidate cosine similarity between the query text and
each node's stored embedding. The scores are injected into the LLM
prompt as structured fields (`embedding_score=0.42`), never as raw
vectors — the model uses them as additional retrieval signal but
still picks only from the deterministic candidate pool. Candidates
without an embedding show `embedding_score=—` so the model can tell
"no visual signal" apart from "weak visual signal".

CLI parity: `resolve ... --llm-backend ... --vlm-backend hashing|clip`.

### Clarification dialog for ambiguous goals

When the deterministic resolver's top-1 and top-2 candidates have
near-equal scores, or when the LLM emits a `Clarify: <question>`
line, the result carries a `ClarificationQuestion` instead of
committing. Callers ask the user, then re-call with a
`ClarificationAnswer` (either a `chosen_id` from the surfaced
candidates — out-of-pool ids are silently dropped — or a `free_text`
hint appended to the original query).

```python
from semantic_toponav.query import (
    llm_resolve_goal, ClarificationAnswer, AmbiguousGoalError,
)

result = llm_resolve_goal(graph, "meeting room", backend)
if result.clarification is not None:
    print("Ambiguous:", result.clarification.question)
    user_pick = ask_user(result.clarification.candidates)
    result = llm_resolve_goal(
        graph, "meeting room", backend,
        clarification=ClarificationAnswer(chosen_id=user_pick),
    )
```

CLI: `resolve ... --llm-backend ... --clarify-with NODE_ID` or
`--clarify-free "on the second floor"`. JSON output grows
`llm.clarification.question` and `llm.clarification.candidate_ids`.

### Multi-turn DialogSession

The one-shot `ClarificationAnswer` only carries the current call's
hint. `DialogSession` is the stateful wrapper that accumulates
`free_text` hints across replies — so "the second floor one" plus a
later "with the big window" narrows together instead of replacing:

```python
from semantic_toponav.query import DialogSession, ClarificationAnswer

session = DialogSession(graph, backend)
result = session.start("find the meeting room")
while not session.is_resolved():
    question = session.question()
    user_reply = ask_user(question)
    result = session.reply(ClarificationAnswer(free_text=user_reply))

chosen = session.chosen()
```

`session.turns` records the full history (`DialogTurn` per round
with the effective query, the answer that triggered the turn, and
the resolver's result). `start(text)` clears state and begins a
fresh dialog so the same session can be re-used across distinct
goals.

## Visit-history memory

A small memory layer records when each node was last visited, then
lets the planner reason over that history. Visit data lives in
`node.properties` so it round-trips through YAML/JSON with no schema
change.

```python
from semantic_toponav.memory import (
    record_path, prefer_unvisited, prefer_familiar, avoid_recently_visited,
)
from semantic_toponav.planner import plan_astar

record_path(graph, executed_path)

# Coverage / patrol — bias toward unexplored nodes:
path = plan_astar(graph, "entrance", "lab", cost_fn=prefer_unvisited(graph))

# Retrace a familiar route, or avoid nodes touched in the last minute:
plan_astar(graph, "entrance", "lab", cost_fn=prefer_familiar(graph))
plan_astar(graph, "entrance", "lab",
           cost_fn=avoid_recently_visited(graph, within_seconds=60.0))
```

`python examples/memory_demo.py` walks through coverage, retrace,
and time-decay scenarios.

The same history is also addressable from the shell:

```bash
semantic-toponav record-path examples/multi_floor_office.yaml \
    entrance corridor_1f lobby_1f stairs_1f stairs_2f stairs_3f corridor_3f exec_office_3f \
    --in-place
semantic-toponav plan examples/multi_floor_office.yaml entrance exec_office_3f \
    --prefer-unvisited --visited-multiplier 10
semantic-toponav history examples/multi_floor_office.yaml
semantic-toponav clear-history examples/multi_floor_office.yaml --in-place
```
