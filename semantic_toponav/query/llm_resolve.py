"""LLM-augmented goal resolution on top of :func:`resolve_goal`.

:func:`resolve_goal` runs a deterministic bag-of-words + floor-aware
scorer over the graph. It is fast, dependency-free, and reproducible,
but it doesn't understand synonyms ("conf room" ≈ "meeting room") or
soft phrasing ("somewhere quiet to take a call"). The LLM rewrite
layer here closes that gap *without* discarding the deterministic
floor: we always start from a list of candidates produced by
``resolve_goal`` and ask the LLM only to *re-rank or pick from* that
list, never to invent a node id.

If the LLM names a node id that doesn't appear in the candidate pool,
we ignore the pick and fall back to the deterministic ranking. That is
the safety property that lets this layer be turned on by default
without breaking offline / unit-test use.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from semantic_toponav.encoders.backends import Backend as EncoderBackend
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import TopologyNode
from semantic_toponav.llm.backends import LLMBackend
from semantic_toponav.query.embedding import (
    DEFAULT_EMBEDDING_PROPERTY,
    cosine_similarity,
)
from semantic_toponav.query.resolve import GoalCandidate, resolve_goal

_TOP_MATCH_LINE = re.compile(
    r"^\s*(?:top\s+match|best|chosen|pick|answer)\s*[:\-]\s*(\S+)\s*$",
    re.IGNORECASE,
)

_DEFAULT_SYSTEM = (
    "You resolve free-text navigation goals to a specific node id from "
    "a pre-filtered candidate list. You MUST pick a node id from the "
    "candidate list — never invent one. Reply with exactly two lines: "
    "first `Top match: <node_id>`, then `Reason: <one-sentence "
    "justification>`."
)


@dataclass
class LLMResolveResult:
    """Outcome of :func:`llm_resolve_goal`.

    Attributes
    ----------
    query:
        The original free-text query.
    candidates:
        Final ranking — either the LLM-picked candidate moved to the
        front of the deterministic list, or the deterministic order
        unchanged when the LLM reply was unparseable or pointed at a
        node id outside the candidate pool.
    base_candidates:
        The deterministic candidate list returned by
        :func:`resolve_goal`, preserved so callers can diff against
        the rewrite.
    llm_pick:
        Node id the model named as the top match, when the reply could
        be parsed. ``None`` when parsing failed or the model didn't
        pick anything.
    llm_reason:
        One-line justification the model supplied, when parsable.
    raw_response:
        Unmodified backend output, useful for logging.
    used_fallback:
        ``True`` when the LLM pick was rejected (unparseable or
        out-of-pool) and the deterministic ranking was kept.
    embedding_scores:
        Per-candidate cosine similarity between the query embedding
        and each candidate node's stored embedding. Empty when no
        ``query_encoder`` was passed to :func:`llm_resolve_goal`, or
        for candidates that don't carry an embedding. Pure telemetry —
        the LLM sees these as structured context in the prompt;
        callers can inspect them to diff embedding ranking against
        the deterministic ranking.
    """

    query: str
    candidates: list[GoalCandidate]
    base_candidates: list[GoalCandidate]
    llm_pick: str | None = None
    llm_reason: str | None = None
    raw_response: str = ""
    used_fallback: bool = False
    embedding_scores: dict[str, float] = field(default_factory=dict)


def _format_candidate_block(
    candidates: list[GoalCandidate],
    embedding_scores: dict[str, float] | None = None,
) -> str:
    """Format candidate list lines for the LLM prompt.

    When ``embedding_scores`` is provided, every line gains an
    ``embedding_score=0.42`` field for the candidates that have a
    stored embedding. Candidates without an embedding get
    ``embedding_score=—`` so the LLM can tell "we have no visual
    signal here" apart from "the visual signal was weak". Raw
    vectors are never embedded into the prompt — only the scalar
    similarities.
    """
    lines: list[str] = []
    for c in candidates:
        node = c.node
        floor = node.properties.get("floor")
        floor_part = f", floor={floor}" if isinstance(floor, int) else ""
        emb_part = ""
        if embedding_scores is not None:
            if c.node_id in embedding_scores:
                emb_part = f", embedding_score={embedding_scores[c.node_id]:.3f}"
            else:
                emb_part = ", embedding_score=—"
        lines.append(
            f"- {c.node_id}: label={node.label!r}, type={node.type}"
            f"{floor_part} (score={c.score:g}{emb_part})"
        )
    return "\n".join(lines)


def _build_prompt(
    query: str,
    candidates: list[GoalCandidate],
    embedding_scores: dict[str, float] | None = None,
) -> str:
    lines = [
        f"User query: {query}",
        "",
        "Candidate nodes (you MUST pick one of these node ids):",
        _format_candidate_block(candidates, embedding_scores=embedding_scores),
        "",
    ]
    if embedding_scores:
        lines.extend(
            [
                "Each candidate shows a deterministic `score=` from text "
                "matching plus an `embedding_score=` cosine similarity from "
                "the visual encoder (when available). Use the embedding "
                "score as additional signal, especially when the visual "
                "content matches the query phrasing.",
                "",
            ]
        )
    lines.extend(
        [
            "Reply with exactly:",
            "Top match: <node_id>",
            "Reason: <one short sentence>",
        ]
    )
    return "\n".join(lines)


def _compute_embedding_scores(
    candidates: list[GoalCandidate],
    query_encoder: EncoderBackend,
    query_text: str,
    *,
    embedding_property: str = DEFAULT_EMBEDDING_PROPERTY,
) -> dict[str, float]:
    """Cosine similarity between the query embedding and each candidate.

    Candidates whose node lacks an embedding under
    ``embedding_property`` are skipped (the returned dict simply
    doesn't include them). A dimension mismatch silently skips the
    candidate too — the encoder identity isn't recorded on the
    graph, so we can't verify it at runtime; the conservative
    behavior is "no number is better than a wrong number".
    """
    query_vec = query_encoder.embed_text(query_text)
    out: dict[str, float] = {}
    for c in candidates:
        stored = c.node.properties.get(embedding_property)
        if not isinstance(stored, (list, tuple)):
            continue
        if len(stored) != len(query_vec):
            continue
        try:
            out[c.node_id] = cosine_similarity(query_vec, list(stored))
        except ValueError:
            # Zero-vector candidate; treat as "no signal".
            continue
    return out


def _parse_response(text: str) -> tuple[str | None, str | None]:
    """Extract ``(node_id, reason)`` from a backend reply.

    Tolerant of extra prose — looks for a ``Top match: X`` line first
    and a ``Reason: Y`` line second. Returns ``(None, None)`` when no
    match line is present.
    """
    pick: str | None = None
    reason: str | None = None
    for raw in text.splitlines():
        m = _TOP_MATCH_LINE.match(raw)
        if m is not None and pick is None:
            pick = m.group(1).strip().strip(".,;:'\"`")
            continue
        if reason is None:
            m2 = re.match(r"^\s*reason\s*[:\-]\s*(.+?)\s*$", raw, re.IGNORECASE)
            if m2 is not None:
                reason = m2.group(1).strip()
    return pick, reason


def llm_resolve_goal(
    graph: TopologyGraph,
    text: str,
    backend: LLMBackend,
    *,
    top_k: int = 5,
    candidates: Iterable[TopologyNode] | None = None,
    system: str | None = None,
    query_encoder: EncoderBackend | None = None,
    embedding_property: str = DEFAULT_EMBEDDING_PROPERTY,
) -> LLMResolveResult:
    """Resolve a free-text goal, then ask an LLM to refine the ranking.

    The deterministic :func:`resolve_goal` always runs first; the LLM
    only re-orders its top-``top_k`` results. When the model's pick is
    in the candidate pool it gets moved to position 0 with its reason
    appended to its ``reasons`` list; otherwise the deterministic
    order is preserved untouched.

    Parameters
    ----------
    graph, text, top_k, candidates:
        Forwarded to :func:`resolve_goal`. ``top_k`` controls both the
        deterministic shortlist size and what gets shown to the LLM.
    backend:
        :class:`~semantic_toponav.llm.LLMBackend` instance.
    system:
        Optional override for the system instruction.
    query_encoder:
        Optional :class:`~semantic_toponav.encoders.Backend` used to
        embed ``text`` and compute cosine similarity against any
        stored node embeddings under ``embedding_property``. When
        provided, the LLM prompt gains per-candidate
        ``embedding_score=`` fields and the returned result carries
        ``embedding_scores``. Raw vectors are never sent to the LLM —
        only the scalar scores, per the safety rule that the prompt
        carries structured retrieval context, not opaque numerics.
    embedding_property:
        Node-property key the stored embeddings are stamped under.
        Defaults to ``"embedding"`` (matches
        :func:`semantic_toponav.query.find_nodes_by_embedding`).

    Returns
    -------
    LLMResolveResult
        Final ranking + telemetry about the LLM pick + any computed
        embedding scores.
    """
    base = resolve_goal(graph, text, top_k=top_k, candidates=candidates)
    if not base:
        return LLMResolveResult(
            query=text,
            candidates=[],
            base_candidates=[],
        )

    embedding_scores: dict[str, float] = {}
    if query_encoder is not None:
        embedding_scores = _compute_embedding_scores(
            base,
            query_encoder,
            text,
            embedding_property=embedding_property,
        )

    prompt = _build_prompt(
        text, base,
        embedding_scores=embedding_scores if embedding_scores else None,
    )
    sys_msg = system if system is not None else _DEFAULT_SYSTEM
    raw = backend.generate(prompt, system=sys_msg)

    pick_id, reason = _parse_response(raw)
    base_ids = {c.node_id for c in base}
    if pick_id is None or pick_id not in base_ids:
        return LLMResolveResult(
            query=text,
            candidates=list(base),
            base_candidates=list(base),
            llm_pick=pick_id,
            llm_reason=reason,
            raw_response=raw,
            used_fallback=True,
            embedding_scores=embedding_scores,
        )

    reordered: list[GoalCandidate] = []
    picked: GoalCandidate | None = None
    for c in base:
        if c.node_id == pick_id and picked is None:
            picked = c
        else:
            reordered.append(c)
    assert picked is not None
    if reason:
        picked.reasons = list(picked.reasons) + [f"LLM: {reason}"]
    final = [picked, *reordered]

    return LLMResolveResult(
        query=text,
        candidates=final,
        base_candidates=list(base),
        llm_pick=pick_id,
        llm_reason=reason,
        raw_response=raw,
        used_fallback=False,
        embedding_scores=embedding_scores,
    )


__all__ = ["LLMResolveResult", "llm_resolve_goal"]
