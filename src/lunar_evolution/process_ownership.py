"""Fail-closed cleanup primitives for locally owned process groups.

The controller records a PID and process-group ID before it starts work.  This module only
operates on that exact registration: it rechecks ownership before each signal, gives SIGTERM a
bounded grace period, and escalates to SIGKILL only while ownership still holds.  The fan-out
helper deliberately turns one target's callback/OS failure into a result so other registrations
are still attempted.
"""

from __future__ import annotations

import errno
import os
import signal
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum

DEFAULT_CLEANUP_GRACE_SECONDS = 0.25
MAX_CLEANUP_GRACE_SECONDS = 30.0


class ProcessCleanupStatus(StrEnum):
    CLEANED = "cleaned"
    ALREADY_EXITED = "already_exited"
    OWNERSHIP_LOST = "ownership_lost"
    OWNER_CHECK_FAILED = "owner_check_failed"
    INVALID_REGISTRATION = "invalid_registration"
    TERM_FAILED = "term_failed"
    KILL_FAILED = "kill_failed"
    PROBE_FAILED = "probe_failed"
    CLEANUP_UNVERIFIED = "cleanup_unverified"
    CALLBACK_FAILED = "callback_failed"


@dataclass(frozen=True)
class RegisteredProcess:
    """One persisted process identity and its current ownership predicate."""

    pid: int
    pgid: int
    owner_check: Callable[[], bool] | None = None
    label: str = ""


@dataclass(frozen=True)
class ProcessCleanupResult:
    label: str
    pid: int
    pgid: int
    status: ProcessCleanupStatus
    term_sent: bool = False
    kill_sent: bool = False
    alive_after: bool = False
    error: str | None = None


def _valid_registration(registration: RegisteredProcess) -> bool:
    return (
        isinstance(registration.pid, int)
        and not isinstance(registration.pid, bool)
        and registration.pid > 1
        and isinstance(registration.pgid, int)
        and not isinstance(registration.pgid, bool)
        and registration.pgid > 1
        and registration.pgid != os.getpgrp()
        and (registration.owner_check is None or callable(registration.owner_check))
    )


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return False
        if exc.errno == errno.EPERM:
            return True
        raise
    return True


def _default_owner_check(registration: RegisteredProcess) -> bool:
    """Verify the registered leader still belongs to the registered process group."""
    try:
        return os.getpgid(registration.pid) == registration.pgid
    except ProcessLookupError:
        return False


def _check_owner(
    registration: RegisteredProcess, *, allow_exited_leader: bool = False,
) -> tuple[bool, ProcessCleanupStatus | None]:
    # A durable database predicate is necessary but not sufficient: the OS identity must
    # still resolve to the same process group, otherwise a reused PID could receive a signal.
    try:
        os_owned = os.getpgid(registration.pid) == registration.pgid
    except ProcessLookupError:
        # The leader may have been reaped while descendants keep its group alive. POSIX
        # reserves that group ID until the group is empty. Callers may extend their earlier
        # ownership observation only for an actual private group leader with a live owner
        # predicate; a reused PID in another group still fails the OS check above.
        os_owned = (
            allow_exited_leader
            and registration.pid == registration.pgid
            and registration.owner_check is not None
        )
    except Exception:  # noqa: BLE001 - the OS boundary is fail-closed.
        return False, ProcessCleanupStatus.OWNER_CHECK_FAILED
    if not os_owned:
        return False, ProcessCleanupStatus.OWNERSHIP_LOST
    try:
        owned = (
            registration.owner_check()
            if registration.owner_check is not None
            else _default_owner_check(registration)
        )
    except Exception:  # noqa: BLE001 - owner callbacks are an external safety boundary.
        return False, ProcessCleanupStatus.OWNER_CHECK_FAILED
    if not isinstance(owned, bool):
        return False, ProcessCleanupStatus.OWNER_CHECK_FAILED
    return owned, None if owned else ProcessCleanupStatus.OWNERSHIP_LOST


def _result(registration: RegisteredProcess, status: ProcessCleanupStatus, **kwargs: object) -> ProcessCleanupResult:
    return ProcessCleanupResult(
        label=registration.label,
        pid=registration.pid,
        pgid=registration.pgid,
        status=status,
        **kwargs,
    )


def cleanup_registered_process(
    registration: RegisteredProcess,
    *,
    grace_seconds: float = DEFAULT_CLEANUP_GRACE_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    allow_exited_leader_initial: bool = False,
) -> ProcessCleanupResult:
    """Terminate one registered group without signalling a reused/unowned identity.

    A caller that observed and reaped its own private group leader may extend its
    registration authority to the retained group. An unrelated or reused leader PID
    still fails the OS identity check.
    """
    if (
        isinstance(grace_seconds, bool)
        or not isinstance(grace_seconds, (int, float))
        or not 0 < float(grace_seconds) <= MAX_CLEANUP_GRACE_SECONDS
    ) or not _valid_registration(registration):
        return _result(registration, ProcessCleanupStatus.INVALID_REGISTRATION)

    try:
        alive = _group_alive(registration.pgid)
    except OSError as exc:
        return _result(registration, ProcessCleanupStatus.PROBE_FAILED, error=type(exc).__name__)
    if not alive:
        return _result(registration, ProcessCleanupStatus.ALREADY_EXITED)
    owned, failure = _check_owner(
        registration, allow_exited_leader=allow_exited_leader_initial,
    )
    if not owned:
        return _result(registration, failure or ProcessCleanupStatus.OWNERSHIP_LOST, alive_after=True)

    try:
        os.killpg(registration.pgid, signal.SIGTERM)
    except ProcessLookupError:
        return _result(registration, ProcessCleanupStatus.ALREADY_EXITED)
    except OSError as exc:
        return _result(registration, ProcessCleanupStatus.TERM_FAILED, alive_after=True, error=type(exc).__name__)

    deadline = monotonic() + float(grace_seconds)
    while True:
        try:
            alive = _group_alive(registration.pgid)
        except OSError as exc:
            return _result(
                registration, ProcessCleanupStatus.PROBE_FAILED,
                term_sent=True, alive_after=True, error=type(exc).__name__,
            )
        if not alive:
            return _result(registration, ProcessCleanupStatus.CLEANED, term_sent=True)
        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        sleep(min(0.01, remaining))

    owned, failure = _check_owner(registration, allow_exited_leader=True)
    if not owned:
        return _result(
            registration, failure or ProcessCleanupStatus.OWNERSHIP_LOST,
            term_sent=True, alive_after=True,
        )
    try:
        os.killpg(registration.pgid, signal.SIGKILL)
    except ProcessLookupError:
        return _result(registration, ProcessCleanupStatus.CLEANED, term_sent=True, kill_sent=True)
    except OSError as exc:
        return _result(
            registration, ProcessCleanupStatus.KILL_FAILED,
            term_sent=True, alive_after=True, error=type(exc).__name__,
        )

    kill_deadline = monotonic() + float(grace_seconds)
    while True:
        try:
            alive = _group_alive(registration.pgid)
        except OSError as exc:
            return _result(
                registration, ProcessCleanupStatus.PROBE_FAILED,
                term_sent=True, kill_sent=True, alive_after=True, error=type(exc).__name__,
            )
        if not alive:
            break
        remaining = kill_deadline - monotonic()
        if remaining <= 0:
            return _result(
                registration, ProcessCleanupStatus.CLEANUP_UNVERIFIED,
                term_sent=True, kill_sent=True, alive_after=True,
            )
        sleep(min(0.01, remaining))
    return _result(registration, ProcessCleanupStatus.CLEANED, term_sent=True, kill_sent=True)


def cleanup_registered_processes(
    registrations: Iterable[RegisteredProcess],
    *,
    grace_seconds: float = DEFAULT_CLEANUP_GRACE_SECONDS,
    cleanup: Callable[..., ProcessCleanupResult] = cleanup_registered_process,
) -> tuple[ProcessCleanupResult, ...]:
    """Clean all registrations, preserving fan-out after callback or OS failures."""
    results: list[ProcessCleanupResult] = []
    completed: dict[tuple[int, int], ProcessCleanupResult] = {}
    for registration in registrations:
        identity = (registration.pid, registration.pgid)
        prior = completed.get(identity)
        if prior is not None:
            # A successfully cleaned group needs no more signals. Retain one result per
            # durable registration so each row can be conditionally released by the caller.
            results.append(ProcessCleanupResult(
                registration.label,
                registration.pid,
                registration.pgid,
                prior.status,
                term_sent=prior.term_sent,
                kill_sent=prior.kill_sent,
                alive_after=prior.alive_after,
                error=prior.error,
            ))
            continue
        try:
            result = cleanup(registration, grace_seconds=grace_seconds)
        except Exception as exc:  # noqa: BLE001 - continue fan-out after one callback fails.
            result = _result(
                registration, ProcessCleanupStatus.CALLBACK_FAILED, error=type(exc).__name__,
            )
        results.append(result)
        if result.status in {ProcessCleanupStatus.CLEANED, ProcessCleanupStatus.ALREADY_EXITED}:
            completed[identity] = result
    return tuple(results)


__all__ = [
    "DEFAULT_CLEANUP_GRACE_SECONDS", "MAX_CLEANUP_GRACE_SECONDS", "ProcessCleanupResult",
    "ProcessCleanupStatus", "RegisteredProcess", "cleanup_registered_process",
    "cleanup_registered_processes",
]
