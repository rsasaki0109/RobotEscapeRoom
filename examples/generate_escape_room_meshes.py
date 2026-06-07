"""Generate per-room OBJ meshes for the Robot Escape Room facility.

Reads ``robot_escape_room.yaml`` and writes one box mesh per topology node
plus a combined scene file. Import into Blender / 3ds Max / Gazebo:

    PYTHONPATH=. python3 examples/generate_escape_room_meshes.py

Outputs under ``examples/meshes/escape_room/``:

* ``<node_id>.obj`` — one room/corridor box each
* ``escape_room_scene.obj`` — merged facility
* ``manifest.json`` — centres, sizes, colours for tooling
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from semantic_toponav.graph.serialization import load_graph

from escape_room_meshes import (
    MESH_DIR,
    MANIFEST_PATH,
    SCENE_OBJ,
    all_meshes,
    write_manifest,
    write_obj,
)

GRAPH_PATH = Path(__file__).parent / "robot_escape_room.yaml"


def main() -> None:
    graph = load_graph(GRAPH_PATH)
    meshes = all_meshes(graph)
    MESH_DIR.mkdir(parents=True, exist_ok=True)

    for mesh in meshes:
        out = MESH_DIR / f"{mesh.node_id}.obj"
        write_obj(out, [mesh], combined=False)

    write_obj(SCENE_OBJ, meshes, combined=True)
    write_manifest(meshes)

    print(f"wrote {len(meshes)} room meshes -> {MESH_DIR.relative_to(ROOT)}")
    print(f"combined scene -> {SCENE_OBJ.relative_to(ROOT)}")
    print(f"manifest -> {MANIFEST_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
