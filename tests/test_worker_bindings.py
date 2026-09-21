from __future__ import annotations

import pytest

from lunar_evolution.agents import AgentRegistry
from lunar_evolution.models import WorkerOutcome, WorkerPhase
from lunar_evolution.store import Store
from lunar_evolution.worker_ownership import WorkerOwnerLock
from lunar_evolution.workers import WorkerService


def _claimed_records(tmp_path, service_owner_id: str = "service-owner"):
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("bind one delegated task")
    task = store.next_task(run.id)
    assert task is not None
    task_attempt = store.claim_task(task.id, "command")
    assert task_attempt is not None
    worker = store.create_worker("owner", "solver", "delegated task", agent_type="fixture")
    worker_attempt = store.start_worker_attempt(
        worker.id, "owner", task.prompt, service_owner_id=service_owner_id,
    )
    return store, run, task, task_attempt, worker, worker_attempt


def test_worker_binding_requires_reciprocal_running_records(tmp_path):
    store, run, task, task_attempt, worker, worker_attempt = _claimed_records(tmp_path)

    binding = store.bind_worker(
        worker_id=worker.id,
        worker_attempt_id=worker_attempt.id,
        run_id=run.id,
        task_id=task.id,
        task_attempt_id=task_attempt.id,
        service_owner_id="service-owner",
        active_timeout=12,
    )

    assert binding.status == "active"
    assert binding.active_timeout == 12
    assert store.get_worker_binding(worker.id) == binding
    assert store.list_worker_bindings(run.id, status="active") == [binding]
    assert store.settle_worker_binding(worker.id, "settled") is True
    assert store.settle_worker_binding(worker.id, "discarded") is False


def test_delivery_reservation_recovers_only_after_stale_timestamp(tmp_path):
    store, run, task, task_attempt, worker, worker_attempt = _claimed_records(
        tmp_path, "worker-owner-" + "b" * 32
    )
    store.bind_worker(
        worker_id=worker.id,
        worker_attempt_id=worker_attempt.id,
        run_id=run.id,
        task_id=task.id,
        task_attempt_id=task_attempt.id,
        service_owner_id=worker_attempt.service_owner_id,
        active_timeout=2,
    )
    assert store.claim_worker_binding_delivery(
        worker_id=worker.id,
        worker_attempt_id=worker_attempt.id,
        run_id=run.id,
        task_id=task.id,
        task_attempt_id=task_attempt.id,
    )
    assert store.recover_worker_binding_delivery(
        worker_id=worker.id, worker_attempt_id=worker_attempt.id, stale_after=60
    ) is False
    with store._connect() as connection:
        connection.execute(
            "UPDATE worker_bindings SET updated_at = datetime('now', '-120 seconds') WHERE worker_id = ?",
            (worker.id,),
        )
    assert store.recover_worker_binding_delivery(
        worker_id=worker.id, worker_attempt_id=worker_attempt.id, stale_after=60
    ) is True
    assert store.get_worker_binding(worker.id).status == "active"


def test_live_delivery_owner_lock_cannot_be_stolen(tmp_path):
    service_owner_id = "worker-owner-" + "c" * 32
    store, run, task, task_attempt, worker, worker_attempt = _claimed_records(tmp_path, service_owner_id)
    store.bind_worker(
        worker_id=worker.id, worker_attempt_id=worker_attempt.id, run_id=run.id,
        task_id=task.id, task_attempt_id=task_attempt.id, service_owner_id=service_owner_id,
        active_timeout=2,
    )
    assert store.claim_worker_binding_delivery(
        worker_id=worker.id, worker_attempt_id=worker_attempt.id, run_id=run.id,
        task_id=task.id, task_attempt_id=task_attempt.id,
    )
    owner = "worker-owner-" + __import__("hashlib").sha256(worker.id.encode()).hexdigest()[:32]
    lock = WorkerOwnerLock.acquire(store.database, owner, create=True)
    assert lock is not None
    try:
        assert WorkerOwnerLock.acquire(store.database, owner) is None
        assert store.recover_worker_binding_delivery(
            worker_id=worker.id, worker_attempt_id=worker_attempt.id, stale_after=60,
        ) is False
        assert store.get_worker_binding(worker.id).status == "delivering"
    finally:
        lock.close()


def test_worker_binding_rejects_wrong_owner_or_duplicate_task_attempt(tmp_path):
    store, run, task, task_attempt, worker, worker_attempt = _claimed_records(tmp_path)
    with pytest.raises(ValueError, match="reciprocal"):
        store.bind_worker(
            worker_id=worker.id,
            worker_attempt_id=worker_attempt.id,
            run_id=run.id,
            task_id=task.id,
            task_attempt_id=task_attempt.id,
            service_owner_id="other-owner",
        )

    binding = store.bind_worker(
        worker_id=worker.id,
        worker_attempt_id=worker_attempt.id,
        run_id=run.id,
        task_id=task.id,
        task_attempt_id=task_attempt.id,
        service_owner_id="service-owner",
    )
    assert binding.worker_id == worker.id
    with pytest.raises(ValueError, match="already has a binding"):
        store.bind_worker(
            worker_id=worker.id,
            worker_attempt_id=worker_attempt.id,
            run_id=run.id,
            task_id=task.id,
            task_attempt_id=task_attempt.id,
            service_owner_id="service-owner",
        )


def test_reconcile_marks_only_matching_active_binding_lost(tmp_path):
    service_owner_id = "worker-owner-" + "a" * 32
    store, run, task, task_attempt, worker, worker_attempt = _claimed_records(tmp_path, service_owner_id)
    store.bind_worker(
        worker_id=worker.id,
        worker_attempt_id=worker_attempt.id,
        run_id=run.id,
        task_id=task.id,
        task_attempt_id=task_attempt.id,
        service_owner_id=service_owner_id,
    )
    other_run = store.create_run("retain another caller binding")
    other_task = store.next_task(other_run.id)
    assert other_task is not None
    other_task_attempt = store.claim_task(other_task.id, "command")
    assert other_task_attempt is not None
    other_worker = store.create_worker("other-owner", "solver", "other delegated task", agent_type="fixture")
    other_worker_attempt = store.start_worker_attempt(
        other_worker.id, "other-owner", other_task.prompt, service_owner_id=service_owner_id,
    )
    other_binding = store.bind_worker(
        worker_id=other_worker.id,
        worker_attempt_id=other_worker_attempt.id,
        run_id=other_run.id,
        task_id=other_task.id,
        task_attempt_id=other_task_attempt.id,
        service_owner_id=service_owner_id,
    )
    lock = WorkerOwnerLock.acquire(store.database, service_owner_id, create=True)
    assert lock is not None
    lock.close()
    service = WorkerService(store, AgentRegistry(), tmp_path / "worker-workspace")
    try:
        assert service.reconcile("owner") == 1
        assert store.get_worker_binding(worker.id).status == "lost"
        assert store.get_worker_attempt(worker.id, worker_attempt.id).outcome is WorkerOutcome.LOST
        assert store.get_worker(worker.id).phase is WorkerPhase.IDLE
        assert store.get_worker_binding(other_worker.id) == other_binding
        assert store.get_worker_attempt(other_worker.id, other_worker_attempt.id).status == "running"
        assert service.reconcile("owner") == 0
        assert store.get_worker_binding(worker.id).status == "lost"
    finally:
        service.close()
