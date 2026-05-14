"""VLM / CLIP encoder subcommand for the ``semantic-toponav`` CLI.

Provides ``embed-regions GRAPH MAP``: re-runs :func:`annotate_regions`
against the supplied occupancy map (so that bbox geometry is available
for each room / labeled component), crops one patch per region from a
source image, embeds the patches via the requested backend, and stamps
the resulting vectors onto every graph node carrying the matching
``region_id`` property.

The default backend is :class:`HashingBackend` so the subcommand runs
with the existing ``[map]`` extra alone. ``--backend clip`` opts into
the heavier ``[vlm]`` extra (``transformers`` + ``torch`` + ``Pillow``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from semantic_toponav.cli.occupancy_cli import (
    _resolve_threshold_args,
    _write_or_print,
)
from semantic_toponav.graph.serialization import GraphLoadError, load_graph
from semantic_toponav.graph.types import GraphValidationError


def cmd_embed_regions(args: argparse.Namespace) -> int:
    code = _resolve_threshold_args(args)
    if code:
        return code

    try:
        from semantic_toponav.conversion.map_io import (
            MapLoadError,
            load_occupancy_map,
        )
        from semantic_toponav.conversion.occupancy import annotate_regions
        from semantic_toponav.conversion.vlm import embed_region_patches
        from semantic_toponav.encoders.backends import (
            CLIPBackend,
            HashingBackend,
        )
    except ImportError as exc:
        print(
            f"error: embed-regions requires the [map] extra ({exc}). Install with "
            "`pip install 'semantic-toponav[map]'`",
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

    image = _load_patch_image(args, occ.free_mask)
    if image is None:
        return 2

    if args.backend == "hashing":
        backend = HashingBackend(dim=args.dim)
    elif args.backend == "clip":
        try:
            backend = CLIPBackend(model_name=args.clip_model, device=args.clip_device)
        except ImportError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    else:  # argparse choices guarantees this is unreachable
        print(f"error: unknown backend {args.backend!r}", file=sys.stderr)
        return 2

    region_kwargs: dict[str, object] = {
        "resolution": occ.resolution,
        "origin": occ.origin,
        "free_threshold": args.free_threshold,
        "min_region_area": args.min_region_area,
    }
    if args.clearance_threshold is not None:
        region_kwargs["clearance_threshold"] = args.clearance_threshold
    if args.clearance_percentile is not None:
        region_kwargs["clearance_percentile"] = args.clearance_percentile
    regions = annotate_regions(graph, occ.free_mask, **region_kwargs)

    include = list(args.include_region) if args.include_region else None
    try:
        result = embed_region_patches(
            graph,
            image,
            regions,
            backend,
            embedding_property=args.embedding_property,
            region_id_property=args.region_id_property,
            pad_cells=args.pad_cells,
            include=include,
        )
    except (ValueError, ImportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(
        f"embedded {len(result.region_embeddings)} region(s) "
        f"(dim={result.backend_dim}); stamped {len(result.node_ids)} node(s)",
        file=sys.stderr,
    )

    return _write_or_print(
        graph,
        source=Path(args.graph),
        out=args.out,
        in_place=args.in_place,
        no_backup=args.no_backup,
    )


def _load_patch_image(args: argparse.Namespace, free_mask):
    """Return the array used as the source for region patches.

    Falls back to the free-mask cast to ``uint8`` grayscale when
    ``--image`` is omitted. With ``--image PATH``, loads the file via
    scikit-image and requires it to match the free-mask shape so the
    occupancy-derived bboxes still index into valid pixels.
    """
    if not args.image:
        try:
            import numpy as np
        except ImportError:  # pragma: no cover — gated by [map] extra
            print("error: numpy is required for embed-regions", file=sys.stderr)
            return None
        return (free_mask.astype(np.uint8) * 255)

    try:
        import numpy as np
        from skimage.io import imread
    except ImportError as exc:  # pragma: no cover — gated by [map] extra
        print(f"error: skimage is required for --image ({exc})", file=sys.stderr)
        return None

    img = imread(args.image)
    if img.ndim == 3 and img.shape[2] == 4:
        img = img[..., :3]
    if img.shape[:2] != free_mask.shape[:2]:
        print(
            f"error: --image shape {img.shape[:2]} does not match map shape "
            f"{free_mask.shape[:2]}",
            file=sys.stderr,
        )
        return None
    if img.dtype != np.uint8:
        img = np.clip(img, 0, 255).astype(np.uint8)
    return img


def register_subcommands(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "embed-regions",
        help=(
            "embed each annotate-regions component via a VLM/CLIP backend "
            "and stamp the vector onto every graph node in that region"
        ),
    )
    p.add_argument("graph", help="path to topology graph (.yaml / .json)")
    p.add_argument("map", help="path to map.yaml (ROS map_server format)")
    p.add_argument(
        "--backend",
        choices=["hashing", "clip"],
        default="hashing",
        help=(
            "encoder backend (default: hashing — deterministic, no extra deps). "
            "Pick `clip` for real semantic embeddings via the [vlm] extra."
        ),
    )
    p.add_argument(
        "--dim",
        type=int,
        default=32,
        help="output dimension for the hashing backend (default: 32)",
    )
    p.add_argument(
        "--clip-model",
        default="openai/clip-vit-base-patch32",
        help=(
            "HuggingFace model id for the clip backend "
            "(default: openai/clip-vit-base-patch32)"
        ),
    )
    p.add_argument(
        "--clip-device",
        default="cpu",
        help="torch device for the clip backend (default: cpu)",
    )
    p.add_argument(
        "--image",
        help=(
            "optional path to a source image aligned to the map "
            "(same H x W as the occupancy grid); used as the patch source. "
            "Defaults to the free-mask cast to uint8 grayscale."
        ),
    )
    p.add_argument(
        "--pad-cells",
        type=int,
        default=0,
        metavar="N",
        help="padding (in cells) added to each region bbox before cropping",
    )
    p.add_argument(
        "--embedding-property",
        default="embedding",
        help="node-property key under which the vector is stamped (default: embedding)",
    )
    p.add_argument(
        "--region-id-property",
        default="region_id",
        help="node-property key holding the region id (default: region_id)",
    )
    p.add_argument(
        "--include-region",
        type=int,
        action="append",
        metavar="RID",
        help=(
            "only embed this region id (repeatable). "
            "Omitting it embeds every region annotate_regions returns."
        ),
    )
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
        help="explicit clearance threshold for doorway pinching (meters)",
    )
    p.add_argument(
        "--clearance-percentile",
        type=float,
        metavar="P",
        help="auto-pick the clearance threshold from this percentile",
    )
    p.add_argument(
        "--min-region-area",
        type=int,
        default=0,
        metavar="N",
        help="drop regions smaller than N cells (default: 0)",
    )
    p.add_argument(
        "--out",
        help="write the modified graph to this path (else stdout)",
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
    p.set_defaults(func=cmd_embed_regions)
