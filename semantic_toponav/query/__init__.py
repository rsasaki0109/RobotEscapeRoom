"""Semantic queries over a TopologyGraph.

These helpers are designed for natural-language-style intents like
"the nearest meeting room" or "any elevator on floor 2". They return
plain ``TopologyNode`` / ``TopologyNode + path`` results — no LLM, no
fuzzy matching beyond simple substring search.
"""

from semantic_toponav.query.clarification import (
    AmbiguousGoalError,
    ClarificationAnswer,
    ClarificationQuestion,
    DialogSession,
    DialogTurn,
)
from semantic_toponav.query.embedding import (
    cosine_similarity,
    find_nodes_by_embedding,
    nearest_node_by_embedding,
)
from semantic_toponav.query.find import (
    NoMatchError,
    find_nodes,
    nearest_node_by_graph_distance,
    nearest_node_by_pose,
)
from semantic_toponav.query.llm_resolve import LLMResolveResult, llm_resolve_goal
from semantic_toponav.query.resolve import GoalCandidate, resolve_goal

__all__ = [
    "AmbiguousGoalError",
    "ClarificationAnswer",
    "ClarificationQuestion",
    "DialogSession",
    "DialogTurn",
    "GoalCandidate",
    "LLMResolveResult",
    "NoMatchError",
    "cosine_similarity",
    "find_nodes",
    "find_nodes_by_embedding",
    "llm_resolve_goal",
    "nearest_node_by_embedding",
    "nearest_node_by_graph_distance",
    "nearest_node_by_pose",
    "resolve_goal",
]
