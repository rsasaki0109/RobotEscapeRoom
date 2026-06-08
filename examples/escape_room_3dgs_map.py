"""Isometric facility background from imported OBJ room meshes.

Regenerate:
    PYTHONPATH=. python3 examples/generate_escape_room_3dgs_map.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from escape_room_mesh_render import render_iso_facility
from escape_room_meshes import MESH_DIR, IsoView, fit_iso_view

HERE = Path(__file__).parent
MAP_PATH = MESH_DIR / "escape_room_facility_mesh.png"
LEGACY_MAP_PATH = MESH_DIR / "escape_room_3dgs_map.png"

SIM_W, BODY_H = 660, 480


def render_facility_background(
    graph: Any,
    *,
    width: int = SIM_W,
    height: int = BODY_H,
    view: IsoView | None = None,
) -> Image.Image:
    return render_iso_facility(graph, width=width, height=height, view=view)


def ensure_map(graph: Any, path: Path = MAP_PATH) -> Path:
    if not path.exists():
        write_map(graph, path)
    return path


def write_map(graph: Any, path: Path = MAP_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    from escape_room_mesh_render import clear_tri_cache

    clear_tri_cache()
    view = fit_iso_view(graph, SIM_W, BODY_H)
    img = render_iso_facility(graph, width=SIM_W, height=BODY_H, view=view)
    img.save(path, optimize=True)
    if path != LEGACY_MAP_PATH:
        img.save(LEGACY_MAP_PATH, optimize=True)
    return path


def load_map(graph: Any, path: Path = MAP_PATH) -> Image.Image:
    ensure_map(graph, path)
    return Image.open(path).convert("RGBA")
