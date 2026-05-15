"""HTTP reference implementation of :class:`Transport` / scheduler server.

PR #41 introduced a deliberately transport-agnostic shim:
:class:`SchedulerService` knows how to *handle* JSON-shaped messages,
and :class:`Transport` defines a one-method protocol for sending them.
The in-process :class:`LocalTransport` was the only concrete impl —
useful for tests and as documentation, but not enough to wire a real
multi-process fleet through.

This module adds the smallest credible "real wire" impl using only the
standard library:

* :class:`HttpScheduerServer` — a :class:`http.server.ThreadingHTTPServer`
  wrapper that POSTs every request body into a
  :class:`SchedulerService.handle` call and returns the response as
  the body. Threading is on so a slow ``claim_many`` from one client
  does not block ``ping`` from another.
* :class:`HttpTransport` — a :class:`Transport` that ``urllib.request``-POSTs
  the message dict at a URL and parses the response. Wires straight
  into :class:`SchedulerClient`.

Wire contract:

* ``POST {url}/`` with ``Content-Type: application/json`` and the
  service message as the body.
* ``200`` with the service response body on success.
* ``400`` with ``{"error": "...", "kind": "RpcError"}`` for malformed
  payloads (the same shape :class:`SchedulerService` already uses for
  :class:`~SchedulerError`).
* Any other method or path → ``405`` / ``404``.

The server is stdlib only — no Flask / FastAPI / aiohttp dependency.
For TLS, auth, schemas, or async, swap in a richer framework on top
of :class:`SchedulerService`; the message shape stays the same.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from semantic_toponav.coordination.rpc import (
    RpcError,
    SchedulerService,
)

# --- server -------------------------------------------------------------------


def _make_handler(service: SchedulerService) -> type[BaseHTTPRequestHandler]:
    """Return a handler class closed over ``service``.

    BaseHTTPRequestHandler reads behavior from a class, not an
    instance, so we build the class inside a factory and stash the
    service on it via a class attribute.
    """

    class _Handler(BaseHTTPRequestHandler):
        _service = service

        # http.server logs to stderr by default; tests get noisy.
        # Override to no-op so the server can be started in test
        # threads without spamming captured stderr.
        def log_message(self, _format: str, *_args: Any) -> None:  # noqa: A003
            return

        def _send_json(self, status: int, body: dict[str, Any]) -> None:
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self) -> None:  # noqa: N802 — required by base
            if self.path not in ("/", ""):
                self._send_json(
                    HTTPStatus.NOT_FOUND,
                    {"error": f"unknown path {self.path!r}", "kind": "RpcError"},
                )
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "empty request body", "kind": "RpcError"},
                )
                return
            raw = self.rfile.read(length)
            try:
                message = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": f"invalid JSON: {exc}", "kind": "RpcError"},
                )
                return
            if not isinstance(message, dict):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "request body must be a JSON object",
                     "kind": "RpcError"},
                )
                return
            try:
                response = self._service.handle(message)
            except RpcError as exc:
                # Routing errors and unknown ops surface as 400 so
                # callers can distinguish "the server didn't even try"
                # from "the server tried and returned a SchedulerError"
                # (which is in-body via the ``error`` key).
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": str(exc), "kind": "RpcError"},
                )
                return
            self._send_json(HTTPStatus.OK, response)

        def do_GET(self) -> None:  # noqa: N802
            self._send_json(
                HTTPStatus.METHOD_NOT_ALLOWED,
                {"error": "use POST", "kind": "RpcError"},
            )

    return _Handler


class HttpSchedulerServer:
    """Thin lifecycle wrapper around :class:`ThreadingHTTPServer`.

    Construct with a :class:`SchedulerService` and an optional bind
    address. Call :meth:`start` to spin up the serving thread (the
    socket is already bound at that point, so :attr:`url` is valid
    immediately afterwards), and :meth:`shutdown` to stop. Doubles as
    a context manager so test code can write
    ``with HttpSchedulerServer(svc) as server: ...``.
    """

    def __init__(
        self,
        service: SchedulerService,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        self._service = service
        # Bind immediately so ``server_address`` is real even before
        # start() is called. Port 0 asks the OS for a free port.
        self._server = ThreadingHTTPServer((host, port), _make_handler(service))
        self._thread: threading.Thread | None = None

    @property
    def host(self) -> str:
        return self._server.server_address[0]

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    @property
    def service(self) -> SchedulerService:
        return self._service

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="HttpSchedulerServer",
            daemon=True,
        )
        self._thread.start()

    def shutdown(self) -> None:
        if self._thread is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2.0)
        self._thread = None

    def __enter__(self) -> HttpSchedulerServer:
        self.start()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.shutdown()


# --- client transport --------------------------------------------------------


class HttpTransport:
    """:class:`Transport` impl that POSTs to a URL.

    Constructs nothing on its own; the server is the caller's
    responsibility. Pair this with :class:`SchedulerClient` to get the
    full scheduler surface over HTTP:

    >>> server = HttpSchedulerServer(service)
    >>> server.start()
    >>> client = SchedulerClient(HttpTransport(server.url))

    All messages must JSON-encode cleanly. The contract assumes the
    server returns a JSON object body for both success and structured
    errors; HTTP-layer failures (DNS, connection refused, non-JSON
    body, non-200 with no JSON) raise :class:`RpcError` so the client
    catches a single exception type regardless of transport.
    """

    def __init__(self, url: str, *, timeout: float = 10.0) -> None:
        self._url = url
        self._timeout = timeout

    @property
    def url(self) -> str:
        return self._url

    def send(self, message: dict) -> dict:
        body = json.dumps(message).encode("utf-8")
        req = urllib.request.Request(
            self._url,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            # The server already encodes structured errors in the body;
            # surface that JSON so :class:`SchedulerClient` re-raises
            # the right RpcError.
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                if isinstance(payload, dict):
                    return payload
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
            raise RpcError(
                f"HTTP {exc.code} from {self._url}: {exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RpcError(f"HTTP transport error: {exc}") from exc
        try:
            response = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RpcError(
                f"server returned non-JSON body: {raw!r}"
            ) from exc
        if not isinstance(response, dict):
            raise RpcError(
                f"server returned non-object body: {response!r}"
            )
        return response
