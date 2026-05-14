"""Transport-agnostic RPC shim for :class:`SharedScheduler`.

:class:`SharedScheduler` is in-process state. That's the right
boundary for the planner core, but it means *one* process owns the
authoritative view of who holds what — wire two agents through two
different Python processes and they each see their own empty
scheduler. Production deployments solve that by routing every claim /
release through a single coordination service (a long-running
process, a leader-elected coordinator, a serverless function, …)
that wraps one real scheduler.

This module ships the minimal contract for that. It is deliberately
transport-agnostic: there is no HTTP server, no gRPC stub, no
WebSocket loop. What's provided:

* :class:`SchedulerProtocol` — the public surface every scheduler-
  shaped object must satisfy. :class:`SharedScheduler` already
  matches it without changes; the new :class:`SchedulerClient` is
  the other implementation. ``plan_with_scheduler`` and
  ``plan_fleet`` accept either.
* :class:`Transport` — a single method, ``send(message: dict) ->
  dict``. Implement it over whatever wire format your deployment
  uses; the message bodies are plain JSON-serializable dicts.
* :class:`SchedulerService` — server-side wrapper. Construct it
  around a real :class:`SharedScheduler`, call ``handle(message)``
  on each incoming request, return the dict to the client.
* :class:`SchedulerClient` — client-side proxy. Holds a
  :class:`Transport`, marshals each scheduler method into a
  message, and reconstructs typed objects from the response.
* :class:`LocalTransport` — trivial in-process transport that
  routes straight into a :class:`SchedulerService`. Useful for
  tests, for development, and as the documented example of "this
  is what a transport implements".

The message contract uses ``HH:MM:SS`` strings for ``time`` values
so the dicts JSON-round-trip without losing precision. The same
midnight-wrap semantics as :func:`time_aware` and the in-memory
scheduler apply — an interval whose ``end <= start`` covers from
``start`` to ``23:59:59`` then ``00:00`` to ``end``.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, time
from typing import Any, Protocol, runtime_checkable

from semantic_toponav.coordination.scheduler import (
    ClaimRequest,
    ClaimResult,
    SchedulerError,
    SharedScheduler,
)
from semantic_toponav.planner.reservations import Reservation, ReservationTable
from semantic_toponav.planner.semantic_costs import _as_time


class RpcError(Exception):
    """Raised when an RPC payload can't be routed or its inputs are bad."""


# --- typed surface ------------------------------------------------------------


@runtime_checkable
class SchedulerProtocol(Protocol):
    """Methods required of any scheduler-shaped object.

    Both :class:`SharedScheduler` (already) and :class:`SchedulerClient`
    (new in this module) satisfy this Protocol. Planner entry points
    that previously typed their scheduler argument as
    :class:`SharedScheduler` should be readable / runnable against
    :class:`SchedulerClient` too — the duck-typing already works; the
    Protocol is the documented contract.
    """

    def claim(self, request: ClaimRequest) -> ClaimResult: ...

    def claim_many(
        self, requests: Iterable[ClaimRequest]
    ) -> list[ClaimResult]: ...

    def release(
        self,
        agent_id: str,
        resource_id: str,
        *,
        start: time | datetime | str | None = None,
        end: time | datetime | str | None = None,
    ) -> int: ...

    def release_all(self, agent_id: str) -> int: ...

    def reservations(self) -> list[Reservation]: ...

    def claims_for(self, agent_id: str) -> list[Reservation]: ...

    def conflicts(
        self,
        resource_id: str,
        start: time | datetime | str,
        end: time | datetime | str,
        *,
        exclude_agent: str | None = None,
    ) -> list[Reservation]: ...

    def table(self) -> ReservationTable: ...

    def __len__(self) -> int: ...


@runtime_checkable
class Transport(Protocol):
    """One-shot request/response transport for the RPC shim.

    Implementations marshal the dict to the wire (HTTP, WebSocket,
    NATS, …) and return the response dict synchronously. Async
    transports can wrap this Protocol behind a thin synchronous
    adapter; keeping the contract sync keeps the planner code simple.
    """

    def send(self, message: dict) -> dict: ...


# --- (de)serialization helpers -----------------------------------------------


def _time_to_str(t: time) -> str:
    return t.strftime("%H:%M:%S")


def _str_to_time(s: str) -> time:
    return _as_time(s)


def _reservation_to_dict(r: Reservation) -> dict:
    return {
        "resource_id": r.resource_id,
        "start": _time_to_str(r.start),
        "end": _time_to_str(r.end),
        "agent_id": r.agent_id,
    }


def _reservation_from_dict(d: dict) -> Reservation:
    return Reservation(
        resource_id=d["resource_id"],
        start=_str_to_time(d["start"]),
        end=_str_to_time(d["end"]),
        agent_id=d.get("agent_id"),
    )


def _claim_request_to_dict(req: ClaimRequest) -> dict:
    return {
        "agent_id": req.agent_id,
        "resource_id": req.resource_id,
        "start": _time_to_str(req.start),
        "end": _time_to_str(req.end),
        "priority": req.priority,
    }


def _claim_request_from_dict(d: dict) -> ClaimRequest:
    return ClaimRequest(
        agent_id=d["agent_id"],
        resource_id=d["resource_id"],
        start=_str_to_time(d["start"]),
        end=_str_to_time(d["end"]),
        priority=int(d.get("priority", 0)),
    )


def _claim_result_to_dict(res: ClaimResult) -> dict:
    return {
        "granted": res.granted,
        "reservation": (
            _reservation_to_dict(res.reservation)
            if res.reservation is not None
            else None
        ),
        "conflicts": [_reservation_to_dict(r) for r in res.conflicts],
        "preempted": [_reservation_to_dict(r) for r in res.preempted],
    }


def _claim_result_from_dict(d: dict) -> ClaimResult:
    return ClaimResult(
        granted=bool(d["granted"]),
        reservation=(
            _reservation_from_dict(d["reservation"])
            if d.get("reservation")
            else None
        ),
        conflicts=[_reservation_from_dict(r) for r in d.get("conflicts", [])],
        preempted=[_reservation_from_dict(r) for r in d.get("preempted", [])],
    )


# --- server side --------------------------------------------------------------


class SchedulerService:
    """Server-side wrapper: route JSON messages to a real scheduler.

    Wrap one :class:`SharedScheduler` instance; call
    :meth:`handle` on every incoming request payload. The service
    returns a dict; the caller serializes it to the transport's wire
    format.

    The supported ``op`` values cover the full :class:`SchedulerProtocol`
    surface, plus a ``"ping"`` health-check that returns
    ``{"ok": True, "size": len(scheduler)}``.
    """

    def __init__(self, scheduler: SharedScheduler) -> None:
        self._scheduler = scheduler

    @property
    def scheduler(self) -> SharedScheduler:
        """The wrapped scheduler. Useful for tests that need to inspect
        live state without round-tripping through a transport."""
        return self._scheduler

    def handle(self, message: dict) -> dict:
        op = message.get("op")
        if not isinstance(op, str):
            raise RpcError(
                f"message missing string `op` field; got {message!r}"
            )
        method = getattr(self, f"_op_{op}", None)
        if method is None:
            raise RpcError(f"unknown op {op!r}")
        try:
            return method(message)
        except SchedulerError as exc:
            return {"error": str(exc), "kind": "SchedulerError"}

    # ----- op handlers --------------------------------------------------

    def _op_ping(self, _message: dict) -> dict:
        return {"ok": True, "size": len(self._scheduler)}

    def _op_claim(self, message: dict) -> dict:
        req = _claim_request_from_dict(message["request"])
        return {"result": _claim_result_to_dict(self._scheduler.claim(req))}

    def _op_claim_many(self, message: dict) -> dict:
        reqs = [_claim_request_from_dict(r) for r in message["requests"]]
        results = self._scheduler.claim_many(reqs)
        return {"results": [_claim_result_to_dict(r) for r in results]}

    def _op_release(self, message: dict) -> dict:
        start = message.get("start")
        end = message.get("end")
        removed = self._scheduler.release(
            message["agent_id"],
            message["resource_id"],
            start=_str_to_time(start) if start else None,
            end=_str_to_time(end) if end else None,
        )
        return {"removed": removed}

    def _op_release_all(self, message: dict) -> dict:
        return {"removed": self._scheduler.release_all(message["agent_id"])}

    def _op_reservations(self, _message: dict) -> dict:
        return {
            "reservations": [
                _reservation_to_dict(r) for r in self._scheduler.reservations()
            ]
        }

    def _op_claims_for(self, message: dict) -> dict:
        return {
            "reservations": [
                _reservation_to_dict(r)
                for r in self._scheduler.claims_for(message["agent_id"])
            ]
        }

    def _op_conflicts(self, message: dict) -> dict:
        return {
            "reservations": [
                _reservation_to_dict(r)
                for r in self._scheduler.conflicts(
                    message["resource_id"],
                    _str_to_time(message["start"]),
                    _str_to_time(message["end"]),
                    exclude_agent=message.get("exclude_agent"),
                )
            ]
        }

    def _op_table(self, _message: dict) -> dict:
        table = self._scheduler.table()
        return {
            "entries": [_reservation_to_dict(r) for r in table.entries],
        }

    def _op_len(self, _message: dict) -> dict:
        return {"size": len(self._scheduler)}


# --- in-process reference transport ------------------------------------------


class LocalTransport:
    """Trivial in-process :class:`Transport`.

    Wraps a :class:`SchedulerService` and routes every ``send`` call
    straight into ``service.handle(message)``. Useful in tests, in
    development, and as the canonical example of "this is the shape a
    real Transport implements". Production transports replace this
    with HTTP / WebSocket / NATS / gRPC / your custom message bus.
    """

    def __init__(self, service: SchedulerService) -> None:
        self._service = service

    def send(self, message: dict) -> dict:
        return self._service.handle(message)


# --- client side --------------------------------------------------------------


class SchedulerClient:
    """Client-side proxy that talks to a :class:`SchedulerService` via a
    :class:`Transport`.

    Has the same public surface as :class:`SharedScheduler` (modulo
    ``clone`` / ``clear``, which only make sense locally). Every call
    marshals into a message, ships it through the transport, and
    reconstructs typed objects from the response. Planner code that
    accepted a :class:`SharedScheduler` works against this class
    unchanged — both satisfy :class:`SchedulerProtocol`.
    """

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def _send(self, message: dict) -> dict:
        response = self._transport.send(message)
        if "error" in response:
            raise RpcError(
                f"{response.get('kind', 'RpcError')}: {response['error']}"
            )
        return response

    def ping(self) -> int:
        """Health-check. Returns the current scheduler size."""
        response = self._send({"op": "ping"})
        return int(response["size"])

    # ----- SchedulerProtocol methods ------------------------------------

    def claim(self, request: ClaimRequest) -> ClaimResult:
        response = self._send(
            {"op": "claim", "request": _claim_request_to_dict(request)}
        )
        return _claim_result_from_dict(response["result"])

    def claim_many(
        self, requests: Iterable[ClaimRequest]
    ) -> list[ClaimResult]:
        response = self._send(
            {
                "op": "claim_many",
                "requests": [_claim_request_to_dict(r) for r in requests],
            }
        )
        return [_claim_result_from_dict(r) for r in response["results"]]

    def release(
        self,
        agent_id: str,
        resource_id: str,
        *,
        start: time | datetime | str | None = None,
        end: time | datetime | str | None = None,
    ) -> int:
        payload: dict[str, Any] = {
            "op": "release",
            "agent_id": agent_id,
            "resource_id": resource_id,
        }
        if start is not None:
            payload["start"] = _time_to_str(_as_time(start))
        if end is not None:
            payload["end"] = _time_to_str(_as_time(end))
        response = self._send(payload)
        return int(response["removed"])

    def release_all(self, agent_id: str) -> int:
        response = self._send({"op": "release_all", "agent_id": agent_id})
        return int(response["removed"])

    def reservations(self) -> list[Reservation]:
        response = self._send({"op": "reservations"})
        return [_reservation_from_dict(r) for r in response["reservations"]]

    def claims_for(self, agent_id: str) -> list[Reservation]:
        response = self._send({"op": "claims_for", "agent_id": agent_id})
        return [_reservation_from_dict(r) for r in response["reservations"]]

    def conflicts(
        self,
        resource_id: str,
        start: time | datetime | str,
        end: time | datetime | str,
        *,
        exclude_agent: str | None = None,
    ) -> list[Reservation]:
        payload: dict[str, Any] = {
            "op": "conflicts",
            "resource_id": resource_id,
            "start": _time_to_str(_as_time(start)),
            "end": _time_to_str(_as_time(end)),
        }
        if exclude_agent is not None:
            payload["exclude_agent"] = exclude_agent
        response = self._send(payload)
        return [_reservation_from_dict(r) for r in response["reservations"]]

    def table(self) -> ReservationTable:
        response = self._send({"op": "table"})
        out = ReservationTable()
        out.extend(_reservation_from_dict(entry) for entry in response["entries"])
        return out

    def __len__(self) -> int:
        response = self._send({"op": "len"})
        return int(response["size"])

    def __iter__(self):
        return iter(self.reservations())
