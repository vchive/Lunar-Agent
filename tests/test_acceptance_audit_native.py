"""Static native evidence fixtures: no candidate, evaluator, or provider is executed."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_candidate_execution_evidence import fixture as execution_fixture

from lunar_evolution import candidate_evaluation as evaluation_module
from lunar_evolution import candidate_execution_evidence as evidence
from lunar_evolution._candidate_workspace_io import DirectoryChain
from lunar_evolution.acceptance_audit import _NativeAudit
from lunar_evolution.algorithm import AlgorithmProblemContract, EvaluationReport
from lunar_evolution.candidate_bundle import CandidateSourceBundle, CandidateSourceFile
from lunar_evolution.candidate_evaluation import inspect_candidate_evaluation
from lunar_evolution.candidate_evaluation_spec import (
    CandidateEvaluationSpec,
    candidate_output_contract_sha256,
    canonical_json,
)
from lunar_evolution.candidate_execution import (
    CandidateExecutionBudget,
    CandidateExecutionInput,
    build_candidate_execution_admission,
)
from lunar_evolution.candidate_execution_cleanup import build_candidate_execution_cleanup
from lunar_evolution.candidate_execution_evidence import inspect_candidate_execution_record
from lunar_evolution.candidate_workspace_plan import build_candidate_workspace_plan
from lunar_evolution.controller import LocalController


def _sha(content):
    return hashlib.sha256(content).hexdigest()


@pytest.fixture(autouse=True)
def no_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("native audit fixture attempted execution")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(evidence, "run_candidate_execution", forbidden)
    monkeypatch.setattr(evidence, "run_candidate_execution_recorded", forbidden)
    monkeypatch.setattr(evaluation_module, "evaluate_candidate_execution", forbidden)
    monkeypatch.setattr(evaluation_module, "_bounded_process_bytes", forbidden)
    monkeypatch.setattr(LocalController, "__init__", forbidden)


def _tree(root):
    return {
        path.relative_to(root).as_posix(): (
            path.stat().st_ino, path.stat().st_mode, path.stat().st_mtime_ns,
            path.stat().st_ctime_ns, path.read_bytes() if path.is_file() else None,
        )
        for path in (root, *sorted(root.rglob("*")))
    }


def _write_execution(admission, request, *, outcome="succeeded", complete=True, cleanup=False):
    plan, admission, binding = evidence._request(admission, request["plan"], {})
    attempt = request["attempt_path"]
    attempt.mkdir()
    chain = DirectoryChain(attempt, "fixture_unsafe")
    try:
        intent, intent_descriptor = evidence._write(chain, "launch-intent.json", {
            "protocol": "lunar-candidate-execution-launch-intent-v1", "schema_version": "1",
            "binding": binding, "workspace_identity": evidence._node(request["workspace_path"].stat()),
            "input_identity": evidence._node(request["input_path"].stat()),
            "attempt_identity": evidence._node(os.fstat(chain.fd)), "nonce": "f" * 64,
        })
        if complete:
            native = {
                "admission_sha256": admission.digest(), "workspace_plan_sha256": plan.digest(),
                "bundle_sha256": plan.bundle_sha256, "input_count": len(admission.inputs),
                "total_input_bytes": sum(item.size for item in admission.inputs),
                "entrypoint": plan.entrypoint, "status": outcome,
                "execution": {"status": outcome, "exit_code": 0 if outcome == "succeeded" else 7,
                              "duration_ms": 1, "stdout_bytes": 0, "stderr_bytes": 0,
                              "error": None if outcome == "succeeded" else "process_failed"},
            }
            result_bytes, result_descriptor = evidence._write(chain, "result.json", {
                "protocol": "lunar-candidate-execution-result-v1", "schema_version": "1",
                "launch_intent_sha256": _sha(intent), "runner_result": native,
                "runner_result_sha256": _sha(evidence._encode(native)),
            })
            cleanup_descriptor = None
            if cleanup:
                cleanup_value = build_candidate_execution_cleanup({
                    "protocol": "lunar-candidate-execution-cleanup-v1", "schema_version": "1",
                    "launch_intent_sha256": _sha(intent), "result_sha256": _sha(result_bytes),
                    "native_exit_code": 0, "process_exit_code": 0,
                    "observer_identity": {"pid": 101, "pgid": 101},
                    "release_identity": {"pid": 101, "pgid": 101},
                    "group_probe": "absent", "ownership_release": "observed",
                    "cleanup": "verified", "observed_ms": 1,
                })
                _, cleanup_descriptor = evidence._write(chain, "cleanup.json", cleanup_value)
            evidence._write(chain, "completed.json", {
                "protocol": "lunar-candidate-execution-completion-v1", "schema_version": "1",
                "launch_intent": intent_descriptor, "result": result_descriptor,
                **({"cleanup": cleanup_descriptor} if cleanup_descriptor is not None else {}),
            })
    finally:
        chain.close()
    return inspect_candidate_execution_record(attempt, plan=plan, admission=admission)


def _auditor(root, admission, request, record):
    plan = request["plan"]
    (root / "plan.json").write_bytes(canonical_json(plan.to_dict()))
    (root / "admission.json").write_bytes(canonical_json(admission.to_dict()))
    audit = _NativeAudit({
        "identities": {"child_run_id": "child", "candidate_id": "candidate"},
        "pins": {"plan_sha256": plan.digest(), "admission_sha256": admission.digest(),
                 "bundle_sha256": plan.bundle_sha256, "contract_sha256": plan.contract_sha256,
                 "completion_sha256": record.completion_sha256 or "0" * 64},
        "manifest": {"input_sha256": _sha(canonical_json([i.to_dict() for i in admission.inputs]))},
        "paths": {"plan": "plan.json", "admission": "admission.json", "execution": "attempt",
                  "evaluation": "evaluation"},
    }, None, root, [])
    audit.child = SimpleNamespace(workspace=root, id="child")
    return audit


def test_native_successful_record_preserves_unknown_cleanup_without_execution(tmp_path):
    admission, request = execution_fixture(tmp_path, script=b"this source must remain data\n")
    record = _write_execution(admission, request)
    assert record.status == "recorded"
    assert record.to_dict()["runner_result"]["status"] == "succeeded"
    audit = _auditor(tmp_path.resolve(), admission, request, record)
    before = _tree(tmp_path)
    result = audit.capture("execution")
    assert result["status"] == "unverifiable"
    assert result["reason"] == "execution_cleanup_unknown"
    assert audit.record == record and audit.plan == request["plan"]
    assert audit.capture("execution") == result
    assert _tree(tmp_path) == before
    assert not (request["workspace_path"] / "count").exists()


def test_native_verified_cleanup_promotes_execution_only(tmp_path):
    admission, request = execution_fixture(tmp_path)
    record = _write_execution(admission, request, cleanup=True)
    assert record.cleanup_status == "verified"
    audit = _auditor(tmp_path.resolve(), admission, request, record)
    result = audit.capture("execution")
    assert result["status"] == "verified"
    assert result["verified_digests"]["cleanup_sha256"] == record.cleanup_sha256


def test_byte_identical_relocated_native_attempt_is_not_verified(tmp_path):
    admission, request = execution_fixture(tmp_path)
    record = _write_execution(admission, request)
    audit = _auditor(tmp_path.resolve(), admission, request, record)
    relocated = tmp_path / "copied-attempt"
    shutil.copytree(request["attempt_path"], relocated)
    audit.paths["execution"] = relocated.name
    assert {p.name: p.read_bytes() for p in relocated.iterdir()} == {
        p.name: p.read_bytes() for p in request["attempt_path"].iterdir()
    }
    before = _tree(tmp_path)
    with pytest.raises(evidence.CandidateExecutionEvidenceError, match="identity_mismatch"):
        inspect_candidate_execution_record(relocated, admission=admission, plan=request["plan"])
    result = audit.capture("execution")
    assert result["status"] == "unverifiable"
    assert result["reason"] == "execution_evidence_unverifiable"
    assert audit.record is None
    assert _tree(tmp_path) == before


@pytest.mark.parametrize("outcome,complete,status,reason", [
    ("failed", True, "failed", "execution_failed"),
    ("succeeded", False, "unverifiable", "execution_evidence_unverifiable"),
])
def test_native_failed_and_uncertain_records_do_not_promote(tmp_path, outcome, complete, status, reason):
    admission, request = execution_fixture(tmp_path)
    record = _write_execution(admission, request, outcome=outcome, complete=complete)
    assert record.status == ("recorded" if complete else "uncertain")
    audit = _auditor(tmp_path.resolve(), admission, request, record)
    before = _tree(tmp_path)
    result = audit.capture("execution")
    assert result["status"] == status and result["reason"] == reason
    assert audit.record is None
    assert _tree(tmp_path) == before


def _scoring_fixture(root, *, valid=1):
    root = root.resolve()
    workspace, inputs = root / "workspace", root / "inputs"
    workspace.mkdir()
    inputs.mkdir()
    source, harness, input_bytes, output_bytes = b"source stays data\n", b"harness stays data\n", b"3", b'{"value":9}'
    (workspace / "main.py").write_bytes(source)
    (inputs / "value").write_bytes(input_bytes)
    contract = AlgorithmProblemContract.from_dict({
        "schema_version": "1", "problem_id": "native-audit", "problem_type": "continuous",
        "statement": "Square the input.", "inputs": [{"path": "value", "format": "text", "fields": {"value": "integer"}}],
        "decision_variables": ["value"], "objective": {"name": "value", "direction": "maximize"},
        "hard_constraints": [], "soft_constraints": [], "success_criteria": ["Correct square"],
        "deliverables": ["output/result.json"], "assumptions": [],
        "outputs": [{"path": "output/result.json", "format": "json", "fields": ["value"]}],
    })
    bundle = CandidateSourceBundle(contract.digest(), "main.py", (
        CandidateSourceFile("main.py", len(source), _sha(source)),
    ))
    plan = build_candidate_workspace_plan(
        bundle, command=(str(Path(sys.executable).resolve()),), contract_sha256=contract.digest(),
        timeout_seconds=2, max_output_bytes=1024,
    )
    evaluator = CandidateEvaluationSpec(_sha(harness), len(harness), (str(Path(sys.executable).resolve()), "-I"))
    admission = build_candidate_execution_admission(
        plan, inputs=(CandidateExecutionInput("value", "fixture", len(input_bytes), _sha(input_bytes)),),
        dependency_sha256="b" * 64, environment_sha256="c" * 64, evaluator=evaluator.pin(),
        output_contract_sha256=candidate_output_contract_sha256(contract.outputs),
        budget=CandidateExecutionBudget(2, 1024, 1024, 1),
    )
    request = {"plan": plan, "workspace_path": workspace, "input_path": inputs, "attempt_path": root / "attempt"}
    record = _write_execution(admission, request)
    audit = _auditor(root, admission, request, record)
    audit.contract, audit.pipeline = contract, SimpleNamespace(evaluator=evaluator)
    _, _, binding = evidence._request(admission, plan, {})
    binding.update({"launch_intent_sha256": record.launch_intent_sha256, "completion_sha256": record.completion_sha256,
                    "evaluator_fingerprint": evaluator.digest(), "output_contract_sha256": admission.output_contract_sha256})
    evaluation = root / "evaluation"
    evaluation.mkdir()
    report = EvaluationReport.from_dict({
        "schema_version": "1", "evaluator_id": evaluator.evaluator_id, "validity": valid,
        "quality": None, "combined_score": 9.0 if valid else 0.0, "detailed_scores": {},
        "error_info": [] if valid else [{"code": "incorrect", "message": "Incorrect output."}],
    }).to_dict()
    files = {
        "request.json": canonical_json({
            "protocol": "lunar-candidate-evaluation-request-v1", "schema_version": "1", "observation": "evaluation-time",
            "binding": binding, "contract": contract.to_dict(), "evaluator": evaluator.to_dict(),
            "inputs": [item.to_dict() for item in admission.inputs],
            "outputs": [{"path": "output/result.json", "present": True, "size": len(output_bytes), "sha256": _sha(output_bytes)}],
        }),
        "evaluator.py": harness, "inputs/value": input_bytes,
        "output/result.json": output_bytes, "report.json": canonical_json(report),
    }
    descriptors = {}
    for name, content in files.items():
        path = evaluation / name
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_bytes(content)
        descriptors[name] = {"size": len(content), "sha256": _sha(content), **evidence._node(path.stat())}
    manifest = canonical_json({
        "protocol": "lunar-candidate-evaluation-v1", "schema_version": "1", "observation": "evaluation-time",
        "evaluation_identity": evidence._node(evaluation.stat()), "binding": binding,
        "files": descriptors, "report": report, "output_contract_valid": True, "harness_invoked": True,
    })
    (evaluation / "evaluation.json").write_bytes(manifest)
    audit.pins["evaluation_sha256"] = _sha(manifest)
    result = inspect_candidate_evaluation(evaluation, expected_evaluation_sha256=_sha(manifest))
    assert result.report.validity == valid
    assert audit.capture("execution")["reason"] == "execution_cleanup_unknown"
    return audit, result


def test_native_scoring_snapshot_verifies_without_filling_cleanup_gap(tmp_path):
    audit, result = _scoring_fixture(tmp_path)
    before = _tree(tmp_path)
    boundary = audit.capture("scoring")
    assert boundary["status"] == "verified"
    assert boundary["verified_digests"] == {"evaluation_sha256": result.digest()}
    assert audit.capture("execution")["reason"] == "execution_cleanup_unknown"
    assert _tree(tmp_path) == before


def test_native_invalid_scoring_remains_failed(tmp_path):
    audit, _ = _scoring_fixture(tmp_path, valid=0)
    assert audit.capture("scoring")["reason"] == "evaluation_invalid"
    assert audit.capture("scoring")["status"] == "failed"
    assert audit.evaluation is None


@pytest.mark.parametrize("name", ["evaluator.py", "inputs/value", "output/result.json", "report.json"])
def test_native_changed_evaluation_files_are_unverifiable(tmp_path, name):
    audit, _ = _scoring_fixture(tmp_path)
    path = tmp_path / "evaluation" / name
    path.write_bytes(path.read_bytes() + b" ")
    before = _tree(tmp_path)
    assert audit.capture("scoring")["status"] == "unverifiable"
    assert audit.evaluation is None
    assert _tree(tmp_path) == before


def test_native_relocated_evaluation_snapshot_is_unverifiable(tmp_path):
    audit, _ = _scoring_fixture(tmp_path)
    shutil.copytree(tmp_path / "evaluation", tmp_path / "copied-evaluation")
    audit.paths["evaluation"] = "copied-evaluation"
    before = _tree(tmp_path)
    assert audit.capture("scoring")["status"] == "unverifiable"
    assert audit.evaluation is None
    assert _tree(tmp_path) == before
