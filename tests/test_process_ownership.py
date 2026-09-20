from __future__ import annotations

import signal

import pytest

from famou.process_ownership import (
    ProcessCleanupResult,
    ProcessCleanupStatus,
    RegisteredProcess,
    cleanup_registered_process,
    cleanup_registered_processes,
)


def test_ownership_loss_prevents_sigterm(monkeypatch: pytest.MonkeyPatch) -> None:
    registration = RegisteredProcess(321, 654, owner_check=lambda: False, label="lost")
    monkeypatch.setattr("famou.process_ownership._group_alive", lambda _pgid: True)
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr("famou.process_ownership.os.killpg", lambda pgid, sig: sent.append((pgid, sig)))
    result = cleanup_registered_process(registration)
    assert result.status is ProcessCleanupStatus.OWNERSHIP_LOST
    assert not sent


def test_owner_callback_failure_is_classified_without_signalling(monkeypatch: pytest.MonkeyPatch) -> None:
    def owner_check() -> bool:
        raise RuntimeError("private")

    registration = RegisteredProcess(321, 654, owner_check=owner_check)
    monkeypatch.setattr("famou.process_ownership._group_alive", lambda _pgid: True)
    monkeypatch.setattr("famou.process_ownership.os.killpg", lambda *_args: pytest.fail("must not signal"))
    result = cleanup_registered_process(registration)
    assert result.status is ProcessCleanupStatus.OWNER_CHECK_FAILED


def test_term_then_kill_after_grace(monkeypatch: pytest.MonkeyPatch) -> None:
    registration = RegisteredProcess(321, 654, owner_check=lambda: True)
    alive = iter([True, True, True, False])
    monkeypatch.setattr("famou.process_ownership._group_alive", lambda _pgid: next(alive))
    sent: list[tuple[int, int]] = []
    monkeypatch.setattr("famou.process_ownership.os.killpg", lambda pgid, sig: sent.append((pgid, sig)))
    clock = iter([0.0, 0.0, 1.0, 1.0])
    result = cleanup_registered_process(registration, grace_seconds=0.5, sleep=lambda _delay: None,
                                        monotonic=lambda: next(clock))
    assert result.status is ProcessCleanupStatus.CLEANED
    assert sent == [(654, signal.SIGTERM), (654, signal.SIGKILL)]
    assert result.term_sent and result.kill_sent


def test_fanout_continues_after_callback_failure() -> None:
    registrations = [RegisteredProcess(1, 2, label="first"), RegisteredProcess(3, 4, label="second")]
    calls: list[str] = []

    def cleanup(registration: RegisteredProcess, *, grace_seconds: float) -> ProcessCleanupResult:
        calls.append(registration.label)
        if registration.label == "first":
            raise RuntimeError("private")
        return ProcessCleanupResult(registration.label, registration.pid, registration.pgid,
                                    ProcessCleanupStatus.CLEANED)

    results = cleanup_registered_processes(registrations, cleanup=cleanup)
    assert calls == ["first", "second"]
    assert [item.status for item in results] == [
        ProcessCleanupStatus.CALLBACK_FAILED, ProcessCleanupStatus.CLEANED,
    ]


@pytest.mark.parametrize("status", [ProcessCleanupStatus.INVALID_REGISTRATION,
                                     ProcessCleanupStatus.ALREADY_EXITED])
def test_invalid_or_exited_registration_is_classified(monkeypatch: pytest.MonkeyPatch, status: ProcessCleanupStatus) -> None:
    if status is ProcessCleanupStatus.INVALID_REGISTRATION:
        registration = RegisteredProcess(1, 2)
    else:
        registration = RegisteredProcess(321, 654, owner_check=lambda: True)
        monkeypatch.setattr("famou.process_ownership._group_alive", lambda _pgid: False)
    assert cleanup_registered_process(registration).status is status
