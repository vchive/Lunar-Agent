from __future__ import annotations

from pathlib import Path
from threading import Event

import pytest

from lunar_evolution.agents import AgentRegistry, AgentResult
from lunar_evolution.algorithm import OutputSpec
from lunar_evolution.config import Config
from lunar_evolution.controller import (
    AgentInvocationError,
    LocalController,
    WorkerObservationTimeout,
)
from lunar_evolution.runtime import MockRuntime


class _ArtifactAdapter:
    name = "worker-fixture"
    roles = frozenset({"solver"})
    capabilities = frozenset({"read_files", "write_artifacts"})

    def run(self, request):
        (request.workspace / "answer.txt").write_text("verified artifact", encoding="utf-8")
        return AgentResult(
            adapter_name=self.name, role=request.role, text="completed",
            artifacts=("answer.txt",), metadata={"fixture": "worker"},
        )

    def cancel(self):
        return None

    def process_info(self):
        return None, None

    def set_process_observer(self, observer):
        del observer


class _BlockingAdapter(_ArtifactAdapter):
    started = Event()
    released = Event()

    @classmethod
    def reset(cls):
        cls.started = Event()
        cls.released = Event()

    def run(self, request):
        type(self).started.set()
        type(self).released.wait(2)
        return super().run(request)

    def cancel(self):
        type(self).released.set()


class _StructuredArtifactAdapter(_ArtifactAdapter):
    def run(self, request):
        output = request.workspace / "output"
        output.mkdir(parents=True, exist_ok=True)
        (output / "value.txt").write_text("verified output", encoding="utf-8")
        return AgentResult(
            adapter_name=self.name, role=request.role, text="completed",
            artifacts=("output/value.txt",), metadata={"fixture": "structured"},
        )


class _NeverInvokedAdapter(_ArtifactAdapter):
    invoked = False

    def run(self, request):
        type(self).invoked = True
        return super().run(request)


class _TraversalArtifactAdapter(_ArtifactAdapter):
    def run(self, request):
        return AgentResult(
            adapter_name=self.name, role=request.role, text="bad",
            artifacts=("../escape.txt",), metadata={},
        )


class _SymlinkArtifactAdapter(_ArtifactAdapter):
    def run(self, request):
        nested = request.workspace / "nested"
        nested.mkdir(parents=True, exist_ok=True)
        (nested / "target.txt").write_text("outside", encoding="utf-8")
        (request.workspace / "link").symlink_to(nested / "target.txt")
        return AgentResult(
            adapter_name=self.name, role=request.role, text="bad",
            artifacts=("link",), metadata={},
        )


def _controller(tmp_path: Path, adapter) -> LocalController:
    registry = AgentRegistry()
    registry.register(adapter, execution_factory=type(adapter))
    return LocalController(Config(tmp_path / ".lunar-evolution"), MockRuntime(), agent_registry=registry)


def test_worker_delegate_materializes_verified_artifacts_and_settles_binding(tmp_path: Path):
    controller = _controller(tmp_path, _ArtifactAdapter())
    run = controller.create("write an artifact")

    settled, result = controller.run_worker_agent(run.id)

    assert settled.status.value == "succeeded"
    assert result.to_dict()["metadata"] == {"fixture": "worker"}
    binding = controller.store.list_worker_bindings(run.id)[0]
    assert binding.status == "settled"
    envelope = controller.store.get_worker_result(binding.worker_id, binding.worker_attempt_id, owner_id=run.id)
    assert envelope is not None
    assert envelope.artifact_manifest[0]["sha256"]
    artifacts = controller.store.list_artifacts(run.id)
    copied = next(item for item in artifacts if item["kind"] == "runtime")
    assert (run.workspace / copied["path"]).read_text(encoding="utf-8") == "verified artifact"


def test_worker_delegate_rejects_artifact_changed_after_worker_completion(tmp_path: Path, monkeypatch):
    controller = _controller(tmp_path, _ArtifactAdapter())
    run = controller.create("write an artifact")
    original_wait = controller.workers.wait

    def tampering_wait(owner_id, worker_id, timeout=None):
        observed = original_wait(owner_id, worker_id, timeout)
        binding = controller.store.get_worker_binding(worker_id)
        assert binding is not None
        source = controller.workers.workspace / "workers" / worker_id / binding.worker_attempt_id / "answer.txt"
        source.write_text("tampered", encoding="utf-8")
        return observed

    monkeypatch.setattr(controller.workers, "wait", tampering_wait)
    with pytest.raises(ValueError, match="integrity check failed"):
        controller.run_worker_agent(run.id)

    task = controller.store.list_tasks(run.id)[0]
    assert task.state.value == "failed"
    assert controller.store.list_worker_bindings(run.id)[0].status == "discarded"
    assert not any(item["kind"] == "runtime" for item in controller.store.list_artifacts(run.id))


def test_worker_delegate_wait_timeout_keeps_binding_active_and_cancel_is_scoped(tmp_path: Path):
    _BlockingAdapter.reset()
    controller = _controller(tmp_path, _BlockingAdapter())
    run = controller.create("block until cancelled")

    with pytest.raises(WorkerObservationTimeout):
        controller.run_worker_agent(run.id, wait_timeout=0.01)

    assert _BlockingAdapter.started.wait(1)
    binding = controller.store.list_worker_bindings(run.id)[0]
    task = controller.store.list_tasks(run.id)[0]
    assert binding.status == "active"
    assert task.state.value == "running"
    assert controller.cancel(run.id) is True
    assert controller.store.get_run(run.id).status.value == "cancelled"
    assert controller.store.get_worker_binding(binding.worker_id).status == "discarded"
    controller.workers.wait(run.id, binding.worker_id, timeout=1)


def test_worker_delegate_discards_result_when_cancel_wins_delivery_race(tmp_path: Path, monkeypatch):
    controller = _controller(tmp_path, _ArtifactAdapter())
    run = controller.create("cancel at delivery")
    original_complete = controller.store.complete_worker_binding

    def cancel_before_commit(**kwargs):
        assert controller.cancel(run.id)
        return original_complete(**kwargs)

    monkeypatch.setattr(controller.store, "complete_worker_binding", cancel_before_commit)
    with pytest.raises(AgentInvocationError, match="binding is no longer active"):
        controller.run_worker_agent(run.id)

    assert controller.store.get_run(run.id).status.value == "cancelled"
    assert controller.store.list_tasks(run.id)[0].state.value == "cancelled"
    assert controller.store.list_worker_bindings(run.id)[0].status == "discarded"
    kinds = {item["kind"] for item in controller.store.list_artifacts(run.id)}
    assert "runtime" not in kinds
    assert "result" not in kinds
    event_types = [event["type"] for event in controller.store.list_events(run.id)]
    assert "agent_finished" not in event_types
    assert "task_evaluated" not in event_types


def test_worker_delegate_reuses_active_binding_after_observation_timeout(tmp_path: Path):
    _BlockingAdapter.reset()
    controller = _controller(tmp_path, _BlockingAdapter())
    run = controller.create("resume bound worker")

    with pytest.raises(WorkerObservationTimeout):
        controller.run_worker_agent(run.id, wait_timeout=0.01)
    task = controller.store.list_tasks(run.id)[0]
    binding = controller.store.list_worker_bindings(run.id)[0]
    _BlockingAdapter.released.set()

    settled, result = controller.run_worker_agent(run.id, task_id=task.id)

    assert settled.status.value == "succeeded"
    assert result.text == "completed"
    assert controller.store.get_worker_binding(binding.worker_id).status == "settled"


def test_worker_delegate_bind_failure_does_not_invoke_adapter_or_leave_binding(tmp_path: Path, monkeypatch):
    _NeverInvokedAdapter.invoked = False
    controller = _controller(tmp_path, _NeverInvokedAdapter())
    run = controller.create("bind failure")

    def fail_materialization(*args, **kwargs):
        raise ValueError("input materialization failed")

    monkeypatch.setattr(controller, "_materialize_task_input_data", fail_materialization)
    with pytest.raises(ValueError, match="input materialization failed"):
        controller.run_worker_agent(run.id)

    assert _NeverInvokedAdapter.invoked is False
    assert controller.store.list_worker_bindings(run.id)[0].status == "discarded"
    assert controller.store.list_tasks(run.id)[0].state.value == "failed"


def test_worker_delegate_rejects_pending_or_dependency_task_id(tmp_path: Path):
    registry = AgentRegistry()
    registry.register(_ArtifactAdapter(), execution_factory=_ArtifactAdapter)
    controller = LocalController(Config(tmp_path / ".lunar-evolution"), MockRuntime(), agent_registry=registry)
    run = controller.store.create_run(
        "dependency delegation",
        tasks=[
            {"id": "first", "title": "first", "prompt": "first"},
            {"id": "second", "title": "second", "prompt": "second", "depends_on": ["first"]},
        ],
    )
    with pytest.raises(ValueError, match="task is not ready"):
        controller.run_worker_agent(run.id, task_id="second")


@pytest.mark.parametrize("adapter", [_TraversalArtifactAdapter, _SymlinkArtifactAdapter])
def test_worker_delegate_rejects_unsafe_final_artifact(adapter, tmp_path: Path):
    controller = _controller(tmp_path, adapter())
    run = controller.create("unsafe artifact")

    if adapter is _TraversalArtifactAdapter:
        settled, result = controller.run_worker_agent(run.id)
        assert settled.status.value == "failed"
        assert result.status == "failed"
    else:
        with pytest.raises((ValueError, AgentInvocationError)):
            controller.run_worker_agent(run.id)

    assert controller.store.list_tasks(run.id)[0].state.value == "failed"
    expected_binding_status = "settled" if adapter is _TraversalArtifactAdapter else "discarded"
    assert controller.store.list_worker_bindings(run.id)[0].status == expected_binding_status
    kinds = {item["kind"] for item in controller.store.list_artifacts(run.id)}
    assert "runtime" not in kinds


def test_worker_delegate_discards_promoted_output_when_cancel_wins_delivery_race(
    tmp_path: Path, monkeypatch
):
    controller = _controller(tmp_path, _StructuredArtifactAdapter())
    output_spec = OutputSpec("output/value.txt", "text")
    monkeypatch.setattr(controller, "_task_output_specs", lambda run, task: (output_spec,))
    run = controller.create("cancel after output promotion")
    original_complete = controller.store.complete_worker_binding

    def cancel_before_commit(**kwargs):
        assert controller.cancel(run.id)
        return original_complete(**kwargs)

    monkeypatch.setattr(controller.store, "complete_worker_binding", cancel_before_commit)
    with pytest.raises(AgentInvocationError, match="binding is no longer active"):
        controller.run_worker_agent(run.id)

    assert not (run.workspace / "output" / "value.txt").exists()
    assert not any(item["kind"] == "output" for item in controller.store.list_artifacts(run.id))
