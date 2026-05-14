"""Conformance suite for :class:`semantic_toponav.coordination.Transport`.

A :class:`Transport` is a one-shot ``send(message: dict) -> dict``
relay. The wire format is intentionally unspecified — HTTP,
WebSocket, NATS, an in-process call queue all qualify — so the
conformance checks focus on what callers depend on:

* ``send`` is callable and returns a ``dict`` (not bytes, not a
  Future, not ``None``).
* The transport routes ``op`` payloads to a real
  :class:`~semantic_toponav.coordination.SchedulerService` such that
  the ``"ping"`` health-check round-trips.
* Round-tripping a small ``claim`` request produces a valid
  :class:`~semantic_toponav.coordination.ClaimResult` payload.

These checks require the transport to be wired to a service-backed
scheduler. The :class:`SchedulerService` instance must be supplied by
the caller, since constructing a fresh server-side scheduler is
deployment-specific (in-process for :class:`LocalTransport`, an HTTP
server for :class:`~semantic_toponav.coordination.HttpTransport`, …).
"""

from __future__ import annotations

from semantic_toponav.coordination.rpc import (
    SchedulerService,
    Transport,
)


def run_transport_conformance(
    transport: Transport,
    *,
    service: SchedulerService,
) -> None:
    """Run the :class:`Transport` conformance checks.

    Parameters
    ----------
    transport:
        The transport under test. Must already be wired to ``service``
        — the caller is responsible for setting up the server side.
    service:
        The :class:`SchedulerService` the transport routes to. The
        suite uses it to confirm that mutations performed over the
        transport are visible on the server side (i.e. the wire
        round-trips data both ways).
    """

    assert isinstance(transport, Transport), (
        f"{type(transport).__name__} does not satisfy the Transport "
        "Protocol (missing send)"
    )

    # ---- ping round-trip ---------------------------------------------------
    pong = transport.send({"op": "ping"})
    assert isinstance(pong, dict), (
        f"send must return dict, got {type(pong).__name__}"
    )
    assert pong.get("ok") is True, (
        f"ping response missing 'ok': True; got {pong!r}"
    )
    assert isinstance(pong.get("size"), int), (
        f"ping response 'size' must be int, got {pong.get('size')!r}"
    )

    # ---- claim round-trip --------------------------------------------------
    initial_size = len(service.scheduler)
    response = transport.send({
        "op": "claim",
        "request": {
            "agent_id": "conformance_probe",
            "resource_id": "transport_check_resource",
            "start": "09:00:00",
            "end": "09:30:00",
            "priority": 0,
        },
    })
    assert isinstance(response, dict), (
        f"claim response must be dict, got {type(response).__name__}"
    )
    assert "result" in response, (
        f"claim response missing 'result' field: {response!r}"
    )
    result = response["result"]
    assert isinstance(result, dict) and result.get("granted") is True, (
        f"claim should have been granted on an empty resource; got {result!r}"
    )

    # The mutation must have landed on the server-side scheduler.
    assert len(service.scheduler) == initial_size + 1, (
        "claim response said granted=True, but the service scheduler did "
        "not grow — the transport is not delivering mutations to the "
        "server side"
    )

    # ---- unknown op surfaces an error structure ----------------------------
    # Transports differ on whether unknown ops raise or return an error
    # dict; the *contract* is just that the caller can detect failure.
    try:
        bad = transport.send({"op": "definitely_not_a_real_op"})
    except Exception:  # noqa: BLE001 - any transport-specific error is fine
        pass
    else:
        assert isinstance(bad, dict), (
            f"unknown-op response must be dict, got {type(bad).__name__}"
        )
        assert "error" in bad, (
            f"unknown-op response should carry an 'error' key; got {bad!r}"
        )

    # ---- ping is repeatable ------------------------------------------------
    # A transport that holds a single-shot socket open and dies on the
    # second message is unusable in practice. Probe it.
    pong2 = transport.send({"op": "ping"})
    assert isinstance(pong2, dict) and pong2.get("ok") is True, (
        f"second ping failed: {pong2!r} — transports must be reusable"
    )

    # ---- release round-trip ------------------------------------------------
    # The claim above landed; the release op must propagate too. Without
    # this check a transport that only implements claim wire-side would
    # still pass the suite.
    pre_release_size = len(service.scheduler)
    release_response = transport.send({
        "op": "release",
        "agent_id": "conformance_probe",
        "resource_id": "transport_check_resource",
    })
    assert isinstance(release_response, dict), (
        f"release response must be dict, got {type(release_response).__name__}"
    )
    assert release_response.get("removed") == 1, (
        f"release should have removed 1 entry; got {release_response!r}"
    )
    assert len(service.scheduler) == pre_release_size - 1, (
        "release response indicated success, but the service scheduler "
        f"size did not drop ({pre_release_size} -> {len(service.scheduler)})"
    )
