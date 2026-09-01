import json
import threading
from pathlib import Path

from famou.config import Config
from famou.controller import LocalController
from famou.evaluator import Evaluation
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
    with store._connect() as connection:  # noqa: SLF001 - verifies transaction rollback
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


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
