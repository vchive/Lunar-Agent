import json
import threading
from pathlib import Path

import pytest

from famou.config import Config
from famou.controller import LocalController
from famou.evaluator import Evaluation
from famou.policy import PlanDocument, PlanPatch, PlanTask
from famou.runtime import MockRuntime, RuntimeResult
from famou.store import Store


class RecordingRuntime:
    name = "recording"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        del timeout
        self.prompts.append(prompt)
        workspace.mkdir(parents=True, exist_ok=True)
        return RuntimeResult(text=f"output for: {prompt}")

    def cancel(self) -> None:
        return None


def _document() -> PlanDocument:
    return PlanDocument(
        goal="prepare and verify a report",
        plan_id="plan-report",
        tasks=(
            PlanTask("research", "Research", "Collect facts"),
            PlanTask("write", "Write", "Draft report", ("research",)),
        ),
    )


class RejectingEvaluator:
    def evaluate(self, result: str, workspace: Path) -> Evaluation:
        del result, workspace
        return Evaluation(False, ("fixture rejected output",), "fixture rejection")


def test_plan_runs_in_dependency_order_and_handoffs_artifact(tmp_path: Path) -> None:
    config = Config(tmp_path / ".famou")
    runtime = RecordingRuntime()
    controller = LocalController(config, runtime)
    run = controller.start(
        "plan goal",
        [
            {"id": "first", "title": "First", "prompt": "make source"},
            {"id": "second", "title": "Second", "prompt": "use source", "depends_on": ["first"]},
        ],
    )
    assert run.status.value == "succeeded"
    assert len(runtime.prompts) == 2
    assert runtime.prompts[0] == "make source"
    assert "tasks/first/" in runtime.prompts[1]
    assert "output for: make source" in runtime.prompts[1]
    tasks = controller.store.list_tasks(run.id)
    assert [task.state.value for task in tasks] == ["succeeded", "succeeded"]
    assert tasks[1].dependencies == ("first",)


def test_rejected_plan_task_blocks_dependents_and_writes_audit(tmp_path: Path) -> None:
    config = Config(tmp_path / ".famou", max_retries=1)
    controller = LocalController(config, MockRuntime(), evaluator=RejectingEvaluator())
    run = controller.start(
        "reject goal",
        [
            {"id": "first", "prompt": "reject this"},
            {"id": "second", "prompt": "never run", "depends_on": ["first"]},
        ],
    )
    assert run.status.value == "failed"
    tasks = {task.id: task for task in controller.store.list_tasks(run.id)}
    assert tasks["first"].state.value == "failed"
    assert tasks["second"].state.value == "blocked"
    assert any(event["type"] == "task_blocked" for event in controller.store.list_events(run.id))
    evaluation_files = list(run.workspace.glob("tasks/first/*/evaluation.json"))
    assert len(evaluation_files) == 1
    assert json.loads(evaluation_files[0].read_text(encoding="utf-8"))["passed"] is False


def test_plan_acceptance_contains_is_applied_after_base_evaluator(tmp_path: Path) -> None:
    controller = LocalController(Config(tmp_path / ".famou"), MockRuntime())
    run = controller.start(
        "acceptance goal",
        [{"id": "check", "prompt": "make output", "acceptance": {"contains": "required"}}],
    )
    assert run.status.value == "failed"
    task = controller.store.list_tasks(run.id)[0]
    assert task.last_error is not None and "required" in task.last_error


def test_invalid_plan_is_rejected_before_run_insert(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    try:
        store.create_run(
            "bad plan",
            tasks=[
                {"id": "a", "prompt": "a", "depends_on": ["b"]},
                {"id": "b", "prompt": "b", "depends_on": ["a"]},
            ],
        )
    except ValueError as exc:
        assert "cycle" in str(exc)
    else:
        raise AssertionError("expected cycle validation error")
    with store._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_plan_id_can_be_reused_by_independent_runs(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    first = store.create_run_with_plan(_document())
    second = store.create_run_with_plan(_document())

    first_plan = store.get_current_plan(first.id)
    second_plan = store.get_current_plan(second.id)
    assert first_plan is not None and first_plan.plan_id == "plan-report"
    assert second_plan is not None and second_plan.plan_id == "plan-report"
    assert len(store.list_plan_revisions(first.id)) == 1
    assert len(store.list_plan_revisions(second.id)) == 1


class FailOnceEvaluator:
    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, result: str, workspace: Path) -> Evaluation:
        del result, workspace
        self.calls += 1
        return Evaluation(self.calls > 1, (), "pass" if self.calls > 1 else "first attempt rejected")


def test_failed_task_reopens_after_replan_and_can_resume(tmp_path: Path) -> None:
    config = Config(tmp_path / ".famou", max_retries=1)
    evaluator = FailOnceEvaluator()
    controller = LocalController(config, MockRuntime(), evaluator=evaluator)
    document = PlanDocument(
        goal="recover a failed task",
        plan_id="plan-recover",
        tasks=(PlanTask("one", "One", "run once"),),
    )
    run = controller.start_plan(document)
    assert run.status.value == "failed"
    revised = PlanDocument(
        goal=document.goal,
        plan_id=document.plan_id,
        version=2,
        parent_version=1,
        tasks=(PlanTask("one", "One", "run again"),),
    )
    controller.replan(run.id, revised, "retry after evaluator evidence")
    assert controller.store.get_run(run.id).status.value == "pending"  # type: ignore[union-attr]
    resumed = controller.resume(run.id)
    assert resumed.status.value == "succeeded"
    task = controller.store.list_tasks(run.id)[0]
    assert task.attempts == 1 and task.state.value == "succeeded"


def test_patch_with_new_dependency_maps_logical_ids_and_resume_executes(tmp_path: Path) -> None:
    config = Config(tmp_path / ".famou")
    controller = LocalController(config, MockRuntime())
    run = controller.start_plan(
        PlanDocument(
            goal="one task then expand",
            plan_id="plan-expand",
            tasks=(PlanTask("first", "First", "first output"),),
        )
    )
    patch = PlanPatch(
        plan_id="plan-expand",
        base_version=1,
        reason="add dependent verification",
        operations=(
            {"op": "add_task", "task": {"id": "check", "title": "Check", "prompt": "check output", "depends_on": ["first"]}},
            {"op": "add_task", "task": {"id": "summary", "title": "Summary", "prompt": "summarize", "depends_on": ["check"]}},
        ),
    )
    controller.patch_plan(run.id, patch)
    tasks = {task.plan_task_id: task for task in controller.store.list_tasks(run.id)}
    assert tasks["summary"].dependencies == (tasks["check"].id,)  # type: ignore[index]
    resumed = controller.resume(run.id)
    assert resumed.status.value == "succeeded"
    assert {task.state.value for task in controller.store.list_tasks(run.id)} == {"succeeded"}


def test_succeeded_task_redefinition_is_rejected_atomically(tmp_path: Path) -> None:
    config = Config(tmp_path / ".famou")
    controller = LocalController(config, MockRuntime())
    document = PlanDocument(
        goal="immutable", plan_id="plan-immutable", tasks=(PlanTask("one", "One", "run one"),)
    )
    run = controller.start_plan(document)
    with pytest.raises(ValueError, match="completed task definitions"):
        controller.replan(
            run.id,
            PlanDocument(
                goal=document.goal,
                plan_id=document.plan_id,
                version=2,
                parent_version=1,
                tasks=(PlanTask("one", "One", "run changed"),),
            ),
            "new prompt",
        )
    current = controller.store.get_current_plan(run.id)
    assert current is not None and current.version == 1


class BlockingRuntime(RecordingRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        self.started.set()
        self.release.wait(timeout=5)
        return super().run(prompt, workspace, timeout)


def test_cancel_discards_late_runtime_result(tmp_path: Path) -> None:
    config = Config(tmp_path / ".famou")
    runtime = BlockingRuntime()
    controller = LocalController(config, runtime)
    run = controller.create("cancel race")
    worker = threading.Thread(target=controller.resume, args=(run.id,))
    worker.start()
    assert runtime.started.wait(timeout=2)
    assert LocalController(config, MockRuntime()).cancel(run.id)
    runtime.release.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    final = controller.store.get_run(run.id)
    assert final is not None and final.status.value == "cancelled"
    task = controller.store.list_tasks(run.id)[0]
    assert task.state.value == "cancelled"
    assert task.result_path is None
    assert any(event["type"] == "task_result_discarded" for event in controller.store.list_events(run.id))
