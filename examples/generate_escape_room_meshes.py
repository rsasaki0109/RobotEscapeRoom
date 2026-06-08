"""Generate detailed interior OBJ meshes for the Robot Escape Room facility.

Each room includes tiled floors, wainscoted walls with doorways, ceiling
lights, and room-specific props. Import into Blender / 3ds Max:

    PYTHONPATH=. python3 examples/generate_escape_room_meshes.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "examples"))

from escape_room_interior import all_room_geometry, geometry_to_obj
from escape_room_meshes import MESH_DIR, MANIFEST_PATH, SCENE_OBJ, all_meshes, write_manifest
from semantic_toponav.graph.serialization import load_graph

GRAPH_PATH = Path(__file__).parent / "robot_escape_room.yaml"


def _write_combined(path: Path, rooms) -> None:
    lines = ["# robot-escape-room detailed interior", "# units: metres, Z-up"]
    offset = 0
    for room in rooms:
        lines.append(f"# {room.label} ({room.node_id}) floor {room.floor}")
        lines.append(f"o {room.node_id}")
        n_tris = len(room.tris)
        for tri in room.tris:
            for v in (tri.v0, tri.v1, tri.v2):
                lines.append(f"v {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}")
        for i in range(n_tris):
            a = offset + i * 3 + 1
            lines.append(f"f {a} {a + 1} {a + 2}")
        offset += n_tris * 3
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    graph = load_graph(GRAPH_PATH)
    rooms = all_room_geometry(graph)
    MESH_DIR.mkdir(parents=True, exist_ok=True)

    for room in rooms:
        out = MESH_DIR / f"{room.node_id}.obj"
        out.write_text(geometry_to_obj(room), encoding="utf-8")

    _write_combined(SCENE_OBJ, rooms)
    write_manifest(all_meshes(graph))

    tri_count = sum(len(r.tris) for r in rooms)
    print(f"wrote {len(rooms)} detailed room meshes ({tri_count} tris) -> {MESH_DIR.relative_to(ROOT)}")
    print(f"combined scene -> {SCENE_OBJ.relative_to(ROOT)}")
    print(f"manifest -> {MANIFEST_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
