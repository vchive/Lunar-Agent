from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from lunar_evolution.agent_loop import AgentLoopRuntime
from lunar_evolution.agents import AgentRegistry, AgentResult, RuntimeAgentAdapter
from lunar_evolution.runtime import ModelTurn, ToolCall
from lunar_evolution.store import Store
from lunar_evolution.tools import LocalToolRegistry
from lunar_evolution.workers import WorkerService


class _Adapter:
    name = "fixture"
    roles = frozenset({"worker"})
    capabilities = frozenset()

    def __init__(self, delay: float = 0.0, text: str = "child complete") -> None:
        self.delay = delay
        self.text = text
        self.cancelled = threading.Event()

    def run(self, request):
        if self.delay:
            time.sleep(self.delay)
        if self.cancelled.is_set():
            return AgentResult(
                self.name, request.role, "", status="cancelled", error="cancelled",
            )
        return AgentResult(self.name, request.role, self.text)

    def cancel(self) -> None:
        self.cancelled.set()

    def process_info(self) -> tuple[int | None, int | None]:
        return None, None

    def set_process_observer(self, observer) -> None:
        del observer


def _registry(adapter: _Adapter) -> AgentRegistry:
    registry = AgentRegistry()
    registry.register(
        adapter,
        execution_factory=lambda: _Adapter(adapter.delay, adapter.text),
    )
    return registry


def test_worker_tools_are_opt_in_and_return_bounded_result(tmp_path: Path) -> None:
    plain = LocalToolRegistry()
    assert all("worker" not in item["function"]["name"] for item in plain.schemas())
    unavailable = plain.execute("spawn_worker", {"prompt": "x"}, tmp_path)
    assert not unavailable.success

    store = Store(tmp_path / "state.db")
    store.initialize()
    service = WorkerService(
        store, _registry(_Adapter(delay=0.2)), tmp_path / "sessions", max_depth=1,
    )
    parent = service.dispatch("owner", prompt="parent", role="worker")
    tools = LocalToolRegistry(max_output_bytes=64)
    tools.set_worker_context(service, "owner", parent.id)
    names = {item["function"]["name"] for item in tools.schemas()}
    assert {"spawn_worker", "wait_worker", "cancel_worker", "read_worker_result"} <= names

    spawned = tools.execute("spawn_worker", {"prompt": "child"}, tmp_path)
    assert spawned.success
    child_id = json.loads(spawned.output)["worker_id"]
    waited = tools.execute("wait_worker", {"worker_id": child_id, "timeout": 2}, tmp_path)
    assert waited.success
    waited_payload = json.loads(waited.output)
    assert waited_payload["phase"] == "idle"
    assert waited_payload["outcome"] == "success"
    child = store.get_worker(child_id)
    assert child is not None and child.parent_worker_id == parent.id and child.depth == 1
    result = tools.execute("read_worker_result", {"worker_id": child_id}, tmp_path)
    assert result.success
    assert json.loads(result.output)["text"] == "child complete"
    service.close()


def test_worker_wait_checks_parent_continuation_guard(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    service = WorkerService(
        store, _registry(_Adapter(delay=0.5)), tmp_path / "sessions", max_depth=1,
    )
    parent = service.dispatch("owner", prompt="parent", role="worker")
    tools = LocalToolRegistry()
    tools.set_worker_context(service, "owner", parent.id)
    child = json.loads(tools.execute("spawn_worker", {"prompt": "slow"}, tmp_path).output)
    checks = 0

    def guard() -> None:
        nonlocal checks
        checks += 1
        if checks >= 2:
            raise RuntimeError("parent stopped")

    tools.set_continuation_guard(guard)
    waited = tools.execute("wait_worker", {"worker_id": child["worker_id"], "timeout": 5}, tmp_path)
    assert not waited.success and "RuntimeError" in waited.output
    service.cancel("owner", child["worker_id"])
    service.close()


class _DynamicModel:
    name = "dynamic"

    def __init__(self, spawn: bool) -> None:
        self.spawn = spawn
        self.turns = 0

    def complete(self, messages, tools=(), timeout=None):
        del tools, timeout
        self.turns += 1
        if self.spawn and self.turns == 1:
            return ModelTurn("", (ToolCall("spawn", "spawn_worker", {"prompt": "child"}),))
        if self.spawn and self.turns == 2:
            payload = json.loads(messages[-1]["content"])
            return ModelTurn(
                "", (ToolCall("wait", "wait_worker", {"worker_id": payload["worker_id"], "timeout": 2}),)
            )
        if self.spawn:
            return ModelTurn("parent observed child")
        return ModelTurn("child response")

    def cancel(self) -> None:
        return None

    def process_info(self) -> tuple[int | None, int | None]:
        return None, None

    def set_process_observer(self, observer) -> None:
        del observer


class _RecursiveModel:
    name = "recursive"

    def __init__(self, level: int) -> None:
        self.level = level
        self.turns = 0

    def complete(self, messages, tools=(), timeout=None):
        del tools, timeout
        self.turns += 1
        if self.level < 2 and self.turns == 1:
            return ModelTurn(
                "", (ToolCall("spawn", "spawn_worker", {"prompt": f"level {self.level + 1}"}),)
            )
        if self.level < 2 and self.turns == 2:
            payload = json.loads(messages[-1]["content"])
            return ModelTurn(
                "", (ToolCall("wait", "wait_worker", {"worker_id": payload["worker_id"], "timeout": 2}),)
            )
        return ModelTurn(f"level {self.level} complete")

    def cancel(self) -> None:
        return None

    def process_info(self) -> tuple[int | None, int | None]:
        return None, None

    def set_process_observer(self, observer) -> None:
        del observer


def test_worker_service_injects_context_into_agent_loop(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    created = 0

    def factory():
        nonlocal created
        created += 1
        runtime = AgentLoopRuntime(
            _DynamicModel(spawn=created == 1), tools=LocalToolRegistry(), max_steps=6,
        )
        return RuntimeAgentAdapter(runtime, runtime_factory=None)

    prototype = RuntimeAgentAdapter(
        AgentLoopRuntime(_DynamicModel(spawn=False), tools=LocalToolRegistry(), max_steps=6),
        runtime_factory=factory,
    )
    registry = AgentRegistry()
    registry.register(prototype, execution_factory=factory)
    service = WorkerService(store, registry, tmp_path / "sessions", max_depth=1, max_workers=2)
    worker = service.dispatch("owner", prompt="parent", role="worker", timeout=5)
    settled = service.wait("owner", worker.id, timeout=5)
    assert settled.outcome.value == "success"
    result = service.read_result_envelope("owner", worker.id)
    assert result.text == "parent observed child"
    children = store.list_workers("owner")
    child = next(item for item in children if item.parent_worker_id == worker.id)
    assert child.outcome.value == "success"
    service.close()


def test_recursive_agent_loop_reaches_grandchild_and_keeps_results_private(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    created = 0

    def factory():
        nonlocal created
        level = created
        created += 1
        runtime = AgentLoopRuntime(
            _RecursiveModel(level), tools=LocalToolRegistry(), max_steps=8,
        )
        return RuntimeAgentAdapter(runtime, runtime_factory=None)

    prototype = RuntimeAgentAdapter(
        AgentLoopRuntime(_RecursiveModel(2), tools=LocalToolRegistry(), max_steps=8),
        runtime_factory=factory,
    )
    registry = AgentRegistry()
    registry.register(prototype, execution_factory=factory)
    service = WorkerService(
        store, registry, tmp_path / "sessions", max_depth=2, max_workers=3,
    )
    root = service.dispatch("owner", prompt="level 0", role="worker", timeout=5)
    assert service.wait("owner", root.id, timeout=5).outcome.value == "success"
    workers = store.list_workers("owner")
    child = next(item for item in workers if item.parent_worker_id == root.id)
    grandchild = next(item for item in workers if item.parent_worker_id == child.id)
    assert (root.depth, child.depth, grandchild.depth) == (0, 1, 2)
    assert service.read_result_envelope("owner", grandchild.id).text == "level 2 complete"

    root_tools = LocalToolRegistry()
    root_tools.set_worker_context(service, "owner", root.id)
    descendant = root_tools.execute("read_worker_result", {"worker_id": grandchild.id}, tmp_path)
    assert descendant.success
    assert json.loads(descendant.output)["text"] == "level 2 complete"

    child_tools = LocalToolRegistry()
    child_tools.set_worker_context(service, "owner", child.id)
    own_descendant = child_tools.execute(
        "read_worker_result", {"worker_id": grandchild.id}, tmp_path,
    )
    assert own_descendant.success
    ancestor = child_tools.execute("read_worker_result", {"worker_id": root.id}, tmp_path)
    assert not ancestor.success
    assert not (tmp_path / "sessions" / "workers" / root.id / "result.txt").exists()
    assert root_tools.execute("read_worker_result", {"worker_id": child.id}, tmp_path).success
    service.close()


def test_recursive_depth_and_capacity_are_explicitly_bounded(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    root = store.create_worker("owner", "worker", "root", max_depth=2)
    child = store.create_worker("owner", "worker", "child", parent_worker_id=root.id, max_depth=2)
    grandchild = store.create_worker(
        "owner", "worker", "grandchild", parent_worker_id=child.id, max_depth=2,
    )
    with pytest.raises(ValueError, match="maximum depth"):
        store.create_worker("owner", "worker", "too deep", parent_worker_id=grandchild.id, max_depth=2)
    with pytest.raises(ValueError, match="max_workers"):
        WorkerService(store, _registry(_Adapter()), tmp_path / "sessions", max_depth=2, max_workers=2)


def test_worker_tool_spawn_requires_a_running_parent(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    service = WorkerService(store, _registry(_Adapter()), tmp_path / "sessions", max_depth=2)
    parent = store.create_worker("owner", "worker", "idle", max_depth=2)
    tools = LocalToolRegistry()
    tools.set_worker_context(service, "owner", parent.id)
    result = tools.execute("spawn_worker", {"prompt": "late child"}, tmp_path)
    assert not result.success
    assert "parent worker is not running" in result.output
    assert store.list_worker_children(parent.id) == []
    service.close()


def test_worker_wait_is_clamped_by_agent_execution_deadline(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    service = WorkerService(
        store, _registry(_Adapter(delay=0.4)), tmp_path / "sessions", max_depth=1, max_workers=2,
    )
    parent = service.dispatch("owner", prompt="parent")
    tools = LocalToolRegistry()
    tools.set_worker_context(service, "owner", parent.id)
    child = json.loads(tools.execute("spawn_worker", {"prompt": "slow child"}, tmp_path).output)
    started = time.monotonic()
    with tools.execution_deadline(started + 0.05):
        observed = tools.execute(
            "wait_worker", {"worker_id": child["worker_id"], "timeout": 5}, tmp_path,
        )
    assert observed.success
    assert json.loads(observed.output)["phase"] == "running"
    assert time.monotonic() - started < 0.3
    service.cancel("owner", parent.id)
    service.close()
