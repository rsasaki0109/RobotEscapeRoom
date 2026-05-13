"""Deterministic natural-language goal resolution over a TopologyGraph.

Given a free-text query like "the second floor office" or "go to the
kitchen", return a ranked list of candidate nodes. The implementation is
intentionally a small bag-of-words scorer — no model, no fuzzy distance
metric, no synonym expansion. The intent is to provide a stable floor
under any later LLM-augmented resolver: feed an LLM these candidates
plus the user's text and let it pick / refine, but always have a
deterministic fallback that runs offline.

Scoring signals
---------------

For each candidate node:

- a query token that appears in ``node.label`` (case-insensitive,
  whole-word, after stopword removal) contributes ``+2`` and a reason
  ``"label matches 'meeting'"``.
- a query token that appears in ``node.type`` contributes ``+1`` and a
  reason ``"type matches 'elevator'"``.
- if the query contains a floor reference (``"2f"`` / ``"floor 2"`` /
  ``"second floor"`` / ``"2nd floor"`` / ``"on the third floor"``) and
  the node carries ``properties.floor == N``, that adds ``+3`` and the
  reason ``"floor 2 matches"``. A floor mismatch instead applies a
  ``-10`` penalty so other-floor nodes drop out unless nothing else
  matches at all.

Ties break by ``node.id`` lexicographically so output is fully
deterministic.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import TopologyNode

_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "any",
        "at",
        "by",
        "for",
        "from",
        "go",
        "going",
        "i",
        "in",
        "into",
        "is",
        "it",
        "let",
        "me",
        "my",
        "near",
        "of",
        "on",
        "onto",
        "or",
        "out",
        "over",
        "please",
        "take",
        "the",
        "then",
        "this",
        "to",
        "towards",
        "us",
        "want",
        "we",
        "you",
        "your",
    }
)

# Ordinal word -> integer for "first/second/third ... tenth floor" phrasing.
_ORDINAL_WORDS: dict[str, int] = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
}

_LABEL_MATCH_WEIGHT = 2.0
_TYPE_MATCH_WEIGHT = 1.0
_FLOOR_MATCH_WEIGHT = 3.0
_FLOOR_MISMATCH_PENALTY = -10.0

# Regexes for floor references. Order matters: the first one to fire
# returns the parsed floor and removes its slice from the query text so
# that subsequent token-overlap scoring doesn't double-count digits.
_FLOOR_PATTERNS: list[tuple[re.Pattern[str], int]] = [
    # "2f" / "2F" / "2 F" (followed by a non-word boundary)
    (re.compile(r"\b(\d+)\s*f\b", re.IGNORECASE), 1),
    # "floor 2"
    (re.compile(r"\bfloor\s+(\d+)\b", re.IGNORECASE), 1),
    # "2nd floor" / "3rd floor" / "10th floor"
    (re.compile(r"\b(\d+)(?:st|nd|rd|th)\s+floor\b", re.IGNORECASE), 1),
]

_ORDINAL_FLOOR_PATTERN = re.compile(
    r"\b(" + "|".join(_ORDINAL_WORDS) + r")\s+floor\b",
    re.IGNORECASE,
)


@dataclass
class GoalCandidate:
    """One candidate node returned by :func:`resolve_goal`.

    Sorted top-first by score; ``reasons`` lists the matches that
    contributed, in the order they were applied.
    """

    node_id: str
    node: TopologyNode
    score: float
    reasons: list[str] = field(default_factory=list)


def _extract_floor(text: str) -> tuple[int | None, str]:
    """Pull a floor reference out of ``text``.

    Returns ``(floor_or_None, text_with_reference_removed)``. Only the
    first matching pattern is honored; ambiguous queries that mention
    multiple floors will pick the leftmost.
    """
    for pat, group in _FLOOR_PATTERNS:
        m = pat.search(text)
        if m is not None:
            floor = int(m.group(group))
            return floor, (text[: m.start()] + " " + text[m.end() :])
    m = _ORDINAL_FLOOR_PATTERN.search(text)
    if m is not None:
        floor = _ORDINAL_WORDS[m.group(1).lower()]
        return floor, (text[: m.start()] + " " + text[m.end() :])
    return None, text


def _tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumerics, drop stopwords and digits."""
    raw = re.findall(r"[a-zA-Z]+", text.lower())
    return [t for t in raw if t and t not in _STOPWORDS]


def _node_label_tokens(node: TopologyNode) -> set[str]:
    label = node.label or ""
    return set(re.findall(r"[a-zA-Z]+", label.lower()))


def _node_type_tokens(node: TopologyNode) -> set[str]:
    return set(re.findall(r"[a-zA-Z]+", node.type.lower()))


def _floor_of(node: TopologyNode) -> int | None:
    floor = node.properties.get("floor")
    if isinstance(floor, int):
        return floor
    return None


def _score_node(
    node: TopologyNode,
    *,
    query_tokens: list[str],
    target_floor: int | None,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    if target_floor is not None:
        node_floor = _floor_of(node)
        if node_floor == target_floor:
            score += _FLOOR_MATCH_WEIGHT
            reasons.append(f"floor {target_floor} matches")
        elif node_floor is not None:
            score += _FLOOR_MISMATCH_PENALTY
            reasons.append(f"floor mismatch (wanted {target_floor}, got {node_floor})")
        # nodes without any floor property neither gain nor lose.

    label_tokens = _node_label_tokens(node)
    type_tokens = _node_type_tokens(node)
    matched_label: set[str] = set()
    matched_type: set[str] = set()
    for token in query_tokens:
        if token in label_tokens and token not in matched_label:
            score += _LABEL_MATCH_WEIGHT
            matched_label.add(token)
            reasons.append(f"label matches {token!r}")
        elif token in type_tokens and token not in matched_type:
            score += _TYPE_MATCH_WEIGHT
            matched_type.add(token)
            reasons.append(f"type matches {token!r}")

    return score, reasons


def resolve_goal(
    graph: TopologyGraph,
    text: str,
    *,
    top_k: int = 5,
    candidates: Iterable[TopologyNode] | None = None,
) -> list[GoalCandidate]:
    """Resolve free-text ``text`` to a ranked list of candidate nodes.

    Returns at most ``top_k`` entries with strictly positive scores,
    sorted by descending score and then by node id (ties broken
    deterministically). Returns an empty list when nothing matches.

    ``candidates`` lets callers restrict scoring to a pre-filtered set
    (for example, only nodes of ``type='room'``). When ``None`` every
    graph node is scored.
    """
    if top_k <= 0:
        return []

    target_floor, residual = _extract_floor(text)
    query_tokens = _tokenize(residual)
    if not query_tokens and target_floor is None:
        return []

    pool = list(candidates) if candidates is not None else list(graph.nodes())

    scored: list[GoalCandidate] = []
    for node in pool:
        score, reasons = _score_node(
            node, query_tokens=query_tokens, target_floor=target_floor
        )
        if score > 0:
            scored.append(
                GoalCandidate(
                    node_id=node.id, node=node, score=score, reasons=reasons
                )
            )

    scored.sort(key=lambda c: (-c.score, c.node_id))
    return scored[:top_k]


__all__ = ["GoalCandidate", "resolve_goal"]
