from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

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
    monkeypatch.setattr("famou.process_ownership.os.getpgid", lambda _pid: 654)
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
    monkeypatch.setattr("famou.process_ownership.os.getpgid", lambda _pid: 654)
    monkeypatch.setattr("famou.process_ownership._group_alive", lambda _pgid: True)
    monkeypatch.setattr("famou.process_ownership.os.killpg", lambda *_args: pytest.fail("must not signal"))
    result = cleanup_registered_process(registration)
    assert result.status is ProcessCleanupStatus.OWNER_CHECK_FAILED


def test_database_owner_cannot_override_os_process_group_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    registration = RegisteredProcess(321, 654, owner_check=lambda: True)
    monkeypatch.setattr("famou.process_ownership.os.getpgid", lambda _pid: 655)
    monkeypatch.setattr("famou.process_ownership._group_alive", lambda _pgid: True)
    monkeypatch.setattr("famou.process_ownership.os.killpg", lambda *_args: pytest.fail("must not signal"))

    result = cleanup_registered_process(registration)

    assert result.status is ProcessCleanupStatus.OWNERSHIP_LOST


def test_term_then_kill_after_grace(monkeypatch: pytest.MonkeyPatch) -> None:
    registration = RegisteredProcess(321, 654, owner_check=lambda: True)
    monkeypatch.setattr("famou.process_ownership.os.getpgid", lambda _pid: 654)
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


def test_missing_leader_never_grants_initial_signal_authority(monkeypatch):
    def missing(_pid):
        raise ProcessLookupError

    monkeypatch.setattr("famou.process_ownership.os.getpgid", missing)
    monkeypatch.setattr("famou.process_ownership._group_alive", lambda _pgid: True)
    monkeypatch.setattr("famou.process_ownership.os.killpg", lambda *_args: pytest.fail("must not signal"))

    result = cleanup_registered_process(RegisteredProcess(321, 321, owner_check=lambda: True))

    assert result.status is ProcessCleanupStatus.OWNERSHIP_LOST


@pytest.mark.parametrize("authority", ["replaced", "missing_callback", "reused_pid", "nonleader"])
def test_exited_leader_escalation_requires_unchanged_authority(monkeypatch, authority):
    pid, pgid = (321, 654) if authority == "nonleader" else (321, 321)
    probes = 0

    def getpgid(_pid):
        nonlocal probes
        probes += 1
        if probes <= (2 if authority == "missing_callback" else 1):
            return pgid
        if authority == "reused_pid":
            return pgid + 1
        raise ProcessLookupError

    owned = iter([True, False] if authority == "replaced" else [True, True])
    registration = RegisteredProcess(
        pid, pgid, owner_check=None if authority == "missing_callback" else lambda: next(owned),
    )
    monkeypatch.setattr("famou.process_ownership.os.getpgid", getpgid)
    monkeypatch.setattr("famou.process_ownership._group_alive", lambda _pgid: True)
    sent = []
    monkeypatch.setattr("famou.process_ownership.os.killpg", lambda _pgid, sig: sent.append(sig))
    clock = iter([0.0, 1.0])

    result = cleanup_registered_process(
        registration, grace_seconds=0.5, monotonic=lambda: next(clock),
    )

    assert result.status is ProcessCleanupStatus.OWNERSHIP_LOST
    assert sent == [signal.SIGTERM]


@pytest.mark.parametrize("failure", [
    ProcessCleanupStatus.OWNERSHIP_LOST,
    ProcessCleanupStatus.OWNER_CHECK_FAILED,
    ProcessCleanupStatus.CALLBACK_FAILED,
])
def test_failed_registration_does_not_block_same_group_fanout(failure):
    registrations = [
        RegisteredProcess(321, 321, label="stale"),
        RegisteredProcess(321, 321, label="current"),
    ]
    calls = []

    def cleanup(registration, *, grace_seconds):
        calls.append(registration.label)
        if registration.label == "stale" and failure is ProcessCleanupStatus.CALLBACK_FAILED:
            raise RuntimeError("private")
        status = failure if registration.label == "stale" else ProcessCleanupStatus.CLEANED
        return ProcessCleanupResult(registration.label, registration.pid, registration.pgid, status)

    results = cleanup_registered_processes(registrations, cleanup=cleanup)

    assert calls == ["stale", "current"]
    assert [result.status for result in results] == [failure, ProcessCleanupStatus.CLEANED]


def test_successful_same_group_cleanup_is_not_repeated():
    registrations = [RegisteredProcess(321, 321, label=label) for label in ("first", "second")]
    calls = []

    def cleanup(registration, *, grace_seconds):
        calls.append(registration.label)
        return ProcessCleanupResult(
            registration.label, registration.pid, registration.pgid,
            ProcessCleanupStatus.CLEANED, term_sent=True,
        )

    results = cleanup_registered_processes(registrations, cleanup=cleanup)

    assert calls == ["first"]
    assert [result.label for result in results] == ["first", "second"]
    assert all(result.status is ProcessCleanupStatus.CLEANED and result.term_sent for result in results)


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX process groups")
def test_real_group_member_is_killed_after_leader_is_reaped():
    # Both processes are direct test children so the test can reap them reliably even on
    # systems whose PID 1 does not promptly reap orphaned descendants. The group lifecycle
    # is identical: its leader exits on TERM while another member ignores TERM.
    leader = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], process_group=0)
    member = None
    try:
        member = subprocess.Popen(
            [sys.executable, "-c", (
                "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                "print('ready', flush=True); time.sleep(60)"
            )],
            process_group=leader.pid, stdout=subprocess.PIPE, text=True,
        )
        assert member.stdout is not None and member.stdout.readline() == "ready\n"

        def reap_and_sleep(delay):
            leader.wait(timeout=2)
            member.poll()
            time.sleep(delay)

        result = cleanup_registered_process(
            RegisteredProcess(leader.pid, leader.pid, owner_check=lambda: True),
            grace_seconds=0.1, sleep=reap_and_sleep,
        )

        assert result.status is ProcessCleanupStatus.CLEANED
        assert result.term_sent and result.kill_sent
        assert leader.returncode == -signal.SIGTERM
        assert member.wait(timeout=2) == -signal.SIGKILL
        with pytest.raises(ProcessLookupError):
            os.killpg(leader.pid, 0)
    finally:
        try:
            os.killpg(leader.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        leader.wait(timeout=2)
        if member is not None:
            member.wait(timeout=2)
            if member.stdout is not None:
                member.stdout.close()
