"""Embedding-based semantic node retrieval demo.

Run from the repository root:

    python examples/embedding_demo.py

The MVP doesn't ship a real text or vision encoder, but the embedding
*storage and query* layer is independent of the encoder. This demo uses
deterministic SHA-256-derived toy vectors so the example runs with no
external dependencies — swap in CLIP / SigLIP / sentence-transformers
vectors at the same code path to use real semantics.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.query import find_nodes_by_embedding, nearest_node_by_embedding

GRAPH_PATH = Path(__file__).parent / "indoor_office.yaml"
EMBEDDING_DIM = 16


def toy_embedding(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """Deterministic [-1, 1] vector derived from a SHA-256 hash of ``text``.

    Not semantically meaningful — purely a stand-in so the demo runs
    without downloading any encoder model.
    """
    out: list[float] = []
    seed = text.encode("utf-8")
    while len(out) < dim:
        seed = hashlib.sha256(seed).digest()
        out.extend((b - 128) / 128.0 for b in seed)
    return out[:dim]


def main() -> None:
    graph = load_graph(GRAPH_PATH)
    for node in graph.nodes():
        node.properties["embedding"] = toy_embedding(node.label)

    queries = [
        "Meeting Room",
        "Robotics Lab",
        "Elevator A (1F)",
        "non-existent label that no node has",
    ]
    for q in queries:
        print(f"\nquery: {q!r}")
        vec = toy_embedding(q)
        for node, sim in find_nodes_by_embedding(graph, vec, top_k=3):
            print(f"  {node.id:25s} sim={sim:+.4f}  label={node.label!r}")

    print("\nfiltered: nearest room-type match to 'Meeting Room'")
    vec = toy_embedding("Meeting Room")
    node = nearest_node_by_embedding(graph, vec, type="room")
    print(f"  -> {node.id} ({node.label!r})")


if __name__ == "__main__":
    main()
