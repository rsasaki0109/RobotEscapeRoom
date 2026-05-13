"""Tiny HTTP server that serves a live-reloading view of a topology graph.

Pair this with the CLI graph editor (``add-node``, ``rm-edge``, etc.) or
plain hand-editing: every time the YAML/JSON file on disk changes, the
open browser tab refreshes itself within ``interval`` seconds.

Implementation notes
--------------------

- The server is single-threaded and synchronous. It is meant for local
  development, not for serving anything in production.
- The view HTML is regenerated *on every request* against the current
  bytes of the source file. This means edits are always picked up;
  there is no in-memory cache to invalidate.
- The browser polls a tiny ``/mtime.json`` endpoint that returns the
  file's modification timestamp, and reloads when it changes. This is
  much friendlier than ``<meta http-equiv=refresh>`` because the page
  only reloads when something actually changed.
- ``pyvis`` is imported lazily through
  :func:`semantic_toponav.visualization.web.to_pyvis_network`, so this
  module is importable without it; calling :func:`serve` without pyvis
  raises :class:`WebViewerImportError`.
"""

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from semantic_toponav.graph.serialization import (
    GraphLoadError,
    load_graph,
)
from semantic_toponav.graph.types import GraphValidationError
from semantic_toponav.visualization.web import graph_html  # re-uses lazy pyvis import

_LIVE_RELOAD_SNIPPET_TEMPLATE = """
<script>
(function () {{
  let last = null;
  async function tick() {{
    try {{
      const r = await fetch('/mtime.json', {{ cache: 'no-store' }});
      if (!r.ok) return;
      const d = await r.json();
      if (last !== null && last !== d.mtime) {{
        location.reload();
      }}
      last = d.mtime;
    }} catch (e) {{}}
  }}
  setInterval(tick, {interval_ms});
  tick();
}})();
</script>
"""


def _inject_live_reload(html: str, interval_ms: int) -> str:
    snippet = _LIVE_RELOAD_SNIPPET_TEMPLATE.format(interval_ms=interval_ms)
    needle = "</body>"
    if needle in html:
        return html.replace(needle, snippet + needle, 1)
    return html + snippet


def _render_page(graph_path: Path, interval_ms: int) -> bytes:
    try:
        graph = load_graph(graph_path)
    except (GraphLoadError, GraphValidationError) as exc:
        body = (
            f"<html><body><pre>error loading {graph_path}:\n{exc}</pre>"
            f"</body></html>"
        )
        return _inject_live_reload(body, interval_ms).encode("utf-8")
    html = graph_html(graph)
    return _inject_live_reload(html, interval_ms).encode("utf-8")


def _make_handler(graph_path: Path, interval_ms: int) -> type:
    class LiveViewerHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A002
            # Quiet by default; turn on for debugging if needed.
            return

        def do_GET(self) -> None:
            if self.path == "/" or self.path.startswith("/?"):
                body = _render_page(graph_path, interval_ms)
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/mtime.json":
                try:
                    mtime = graph_path.stat().st_mtime
                except FileNotFoundError:
                    mtime = 0.0
                body = json.dumps({"mtime": mtime}).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()

    return LiveViewerHandler


def make_server(
    graph_path: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    interval_ms: int = 1000,
) -> HTTPServer:
    """Build (but do not start) an :class:`HTTPServer` for a graph file.

    Use ``server.serve_forever()`` to run, or :func:`serve` for the
    blocking convenience entry point that the CLI uses.
    """
    handler_cls = _make_handler(Path(graph_path), interval_ms)
    return HTTPServer((host, port), handler_cls)


def serve(
    graph_path: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    interval_ms: int = 1000,
) -> None:
    """Run a blocking live-reloading server for ``graph_path``.

    Stop with Ctrl+C.
    """
    server = make_server(
        graph_path, host=host, port=port, interval_ms=interval_ms
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


__all__ = ["make_server", "serve"]
