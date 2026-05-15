"""Tests for the embedding-aware path through llm_resolve_goal (PR #39)."""

from __future__ import annotations

from pathlib import Path

from semantic_toponav.encoders.backends import HashingBackend
from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.llm.backends import EchoBackend
from semantic_toponav.query.llm_resolve import (
    _build_prompt,
    _compute_embedding_scores,
    _format_candidate_block,
    llm_resolve_goal,
)
from semantic_toponav.query.resolve import resolve_goal

EXAMPLE_YAML = Path(__file__).resolve().parents[1] / "examples" / "indoor_office.yaml"


def _graph_with_stamped_embeddings(encoder: HashingBackend):
    """Load the indoor-office example and stamp HashingBackend embeddings
    of each node's label onto the node so embedding queries have a real
    signal to chase."""
    g = load_graph(EXAMPLE_YAML)
    for node in list(g._nodes.values()):  # noqa: SLF001 - test-internal
        node.properties["embedding"] = encoder.embed_text(node.label)
    return g


def test_compute_embedding_scores_populates_dict_when_nodes_have_embeddings() -> None:
    encoder = HashingBackend(dim=32)
    g = _graph_with_stamped_embeddings(encoder)
    base = resolve_goal(g, "kitchen", top_k=5)
    scores = _compute_embedding_scores(base, encoder, "Kitchen")
    # All candidates have an embedding stamped, so every candidate
    # gets a score.
    assert set(scores.keys()) == {c.node_id for c in base}
    # Each score is a finite float in [-1, 1].
    for v in scores.values():
        assert -1.0 <= v <= 1.0


def test_compute_embedding_scores_skips_nodes_without_embedding() -> None:
    encoder = HashingBackend(dim=32)
    g = load_graph(EXAMPLE_YAML)  # no embeddings stamped
    base = resolve_goal(g, "kitchen", top_k=5)
    scores = _compute_embedding_scores(base, encoder, "Kitchen")
    assert scores == {}


def test_compute_embedding_scores_skips_dimension_mismatch() -> None:
    encoder = HashingBackend(dim=32)
    g = load_graph(EXAMPLE_YAML)
    # Stamp a wrong-dim vector on a single node.
    for node in g._nodes.values():
        node.properties["embedding"] = [0.0] * 16  # wrong dim
        break
    base = resolve_goal(g, "kitchen", top_k=5)
    scores = _compute_embedding_scores(base, encoder, "kitchen")
    # No node has the matching dim, so dict stays empty.
    assert scores == {}


def test_prompt_includes_embedding_score_lines() -> None:
    encoder = HashingBackend(dim=32)
    g = _graph_with_stamped_embeddings(encoder)
    base = resolve_goal(g, "kitchen", top_k=3)
    scores = _compute_embedding_scores(base, encoder, "Kitchen")
    prompt = _build_prompt("Kitchen", base, embedding_scores=scores)
    # Every line should carry the embedding_score= suffix.
    for c in base:
        assert f"embedding_score={scores[c.node_id]:.3f}" in prompt
    # And the system instruction note about using the score.
    assert "additional signal" in prompt


def test_prompt_omits_embedding_when_none_given() -> None:
    g = load_graph(EXAMPLE_YAML)
    base = resolve_goal(g, "kitchen", top_k=3)
    prompt = _build_prompt("kitchen", base)
    assert "embedding_score" not in prompt


def test_format_candidate_block_dash_for_missing_embedding() -> None:
    encoder = HashingBackend(dim=32)
    g = _graph_with_stamped_embeddings(encoder)
    # Remove one node's embedding so it shows up as missing.
    target = next(iter(g._nodes.values()))
    target.properties.pop("embedding")
    base = resolve_goal(g, target.label, top_k=5)
    scores = _compute_embedding_scores(base, encoder, target.label)
    block = _format_candidate_block(base, embedding_scores=scores)
    # The target node line carries the em-dash placeholder.
    target_line = next(ln for ln in block.splitlines() if target.id in ln)
    assert "embedding_score=—" in target_line


def test_llm_resolve_goal_with_encoder_populates_embedding_scores() -> None:
    encoder = HashingBackend(dim=32)
    g = _graph_with_stamped_embeddings(encoder)
    backend = EchoBackend(
        script=["Top match: kitchen\nReason: matches the kitchen label."]
    )
    result = llm_resolve_goal(
        g, "kitchen", backend, top_k=5, query_encoder=encoder
    )
    assert result.embedding_scores  # non-empty
    # The picked node id must appear in the embedding_scores keys
    # (every base candidate has an embedding stamped on it).
    assert result.llm_pick in result.embedding_scores


def test_llm_resolve_goal_without_encoder_keeps_empty_scores() -> None:
    g = load_graph(EXAMPLE_YAML)
    backend = EchoBackend(
        script=["Top match: kitchen\nReason: matches the kitchen label."]
    )
    result = llm_resolve_goal(g, "kitchen", backend, top_k=5)
    assert result.embedding_scores == {}


def test_encoder_does_not_change_llm_fallback_safety() -> None:
    """When the LLM picks an out-of-pool id, the embedding scores should
    still be recorded for telemetry but the candidates list still falls
    back to the deterministic order."""
    encoder = HashingBackend(dim=32)
    g = _graph_with_stamped_embeddings(encoder)
    backend = EchoBackend(
        script=["Top match: definitely_not_a_real_node\nReason: hallucinated."]
    )
    result = llm_resolve_goal(
        g, "kitchen", backend, top_k=5, query_encoder=encoder
    )
    assert result.used_fallback is True
    assert result.candidates == result.base_candidates
    # Scores were still computed pre-fallback.
    assert result.embedding_scores


def test_encoder_with_empty_base_short_circuits() -> None:
    """When resolve_goal returns no base candidates, the encoder is not
    invoked at all — short-circuit preserves the contract."""
    g = load_graph(EXAMPLE_YAML)

    class _FailingEncoder:
        dim = 32

        def embed_text(self, text: str):
            raise AssertionError("embed_text must not be called on empty base")

        def embed_image(self, image):  # pragma: no cover - unused
            raise NotImplementedError

        def embed_images(self, images):  # pragma: no cover - unused
            raise NotImplementedError

    result = llm_resolve_goal(
        g, "", EchoBackend(),
        top_k=5,
        query_encoder=_FailingEncoder(),  # type: ignore[arg-type]
    )
    assert result.candidates == []
    assert result.embedding_scores == {}


def test_zero_vector_candidate_silently_skipped() -> None:
    encoder = HashingBackend(dim=32)
    g = _graph_with_stamped_embeddings(encoder)
    # Force one node to a zero embedding so cosine_similarity raises.
    target = next(iter(g._nodes.values()))
    target.properties["embedding"] = [0.0] * 32
    base = resolve_goal(g, target.label, top_k=5)
    scores = _compute_embedding_scores(base, encoder, target.label)
    # The zero-vector node is excluded; other nodes still get scored.
    assert target.id not in scores
