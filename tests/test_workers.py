import threading
import time
from pathlib import Path

import pytest

from lunar_evolution.agents import AgentRegistry, AgentResult
from lunar_evolution.models import WorkerOutcome, WorkerPhase, WorkerStopReason
from lunar_evolution.store import Store
from lunar_evolution.workers import WorkerService


class FixtureAdapter:
    name = "fixture"
    roles = frozenset({"worker"})
    capabilities = frozenset()

    def __init__(self, delay: float = 0.0, text: str = "done") -> None:
        self.delay = delay
        self.text = text
        self.cancelled = threading.Event()

    def run(self, request):
        if self.delay:
            time.sleep(self.delay)
        return AgentResult(adapter_name=self.name, role=request.role, text=self.text)

    def cancel(self) -> None:
        self.cancelled.set()

    def process_info(self):
        return (None, None)

    def set_process_observer(self, observer):
        del observer


class TimeoutAdapter(FixtureAdapter):
    def run(self, request):
        del request
        raise TimeoutError("provider details must not be persisted")


def registry(adapter):
    result = AgentRegistry()
    result.register(adapter, execution_factory=lambda: type(adapter)(adapter.delay, adapter.text))
    return result


def test_worker_store_enforces_owner_depth_and_idempotent_settlement(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    root = store.create_worker("owner-a", "worker", "root", max_depth=1)
    child = store.create_worker("owner-a", "worker", "child", parent_worker_id=root.id, max_depth=1)
    assert child.depth == 1
    with pytest.raises(PermissionError):
        store.create_worker("owner-b", "worker", "bad", parent_worker_id=root.id, max_depth=1)
    with pytest.raises(PermissionError):
        store.start_worker_attempt(root.id, "owner-b", "secret")
    attempt = store.start_worker_attempt(root.id, "owner-a", "work")
    settled = store.settle_worker(root.id, attempt.id, WorkerOutcome.SUCCESS, result="ok")
    assert settled is not None and settled.phase is WorkerPhase.IDLE
    again = store.settle_worker(root.id, attempt.id, WorkerOutcome.FAILURE, result="late")
    assert again is not None and again.outcome is WorkerOutcome.SUCCESS
    assert len(store.list_worker_events(root.id)) == 3


def test_worker_service_dispatch_send_wait_resume_and_cancel(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    adapter = FixtureAdapter(delay=0.05)
    service = WorkerService(store, registry(adapter), tmp_path / "sessions")
    worker = service.dispatch("owner", prompt="first", role="worker")
    service.send("owner", worker.id, "follow up")
    assert service.wait("owner", worker.id, timeout=2).outcome is WorkerOutcome.SUCCESS
    resumed = service.resume("owner", worker.id)
    assert service.wait("owner", resumed.id, timeout=2).outcome is WorkerOutcome.SUCCESS
    assert len(store.list_worker_attempts(worker.id)) == 2
    assert any(event["type"] == "worker_result_delivered" for event in store.list_worker_events(worker.id))
    assert service.list("other") == []
    service.close()


def test_worker_send_requires_running_and_timeout_is_not_failure(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    service = WorkerService(store, registry(FixtureAdapter(delay=0.2)), tmp_path / "sessions")
    worker = store.create_worker("owner", "worker", "idle")
    with pytest.raises(ValueError, match="not running"):
        service.send("owner", worker.id, "late")
    running = service.dispatch("owner", prompt="slow")
    observed = service.wait("owner", running.id, timeout=0.001)
    assert observed.phase is WorkerPhase.RUNNING
    assert observed.outcome is None
    assert service.wait("owner", running.id, timeout=2).outcome is WorkerOutcome.SUCCESS
    service.close()


def test_parent_cancel_cascades_without_touching_unrelated_worker(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    service = WorkerService(
        store,
        registry(FixtureAdapter(delay=0.15)),
        tmp_path / "sessions",
        max_depth=1,
    )
    parent = service.dispatch("owner", prompt="parent")
    child = service.dispatch("owner", prompt="child", parent_worker_id=parent.id)
    unrelated = service.dispatch("owner", prompt="unrelated")
    assert service.cancel("owner", parent.id).stop_reason.value == "cancelled"
    assert store.get_worker(child.id).stop_reason.value == "parent_cancelled"
    assert service.wait("owner", parent.id).outcome is WorkerOutcome.STOPPED
    assert service.wait("owner", child.id).outcome is WorkerOutcome.STOPPED
    assert service.wait("owner", unrelated.id, timeout=2).outcome is WorkerOutcome.SUCCESS
    service.cancel("owner", parent.id)
    assert len([event for event in store.list_worker_events(parent.id) if event["type"] == "worker_cancelled"]) == 1
    service.close()


def test_recursive_parent_cancel_reaches_grandchild(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    service = WorkerService(
        store,
        registry(FixtureAdapter(delay=0.25)),
        tmp_path / "sessions",
        max_depth=2,
        max_workers=4,
    )
    root = service.dispatch("owner", prompt="root")
    child = service.dispatch("owner", prompt="child", parent_worker_id=root.id)
    grandchild = service.dispatch("owner", prompt="grandchild", parent_worker_id=child.id)
    unrelated = service.dispatch("owner", prompt="unrelated")
    stopped = service.cancel("owner", root.id)
    assert stopped.stop_reason is WorkerStopReason.CANCELLED
    assert service.wait("owner", root.id, timeout=2).outcome is WorkerOutcome.STOPPED
    assert service.wait("owner", child.id, timeout=2).stop_reason is WorkerStopReason.PARENT_CANCELLED
    assert service.wait("owner", grandchild.id, timeout=2).stop_reason is WorkerStopReason.PARENT_CANCELLED
    assert service.wait("owner", unrelated.id, timeout=2).outcome is WorkerOutcome.SUCCESS
    service.close()


def test_worker_reconcile_preserves_legacy_unknown_owner(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    worker = store.create_worker("owner", "worker", "restart")
    attempt = store.start_worker_attempt(worker.id, "owner", "work")
    service = WorkerService(store, registry(FixtureAdapter()), tmp_path / "sessions")
    recovered = store.get_worker(worker.id)
    assert recovered is not None
    assert service.reconcile("owner") == 0
    assert recovered.phase is WorkerPhase.RUNNING
    assert recovered.outcome is None
    assert recovered.stop_reason is None
    assert store.list_worker_attempts(worker.id)[0].id == attempt.id
    service.close()


def test_large_worker_result_is_bounded_and_referenced(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    text = "x" * (64 * 1024 + 100)
    service = WorkerService(store, registry(FixtureAdapter(text=text)), tmp_path / "sessions")
    worker = service.dispatch("owner", prompt="large")
    result = service.wait("owner", worker.id, timeout=2)
    assert result.result_ref is not None
    assert len((result.result or "").encode("utf-8")) <= 64 * 1024
    result_path = tmp_path / "sessions" / "workers" / worker.id / store.list_worker_attempts(worker.id)[0].id / "result.txt"
    assert result_path.read_text(encoding="utf-8") == text
    assert service.read_result("owner", worker.id) == text
    result_path.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="integrity"):
        service.read_result("owner", worker.id)
    service.close()


def test_worker_cancel_preserves_stopped_against_late_result(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    adapter = FixtureAdapter(delay=0.2)
    service = WorkerService(store, registry(adapter), tmp_path / "sessions")
    worker = service.dispatch("owner", prompt="slow", role="worker")
    stopped = service.cancel("owner", worker.id)
    assert stopped.outcome is WorkerOutcome.STOPPED
    time.sleep(0.3)
    assert service.wait("owner", worker.id).outcome is WorkerOutcome.STOPPED
    service.close()


def test_cancel_wakes_a_waiter_without_waiting_for_timeout(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    service = WorkerService(store, registry(FixtureAdapter(delay=1)), tmp_path / "sessions")
    worker = service.dispatch("owner", prompt="slow")
    observed: list[WorkerOutcome | None] = []

    def waiter() -> None:
        observed.append(service.wait("owner", worker.id, timeout=5).outcome)

    thread = threading.Thread(target=waiter)
    thread.start()
    time.sleep(0.02)
    service.cancel("owner", worker.id)
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert observed == [WorkerOutcome.STOPPED]
    service.close()


def test_worker_timeout_is_typed_and_events_are_redacted(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    service = WorkerService(store, registry(TimeoutAdapter()), tmp_path / "sessions")
    worker = service.dispatch("owner", prompt="secret prompt")
    settled = service.wait("owner", worker.id, timeout=2)
    assert settled.outcome is WorkerOutcome.FAILURE
    assert settled.stop_reason.value == "timeout"
    events = store.list_worker_events(worker.id)
    serialized = str(events)
    assert "secret prompt" not in serialized
    assert "provider details" not in serialized
    assert all("traceback" not in str(event["payload"]).lower() for event in events)
    service.close()
