"""Explicit, single-use host policy scope with ancillary clock/lifecycle evidence.

The journal is not a native result or receipt. A record describes an append attempt: it
cannot prove its own fsync completed, and no missing/partial closure proves successful cleanup.
release_outcome=returned means release() returned normally; after failed acquisition that
can be an idempotent no-op following native rollback, not proof an assertion was held.
"""
from __future__ import annotations

import json
import math
import os
import stat
import threading
import time
import uuid
from pathlib import Path

MAX_EVENT_BYTES = 8192
_MIN_NS = -(2**63)
_MAX_NS = 2**63 - 1


def _error(code):
    from .host_awake import HostAwakeError
    return HostAwakeError(code)


def _safe_error(exc, code):
    from .host_awake import HostAwakeError
    return exc if isinstance(exc, HostAwakeError) else _error(code)


class SystemClock:
    """Realtime observation bracketed by the unchanged Python monotonic clock."""

    def sample(self):
        before = time.monotonic_ns()
        wall = time.time_ns()
        after = time.monotonic_ns()
        return {'wall_time_ns': wall, 'monotonic_before_ns': before, 'monotonic_after_ns': after}

    def info(self):
        values = {}
        for label, name in (('wall', 'time'), ('monotonic', 'monotonic')):
            info = time.get_clock_info(name)
            values[label] = {key: getattr(info, key) for key in (
                'implementation', 'adjustable', 'monotonic', 'resolution')}
        return values


def _clock_info(clock):
    try:
        value = clock.info()
        if type(value) is not dict or set(value) != {'wall', 'monotonic'}:
            raise ValueError
        result = {}
        for name, item in value.items():
            if type(item) is not dict or set(item) != {
                'implementation', 'adjustable', 'monotonic', 'resolution',
            }:
                raise ValueError
            text = item['implementation']
            resolution = item['resolution']
            if (type(text) is not str or not 0 < len(text) <= 256
                    or not all(32 <= ord(char) < 127 for char in text)
                    or any(type(item[key]) is not bool for key in ('adjustable', 'monotonic'))
                    or type(resolution) not in (int, float)
                    or not math.isfinite(resolution) or not 0 < resolution <= 86400):
                raise ValueError
            result[name] = dict(item)
        if result['monotonic']['monotonic'] is not True:
            raise ValueError
        return result
    except Exception:  # noqa: BLE001 - explicit clock seam must not expose exception prose
        raise _error('clock_invalid') from None


def _clock_sample(clock, previous):
    try:
        value = clock.sample()
        if type(value) is not dict or set(value) != {
            'wall_time_ns', 'monotonic_before_ns', 'monotonic_after_ns',
        }:
            raise ValueError
        if any(type(item) is not int or not _MIN_NS <= item <= _MAX_NS
               for item in value.values()):
            raise ValueError
        if not 0 <= value['monotonic_before_ns'] <= value['monotonic_after_ns']:
            raise ValueError
        if previous is not None and value['monotonic_before_ns'] < previous['monotonic_after_ns']:
            raise ValueError
        return dict(value)
    except Exception:  # noqa: BLE001 - explicit clock seam must not expose exception prose
        raise _error('clock_invalid') from None


def _elapsed(first, last):
    wall = last['wall_time_ns'] - first['wall_time_ns']
    lower = last['monotonic_before_ns'] - first['monotonic_after_ns']
    upper = last['monotonic_after_ns'] - first['monotonic_before_ns']
    return {'wall_elapsed_ns': wall, 'monotonic_elapsed_lower_ns': lower,
            'monotonic_elapsed_upper_ns': upper, 'clock_divergence_lower_ns': wall - upper,
            'clock_divergence_upper_ns': wall - lower}


def _assertion(value, owner):
    if (type(value) is not dict or set(value) != {
        'backend', 'assertion_type', 'assertion_id', 'owner_pid', 'level', 'verified',
    } or type(value['backend']) is not str or value['backend'] != 'macos_iokit'
            or type(value['assertion_type']) is not str
            or value['assertion_type'] != 'PreventUserIdleSystemSleep'
            or type(value['assertion_id']) is not int or not 0 < value['assertion_id'] <= 2**32 - 1
            or type(value['owner_pid']) is not int or value['owner_pid'] != owner
            or type(value['level']) is not int or value['level'] != 255
            or value['verified'] is not True):
        raise _error('assertion_evidence_invalid')
    return dict(value)


class _Journal:
    """Append through the exclusively created FD; validate names, inode and all prior bytes."""

    def __init__(self, report_path):
        self.fd = self.parent_fd = None
        self.owned_fds = set()
        self.expected = b''
        self.count = 0
        self.directories = []
        try:
            path = Path(report_path).expanduser()
            if '..' in path.parts:
                raise _error('journal_invalid')
            self.path = path.absolute()
            if not self.path.name:
                raise _error('journal_invalid')
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            self.parent_fd = os.open(self.path.anchor, flags)
            self.owned_fds.add(self.parent_fd)
            current = Path(self.path.anchor)
            info = os.fstat(self.parent_fd)
            self.directories.append((current, info.st_dev, info.st_ino))
            for part in self.path.parent.parts[1:]:
                child = os.open(part, flags, dir_fd=self.parent_fd)
                self.owned_fds.add(child)
                previous = self.parent_fd
                self.parent_fd = child
                # close() can finish and then raise/cancel after this number was reused.
                # Its outcome is uncertain on failure: never retry that descriptor number.
                self.owned_fds.remove(previous)
                try:
                    os.close(previous)
                except OSError:
                    raise _error('journal_write_failed') from None
                current /= part
                info = os.fstat(child)
                self.directories.append((current, info.st_dev, info.st_ino))
            self.fd = os.open(self.path.name, os.O_CREAT | os.O_EXCL | os.O_RDWR
                              | os.O_APPEND | os.O_NOFOLLOW, 0o600, dir_fd=self.parent_fd)
            self.owned_fds.add(self.fd)
            info = os.fstat(self.fd)
            self.identity = (info.st_dev, info.st_ino)
            self._check()
        except BaseException as exc:
            try:
                self.close()
            except BaseException:  # noqa: BLE001, S110 - preserve original error, never log raw prose
                pass
            if not isinstance(exc, Exception):
                raise
            raise _safe_error(exc, 'journal_invalid') from None
        try:
            # Persist the directory entry as well as each subsequent journal record.
            os.fsync(self.parent_fd)
        except BaseException as exc:
            try:
                self.close()
            except BaseException:  # noqa: BLE001, S110 - preserve original error, never log raw prose
                pass
            if not isinstance(exc, Exception):
                raise
            raise _error('journal_write_failed') from None

    def _check(self):
        try:
            for path, device, inode in self.directories:
                info = path.lstat()
                if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != (device, inode):
                    raise ValueError
            named, opened = self.path.lstat(), os.fstat(self.fd)
            for info in (named, opened):
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                        or (info.st_dev, info.st_ino) != self.identity
                        or info.st_size != len(self.expected)):
                    raise ValueError
            if os.pread(self.fd, 3 * MAX_EVENT_BYTES + 1, 0) != self.expected:
                raise ValueError
        except (OSError, ValueError, TypeError, OverflowError):
            raise _error('journal_invalid') from None

    def append(self, value):
        self._check()
        try:
            encoded = json.dumps(value, ensure_ascii=True, allow_nan=False,
                                 separators=(',', ':')).encode() + b'\n'
            if len(encoded) > MAX_EVENT_BYTES or self.count >= 3:
                raise ValueError
            self.count += 1
            remaining = memoryview(encoded)
            while remaining:
                written = os.write(self.fd, remaining)
                if written <= 0:
                    raise OSError
                remaining = remaining[written:]
            self.expected += encoded
            os.fsync(self.fd)
        except (OSError, ValueError, TypeError, OverflowError, RecursionError):
            raise _error('journal_write_failed') from None
        self._check()

    def close(self):
        error = None
        self.fd = self.parent_fd = None
        owned, self.owned_fds = self.owned_fds, set()
        for fd in owned:
            try:
                os.close(fd)
            except BaseException as exc:  # noqa: BLE001 - close all remaining owned descriptors
                error = error or exc
        if error is not None:
            raise _error('journal_write_failed') from None


class _HostExecution:
    def __init__(self, report_path, guard, clock):
        self.report_path, self.guard = report_path, guard
        self.clock = clock if clock is not None else SystemClock()
        self.owner_pid = os.getpid()
        self.state_lock = threading.RLock()
        self.state, self.sequence = 'new', 0
        self.journal = self.assertion = self.first_sample = self.previous_sample = None
        self.attempted = self.starting_durable = False
        self.acquisition = 'not_attempted'
        self.verification, self.release = 'not_attempted', 'not_attempted'

    def _owner(self):
        if os.getpid() != self.owner_pid:
            raise _error('session_pid_mismatch')

    def _sample(self):
        value = _clock_sample(self.clock, self.previous_sample)
        self.previous_sample = value
        return value

    def _append(self, event, sample, work, clock_outcome='observed'):
        self.sequence += 1
        value = {
            'schema_version': '1', 'kind': 'host_execution', 'session_id': self.session_id,
            'owner_pid': self.owner_pid, 'policy': 'prevent_idle_system_sleep',
            'sequence': self.sequence, 'event': event, 'clock_info': self.clock_info,
            'sample': sample,
            'elapsed': _elapsed(self.first_sample, sample) if event == 'closed' and sample else None,
            'assertion': self.assertion, 'work_outcome': work,
            'acquisition_outcome': self.acquisition,
            'verification_outcome': self.verification, 'release_outcome': self.release,
            'clock_outcome': clock_outcome, 'journal_outcome': 'append_requested',
        }
        try:
            self.journal.append(value)
        except BaseException as exc:
            if not isinstance(exc, Exception):
                raise
            raise _safe_error(exc, 'journal_write_failed') from None

    def _finish(self, work):
        errors = []
        if self.assertion is not None:
            try:
                observed = _assertion(self.guard.verify(), self.owner_pid)
                if observed != self.assertion:
                    raise _error('assertion_evidence_invalid')
                self.verification = 'verified'
            except BaseException as exc:  # noqa: BLE001 - verification cannot skip release
                self.verification = 'failed'
                errors.append(_safe_error(exc, 'session_cleanup_failed'))
        if self.attempted:
            try:
                self.guard.release()
                self.release = 'returned'
            except BaseException as exc:  # noqa: BLE001 - preserve the protected work exception
                self.release = 'failed'
                errors.append(_safe_error(exc, 'session_cleanup_failed'))
        if self.starting_durable:
            try:
                sample, clock_outcome = self._sample(), 'observed'
            except BaseException as exc:  # noqa: BLE001 - failed clock cannot skip journal cleanup
                sample, clock_outcome = None, 'failed'
                errors.append(_safe_error(exc, 'clock_invalid'))
            try:
                self._append('closed', sample, work, clock_outcome)
            except BaseException as exc:  # noqa: BLE001 - failed append cannot skip descriptor cleanup
                errors.append(_safe_error(exc, 'journal_write_failed'))
        if self.journal is not None:
            try:
                self.journal.close()
            except BaseException as exc:  # noqa: BLE001 - preserve the protected work exception
                errors.append(_safe_error(exc, 'journal_write_failed'))
        with self.state_lock:
            self.state = 'closed'
        return errors

    def __enter__(self):
        self._owner()
        with self.state_lock:
            if self.state != 'new':
                raise _error('session_reused')
            self.state = 'entering'
        self.session_id = str(uuid.uuid4())
        try:
            self.clock_info = _clock_info(self.clock)
            self.first_sample = self._sample()
            self.journal = _Journal(self.report_path)
            self._append('starting', self.first_sample, 'not_started')
            self.starting_durable = True
            if self.guard is None:
                from .host_awake import MacOSIdleSleepAssertion
                self.guard = MacOSIdleSleepAssertion()
            self.attempted = True
            self.acquisition = 'attempting'
            try:
                self.assertion = _assertion(self.guard.acquire(), self.owner_pid)
                self.acquisition = 'acquired'
            except BaseException:
                self.acquisition = 'failed'
                raise
            self.verification = 'verified'
            self._append('active', self._sample(), 'not_started')
            with self.state_lock:
                self.state = 'active'
            return self
        except BaseException as exc:
            self._finish('not_started')
            if not isinstance(exc, Exception):
                raise
            raise _safe_error(exc, 'session_cleanup_failed') from None

    def __exit__(self, exc_type, exc, traceback):
        # Cross-PID use rejects without operating on the parent's assertion or journal.
        # Work-exception precedence applies only inside this process-owned scope.
        self._owner()
        with self.state_lock:
            if self.state != 'active':
                raise _error('session_reused')
            self.state = 'exiting'
        errors = self._finish('raised' if exc_type is not None else 'returned')
        if exc_type is None and errors:
            raise errors[0] from None
        return False


def host_execution(report_path, *, guard=None, clock=None):
    """Return a lazy, single-use scope; acquisition and durable activation precede its body.

    guard and clock are explicit dependency seams. The default guard uses a process-owned
    macOS idle-system-sleep assertion. No operation result or exception text is journaled.
    """
    return _HostExecution(report_path, guard, clock)
