"""Visual topological navigation: close the perception → plan → progress loop.

Where :func:`semantic_toponav.query.localize_by_image` answers *"which
place do I see right now?"*, this module answers the two navigation
questions that bracket it:

* :func:`plan_visual_route` — *"given a goal, how do I get there from
  what I currently see?"* It localizes a start frame to a node, A*-plans
  to the goal node, and converts the route into semantic waypoints. This
  is the same composition LM-Nav makes (ground the start with a
  vision-language model, then search the topological graph), expressed
  with the pieces this repo already ships.
* :class:`VisualRouteFollower` — *"how far along the plan am I now?"* It
  re-localizes a stream of camera frames against the graph and maps each
  fix onto a monotonic position along the committed route — the
  perception side of a route-following loop. The actual node-to-node
  locomotion stays out of this repo by design (decision D-16): a learned
  image-goal policy (ViNT / NoMaD / ViNG) or Nav2 owns *how to move*;
  this follower owns *where on the plan the robot has reached*.

Everything here is a thin, honest composition of existing helpers
(:func:`localize_by_image`, :func:`plan_astar`,
:func:`path_to_semantic_waypoints`), so the module stays dependency-free
at import time. The encoder is pluggable exactly as in
:mod:`semantic_toponav.query.visual_localization`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from semantic_toponav.encoders.backends import Backend
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import TopologyEdge, TopologyNode
from semantic_toponav.planner.astar import plan_astar
from semantic_toponav.query.embedding import DEFAULT_EMBEDDING_PROPERTY
from semantic_toponav.query.visual_localization import (
    VisualLocalization,
    localize_by_image,
)
from semantic_toponav.waypoint.semantic_waypoint import (
    SemanticWaypoint,
    path_to_semantic_waypoints,
)


@dataclass
class VisualRoute:
    """A route planned from an image-grounded start to a goal node.

    Attributes
    ----------
    start:
        The :class:`VisualLocalization` that grounded the start frame.
        ``start.node`` is the route's first node.
    route:
        Node-id path from the grounded start to ``goal`` (inclusive of
        both ends), as returned by :func:`plan_astar`.
    waypoints:
        The semantic-waypoint expansion of ``route``.
    """

    start: VisualLocalization
    route: list[str]
    waypoints: list[SemanticWaypoint]

    @property
    def goal(self) -> str:
        """The goal node id (the last node on the route)."""
        return self.route[-1]


@dataclass
class RouteProgress:
    """Where the robot is along a planned route, from one localized frame.

    Attributes
    ----------
    localized:
        The raw :func:`localize_by_image` result for this frame — the
        best-matching node and its cosine score, regardless of whether
        that node lies on the route.
    index:
        The robot's position along ``route`` as a 0-based index, after
        applying this frame. Monotonically non-decreasing across
        :meth:`VisualRouteFollower.update` calls.
    current_node:
        ``route[index]`` — the route node the robot is considered to be
        at.
    on_route:
        Whether ``localized.node`` is itself a node on the route.
    advanced:
        Whether ``index`` increased relative to the previous update.
    reached_goal:
        Whether ``index`` now points at the final route node.
    remaining:
        The node ids still ahead, ``route[index + 1:]``.
    """

    localized: VisualLocalization
    index: int
    current_node: TopologyNode
    on_route: bool
    advanced: bool
    reached_goal: bool
    remaining: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        """Cosine similarity of the localized frame (``localized.score``)."""
        return self.localized.score


def plan_visual_route(
    graph: TopologyGraph,
    start_image: Any,
    goal_id: str,
    backend: Backend,
    *,
    cost_fn: Callable[[TopologyEdge], float] | None = None,
    heuristic_fn: Callable[[TopologyGraph, str, str], float] | None = None,
    top_k: int = 5,
    embedding_property: str = DEFAULT_EMBEDDING_PROPERTY,
    neighbor_weight: float = 0.0,
    neighbor_hops: int = 1,
    type: str | None = None,
    label_contains: str | None = None,
    label_equals: str | None = None,
    properties: dict[str, Any] | None = None,
) -> VisualRoute:
    """Ground a start frame to a node, then plan a route to ``goal_id``.

    The LM-Nav-style composition expressed with this repo's pieces:
    :func:`localize_by_image` grounds ``start_image`` to its most likely
    node, :func:`plan_astar` searches the topological graph from there to
    ``goal_id``, and :func:`path_to_semantic_waypoints` expands the path
    into subgoals. No locomotion happens here — the result is a *plan*.

    Parameters
    ----------
    graph:
        Topology graph whose nodes carry embeddings (not mutated).
    start_image:
        The robot's current frame. Anything ``backend.embed_image``
        accepts (array, path, ``bytes``, ``PIL.Image``).
    goal_id:
        Destination node id. Must exist in ``graph``.
    backend:
        Encoder satisfying the
        :class:`~semantic_toponav.encoders.backends.Backend` protocol —
        the same identity used to stamp the node embeddings.
    cost_fn, heuristic_fn:
        Optional planner overrides, forwarded to :func:`plan_astar`
        (e.g. ``compose_costs(prefer_elevator)``).
    top_k, embedding_property, neighbor_weight, neighbor_hops, type,
    label_contains, label_equals, properties:
        Localization controls, forwarded to :func:`localize_by_image`
        (``neighbor_weight`` / ``neighbor_hops`` enable graph-context
        re-ranking of the grounded start).

    Returns
    -------
    VisualRoute
        The grounded start, the node-id route, and its semantic
        waypoints.

    Raises
    ------
    NoMatchError
        If the start frame cannot be grounded (no candidate node carries
        an embedding under ``embedding_property``).
    PlanningError
        If ``goal_id`` is unknown or unreachable from the grounded start.
    """
    start = localize_by_image(
        graph,
        start_image,
        backend,
        top_k=top_k,
        embedding_property=embedding_property,
        neighbor_weight=neighbor_weight,
        neighbor_hops=neighbor_hops,
        type=type,
        label_contains=label_contains,
        label_equals=label_equals,
        properties=properties,
    )
    route = plan_astar(
        graph,
        start.node.id,
        goal_id,
        cost_fn=cost_fn,
        heuristic_fn=heuristic_fn,
    )
    waypoints = path_to_semantic_waypoints(graph, route)
    return VisualRoute(start=start, route=route, waypoints=waypoints)


class VisualRouteFollower:
    """Track monotonic progress along a route by re-localizing frames.

    Construct it with a committed ``route`` (e.g. ``VisualRoute.route``),
    then feed camera frames to :meth:`update` as the robot drives. Each
    update localizes the frame with :func:`localize_by_image` and maps
    the best-matching node onto a position along the route.

    Progress is **monotonic**: the tracked index only moves forward (or
    holds). This keeps a transient mis-localization to an already-passed
    place — or a glance back down a corridor — from rewinding the plan. A
    frame whose best match is *not* on the route, or scores below
    ``min_score``, is treated as "no confident fix" and holds the current
    index.

    Parameters
    ----------
    graph:
        The same graph the route was planned over (not mutated).
    route:
        Committed node-id sequence to follow. Must be non-empty; its
        nodes must exist in ``graph``.
    backend:
        Encoder matching the node embeddings' identity.
    min_score:
        Cosine floor below which a localization is ignored as a no-fix.
        Defaults to ``0.0`` (accept any on-route match).
    allow_skip:
        If ``True`` (default), localizing to a route node several hops
        ahead jumps the index straight there (the robot evidently
        skipped intermediate places). If ``False``, the index advances
        by at most one step per update, so progress can never leapfrog
        an unconfirmed waypoint.
    embedding_property:
        Node property key the embeddings live under.
    neighbor_weight, neighbor_hops:
        Graph-context aggregation controls forwarded to
        :func:`localize_by_image` on every frame (``neighbor_weight=0.0``
        = pure single-frame cosine; ``neighbor_hops`` widens the
        corroboration radius). Re-ranking each fix against its graph
        neighborhood damps perceptual-aliasing jumps mid-route.
    start_index:
        Where on the route to start tracking. Defaults to ``0`` (the
        robot begins at the route's first node).
    """

    def __init__(
        self,
        graph: TopologyGraph,
        route: list[str],
        backend: Backend,
        *,
        min_score: float = 0.0,
        allow_skip: bool = True,
        embedding_property: str = DEFAULT_EMBEDDING_PROPERTY,
        neighbor_weight: float = 0.0,
        neighbor_hops: int = 1,
        start_index: int = 0,
    ) -> None:
        if not route:
            raise ValueError("route must be non-empty")
        if not 0 <= start_index < len(route):
            raise ValueError(
                f"start_index {start_index} out of range for route of "
                f"length {len(route)}"
            )
        self.graph = graph
        self.route = list(route)
        self.backend = backend
        self.min_score = min_score
        self.allow_skip = allow_skip
        self.embedding_property = embedding_property
        self.neighbor_weight = neighbor_weight
        self.neighbor_hops = neighbor_hops
        self._index = start_index
        # First on-route occurrence of each node id — A* paths are simple
        # so this is unambiguous, but be explicit about the convention.
        self._pos: dict[str, int] = {}
        for i, node_id in enumerate(self.route):
            self._pos.setdefault(node_id, i)

    @property
    def index(self) -> int:
        """Current 0-based position along the route."""
        return self._index

    @property
    def current_node(self) -> TopologyNode:
        """The route node the robot is currently considered to be at."""
        return self.graph.get_node(self.route[self._index])

    @property
    def reached_goal(self) -> bool:
        """Whether the tracked index is at the final route node."""
        return self._index == len(self.route) - 1

    @property
    def remaining(self) -> list[str]:
        """Node ids still ahead of the current position."""
        return self.route[self._index + 1 :]

    def update(self, image: Any) -> RouteProgress:
        """Localize one frame and fold it into the route progress.

        Returns a :class:`RouteProgress` snapshot. Does not raise on a
        poor or off-route fix — it simply holds the current index and
        reports ``advanced=False`` / ``on_route=False``.

        Raises
        ------
        NoMatchError
            Only if *no* node in the graph carries an embedding to
            localize against (a setup error, not a runtime miss).
        """
        localized = localize_by_image(
            self.graph,
            image,
            self.backend,
            embedding_property=self.embedding_property,
            neighbor_weight=self.neighbor_weight,
            neighbor_hops=self.neighbor_hops,
        )
        prev = self._index
        node_id = localized.node.id
        on_route = node_id in self._pos and localized.score >= self.min_score

        if on_route:
            target = self._pos[node_id]
            if self.allow_skip:
                self._index = max(self._index, target)
            elif target == self._index + 1:
                self._index = target
            # target <= current, or a multi-hop jump with skipping off:
            # hold — progress is monotonic and one-step-at-a-time here.

        return RouteProgress(
            localized=localized,
            index=self._index,
            current_node=self.current_node,
            on_route=on_route,
            advanced=self._index > prev,
            reached_goal=self.reached_goal,
            remaining=self.remaining,
        )
