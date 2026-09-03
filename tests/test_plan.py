import json
import threading
from pathlib import Path

import pytest

from famou.algorithm import AlgorithmProblemContract
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


class ArtifactRuntime:
    name = "artifact"

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        del prompt, timeout
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "report.json").write_text(
            json.dumps({"summary": "verified", "sources": []}), encoding="utf-8"
        )
        return RuntimeResult(text="report written", artifacts=("report.json",))

    def cancel(self) -> None:
        return None


class StructuredOutputRuntime:
    name = "structured-output"

    def __init__(self, *, mode: str = "valid") -> None:
        self.mode = mode

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        del prompt, timeout
        workspace.mkdir(parents=True, exist_ok=True)
        if self.mode == "valid":
            output = workspace / "output"
            output.mkdir(parents=True, exist_ok=True)
            (output / "routes.csv").write_text(
                "item_id,route_id\norder-1,route-a\n", encoding="utf-8"
            )
        elif self.mode == "invalid":
            output = workspace / "output"
            output.mkdir(parents=True, exist_ok=True)
            (output / "routes.csv").write_text("item_id\norder-1\n", encoding="utf-8")
        return RuntimeResult("solver completed")

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


def _structured_output_contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "output-demo",
            "problem_type": "routing",
            "statement": "Assign every order to a route.",
            "inputs": [{"path": "orders.csv", "format": "csv", "fields": {"id": "order id"}}],
            "decision_variables": ["route per order"],
            "objective": {"name": "distance", "direction": "minimize"},
            "hard_constraints": [],
            "soft_constraints": [],
            "success_criteria": ["Every order is assigned."],
            "deliverables": ["Route table."],
            "outputs": [
                {"path": "output/routes.csv", "format": "csv", "fields": ["item_id", "route_id"]}
            ],
        }
    )


def test_algorithm_outputs_are_promoted_hashed_and_delivered(tmp_path: Path) -> None:
    contract = _structured_output_contract()
    plan = PlanDocument(
        goal="solve routes",
        plan_id="plan-output-demo",
        tasks=(PlanTask("solver", "Solver", "write the route output"),),
        algorithm_problem=contract.to_dict(),
    )
    controller = LocalController(Config(tmp_path / ".famou"), StructuredOutputRuntime())
    run = controller.start_plan(plan)

    delivered_path = run.workspace / "output" / "routes.csv"
    assert run.status.value == "succeeded"
    assert delivered_path.read_text(encoding="utf-8").startswith("item_id,route_id")
    output_artifacts = [
        item for item in controller.store.list_artifacts(run.id) if item["kind"] == "output"
    ]
    assert len(output_artifacts) == 1
    assert output_artifacts[0]["path"] == "output/routes.csv"
    assert len(output_artifacts[0]["sha256"]) == 64
    assert "output/routes.csv" in controller.deliver(run.id).evidence
    assert any(event["type"] == "algorithm_outputs_promoted" for event in controller.store.list_events(run.id))


def test_required_algorithm_output_is_not_satisfied_by_prose(tmp_path: Path) -> None:
    plan = PlanDocument(
        goal="solve routes",
        plan_id="plan-missing-output",
        tasks=(PlanTask("solver", "Solver", "write the route output"),),
        algorithm_problem=_structured_output_contract().to_dict(),
    )
    controller = LocalController(
        Config(tmp_path / ".famou", max_retries=1), StructuredOutputRuntime(mode="invalid")
    )
    run = controller.start_plan(plan)

    assert run.status.value == "failed"
    assert not (run.workspace / "output" / "routes.csv").exists()
    with pytest.raises(ValueError, match="verified algorithm outputs"):
        controller.deliver(run.id)


def test_algorithm_contract_round_trips_in_revision_and_legacy_plan_stays_generic(tmp_path: Path) -> None:
    contract = {
        "problem_id": "assignment-plan",
        "problem_type": "assignment",
        "statement": "Assign each worker to one task.",
        "inputs": [
            {
                "path": "workers.csv",
                "format": "csv",
                "fields": {"worker_id": "unique worker identifier"},
                "key": "worker_id",
            }
        ],
        "decision_variables": ["worker-task assignment"],
        "objective": {"name": "total preference", "direction": "maximize"},
        "hard_constraints": [
            {
                "id": "one-task",
                "description": "Each worker receives one task.",
                "source": "user_confirmed",
                "verification": "independent",
                "result_fields": ["worker_id", "task_id"],
            }
        ],
        "success_criteria": ["Every worker is assigned."],
        "deliverables": ["Assignment table."],
    }
    controller = LocalController(Config(tmp_path / ".famou"), MockRuntime())
    document = PlanDocument.from_dict(
        {
            "plan_id": "assignment-plan-revision",
            "goal": "solve assignment",
            "tasks": [{"id": "solve", "prompt": "write assignment"}],
            "algorithm_problem": contract,
        }
    )
    run = controller.start_plan(document)
    current = controller.store.get_current_plan(run.id)
    assert current is not None and current.algorithm_problem == document.algorithm_problem
    assert PlanDocument.from_dict(_document().to_dict()).algorithm_problem is None


def test_replan_updates_algorithm_contract_manifest_and_keeps_revision_audit(tmp_path: Path) -> None:
    initial_contract = {
        "problem_id": "routing-replan",
        "problem_type": "routing",
        "statement": "Route each item while minimizing travel time.",
        "inputs": [
            {
                "path": "items.csv",
                "format": "csv",
                "fields": {"item_id": "unique item identifier"},
                "key": "item_id",
            }
        ],
        "decision_variables": ["route per item"],
        "objective": {"name": "travel time", "direction": "minimize"},
        "hard_constraints": [
            {
                "id": "serve-each",
                "description": "Serve each item exactly once.",
                "source": "user_confirmed",
                "verification": "independent",
                "result_fields": ["item_id"],
            }
        ],
        "success_criteria": ["Every item is served."],
        "deliverables": ["Route table."],
        "evolution": {"strategy": "loop", "max_rounds": 5, "stagnation_rounds": 3},
    }
    controller = LocalController(Config(tmp_path / ".famou"), MockRuntime())
    original = PlanDocument.from_dict(
        {
            "plan_id": "plan-algorithm-replan",
            "goal": "solve routing",
            "tasks": [{"id": "solve", "title": "Solve", "prompt": "write route"}],
            "algorithm_problem": initial_contract,
        }
    )
    run = controller.start_plan(original)
    first_manifest = json.loads((run.workspace / "algorithm-workspace.json").read_text(encoding="utf-8"))
    first_digest = first_manifest["contract_sha256"]
    completed_task = controller.store.list_tasks(run.id)[0]
    assert completed_task.result_path is not None
    result_path = run.workspace / completed_task.result_path
    result_before = result_path.read_bytes()

    revised_contract = {
        **initial_contract,
        "evolution": {"strategy": "population", "max_rounds": 20, "stagnation_rounds": 4},
    }
    revised = PlanDocument.from_dict(
        {
            "plan_id": original.plan_id,
            "version": 2,
            "parent_version": 1,
            "goal": original.goal,
            "tasks": [{"id": "solve", "title": "Solve", "prompt": "write route"}],
            "algorithm_problem": revised_contract,
        }
    )
    committed = controller.replan(run.id, revised, "enable population for a longer local run")

    manifest = json.loads((run.workspace / "algorithm-workspace.json").read_text(encoding="utf-8"))
    assert committed.version == 2
    assert manifest["plan_version"] == 2
    assert manifest["contract_sha256"] != first_digest
    current = controller.store.get_current_plan(run.id)
    assert current is not None and current.algorithm_problem is not None
    assert current.algorithm_problem["evolution"]["strategy"] == "population"
    assert manifest["contract_sha256"] == AlgorithmProblemContract.from_dict(
        current.algorithm_problem
    ).digest()
    completed_after = controller.store.list_tasks(run.id)[0]
    assert completed_after.state.value == "succeeded"
    assert completed_after.result_path == completed_task.result_path
    assert result_path.read_bytes() == result_before
    registered = [
        event
        for event in controller.store.list_events(run.id)
        if event["type"] == "algorithm_contract_registered"
    ]
    assert [event["payload"]["plan_version"] for event in registered] == [1, 2]
    manifest_artifacts = [
        artifact for artifact in controller.store.list_artifacts(run.id) if artifact["kind"] == "algorithm_manifest"
    ]
    assert len(manifest_artifacts) == 2
    assert len({artifact["sha256"] for artifact in manifest_artifacts}) == 2
    assert manifest_artifacts[-1]["size"] == (run.workspace / "algorithm-workspace.json").stat().st_size


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


def test_artifact_acceptance_is_independently_verified_and_deliverable(tmp_path: Path) -> None:
    controller = LocalController(Config(tmp_path / ".famou"), ArtifactRuntime())
    run = controller.start_plan(
        PlanDocument(
            goal="write a verified report",
            plan_id="plan-artifact-report",
            tasks=(
                PlanTask(
                    "report",
                    "Report",
                    "write report",
                    acceptance={
                        "all": [
                            {"artifact_exists": "report.json"},
                            {
                                "json_has_keys": {
                                    "path": "report.json",
                                    "keys": ["summary", "sources"],
                                }
                            },
                        ]
                    },
                ),
            ),
        )
    )

    assert run.status.value == "succeeded"
    event = next(event for event in controller.store.list_events(run.id) if event["type"] == "task_evaluated")
    assert event["payload"]["details"]["acceptance"]["check"]["passed"] is True
    physical_task_id = controller.store.list_tasks(run.id)[0].id
    audit = next(run.workspace.glob(f"tasks/{physical_task_id}/*/evaluation.json"))
    assert json.loads(audit.read_text(encoding="utf-8"))["details"]["acceptance"]["check"]["rule"] == "all"
    assert controller.deliver(run.id).action == "deliver"


def test_missing_artifact_acceptance_prevents_delivery(tmp_path: Path) -> None:
    controller = LocalController(Config(tmp_path / ".famou", max_retries=1), MockRuntime())
    run = controller.start(
        "checked output",
        [{"id": "report", "prompt": "write report", "acceptance": {"artifact_exists": "report.json"}}],
    )

    assert run.status.value == "failed"
    with pytest.raises(ValueError, match="fully verified"):
        controller.deliver(run.id)


def test_replan_preserves_a_completed_artifact_contract(tmp_path: Path) -> None:
    controller = LocalController(Config(tmp_path / ".famou"), ArtifactRuntime())
    acceptance = {"json_has_keys": {"path": "report.json", "keys": ["summary", "sources"]}}
    original = PlanDocument(
        goal="write checked report",
        plan_id="plan-artifact-revision",
        tasks=(PlanTask("report", "Report", "write report", acceptance=acceptance),),
    )
    run = controller.start_plan(original)

    revised = PlanDocument(
        goal=original.goal,
        plan_id=original.plan_id,
        version=2,
        parent_version=1,
        tasks=(PlanTask("report", "Report", "write report", acceptance=acceptance),),
    )
    result = controller.replan(run.id, revised, "retain verified artifact contract")

    assert result.version == 2
    current = controller.store.get_current_plan(run.id)
    assert current is not None and current.tasks[0].acceptance == acceptance


def test_unsafe_acceptance_is_rejected_before_a_legacy_run_insert(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()

    with pytest.raises(ValueError, match="workspace"):
        store.create_run("unsafe", tasks=[{"id": "one", "prompt": "one", "acceptance": {"artifact_exists": "../outside"}}])

    with store._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


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
