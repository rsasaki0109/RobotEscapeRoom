"""Tests for the SchedulerService / SchedulerClient / Transport shim."""

from __future__ import annotations

import json
from datetime import time
from pathlib import Path

import pytest

from semantic_toponav.coordination.fleet import (
    FleetRequest,
    plan_fleet,
    plan_with_scheduler,
)
from semantic_toponav.coordination.rpc import (
    LocalTransport,
    RpcError,
    SchedulerClient,
    SchedulerProtocol,
    SchedulerService,
    Transport,
    _claim_request_from_dict,
    _claim_request_to_dict,
    _claim_result_from_dict,
    _claim_result_to_dict,
    _reservation_from_dict,
    _reservation_to_dict,
)
from semantic_toponav.coordination.scheduler import (
    ClaimRequest,
    SharedScheduler,
)
from semantic_toponav.graph.serialization import load_graph
from semantic_toponav.planner.reservations import Reservation

EXAMPLE_YAML = Path(__file__).resolve().parents[1] / "examples" / "indoor_office.yaml"


def _make_pair() -> tuple[SharedScheduler, SchedulerClient]:
    s = SharedScheduler()
    service = SchedulerService(s)
    transport = LocalTransport(service)
    client = SchedulerClient(transport)
    return s, client


# ----- protocol surface ------------------------------------------------------


def test_shared_scheduler_satisfies_protocol() -> None:
    s = SharedScheduler()
    assert isinstance(s, SchedulerProtocol)


def test_scheduler_client_satisfies_protocol() -> None:
    _, client = _make_pair()
    assert isinstance(client, SchedulerProtocol)


def test_local_transport_satisfies_protocol() -> None:
    transport = LocalTransport(SchedulerService(SharedScheduler()))
    assert isinstance(transport, Transport)


# ----- serialization helpers --------------------------------------------------


def test_reservation_roundtrip() -> None:
    r = Reservation(
        resource_id="corridor",
        start=time(10, 0),
        end=time(11, 30),
        agent_id="r1",
    )
    rebuilt = _reservation_from_dict(_reservation_to_dict(r))
    assert rebuilt == r


def test_claim_request_roundtrip_with_priority() -> None:
    req = ClaimRequest(
        agent_id="r1",
        resource_id="hub",
        start=time(9, 0),
        end=time(10, 15),
        priority=5,
    )
    rebuilt = _claim_request_from_dict(_claim_request_to_dict(req))
    assert rebuilt == req


def test_claim_result_roundtrip_preserves_conflicts_and_preempted() -> None:
    res = _claim_result_to_dict(
        _claim_result_from_dict(
            {
                "granted": True,
                "reservation": {
                    "resource_id": "x", "start": "10:00:00",
                    "end": "11:00:00", "agent_id": "r1",
                },
                "conflicts": [],
                "preempted": [
                    {
                        "resource_id": "x", "start": "09:30:00",
                        "end": "10:30:00", "agent_id": "other",
                    }
                ],
            }
        )
    )
    assert res["granted"] is True
    assert len(res["preempted"]) == 1
    assert res["preempted"][0]["agent_id"] == "other"


def test_payloads_are_json_serializable() -> None:
    """Transports go over the wire — every payload must json.dumps cleanly."""
    s, client = _make_pair()
    req = ClaimRequest(
        agent_id="r1", resource_id="hub",
        start=time(10, 0), end=time(11, 0),
    )
    # Direct serialization round-trip of each payload type.
    for payload in (
        {"op": "ping"},
        {"op": "claim", "request": _claim_request_to_dict(req)},
        {"op": "claim_many", "requests": [_claim_request_to_dict(req)]},
        {"op": "release", "agent_id": "r1", "resource_id": "hub"},
        {"op": "release_all", "agent_id": "r1"},
        {"op": "reservations"},
        {"op": "claims_for", "agent_id": "r1"},
        {
            "op": "conflicts", "resource_id": "hub",
            "start": "10:00:00", "end": "11:00:00",
        },
        {"op": "table"},
        {"op": "len"},
    ):
        json.dumps(payload)  # must not raise


# ----- service routing --------------------------------------------------------


def test_service_ping_reports_size() -> None:
    s = SharedScheduler()
    service = SchedulerService(s)
    assert service.handle({"op": "ping"}) == {"ok": True, "size": 0}


def test_service_rejects_unknown_op() -> None:
    service = SchedulerService(SharedScheduler())
    with pytest.raises(RpcError):
        service.handle({"op": "nope"})


def test_service_rejects_missing_op_field() -> None:
    service = SchedulerService(SharedScheduler())
    with pytest.raises(RpcError):
        service.handle({})


def test_service_routes_scheduler_error_into_response() -> None:
    """Empty agent_id triggers SchedulerError on the server. The client
    sees an `error` field rather than a crash."""
    service = SchedulerService(SharedScheduler())
    result = service.handle(
        {
            "op": "claim",
            "request": _claim_request_to_dict(
                ClaimRequest(
                    agent_id="",
                    resource_id="x",
                    start=time(10, 0),
                    end=time(11, 0),
                )
            ),
        }
    )
    assert "error" in result
    assert result["kind"] == "SchedulerError"


# ----- client end-to-end -----------------------------------------------------


def test_client_claim_matches_direct_claim() -> None:
    direct = SharedScheduler()
    via_rpc = SharedScheduler()
    client = SchedulerClient(LocalTransport(SchedulerService(via_rpc)))

    req = ClaimRequest(
        agent_id="r1",
        resource_id="hub",
        start=time(10, 0),
        end=time(11, 0),
    )
    d_res = direct.claim(req)
    c_res = client.claim(req)

    assert d_res.granted == c_res.granted is True
    assert d_res.reservation == c_res.reservation
    assert len(via_rpc) == len(direct) == 1


def test_client_claim_many_atomic_rollback() -> None:
    via_rpc = SharedScheduler()
    via_rpc.claim(
        ClaimRequest(
            agent_id="blocker",
            resource_id="hub",
            start=time(10, 0),
            end=time(11, 0),
        )
    )
    client = SchedulerClient(LocalTransport(SchedulerService(via_rpc)))
    requests = [
        ClaimRequest(
            agent_id="r1", resource_id="hub",
            start=time(10, 0), end=time(11, 0),
        ),
        ClaimRequest(
            agent_id="r1", resource_id="other",
            start=time(10, 0), end=time(11, 0),
        ),
    ]
    results = client.claim_many(requests)
    # First conflicts; the rest is rolled back so r1 holds nothing.
    assert results[0].granted is False
    assert client.claims_for("r1") == []


def test_client_release_and_release_all() -> None:
    s, client = _make_pair()
    client.claim(
        ClaimRequest(
            agent_id="r1", resource_id="entrance",
            start=time(10, 0), end=time(11, 0),
        )
    )
    client.claim(
        ClaimRequest(
            agent_id="r2", resource_id="kitchen",
            start=time(10, 0), end=time(11, 0),
        )
    )
    assert len(client) == 2
    # release specific window
    removed = client.release(
        "r1", "entrance",
        start=time(10, 0), end=time(11, 0),
    )
    assert removed == 1
    # release_all the rest
    removed_all = client.release_all("r2")
    assert removed_all == 1
    assert len(client) == 0


def test_client_conflicts_excludes_own_agent() -> None:
    s, client = _make_pair()
    client.claim(
        ClaimRequest(
            agent_id="r1", resource_id="hub",
            start=time(10, 0), end=time(11, 0),
        )
    )
    out = client.conflicts(
        "hub", time(10, 30), time(11, 30), exclude_agent="r1"
    )
    assert out == []
    out2 = client.conflicts("hub", time(10, 30), time(11, 30))
    assert len(out2) == 1
    assert out2[0].agent_id == "r1"


def test_client_table_round_trip() -> None:
    s, client = _make_pair()
    client.claim(
        ClaimRequest(
            agent_id="r1", resource_id="hub",
            start=time(10, 0), end=time(11, 0),
        )
    )
    table = client.table()
    assert len(table.entries) == 1
    assert table.entries[0].resource_id == "hub"


def test_client_idempotent_same_window_claim() -> None:
    s, client = _make_pair()
    req = ClaimRequest(
        agent_id="r1", resource_id="hub",
        start=time(10, 0), end=time(11, 0),
    )
    a = client.claim(req)
    b = client.claim(req)
    assert a.granted and b.granted
    assert len(s) == 1


def test_client_rpc_error_propagates_empty_agent_id() -> None:
    s, client = _make_pair()
    with pytest.raises(RpcError):
        client.claim(
            ClaimRequest(
                agent_id="",
                resource_id="x",
                start=time(10, 0),
                end=time(11, 0),
            )
        )


# ----- end-to-end: planner runs against the client ---------------------------


def test_plan_with_scheduler_against_rpc_client() -> None:
    g = load_graph(EXAMPLE_YAML)
    # The "real" scheduler lives behind the service; the planner only
    # sees the RPC client. plan_with_scheduler should mutate the
    # backing scheduler through the wire.
    backing = SharedScheduler()
    client = SchedulerClient(LocalTransport(SchedulerService(backing)))
    result = plan_with_scheduler(
        g, "r1", "entrance", "kitchen", client,
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    assert result.granted is True
    assert result.reason_code == "ok"
    assert len(backing) > 0  # claims applied through the transport


def test_plan_fleet_against_rpc_client() -> None:
    g = load_graph(EXAMPLE_YAML)
    backing = SharedScheduler()
    client = SchedulerClient(LocalTransport(SchedulerService(backing)))
    requests = [
        FleetRequest("r1", "entrance", "kitchen"),
        FleetRequest("r2", "entrance", "lab"),
    ]
    result = plan_fleet(
        g, requests, client,
        hold_start=time(10, 0), hold_end=time(11, 0),
    )
    # At least r1 should succeed; behavior with shared resources is
    # the same regardless of whether the scheduler is in-process or
    # behind the shim.
    assert result.results[0].granted is True


def test_client_len_and_iter_match_backing() -> None:
    s, client = _make_pair()
    for resource in ("a", "b", "c"):
        client.claim(
            ClaimRequest(
                agent_id="r1", resource_id=resource,
                start=time(10, 0), end=time(11, 0),
            )
        )
    assert len(client) == 3
    assert {r.resource_id for r in client} == {"a", "b", "c"}


def test_local_transport_is_a_thin_wrapper() -> None:
    """A 1-line LocalTransport is the canonical reference implementation;
    real transports should be just as small."""
    s = SharedScheduler()
    service = SchedulerService(s)
    transport = LocalTransport(service)
    # Calling send routes directly into handle without any extra
    # bookkeeping — verify by hand.
    assert transport.send({"op": "ping"}) == {"ok": True, "size": 0}
