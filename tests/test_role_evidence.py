import json
from pathlib import Path

from famou.algorithm import AlgorithmProblemContract
from famou.cli import _status_payload
from famou.config import Config
from famou.controller import LocalController
from famou.conversational import build_algorithm_role_plan
from famou.runtime import RuntimeResult


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "role-evidence",
            "problem_type": "routing",
            "statement": "Assign orders to routes.",
            "inputs": [{"path": "orders.csv", "format": "csv", "fields": {"id": "order id"}}],
            "decision_variables": ["route per order"],
            "objective": {"name": "distance", "direction": "minimize"},
            "hard_constraints": [],
            "soft_constraints": [],
            "success_criteria": ["Every order is served."],
            "deliverables": ["Verified route table."],
        }
    )


class RoleRuntime:
    name = "role-fixture"

    def __init__(self, *, omit_evaluation: bool = False) -> None:
        self.omit_evaluation = omit_evaluation

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        del timeout
        workspace.mkdir(parents=True, exist_ok=True)
        if "data/processed/data-profile.json" in prompt:
            path = workspace / "data" / "processed" / "data-profile.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "inputs": [
                            {
                                "path": "data/raw/orders.csv",
                                "format": "csv",
                                "row_count": 1,
                                "columns": ["id"],
                                "issues": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
        if "solve/problem-formulation.md" in prompt:
            path = workspace / "solve" / "problem-formulation.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Formulation\n", encoding="utf-8")
        if "evaluate/evaluation.json" in prompt and not self.omit_evaluation:
            path = workspace / "evaluate" / "evaluation.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "evaluator_id": "fixture",
                        "validity": 1,
                        "quality": 1,
                        "combined_score": 1,
                        "detailed_scores": {},
                        "error_info": [],
                    }
                ),
                encoding="utf-8",
            )
        if "evaluate/review.md" in prompt:
            path = workspace / "evaluate" / "review.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Review\nVerified.\n", encoding="utf-8")
        return RuntimeResult("role completed")

    def cancel(self) -> None:
        return None


def test_role_dag_records_strict_evidence_and_delivers_it(tmp_path: Path) -> None:
    controller = LocalController(Config(tmp_path / "home"), RoleRuntime())
    run = controller.start_plan(build_algorithm_role_plan("route orders", _contract()))

    assert run.status.value == "succeeded"
    evidence = [
        item for item in controller.store.list_artifacts(run.id) if item["kind"] == "role_evidence"
    ]
    assert len(evidence) == 4
    assert all(len(item["sha256"]) == 64 for item in evidence)
    decision = controller.deliver(run.id)
    assert decision.action == "deliver"
    assert any(path.endswith("data-profile.json") for path in decision.evidence)
    status = _status_payload(Config(tmp_path / "home"), run.id)
    assert status is not None and len(status["role_evidence"]) == 4
    assert any(event["type"] == "role_evidence_recorded" for event in controller.store.list_events(run.id))


def test_role_dag_rejects_evaluator_prose_without_report(tmp_path: Path) -> None:
    controller = LocalController(
        Config(tmp_path / "home", max_retries=1), RoleRuntime(omit_evaluation=True)
    )
    run = controller.start_plan(build_algorithm_role_plan("route orders", _contract()))

    assert run.status.value == "failed"
    evaluator_task = next(
        task for task in controller.store.list_tasks(run.id) if task.plan_task_id == "evaluator"
    )
    assert evaluator_task.last_error is not None
    assert "evaluation report" in evaluator_task.last_error
