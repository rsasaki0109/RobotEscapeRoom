"""Occupancy-pipeline subcommands for the semantic-toponav CLI.

These wrap the in-tree occupancy conversion helpers so a ROS-style
``map_server`` YAML bundle can be turned into a topology graph, and an
existing graph can be enriched with door / region metadata without
hand-writing Python.

Subcommands:

* ``from-occupancy MAP --out GRAPH`` — skeletonize the occupancy bundle
  and emit a topology graph.
* ``mark-doors GRAPH MAP`` — re-type narrow-passage nodes / edges as
  doors via the distance-transform clearance heuristic.
* ``annotate-regions GRAPH MAP`` — stamp connected-component
  ``region_id`` properties onto nodes (with optional doorway pinching).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from semantic_toponav.graph.serialization import (
    GraphLoadError,
    graph_to_dict,
    load_graph,
    save_graph,
)
from semantic_toponav.graph.topology_graph import TopologyGraph
from semantic_toponav.graph.types import GraphValidationError

BACKUP_SUFFIX = ".bak"


def _backup_path(path: Path) -> Path:
    return path.with_name(path.name + BACKUP_SUFFIX)


def _create_backup(target: Path) -> Path | None:
    if not target.exists():
        return None
    backup = _backup_path(target)
    backup.write_bytes(target.read_bytes())
    return backup


def _format_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix in {".yaml", ".yml"}:
        return "yaml"
    raise GraphLoadError(
        f"unsupported file extension {suffix!r}; expected .yaml, .yml, or .json"
    )


def _serialize(graph: TopologyGraph, fmt: str) -> str:
    data = graph_to_dict(graph)
    if fmt == "json":
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def _write_or_print(
    graph: TopologyGraph,
    *,
    source: Path,
    out: str | None,
    in_place: bool,
    no_backup: bool,
) -> int:
    if out and in_place:
        print("error: pass at most one of --out and --in-place", file=sys.stderr)
        return 2

    target: Path | None = None
    if in_place:
        target = source
    elif out:
        target = Path(out)

    if target is not None:
        if not no_backup:
            backup = _create_backup(target)
            if backup is not None:
                print(f"backup: {backup}", file=sys.stderr)
        text = _serialize(graph, _format_for(target))
        target.write_text(text, encoding="utf-8")
        print(f"wrote {target}", file=sys.stderr)
    else:
        text = _serialize(graph, _format_for(source))
        sys.stdout.write(text)
    return 0


def _resolve_threshold_args(args: argparse.Namespace) -> int:
    """Return non-zero CLI exit code if both threshold knobs are set."""
    if args.clearance_threshold is not None and args.clearance_percentile is not None:
        print(
            "error: pass at most one of --clearance-threshold and "
            "--clearance-percentile",
            file=sys.stderr,
        )
        return 2
    return 0


def cmd_from_occupancy(args: argparse.Namespace) -> int:
    try:
        from semantic_toponav.conversion.map_io import MapLoadError, load_occupancy_map
        from semantic_toponav.conversion.occupancy import topology_from_occupancy
    except ImportError as exc:
        print(
            f"error: occupancy CLI requires the [map] extra ({exc}). Install with "
            f"`pip install 'semantic-toponav[map]'`",
            file=sys.stderr,
        )
        return 2

    try:
        occ = load_occupancy_map(args.map)
    except MapLoadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    graph = topology_from_occupancy(
        occ.free_mask,
        resolution=occ.resolution,
        origin=occ.origin,
        endpoint_type=args.endpoint_type,
        junction_type=args.junction_type,
        edge_type=args.edge_type,
        id_prefix=args.id_prefix,
        frame_id=args.frame_id,
    )

    out_path = Path(args.out)
    try:
        if not args.no_backup:
            backup = _create_backup(out_path)
            if backup is not None:
                print(f"backup: {backup}", file=sys.stderr)
        save_graph(graph, out_path)
    except GraphLoadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(
        f"wrote {out_path}: {len(graph.node_ids())} nodes, "
        f"{len(graph.edge_ids())} edges",
        file=sys.stderr,
    )
    return 0


def cmd_mark_doors(args: argparse.Namespace) -> int:
    code = _resolve_threshold_args(args)
    if code:
        return code

    try:
        from semantic_toponav.conversion.map_io import MapLoadError, load_occupancy_map
        from semantic_toponav.conversion.occupancy import mark_doors_by_clearance
    except ImportError as exc:
        print(
            f"error: occupancy CLI requires the [map] extra ({exc}). Install with "
            f"`pip install 'semantic-toponav[map]'`",
            file=sys.stderr,
        )
        return 2

    try:
        graph = load_graph(args.graph)
    except (GraphLoadError, GraphValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        occ = load_occupancy_map(args.map)
    except MapLoadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    kwargs: dict[str, object] = {
        "resolution": occ.resolution,
        "origin": occ.origin,
        "free_threshold": args.free_threshold,
        "mark_edges": not args.no_mark_edges,
        "edge_samples": args.edge_samples,
    }
    if args.clearance_threshold is not None:
        kwargs["clearance_threshold"] = args.clearance_threshold
    if args.clearance_percentile is not None:
        kwargs["clearance_percentile"] = args.clearance_percentile

    result = mark_doors_by_clearance(graph, occ.free_mask, **kwargs)
    print(
        f"marked {len(result.node_ids)} door node(s) and "
        f"{len(result.edge_ids)} door edge(s)",
        file=sys.stderr,
    )

    return _write_or_print(
        graph,
        source=Path(args.graph),
        out=args.out,
        in_place=args.in_place,
        no_backup=args.no_backup,
    )


def cmd_annotate_regions(args: argparse.Namespace) -> int:
    code = _resolve_threshold_args(args)
    if code:
        return code

    try:
        from semantic_toponav.conversion.map_io import MapLoadError, load_occupancy_map
        from semantic_toponav.conversion.occupancy import annotate_regions
    except ImportError as exc:
        print(
            f"error: occupancy CLI requires the [map] extra ({exc}). Install with "
            f"`pip install 'semantic-toponav[map]'`",
            file=sys.stderr,
        )
        return 2

    try:
        graph = load_graph(args.graph)
    except (GraphLoadError, GraphValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        occ = load_occupancy_map(args.map)
    except MapLoadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    kwargs: dict[str, object] = {
        "resolution": occ.resolution,
        "origin": occ.origin,
        "free_threshold": args.free_threshold,
        "min_region_area": args.min_region_area,
    }
    if args.clearance_threshold is not None:
        kwargs["clearance_threshold"] = args.clearance_threshold
    if args.clearance_percentile is not None:
        kwargs["clearance_percentile"] = args.clearance_percentile

    result = annotate_regions(graph, occ.free_mask, **kwargs)
    print(
        f"found {len(result.regions)} region(s); stamped {len(result.node_ids)} "
        f"node(s); {len(result.doorway_node_ids)} doorway node(s)",
        file=sys.stderr,
    )
    if args.show_regions and result.regions:
        for rid, info in sorted(result.regions.items()):
            cx, cy = info.centroid_world
            print(
                f"  region {rid}: area={info.area_cells} cells "
                f"({info.area_m2:.2f} m^2) centroid=({cx:.2f}, {cy:.2f})",
                file=sys.stderr,
            )

    return _write_or_print(
        graph,
        source=Path(args.graph),
        out=args.out,
        in_place=args.in_place,
        no_backup=args.no_backup,
    )


def _add_threshold_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--free-threshold",
        type=float,
        default=0.5,
        help="cells with value >= FREE are treated as traversable (default: 0.5)",
    )
    p.add_argument(
        "--clearance-threshold",
        type=float,
        metavar="METERS",
        help="explicit clearance threshold in meters",
    )
    p.add_argument(
        "--clearance-percentile",
        type=float,
        metavar="P",
        help="auto-pick the clearance threshold from this percentile",
    )


def _add_output_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--out", help="write the modified graph to this path (else stdout)"
    )
    p.add_argument(
        "--in-place",
        action="store_true",
        help="overwrite the input graph file in place",
    )
    p.add_argument(
        "--no-backup",
        action="store_true",
        help="skip writing a .bak file before overwriting",
    )


def register_subcommands(sub: argparse._SubParsersAction) -> None:
    p_from = sub.add_parser(
        "from-occupancy",
        help="build a topology graph from a ROS map_server occupancy bundle",
    )
    p_from.add_argument("map", help="path to map.yaml (ROS map_server format)")
    p_from.add_argument(
        "--out",
        required=True,
        help="output graph path (.yaml / .yml / .json)",
    )
    p_from.add_argument(
        "--endpoint-type",
        default="endpoint",
        help="node type for skeleton endpoints (default: endpoint)",
    )
    p_from.add_argument(
        "--junction-type",
        default="intersection",
        help="node type for skeleton junctions (default: intersection)",
    )
    p_from.add_argument(
        "--edge-type",
        default="corridor",
        help="edge type for skeleton segments (default: corridor)",
    )
    p_from.add_argument(
        "--id-prefix", default="", help="prefix for generated node / edge ids"
    )
    p_from.add_argument(
        "--frame-id",
        default="map",
        help="frame_id stamped on node poses (default: map)",
    )
    p_from.add_argument(
        "--no-backup",
        action="store_true",
        help="skip writing a .bak file when --out already exists",
    )
    p_from.set_defaults(func=cmd_from_occupancy)

    p_doors = sub.add_parser(
        "mark-doors",
        help="re-type narrow-passage nodes / edges as doors based on clearance",
    )
    p_doors.add_argument("graph", help="path to topology graph (.yaml / .json)")
    p_doors.add_argument("map", help="path to map.yaml (ROS map_server format)")
    _add_threshold_args(p_doors)
    p_doors.add_argument(
        "--no-mark-edges",
        action="store_true",
        help="only re-type nodes; leave edges alone",
    )
    p_doors.add_argument(
        "--edge-samples",
        type=int,
        default=32,
        help="straight-line samples per edge when computing clearance (default: 32)",
    )
    _add_output_args(p_doors)
    p_doors.set_defaults(func=cmd_mark_doors)

    p_regions = sub.add_parser(
        "annotate-regions",
        help="stamp connected-component region ids onto graph nodes",
    )
    p_regions.add_argument("graph", help="path to topology graph (.yaml / .json)")
    p_regions.add_argument("map", help="path to map.yaml (ROS map_server format)")
    _add_threshold_args(p_regions)
    p_regions.add_argument(
        "--min-region-area",
        type=int,
        default=0,
        metavar="N",
        help="drop regions smaller than N cells (default: 0)",
    )
    p_regions.add_argument(
        "--show-regions",
        action="store_true",
        help="print per-region area / centroid summary to stderr",
    )
    _add_output_args(p_regions)
    p_regions.set_defaults(func=cmd_annotate_regions)
