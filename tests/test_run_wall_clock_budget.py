import time
from dataclasses import replace
from pathlib import Path
from threading import Event, Lock, Thread

import pytest

import lunar_evolution.controller as controller_module
from lunar_evolution.budget import BudgetExceeded, BudgetSpec
from lunar_evolution.config import Config
from lunar_evolution.controller import LocalController
from lunar_evolution.policy import PlanDocument, PlanTask
from lunar_evolution.routing import RouteDecision
from lunar_evolution.runtime import MockRuntime, RuntimeResult


class CapturingRuntime:
    name = "capturing-runtime"

    def __init__(self, delay: float = 0.0, clock=None) -> None:
        self.delay = delay
        self.clock = clock
        self.timeouts: list[float | None] = []

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        del prompt
        self.timeouts.append(timeout)
        if self.delay:
            if self.clock is None:
                time.sleep(self.delay)
            else:
                self.clock.advance(self.delay)
        workspace.mkdir(parents=True, exist_ok=True)
        return RuntimeResult("done")

    def cancel(self) -> None:
        return None

    def process_info(self) -> tuple[int | None, int | None]:
        return (None, None)

    def set_process_observer(self, observer) -> None:
        del observer


class BlockingRuntime:
    name = "blocking-runtime"

    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()
        self.timeouts: list[float | None] = []
        self.cancel_calls = 0

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        del prompt, workspace
        self.timeouts.append(timeout)
        self.started.set()
        if not self.release.wait(timeout=2):
            raise TimeoutError("fixture runtime was not released")
        return RuntimeResult("late result")

    def cancel(self) -> None:
        self.cancel_calls += 1

    def process_info(self) -> tuple[int | None, int | None]:
        return (None, None)

    def set_process_observer(self, observer) -> None:
        del observer


class _ControllerClock:
    """Deterministic monotonic clock for budget ordering tests.

    Runtime fixtures still use the real clock for thread synchronization.  Only the
    controller's elapsed-budget observations are advanced by the test, so CI startup
    latency cannot decide which terminal state wins.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._now = 100.0

    def monotonic(self) -> float:
        with self._lock:
            return self._now

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._now += seconds

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)


def _route_with_budget(controller: LocalController, budget: BudgetSpec) -> RouteDecision:
    return replace(controller.router.route("write a report"), budget=budget)


def test_run_agent_clips_explicit_timeout_to_remaining_run_budget(tmp_path: Path) -> None:
    runtime = MockRuntime()
    controller = LocalController(Config(tmp_path / ".lunar-evolution"), runtime)
    adapter = _CapturingAdapter()
    controller.agent_registry = controller.agent_registry.__class__([adapter])
    run = controller.store.create_run(
        "write a report",
        route=_route_with_budget(controller, BudgetSpec(max_runtime_seconds=0.2)),
    )

    settled, _ = controller.run_agent(run.id, timeout=30)

    assert settled.status.value == "succeeded"
    assert 0 < adapter.timeout <= 0.2


def test_run_agent_does_not_claim_when_wall_budget_is_already_exhausted(tmp_path: Path) -> None:
    controller = LocalController(Config(tmp_path / ".lunar-evolution"), MockRuntime())
    adapter = _CapturingAdapter()
    controller.agent_registry = controller.agent_registry.__class__([adapter])
    run = controller.store.create_run(
        "write a report",
        route=_route_with_budget(controller, BudgetSpec(max_runtime_seconds=0.000001)),
    )

    with pytest.raises(BudgetExceeded, match="max_runtime_seconds"):
        controller.run_agent(run.id)

    assert adapter.timeout == 0
    task = controller.store.list_tasks(run.id)[0]
    assert task.attempts == 0
    assert any(
        event["type"] == "budget_exceeded"
        and event["payload"]["limit"] == "max_runtime_seconds"
        for event in controller.store.list_events(run.id)
    )


class _CapturingAdapter:
    name = "capturing-adapter"
    roles = frozenset({"solver"})
    capabilities = frozenset({"read_files", "write_artifacts"})

    def __init__(self) -> None:
        self.timeout = 0.0

    def run(self, request):
        self.timeout = request.timeout
        from lunar_evolution.agents import AgentResult

        return AgentResult(self.name, request.role, "done")

    def cancel(self) -> None:
        return None

    def process_info(self) -> tuple[int | None, int | None]:
        return (None, None)

    def set_process_observer(self, observer) -> None:
        del observer


def test_resume_workers_share_one_wall_clock_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = _ControllerClock()
    monkeypatch.setattr(controller_module, "time", clock)
    runtime = CapturingRuntime(delay=0.05, clock=clock)
    controller = LocalController(Config(tmp_path / ".lunar-evolution", runtime_timeout=10), runtime)
    plan = PlanDocument(
        goal="write two reports",
        plan_id="wall-clock",
        tasks=(PlanTask("one", "One", "one"), PlanTask("two", "Two", "two")),
        budget=BudgetSpec(max_runtime_seconds=0.25),
    )

    settled = controller.start_plan(plan)

    assert settled.status.value == "succeeded"
    assert len(runtime.timeouts) == 2
    assert all(timeout is not None and 0 < timeout <= 0.25 for timeout in runtime.timeouts)
    assert runtime.timeouts[1] < runtime.timeouts[0]


def test_concurrent_workers_use_one_shared_wall_clock_budget(tmp_path: Path) -> None:
    runtimes: list[CapturingRuntime] = []

    def factory() -> CapturingRuntime:
        runtime = CapturingRuntime(delay=0.05)
        runtimes.append(runtime)
        return runtime

    controller = LocalController(
        Config(tmp_path / ".lunar-evolution", runtime_timeout=10),
        CapturingRuntime(),
        runtime_factory=factory,
        max_workers=2,
    )
    plan = PlanDocument(
        goal="write two reports",
        plan_id="wall-clock-concurrent",
        tasks=(PlanTask("one", "One", "one"), PlanTask("two", "Two", "two")),
        budget=BudgetSpec(max_runtime_seconds=0.25),
    )

    settled = controller.start_plan(plan)

    assert settled.status.value == "succeeded"
    timeouts = [timeout for runtime in runtimes for timeout in runtime.timeouts]
    assert len(timeouts) == 2
    assert all(timeout is not None and 0 < timeout <= 0.25 for timeout in timeouts)


def test_exhausted_run_records_budget_before_claiming_next_task(tmp_path: Path) -> None:
    runtime = CapturingRuntime(delay=0.08)
    controller = LocalController(Config(tmp_path / ".lunar-evolution", runtime_timeout=10), runtime)
    plan = PlanDocument(
        goal="write two reports",
        plan_id="wall-clock-fail",
        tasks=(PlanTask("one", "One", "one"), PlanTask("two", "Two", "two")),
        budget=BudgetSpec(max_runtime_seconds=0.05),
    )

    settled = controller.start_plan(plan)

    assert settled.status.value == "failed"
    assert len(runtime.timeouts) == 1
    events = controller.store.list_events(settled.id)
    assert sum(event["type"] == "budget_exceeded" for event in events) == 1
    assert any(event["payload"]["limit"] == "max_runtime_seconds" for event in events if event["type"] == "budget_exceeded")


def test_cancellation_first_discards_result_returned_after_wall_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = _ControllerClock()
    monkeypatch.setattr(controller_module, "time", clock)
    runtime = BlockingRuntime()
    controller = LocalController(Config(tmp_path / ".lunar-evolution", runtime_timeout=10), runtime)
    run = controller.store.create_run(
        "cancel before the wall budget",
        route=_route_with_budget(controller, BudgetSpec(max_runtime_seconds=0.05)),
    )
    settled: list[object] = []
    worker = Thread(target=lambda: settled.append(controller.resume(run.id)))

    worker.start()
    assert runtime.started.wait(timeout=2)
    assert controller.cancel(run.id)
    assert runtime.cancel_calls == 1
    assert runtime.timeouts[0] is not None
    # Cancellation owns the terminal transition even after the controller clock crosses
    # the wall budget while the runtime is unwinding.
    clock.advance(0.10)
    runtime.release.set()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert settled[0].status.value == "cancelled"
    task = controller.store.list_tasks(run.id)[0]
    assert task.state.value == "cancelled"
    assert task.result_path is None
    events = controller.store.list_events(run.id)
    assert sum(event["type"] == "task_result_discarded" for event in events) == 1
    assert not any(event["type"] == "budget_exceeded" for event in events)
    assert not any(event["type"] in {"task_succeeded", "task_evaluated"} for event in events)
    assert not any(item["kind"] == "result" for item in controller.store.list_artifacts(run.id))


def test_budget_first_rejects_later_cancellation_without_rewriting_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = _ControllerClock()
    monkeypatch.setattr(controller_module, "time", clock)
    runtime = BlockingRuntime()
    controller = LocalController(Config(tmp_path / ".lunar-evolution", runtime_timeout=10), runtime)
    run = controller.store.create_run(
        "exhaust the wall budget before cancellation",
        route=_route_with_budget(controller, BudgetSpec(max_runtime_seconds=0.05)),
    )
    budget_recorded = Event()
    finish_budget_failure = Event()
    original_fail_budget = controller.store.fail_budget

    def pause_after_budget_is_recorded(
        run_id: str, limit: str, actual: float, maximum: float, reason: str
    ) -> bool:
        changed = original_fail_budget(run_id, limit, actual, maximum, reason)
        budget_recorded.set()
        assert finish_budget_failure.wait(timeout=2)
        return changed

    monkeypatch.setattr(controller.store, "fail_budget", pause_after_budget_is_recorded)
    settled: list[object] = []
    worker = Thread(target=lambda: settled.append(controller.resume(run.id)))

    worker.start()
    assert runtime.started.wait(timeout=2)
    assert runtime.timeouts[0] is not None
    # Advance only the controller's wall clock.  This deterministically crosses the
    # configured budget without waiting for process startup or scheduler timing.
    clock.advance(0.10)
    runtime.release.set()
    assert budget_recorded.wait(timeout=2)
    assert not controller.cancel(run.id)
    finish_budget_failure.set()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert settled[0].status.value == "failed"
    task = controller.store.list_tasks(run.id)[0]
    assert task.state.value == "blocked"
    assert task.result_path is None
    events = controller.store.list_events(run.id)
    assert sum(event["type"] == "budget_exceeded" for event in events) == 1
    assert not any(event["type"] in {"run_cancelled", "task_cancelled"} for event in events)
    assert not any(event["type"] in {"task_succeeded", "task_evaluated"} for event in events)
