import hashlib
import json
from pathlib import Path

import pytest

from famou import cli
from famou.algorithm import AlgorithmProblemContract
from famou.benchmark_comparison import BenchmarkComparisonPlan
from famou.benchmark_result import (
    BenchmarkComparisonResult,
    BenchmarkResultError,
    ComparisonArmResult,
    admit_benchmark_comparison_result,
    parse_benchmark_comparison_result,
)
from tests.test_benchmark_comparison import env


def _plan() -> BenchmarkComparisonPlan:
    return BenchmarkComparisonPlan.from_envelopes({"sky": env(), "llm4ad": env("llm4ad")})


def _result(plan: BenchmarkComparisonPlan) -> BenchmarkComparisonResult:
    arms = tuple(ComparisonArmResult(a.id, "completed", 10, 2, 1, 0.5, "e" * 64) for a in plan.arms)
    from famou import benchmark_result as module
    rid = module._result_id(plan.comparison_id, arms)
    return BenchmarkComparisonResult(plan.comparison_id, rid, arms)


def test_result_roundtrip_and_plan_admission(tmp_path: Path):
    plan = _plan()
    result = _result(plan)
    assert parse_benchmark_comparison_result(result.to_dict()).digest() == result.digest()
    assert admit_benchmark_comparison_result(result, plan) == result


def test_result_rejects_missing_or_extra_arm():
    plan = _plan()
    result = _result(plan)
    arm = result.arms[0]
    with pytest.raises(BenchmarkResultError):
        admit_benchmark_comparison_result(BenchmarkComparisonResult(plan.comparison_id, result.result_id, (arm,)), plan)


def test_result_parser_rejects_duplicate_keys(tmp_path: Path):
    path = tmp_path / "result.json"
    path.write_text('{"schema_version":"1","schema_version":"1"}')
    with pytest.raises(BenchmarkResultError):
        parse_benchmark_comparison_result(path)


def test_result_evidence_binding_checks_declared_file(tmp_path: Path):
    plan = _plan()
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    payload = b'{"arm":"sky","status":"completed"}\n'
    (evidence_root / "sky.json").write_bytes(payload)
    (evidence_root / "llm4ad.json").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    from famou.benchmark_result import bind_benchmark_comparison_result_evidence
    arms = tuple(
        ComparisonArmResult(a.id, "completed", 10, 2, 1, 0.5, digest, f"{a.id}.json", len(payload))
        for a in plan.arms
    )
    from famou import benchmark_result as module
    result = BenchmarkComparisonResult(plan.comparison_id, module._result_id(plan.comparison_id, arms), arms)
    assert bind_benchmark_comparison_result_evidence(result, plan, evidence_root) == result


def test_result_evidence_binding_rejects_missing_or_changed_file(tmp_path: Path):
    plan = _plan()
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    payload = b"evidence"
    (evidence_root / "sky.json").write_bytes(payload)
    (evidence_root / "llm4ad.json").write_bytes(b"changed")
    digest = hashlib.sha256(payload).hexdigest()
    arms = tuple(
        ComparisonArmResult(a.id, "completed", 10, 2, 1, 0.5, digest, f"{a.id}.json", len(payload))
        for a in plan.arms
    )
    from famou import benchmark_result as module
    result = BenchmarkComparisonResult(plan.comparison_id, module._result_id(plan.comparison_id, arms), arms)
    from famou.benchmark_result import (
        BenchmarkResultError,
        bind_benchmark_comparison_result_evidence,
    )
    with pytest.raises(BenchmarkResultError, match="benchmark_result_evidence_changed"):
        bind_benchmark_comparison_result_evidence(result, plan, evidence_root)


def test_result_evidence_binding_rejects_symlink_and_traversal(tmp_path: Path):
    plan = _plan()
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"evidence")
    (evidence_root / "sky.json").symlink_to(outside)
    payload = b"evidence"
    (evidence_root / "llm4ad.json").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    arms = (
        ComparisonArmResult("sky", "completed", 10, 2, 1, 0.5, digest, "sky.json", len(payload)),
        ComparisonArmResult("llm4ad", "completed", 10, 2, 1, 0.5, digest, "llm4ad.json", len(payload)),
    )
    from famou import benchmark_result as module
    result = BenchmarkComparisonResult(plan.comparison_id, module._result_id(plan.comparison_id, arms), arms)
    from famou.benchmark_result import (
        BenchmarkResultError,
        bind_benchmark_comparison_result_evidence,
    )
    with pytest.raises(BenchmarkResultError, match="benchmark_result_evidence_unsafe"):
        bind_benchmark_comparison_result_evidence(result, plan, evidence_root)


def test_cli_validates_plan_and_result_without_initializing_home(tmp_path: Path, monkeypatch, capsys):
    contract = AlgorithmProblemContract.from_dict({
        "schema_version": "1", "problem_id": "benchmark-fixture", "problem_type": "routing",
        "statement": "fixture", "inputs": [{"path": "task.json", "format": "json", "fields": {"items": "items"}}],
        "decision_variables": ["value"], "objective": {"name": "quality", "direction": "maximize"},
        "hard_constraints": [], "soft_constraints": [], "success_criteria": ["valid"],
        "deliverables": ["candidate source"], "evolution": {"strategy": "population", "max_rounds": 1, "stagnation_rounds": 1},
    })
    contract_path = tmp_path / "contract.json"; contract_path.write_text(json.dumps(contract.to_dict()))
    input_root = tmp_path / "inputs"; input_root.mkdir(); (input_root / "task.json").write_bytes(b'{"items":[1]}')
    from famou.benchmark_task import BenchmarkTaskEnvelope
    envelopes = {name: BenchmarkTaskEnvelope.from_dict({**item.to_dict(), "contract_sha256": contract.digest()}) for name, item in (("sky", env()), ("llm4ad", env("llm4ad")))}
    plan = BenchmarkComparisonPlan.from_envelopes(envelopes)
    result = _result(plan)
    plan_path = tmp_path / "plan.json"; plan_path.write_text(json.dumps(plan.to_dict()))
    result_path = tmp_path / "result.json"; result_path.write_text(json.dumps(result.to_dict()))
    monkeypatch.setattr(cli, "_config", lambda *_args, **_kwargs: pytest.fail("initialized home"))
    assert cli.main(["benchmark-comparison", "validate-result", str(plan_path), str(result_path), "--contract", str(contract_path), "--input-root", str(input_root), "--model-profile-sha256", "d" * 64, "--evaluator-fingerprint", "b" * 64, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["arm_count"] == 2


def test_cli_evidence_root_binds_descriptor_receipts(tmp_path: Path, monkeypatch, capsys):
    contract = AlgorithmProblemContract.from_dict({
        "schema_version": "1", "problem_id": "benchmark-fixture", "problem_type": "routing",
        "statement": "fixture", "inputs": [{"path": "task.json", "format": "json", "fields": {"items": "items"}}],
        "decision_variables": ["value"], "objective": {"name": "quality", "direction": "maximize"},
        "hard_constraints": [], "soft_constraints": [], "success_criteria": ["valid"],
        "deliverables": ["candidate source"], "evolution": {"strategy": "population", "max_rounds": 1, "stagnation_rounds": 1},
    })
    contract_path = tmp_path / "contract.json"; contract_path.write_text(json.dumps(contract.to_dict()))
    input_root = tmp_path / "inputs"; input_root.mkdir(); (input_root / "task.json").write_bytes(b'{"items":[1]}')
    evidence_root = tmp_path / "evidence"; evidence_root.mkdir()
    evidence = b"arm evidence\n"
    digest = hashlib.sha256(evidence).hexdigest()
    for arm_id in ("sky", "llm4ad"):
        (evidence_root / f"{arm_id}.json").write_bytes(evidence)
    from famou.benchmark_task import BenchmarkTaskEnvelope
    envelopes = {name: BenchmarkTaskEnvelope.from_dict({**item.to_dict(), "contract_sha256": contract.digest()}) for name, item in (("sky", env()), ("llm4ad", env("llm4ad")))}
    plan = BenchmarkComparisonPlan.from_envelopes(envelopes)
    arms = tuple(ComparisonArmResult(a.id, "completed", 10, 2, 1, 0.5, digest, f"{a.id}.json", len(evidence)) for a in plan.arms)
    from famou import benchmark_result as module
    result = BenchmarkComparisonResult(plan.comparison_id, module._result_id(plan.comparison_id, arms), arms)
    plan_path = tmp_path / "plan.json"; plan_path.write_text(json.dumps(plan.to_dict()))
    result_path = tmp_path / "result.json"; result_path.write_text(json.dumps(result.to_dict()))
    monkeypatch.setattr(cli, "_config", lambda *_args, **_kwargs: pytest.fail("initialized home"))
    assert cli.main(["benchmark-comparison", "validate-result", str(plan_path), str(result_path), "--contract", str(contract_path), "--input-root", str(input_root), "--model-profile-sha256", "d" * 64, "--evaluator-fingerprint", "b" * 64, "--evidence-root", str(evidence_root), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["evidence_bound"] is True
