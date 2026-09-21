from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from time import monotonic

import pytest
from test_worker_delegate import _controller, _StructuredArtifactAdapter

from lunar_evolution.algorithm import OutputSpec
from lunar_evolution.controller import WorkerObservationTimeout


class _ControllerCrash(BaseException):
    """Simulate process loss without running the normal exception compensation path."""


def _structured_controller(tmp_path, monkeypatch):
    controller = _controller(tmp_path, _StructuredArtifactAdapter())
    monkeypatch.setattr(
        controller, "_task_output_specs", lambda run, task: (OutputSpec("output/value.txt", "text"),)
    )
    return controller


def _backdate_delivery(controller, run_id):
    binding = controller.store.list_worker_bindings(run_id)[0]
    assert binding.status == "delivering"
    with controller.store._connect() as connection:
        connection.execute(
            "UPDATE worker_bindings SET updated_at = ? WHERE worker_id = ?",
            ((datetime.now(UTC) - timedelta(minutes=5)).isoformat(), binding.worker_id),
        )
    return binding


def _crash_delivery(controller, run_id, monkeypatch, crash_stage):
    def crash(*args, **kwargs):
        raise _ControllerCrash(crash_stage)

    target, method = (
        (controller, "_evaluate")
        if crash_stage == "evaluation"
        else (controller.store, "complete_worker_binding")
    )
    monkeypatch.setattr(target, method, crash)
    with pytest.raises(_ControllerCrash, match=crash_stage):
        controller.run_worker_agent(run_id)
    binding = _backdate_delivery(controller, run_id)
    kinds = [item["kind"] for item in controller.store.list_artifacts(run_id)]
    assert kinds.count("result") == kinds.count("runtime") == 1
    assert kinds.count("output") == (0 if crash_stage == "evaluation" else 1)
    assert controller.store.get_task(binding.task_id).state.value == "running"
    return binding


@pytest.mark.parametrize("crash_stage", ["evaluation", "commit"])
def test_worker_delivery_recovers_crash_after_staging_without_duplicate_artifacts(
    tmp_path: Path, monkeypatch, crash_stage: str,
):
    first = _structured_controller(tmp_path, monkeypatch)
    run = first.create("recover interrupted delivery")
    binding = _crash_delivery(first, run.id, monkeypatch, crash_stage)
    second = _structured_controller(tmp_path, monkeypatch)

    settled, result = second.run_worker_agent(run.id, wait_timeout=1)

    assert settled.status.value == "succeeded"
    assert result.text == "completed"
    assert second.store.get_worker_binding(binding.worker_id).status == "settled"
    assert len(second.store.list_worker_bindings(run.id)) == 1
    assert second.store.get_attempt(binding.task_attempt_id).status == "succeeded"
    artifacts = second.store.list_artifacts(run.id)
    for kind in ("result", "runtime", "output"):
        assert sum(item["kind"] == kind for item in artifacts) == 1
    for artifact in artifacts:
        assert (run.workspace / artifact["path"]).is_file()
    assert (run.workspace / "output/value.txt").read_text(encoding="utf-8") == "verified output"
    events = second.store.list_events(run.id)
    for event_type in ("agent_finished", "task_evaluated", "task_succeeded"):
        assert sum(event["type"] == event_type for event in events) == 1


def test_live_worker_delivery_observer_respects_timeout_and_releases_controller_lock(
    tmp_path: Path, monkeypatch,
):
    first = _structured_controller(tmp_path, monkeypatch)
    run = first.create("observe live delivery")
    second = _structured_controller(tmp_path, monkeypatch)
    staged, release = Event(), Event()
    original_evaluate = first._evaluate
    results, errors = [], []

    def hold_delivery(*args, **kwargs):
        staged.set()
        assert release.wait(5), "test did not release the delivery owner"
        return original_evaluate(*args, **kwargs)

    def deliver():
        try:
            results.append(first.run_worker_agent(run.id, timeout=1))
        except BaseException as exc:  # noqa: BLE001 - surface every background observer failure
            errors.append(exc)

    monkeypatch.setattr(first, "_evaluate", hold_delivery)
    delivery_thread = Thread(target=deliver)
    delivery_thread.start()
    acquired = []
    try:
        assert staged.wait(2), "worker did not reach result delivery"
        binding = _backdate_delivery(first, run.id)
        started = monotonic()
        with pytest.raises(WorkerObservationTimeout):
            second.run_worker_agent(run.id, wait_timeout=0.02)
        elapsed = monotonic() - started

        def probe_controller_lock():
            locked = second._active_lock.acquire(timeout=0.2)
            acquired.append(locked)
            if locked:
                second._active_lock.release()

        probe = Thread(target=probe_controller_lock)
        probe.start()
        probe.join(timeout=1)
        assert not probe.is_alive()
        assert second.store.get_worker_binding(binding.worker_id).status == "delivering"
        assert [item["kind"] for item in second.store.list_artifacts(run.id)].count("result") == 1
    finally:
        release.set()
        delivery_thread.join(timeout=3)

    assert not delivery_thread.is_alive()
    assert errors == []
    assert len(results) == 1 and results[0][0].status.value == "succeeded"
    assert elapsed < 0.5, f"observation timeout included {elapsed:.3f}s of delivery waiting"
    assert acquired == [True], "observation timeout leaked the controller's active lock"


def test_cancel_stale_worker_delivery_removes_staged_and_promoted_artifacts(
    tmp_path: Path, monkeypatch,
):
    first = _structured_controller(tmp_path, monkeypatch)
    run = first.create("cancel abandoned delivery")
    binding = _crash_delivery(first, run.id, monkeypatch, "commit")
    staged_paths = [
        run.workspace / item["path"]
        for item in first.store.list_artifacts(run.id)
        if item["kind"] in {"result", "runtime", "output"}
    ]
    second = _structured_controller(tmp_path, monkeypatch)

    assert second.cancel(run.id)

    assert second.store.get_run(run.id).status.value == "cancelled"
    assert second.store.get_task(binding.task_id).state.value == "cancelled"
    assert second.store.get_worker_binding(binding.worker_id).status == "discarded"
    assert not any(
        item["kind"] in {"result", "runtime", "output"}
        for item in second.store.list_artifacts(run.id)
    )
    assert all(not path.exists() for path in staged_paths)
    assert not any(
        event["type"] in {"agent_finished", "task_evaluated", "task_succeeded"}
        for event in second.store.list_events(run.id)
    )


@pytest.mark.parametrize("after_ledger", [False, True])
@pytest.mark.parametrize("cancel", [False, True])
def test_output_write_interruption_recovers_or_cleans_exact_batch(
    tmp_path: Path, monkeypatch, after_ledger: bool, cancel: bool,
):
    first = _structured_controller(tmp_path, monkeypatch)
    run = first.create("interrupted output publication")
    original_add = first.store.add_artifact

    def crash_at_output(*args, **kwargs):
        kind = args[5] if len(args) > 5 else kwargs.get("kind", "result")
        if kind == "output":
            if after_ledger:
                original_add(*args, **kwargs)
            raise _ControllerCrash("output record")
        return original_add(*args, **kwargs)

    monkeypatch.setattr(first.store, "add_artifact", crash_at_output)
    with pytest.raises(_ControllerCrash):
        first.run_worker_agent(run.id)
    assert (run.workspace / "output/value.txt").is_file()
    binding = _backdate_delivery(first, run.id)
    second = _structured_controller(tmp_path, monkeypatch)
    if cancel:
        assert second.cancel(run.id)
        assert not (run.workspace / "output/value.txt").exists()
        assert not any(a["kind"] in {"result", "runtime", "output"}
                       for a in second.store.list_artifacts(run.id))
        assert second.store.get_worker_binding(binding.worker_id).status == "discarded"
    else:
        assert second.run_worker_agent(run.id)[0].status.value == "succeeded"
        kinds = [a["kind"] for a in second.store.list_artifacts(run.id)]
        assert kinds.count("result") == kinds.count("runtime") == kinds.count("output") == 1


def test_worker_delivery_counts_promoted_output_toward_artifact_budget(tmp_path: Path, monkeypatch):
    from dataclasses import replace

    from lunar_evolution.budget import BudgetExceeded, BudgetSpec

    controller = _structured_controller(tmp_path, monkeypatch)
    route = replace(controller.router.route("bounded output"), budget=BudgetSpec(max_artifact_bytes=30))
    run = controller.store.create_run("bounded output", route=route)
    with pytest.raises(BudgetExceeded, match="max_artifact_bytes"):
        controller.run_worker_agent(run.id)
    assert controller.store.get_run(run.id).status.value == "failed"
    assert not (run.workspace / "output/value.txt").exists()
    assert not any(a["kind"] in {"result", "runtime", "output"}
                   for a in controller.store.list_artifacts(run.id))
