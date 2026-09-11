"""Deterministic, offline host-scope lifecycle and evidence checks."""
from __future__ import annotations

import json
import os
import stat
import threading
from contextlib import suppress

import pytest

import famou.host_session as session


class Guard:
    def __init__(self, *, acquire_error=None, verify_error=None, release_error=None):
        self.calls = []
        self.acquire_error, self.verify_error, self.release_error = (
            acquire_error, verify_error, release_error,
        )

    def evidence(self):
        return {'backend': 'macos_iokit', 'assertion_type': 'PreventUserIdleSystemSleep',
                'assertion_id': 17, 'owner_pid': os.getpid(), 'level': 255, 'verified': True}

    def acquire(self):
        self.calls.append('acquire')
        if self.acquire_error:
            raise self.acquire_error
        return self.evidence()

    def verify(self):
        self.calls.append('verify')
        if self.verify_error:
            raise self.verify_error
        return self.evidence()

    def release(self):
        self.calls.append('release')
        if self.release_error:
            raise self.release_error


class Clock:
    def __init__(self, walls=(1000, 1500, 2100), monos=((10, 12), (20, 22), (30, 34))):
        self.samples = [{'wall_time_ns': wall, 'monotonic_before_ns': before,
                         'monotonic_after_ns': after}
                        for wall, (before, after) in zip(walls, monos, strict=True)]
        self.count = 0

    def info(self):
        return {name: {'implementation': 'fixture_clock', 'adjustable': name == 'wall',
                       'monotonic': name == 'monotonic', 'resolution': 1e-9}
                for name in ('wall', 'monotonic')}

    def sample(self):
        value = self.samples[self.count]
        self.count += 1
        return value


def events(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_scope_is_lazy_single_use_and_preserves_work_result(tmp_path):
    path, guard, clock = tmp_path / 'host.jsonl', Guard(), Clock()
    scope = session.host_execution(path, guard=guard, clock=clock)
    assert not path.exists() and not guard.calls and clock.count == 0
    sentinel = object()
    with scope:
        assert guard.calls == ['acquire']
        assert [e['event'] for e in events(path)] == ['starting', 'active']
        result = sentinel
    assert result is sentinel
    assert guard.calls == ['acquire', 'verify', 'release']
    rows = events(path)
    assert [e['event'] for e in rows] == ['starting', 'active', 'closed']
    assert [e['sequence'] for e in rows] == [1, 2, 3]
    assert len({e['session_id'] for e in rows}) == 1
    assert rows[-1]['work_outcome'] == 'returned'
    assert rows[-1]['verification_outcome'] == 'verified'
    assert rows[-1]['release_outcome'] == 'returned'
    assert [e['acquisition_outcome'] for e in rows] == ['not_attempted', 'acquired', 'acquired']
    assert rows[-1]['elapsed'] == {
        'wall_elapsed_ns': 1100, 'monotonic_elapsed_lower_ns': 18,
        'monotonic_elapsed_upper_ns': 24, 'clock_divergence_lower_ns': 1076,
        'clock_divergence_upper_ns': 1082,
    }
    original = path.read_bytes()
    with (
        pytest.raises(ValueError, match='session_reused'),
        scope,
    ):
        pytest.fail('reused scope dispatched')
    assert path.read_bytes() == original


@pytest.mark.parametrize('kind', ['existing', 'directory', 'symlink', 'ancestor_symlink'])
def test_unsafe_or_existing_report_rejected_before_guard(tmp_path, kind):
    path, guard = tmp_path / 'host.jsonl', Guard()
    target = tmp_path / 'target'
    target.write_text('untouched')
    if kind == 'existing':
        path.write_text('untouched')
    elif kind == 'directory':
        path.mkdir()
    elif kind == 'symlink':
        path.symlink_to(target)
    else:
        directory = tmp_path / 'real'
        directory.mkdir()
        alias = tmp_path / 'alias'
        alias.symlink_to(directory, target_is_directory=True)
        path = alias / 'host.jsonl'
    with (
        pytest.raises(ValueError, match='journal_invalid'),
        session.host_execution(path, guard=guard, clock=Clock()),
    ):
        pytest.fail('unsafe report dispatched')
    assert not guard.calls and target.read_text() == 'untouched'


def test_starting_and_active_are_fsynced_before_dispatch(tmp_path, monkeypatch):
    path, guard = tmp_path / 'host.jsonl', Guard()
    calls, original = [], session.os.fsync
    def fsync(fd):
        calls.append(path.read_bytes() if path.exists() else b'')
        return original(fd)
    monkeypatch.setattr(session.os, 'fsync', fsync)
    original_acquire = guard.acquire
    def acquire():
        assert any(b'"event":"starting"' in content for content in calls)
        return original_acquire()
    guard.acquire = acquire
    with session.host_execution(path, guard=guard, clock=Clock()):
        assert any(b'"event":"active"' in content for content in calls)
    assert any(b'"event":"closed"' in content for content in calls)


def test_failed_acquisition_releases_without_exposing_exception(tmp_path):
    path = tmp_path / 'host.jsonl'
    guard = Guard(acquire_error=ValueError('fixture-secret-provider-text'))
    with (
        pytest.raises(ValueError, match='session_cleanup_failed'),
        session.host_execution(path, guard=guard, clock=Clock()),
    ):
        pytest.fail('failed acquisition dispatched')
    assert guard.calls == ['acquire', 'release']
    assert events(path)[-1]['work_outcome'] == 'not_started'
    assert events(path)[-1]['acquisition_outcome'] == 'failed'
    assert events(path)[-1]['release_outcome'] == 'returned'
    assert 'fixture-secret' not in path.read_text()


@pytest.mark.parametrize('stage', ['starting', 'active', 'closed'])
def test_write_failure_blocks_entry_or_reports_closure_failure(tmp_path, monkeypatch, stage):
    path, guard = tmp_path / 'host.jsonl', Guard()
    append = session._Journal.append
    def fail(self, value):
        if value['event'] == stage:
            raise OSError('fixture-secret-write')
        return append(self, value)
    monkeypatch.setattr(session._Journal, 'append', fail)
    body = []
    with (
        pytest.raises(ValueError, match='journal_write_failed'),
        session.host_execution(path, guard=guard, clock=Clock()),
    ):
        body.append(True)
    assert body == ([True] if stage == 'closed' else [])
    assert ('release' in guard.calls) == (stage != 'starting')
    assert 'fixture-secret' not in path.read_text()


@pytest.mark.parametrize('failure', ['verify', 'release'])
def test_guard_cleanup_failure_keeps_returned_work_distinct(tmp_path, failure):
    path = tmp_path / 'host.jsonl'
    guard = Guard(**{failure + '_error': RuntimeError('fixture-secret-cleanup')})
    with (
        pytest.raises(ValueError, match='session_cleanup_failed'),
        session.host_execution(path, guard=guard, clock=Clock()),
    ):
        pass
    last = events(path)[-1]
    assert last['work_outcome'] == 'returned'
    assert last[failure.replace('verify', 'verification') + '_outcome'] == 'failed'
    assert guard.calls[-1] == 'release'
    assert 'fixture-secret' not in path.read_text()


@pytest.mark.parametrize('error', [RuntimeError('private work'), KeyboardInterrupt(),
                                  SystemExit(7), GeneratorExit()])
@pytest.mark.parametrize('cleanup_failure', ['verify', 'release', 'journal'])
def test_original_baseexception_object_survives_cleanup_failure(
    tmp_path, monkeypatch, error, cleanup_failure,
):
    path, guard = tmp_path / 'host.jsonl', Guard()
    if cleanup_failure == 'journal':
        append = session._Journal.append
        def fail(self, value):
            if value['event'] == 'closed':
                raise OSError('private journal failure')
            return append(self, value)
        monkeypatch.setattr(session._Journal, 'append', fail)
    else:
        setattr(guard, cleanup_failure + '_error', RuntimeError('private cleanup'))
    with (
        pytest.raises(type(error)) as caught,
        session.host_execution(path, guard=guard, clock=Clock()),
    ):
        raise error
    assert caught.value is error and guard.calls[-1] == 'release'
    assert 'private' not in path.read_text()


@pytest.mark.parametrize('mutation', ['replace', 'append', 'truncate', 'symlink'])
def test_journal_tampering_never_overwrites_foreign_data(tmp_path, mutation):
    path, guard = tmp_path / 'host.jsonl', Guard()
    with (
        pytest.raises(ValueError, match='journal_invalid'),
        session.host_execution(path, guard=guard, clock=Clock()),
    ):
        if mutation == 'replace':
            path.rename(tmp_path / 'original')
            path.write_text('foreign')
        elif mutation == 'append':
            with path.open('a') as handle:
                handle.write('foreign')
        elif mutation == 'truncate':
            path.write_text('foreign')
        else:
            path.rename(tmp_path / 'original')
            target = tmp_path / 'foreign'
            target.write_text('foreign')
            path.symlink_to(target)
    assert guard.calls[-1] == 'release'
    assert path.read_text().endswith('foreign')


def test_clock_jump_is_signed_observation_not_sleep_inference(tmp_path):
    path = tmp_path / 'host.jsonl'
    with session.host_execution(path, guard=Guard(), clock=Clock(walls=(1000, 900, 500))):
        pass
    last = events(path)[-1]
    assert last['elapsed']['wall_elapsed_ns'] == -500
    assert last['elapsed']['clock_divergence_lower_ns'] == -524
    assert last['elapsed']['clock_divergence_upper_ns'] == -518
    assert 'sleep_seconds' not in path.read_text()


def test_wall_clock_int64_minimum_is_preserved_as_a_signed_jump(tmp_path):
    path = tmp_path / 'host.jsonl'
    with session.host_execution(path, guard=Guard(), clock=Clock(walls=(0, 0, -(2**63)))):
        pass
    last = events(path)[-1]
    assert last['sample']['wall_time_ns'] == -(2**63)
    assert last['elapsed']['wall_elapsed_ns'] == -(2**63)
    assert last['elapsed']['clock_divergence_lower_ns'] == -(2**63) - 24
    assert last['clock_outcome'] == 'observed'


@pytest.mark.parametrize('bad', [True, float('nan'), 1.1, '12', 2**64])
def test_invalid_clock_rejects_before_acquisition(tmp_path, bad):
    guard, clock = Guard(), Clock()
    clock.samples[0]['wall_time_ns'] = bad
    with (
        pytest.raises(ValueError, match='clock_invalid'),
        session.host_execution(tmp_path / 'host.jsonl', guard=guard, clock=clock),
    ):
        pytest.fail('bad clock dispatched')
    assert not guard.calls


def test_invalid_active_clock_still_releases_and_never_dispatches(tmp_path):
    guard, clock = Guard(), Clock()
    clock.samples[1]['monotonic_before_ns'] = 0
    with (
        pytest.raises(ValueError, match='clock_invalid'),
        session.host_execution(tmp_path / 'host.jsonl', guard=guard, clock=clock),
    ):
        pytest.fail('bad active clock dispatched')
    assert guard.calls[-1] == 'release'


def test_invalid_final_clock_records_explicit_failure(tmp_path):
    path, guard, clock = tmp_path / 'host.jsonl', Guard(), Clock()
    clock.samples[2]['monotonic_after_ns'] = -1
    with (
        pytest.raises(ValueError, match='clock_invalid'),
        session.host_execution(path, guard=guard, clock=clock),
    ):
        pass
    last = events(path)[-1]
    assert last['sample'] is None and last['elapsed'] is None
    assert last['clock_outcome'] == 'failed' and last['work_outcome'] == 'returned'
    assert guard.calls[-1] == 'release'


@pytest.mark.parametrize('field,value', [('assertion_id', 0), ('owner_pid', 1), ('level', 1),
                                        ('verified', False), ('backend', 'foreign'),
                                        ('assertion_type', 'foreign')])
def test_unverified_or_wrong_assertion_never_dispatches(tmp_path, field, value):
    guard = Guard()
    original = guard.evidence
    guard.evidence = lambda: {**original(), field: value}
    with (
        pytest.raises(ValueError, match='assertion_evidence_invalid'),
        session.host_execution(tmp_path / 'host.jsonl', guard=guard, clock=Clock()),
    ):
        pytest.fail('invalid assertion dispatched')
    assert guard.calls[-1] == 'release'


def test_scope_rejects_cross_pid_before_action(tmp_path, monkeypatch):
    path, guard = tmp_path / 'host.jsonl', Guard()
    scope = session.host_execution(path, guard=guard, clock=Clock())
    real_pid = os.getpid()
    monkeypatch.setattr(session.os, 'getpid', lambda: real_pid + 100000)
    with (
        pytest.raises(ValueError, match='session_pid_mismatch'),
        scope,
    ):
        pytest.fail('cross pid dispatched')
    assert not path.exists() and not guard.calls


def test_system_clock_sample_is_bracketed_and_info_fixed():
    clock = session.SystemClock()
    sample = clock.sample()
    assert type(sample['wall_time_ns']) is int
    assert sample['monotonic_before_ns'] <= sample['monotonic_after_ns']
    assert set(clock.info()) == {'wall', 'monotonic'}


def test_journal_is_bounded_and_has_only_fixed_safe_fields(tmp_path):
    path = tmp_path / 'host.jsonl'
    with session.host_execution(path, guard=Guard(), clock=Clock()):
        callback_result = {'secret': 'must never serialize callback data'}
    assert callback_result['secret'] not in path.read_text()
    assert path.stat().st_size <= 3 * session.MAX_EVENT_BYTES
    allowed = {'schema_version', 'kind', 'session_id', 'owner_pid', 'policy', 'sequence',
               'event', 'clock_info', 'sample', 'elapsed', 'assertion', 'work_outcome',
               'acquisition_outcome', 'verification_outcome', 'release_outcome',
               'clock_outcome', 'journal_outcome'}
    assert all(set(value) == allowed for value in events(path))


@pytest.mark.parametrize('failure_at', [1, 2, 3, 4])
def test_directory_and_event_fsync_failures_never_claim_their_own_durability(
    tmp_path, monkeypatch, failure_at,
):
    path, guard, count = tmp_path / 'host.jsonl', Guard(), 0
    fsync = session.os.fsync
    def fail(fd):
        nonlocal count
        count += 1
        if count == 1:
            assert stat.S_ISDIR(os.fstat(fd).st_mode)
        if count == failure_at:
            raise OSError('secret sync failure')
        return fsync(fd)
    monkeypatch.setattr(session.os, 'fsync', fail)
    body = []
    with (
        pytest.raises(ValueError, match='journal_write_failed'),
        session.host_execution(path, guard=guard, clock=Clock()),
    ):
        body.append(True)
    assert body == ([True] if failure_at == 4 else [])
    assert bool(guard.calls) == (failure_at >= 3)
    if guard.calls:
        assert guard.calls[-1] == 'release'
    assert all(e['journal_outcome'] == 'append_requested' for e in events(path))
    assert 'secret' not in path.read_text()


def test_replaced_parent_directory_is_rejected_without_touching_foreign_file(tmp_path):
    parent, guard = tmp_path / 'parent', Guard()
    parent.mkdir()
    path = parent / 'host.jsonl'
    with (
        pytest.raises(ValueError, match='journal_invalid'),
        session.host_execution(path, guard=guard, clock=Clock()),
    ):
        parent.rename(tmp_path / 'original-parent')
        parent.mkdir()
        path.write_text('foreign')
    assert path.read_text() == 'foreign'
    assert guard.calls[-1] == 'release'


def test_replacement_during_acquisition_prevents_body(tmp_path):
    path, guard = tmp_path / 'host.jsonl', Guard()
    acquire = guard.acquire
    def replace():
        value = acquire()
        path.rename(tmp_path / 'original')
        path.write_text('foreign')
        return value
    guard.acquire = replace
    with (
        pytest.raises(ValueError, match='journal_invalid'),
        session.host_execution(path, guard=guard, clock=Clock()),
    ):
        pytest.fail('replacement allowed body')
    assert guard.calls[-1] == 'release' and path.read_text() == 'foreign'


def test_valid_but_different_assertion_identity_at_exit_is_rejected(tmp_path):
    path, guard = tmp_path / 'host.jsonl', Guard()
    with (
        pytest.raises(ValueError, match='assertion_evidence_invalid'),
        session.host_execution(path, guard=guard, clock=Clock()),
    ):
        original = guard.verify
        guard.verify = lambda: {**original(), 'assertion_id': 18}
    last = events(path)[-1]
    assert last['verification_outcome'] == 'failed'
    assert last['assertion']['assertion_id'] == 17 and last['release_outcome'] == 'returned'


@pytest.mark.parametrize('bad_info', ['huge_text', 'nan', 'bool_resolution', 'extra', 'not_monotonic'])
def test_invalid_clock_info_rejected_before_any_guard_action(tmp_path, bad_info):
    clock, guard = Clock(), Guard()
    info = clock.info()
    if bad_info == 'huge_text':
        info['wall']['implementation'] = 'x' * 10000
    elif bad_info == 'nan':
        info['wall']['resolution'] = float('nan')
    elif bad_info == 'bool_resolution':
        info['wall']['resolution'] = True
    elif bad_info == 'extra':
        info['wall']['secret'] = 'not a clock field'
    else:
        info['monotonic']['monotonic'] = False
    clock.info = lambda: info
    with (
        pytest.raises(ValueError, match='clock_invalid'),
        session.host_execution(tmp_path / 'host.jsonl', guard=guard, clock=clock),
    ):
        pytest.fail('bad clock info dispatched')
    assert not guard.calls


def test_journal_rejects_oversized_event_and_fourth_append(tmp_path):
    journal = session._Journal(tmp_path / 'direct.jsonl')
    try:
        with pytest.raises(ValueError, match='journal_write_failed'):
            journal.append({'payload': 'x' * session.MAX_EVENT_BYTES})
        assert not journal.expected
        for _ in range(3):
            journal.append({'bounded': True})
        saved = journal.path.read_bytes()
        with pytest.raises(ValueError, match='journal_write_failed'):
            journal.append({'fourth': True})
        assert journal.path.read_bytes() == saved
    finally:
        journal.close()


@pytest.mark.parametrize('body_error', [False, True])
def test_journal_descriptors_are_closed_on_both_work_outcomes(tmp_path, body_error):
    scope = session.host_execution(tmp_path / 'host.jsonl', guard=Guard(), clock=Clock())
    try:
        with scope:
            fds = [scope.journal.fd, scope.journal.parent_fd]
            if body_error:
                raise RuntimeError('work error')
    except RuntimeError:
        assert body_error
    assert scope.journal.fd is None and scope.journal.parent_fd is None
    for fd in fds:
        with pytest.raises(OSError):
            os.fstat(fd)


@pytest.mark.parametrize('cancel', [KeyboardInterrupt(), SystemExit(8), GeneratorExit()])
def test_entry_baseexception_after_acquisition_attempt_always_releases(tmp_path, cancel):
    guard = Guard(acquire_error=cancel)
    with (
        pytest.raises(type(cancel)) as caught,
        session.host_execution(tmp_path / 'host.jsonl', guard=guard, clock=Clock()),
    ):
        pytest.fail('cancelled acquisition dispatched')
    assert caught.value is cancel and guard.calls == ['acquire', 'release']


@pytest.mark.parametrize('error', [OSError('private close failure'), KeyboardInterrupt()])
def test_intermediate_directory_close_failure_closes_newly_opened_child(
    tmp_path, monkeypatch, error,
):
    opened, closed, failed = [], [], False
    original_open, original_close = session.os.open, session.os.close
    def record_open(*args, **kwargs):
        fd = original_open(*args, **kwargs)
        opened.append(fd)
        return fd
    def close(fd):
        nonlocal failed
        closed.append(fd)
        if not failed:
            failed = True
            raise error
        return original_close(fd)
    monkeypatch.setattr(session.os, 'open', record_open)
    monkeypatch.setattr(session.os, 'close', close)
    guard = Guard()
    expected = ValueError if isinstance(error, OSError) else KeyboardInterrupt
    try:
        with (
            pytest.raises(expected) as caught,
            session.host_execution(tmp_path / 'host.jsonl', guard=guard, clock=Clock()),
        ):
            pytest.fail('failed directory cleanup dispatched')
        assert not guard.calls and len(opened) == 2
        if isinstance(error, KeyboardInterrupt):
            assert caught.value is error
        # The fixture knows this close failed before doing anything. The product cannot
        # know that, so it must not retry a possibly reused old number; the fixture owns
        # this uncertain descriptor's cleanup. The newly opened child is still closed.
        assert closed == opened
        os.fstat(opened[0])
        with pytest.raises(OSError):
            os.fstat(opened[1])
    finally:
        if opened:
            with suppress(OSError):
                original_close(opened[0])


def test_closed_directory_fd_reuse_is_not_closed_again_after_cancellation(tmp_path, monkeypatch):
    foreign = tmp_path / 'foreign.txt'
    foreign.write_bytes(b'foreign data remains accessible')
    original_open, original_close = session.os.open, session.os.close
    reused, attempted = None, False
    cancellation = KeyboardInterrupt()
    def close(fd):
        nonlocal reused, attempted
        if not attempted:
            attempted = True
            original_close(fd)
            reused = original_open(foreign, os.O_RDONLY)
            assert reused == fd
            raise cancellation
        return original_close(fd)
    monkeypatch.setattr(session.os, 'close', close)
    guard = Guard()
    try:
        with (
            pytest.raises(KeyboardInterrupt) as caught,
            session.host_execution(tmp_path / 'host.jsonl', guard=guard, clock=Clock()),
        ):
            pytest.fail('uncertain directory close allowed dispatch')
        assert caught.value is cancellation and not guard.calls
        assert os.fstat(reused).st_ino == foreign.stat().st_ino
        assert os.read(reused, 100) == b'foreign data remains accessible'
    finally:
        if reused is not None:
            with suppress(OSError):
                original_close(reused)


def test_original_creation_cancellation_survives_descriptor_close_failure(tmp_path, monkeypatch):
    opened, cancelling = [], False
    original_open, original_close = session.os.open, session.os.close
    cancellation = KeyboardInterrupt()
    def record_open(*args, **kwargs):
        fd = original_open(*args, **kwargs)
        opened.append(fd)
        return fd
    def cancel(_):
        nonlocal cancelling
        cancelling = True
        raise cancellation
    def close(fd):
        original_close(fd)
        if cancelling:
            raise RuntimeError('private cleanup error')
    monkeypatch.setattr(session.os, 'open', record_open)
    monkeypatch.setattr(session.os, 'fsync', cancel)
    monkeypatch.setattr(session.os, 'close', close)
    with pytest.raises(KeyboardInterrupt) as caught:
        session._Journal(tmp_path / 'host.jsonl')
    assert caught.value is cancellation
    for fd in set(opened):
        with pytest.raises(OSError):
            os.fstat(fd)


def test_cross_pid_exit_does_not_touch_parent_guard_or_journal(tmp_path, monkeypatch):
    path, guard = tmp_path / 'host.jsonl', Guard()
    scope = session.host_execution(path, guard=guard, clock=Clock())
    scope.__enter__()
    prior, parent_pid = path.read_bytes(), os.getpid()
    with monkeypatch.context() as patch:
        patch.setattr(session.os, 'getpid', lambda: parent_pid + 100000)
        with pytest.raises(ValueError, match='session_pid_mismatch'):
            scope.__exit__(RuntimeError, RuntimeError('child exception'), None)
    assert path.read_bytes() == prior and guard.calls == ['acquire']
    assert scope.state == 'active'
    scope.__exit__(None, None, None)
    assert guard.calls == ['acquire', 'verify', 'release']


def test_two_threads_cannot_enter_the_same_scope(tmp_path):
    path, guard = tmp_path / 'host.jsonl', Guard()
    barrier, rejected = threading.Barrier(2), threading.Event()
    results, bodies = [], []
    acquire = guard.acquire
    def held_acquire():
        assert rejected.wait(2), 'second entrant did not reject within bound'
        return acquire()
    guard.acquire = held_acquire
    scope = session.host_execution(path, guard=guard, clock=Clock())
    def run():
        barrier.wait(timeout=2)
        try:
            with scope:
                bodies.append(True)
        except ValueError as error:
            results.append(str(error))
            rejected.set()
    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)
    assert not any(thread.is_alive() for thread in threads)
    assert results == ['session_reused'] and bodies == [True]
    assert guard.calls == ['acquire', 'verify', 'release']
    assert [value['event'] for value in events(path)] == ['starting', 'active', 'closed']


def test_two_threads_cannot_close_the_same_scope(tmp_path):
    path, guard = tmp_path / 'host.jsonl', Guard()
    barrier, rejected = threading.Barrier(2), threading.Event()
    results = []
    verify = guard.verify
    def held_verify():
        assert rejected.wait(2), 'second closer did not reject within bound'
        return verify()
    guard.verify = held_verify
    scope = session.host_execution(path, guard=guard, clock=Clock())
    scope.__enter__()
    def close():
        barrier.wait(timeout=2)
        try:
            scope.__exit__(None, None, None)
        except ValueError as error:
            results.append(str(error))
            rejected.set()
    threads = [threading.Thread(target=close) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)
    assert not any(thread.is_alive() for thread in threads)
    assert results == ['session_reused']
    assert guard.calls == ['acquire', 'verify', 'release']
    assert [value['event'] for value in events(path)] == ['starting', 'active', 'closed']
