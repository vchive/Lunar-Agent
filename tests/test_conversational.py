import json
from pathlib import Path

import pytest

from famou.algorithm import AlgorithmProblemContract
from famou.config import Config
from famou.controller import LocalController
from famou.conversational import (
    ContractCompilationError,
    RuntimeContractCompiler,
    build_algorithm_plan,
    build_algorithm_role_plan,
)
from famou.runtime import MockRuntime, RuntimeResult


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "mission-test",
            "problem_type": "routing",
            "statement": "Route all orders.",
            "inputs": [{"path": "orders.csv", "format": "csv", "fields": {"id": "order id"}}],
            "decision_variables": ["route order"],
            "objective": {"name": "distance", "direction": "minimize"},
            "hard_constraints": [],
            "soft_constraints": [],
            "success_criteria": ["Every order is served."],
            "deliverables": ["Route table."],
        }
    )


class EnvelopeRuntime:
    name = "fixture-compiler"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        del timeout
        self.prompts.append(prompt)
        if len(self.prompts) == 1:
            payload = {"status": "needs_input", "questions": [{"question": "Objective?", "options": ["time", "cost"]}]}
        else:
            payload = {"status": "compiled", "contract": _contract().to_dict()}
        workspace.mkdir(parents=True, exist_ok=True)
        return RuntimeResult(json.dumps(payload))

    def cancel(self) -> None:
        return None

    def process_info(self) -> tuple[int | None, int | None]:
        return (None, None)

    def set_process_observer(self, observer) -> None:
        del observer


def test_runtime_compiler_requires_strict_envelope_and_builds_plan(tmp_path: Path) -> None:
    runtime = EnvelopeRuntime()
    result = RuntimeContractCompiler(runtime).compile("route orders", tmp_path)
    assert result.status == "needs_input"
    assert result.questions[0].options == ("time", "cost")
    compiled = RuntimeContractCompiler(
        type("OneShot", (), {"name": "one", "run": lambda self, p, w, timeout=None: RuntimeResult(json.dumps({"status": "compiled", "contract": _contract().to_dict()}))})()
    ).compile("route orders", tmp_path)
    assert compiled.contract is not None
    plan = build_algorithm_plan("route orders", compiled.contract)
    assert [task.id for task in plan.tasks] == ["data_discovery", "formulate", "solve", "verify"]
    assert plan.tasks[-1].depends_on == ("solve",)


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "compiled", "contract": {"problem_id": "../escape"}},
        {"status": "needs_input", "questions": []},
        {"status": "compiled", "contract": {}, "raw": "unexpected"},
    ],
)
def test_runtime_compiler_rejects_malformed_or_unsafe_responses(tmp_path: Path, payload: dict[str, object]) -> None:
    class BadRuntime(MockRuntime):
        name = "bad"

        def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
            del prompt, workspace, timeout
            return RuntimeResult(json.dumps(payload))

    with pytest.raises(ContractCompilationError):
        RuntimeContractCompiler(BadRuntime()).compile("route orders", tmp_path)


def test_conversational_run_pauses_and_promotes_same_run_after_answer(tmp_path: Path) -> None:
    config = Config(tmp_path / "home")
    runtime = EnvelopeRuntime()
    controller = LocalController(config, runtime)
    compiler = RuntimeContractCompiler(runtime)
    run = controller.start_conversational("route orders", compiler, compiler_fingerprint="fp")
    assert run.status.value == "awaiting_input"
    pending = controller.store.pending_input(run.id)
    assert pending is not None
    artifacts = controller.store
    answer_path = Path(run.workspace) / "tasks" / pending["task_id"] / "input-answer.json"
    answer_path.parent.mkdir(parents=True, exist_ok=True)
    answer_path.write_text(json.dumps({"answer": "minimize time"}), encoding="utf-8")
    artifacts.add_artifact(run.id, pending["task_id"], "tasks/contract-intake/input-answer.json", "0" * 64, answer_path.stat().st_size, "input")
    assert controller.store.answer_input(run.id, "tasks/contract-intake/input-answer.json") == pending["task_id"]
    resumed = controller.resume_conversational(run.id, compiler, compiler_fingerprint="fp")
    assert resumed.status.value == "succeeded"
    assert resumed.id == run.id
    assert resumed.current_plan_id is not None
    assert (run.workspace / "solve" / "contract.json").is_file()
    assert len(controller.store.list_tasks(run.id)) == 5
    assert any(event["type"] == "contract_compiled" for event in controller.store.list_events(run.id))


def test_mock_compiler_is_standalone() -> None:
    result = RuntimeContractCompiler(MockRuntime()).compile("design a route", Path.cwd())
    assert result.status == "compiled"
    assert result.contract is not None
    assert result.contract.problem_type == "routing"


def test_role_plan_has_five_authority_bound_stages() -> None:
    plan = build_algorithm_role_plan("route orders", _contract())
    assert [task.id for task in plan.tasks] == [
        "data_discovery",
        "problem_formulator",
        "solver",
        "evaluator",
        "reviewer",
    ]
    assert plan.tasks[-1].depends_on == ("evaluator",)
    assert all("Role:" in task.prompt for task in plan.tasks)
    assert plan.algorithm_problem == _contract().to_dict()
    acceptance = {task.id: task.acceptance for task in plan.tasks}
    assert acceptance["data_discovery"] == {
        "data_profile_valid": "data/processed/data-profile.json"
    }
    assert acceptance["problem_formulator"] == {
        "artifact_valid": {
            "path": "solve/problem-formulation.md",
            "format": "text",
            "fields": [],
        }
    }
    assert acceptance["evaluator"] == {"evaluation_report_valid": "evaluate/evaluation.json"}
    assert acceptance["reviewer"] == {
        "artifact_valid": {"path": "evaluate/review.md", "format": "text", "fields": []}
    }


def test_algorithm_plan_turns_declared_outputs_into_independent_checks() -> None:
    contract = AlgorithmProblemContract.from_dict(
        {
            **_contract().to_dict(),
            "outputs": [
                {"path": "output/routes.csv", "format": "csv", "fields": ["order_id", "route_id"]},
                {"path": "output/summary.json", "format": "json", "fields": ["distance"]},
            ],
        }
    )
    plan = build_algorithm_plan("route orders", contract)
    acceptance = plan.tasks[2].acceptance
    assert isinstance(acceptance, dict)
    assert "all" in acceptance
    assert len(acceptance["all"]) == 2
    assert plan.algorithm_problem["outputs"][0]["path"] == "output/routes.csv"
