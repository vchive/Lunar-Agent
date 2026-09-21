"""Local source structure checks remain independent from the output evaluator."""
from __future__ import annotations

import hashlib
import json
import shutil
from types import SimpleNamespace

import pytest
import test_candidate_evaluation as integration

from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.candidate_evaluation import (
    evaluate_candidate_execution,
    inspect_candidate_evaluation,
)
from lunar_evolution.candidate_evaluation_spec import CandidateEvaluationError, canonical_json


def _constraint(minimum=2, **changes):
    return {
        "id": "two_python_files", "description": "Deliver at least two Python source files.",
        "source": "user_confirmed", "verification": "independent", "result_fields": [],
        "verification_scope": "source",
        "source_check": {"kind": "python_file_count", "minimum": minimum},
        **changes,
    }


def _fixture(tmp_path, monkeypatch, *, minimum=2, hard=None, soft=None, harness=None):
    def contract(value):
        return AlgorithmProblemContract.from_dict({
            **value, "hard_constraints": [_constraint(minimum)] if hard is None else hard,
            "soft_constraints": [] if soft is None else soft,
        })

    with monkeypatch.context() as patch:
        patch.setattr(integration, "AlgorithmProblemContract", SimpleNamespace(from_dict=contract))
        return integration.fixture(tmp_path, harness=harness)


def _descriptor(path):
    data, info = path.read_bytes(), path.stat()
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "device": info.st_dev, "inode": info.st_ino}


def _rewrite(path, name, value, manifest):
    (path / name).write_bytes(canonical_json(value))
    manifest["files"][name] = _descriptor(path / name)
    (path / "evaluation.json").write_bytes(canonical_json(manifest))


def test_passing_source_check_is_retained_without_exposing_evidence_to_harness(tmp_path, monkeypatch):
    harness = b'from pathlib import Path\nassert not Path("source-checks.json").exists()\n' + integration.HARNESS
    admission, request = _fixture(tmp_path, monkeypatch, harness=harness)
    result = evaluate_candidate_execution(admission, **request)

    assert result.report.validity == 1 and result.report.combined_score == 9
    assert result.to_dict()["source_constraints_valid"] is True
    assert result.to_dict()["harness_invoked"] is True
    manifest = json.loads((result.evaluation_path / "evaluation.json").read_bytes())
    assert manifest["protocol"] == "lunar-candidate-evaluation-source-v1"
    retained = json.loads((result.evaluation_path / "source-checks.json").read_bytes())
    assert retained["bundle"] == request["plan"].bundle.to_dict()
    assert retained["checks"] == [{"id": "two_python_files", "kind": "python_file_count",
                                   "minimum": 2, "observed": 2, "passed": True}]
    assert not (result.evaluation_path / "solve").exists()
    assert (request["workspace_path"] / "count").read_text() == "x"
    shutil.rmtree(request["workspace_path"])
    assert inspect_candidate_evaluation(result.evaluation_path, expected_evaluation_sha256=result.digest()) == result


def test_failed_source_check_prevents_output_harness_and_retains_invalid_report(tmp_path, monkeypatch):
    admission, request = _fixture(
        tmp_path, monkeypatch, minimum=3, harness=b'raise RuntimeError("must not run")\n',
    )
    result = evaluate_candidate_execution(admission, **request)
    assert result.report.validity == 0 and result.report.combined_score == 0
    assert result.report.quality is None
    assert result.to_dict()["source_constraints_valid"] is False
    assert result.to_dict()["output_contract_valid"] is True
    assert result.to_dict()["harness_invoked"] is False
    assert "two_python_files" in json.dumps(result.report.error_info)
    assert inspect_candidate_evaluation(result.evaluation_path) == result


def test_harness_cannot_publish_its_own_source_check_evidence(tmp_path, monkeypatch):
    harness = (b'from pathlib import Path\nPath("source-checks.json").write_text("{}")\n'
               + integration.HARNESS)
    admission, request = _fixture(tmp_path, monkeypatch, harness=harness)
    with pytest.raises(CandidateEvaluationError):
        evaluate_candidate_execution(admission, **request)
    paths = list(request["evaluation_root"].iterdir())
    assert len(paths) == 1
    assert not (paths[0] / "evaluation.json").exists()


def test_undeclared_python_files_do_not_satisfy_source_check(tmp_path, monkeypatch):
    admission, request = _fixture(tmp_path, monkeypatch, minimum=3)
    (request["workspace_path"] / "undeclared.py").write_text("# Not in the source bundle.\n")
    result = evaluate_candidate_execution(admission, **request)
    assert result.to_dict()["source_constraints_valid"] is False
    retained = json.loads((result.evaluation_path / "source-checks.json").read_bytes())
    assert retained["checks"][0]["observed"] == 2


def test_source_checks_use_verified_bytes_not_only_a_declared_file_count(tmp_path, monkeypatch):
    admission, request = _fixture(tmp_path, monkeypatch)
    (request["workspace_path"] / "solve/helper.py").write_text("# Changed since execution.\n")
    with pytest.raises(CandidateEvaluationError, match="source_changed"):
        evaluate_candidate_execution(admission, **request)
    assert list(request["evaluation_root"].iterdir()) == []


@pytest.mark.parametrize("minimum", [2, 3])
def test_output_failure_takes_precedence_and_retains_source_evidence(tmp_path, monkeypatch, minimum):
    admission, request = _fixture(tmp_path, monkeypatch, minimum=minimum)
    (request["workspace_path"] / "output/result.json").write_text("invalid-json")
    result = evaluate_candidate_execution(admission, **request)
    assert result.to_dict()["harness_invoked"] is False
    assert result.to_dict()["source_constraints_valid"] is (minimum == 2)
    assert result.report.error_info[0]["code"] == "output_contract_failed"
    assert inspect_candidate_evaluation(result.evaluation_path) == result


@pytest.mark.parametrize("scope", ["source", "execution"])
def test_unsupported_scope_fails_before_evaluation_io(tmp_path, monkeypatch, scope):
    constraint = _constraint(verification_scope=scope)
    del constraint["source_check"]
    admission, request = _fixture(tmp_path, monkeypatch, hard=[constraint])
    with pytest.raises(CandidateEvaluationError, match="unsupported_constraints"):
        evaluate_candidate_execution(admission, **request)
    assert list(request["evaluation_root"].iterdir()) == []


def test_unsupported_soft_source_fails_before_evaluation_io(tmp_path, monkeypatch):
    constraint = _constraint()
    del constraint["source_check"]
    admission, request = _fixture(tmp_path, monkeypatch, hard=[], soft=[constraint])
    with pytest.raises(CandidateEvaluationError, match="unsupported_constraints"):
        evaluate_candidate_execution(admission, **request)
    assert list(request["evaluation_root"].iterdir()) == []


@pytest.mark.parametrize("field", ["observed", "minimum", "passed", "id", "kind", "validity", "unknown"])
def test_inspection_recomputes_source_evidence_even_if_its_descriptor_is_rebound(tmp_path, monkeypatch, field):
    admission, request = _fixture(tmp_path, monkeypatch)
    result = evaluate_candidate_execution(admission, **request)
    path = result.evaluation_path
    manifest = json.loads((path / "evaluation.json").read_bytes())
    retained = json.loads((path / "source-checks.json").read_bytes())
    if field in {"validity", "unknown"}:
        retained[field] = False
    else:
        retained["checks"][0][field] = {
            "observed": 3, "minimum": 1, "passed": False, "id": "other", "kind": "all_files",
        }[field]
    _rewrite(path, "source-checks.json", retained, manifest)
    with pytest.raises(CandidateEvaluationError, match="source_constraints_invalid"):
        inspect_candidate_evaluation(path)


@pytest.mark.parametrize("field", ["bundle_sha256", "source_file_table_sha256"])
def test_inspection_binds_source_evidence_to_the_request(tmp_path, monkeypatch, field):
    admission, request = _fixture(tmp_path, monkeypatch)
    result = evaluate_candidate_execution(admission, **request)
    path = result.evaluation_path
    manifest = json.loads((path / "evaluation.json").read_bytes())
    retained = json.loads((path / "request.json").read_bytes())
    retained["binding"][field] = "0" * 64
    manifest["binding"] = retained["binding"]
    _rewrite(path, "request.json", retained, manifest)
    with pytest.raises(CandidateEvaluationError):
        inspect_candidate_evaluation(path)


def test_inspection_rejects_a_forged_success_report_for_failed_source_check(tmp_path, monkeypatch):
    admission, request = _fixture(tmp_path, monkeypatch, minimum=3)
    result = evaluate_candidate_execution(admission, **request)
    path = result.evaluation_path
    manifest = json.loads((path / "evaluation.json").read_bytes())
    report = result.report.to_dict()
    report.update(validity=1, quality=None, combined_score=999, error_info=[])
    manifest["report"] = report
    _rewrite(path, "report.json", report, manifest)
    with pytest.raises(CandidateEvaluationError, match="identity_mismatch"):
        inspect_candidate_evaluation(path)


@pytest.mark.parametrize("change", ["downgrade", "missing", "flag", "invoked"])
def test_inspection_rejects_source_check_bypass(tmp_path, monkeypatch, change):
    admission, request = _fixture(tmp_path, monkeypatch, minimum=3)
    result = evaluate_candidate_execution(admission, **request)
    path = result.evaluation_path
    manifest = json.loads((path / "evaluation.json").read_bytes())
    if change in {"downgrade", "missing"}:
        (path / "source-checks.json").unlink()
        del manifest["files"]["source-checks.json"]
    if change == "downgrade":
        manifest["protocol"] = "lunar-candidate-evaluation-v1"
        del manifest["source_constraints_valid"]
    elif change == "flag":
        manifest["source_constraints_valid"] = True
    elif change == "invoked":
        manifest["harness_invoked"] = True
    (path / "evaluation.json").write_bytes(canonical_json(manifest))
    with pytest.raises(CandidateEvaluationError):
        inspect_candidate_evaluation(path)


def test_legacy_record_shape_stays_unchanged_when_no_source_checks_exist(tmp_path):
    admission, request = integration.fixture(tmp_path)
    result = evaluate_candidate_execution(admission, **request)
    manifest = json.loads((result.evaluation_path / "evaluation.json").read_bytes())
    assert manifest["protocol"] == "lunar-candidate-evaluation-v1"
    assert "source_constraints_valid" not in manifest
    assert "source_constraints_valid" not in result.to_dict()
    assert "source-checks.json" not in manifest["files"]
    assert set(manifest) == {"protocol", "schema_version", "observation", "evaluation_identity",
                             "binding", "files", "report", "output_contract_valid", "harness_invoked"}
    assert inspect_candidate_evaluation(result.evaluation_path) == result
