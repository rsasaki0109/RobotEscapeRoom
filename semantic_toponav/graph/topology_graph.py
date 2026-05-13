"""TopologyGraph: a small, explicit semantic topology graph."""

from __future__ import annotations

from collections.abc import Iterable

from semantic_toponav.graph.types import (
    GraphValidationError,
    TopologyEdge,
    TopologyNode,
)


class TopologyGraph:
    """A semantic topology graph with explicit nodes and edges.

    Designed to be small and direct. No abstract graph interface; no
    third-party graph library. Validation surfaces user mistakes early.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, TopologyNode] = {}
        self._edges: dict[str, TopologyEdge] = {}
        self._adjacency: dict[str, list[str]] = {}

    def add_node(self, node: TopologyNode) -> None:
        if node.id in self._nodes:
            raise GraphValidationError(f"duplicate node id: {node.id!r}")
        self._nodes[node.id] = node
        self._adjacency.setdefault(node.id, [])

    def add_edge(self, edge: TopologyEdge) -> None:
        if edge.id in self._edges:
            raise GraphValidationError(f"duplicate edge id: {edge.id!r}")
        if edge.source not in self._nodes:
            raise GraphValidationError(
                f"edge {edge.id!r} references missing source node {edge.source!r}"
            )
        if edge.target not in self._nodes:
            raise GraphValidationError(
                f"edge {edge.id!r} references missing target node {edge.target!r}"
            )
        if edge.cost < 0:
            raise GraphValidationError(
                f"edge {edge.id!r} has negative cost {edge.cost}"
            )
        self._edges[edge.id] = edge
        self._adjacency[edge.source].append(edge.id)
        if edge.bidirectional:
            self._adjacency[edge.target].append(edge.id)

    def remove_node(self, node_id: str) -> list[str]:
        """Remove a node and all of its incident edges.

        Returns the list of edge IDs that were removed alongside the node.
        Raises ``GraphValidationError`` if the node does not exist.
        """
        if node_id not in self._nodes:
            raise GraphValidationError(f"unknown node id: {node_id!r}")
        incident = [
            eid
            for eid, e in self._edges.items()
            if e.source == node_id or e.target == node_id
        ]
        for eid in incident:
            self.remove_edge(eid)
        del self._nodes[node_id]
        del self._adjacency[node_id]
        return incident

    def remove_edge(self, edge_id: str) -> None:
        if edge_id not in self._edges:
            raise GraphValidationError(f"unknown edge id: {edge_id!r}")
        edge = self._edges[edge_id]
        adj_src = self._adjacency.get(edge.source)
        if adj_src is not None and edge_id in adj_src:
            adj_src.remove(edge_id)
        if edge.bidirectional:
            adj_tgt = self._adjacency.get(edge.target)
            if adj_tgt is not None and edge_id in adj_tgt:
                adj_tgt.remove(edge_id)
        del self._edges[edge_id]

    def has_node(self, node_id: str) -> bool:
        return node_id in self._nodes

    def has_edge(self, edge_id: str) -> bool:
        return edge_id in self._edges

    def get_node(self, node_id: str) -> TopologyNode:
        if node_id not in self._nodes:
            raise KeyError(f"unknown node id: {node_id!r}")
        return self._nodes[node_id]

    def get_edge(self, edge_id: str) -> TopologyEdge:
        if edge_id not in self._edges:
            raise KeyError(f"unknown edge id: {edge_id!r}")
        return self._edges[edge_id]

    def neighbors(self, node_id: str) -> list[TopologyEdge]:
        """Return outgoing edges from ``node_id`` (respecting direction).

        For bidirectional edges, both endpoints see the edge. For one-way
        (``bidirectional=False``) edges, only the source sees it.
        """
        if node_id not in self._nodes:
            raise KeyError(f"unknown node id: {node_id!r}")
        edges: list[TopologyEdge] = []
        for eid in self._adjacency[node_id]:
            edge = self._edges[eid]
            if edge.source == node_id or edge.bidirectional:
                edges.append(edge)
        return edges

    def other_end(self, edge: TopologyEdge, node_id: str) -> str:
        """Given an edge and one of its endpoints, return the other endpoint."""
        if edge.source == node_id:
            return edge.target
        if edge.target == node_id and edge.bidirectional:
            return edge.source
        raise GraphValidationError(
            f"node {node_id!r} is not a traversable endpoint of edge {edge.id!r}"
        )

    def node_ids(self) -> list[str]:
        return list(self._nodes.keys())

    def edge_ids(self) -> list[str]:
        return list(self._edges.keys())

    def nodes(self) -> Iterable[TopologyNode]:
        return self._nodes.values()

    def edges(self) -> Iterable[TopologyEdge]:
        return self._edges.values()

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, node_id: object) -> bool:
        return isinstance(node_id, str) and node_id in self._nodes

    def validate(self) -> None:
        """Run a full consistency check.

        Most invariants are checked on insert, but this method re-verifies
        them for graphs that may have been mutated by other means.
        """
        seen_node_ids: set[str] = set()
        for node in self._nodes.values():
            if node.id in seen_node_ids:
                raise GraphValidationError(f"duplicate node id: {node.id!r}")
            seen_node_ids.add(node.id)

        seen_edge_ids: set[str] = set()
        for edge in self._edges.values():
            if edge.id in seen_edge_ids:
                raise GraphValidationError(f"duplicate edge id: {edge.id!r}")
            seen_edge_ids.add(edge.id)
            if edge.source not in self._nodes:
                raise GraphValidationError(
                    f"edge {edge.id!r} references missing source node {edge.source!r}"
                )
            if edge.target not in self._nodes:
                raise GraphValidationError(
                    f"edge {edge.id!r} references missing target node {edge.target!r}"
                )
            if edge.cost < 0:
                raise GraphValidationError(
                    f"edge {edge.id!r} has negative cost {edge.cost}"
                )
