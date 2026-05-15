"""Tests for the HTTP reference transport / server.

These tests start a real ThreadingHTTPServer on a free local port,
talk to it from the same process via :class:`SchedulerClient` +
:class:`HttpTransport`, and shut it down afterwards. The server lives
on its own daemon thread so test isolation is per-test (each test
creates its own server)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import time
from pathlib import Path

import pytest

from semantic_toponav.coordination.fleet import FleetRequest, plan_fleet
from semantic_toponav.coordination.http_transport import (
    HttpSchedulerServer,
    HttpTransport,
)
from semantic_toponav.coordination.rpc import (
    RpcError,
    SchedulerClient,
    SchedulerProtocol,
    SchedulerService,
    Transport,
)
from semantic_toponav.coordination.scheduler import (
    ClaimRequest,
    SharedScheduler,
)
from semantic_toponav.graph.serialization import load_graph


@pytest.fixture()
def running_server():
    """Spin up an HttpSchedulerServer on a free port; yield (server, scheduler)."""
    scheduler = SharedScheduler()
    server = HttpSchedulerServer(SchedulerService(scheduler))
    server.start()
    try:
        yield server, scheduler
    finally:
        server.shutdown()


# ----- protocol surface ------------------------------------------------------


def test_http_transport_satisfies_transport_protocol() -> None:
    """Even before any request goes through, the type contract holds."""
    t = HttpTransport("http://127.0.0.1:1/")
    assert isinstance(t, Transport)


def test_scheduler_client_over_http_satisfies_protocol(running_server) -> None:
    server, _ = running_server
    client = SchedulerClient(HttpTransport(server.url))
    assert isinstance(client, SchedulerProtocol)


def test_server_exposes_url_after_start(running_server) -> None:
    server, _ = running_server
    assert server.url.startswith("http://127.0.0.1:")
    assert server.port > 0


# ----- basic round-trip ------------------------------------------------------


def test_ping_returns_size(running_server) -> None:
    server, _ = running_server
    client = SchedulerClient(HttpTransport(server.url))
    assert client.ping() == 0


def test_claim_round_trip_mutates_backing_scheduler(running_server) -> None:
    server, backing = running_server
    client = SchedulerClient(HttpTransport(server.url))
    res = client.claim(
        ClaimRequest(
            agent_id="r1", resource_id="hub",
            start=time(10, 0), end=time(11, 0),
        )
    )
    assert res.granted is True
    # The HTTP layer is end-to-end transparent — the in-process
    # scheduler the server holds saw the claim, just like LocalTransport.
    assert len(backing) == 1


def test_claim_many_atomic_rollback_over_http(running_server) -> None:
    server, backing = running_server
    # Pre-load a blocker on the backing scheduler.
    backing.claim(
        ClaimRequest(
            agent_id="blocker", resource_id="hub",
            start=time(10, 0), end=time(11, 0),
        )
    )
    client = SchedulerClient(HttpTransport(server.url))
    results = client.claim_many(
        [
            ClaimRequest(
                agent_id="r1", resource_id="hub",
                start=time(10, 0), end=time(11, 0),
            ),
            ClaimRequest(
                agent_id="r1", resource_id="other",
                start=time(10, 0), end=time(11, 0),
            ),
        ]
    )
    assert results[0].granted is False
    # Rollback: r1 should hold nothing on the other resource.
    assert client.claims_for("r1") == []


def test_release_specific_and_release_all(running_server) -> None:
    server, _ = running_server
    client = SchedulerClient(HttpTransport(server.url))
    client.claim(
        ClaimRequest(
            agent_id="r1", resource_id="hub",
            start=time(10, 0), end=time(11, 0),
        )
    )
    client.claim(
        ClaimRequest(
            agent_id="r2", resource_id="lab",
            start=time(10, 0), end=time(11, 0),
        )
    )
    removed = client.release(
        "r1", "hub", start=time(10, 0), end=time(11, 0),
    )
    assert removed == 1
    assert client.release_all("r2") == 1
    assert len(client) == 0


def test_iter_and_len_match_backing(running_server) -> None:
    server, _ = running_server
    client = SchedulerClient(HttpTransport(server.url))
    for resource in ("a", "b", "c"):
        client.claim(
            ClaimRequest(
                agent_id="r1", resource_id=resource,
                start=time(10, 0), end=time(11, 0),
            )
        )
    assert len(client) == 3
    assert {r.resource_id for r in client} == {"a", "b", "c"}


def test_conflicts_excludes_own_agent(running_server) -> None:
    server, _ = running_server
    client = SchedulerClient(HttpTransport(server.url))
    client.claim(
        ClaimRequest(
            agent_id="r1", resource_id="hub",
            start=time(10, 0), end=time(11, 0),
        )
    )
    assert client.conflicts(
        "hub", time(10, 30), time(11, 30), exclude_agent="r1"
    ) == []
    out = client.conflicts("hub", time(10, 30), time(11, 30))
    assert len(out) == 1 and out[0].agent_id == "r1"


def test_table_round_trip(running_server) -> None:
    server, _ = running_server
    client = SchedulerClient(HttpTransport(server.url))
    client.claim(
        ClaimRequest(
            agent_id="r1", resource_id="hub",
            start=time(10, 0), end=time(11, 0),
        )
    )
    table = client.table()
    assert len(table.entries) == 1
    assert table.entries[0].resource_id == "hub"


# ----- error paths -----------------------------------------------------------


def test_empty_agent_id_surfaces_as_rpcerror(running_server) -> None:
    server, _ = running_server
    client = SchedulerClient(HttpTransport(server.url))
    with pytest.raises(RpcError):
        client.claim(
            ClaimRequest(
                agent_id="", resource_id="x",
                start=time(10, 0), end=time(11, 0),
            )
        )


def test_unknown_op_returns_400(running_server) -> None:
    """A direct POST with a bad op should give a 400 with structured body."""
    server, _ = running_server
    req = urllib.request.Request(
        server.url,
        data=json.dumps({"op": "nope"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(req, timeout=5.0)
    assert ei.value.code == 400


def test_get_method_not_allowed(running_server) -> None:
    server, _ = running_server
    req = urllib.request.Request(server.url, method="GET")
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(req, timeout=5.0)
    assert ei.value.code == 405


def test_unknown_path_returns_404(running_server) -> None:
    server, _ = running_server
    bad_url = server.url + "wrong"
    req = urllib.request.Request(
        bad_url,
        data=json.dumps({"op": "ping"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(req, timeout=5.0)
    assert ei.value.code == 404


def test_non_json_body_returns_400(running_server) -> None:
    server, _ = running_server
    req = urllib.request.Request(
        server.url,
        data=b"not json",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(req, timeout=5.0)
    assert ei.value.code == 400


def test_empty_body_returns_400(running_server) -> None:
    server, _ = running_server
    req = urllib.request.Request(
        server.url,
        data=b"",
        headers={
            "Content-Type": "application/json",
            "Content-Length": "0",
        },
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(req, timeout=5.0)
    assert ei.value.code == 400


def test_transport_url_property_accessible() -> None:
    t = HttpTransport("http://example.invalid/")
    assert t.url == "http://example.invalid/"


def test_connection_refused_raises_rpcerror() -> None:
    """No server running on the port → URLError → RpcError."""
    t = HttpTransport("http://127.0.0.1:1/", timeout=1.0)
    with pytest.raises(RpcError):
        t.send({"op": "ping"})


# ----- planner end-to-end ----------------------------------------------------


def test_plan_fleet_runs_against_http_client(running_server) -> None:
    """Same end-to-end check PR #41 did with LocalTransport — but over the
    real HTTP server. If the wire is faithful, fleet behavior is identical."""
    example_yaml = (
        Path(__file__).resolve().parents[1] / "examples" / "indoor_office.yaml"
    )
    g = load_graph(example_yaml)
    server, backing = running_server
    client = SchedulerClient(HttpTransport(server.url))
    requests = [
        FleetRequest("r1", "entrance", "kitchen"),
        FleetRequest("r2", "entrance", "lab"),
    ]
    result = plan_fleet(
        g, requests, client,
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    assert result.results[0].granted is True
    # Mutations flow through to the in-process scheduler the server owns.
    assert len(backing) > 0


# ----- lifecycle -------------------------------------------------------------


def test_server_context_manager_starts_and_stops() -> None:
    with HttpSchedulerServer(SchedulerService(SharedScheduler())) as server:
        client = SchedulerClient(HttpTransport(server.url))
        assert client.ping() == 0
    # After context exit, the server is stopped — further requests fail.
    with pytest.raises(RpcError):
        HttpTransport(server.url, timeout=1.0).send({"op": "ping"})


def test_double_start_is_idempotent() -> None:
    """Calling start() twice should not spawn a second thread or crash."""
    server = HttpSchedulerServer(SchedulerService(SharedScheduler()))
    try:
        server.start()
        server.start()  # second call is a no-op
        client = SchedulerClient(HttpTransport(server.url))
        assert client.ping() == 0
    finally:
        server.shutdown()


def test_double_shutdown_is_safe() -> None:
    server = HttpSchedulerServer(SchedulerService(SharedScheduler()))
    server.start()
    server.shutdown()
    server.shutdown()  # second call is a no-op
