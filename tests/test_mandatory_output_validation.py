import hashlib
import json
from pathlib import Path

import pytest

from famou.algorithm import AlgorithmProblemContract
from famou.config import Config
from famou.controller import LocalController
from famou.evaluator import ContainsEvaluator
from famou.policy import PlanDocument, PlanTask
from famou.runtime import RuntimeResult

VALID_CSV = "item_id,route_id\norder-1,route-a\n"
INVALID_CSV = "item_id\norder-1\n"
OUTPUT_RULE = {
    "output_valid": {
        "path": "output/routes.csv",
        "format": "csv",
        "fields": ["item_id", "route_id"],
    }
}


class OutputRuntime:
    name = "mandatory-output-fixture"

    def __init__(self, *modes: str) -> None:
        self.modes = modes
        self.prompts: list[str] = []

    def run(self, prompt: str, workspace: Path, timeout=None) -> RuntimeResult:
        del timeout
        mode = self.modes[len(self.prompts)]
        self.prompts.append(prompt)
        workspace.mkdir(parents=True, exist_ok=True)
        output = workspace / "output"
        if mode == "ancestor_symlink":
            actual = workspace / "actual-output"
            actual.mkdir()
            output.symlink_to(actual, target_is_directory=True)
        elif mode == "non_directory_ancestor":
            output.write_text("not a directory", encoding="utf-8")
        elif mode != "absent":
            output.mkdir()
            target = output / "routes.csv"
            if mode == "directory":
                target.mkdir()
            elif mode in {"symlink", "dangling_symlink"}:
                actual = workspace / "actual-routes.csv"
                if mode == "symlink":
                    actual.write_text(VALID_CSV, encoding="utf-8")
                target.symlink_to(actual)
            else:
                assert mode in {"valid", "invalid"}
                target.write_text(VALID_CSV if mode == "valid" else INVALID_CSV, encoding="utf-8")
        return RuntimeResult("solver completed")

    def cancel(self) -> None:
        return None


def _plan(acceptance=None, *, required: bool = True) -> PlanDocument:
    contract = AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "mandatory-output-check",
            "problem_type": "routing",
            "statement": "Assign every order to a route.",
            "inputs": [{"path": "orders.csv", "format": "csv", "fields": {"id": "order ID"}}],
            "decision_variables": ["route per order"],
            "objective": {"name": "distance", "direction": "minimize"},
            "hard_constraints": [],
            "soft_constraints": [],
            "success_criteria": ["Every order is assigned."],
            "deliverables": ["Route table."],
            "outputs": [{**OUTPUT_RULE["output_valid"], "required": required}],
        }
    )
    return PlanDocument(
        goal="solve routes",
        plan_id="plan-mandatory-output-check",
        tasks=(PlanTask("solver", "Solver", "write route output", acceptance=acceptance),),
        algorithm_problem=contract.to_dict(),
    )


def _alternative_acceptance(kind: str):
    alternative = {"any": [OUTPUT_RULE, {"result_contains": "solver completed"}]}
    if kind == "nested":
        return {"all": [{"result_contains": "solver"}, alternative]}
    if kind == "encoded":
        return json.dumps(alternative)
    assert kind == "any"
    return alternative


def _evaluations(controller, run):
    return [
        event["payload"]
        for event in controller.store.list_events(run.id)
        if event["type"] == "task_evaluated"
    ]


def _output_artifacts(controller, run):
    return [item for item in controller.store.list_artifacts(run.id) if item["kind"] == "output"]


def _assert_rejected(controller, run) -> None:
    assert run.status.value == "failed"
    assert not (run.workspace / "output/routes.csv").exists()
    assert _output_artifacts(controller, run) == []
    with pytest.raises(ValueError):
        controller.deliver(run.id)


@pytest.mark.parametrize("kind", ["any", "nested", "encoded"])
def test_alternative_acceptance_cannot_override_invalid_required_output(tmp_path, kind) -> None:
    controller = LocalController(Config(tmp_path / "home", max_retries=1), OutputRuntime("invalid"))
    run = controller.start_plan(_plan(_alternative_acceptance(kind)))

    _assert_rejected(controller, run)
    evaluation = _evaluations(controller, run)[0]
    assert evaluation["passed"] is False
    assert evaluation["details"]["acceptance"]["check"]["passed"] is True
    assert "output_valid" in controller._failed_acceptance_rules(evaluation["details"])


@pytest.mark.parametrize("kind,mode", [("any", "valid"), ("all", "valid"), ("all", "invalid")])
def test_output_contract_preserves_valid_alternative_and_all_semantics(tmp_path, kind, mode) -> None:
    acceptance = {kind: [OUTPUT_RULE, {"result_contains": "solver completed"}]}
    controller = LocalController(Config(tmp_path / "home", max_retries=1), OutputRuntime(mode))
    run = controller.start_plan(_plan(acceptance))

    if mode == "invalid":
        _assert_rejected(controller, run)
    else:
        assert run.status.value == "succeeded"
        assert (run.workspace / "output/routes.csv").read_text(encoding="utf-8") == VALID_CSV
        assert "output/routes.csv" in controller.deliver(run.id).evidence


@pytest.mark.parametrize(
    "mode",
    [
        "absent", "valid", "invalid", "directory", "symlink", "dangling_symlink",
        "ancestor_symlink", "non_directory_ancestor",
    ],
)
def test_optional_output_can_be_omitted_only_when_safely_absent(tmp_path, mode) -> None:
    controller = LocalController(Config(tmp_path / "home", max_retries=1), OutputRuntime(mode))
    run = controller.start_plan(_plan(required=False))

    if mode in {"absent", "valid"}:
        assert run.status.value == "succeeded"
        assert controller.deliver(run.id).action == "deliver"
        assert len(_output_artifacts(controller, run)) == (1 if mode == "valid" else 0)
    else:
        _assert_rejected(controller, run)
        evaluation = _evaluations(controller, run)[0]
        assert "output_valid" in controller._failed_acceptance_rules(evaluation["details"])


@pytest.mark.parametrize("rejecting_check", ["base", "acceptance"])
def test_valid_output_does_not_override_base_or_custom_acceptance_failure(
    tmp_path, rejecting_check
) -> None:
    evaluator = ContainsEvaluator("never returned") if rejecting_check == "base" else None
    acceptance = {"result_contains": "never returned"} if rejecting_check == "acceptance" else None
    controller = LocalController(
        Config(tmp_path / "home", max_retries=1), OutputRuntime("valid"), evaluator=evaluator
    )
    run = controller.start_plan(_plan(acceptance))

    _assert_rejected(controller, run)
    assert _evaluations(controller, run)[0]["passed"] is False


def test_invalid_alternative_output_is_retried_with_feedback_before_delivery(tmp_path) -> None:
    runtime = OutputRuntime("invalid", "valid")
    controller = LocalController(Config(tmp_path / "home", max_retries=2), runtime)
    run = controller.start_plan(_plan(_alternative_acceptance("any")))

    assert run.status.value == "succeeded"
    assert len(runtime.prompts) == 2
    assert "Retry feedback" in runtime.prompts[1]
    assert "acceptance_rule:output_valid" in runtime.prompts[1]
    assert [item["passed"] for item in _evaluations(controller, run)] == [False, True]
    assert (run.workspace / "output/routes.csv").read_text(encoding="utf-8") == VALID_CSV
    artifacts = _output_artifacts(controller, run)
    assert len(artifacts) == 1
    assert artifacts[0]["sha256"] == hashlib.sha256(VALID_CSV.encode("utf-8")).hexdigest()
    assert "output/routes.csv" in controller.deliver(run.id).evidence
