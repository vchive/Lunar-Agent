import time
from dataclasses import replace
from pathlib import Path

import pytest

from famou.budget import BudgetExceeded, BudgetSpec
from famou.config import Config
from famou.controller import LocalController
from famou.policy import PlanDocument, PlanTask
from famou.routing import RouteDecision
from famou.runtime import MockRuntime, RuntimeResult


class CapturingRuntime:
    name = "capturing-runtime"

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.timeouts: list[float | None] = []

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        del prompt
        self.timeouts.append(timeout)
        if self.delay:
            time.sleep(self.delay)
        workspace.mkdir(parents=True, exist_ok=True)
        return RuntimeResult("done")

    def cancel(self) -> None:
        return None

    def process_info(self) -> tuple[int | None, int | None]:
        return (None, None)

    def set_process_observer(self, observer) -> None:
        del observer


def _route_with_budget(controller: LocalController, budget: BudgetSpec) -> RouteDecision:
    return replace(controller.router.route("write a report"), budget=budget)


def test_run_agent_clips_explicit_timeout_to_remaining_run_budget(tmp_path: Path) -> None:
    runtime = MockRuntime()
    controller = LocalController(Config(tmp_path / ".famou"), runtime)
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
    controller = LocalController(Config(tmp_path / ".famou"), MockRuntime())
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
        from famou.agents import AgentResult

        return AgentResult(self.name, request.role, "done")

    def cancel(self) -> None:
        return None

    def process_info(self) -> tuple[int | None, int | None]:
        return (None, None)

    def set_process_observer(self, observer) -> None:
        del observer


def test_resume_workers_share_one_wall_clock_budget(tmp_path: Path) -> None:
    runtime = CapturingRuntime(delay=0.05)
    controller = LocalController(Config(tmp_path / ".famou", runtime_timeout=10), runtime)
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
        Config(tmp_path / ".famou", runtime_timeout=10),
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
    controller = LocalController(Config(tmp_path / ".famou", runtime_timeout=10), runtime)
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
