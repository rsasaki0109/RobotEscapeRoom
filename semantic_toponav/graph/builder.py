"""Fluent / chainable builder for :class:`TopologyGraph`.

Hand-writing dataclasses (``TopologyNode(...)`` / ``TopologyEdge(...)``)
is verbose for small graphs. :class:`GraphBuilder` keeps the same data
model but lets you chain ``.node(...).node(...).edge(...).build()``
and inlines a couple of ergonomic shortcuts:

- ``x=`` / ``y=`` build a ``Pose2D`` for you (with optional ``yaw`` /
  ``frame_id``); pass either ``pose=Pose2D(...)`` or ``x=`` / ``y=``,
  not both.
- ``edge()`` auto-generates an id like ``"<source>__<target>"`` if you
  don't pass one explicitly.
- ``label`` defaults to ``id`` when omitted.
"""

from __future__ import annotations

from typing import Any

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import Pose2D, TopologyEdge, TopologyNode


class GraphBuilder:
    """Chainable constructor for :class:`TopologyGraph`."""

    def __init__(self) -> None:
        self._graph = TopologyGraph()

    @classmethod
    def from_graph(cls, graph: TopologyGraph) -> GraphBuilder:
        """Wrap an existing graph and continue adding nodes/edges to it."""
        b = cls()
        b._graph = graph
        return b

    def node(
        self,
        id: str,
        *,
        type: str,
        label: str | None = None,
        pose: Pose2D | None = None,
        x: float | None = None,
        y: float | None = None,
        yaw: float = 0.0,
        frame_id: str = "map",
        properties: dict[str, Any] | None = None,
    ) -> GraphBuilder:
        """Add a node and return ``self`` so calls can be chained."""
        if pose is not None and (x is not None or y is not None):
            raise ValueError(
                "node(): pass either `pose=Pose2D(...)` or `x=`/`y=`, not both"
            )
        if pose is None and (x is not None or y is not None):
            if x is None or y is None:
                raise ValueError("node(): `x` and `y` must be provided together")
            pose = Pose2D(x=float(x), y=float(y), yaw=float(yaw), frame_id=frame_id)
        self._graph.add_node(
            TopologyNode(
                id=id,
                label=label if label is not None else id,
                type=type,
                pose=pose,
                properties=dict(properties or {}),
            )
        )
        return self

    def edge(
        self,
        source: str,
        target: str,
        *,
        type: str,
        id: str | None = None,
        cost: float = 1.0,
        bidirectional: bool = True,
        properties: dict[str, Any] | None = None,
    ) -> GraphBuilder:
        """Add an edge and return ``self``.

        ``id`` defaults to ``"<source>__<target>"`` when omitted.
        """
        edge_id = id if id is not None else f"{source}__{target}"
        self._graph.add_edge(
            TopologyEdge(
                id=edge_id,
                source=source,
                target=target,
                type=type,
                cost=cost,
                bidirectional=bidirectional,
                properties=dict(properties or {}),
            )
        )
        return self

    def connect(
        self,
        *node_ids: str,
        type: str = "traversable",
        cost: float = 1.0,
        bidirectional: bool = True,
    ) -> GraphBuilder:
        """Chain edges through ``node_ids[0] -> node_ids[1] -> ...``.

        Useful for laying down a corridor in one call::

            (GraphBuilder()
                .node("a", type="entrance", x=0, y=0)
                .node("b", type="corridor", x=1, y=0)
                .node("c", type="room",     x=2, y=0)
                .connect("a", "b", "c"))
        """
        if len(node_ids) < 2:
            raise ValueError("connect() needs at least two node ids")
        for src, tgt in zip(node_ids, node_ids[1:], strict=False):
            self.edge(src, tgt, type=type, cost=cost, bidirectional=bidirectional)
        return self

    def build(self) -> TopologyGraph:
        """Return the constructed :class:`TopologyGraph`.

        The same builder instance may be re-used: subsequent calls return
        the *same* underlying graph.
        """
        return self._graph
