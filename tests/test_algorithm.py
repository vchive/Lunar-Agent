import hashlib
import json
from pathlib import Path

import pytest

from famou.algorithm import (
    AlgorithmProblemContract,
    EvaluationReport,
    OutputSpec,
    materialize_algorithm_workspace,
)
from famou.config import Config
from famou.controller import LocalController
from famou.policy import PlanDocument
from famou.runtime import MockRuntime


def _contract(problem_type: str = "routing", **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1",
        "problem_id": "routing-demo",
        "problem_type": problem_type,
        "statement": "Assign every item to a feasible route.",
        "inputs": [
            {
                "path": "items.csv",
                "format": "csv",
                "fields": {"item_id": "unique item identifier", "demand": "non-negative demand"},
                "key": "item_id",
            }
        ],
        "decision_variables": ["route sequence per item"],
        "objective": {"name": "travel time", "direction": "minimize"},
        "hard_constraints": [
            {
                "id": "serve-each",
                "description": "Every item is served exactly once.",
                "source": "user_confirmed",
                "verification": "independent",
                "result_fields": ["item_id", "route_id"],
            }
        ],
        "soft_constraints": [],
        "success_criteria": ["All items appear in the result."],
        "deliverables": ["Route table and summary."],
        "assumptions": [],
        "evolution": {"strategy": "loop", "max_rounds": 5, "stagnation_rounds": 3},
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    "problem_type",
    ["scheduling", "routing", "packing", "assignment", "forecasting", "network_flow", "continuous"],
)
def test_problem_contract_round_trips_all_supported_types(problem_type: str) -> None:
    contract = AlgorithmProblemContract.from_dict(_contract(problem_type))
    canonical = contract.to_dict()
    assert canonical["problem_type"] == problem_type
    assert AlgorithmProblemContract.from_dict(canonical).to_dict() == canonical


def test_problem_contract_defaults_to_loop_and_accepts_population() -> None:
    without_evolution = _contract()
    without_evolution.pop("evolution")
    assert AlgorithmProblemContract.from_dict(without_evolution).evolution.strategy == "loop"
    population = AlgorithmProblemContract.from_dict(
        _contract(evolution={"strategy": "population", "max_rounds": 20, "stagnation_rounds": 4})
    )
    assert population.evolution.strategy == "population"


def test_contract_declares_structured_data_outputs() -> None:
    contract = AlgorithmProblemContract.from_dict(
        _contract(
            outputs=[
                {
                    "path": "output/routes.csv",
                    "format": "csv",
                    "fields": ["item_id", "route_id"],
                    "description": "One route assignment per item",
                },
                {"path": "output/summary.json", "format": "json", "fields": ["distance"]},
            ]
        )
    )
    assert contract.outputs[0] == OutputSpec(
        "output/routes.csv", "csv", ("item_id", "route_id"), description="One route assignment per item"
    )
    assert AlgorithmProblemContract.from_dict(contract.to_dict()).to_dict() == contract.to_dict()
    with pytest.raises(ValueError, match="output/"):
        OutputSpec("solve/routes.csv", "csv")
    with pytest.raises(ValueError, match="format"):
        OutputSpec("output/routes.bin", "binary")


@pytest.mark.parametrize(
    "mutator, message",
    [
        (lambda p: p["inputs"][0].update(path="../outside.csv"), "relative"),
        (lambda p: p["inputs"][0].update(path="/tmp/outside.csv"), "relative"),
        (lambda p: p["hard_constraints"][0].pop("source"), "source"),
        (lambda p: p["evolution"].update(strategy="unknown"), "strategy"),
    ],
)
def test_problem_contract_rejects_unsafe_or_incomplete_values(mutator, message: str) -> None:
    payload = _contract()
    mutator(payload)
    with pytest.raises((ValueError, TypeError), match=message):
        AlgorithmProblemContract.from_dict(payload)


def test_problem_contract_rejects_duplicate_ids_and_secrets() -> None:
    payload = _contract(
        hard_constraints=[
            {
                "id": "duplicate",
                "description": "first",
                "source": "user_confirmed",
                "verification": "independent",
                "result_fields": [],
            },
            {
                "id": "duplicate",
                "description": "second",
                "source": "data_observed",
                "verification": "independent",
                "result_fields": [],
            },
        ]
    )
    with pytest.raises(ValueError, match="unique"):
        AlgorithmProblemContract.from_dict(payload)
    secret = _contract(statement="Use api_key=secret-value")
    with pytest.raises(ValueError, match="credential"):
        AlgorithmProblemContract.from_dict(secret)


def test_workspace_manifest_is_hashed_and_confined(tmp_path: Path) -> None:
    contract = AlgorithmProblemContract.from_dict(_contract())
    manifest_path = materialize_algorithm_workspace(tmp_path / "run", contract, "plan-1", 2)
    expected = hashlib.sha256(
        json.dumps(contract.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["contract_sha256"] == expected
    assert payload["plan_version"] == 2
    for directory in ("data/raw", "data/processed", "solve", "evaluate", "output", "evolution"):
        assert (tmp_path / "run" / directory).is_dir()
    assert manifest_path.parent == (tmp_path / "run").resolve()


def test_workspace_rejects_symlinked_role_directory(tmp_path: Path) -> None:
    root = tmp_path / "run"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "solve").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        materialize_algorithm_workspace(root, AlgorithmProblemContract.from_dict(_contract()), "plan-1", 1)


def test_evaluation_report_enforces_validity_first() -> None:
    valid = EvaluationReport.from_dict(
        {
            "schema_version": "1",
            "evaluator_id": "routing-v1",
            "validity": 1,
            "quality": 0.8,
            "combined_score": 0.8,
            "detailed_scores": {"travel_time": {"value": 0.8, "direction": "maximize"}},
            "error_info": [],
        }
    )
    assert valid.to_dict()["validity"] == 1
    invalid = {
        **valid.to_dict(),
        "validity": 0,
        "combined_score": 0,
        "error_info": [{"code": "constraint_violation", "message": "serve-each failed"}],
    }
    assert EvaluationReport.from_dict(invalid).to_dict()["combined_score"] == 0
    with pytest.raises(ValueError, match="combined_score"):
        EvaluationReport.from_dict({**invalid, "combined_score": 1})
    with pytest.raises(ValueError, match="error_info"):
        EvaluationReport.from_dict({**invalid, "error_info": []})


def test_evaluation_report_rejects_negative_or_nonfinite_scores() -> None:
    base = {
        "schema_version": "1",
        "evaluator_id": "x",
        "validity": 1,
        "quality": 0,
        "combined_score": 0,
        "detailed_scores": {"metric": {"value": 1, "direction": "minimize"}},
        "error_info": [],
    }
    with pytest.raises(ValueError, match="non-negative"):
        EvaluationReport.from_dict({**base, "combined_score": -1})
    with pytest.raises(ValueError, match="finite"):
        EvaluationReport.from_dict({**base, "quality": float("inf")})


def test_algorithm_problem_is_preserved_and_materialized_on_run(tmp_path: Path) -> None:
    document = PlanDocument.from_dict(
        {
            "plan_id": "algorithm-plan",
            "goal": "solve routing",
            "tasks": [{"id": "solve", "title": "Solve", "prompt": "write a result"}],
            "algorithm_problem": _contract(),
        }
    )
    assert document.algorithm_problem is not None
    assert document.algorithm_problem["evolution"]["strategy"] == "loop"
    controller = LocalController(Config(tmp_path / ".famou"), MockRuntime())
    run = controller.start_plan(document)
    manifest = run.workspace / "algorithm-workspace.json"
    assert run.status.value == "succeeded"
    assert manifest.is_file()
    assert any(event["type"] == "algorithm_contract_registered" for event in controller.store.list_events(run.id))
    assert any(item["kind"] == "algorithm_manifest" for item in controller.store.list_artifacts(run.id))
