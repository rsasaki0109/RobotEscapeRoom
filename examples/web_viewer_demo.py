"""Interactive web viewer demo.

Run from the repository root:

    pip install 'semantic-toponav[viz_web]'
    python examples/web_viewer_demo.py

Renders the bundled multi-floor office graph as a standalone, draggable
HTML page. The shortest path between ``entrance`` and a room on the 3rd
floor is highlighted in pink. Open the resulting file in any browser:

    xdg-open examples/multi_floor_viewer.html
"""

from __future__ import annotations

from pathlib import Path

from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.planner import plan_astar
from semantic_toponav.visualization import save_interactive_html

GRAPH_PATH = Path(__file__).parent / "multi_floor_office.yaml"
OUTPUT_PATH = Path(__file__).parent / "multi_floor_viewer.html"


def main() -> None:
    graph = load_graph(GRAPH_PATH)
    path = plan_astar(graph, "entrance", "exec_office_3f")
    print(f"path: {' -> '.join(path)}")

    out = save_interactive_html(graph, OUTPUT_PATH, path=path)
    print(f"saved {out.relative_to(Path.cwd()) if out.is_absolute() else out}")
    print("open in a browser to explore (nodes are draggable; tooltips on hover)")


if __name__ == "__main__":
    main()
