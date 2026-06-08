#!/usr/bin/env python3
"""Pre-render the escape-room 3DGS isometric background PNG.

    PYTHONPATH=. python3 examples/generate_escape_room_3dgs_map.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "examples"))

from escape_room_3dgs_map import MAP_PATH, write_map  # noqa: E402
from semantic_toponav.graph.serialization import load_graph  # noqa: E402

GRAPH = ROOT / "examples" / "robot_escape_room.yaml"


def main() -> None:
    graph = load_graph(GRAPH)
    out = write_map(graph)
    print(f"wrote facility mesh render -> {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
