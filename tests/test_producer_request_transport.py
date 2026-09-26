from __future__ import annotations

import os

import pytest

import lunar_evolution.producer_request_transport as transport
from lunar_evolution import (
    ControllerOwnedRequestBroker,
    ControllerRequestBrokerError,
    HostRequestJournal,
    HostRequestJournalIdentity,
    HostRequestLedger,
    ProducerRequestTransportError,
    RequestAdmission,
    read_host_request_journal,
)


class Clock:
    def __init__(self) -> None:
        self.value = 1_000_000_000

    def __call__(self) -> int:
        return self.value


class ImmediateHandle:
    def __init__(self, status: str = "completed") -> None:
        self.status = status
        self.waits: list[float] = []
        self.cancelled = False

    def wait(self, timeout_seconds: float) -> str:
        self.waits.append(timeout_seconds)
        return self.status

    def cancel(self) -> bool:
        self.cancelled = True
        return True


class CancelOnDeadlineHandle:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.waits: list[float] = []
        self.cancelled = False

    def wait(self, timeout_seconds: float) -> str | None:
        self.waits.append(timeout_seconds)
        if not self.cancelled:
            self.clock.value += 1_000_000_000
            return None
        return "cancelled"

    def cancel(self) -> bool:
        self.cancelled = True
        return True


class NonCancellableHandle:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock

    def wait(self, _timeout_seconds: float) -> None:
        self.clock.value += 1_000_000_000

    def cancel(self) -> bool:
        return False


class RecordingTransport:
    def __init__(self, handle_factory) -> None:
        self.handle_factory = handle_factory
        self.admissions: list[RequestAdmission] = []
        self.payloads: list[object] = []

    def start(self, admission: RequestAdmission, payload: object):
        self.admissions.append(admission)
        self.payloads.append(payload)
        return self.handle_factory()


def _identity() -> HostRequestJournalIdentity:
    return HostRequestJournalIdentity(
        launch_id="launch-001", journal_id="journal-001", run_id="run-001",
        parent_task_id="parent-001", task_id="task-001", intent_sha256="a" * 64,
        request_timeout_seconds=1, max_requests=2,
    )


def _error(code: str, operation) -> None:
    with pytest.raises(ProducerRequestTransportError) as exc:
        operation()
    assert exc.value.code == code


def test_admission_counts_before_io_and_denies_over_budget():
    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=2, max_requests=1, monotonic_ns=clock)
    admission = ledger.admit("request-001")
    assert admission.deadline_ns == clock.value + 2_000_000_000
    assert ledger.snapshot().admitted_count == 1
    assert ledger.snapshot().active_count == 1
    _error("producer_request_transport_budget_exceeded", lambda: ledger.admit("request-002"))
    clock.value += 1_250_000
    event = ledger.finish(admission, status="completed")
    assert (event.sequence, event.status, event.duration_ms) == (1, "completed", 2)
    assert ledger.snapshot().within_broker_limits
    assert ledger.snapshot().coverage == "brokered_requests_only"
    assert ledger.snapshot().clock_source == "controller_monotonic"


def test_host_clock_marks_late_completion_and_expiration():
    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=2, monotonic_ns=clock)
    first = ledger.admit("request-001")
    clock.value += 1_000_000_000
    event = ledger.finish(first, status="completed")
    assert (event.status, event.duration_ms) == ("timed_out", 1000)
    second = ledger.admit("request-002")
    clock.value += 1_000_000_001
    assert ledger.expire()[0].status == "timed_out"
    assert ledger.snapshot().active_count == 0
    assert not ledger.snapshot().within_broker_limits
    _error(
        "producer_request_transport_admission_invalid",
        lambda: ledger.finish(second, status="completed"),
    )


def test_out_of_order_completion_preserves_admission_sequence():
    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=2, monotonic_ns=clock)
    first = ledger.admit("request-001")
    second = ledger.admit("request-002")
    ledger.finish(second, status="failed")
    ledger.finish(first, status="completed")
    assert [(item.sequence, item.status) for item in ledger.snapshot().events] == [
        (1, "completed"), (2, "failed"),
    ]


def test_forged_or_reused_admission_cannot_finish_a_request():
    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=2, monotonic_ns=clock)
    admission = ledger.admit("request-001")
    forged = RequestAdmission(1, "request-001", admission.started_ns, admission.deadline_ns)
    _error("producer_request_transport_admission_invalid", lambda: ledger.finish(forged, status="completed"))
    _error("producer_request_transport_request_id_duplicate", lambda: ledger.admit("request-001"))
    _error("producer_request_transport_status_invalid", lambda: ledger.finish(admission, status="timed_out"))
    _error("producer_request_transport_status_invalid", lambda: ledger.finish(admission, status=[]))
    assert ledger.snapshot().active_count == 1
    ledger.finish(admission, status="cancelled")
    _error("producer_request_transport_admission_invalid", lambda: ledger.finish(admission, status="completed"))


@pytest.mark.parametrize(
    ("timeout", "budget", "code"),
    [
        (True, 1, "producer_request_transport_timeout_invalid"),
        (0, 1, "producer_request_transport_timeout_invalid"),
        (1, True, "producer_request_transport_budget_invalid"),
        (1, 16_385, "producer_request_transport_budget_invalid"),
    ],
)
def test_invalid_limits_fail_closed(timeout, budget, code):
    _error(code, lambda: HostRequestLedger(request_timeout_seconds=timeout, max_requests=budget))


def test_untrusted_id_and_bad_clock_fail_closed():
    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=2, monotonic_ns=clock)
    _error("producer_request_transport_request_id_invalid", lambda: ledger.admit("a" * 129))
    _error("producer_request_transport_request_id_invalid", lambda: ledger.admit("bad/id"))
    clock.value = -1
    _error("producer_request_transport_clock_invalid", lambda: ledger.admit("request-001"))
    assert ledger.snapshot().admitted_count == 0


def test_clock_regression_and_callback_exception_preserve_active_request():
    clock = Clock()
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=clock)
    admission = ledger.admit("request-001")
    clock.value -= 1
    _error("producer_request_transport_clock_invalid", lambda: ledger.finish(admission, status="completed"))
    assert ledger.snapshot().active_count == 1
    clock.value += 1
    ledger.finish(admission, status="completed")

    def broken_clock() -> int:
        raise RuntimeError("clock unavailable")

    broken = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=broken_clock)
    _error("producer_request_transport_clock_invalid", lambda: broken.admit("request-001"))
    assert broken.snapshot().admitted_count == 0


def test_durable_journal_replays_completed_and_uncertain_requests(tmp_path):
    path = tmp_path / "requests.log"
    identity = _identity()
    clock = Clock()
    with HostRequestJournal.create(path, identity) as journal:
        ledger = HostRequestLedger(
            request_timeout_seconds=1, max_requests=2, monotonic_ns=clock, journal=journal,
        )
        first = ledger.admit("request-001")
        ledger.admit("request-002")
        clock.value += 125_000_000
        ledger.finish(first, status="completed")
    assert os.stat(path).st_mode & 0o777 == 0o600
    recovery = read_host_request_journal(path, expected_identity=identity)
    assert recovery.snapshot.admitted_count == 2
    assert recovery.snapshot.active_count == 1
    assert [(event.sequence, event.status, event.duration_ms) for event in recovery.snapshot.events] == [
        (1, "completed", 125),
    ]
    assert recovery.uncertain_request_ids == ("request-002",)
    assert not recovery.snapshot.within_broker_limits


def test_journal_recovery_checks_identity_and_detects_tampering(tmp_path):
    path = tmp_path / "requests.log"
    identity = _identity()
    clock = Clock()
    with HostRequestJournal.create(path, identity) as journal:
        ledger = HostRequestLedger(
            request_timeout_seconds=1, max_requests=2, monotonic_ns=clock, journal=journal,
        )
        admission = ledger.admit("request-001")
        ledger.finish(admission, status="completed")
    wrong = HostRequestJournalIdentity(**{**identity.to_dict(), "task_id": "task-002"})
    _error(
        "producer_request_transport_journal_binding_mismatch",
        lambda: read_host_request_journal(path, expected_identity=wrong),
    )
    original = path.read_bytes()
    path.write_bytes(original.replace(b"request-001", b"request-999"))
    _error(
        "producer_request_transport_journal_invalid",
        lambda: read_host_request_journal(path, expected_identity=identity),
    )
    path.write_bytes(original[:-1])
    _error(
        "producer_request_transport_journal_invalid",
        lambda: read_host_request_journal(path, expected_identity=identity),
    )


def test_journal_rejects_existing_path_and_symbolic_links(tmp_path):
    identity = _identity()
    path = tmp_path / "requests.log"
    with HostRequestJournal.create(path, identity):
        pass
    _error(
        "producer_request_transport_journal_path_invalid",
        lambda: HostRequestJournal.create(path, identity),
    )
    alias = tmp_path / "alias.log"
    alias.symlink_to(path)
    _error(
        "producer_request_transport_journal_path_invalid",
        lambda: read_host_request_journal(alias, expected_identity=identity),
    )
    directory = tmp_path / "real"
    directory.mkdir()
    ancestor_link = tmp_path / "alias"
    ancestor_link.symlink_to(directory, target_is_directory=True)
    _error(
        "producer_request_transport_journal_path_invalid",
        lambda: HostRequestJournal.create(ancestor_link / "new.log", identity),
    )


def test_journal_write_failure_poison_and_does_not_advance_ledger(tmp_path, monkeypatch):
    path = tmp_path / "requests.log"
    clock = Clock()
    with HostRequestJournal.create(path, _identity()) as journal:
        ledger = HostRequestLedger(
            request_timeout_seconds=1, max_requests=2, monotonic_ns=clock, journal=journal,
        )

        def fail_sync(_fd: int) -> None:
            raise OSError("fixture sync failure")

        monkeypatch.setattr(transport.os, "fsync", fail_sync)
        _error("producer_request_transport_journal_write_failed", lambda: ledger.admit("request-001"))
        assert ledger.snapshot().admitted_count == 0
        _error("producer_request_transport_journal_unavailable", lambda: ledger.admit("request-001"))


def test_terminal_write_failure_leaves_request_active(tmp_path, monkeypatch):
    clock = Clock()
    with HostRequestJournal.create(tmp_path / "requests.log", _identity()) as journal:
        ledger = HostRequestLedger(
            request_timeout_seconds=1, max_requests=2, monotonic_ns=clock, journal=journal,
        )
        admission = ledger.admit("request-001")

        def fail_sync(_fd: int) -> None:
            raise OSError("fixture sync failure")

        monkeypatch.setattr(transport.os, "fsync", fail_sync)
        _error(
            "producer_request_transport_journal_write_failed",
            lambda: ledger.finish(admission, status="completed"),
        )
        assert ledger.snapshot().active_count == 1
        assert ledger.snapshot().events == ()


def test_journal_size_limit_denies_admission_before_state_change(tmp_path, monkeypatch):
    path = tmp_path / "requests.log"
    with HostRequestJournal.create(path, _identity()) as journal:
        monkeypatch.setattr(transport, "MAX_HOST_REQUEST_JOURNAL_BYTES", journal._size + 1)
        ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=2, journal=journal)
        _error("producer_request_transport_journal_too_large", lambda: ledger.admit("request-001"))
        assert ledger.snapshot().admitted_count == 0


def test_journal_cannot_bind_to_two_ledgers(tmp_path):
    with HostRequestJournal.create(tmp_path / "requests.log", _identity()) as journal:
        HostRequestLedger(request_timeout_seconds=1, max_requests=2, journal=journal)
        _error(
            "producer_request_transport_journal_unavailable",
            lambda: HostRequestLedger(request_timeout_seconds=1, max_requests=2, journal=journal),
        )


def test_controller_broker_admits_before_transport_and_forwards_deadline():
    clock = Clock()
    handle = ImmediateHandle()
    transport = RecordingTransport(lambda: handle)
    ledger = HostRequestLedger(request_timeout_seconds=2, max_requests=1, monotonic_ns=clock)
    result = ControllerOwnedRequestBroker(
        ledger, transport, monotonic_ns=clock, cancel_grace_seconds=0.1,
    ).execute("request-001", {"opaque": True})
    assert transport.payloads == [{"opaque": True}]
    assert transport.admissions[0].deadline_ns == clock.value + 2_000_000_000
    assert handle.waits == [2.0]
    assert result.event.status == "completed"
    assert not result.host_timeout_enforced


def test_controller_broker_requires_cancel_ack_and_terminal_confirmation():
    clock = Clock()
    handle = CancelOnDeadlineHandle(clock)
    transport = RecordingTransport(lambda: handle)
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=clock)
    result = ControllerOwnedRequestBroker(
        ledger, transport, monotonic_ns=clock, cancel_grace_seconds=0.1,
    ).execute("request-001", None)
    assert result.event.status == "timed_out"
    assert result.cancellation_requested and result.cancellation_acknowledged
    assert result.host_timeout_enforced
    assert ledger.snapshot().active_count == 0


def test_controller_broker_keeps_unconfirmed_timeout_fail_closed():
    clock = Clock()
    transport = RecordingTransport(lambda: NonCancellableHandle(clock))
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=clock)
    with pytest.raises(ControllerRequestBrokerError) as exc:
        ControllerOwnedRequestBroker(
            ledger, transport, monotonic_ns=clock, cancel_grace_seconds=0.1,
        ).execute("request-001", None)
    assert exc.value.code == "producer_request_broker_timeout_unconfirmed"
    assert exc.value.event is not None and exc.value.event.status == "timed_out"
    assert ledger.snapshot().active_count == 0


def test_controller_broker_rejects_handle_without_cancellation():
    class WaitOnly:
        def wait(self, _timeout_seconds: float) -> str:
            return "completed"

    clock = Clock()
    transport = RecordingTransport(WaitOnly)
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=clock)
    with pytest.raises(ControllerRequestBrokerError) as exc:
        ControllerOwnedRequestBroker(ledger, transport, monotonic_ns=clock).execute("request-001", None)
    assert exc.value.code == "producer_request_broker_handle_invalid"
    assert exc.value.event is not None and exc.value.event.status == "failed"


def test_controller_broker_rejects_unhashable_transport_status():
    class BadStatus:
        def wait(self, _timeout_seconds: float):
            return []

        def cancel(self) -> bool:
            return True

    clock = Clock()
    transport = RecordingTransport(BadStatus)
    ledger = HostRequestLedger(request_timeout_seconds=1, max_requests=1, monotonic_ns=clock)
    with pytest.raises(ControllerRequestBrokerError) as exc:
        ControllerOwnedRequestBroker(ledger, transport, monotonic_ns=clock).execute("request-001", None)
    assert exc.value.code == "producer_request_broker_status_invalid"
    assert exc.value.event is not None and exc.value.event.status == "failed"
