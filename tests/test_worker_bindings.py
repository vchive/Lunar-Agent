from __future__ import annotations

import pytest

from lunar_evolution.store import Store


def _claimed_records(tmp_path):
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("bind one delegated task")
    task = store.next_task(run.id)
    assert task is not None
    task_attempt = store.claim_task(task.id, "command")
    assert task_attempt is not None
    worker = store.create_worker("owner", "solver", "delegated task", agent_type="fixture")
    worker_attempt = store.start_worker_attempt(
        worker.id, "owner", task.prompt, service_owner_id="service-owner",
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
