"""Export a :class:`TopologyGraph` to the Nav2 Route Server GeoJSON format.

Since 2024–25 the ROS 2 **Nav2 Route Server** plans over a predefined
navigation graph loaded from a GeoJSON file (its default
``GeoJsonGraphFileLoader``). That makes the "we are the planning tier
*above* Nav2, not a rival to it" story concrete: author / ground / repair
the semantic topology here, then hand the graph to Nav2 to execute over.

This module is the bridge. It serializes a semantic-toponav
:class:`~semantic_toponav.graph.types.TopologyGraph` into the exact
FeatureCollection the loader parses:

* **nodes** → ``Point`` features. ``properties.id`` is a stable unsigned
  integer (Nav2 ids are ``unsigned int``); the original string id, label,
  semantic ``type``, floor and any extra node properties are preserved
  under ``properties.metadata`` (where Nav2's scorers/operations read
  application fields), with the semantic ``type`` mirrored to
  ``metadata.class`` for ``SemanticScorer``. ``coordinates`` are
  ``[x, y]`` map-frame **metres** (not lon/lat).
* **edges** → ``LineString`` features with ``properties.id`` /
  ``startid`` / ``endid`` (integer node ids) and the edge ``cost`` as a
  first-class property. A **bidirectional** edge is emitted as **two
  directed features** with swapped ``startid`` / ``endid`` — Nav2 edges
  have no bidirectional flag.

Nodes must carry a pose (the Route Server needs metric coordinates);
:func:`topology_to_nav2_geojson` raises if any included node lacks one.

The format was verified against the Nav2 ``GeoJsonGraphFileLoader``
parser and the shipped ``aws_graph.geojson`` sample — see
[`docs/related_work.md`](../../docs/related_work.md) (Plan axis).
"""

from __future__ import annotations

import json
from collections.abc import Collection
from pathlib import Path
from typing import Any

from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import TopologyNode

_RESERVED_NODE_META = {"id", "frame", "metadata"}


def _node_metadata(node: TopologyNode) -> dict[str, Any]:
    """Application fields for a node, under the Nav2 ``metadata`` key."""
    meta: dict[str, Any] = {
        "node_id": node.id,
        "label": node.label,
        "class": node.type,  # SemanticScorer reads `class` from metadata
    }
    # Preserve every extra node property, but skip embeddings — large
    # vectors don't belong in a route graph file.
    for key, value in node.properties.items():
        if key == "embedding":
            continue
        meta[key] = value
    return meta


def topology_to_nav2_geojson(
    graph: TopologyGraph,
    *,
    route_frame: str = "map",
    node_ids: Collection[str] | None = None,
) -> dict[str, Any]:
    """Serialize ``graph`` as a Nav2 Route Server GeoJSON FeatureCollection.

    Parameters
    ----------
    graph:
        The topology graph to export (not mutated).
    route_frame:
        Frame written to each node's ``properties.frame`` when the node's
        pose carries no ``frame_id`` (Nav2 TF-transforms from it into its
        ``route_frame``). Defaults to ``"map"``.
    node_ids:
        Optional subset of node ids to export — e.g. a planned route — so
        the handoff can be the whole graph or just the committed path.
        Edges are included only when *both* endpoints are in the subset.
        ``None`` (default) exports the whole graph.

    Returns
    -------
    dict
        A GeoJSON ``FeatureCollection`` dict ready for :func:`json.dump`.

    Raises
    ------
    ValueError
        If any exported node lacks a pose (Nav2 needs metric coordinates),
        listing the offending node ids.
    """
    selected = (
        [n for n in graph.nodes() if n.id in set(node_ids)]
        if node_ids is not None
        else list(graph.nodes())
    )
    missing = [n.id for n in selected if n.pose is None]
    if missing:
        raise ValueError(
            "cannot export to Nav2 GeoJSON: these nodes have no pose "
            f"(Nav2 needs metric coordinates): {', '.join(sorted(missing))}"
        )

    # Stable string→int id map (sorted for determinism). Nav2 ids are
    # unsigned ints; edges get a disjoint id range above the nodes so no
    # node and edge id ever collide.
    ordered_ids = sorted(n.id for n in selected)
    int_id = {sid: i for i, sid in enumerate(ordered_ids)}
    selected_set = set(int_id)

    features: list[dict[str, Any]] = []
    for node in sorted(selected, key=lambda n: n.id):
        pose = node.pose
        assert pose is not None  # guarded above
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "id": int_id[node.id],
                    "frame": pose.frame_id or route_frame,
                    "metadata": _node_metadata(node),
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [pose.x, pose.y],
                },
            }
        )

    edge_id = len(ordered_ids)  # disjoint from node ids
    for edge in graph.edges():
        if edge.source not in selected_set or edge.target not in selected_set:
            continue
        src = graph.get_node(edge.source)
        dst = graph.get_node(edge.target)
        assert src.pose is not None and dst.pose is not None
        meta = {"edge_id": edge.id, "class": edge.type, **dict(edge.properties)}
        directed = [(edge.source, edge.target, src, dst)]
        if edge.bidirectional:
            directed.append((edge.target, edge.source, dst, src))
        for a, b, na, nb in directed:
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "id": edge_id,
                        "startid": int_id[a],
                        "endid": int_id[b],
                        "cost": float(edge.cost),
                        "metadata": meta,
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [na.pose.x, na.pose.y],
                            [nb.pose.x, nb.pose.y],
                        ],
                    },
                }
            )
            edge_id += 1

    return {"type": "FeatureCollection", "features": features}


def write_nav2_geojson(
    graph: TopologyGraph,
    path: str | Path,
    *,
    route_frame: str = "map",
    node_ids: Collection[str] | None = None,
    indent: int = 2,
) -> Path:
    """Write ``graph`` to ``path`` as a Nav2 Route Server GeoJSON file.

    Returns the written :class:`~pathlib.Path`. See
    :func:`topology_to_nav2_geojson` for the arguments and the raised
    ``ValueError`` on pose-less nodes.
    """
    fc = topology_to_nav2_geojson(graph, route_frame=route_frame, node_ids=node_ids)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fc, indent=indent) + "\n", encoding="utf-8")
    return out


__all__ = ["topology_to_nav2_geojson", "write_nav2_geojson"]
