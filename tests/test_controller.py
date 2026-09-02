import time
from pathlib import Path
from threading import Event, Lock, Thread
from typing import ClassVar

from famou.agent_loop import AgentLoopRuntime
from famou.agents import AgentInvocationError, AgentRegistry, AgentResult
from famou.config import Config
from famou.controller import LocalController
from famou.memory import MemoryStore
from famou.runtime import MockRuntime, ModelTurn, RuntimeResult, ToolCall
from famou.tools import LocalToolRegistry


class DelegatingFixtureAdapter:
    name = "fixture-agent"
    roles = frozenset({"solver"})
    capabilities = frozenset({"read_files", "write_artifacts"})

    def __init__(self, text: str = "delegated result") -> None:
        self.text = text
        self.requests = []
        self.observer = None

    def run(self, request):
        self.requests.append(request)
        request.workspace.mkdir(parents=True, exist_ok=True)
        (request.workspace / "worker.txt").write_text("worker evidence", encoding="utf-8")
        return AgentResult(
            adapter_name=self.name,
            role=request.role,
            text=self.text,
            artifacts=("worker.txt",),
            metadata={"fixture": "yes"},
        )

    def cancel(self):
        return None

    def process_info(self):
        return (None, None)

    def set_process_observer(self, observer):
        self.observer = observer


class FailingDelegatingAdapter(DelegatingFixtureAdapter):
    name = "failing-agent"

    def run(self, request):
        del request
        raise AgentInvocationError("fixture failed")


class FixtureModel:
    name = "fixture"

    def __init__(self) -> None:
        self.turns = [
            ModelTurn("", (ToolCall("1", "write_file", {"path": "output.txt", "content": "ok"}),)),
            ModelTurn("done", ()),
        ]

    def complete(self, messages, tools=(), timeout=None):
        del messages, tools, timeout
        return self.turns.pop(0)

    def cancel(self) -> None:
        return None

    def process_info(self) -> tuple[int | None, int | None]:
        return (None, None)

    def set_process_observer(self, observer) -> None:
        del observer


def test_controller_delegates_with_durable_agent_events_and_artifacts(tmp_path: Path) -> None:
    config = Config(tmp_path / ".famou")
    adapter = DelegatingFixtureAdapter()
    controller = LocalController(
        config,
        MockRuntime(),
        agent_registry=AgentRegistry([adapter]),
    )
    run = controller.create("write a report")
    settled, result = controller.run_agent(run.id, role="solver")

    assert settled.status.value == "succeeded"
    assert result.adapter_name == "fixture-agent"
    assert len(adapter.requests) == 1
    request = adapter.requests[0]
    assert request.run_id == run.id
    assert request.task_id == controller.store.list_tasks(run.id)[0].id
    assert request.workspace.is_dir()
    artifacts = controller.store.list_artifacts(run.id)
    assert any(item["kind"] == "runtime" and item["path"].endswith("worker.txt") for item in artifacts)
    event_types = [event["type"] for event in controller.store.list_events(run.id)]
    assert "agent_selected" in event_types
    assert "agent_started" in event_types
    assert "agent_finished" in event_types
    assert "task_evaluated" in event_types


def test_controller_default_runtime_is_available_through_agent_boundary(tmp_path: Path) -> None:
    controller = LocalController(Config(tmp_path / ".famou"), MockRuntime())
    run = controller.create("answer locally")
    settled, result = controller.run_agent(run.id)
    assert settled.status.value == "succeeded"
    assert result.adapter_name == "mock"


def test_controller_fails_closed_when_agent_invocation_fails(tmp_path: Path) -> None:
    config = Config(tmp_path / ".famou", max_retries=1)
    adapter = FailingDelegatingAdapter()
    controller = LocalController(config, MockRuntime(), agent_registry=AgentRegistry([adapter]))
    run = controller.create("delegate a report")
    try:
        controller.run_agent(run.id)
    except AgentInvocationError as exc:
        assert "fixture failed" in str(exc)
    else:  # pragma: no cover - assertion keeps the failure explicit
        raise AssertionError("expected AgentInvocationError")
    failed = controller.store.get_run(run.id)
    assert failed is not None
    assert failed.status.value == "failed"
    assert any(event["type"] == "agent_failed" for event in controller.store.list_events(run.id))


def test_controller_completes_mock_run_and_is_idempotent(tmp_path: Path) -> None:
    config = Config(tmp_path / ".famou")
    controller = LocalController(config, MockRuntime())
    run = controller.start("produce a local report")
    assert run.status.value == "succeeded"
    artifacts = controller.store.list_artifacts(run.id)
    assert len(artifacts) == 2  # prompt and result are independently inspectable
    assert all((run.workspace / item["path"]).is_file() for item in artifacts)

    resumed = controller.resume(run.id)
    assert resumed.status == run.status
    assert len(controller.store.list_artifacts(run.id)) == 2
    assert sum(event["type"] == "run_succeeded" for event in controller.store.list_events(run.id)) == 1


def test_controller_recovers_a_claimed_task(tmp_path: Path) -> None:
    config = Config(tmp_path / ".famou")
    controller = LocalController(config, MockRuntime())
    run = controller.store.create_run("recover me")
    task = controller.store.next_task(run.id)
    assert task is not None
    assert controller.store.claim_task(task.id, "mock") is not None
    resumed = controller.resume(run.id)
    assert resumed.status.value == "succeeded"


def test_controller_wires_hermes_loop_events_and_artifacts(tmp_path: Path) -> None:
    config = Config(tmp_path / ".famou")
    memory = MemoryStore(config.database)
    runtime = AgentLoopRuntime(
        FixtureModel(),
        tools=LocalToolRegistry(),
        max_steps=3,
    )
    controller = LocalController(config, runtime, memory=memory)
    run = controller.start("write a file")

    assert run.status.value == "succeeded"
    artifacts = controller.store.list_artifacts(run.id)
    assert any(item["path"].endswith("output.txt") for item in artifacts)
    event_types = [item["type"] for item in controller.store.list_events(run.id)]
    assert "agent_model_turn" in event_types
    assert "agent_tool_result" in event_types


class ParallelFixtureRuntime:
    """Runtime fixture that proves task overlap and receives isolated callbacks."""

    name = "parallel-fixture"
    started = Event()
    release = Event()
    lock = Lock()
    active = 0
    max_active = 0
    contexts: ClassVar[list[str]] = []
    cancellations = 0

    @classmethod
    def reset(cls) -> None:
        cls.started = Event()
        cls.release = Event()
        cls.lock = Lock()
        cls.active = 0
        cls.max_active = 0
        cls.contexts = []
        cls.cancellations = 0

    def __init__(self) -> None:
        self.task_id = ""
        self.cancelled = Event()

    def set_context(self, run_id: str, task_id: str, goal: str | None = None) -> None:
        del run_id, goal
        self.task_id = task_id
        with self.lock:
            self.contexts.append(task_id)

    def set_event_sink(self, sink) -> None:
        del sink

    def set_process_observer(self, observer) -> None:
        del observer

    def set_session_path(self, path) -> None:
        del path

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        del prompt, workspace, timeout
        with self.lock:
            type(self).active += 1
            type(self).max_active = max(type(self).max_active, type(self).active)
            type(self).started.set()
        try:
            while not self.release.is_set() and not self.cancelled.is_set():
                time.sleep(0.005)
            return RuntimeResult("parallel result")
        finally:
            with self.lock:
                type(self).active -= 1

    def cancel(self) -> None:
        type(self).cancellations += 1
        self.cancelled.set()

    def process_info(self) -> tuple[int | None, int | None]:
        return (None, None)


def test_controller_runs_independent_tasks_in_isolated_workers(tmp_path: Path) -> None:
    ParallelFixtureRuntime.reset()
    controller = LocalController(
        Config(tmp_path / ".famou"),
        ParallelFixtureRuntime(),
        runtime_factory=ParallelFixtureRuntime,
        max_workers=2,
    )
    result: list[object] = []
    thread = Thread(
        target=lambda: result.append(
            controller.start(
                "parallel",
                [{"id": "one", "prompt": "one"}, {"id": "two", "prompt": "two"}],
            )
        )
    )
    thread.start()
    assert ParallelFixtureRuntime.started.wait(2)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and ParallelFixtureRuntime.max_active < 2:
        time.sleep(0.005)
    assert ParallelFixtureRuntime.max_active == 2
    ParallelFixtureRuntime.release.set()
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert result[0].status.value == "succeeded"
    assert set(ParallelFixtureRuntime.contexts) == {"one", "two"}


def test_controller_parallel_workers_preserve_dependency_order(tmp_path: Path) -> None:
    ParallelFixtureRuntime.reset()
    ParallelFixtureRuntime.release.set()
    controller = LocalController(
        Config(tmp_path / ".famou"),
        ParallelFixtureRuntime(),
        runtime_factory=ParallelFixtureRuntime,
        max_workers=2,
    )
    run = controller.start(
        "dependency",
        [
            {"id": "one", "prompt": "one"},
            {"id": "two", "prompt": "two"},
            {"id": "three", "prompt": "three", "depends_on": ["one", "two"]},
        ],
    )
    assert run.status.value == "succeeded"
    events = controller.store.list_events(run.id)
    positions = {event["type"] + ":" + str(event["task_id"]): index for index, event in enumerate(events)}
    assert positions["task_claimed:three"] > positions["task_succeeded:one"]
    assert positions["task_claimed:three"] > positions["task_succeeded:two"]


def test_parallel_workers_require_a_runtime_factory(tmp_path: Path) -> None:
    try:
        LocalController(Config(tmp_path / ".famou"), MockRuntime(), max_workers=2)
    except ValueError as exc:
        assert "runtime_factory" in str(exc)
    else:
        raise AssertionError("parallel controller accepted a shared runtime")


def test_controller_cancel_fans_out_to_active_workers(tmp_path: Path) -> None:
    ParallelFixtureRuntime.reset()
    controller = LocalController(
        Config(tmp_path / ".famou"),
        ParallelFixtureRuntime(),
        runtime_factory=ParallelFixtureRuntime,
        max_workers=2,
    )
    result: list[object] = []
    run = controller.create(
        "cancel",
        [{"id": "one", "prompt": "one"}, {"id": "two", "prompt": "two"}],
    )
    thread = Thread(target=lambda: result.append(controller.resume(run.id)))
    thread.start()
    assert ParallelFixtureRuntime.started.wait(2)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and ParallelFixtureRuntime.max_active < 2:
        time.sleep(0.005)
    assert controller.cancel(run.id)
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert result[0].status.value == "cancelled"
    assert ParallelFixtureRuntime.cancellations == 2
