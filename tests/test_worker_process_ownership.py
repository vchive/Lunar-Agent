"""Worker cancellation and release against actual private local process groups."""

import os
import signal
import sys
import time

import pytest

from lunar_evolution import workers
from lunar_evolution.agents import AgentRegistry, CommandAgentAdapter
from lunar_evolution.models import WorkerOutcome, WorkerPhase, WorkerStopReason
from lunar_evolution.process_ownership import ProcessCleanupResult, ProcessCleanupStatus
from lunar_evolution.store import Store
from lunar_evolution.workers import WorkerService


def eventually(predicate):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.01)
    pytest.fail("local process did not reach the expected state")


def group_gone(pgid):
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        pass
    return False


def service_for(tmp_path, code):
    store = Store(tmp_path / "state.db")
    store.initialize()
    adapter = CommandAgentAdapter([sys.executable, "-c", code])
    service = WorkerService(store, AgentRegistry([adapter]), tmp_path / "workspace")
    return store, service


def registrations(store, service, worker):
    attempt = store.list_worker_attempts(worker.id)[-1]
    return store.list_worker_processes(worker.id, attempt.id, service.service_owner_id)


WAIT_FOR_FILE = (
    "import pathlib,time,sys; sys.stdin.read(); pathlib.Path('started').touch(); "
    "exec(\"while not pathlib.Path('go').exists(): time.sleep(0.01)\"); print('done')"
)


def test_real_cancel_cleans_target_group_and_preserves_unrelated(tmp_path):
    store, service = service_for(tmp_path, WAIT_FOR_FILE)
    groups = []
    try:
        target = service.dispatch("owner", prompt="target", timeout=8)
        unrelated = service.dispatch("owner", prompt="unrelated", timeout=8)
        target_reg = eventually(lambda: registrations(store, service, target))[0]
        other_reg = eventually(lambda: registrations(store, service, unrelated))[0]
        groups = [target_reg.pgid, other_reg.pgid]
        assert target_reg.pid == target_reg.pgid != other_reg.pgid

        service.cancel("owner", target.id)
        eventually(lambda: group_gone(target_reg.pgid))
        eventually(lambda: not registrations(store, service, target))
        assert store.get_worker(unrelated.id).phase is WorkerPhase.RUNNING
        assert not group_gone(other_reg.pgid)
        attempt = store.list_worker_attempts(unrelated.id)[-1]
        (service.workspace / "workers" / unrelated.id / attempt.id / "go").touch()
        assert service.wait("owner", unrelated.id, timeout=4).outcome is WorkerOutcome.SUCCESS
        assert store.get_worker(target.id).outcome is WorkerOutcome.STOPPED
        assert not registrations(store, service, unrelated)
        eventually(lambda: not service._active)
        assert service._owner_lock is None
    finally:
        service.close()
        for pgid in groups:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_actual_process_registration_failure_cannot_leave_a_live_command(tmp_path, monkeypatch):
    store, service = service_for(tmp_path, "import time; time.sleep(30)")
    observed = []

    def fail_registration(worker, attempt, owner, pid, pgid):
        observed.append(pgid)
        raise OSError("registration fixture")

    monkeypatch.setattr(store, "register_worker_process", fail_registration)
    try:
        worker = service.dispatch("owner", prompt="observe failure", timeout=4)
        assert service.wait("owner", worker.id, timeout=4).outcome is WorkerOutcome.FAILURE
        assert observed
        eventually(lambda: group_gone(observed[0]))
        eventually(lambda: not service._active)
        assert service._owner_lock is None
    finally:
        service.close()


def test_unconfirmed_cleanup_retains_exact_registration_and_blocks_resume(tmp_path, monkeypatch):
    store, service = service_for(tmp_path, "print('done')")
    original = workers.cleanup_registered_processes

    def failed_cleanup(registrations):
        return tuple(ProcessCleanupResult(
            reg.label, reg.pid, reg.pgid, ProcessCleanupStatus.CALLBACK_FAILED, alive_after=True,
        ) for reg in registrations)

    monkeypatch.setattr(workers, "cleanup_registered_processes", failed_cleanup)
    try:
        worker = service.dispatch("owner", prompt="retained", timeout=4)
        settled = service.wait("owner", worker.id, timeout=4)
        assert settled.outcome is WorkerOutcome.FAILURE
        assert settled.stop_reason is WorkerStopReason.PROCESS_CLEANUP
        assert registrations(store, service, worker)
        eventually(lambda: not service._active)
        with pytest.raises(ValueError, match="process"):
            service.resume("owner", worker.id)
        assert len(store.list_worker_attempts(worker.id)) == 1
        monkeypatch.setattr(workers, "cleanup_registered_processes", original)
        assert service.reconcile("owner") == 0  # Cleanup may retry, but terminal failure is retained.
        assert not registrations(store, service, worker)
        assert store.get_worker(worker.id).outcome is WorkerOutcome.FAILURE
    finally:
        monkeypatch.setattr(workers, "cleanup_registered_processes", original)
        service.close()


def test_close_stops_owned_command_and_drains_queued_work(tmp_path):
    store, service = service_for(tmp_path, WAIT_FOR_FILE)
    worker = service.dispatch("owner", prompt="close", timeout=8)
    reg = eventually(lambda: registrations(store, service, worker))[0]
    service.close()
    eventually(lambda: group_gone(reg.pgid))
    eventually(lambda: not service._active)
    assert service._owner_lock is None
    assert store.get_worker(worker.id).outcome is WorkerOutcome.STOPPED
    with pytest.raises(ValueError, match="closed"):
        service.dispatch("owner", prompt="no new invocation")


def test_real_parent_cancel_cleans_child_group_and_preserves_unrelated(tmp_path):
    store, service = service_for(tmp_path, WAIT_FOR_FILE)
    groups = []
    try:
        parent = service.dispatch("owner", prompt="parent", timeout=10)
        child = service.dispatch("owner", prompt="child", parent_worker_id=parent.id, timeout=10)
        unrelated = service.dispatch("owner", prompt="unrelated", timeout=10)
        parent_reg, child_reg, unrelated_reg = [
            eventually(lambda worker=worker: registrations(store, service, worker))[0]
            for worker in (parent, child, unrelated)
        ]
        groups = [parent_reg.pgid, child_reg.pgid, unrelated_reg.pgid]
        assert len(set(groups)) == 3

        service.cancel("owner", parent.id)
        for worker, reg in ((parent, parent_reg), (child, child_reg)):
            eventually(lambda reg=reg: group_gone(reg.pgid))
            eventually(lambda worker=worker: not registrations(store, service, worker))
            assert store.get_worker(worker.id).outcome is WorkerOutcome.STOPPED
        assert not group_gone(unrelated_reg.pgid)
        attempt = store.list_worker_attempts(unrelated.id)[-1]
        (service.workspace / "workers" / unrelated.id / attempt.id / "go").touch()
        assert service.wait("owner", unrelated.id, timeout=4).outcome is WorkerOutcome.SUCCESS
        eventually(lambda: not service._active)
        assert service._owner_lock is None
    finally:
        service.close()
        for pgid in groups:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
