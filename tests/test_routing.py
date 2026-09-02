import sqlite3
from pathlib import Path

import pytest

from famou.agent_loop import AgentLoopRuntime
from famou.budget import BudgetSpec
from famou.config import Config
from famou.controller import LocalController
from famou.evaluator import Evaluation, NonEmptyEvaluator
from famou.policy import PlanDocument, PlanTask
from famou.profiles import EvaluatorProfile, ProfileRegistry
from famou.routing import DomainRouter
from famou.runtime import MockRuntime, ModelTurn, ToolCall


def test_deterministic_domain_router_classifies_english_and_chinese_goals() -> None:
    router = DomainRouter()
    assert router.route("Analyze a CSV and calculate aggregates").domain == "data"
    assert router.route("修复代码并运行测试").domain == "coding"
    assert router.route("Research papers and cite sources").domain == "research"
    general = router.route("What is SQLite WAL?")
    assert general.domain == "general"
    assert general.evidence == ("fallback:general",)


def test_routed_run_persists_status_metadata_and_uses_injected_evaluator(tmp_path: Path) -> None:
    class RejectingEvaluator:
        def evaluate(self, result: str, workspace: Path) -> Evaluation:
            del result, workspace
            return Evaluation(False, (), "fixture profile rejected result")

    profiles = ProfileRegistry(evaluators=(EvaluatorProfile("coding", "fixture", RejectingEvaluator),))
    controller = LocalController(Config(tmp_path / ".famou", max_retries=1), MockRuntime(), profiles=profiles)
    run = controller.start("fix this code bug and run tests")

    assert run.status.value == "failed"
    restored = controller.store.get_run(run.id)
    assert restored is not None
    assert restored.route_domain == "coding"
    assert restored.solver_profile == "coding"
    assert restored.evaluator_profile == "coding"
    assert any(event["type"] == "route_selected" for event in controller.store.list_events(run.id))
    assert any(event["type"] == "task_evaluated" and not event["payload"]["passed"] for event in controller.store.list_events(run.id))


def test_missing_route_profile_is_rejected_before_a_run_is_created(tmp_path: Path) -> None:
    profiles = ProfileRegistry(evaluators=(EvaluatorProfile("general", "only general", NonEmptyEvaluator),))
    controller = LocalController(Config(tmp_path / ".famou"), MockRuntime(), profiles=profiles)

    with pytest.raises(ValueError, match="unknown evaluator profile: coding"):
        controller.create("fix this code bug")

    with sqlite3.connect(controller.config.database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_plan_budget_fails_closed_before_claiming_work(tmp_path: Path) -> None:
    controller = LocalController(Config(tmp_path / ".famou"), MockRuntime())
    document = PlanDocument(
        goal="write a report",
        plan_id="budget-tasks",
        tasks=(PlanTask("one", "One", "one"), PlanTask("two", "Two", "two")),
        budget=BudgetSpec(max_tasks=1),
    )
    run = controller.start_plan(document)

    assert run.status.value == "failed"
    events = controller.store.list_events(run.id)
    assert any(event["type"] == "budget_exceeded" and event["payload"]["limit"] == "max_tasks" for event in events)
    assert all(task.attempts == 0 for task in controller.store.list_tasks(run.id))


class _ToolFixture:
    name = "fixture"

    def __init__(self) -> None:
        self.turns = [
            ModelTurn("", (ToolCall("1", "write_file", {"path": "a.txt", "content": "a"}), ToolCall("2", "write_file", {"path": "b.txt", "content": "b"}))),
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


def test_tool_step_budget_is_auditable_and_prevents_delivery(tmp_path: Path) -> None:
    runtime = AgentLoopRuntime(_ToolFixture(), max_steps=3)
    controller = LocalController(Config(tmp_path / ".famou"), runtime)
    document = PlanDocument(
        goal="fix code",
        plan_id="budget-tools",
        tasks=(PlanTask("one", "One", "write files"),),
        budget=BudgetSpec(max_tool_steps=1),
    )
    run = controller.start_plan(document)

    assert run.status.value == "failed"
    assert any(event["type"] == "budget_exceeded" and event["payload"]["limit"] == "max_tool_steps" for event in controller.store.list_events(run.id))
    try:
        controller.deliver(run.id)
    except ValueError as error:
        assert "verified" in str(error)
    else:  # pragma: no cover - the assertion above should always raise
        raise AssertionError("delivery must reject a budget-failed run")
