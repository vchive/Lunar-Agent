"""Exercise worker isolation and cancellation with deterministic blocked adapters."""

import os
import sys
import threading
from multiprocessing import get_context
from pathlib import Path

import pytest

from famou import workers
from famou.agents import AgentRegistry, AgentResult, RuntimeAgentAdapter
from famou.models import WorkerOutcome, WorkerPhase, WorkerStopReason
from famou.process_ownership import ProcessCleanupResult, ProcessCleanupStatus
from famou.runtime import SubprocessRuntime
from famou.store import Store
from famou.worker_ownership import WorkerOwnerLock
from famou.workers import WorkerService


class ControlledAdapter:
    name = "controlled"
    roles = frozenset({"worker"})
    capabilities = frozenset()

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.cancelled = threading.Event()
        self.finished = threading.Event()
        self.calls = 0
        self.observer = None

    def run(self, request):
        self.calls += 1
        self.started.set()
        try:
            assert self.release.wait(timeout=5), "test did not release blocked adapter"
            return AgentResult(adapter_name=self.name, role=request.role, text="completed")
        finally:
            self.finished.set()

    def cancel(self) -> None:
        self.cancelled.set()

    def process_info(self):
        return None, None

    def set_process_observer(self, observer) -> None:
        self.observer = observer


class AdapterFactory:
    def __init__(self) -> None:
        self.created: list[ControlledAdapter] = []
        self.registry = AgentRegistry()
        self.registry.register(ControlledAdapter(), execution_factory=self.create)

    def create(self) -> ControlledAdapter:
        adapter = ControlledAdapter()
        self.created.append(adapter)
        return adapter

    def release_all(self) -> None:
        for adapter in self.created:
            adapter.release.set()


def _store(tmp_path: Path) -> Store:
    store = Store(tmp_path / "state.db")
    store.initialize()
    return store


def test_second_service_cannot_reconcile_another_live_owner(tmp_path: Path) -> None:
    store = _store(tmp_path)
    factory = AdapterFactory()
    first = WorkerService(store, factory.registry, tmp_path / "first-workspace")
    second = None
    try:
        worker = first.dispatch("owner", prompt="blocked")
        execution = factory.created[0]
        assert execution.started.wait(timeout=2)
        attempt = store.list_worker_attempts(worker.id)[0]
        assert attempt.service_owner_id == first.service_owner_id

        independent_store = Store(store.database)
        independent_store.initialize()
        second = WorkerService(independent_store, factory.registry, tmp_path / "second-workspace")
        assert independent_store.get_worker(worker.id).phase is WorkerPhase.RUNNING
        assert second.reconcile("owner") == 0
        assert independent_store.get_worker(worker.id).phase is WorkerPhase.RUNNING
        assert independent_store.get_worker_attempt(worker.id, attempt.id).status == "running"
        assert not execution.cancelled.is_set()

        execution.release.set()
        assert first.wait("owner", worker.id, timeout=2).outcome is WorkerOutcome.SUCCESS
        assert all(event["type"] != "worker_lost" for event in store.list_worker_events(worker.id))
    finally:
        factory.release_all()
        first.close()
        if second is not None:
            second.close()


def test_single_slot_cancelled_queue_never_calls_its_adapter(tmp_path: Path) -> None:
    store = _store(tmp_path)
    factory = AdapterFactory()
    service = WorkerService(store, factory.registry, tmp_path / "workspace", max_workers=1)
    try:
        first = service.dispatch("owner", prompt="occupy slot")
        running = factory.created[0]
        assert running.started.wait(timeout=2)
        queued = service.dispatch("owner", prompt="cancel before start")
        cancelled = factory.created[1]
        assert not cancelled.started.is_set()
        assert service.cancel("owner", queued.id).outcome is WorkerOutcome.STOPPED

        sentinel = service.dispatch("owner", prompt="prove queue drained")
        last = factory.created[2]
        running.release.set()
        assert last.started.wait(timeout=2)
        assert cancelled.calls == 0
        assert not cancelled.started.is_set()
        assert service.wait("owner", queued.id, timeout=0).outcome is WorkerOutcome.STOPPED
        assert service.wait("owner", first.id, timeout=2).outcome is WorkerOutcome.SUCCESS
        last.release.set()
        assert service.wait("owner", sentinel.id, timeout=2).outcome is WorkerOutcome.SUCCESS
    finally:
        factory.release_all()
        service.close()


def test_same_type_factory_adapters_cancel_only_the_target_worker(tmp_path: Path) -> None:
    store = _store(tmp_path)
    factory = AdapterFactory()
    service = WorkerService(store, factory.registry, tmp_path / "workspace", max_workers=2)
    try:
        target = service.dispatch("owner", prompt="cancel target")
        unrelated = service.dispatch("owner", prompt="keep running")
        cancelled, survivor = factory.created
        assert cancelled is not survivor
        assert cancelled.started.wait(timeout=2)
        assert survivor.started.wait(timeout=2)
        assert service.cancel("owner", target.id).outcome is WorkerOutcome.STOPPED
        assert cancelled.cancelled.is_set()
        assert not survivor.cancelled.is_set()
        assert service.wait("owner", unrelated.id, timeout=0).phase is WorkerPhase.RUNNING

        cancelled.release.set()
        survivor.release.set()
        assert service.wait("owner", unrelated.id, timeout=2).outcome is WorkerOutcome.SUCCESS
        assert service.wait("owner", target.id, timeout=0).outcome is WorkerOutcome.STOPPED
    finally:
        factory.release_all()
        service.close()


def test_old_attempt_completion_cannot_release_resumed_execution_handle(tmp_path: Path) -> None:
    store = _store(tmp_path)
    factory = AdapterFactory()
    service = WorkerService(store, factory.registry, tmp_path / "workspace", max_workers=2)
    try:
        worker = service.dispatch("owner", prompt="first attempt")
        original = factory.created[0]
        assert original.started.wait(timeout=2)
        first_attempt = store.list_worker_attempts(worker.id)[0]
        # The future is only a test synchronization point: its completion proves the old
        # finally/callback path has run before exercising cancellation of the new attempt.
        old_completion = service._futures[first_attempt.id]
        service.cancel("owner", worker.id)
        resumed = service.resume("owner", worker.id, prompt="second attempt")
        replacement = factory.created[1]
        assert replacement.started.wait(timeout=2)
        original.release.set()
        old_completion.result(timeout=2)

        assert service.wait("owner", resumed.id, timeout=0).phase is WorkerPhase.RUNNING
        assert not replacement.cancelled.is_set()
        assert store.get_worker_attempt(worker.id, first_attempt.id).outcome is WorkerOutcome.STOPPED
        assert service.cancel("owner", resumed.id).outcome is WorkerOutcome.STOPPED
        assert replacement.cancelled.is_set()
    finally:
        factory.release_all()
        service.close()


def _hold_owner_lock(database: str, service_owner_id: str, acquired, release) -> None:
    lock = WorkerOwnerLock.acquire(Path(database), service_owner_id, create=True)
    assert lock is not None
    try:
        acquired.set()
        assert release.wait(timeout=10), "test did not release service owner lock"
    finally:
        lock.close()


def test_cross_process_owner_liveness_and_recovery_are_caller_scoped(tmp_path: Path) -> None:
    store = _store(tmp_path)
    factory = AdapterFactory()
    service = WorkerService(store, factory.registry, tmp_path / "separate-workspace")
    service_owner_id = "worker-owner-" + "a" * 32
    context = get_context("spawn")
    acquired, release = context.Event(), context.Event()
    holder = context.Process(
        target=_hold_owner_lock, args=(str(store.database), service_owner_id, acquired, release),
    )
    holder.start()
    try:
        assert acquired.wait(timeout=5), "child did not acquire owner lock"
        worker = store.create_worker("owner", "worker", "interrupted execution")
        interrupted = store.start_worker_attempt(worker.id, "owner", "work", service_owner_id=service_owner_id)
        other = store.create_worker("other-caller", "worker", "another caller")
        other_attempt = store.start_worker_attempt(
            other.id, "other-caller", "work", service_owner_id=service_owner_id,
        )
        legacy = store.create_worker("owner", "worker", "legacy unknown ownership")
        legacy_attempt = store.start_worker_attempt(legacy.id, "owner", "legacy work")

        assert service.reconcile("owner") == 0
        assert store.get_worker_attempt(worker.id, interrupted.id).status == "running"
        release.set()
        holder.join(timeout=3)
        assert not holder.is_alive()
        assert holder.exitcode == 0

        assert service.reconcile("owner") == 1
        assert store.get_worker_attempt(worker.id, interrupted.id).outcome is WorkerOutcome.LOST
        assert store.get_worker_attempt(other.id, other_attempt.id).status == "running"
        assert store.get_worker_attempt(legacy.id, legacy_attempt.id).status == "running"
        assert service.reconcile("owner") == 0
    finally:
        release.set()
        holder.join(timeout=3)
        if holder.is_alive():
            holder.terminate()
            holder.join(timeout=2)
        service.close()


def test_missing_owner_lock_is_unknown_and_does_not_prove_owner_death(tmp_path: Path) -> None:
    store = _store(tmp_path)
    factory = AdapterFactory()
    service = WorkerService(store, factory.registry, tmp_path / "workspace")
    try:
        worker = store.create_worker("owner", "worker", "unknown ownership evidence")
        attempt = store.start_worker_attempt(
            worker.id, "owner", "work", service_owner_id="worker-owner-" + "b" * 32,
        )
        assert service.reconcile("owner") == 0
        assert store.get_worker_attempt(worker.id, attempt.id).status == "running"
    finally:
        service.close()


def test_service_close_keeps_owner_live_until_active_adapter_has_drained(tmp_path: Path) -> None:
    store = _store(tmp_path)
    factory = AdapterFactory()
    first = WorkerService(store, factory.registry, tmp_path / "first-workspace")
    second = WorkerService(store, factory.registry, tmp_path / "second-workspace")
    try:
        worker = first.dispatch("owner", prompt="delayed cleanup")
        execution = factory.created[0]
        assert execution.started.wait(timeout=2)
        attempt = store.list_worker_attempts(worker.id)[0]
        completion = first._futures[attempt.id]
        first.close()
        assert execution.cancelled.is_set()
        assert WorkerOwnerLock.acquire(store.database, first.service_owner_id) is None
        assert second.reconcile("owner") == 0

        execution.release.set()
        completion.result(timeout=2)
        released = WorkerOwnerLock.acquire(store.database, first.service_owner_id)
        assert released is not None
        released.close()
        assert store.get_worker(worker.id).outcome is WorkerOutcome.STOPPED
    finally:
        factory.release_all()
        first.close()
        second.close()


def test_closing_old_service_cannot_cancel_another_services_resumed_attempt(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first_factory, second_factory = AdapterFactory(), AdapterFactory()
    first = WorkerService(store, first_factory.registry, tmp_path / "first-workspace")
    second = WorkerService(store, second_factory.registry, tmp_path / "second-workspace")
    try:
        worker = first.dispatch("owner", prompt="cancelled old attempt")
        old_execution = first_factory.created[0]
        assert old_execution.started.wait(timeout=2)
        old_attempt = store.list_worker_attempts(worker.id)[0]
        old_completion = first._futures[old_attempt.id]
        first.cancel("owner", worker.id)
        second.resume("owner", worker.id, prompt="new service owns execution")
        replacement = second_factory.created[0]
        assert replacement.started.wait(timeout=2)
        new_attempt = store.list_worker_attempts(worker.id)[-1]

        first.close()
        old_execution.release.set()
        old_completion.result(timeout=2)
        assert store.get_worker_attempt(worker.id, old_attempt.id).outcome is WorkerOutcome.STOPPED
        assert store.get_worker_attempt(worker.id, new_attempt.id).status == "running"
        assert not replacement.cancelled.is_set()
        replacement.release.set()
        assert second.wait("owner", worker.id, timeout=2).outcome is WorkerOutcome.SUCCESS
    finally:
        first_factory.release_all()
        second_factory.release_all()
        first.close()
        second.close()


def test_process_store_read_failure_does_not_block_other_owned_cancellation(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    factory = AdapterFactory()
    service = WorkerService(store, factory.registry, tmp_path / "workspace", max_workers=2)
    original_list = store.list_worker_processes
    completions = []
    retained = []

    def failed_cleanup(registrations):
        return tuple(ProcessCleanupResult(
            reg.label, reg.pid, reg.pgid, ProcessCleanupStatus.CALLBACK_FAILED, alive_after=True,
        ) for reg in registrations)

    monkeypatch.setattr(workers, "cleanup_registered_processes", failed_cleanup)
    try:
        parent = service.dispatch("owner", prompt="parent")
        child = service.dispatch("owner", prompt="child", parent_worker_id=parent.id)
        assert all(adapter.started.wait(timeout=2) for adapter in factory.created)
        for index, worker in enumerate((parent, child)):
            attempt = store.list_worker_attempts(worker.id)[0]
            completions.append(service._futures[attempt.id])
            identity = (worker.id, attempt.id, service.service_owner_id, 999_999_991 + index, 999_999_991 + index)
            assert store.register_worker_process(*identity)
            retained.append(identity)
        observed = []

        def fail_parent_read(worker_id, attempt_id, service_owner_id):
            observed.append(worker_id)
            if worker_id == parent.id:
                raise OSError("store read failed")
            return original_list(worker_id, attempt_id, service_owner_id)

        monkeypatch.setattr(store, "list_worker_processes", fail_parent_read)
        assert service.cancel("owner", parent.id).outcome is WorkerOutcome.STOPPED
        assert all(adapter.cancelled.is_set() for adapter in factory.created)
        assert parent.id in observed and child.id in observed
        assert all(original_list(*identity[:3]) for identity in retained)
    finally:
        monkeypatch.setattr(store, "list_worker_processes", original_list)
        factory.release_all()
        for completion in completions:
            completion.result(timeout=2)
        for identity in retained:
            store.clear_worker_process(*identity)
        service.close()


def test_submit_and_compensating_settlement_failure_release_idle_owner(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    factory = AdapterFactory()
    service = WorkerService(store, factory.registry, tmp_path / "workspace")
    original_settle = store.settle_worker

    def fail_submit(*args, **kwargs):
        raise RuntimeError("executor submit failed")

    def fail_settle(*args, **kwargs):
        raise OSError("settlement persistence failed")

    monkeypatch.setattr(service._executor, "submit", fail_submit)
    monkeypatch.setattr(store, "settle_worker", fail_settle)
    try:
        with pytest.raises((OSError, RuntimeError)):
            service.dispatch("owner", prompt="submission will fail")
        assert service._active == {}
        assert service._futures == {}
        assert service._owner_lock is None
        probe = WorkerOwnerLock.acquire(store.database, service.service_owner_id)
        assert probe is not None
        probe.close()
        assert all(adapter.calls == 0 for adapter in factory.created)
        monkeypatch.setattr(store, "settle_worker", original_settle)
        assert service.reconcile("owner") == 1
        assert store.list_workers("owner")[0].outcome is WorkerOutcome.LOST
    finally:
        monkeypatch.setattr(store, "settle_worker", original_settle)
        factory.release_all()
        service.close()


def test_transient_close_settlement_failure_still_records_stopped_after_store_recovers(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    factory = AdapterFactory()
    service = WorkerService(store, factory.registry, tmp_path / "workspace")

    def fail_settle(*args, **kwargs):
        raise OSError("temporary settlement failure")

    try:
        worker = service.dispatch("owner", prompt="close despite temporary persistence failure")
        execution = factory.created[0]
        assert execution.started.wait(timeout=2)
        with monkeypatch.context() as failure:
            failure.setattr(store, "settle_worker", fail_settle)
            service.close()
        assert execution.cancelled.is_set()
        execution.release.set()
        result = service.wait("owner", worker.id, timeout=2)
        assert result.outcome is WorkerOutcome.STOPPED
        assert result.stop_reason is WorkerStopReason.CANCELLED
    finally:
        factory.release_all()
        service.close()


def test_subprocess_runtime_cannot_swallow_worker_process_registration_failure(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    command = [sys.executable, "-c", "import time; time.sleep(10); print('unregistered execution completed')"]
    registry = AgentRegistry([
        RuntimeAgentAdapter(SubprocessRuntime(command), runtime_factory=lambda: SubprocessRuntime(command)),
    ])
    service = WorkerService(store, registry, tmp_path / "workspace")
    observed = []

    def fail_registration(worker_id, attempt_id, service_owner_id, pid, pgid):
        observed.append((pid, pgid))
        raise OSError("test process registration failed")

    monkeypatch.setattr(store, "register_worker_process", fail_registration)
    try:
        worker = service.dispatch("owner", prompt="registration must precede execution", timeout=8)
        result = service.wait("owner", worker.id, timeout=3)
        assert result.outcome is WorkerOutcome.FAILURE
        assert result.stop_reason is WorkerStopReason.PROCESS_CLEANUP
        assert observed
        pid, pgid = observed[0]
        assert pid == pgid
        with pytest.raises(ProcessLookupError):
            os.killpg(pgid, 0)
        attempt = store.list_worker_attempts(worker.id)[0]
        assert store.list_worker_processes(worker.id, attempt.id, service.service_owner_id) == []
        assert "test process registration failed" not in (result.last_error or "")
    finally:
        service.close()


def test_close_before_delayed_process_launch_prevents_execution_after_settlement_failure(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    command = [
        sys.executable, "-c",
        "import pathlib,sys; sys.stdin.read(); pathlib.Path('closed-launch-marker').write_text('executed'); print('done')",
    ]
    created = []

    class DelayedRuntime(SubprocessRuntime):
        def __init__(self) -> None:
            super().__init__(command)
            self.before_launch = threading.Event()
            self.release_launch = threading.Event()

        def run(self, prompt, workspace, timeout=None):
            # RuntimeAgentAdapter has already checked its continuation guard when this
            # boundary is reached, but there is no Popen handle for close() to cancel yet.
            self.before_launch.set()
            assert self.release_launch.wait(timeout=5), "test did not release delayed process launch"
            return super().run(prompt, workspace, timeout)

    def create_runtime():
        runtime = DelayedRuntime()
        created.append(runtime)
        return runtime

    def fail_settle(*args, **kwargs):
        raise OSError("temporary close settlement failure")

    registry = AgentRegistry([
        RuntimeAgentAdapter(SubprocessRuntime(command), runtime_factory=create_runtime),
    ])
    service = WorkerService(store, registry, tmp_path / "workspace")
    try:
        worker = service.dispatch("owner", prompt="no execution after close", timeout=3)
        runtime = created[0]
        assert runtime.before_launch.wait(timeout=2)
        attempt = store.list_worker_attempts(worker.id)[0]
        completion = service._futures[attempt.id]
        with monkeypatch.context() as failure:
            failure.setattr(store, "settle_worker", fail_settle)
            service.close()
        assert store.get_worker_attempt(worker.id, attempt.id).status == "running"
        runtime.release_launch.set()
        completion.result(timeout=3)

        marker = service.workspace / "workers" / worker.id / attempt.id / "closed-launch-marker"
        assert not marker.exists()
        assert store.get_worker(worker.id).outcome is WorkerOutcome.STOPPED
        assert store.list_worker_processes(worker.id, attempt.id, service.service_owner_id) == []
        assert service._owner_lock is None
    finally:
        for runtime in created:
            runtime.release_launch.set()
        service.close()
