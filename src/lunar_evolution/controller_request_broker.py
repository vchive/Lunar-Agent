"""Controller-owned request execution boundary.

The request ledger records controller observations, but it cannot interrupt an
arbitrary blocking callable.  This module adds the small transport contract
needed by a controlled runtime: a transport returns a handle with explicit
``wait`` and ``cancel`` operations.  A timeout is host-enforced only after the
handle acknowledges cancellation and reaches a terminal state.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .producer_request_transport import (
    HostRequestEvent,
    HostRequestLedger,
    RequestAdmission,
)

_MAX_CANCEL_GRACE_SECONDS = 60.0
_TERMINAL = frozenset({"completed", "failed", "cancelled"})


class ControllerRequestBrokerError(ValueError):
    """Fixed-code failure at the controller-owned transport boundary."""

    def __init__(self, code: str, *, event: HostRequestEvent | None = None) -> None:
        self.code = code
        self.event = event
        super().__init__(code)


class ControllerRequestHandle(Protocol):
    """Controlled transport handle with host-visible cancellation."""

    def wait(self, timeout_seconds: float) -> str | None:
        """Return a terminal status, or ``None`` while the request is active."""

    def cancel(self) -> bool:
        """Request cancellation and report whether the transport accepted it."""


class ControllerRequestTransport(Protocol):
    """Transport owned by the controller, not by the producer process."""

    def start(self, admission: RequestAdmission, payload: object) -> ControllerRequestHandle:
        """Start I/O only after the controller has durably admitted the request."""


@dataclass(frozen=True, slots=True)
class BrokerRequestResult:
    """Controller observation for one request handled by a controlled transport."""

    admission: RequestAdmission
    event: HostRequestEvent
    cancellation_requested: bool
    cancellation_acknowledged: bool
    host_timeout_enforced: bool


class ControllerOwnedRequestBroker:
    """Run requests through a transport that exposes cancellation semantics.

    The broker never stores ``payload``.  A transport that cannot acknowledge
    cancellation is rejected as uncertain at the deadline; the result cannot be
    upgraded to host-enforced evidence by polling after the call returns.
    """

    def __init__(
        self,
        ledger: HostRequestLedger,
        transport: ControllerRequestTransport,
        *,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        cancel_grace_seconds: float = 0.1,
    ) -> None:
        if type(ledger) is not HostRequestLedger:
            raise ControllerRequestBrokerError("producer_request_broker_ledger_invalid")
        if not callable(getattr(transport, "start", None)):
            raise ControllerRequestBrokerError("producer_request_broker_transport_invalid")
        if (
            type(cancel_grace_seconds) is not float
            or not math.isfinite(cancel_grace_seconds)
            or not 0.0 < cancel_grace_seconds <= _MAX_CANCEL_GRACE_SECONDS
        ):
            raise ControllerRequestBrokerError("producer_request_broker_cancel_grace_invalid")
        if not callable(monotonic_ns):
            raise ControllerRequestBrokerError("producer_request_broker_clock_invalid")
        self._ledger = ledger
        self._transport = transport
        self._clock = monotonic_ns
        self._cancel_grace_seconds = cancel_grace_seconds

    def execute(self, request_id: str, payload: object) -> BrokerRequestResult:
        """Admit, run, and finish one controller-owned request.

        The transport receives the exact controller-issued admission, including
        its deadline.  Invalid transport behavior fails the request before any
        result can be treated as complete.
        """
        admission = self._ledger.admit(request_id)
        try:
            handle = self._transport.start(admission, payload)
        except Exception as exc:
            event = self._finish_failed(admission)
            raise ControllerRequestBrokerError(
                "producer_request_broker_transport_start_failed", event=event,
            ) from exc
        if not callable(getattr(handle, "wait", None)) or not callable(getattr(handle, "cancel", None)):
            event = self._finish_failed(admission)
            raise ControllerRequestBrokerError(
                "producer_request_broker_handle_invalid", event=event,
            )

        remaining = self._remaining_seconds(admission)
        try:
            status = handle.wait(remaining)
        except Exception as exc:
            event = self._finish_failed(admission)
            raise ControllerRequestBrokerError(
                "producer_request_broker_wait_failed", event=event,
            ) from exc
        if type(status) is str and status in _TERMINAL:
            event = self._finish(admission, status)
            return BrokerRequestResult(admission, event, False, False, False)
        if status is not None:
            event = self._finish_failed(admission)
            raise ControllerRequestBrokerError(
                "producer_request_broker_status_invalid", event=event,
            )

        # The transport did not finish before the controller deadline.  A
        # cancellation acknowledgement and terminal confirmation are both
        # required before this becomes host-observed timeout evidence.
        try:
            acknowledged = handle.cancel() is True
        except Exception as exc:  # noqa: BLE001 - cancellation failures are boundary errors
            acknowledged = False
            cancel_error = exc
        else:
            cancel_error = None
        if not acknowledged:
            event = self._expire(admission)
            error = ControllerRequestBrokerError(
                "producer_request_broker_timeout_unconfirmed", event=event,
            )
            if cancel_error is not None:
                raise error from cancel_error
            raise error
        try:
            terminal = handle.wait(self._cancel_grace_seconds)
        except Exception as exc:
            event = self._expire(admission)
            raise ControllerRequestBrokerError(
                "producer_request_broker_cancellation_wait_failed", event=event,
            ) from exc
        if terminal not in _TERMINAL:
            event = self._expire(admission)
            raise ControllerRequestBrokerError(
                "producer_request_broker_timeout_unconfirmed", event=event,
            )
        event = self._expire(admission)
        if event is None:
            # The controller clock did not reach the admission deadline, so a
            # transport cannot manufacture host timeout evidence by returning
            # ``cancelled`` early.
            event = self._finish(admission, "cancelled")
            raise ControllerRequestBrokerError(
                "producer_request_broker_deadline_not_reached", event=event,
            )
        return BrokerRequestResult(admission, event, True, True, event.status == "timed_out")

    def _remaining_seconds(self, admission: RequestAdmission) -> float:
        try:
            now = self._clock()
        except Exception as exc:
            event = self._finish_failed(admission)
            raise ControllerRequestBrokerError(
                "producer_request_broker_clock_invalid", event=event,
            ) from exc
        if type(now) is not int or now < admission.started_ns or now > 2**63 - 1:
            event = self._finish_failed(admission)
            raise ControllerRequestBrokerError(
                "producer_request_broker_clock_invalid", event=event,
            )
        return max(0.0, (admission.deadline_ns - now) / 1_000_000_000)

    def _finish(self, admission: RequestAdmission, status: str) -> HostRequestEvent:
        try:
            return self._ledger.finish(admission, status=status)
        except Exception as exc:
            raise ControllerRequestBrokerError("producer_request_broker_finish_failed") from exc

    def _finish_failed(self, admission: RequestAdmission) -> HostRequestEvent:
        return self._finish(admission, "failed")

    def _expire(self, admission: RequestAdmission) -> HostRequestEvent | None:
        try:
            expired = self._ledger.expire(admission=admission)
        except Exception as exc:
            raise ControllerRequestBrokerError("producer_request_broker_expire_failed") from exc
        for event in expired:
            if event.sequence == admission.sequence:
                return event
        return None


__all__ = [
    "BrokerRequestResult",
    "ControllerOwnedRequestBroker",
    "ControllerRequestBrokerError",
    "ControllerRequestHandle",
    "ControllerRequestTransport",
]
