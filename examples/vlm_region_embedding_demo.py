"""VLM region-embedding retrieval demo.

Run from the repository root:

    pip install -e '.[viz,map]'
    python examples/vlm_region_embedding_demo.py

What it does
------------
1. Load the bundled occupancy map (``examples/sample_map.yaml``).
2. Convert it to a topology graph and annotate connected-component
   regions (rooms) via :func:`annotate_regions`.
3. Embed each region's patch with a :class:`HashingBackend` (no heavy
   deps; swap in :class:`CLIPBackend` for real semantics) and stamp
   the result onto every node carrying the region id.
4. For each region, treat its embedding as a "query" and color every
   node by cosine similarity to that query — exactly what the LLM /
   text-resolve path consumes via ``embedding_score=`` injection.

The output is two artifacts under ``docs/images/``:

* ``14_vlm_region_overview.png`` — 2x2 grid: overview + similarity
  heatmaps for three different query regions.
* ``15_vlm_region_cycle.gif`` — animated GIF cycling through the
  three queries (1.8 s per frame, infinite loop).

The demo intentionally uses ``HashingBackend`` so it runs with zero
extra dependencies. Patch-byte similarity is *not* semantically
meaningful — it shows the *mechanism* (per-node colored similarity
heatmap, different query → different highlight pattern). To ground
text queries on actual photographs, drop a :class:`CLIPBackend`
instance in at the same call site and feed an aligned RGB image via
``rgb_source=`` (see PR #52's :class:`AlignedRgbSource` plug point).
"""

from __future__ import annotations

import io
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

from semantic_toponav.conversion import (
    annotate_regions,
    load_occupancy_map,
    topology_from_occupancy,
)
from semantic_toponav.conversion.vlm import embed_region_patches
from semantic_toponav.encoders.backends import HashingBackend
from semantic_toponav.query.embedding import cosine_similarity
from semantic_toponav.visualization import plot_graph

HERE = Path(__file__).parent
IMAGE_DIR = HERE.parent / "docs" / "images"
MAP_YAML = HERE / "sample_map.yaml"

# Panel layout
OVERVIEW_PNG = IMAGE_DIR / "14_vlm_region_overview.png"
CYCLE_GIF = IMAGE_DIR / "15_vlm_region_cycle.gif"
FRAME_W, FRAME_H = 7.5, 5.0
FRAME_DPI = 110
GIF_FRAME_MS = 1800
GIF_LOOP = 0  # forever


def _node_xy(node) -> tuple[float, float]:
    return float(node.pose.x), float(node.pose.y)


def _render_panel(
    ax,
    graph,
    *,
    grid,
    resolution,
    origin,
    title: str,
    node_scores: dict[str, float] | None = None,
    highlight_bbox=None,
) -> None:
    """Draw a single panel: occupancy + topology + per-node similarity.

    When ``node_scores`` is None, nodes are drawn in a neutral color
    (overview panel). Otherwise nodes are colored by cosine similarity
    (red = high, gray-blue = low).
    """
    plot_graph(
        graph,
        ax=ax,
        title=title,
        show_labels=False,
        show_edge_ids=False,
        occupancy_grid=grid,
        resolution=resolution,
        origin=origin,
    )

    # Overlay nodes as a scatter on top of plot_graph's default markers.
    nodes = list(graph.nodes())
    xs = [_node_xy(n)[0] for n in nodes]
    ys = [_node_xy(n)[1] for n in nodes]
    if node_scores is None:
        ax.scatter(
            xs, ys, s=80, c="#3b82f6", edgecolor="white", linewidth=1.0, zorder=5
        )
    else:
        colors = [node_scores.get(n.id, 0.0) for n in nodes]
        sc = ax.scatter(
            xs, ys,
            s=110, c=colors, cmap="hot",
            vmin=-1.0, vmax=1.0,
            edgecolor="black", linewidth=0.6, zorder=5,
        )
        cbar = ax.figure.colorbar(sc, ax=ax, fraction=0.04, pad=0.02)
        cbar.set_label("cosine similarity", fontsize=8)
        cbar.ax.tick_params(labelsize=7)

    # Overlay highlight bbox (the query region) as a translucent rectangle
    # in *world* coordinates (matching plot_graph's extent).
    if highlight_bbox is not None:
        rmin, cmin, rmax, cmax = highlight_bbox
        # bbox is in cell coordinates (rows from top, cols from left).
        # Convert to world coordinates: y increases upward in plot_graph
        # because origin="lower", so we flip rows.
        h = grid.shape[0]
        x0 = origin[0] + cmin * resolution
        x1 = origin[0] + (cmax + 1) * resolution
        y0 = origin[1] + (h - 1 - rmax) * resolution
        y1 = origin[1] + (h - cmin) * resolution  # not actually used below
        _ = y1
        from matplotlib.patches import Rectangle

        rect = Rectangle(
            (x0, y0),
            x1 - x0,
            (rmax - rmin + 1) * resolution,
            linewidth=2.2,
            edgecolor="#facc15",
            facecolor="#facc15",
            alpha=0.18,
            zorder=4,
        )
        ax.add_patch(rect)

    ax.set_xlabel("x (m)", fontsize=8)
    ax.set_ylabel("y (m)", fontsize=8)
    ax.tick_params(labelsize=7)


def _compute_node_scores(graph, query_vec, *, embedding_property: str = "embedding"):
    """Cosine similarity from query to every node carrying an embedding."""
    out: dict[str, float] = {}
    for node in graph.nodes():
        vec = node.properties.get(embedding_property)
        if isinstance(vec, list) and len(vec) == len(query_vec):
            out[node.id] = cosine_similarity(query_vec, vec)
    return out


def main() -> None:
    m = load_occupancy_map(MAP_YAML)
    print(f"loaded {MAP_YAML.name}: shape={m.shape} resolution={m.resolution}")

    graph = topology_from_occupancy(
        m.free_mask, resolution=m.resolution, origin=m.origin
    )
    region_result = annotate_regions(
        graph, m.free_mask,
        resolution=m.resolution, origin=m.origin,
        clearance_percentile=70,
    )
    print(f"annotated {len(region_result.regions)} regions; "
          f"doorway nodes: {len(region_result.doorway_node_ids)}")

    backend = HashingBackend(dim=32)
    emb_result = embed_region_patches(
        graph, m.free_mask, region_result, backend,
    )
    print(f"embedded {len(emb_result.region_embeddings)} regions × dim={backend.dim}")

    region_ids = sorted(emb_result.region_embeddings.keys())
    if len(region_ids) < 3:
        raise RuntimeError(
            f"demo expects ≥ 3 regions on this map; got {len(region_ids)}. "
            "Adjust --clearance-percentile in annotate_regions."
        )

    # ---- 1) Static 2x2 PNG ------------------------------------------------
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(2, 2, figsize=(FRAME_W * 2.05, FRAME_H * 2.05), dpi=FRAME_DPI)
    axes = np.array(axes).reshape(2, 2)

    _render_panel(
        axes[0, 0], graph,
        grid=m.free_mask, resolution=m.resolution, origin=m.origin,
        title=f"Overview — {len(region_ids)} regions, {len(graph.node_ids())} nodes",
    )
    for ax, region_id in zip(axes.flat[1:], region_ids[:3], strict=False):
        q = emb_result.region_embeddings[region_id]
        scores = _compute_node_scores(graph, q)
        bbox = region_result.regions[region_id].bbox_cells
        _render_panel(
            ax, graph,
            grid=m.free_mask, resolution=m.resolution, origin=m.origin,
            title=f"Query = region {region_id} (yellow box)\n"
                  f"node color = cos(query, node.embedding)",
            node_scores=scores,
            highlight_bbox=bbox,
        )

    fig.suptitle(
        "VLM region embedding — same graph, three different query regions",
        fontsize=13, y=1.00,
    )
    fig.tight_layout()
    fig.savefig(OVERVIEW_PNG, dpi=FRAME_DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {OVERVIEW_PNG.relative_to(Path.cwd()) if OVERVIEW_PNG.is_absolute() else OVERVIEW_PNG}")

    # ---- 2) Cycling GIF --------------------------------------------------
    frames: list[Image.Image] = []
    for region_id in region_ids[:3]:
        q = emb_result.region_embeddings[region_id]
        scores = _compute_node_scores(graph, q)
        bbox = region_result.regions[region_id].bbox_cells
        fig, ax = plt.subplots(figsize=(FRAME_W, FRAME_H), dpi=FRAME_DPI)
        _render_panel(
            ax, graph,
            grid=m.free_mask, resolution=m.resolution, origin=m.origin,
            title=f"Query region = {region_id} (yellow box)  →  cosine-similarity heatmap on nodes",
            node_scores=scores,
            highlight_bbox=bbox,
        )
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=FRAME_DPI, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        frames.append(Image.open(buf).convert("P", palette=Image.ADAPTIVE))

    frames[0].save(
        CYCLE_GIF,
        save_all=True,
        append_images=frames[1:],
        duration=GIF_FRAME_MS,
        loop=GIF_LOOP,
        optimize=True,
    )
    size_kb = CYCLE_GIF.stat().st_size / 1024
    print(f"wrote {CYCLE_GIF.relative_to(Path.cwd()) if CYCLE_GIF.is_absolute() else CYCLE_GIF} "
          f"({size_kb:.0f} KB, {len(frames)} frames)")


if __name__ == "__main__":
    main()
