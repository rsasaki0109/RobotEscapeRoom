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
from semantic_toponav.query.clarification import (
    AmbiguousGoalError,
    ClarificationAnswer,
    ClarificationQuestion,
)
from semantic_toponav.query.embedding import (
    DEFAULT_EMBEDDING_PROPERTY,
    cosine_similarity,
)
from semantic_toponav.query.resolve import GoalCandidate, resolve_goal

_TOP_MATCH_LINE = re.compile(
    r"^\s*(?:top\s+match|best|chosen|pick|answer)\s*[:\-]\s*(\S+)\s*$",
    re.IGNORECASE,
)

_CLARIFY_LINE = re.compile(
    r"^\s*clarify\s*[:\-]\s*(.+?)\s*$",
    re.IGNORECASE,
)

_DEFAULT_SYSTEM = (
    "You resolve free-text navigation goals to a specific node id from "
    "a pre-filtered candidate list. You MUST pick a node id from the "
    "candidate list — never invent one. Reply with exactly two lines: "
    "first `Top match: <node_id>`, then `Reason: <one-sentence "
    "justification>`. If the query is too ambiguous between two or more "
    "candidates to pick confidently, reply with a single line "
    "`Clarify: <one short question for the user>` instead."
)

# Abstention-aware variant. The default prompt only licenses a `Clarify:`
# reply when the candidates are mutually *ambiguous*; it still pressures the
# model to pick *something*. That is exactly wrong for the token-leak failure
# mode the abstention benchmark targets: the deterministic floor matches a
# stray token (`room`, `kitchen`) and forwards an off-topic candidate, so the
# model is handed a pool where the *right* answer is "none of these". This
# prompt adds that escape hatch — abstain (via `Clarify:`) when no candidate
# genuinely denotes the requested place, or when the query presupposes a
# floor / attribute none of the candidates satisfy. The structural no-invent
# guarantee is unchanged; this only changes *when the model is allowed to
# decline*. See :mod:`semantic_toponav.eval.abstention`.
ABSTAIN_AWARE_SYSTEM = (
    "You resolve free-text navigation goals to a specific node id from a "
    "pre-filtered candidate list. The list was produced by a keyword matcher "
    "that can over-fire on a generic word (a candidate may appear only "
    "because it shares the token `room` or `office`, not because it is the "
    "place asked for). You MUST NOT invent a node id. Reply with exactly two "
    "lines — `Top match: <node_id>` then `Reason: <one sentence>` — ONLY when "
    "some candidate genuinely denotes the requested place. If NONE of the "
    "candidates actually matches — the query names a place type, floor, or "
    "attribute that no candidate satisfies (e.g. a `server room` when only a "
    "meeting room is offered, or a `basement` floor that does not exist) — do "
    "NOT force a pick: reply with a single line `Clarify: <one short "
    "question>` instead. Abstaining is the correct answer when nothing fits."
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
    clarification:
        Populated when the resolver concluded the query was too
        ambiguous to pick confidently — either because the top-1 and
        top-2 deterministic scores were within ``ambiguity_threshold``
        of each other, or because the LLM emitted a ``Clarify:``
        line instead of a ``Top match:`` line. ``None`` otherwise.
        Callers handle a multi-turn dialog by detecting this field,
        asking the user, then re-calling :func:`llm_resolve_goal`
        with the user's reply wrapped in a
        :class:`ClarificationAnswer`.
    """

    query: str
    candidates: list[GoalCandidate]
    base_candidates: list[GoalCandidate]
    llm_pick: str | None = None
    llm_reason: str | None = None
    raw_response: str = ""
    used_fallback: bool = False
    embedding_scores: dict[str, float] = field(default_factory=dict)
    clarification: ClarificationQuestion | None = None

    def to_dict(self) -> dict[str, object]:
        """JSON-serializable form. v1-stable — see ``schemas/resolve_trace_v1.schema.json``."""
        return {
            "query": self.query,
            "candidates": [_candidate_to_dict(c) for c in self.candidates],
            "base_candidates": [_candidate_to_dict(c) for c in self.base_candidates],
            "llm_pick": self.llm_pick,
            "llm_reason": self.llm_reason,
            "raw_response": self.raw_response,
            "used_fallback": bool(self.used_fallback),
            "embedding_scores": {k: float(v) for k, v in self.embedding_scores.items()},
            "clarification": (
                _clarification_to_dict(self.clarification)
                if self.clarification is not None
                else None
            ),
        }


def _candidate_to_dict(c: GoalCandidate) -> dict[str, object]:
    """Render a :class:`GoalCandidate` for the v1 ResolveTrace wire format."""
    return {
        "node_id": c.node_id,
        "score": float(c.score),
        "reasons": list(c.reasons),
    }


def _clarification_to_dict(q: ClarificationQuestion) -> dict[str, object]:
    return {
        "question": q.question,
        "candidates": [_candidate_to_dict(c) for c in q.candidates],
    }


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


def _parse_response(
    text: str,
) -> tuple[str | None, str | None, str | None]:
    """Extract ``(node_id, reason, clarify_question)`` from a backend reply.

    Tolerant of extra prose — looks for a ``Top match: X`` line first,
    a ``Reason: Y`` line second, and a ``Clarify: Z`` line as the
    alternative ambiguity signal. A reply that contains both
    ``Top match:`` and ``Clarify:`` is treated as a pick (the model
    answered the question and asked a follow-up); the clarify text is
    reported alongside.
    """
    pick: str | None = None
    reason: str | None = None
    clarify: str | None = None
    for raw in text.splitlines():
        if pick is None:
            m = _TOP_MATCH_LINE.match(raw)
            if m is not None:
                pick = m.group(1).strip().strip(".,;:'\"`")
                continue
        if clarify is None:
            m_clarify = _CLARIFY_LINE.match(raw)
            if m_clarify is not None:
                clarify = m_clarify.group(1).strip()
                continue
        if reason is None:
            m2 = re.match(r"^\s*reason\s*[:\-]\s*(.+?)\s*$", raw, re.IGNORECASE)
            if m2 is not None:
                reason = m2.group(1).strip()
    return pick, reason, clarify


def _detect_deterministic_ambiguity(
    candidates: list[GoalCandidate], *, threshold: float
) -> ClarificationQuestion | None:
    """Return a :class:`ClarificationQuestion` when the top candidates
    are within ``threshold`` of each other on deterministic score.

    Looks at the score delta between the top-1 and top-2 entries.
    When the delta is small the resolver can't tell which the user
    meant. Returns ``None`` for an empty or single-candidate list
    (nothing to be ambiguous about) and when the gap is wider than
    the threshold.
    """
    if len(candidates) < 2:
        return None
    gap = candidates[0].score - candidates[1].score
    if gap > threshold:
        return None
    # Group the leading tier — all candidates within `threshold` of the
    # top score. That's what the user has to disambiguate between, not
    # just the top-2.
    top_score = candidates[0].score
    tier = tuple(
        c for c in candidates if (top_score - c.score) <= threshold
    )
    if len(tier) < 2:
        return None
    ids = ", ".join(c.node_id for c in tier)
    question = (
        f"The query matched {len(tier)} candidates with near-equal "
        f"deterministic scores: {ids}. Which one did you mean?"
    )
    return ClarificationQuestion(question=question, candidates=tier)


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
    clarification: ClarificationAnswer | None = None,
    ambiguity_threshold: float = 0.5,
    raise_on_ambiguous: bool = False,
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
    clarification:
        Optional answer to a previous turn's
        :class:`ClarificationQuestion`. When ``chosen_id`` is set and
        appears in the current candidate pool, the resolver narrows
        the pool to that single candidate before consulting the LLM
        (so the LLM either confirms with a Reason: line or the call
        short-circuits). When ``free_text`` is set, it is appended to
        ``text`` before re-running :func:`resolve_goal`. Out-of-pool
        ``chosen_id`` values are silently ignored — the safety
        property "no invented node ids" still holds.
    ambiguity_threshold:
        Maximum allowed gap between the top-1 and top-2 deterministic
        scores before the resolver decides it's ambiguous. Defaults
        to ``0.5`` (matches the bag-of-words scorer's token weight
        unit). Set to ``0.0`` for "only flag exact ties" or to a
        large number to disable deterministic ambiguity detection.
    raise_on_ambiguous:
        When ``True``, raise :class:`AmbiguousGoalError` if the
        resolver emits a clarification. Useful for synchronous APIs
        that prefer to surface ambiguity through the exception
        channel. Defaults to ``False`` (return the question in
        :attr:`LLMResolveResult.clarification`).

    Returns
    -------
    LLMResolveResult
        Final ranking + telemetry about the LLM pick + any computed
        embedding scores + an optional :class:`ClarificationQuestion`
        when ambiguity was detected.
    """
    # Thread any `free_text` clarification into the query *first*, so
    # the resolver gets a chance to reuse the disambiguated phrasing
    # when ranking and the LLM sees the enriched prompt.
    effective_text = text
    if clarification is not None and clarification.free_text:
        effective_text = f"{text} ({clarification.free_text})"

    base = resolve_goal(graph, effective_text, top_k=top_k, candidates=candidates)
    if not base:
        return LLMResolveResult(
            query=effective_text,
            candidates=[],
            base_candidates=[],
        )

    # If the caller pinned a specific candidate via clarification.chosen_id,
    # narrow the pool to that candidate. Out-of-pool ids are ignored
    # so the safety property holds (no caller-supplied invention).
    base_ids = {c.node_id for c in base}
    if clarification is not None and clarification.chosen_id in base_ids:
        base = [c for c in base if c.node_id == clarification.chosen_id]
        base_ids = {c.node_id for c in base}

    embedding_scores: dict[str, float] = {}
    if query_encoder is not None:
        embedding_scores = _compute_embedding_scores(
            base,
            query_encoder,
            effective_text,
            embedding_property=embedding_property,
        )

    prompt = _build_prompt(
        effective_text, base,
        embedding_scores=embedding_scores if embedding_scores else None,
    )
    sys_msg = system if system is not None else _DEFAULT_SYSTEM
    raw = backend.generate(prompt, system=sys_msg)

    pick_id, reason, clarify_text = _parse_response(raw)

    # LLM-driven ambiguity: model emitted Clarify: ... instead of a pick.
    if pick_id is None and clarify_text:
        clarification_q = ClarificationQuestion(
            question=clarify_text,
            candidates=tuple(base),
        )
        result = LLMResolveResult(
            query=effective_text,
            candidates=list(base),
            base_candidates=list(base),
            llm_pick=None,
            llm_reason=reason,
            raw_response=raw,
            used_fallback=False,
            embedding_scores=embedding_scores,
            clarification=clarification_q,
        )
        if raise_on_ambiguous:
            raise AmbiguousGoalError(clarification_q)
        return result

    # Out-of-pool / unparseable LLM pick → fall back to deterministic.
    if pick_id is None or pick_id not in base_ids:
        # Even on fallback, surface deterministic-tier ambiguity so
        # callers can ask a follow-up before guessing.
        det_question = _detect_deterministic_ambiguity(
            base, threshold=ambiguity_threshold
        )
        if det_question is not None and raise_on_ambiguous:
            raise AmbiguousGoalError(det_question)
        return LLMResolveResult(
            query=effective_text,
            candidates=list(base),
            base_candidates=list(base),
            llm_pick=pick_id,
            llm_reason=reason,
            raw_response=raw,
            used_fallback=True,
            embedding_scores=embedding_scores,
            clarification=det_question,
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

    # When the LLM picked confidently, deterministic ambiguity is still
    # surfaced for telemetry but not raised — the LLM made a call.
    det_question = _detect_deterministic_ambiguity(
        base, threshold=ambiguity_threshold
    )

    return LLMResolveResult(
        query=effective_text,
        candidates=final,
        base_candidates=list(base),
        llm_pick=pick_id,
        llm_reason=reason,
        raw_response=raw,
        used_fallback=False,
        embedding_scores=embedding_scores,
        clarification=det_question,
    )


__all__ = ["ABSTAIN_AWARE_SYSTEM", "LLMResolveResult", "llm_resolve_goal"]
