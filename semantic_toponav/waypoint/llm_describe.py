"""LLM-augmented path narration on top of :func:`describe_path`.

:func:`semantic_toponav.waypoint.describe_path` produces a fully
deterministic, edge-aware list of imperative steps. That output is
useful as-is, but it is intentionally rigid ("Proceed through Main
Corridor", "Take the elevator from X to Y"). When the consumer is a
person reading the instructions out loud (or another agent generating
spoken guidance), a small rewrite layer can make the same plan flow
much better.

:func:`llm_describe_path` is that rewrite layer. It:

1. Calls :func:`path_to_steps` to get the deterministic floor.
2. Builds a structured prompt that includes per-step context (node
   label, type, floor, edge metadata) so the LLM has something concrete
   to rewrite, not just opaque imperatives.
3. Asks the configured :class:`~semantic_toponav.llm.LLMBackend` to
   rewrite the steps into natural-sounding prose, preserving the
   numbered-step structure so we can parse the result back into a
   list.
4. Falls back to the deterministic output if the LLM response can't be
   parsed back into the expected step count — the LLM is never allowed
   to *lose* a step, only to rephrase one.

The deterministic floor is always preserved on :class:`LLMDescribeResult`
so callers can compare the rewrite against the original, or fall back
to it if they want to.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.llm.backends import LLMBackend
from semantic_toponav.waypoint.describe import PathStep, path_to_steps

_NUMBERED_LINE = re.compile(r"^\s*(\d+)[\.\)]\s+(.+?)\s*$")

_DEFAULT_SYSTEM = (
    "You are a navigation-instruction rewriter. You will be given a "
    "numbered list of deterministic robot-navigation steps plus context "
    "about the nodes and edges they refer to. Rewrite each step in "
    "natural, friendly prose for a human reader, preserving the exact "
    "numbering, the exact step count, and all node references. Do not "
    "merge, split, reorder, or invent steps."
)


@dataclass
class LLMDescribeResult:
    """Outcome of :func:`llm_describe_path`.

    Attributes
    ----------
    steps:
        Either the rewritten step strings (when the LLM produced one
        line per deterministic step) or the deterministic step text as
        a fallback. The numbering on each entry always matches the
        deterministic order.
    raw_response:
        The unmodified backend reply, in case the caller wants to log
        it or display the full prose.
    base_steps:
        The deterministic :class:`PathStep` list this rewrite is
        derived from. Always present.
    used_fallback:
        ``True`` when the response could not be parsed back into one
        line per step and the deterministic text was used instead.
    """

    steps: list[str] = field(default_factory=list)
    raw_response: str = ""
    base_steps: list[PathStep] = field(default_factory=list)
    used_fallback: bool = False


def _format_step_context(graph: TopologyGraph, step: PathStep) -> str:
    """Render one step + its node/edge context into a compact prompt line."""
    parts: list[str] = [f"{step.index}. {step.text}"]
    detail_bits: list[str] = []
    if step.node_id is not None:
        node = graph.get_node(step.node_id)
        if node.label:
            detail_bits.append(f"label='{node.label}'")
        detail_bits.append(f"type={node.type}")
        floor = node.properties.get("floor")
        if isinstance(floor, int):
            detail_bits.append(f"floor={floor}")
    if step.edge_id is not None:
        edge = graph.get_edge(step.edge_id)
        detail_bits.append(f"edge_type={edge.type}")
    if detail_bits:
        parts.append(f"   ({', '.join(detail_bits)})")
    return "\n".join(parts)


def _build_prompt(
    graph: TopologyGraph,
    steps: Sequence[PathStep],
    *,
    style: str | None,
) -> str:
    lines = [
        "Rewrite the following navigation steps into natural prose for "
        "a human reader. Keep exactly the same numbering and step count.",
        "",
    ]
    if style:
        lines.append(f"Target style: {style}.")
        lines.append("")
    lines.append("Original steps with context:")
    for step in steps:
        lines.append(_format_step_context(graph, step))
    lines.append("")
    lines.append(
        "Respond with the rewritten steps as one numbered line per step, "
        "in the same order, using the format `N. <text>` (no extra lines, "
        "no preamble, no closing remarks)."
    )
    return "\n".join(lines)


def _parse_numbered_lines(text: str, expected: int) -> list[str] | None:
    """Parse ``N. <text>`` lines out of the response.

    Returns ``None`` when the response does not contain exactly
    ``expected`` such lines — the caller falls back to deterministic
    text in that case so a malformed reply never loses or duplicates
    a step.
    """
    out: list[str] = []
    seen_indices: list[int] = []
    for raw in text.splitlines():
        m = _NUMBERED_LINE.match(raw)
        if not m:
            continue
        seen_indices.append(int(m.group(1)))
        out.append(m.group(2))
    if len(out) != expected:
        return None
    if seen_indices != list(range(1, expected + 1)):
        return None
    return out


def llm_describe_path(
    graph: TopologyGraph,
    path: Sequence[str],
    backend: LLMBackend,
    *,
    style: str | None = None,
    include_floor_changes: bool = True,
    system: str | None = None,
) -> LLMDescribeResult:
    """Rewrite a deterministic path narration via an LLM backend.

    Parameters
    ----------
    graph, path:
        Same as :func:`describe_path` — the path is a sequence of node
        ids, and ``graph`` is consulted for node labels / types and
        edge metadata.
    backend:
        Any object satisfying :class:`LLMBackend`. Use
        :class:`~semantic_toponav.llm.EchoBackend` for tests and
        offline demos; use :class:`~semantic_toponav.llm.AnthropicBackend`
        (or any other implementation of the protocol) for real
        rewrites.
    style:
        Optional natural-language style hint sent to the model
        ("concise", "friendly", "verbose", ...). Pure prompt sugar —
        the model decides what it means.
    include_floor_changes:
        Forwarded to :func:`path_to_steps`. Disable to skip the
        synthetic "Floor change: 1 -> 2" call-outs.
    system:
        Optional override for the system instruction. The default
        instruction tells the model not to merge / split / reorder
        steps; pass a custom one only if you intentionally want
        different behavior.

    Returns
    -------
    LLMDescribeResult
        ``steps`` holds the rewritten lines (or deterministic fallback
        when the reply was unparseable); ``raw_response`` carries the
        unmodified backend output; ``base_steps`` is the deterministic
        floor; ``used_fallback`` records whether the rewrite was
        accepted.
    """
    base = path_to_steps(graph, path, include_floor_changes=include_floor_changes)
    if not base:
        return LLMDescribeResult(steps=[], raw_response="", base_steps=[])

    prompt = _build_prompt(graph, base, style=style)
    sys_msg = system if system is not None else _DEFAULT_SYSTEM
    raw = backend.generate(prompt, system=sys_msg)

    parsed = _parse_numbered_lines(raw, expected=len(base))
    if parsed is None:
        fallback = [step.text for step in base]
        return LLMDescribeResult(
            steps=fallback,
            raw_response=raw,
            base_steps=base,
            used_fallback=True,
        )

    return LLMDescribeResult(
        steps=parsed,
        raw_response=raw,
        base_steps=base,
        used_fallback=False,
    )


__all__ = ["LLMDescribeResult", "llm_describe_path"]
