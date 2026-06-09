"""Robot RGB camera panel — renders imported OBJ room meshes."""

from __future__ import annotations

from typing import Any

from escape_room_mesh_render import render_camera_facility
from PIL import Image


def render_camera_view(
    graph: Any,
    meta: dict,
    *,
    width: int,
    height: int,
) -> Image.Image:
    return render_camera_facility(graph, meta, width=width, height=height)
