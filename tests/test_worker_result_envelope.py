from __future__ import annotations

import json

import pytest

from lunar_evolution.agents import AgentRegistry, AgentResult
from lunar_evolution.store import Store
from lunar_evolution.workers import WorkerService


def _attempt(tmp_path):
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("durable worker result")
    worker = store.create_worker(run.id, "solver", "result", agent_type="fixture")
    attempt = store.start_worker_attempt(worker.id, run.id, "return result", service_owner_id="svc")
    return store, worker, attempt


def test_worker_result_envelope_round_trips_full_agent_result(tmp_path):
    store, worker, attempt = _attempt(tmp_path)
    result = AgentResult(
        adapter_name="fixture", role="solver", text="answer", artifacts=("answer.txt",),
        metadata={"score": 0.5},
    )
    envelope = store.persist_worker_result(
        worker.id, attempt.id, result,
        artifact_manifest=({"path": "answer.txt", "size": 6, "sha256": "a" * 64},),
    )
    assert envelope.result.to_dict() == result.to_dict()
    assert envelope.size > 0
    assert len(envelope.sha256) == 64
    assert store.get_worker_result(worker.id, attempt.id, owner_id=worker.owner_id).result == result
    assert store.persist_worker_result(
        worker.id, attempt.id, result,
        artifact_manifest=({"path": "answer.txt", "size": 6, "sha256": "a" * 64},),
    ).sha256 == envelope.sha256


def test_worker_result_envelope_rejects_conflicting_or_tampered_payload(tmp_path):
    store, worker, attempt = _attempt(tmp_path)
    result = AgentResult(adapter_name="fixture", role="solver", text="answer")
    store.persist_worker_result(worker.id, attempt.id, result)
    with pytest.raises(ValueError, match="different content"):
        store.persist_worker_result(
            worker.id, attempt.id,
            AgentResult(adapter_name="fixture", role="solver", text="changed"),
        )
    with store._connect() as connection:
        connection.execute(
            "UPDATE worker_attempt_results SET payload = ? WHERE worker_attempt_id = ?",
            (json.dumps({"schema_version": "lunar-worker-result-v1"}), attempt.id),
        )
    with pytest.raises(ValueError, match="integrity"):
        store.get_worker_result(worker.id, attempt.id)


def test_worker_service_restores_persisted_result_envelope(tmp_path):
    class Adapter:
        name = "fixture"
        roles = frozenset({"worker"})
        capabilities = frozenset()

        def run(self, request):
            (request.workspace / "answer.txt").write_text("artifact", encoding="utf-8")
            return AgentResult(
                adapter_name=self.name, role=request.role, text="answer",
                artifacts=("answer.txt",), metadata={"attempt": 1},
            )

        def cancel(self):
            return None

        def process_info(self):
            return None, None

        def set_process_observer(self, observer):
            del observer

    store = Store(tmp_path / "state.db")
    store.initialize()
    registry = AgentRegistry()
    registry.register(Adapter(), execution_factory=Adapter)
    service = WorkerService(store, registry, tmp_path / "sessions")
    worker = service.dispatch("owner", role="worker", prompt="return an artifact")
    assert service.wait("owner", worker.id, timeout=2).outcome.value == "success"
    result = service.read_result_envelope("owner", worker.id)
    assert result.to_dict() == {
        "adapter_name": "fixture", "role": "worker", "status": "succeeded", "text": "answer",
        "artifacts": ["answer.txt"], "metadata": {"attempt": 1}, "error": None,
    }
    envelope = store.get_worker_result(worker.id, owner_id="owner")
    assert envelope is not None
    assert envelope.artifact_manifest[0]["sha256"]
    service.close()
