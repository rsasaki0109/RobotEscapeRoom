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
from dataclasses import dataclass

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import TopologyNode
from semantic_toponav.llm.backends import LLMBackend
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
    """

    query: str
    candidates: list[GoalCandidate]
    base_candidates: list[GoalCandidate]
    llm_pick: str | None = None
    llm_reason: str | None = None
    raw_response: str = ""
    used_fallback: bool = False


def _format_candidate_block(candidates: list[GoalCandidate]) -> str:
    lines: list[str] = []
    for c in candidates:
        node = c.node
        floor = node.properties.get("floor")
        floor_part = f", floor={floor}" if isinstance(floor, int) else ""
        lines.append(
            f"- {c.node_id}: label={node.label!r}, type={node.type}"
            f"{floor_part} (score={c.score:g})"
        )
    return "\n".join(lines)


def _build_prompt(query: str, candidates: list[GoalCandidate]) -> str:
    lines = [
        f"User query: {query}",
        "",
        "Candidate nodes (you MUST pick one of these node ids):",
        _format_candidate_block(candidates),
        "",
        "Reply with exactly:",
        "Top match: <node_id>",
        "Reason: <one short sentence>",
    ]
    return "\n".join(lines)


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

    Returns
    -------
    LLMResolveResult
        Final ranking + telemetry about the LLM pick.
    """
    base = resolve_goal(graph, text, top_k=top_k, candidates=candidates)
    if not base:
        return LLMResolveResult(
            query=text,
            candidates=[],
            base_candidates=[],
        )

    prompt = _build_prompt(text, base)
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
    )


__all__ = ["LLMResolveResult", "llm_resolve_goal"]
