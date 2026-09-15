import hashlib
import json
from pathlib import Path

import pytest
from test_cli import _write_evolution_contract

from famou import benchmark_result as module
from famou import cli
from famou.algorithm import AlgorithmProblemContract
from famou.benchmark_comparison import BenchmarkComparisonPlan
from famou.benchmark_result import BenchmarkComparisonResult, ComparisonArmResult
from famou.benchmark_task import BenchmarkTaskEnvelope
from tests.test_benchmark_comparison import env


def _cli_files(tmp_path: Path):
    contract_path = tmp_path / "private-contract.json"
    _write_evolution_contract(contract_path)
    contract = AlgorithmProblemContract.from_dict(json.loads(contract_path.read_text()))
    input_root = tmp_path / "private-inputs"
    input_root.mkdir()
    (input_root / "task.json").write_bytes(b'{"items":[1]}')
    plan = BenchmarkComparisonPlan.from_envelopes({
        name: BenchmarkTaskEnvelope.from_dict({
            **env(name).to_dict(), "contract_sha256": contract.digest(),
        }) for name in ("sky", "llm4ad")
    })
    plan_path = tmp_path / "private-plan.json"
    plan_path.write_text(json.dumps(plan.to_dict()))
    evidence_root = tmp_path / "private-evidence"
    evidence_root.mkdir()
    evidence = evidence_root / "private-observation.txt"
    content = b"private-evidence-content-must-not-be-printed"
    evidence.write_bytes(content)
    arms = tuple(
        ComparisonArmResult(
            arm.id, "completed", 10, 2, 1, 0.5,
            hashlib.sha256(content).hexdigest(), evidence.name, len(content),
        ) for arm in plan.arms
    )
    result = BenchmarkComparisonResult(
        plan.comparison_id, module._result_id(plan.comparison_id, arms), arms,
    )
    result_path = tmp_path / "private-result.json"
    result_path.write_text(json.dumps(result.to_dict()))
    args = [
        "benchmark-comparison", "validate-result", str(plan_path), str(result_path),
        "--contract", str(contract_path), "--input-root", str(input_root),
        "--model-profile-sha256", "d" * 64, "--evaluator-fingerprint", "b" * 64,
        "--evidence-root", str(evidence_root),
    ]
    return args, result_path, evidence


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize(
    ("failure", "error_code"),
    [
        ("missing", "benchmark_result_evidence_missing"),
        ("changed", "benchmark_result_evidence_changed"),
        ("symlink", "benchmark_result_evidence_unsafe"),
        ("null_descriptor", "benchmark_result_evidence_invalid"),
        ("invalid_status", "benchmark_result_invalid"),
        ("overflow_score", "benchmark_result_invalid"),
        ("surrogate_path", "benchmark_result_evidence_invalid"),
        ("oversized_json_integer", "benchmark_result_invalid"),
    ],
)
def test_cli_evidence_failure_is_static_and_redacted(
    tmp_path: Path, monkeypatch, capsys, json_mode: bool, failure: str, error_code: str,
):
    args, result_path, evidence = _cli_files(tmp_path)
    payload = json.loads(result_path.read_text())
    if failure == "missing":
        evidence.unlink()
    elif failure == "changed":
        evidence.write_bytes(b"modified-private-content-must-not-be-printed")
    elif failure == "symlink":
        outside = tmp_path / "private-outside.txt"
        evidence.rename(outside)
        evidence.symlink_to(outside)
    elif failure == "oversized_json_integer":
        result_path.write_text('{"private_integer":' + "1" * 5000 + "}")
    else:
        mutations = {
            "null_descriptor": {"evidence_path": None, "evidence_size": None},
            "invalid_status": {"status": ["private-status-value"]},
            "overflow_score": {"best_score": 10**400},
            "surrogate_path": {"evidence_path": "\ud800"},
        }
        payload["arms"][0].update(mutations[failure])
        result_path.write_text(json.dumps(payload))

    def unexpected_initialization(*_args, **_kwargs):
        pytest.fail("static validation initialized home or Store")

    monkeypatch.setattr(cli, "_config", unexpected_initialization)
    monkeypatch.setattr(cli.Config, "ensure", unexpected_initialization)
    monkeypatch.setattr(cli.Store, "__init__", unexpected_initialization)
    monkeypatch.setattr(cli.Store, "initialize", unexpected_initialization)
    home = tmp_path / "private-home-must-not-be-created"
    args.extend(["--home", str(home)])
    if json_mode:
        args.append("--json")

    assert cli.main(args) == 2
    output = capsys.readouterr()
    assert output.out == ""
    if json_mode:
        assert json.loads(output.err) == {"error": error_code}
    else:
        assert output.err == f"error: {error_code}\n"
    assert str(tmp_path) not in output.err
    assert "private-" not in output.err
    assert not home.exists()
    assert not list(tmp_path.rglob("state.db"))
