"""Protocol regressions for independent evaluation and modest descriptor limits."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
import test_candidate_evaluation as integration

from lunar_evolution.candidate_evaluation import (
    evaluate_candidate_execution,
    inspect_candidate_evaluation,
)
from lunar_evolution.candidate_evaluation_spec import (
    CandidateEvaluationError,
    CandidateEvaluationSpec,
    canonical_json,
    parse_candidate_evaluation_spec,
)


def _descriptor(path):
    content = path.read_bytes()
    info = path.stat()
    return {
        "size": len(content), "sha256": hashlib.sha256(content).hexdigest(),
        "device": info.st_dev, "inode": info.st_ino,
    }


@pytest.mark.parametrize("content", [b"\xff", b"print(0)\x00"], ids=["invalid-utf8", "nul"])
def test_inspection_rejects_invalid_harness_text_even_when_all_record_hashes_match(tmp_path, content):
    admission, request = integration.fixture(tmp_path)
    result = evaluate_candidate_execution(admission, **request)
    path = result.evaluation_path
    retained_request = json.loads((path / "request.json").read_bytes())
    manifest = json.loads((path / "evaluation.json").read_bytes())

    # Rebind all local commitments to the changed bytes. The text protocol itself must still
    # reject them, independently of the optional caller pin and the byte-integrity checks.
    (path / "evaluator.py").write_bytes(content)
    retained_request["evaluator"].update(
        harness_sha256=hashlib.sha256(content).hexdigest(), harness_size=len(content),
    )
    spec = parse_candidate_evaluation_spec(retained_request["evaluator"])
    retained_request["binding"]["evaluator_fingerprint"] = spec.digest()
    (path / "request.json").write_bytes(canonical_json(retained_request))
    manifest["binding"] = retained_request["binding"]
    for name in ("request.json", "evaluator.py"):
        manifest["files"][name] = _descriptor(path / name)
    (path / "evaluation.json").write_bytes(canonical_json(manifest))

    with pytest.raises(CandidateEvaluationError, match="^candidate_evaluation_harness_changed$"):
        inspect_candidate_evaluation(path)


@pytest.mark.parametrize("content", [None, b"not-json"], ids=["missing", "malformed"])
def test_invalid_output_is_scored_without_requiring_the_unused_interpreter(tmp_path, monkeypatch, content):
    def evaluator_spec(*args, **kwargs):
        return replace(
            CandidateEvaluationSpec(*args, **kwargs),
            command=(str(tmp_path / "unavailable-interpreter"),),
        )

    monkeypatch.setattr(integration, "CandidateEvaluationSpec", evaluator_spec)
    admission, request = integration.fixture(tmp_path)
    output = request["workspace_path"] / "output/result.json"
    if content is None:
        output.unlink()
    else:
        output.write_bytes(content)

    result = evaluate_candidate_execution(admission, **request)
    assert result.report.validity == 0
    assert result.report.combined_score == 0
    assert result.to_dict()["harness_invoked"] is False
    assert result.to_dict()["output_contract_valid"] is False
    assert (request["workspace_path"] / "count").read_text() == "x"
    assert inspect_candidate_evaluation(result.evaluation_path) == result


def test_evaluate_and_inspect_work_under_128_file_descriptors_in_an_isolated_process(tmp_path):
    pytest.importorskip("resource")
    repository = Path(__file__).resolve().parents[1]
    script = """import resource, sys
from pathlib import Path
from test_candidate_evaluation import fixture
from lunar_evolution.candidate_evaluation import evaluate_candidate_execution, inspect_candidate_evaluation
_, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
if hard != resource.RLIM_INFINITY and hard < 128:
    raise SystemExit(77)
resource.setrlimit(resource.RLIMIT_NOFILE, (128, hard))
admission, request = fixture(Path(sys.argv[1]))
result = evaluate_candidate_execution(admission, **request)
assert result.report.validity == 1 and result.report.combined_score == 9
assert inspect_candidate_evaluation(result.evaluation_path) == result
assert (request['workspace_path'] / 'count').read_text() == 'x'
print('ok')
"""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join((str(repository / "src"), str(repository / "tests")))
    completed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)], cwd=repository,
        env=environment, capture_output=True, text=True, timeout=20, check=False,
    )
    if completed.returncode == 77:
        pytest.skip("host hard descriptor limit is below 128")
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "ok\n"


@pytest.mark.parametrize(("harness", "timeout", "error"), [
    (b'import os; os.write(1, b"\\xff")\n', 2, "report_invalid"),
    (b"raise SystemExit(7)\n", 2, "process_failed"),
    (b"import time; time.sleep(1)\n", 0.05, "process_timed_out"),
    (b'import os; os.write(1, b"x" * 32769)\n', 2, "output_limit_exceeded"),
    (b'import os; os.write(2, b"x" * 32769)\n', 2, "output_limit_exceeded"),
], ids=["invalid-report-utf8", "nonzero-exit", "timeout", "stdout-overflow", "stderr-overflow"])
def test_real_harness_failures_preserve_an_incomplete_evaluation(tmp_path, monkeypatch, harness, timeout, error):
    def evaluator_spec(*args, **kwargs):
        return replace(CandidateEvaluationSpec(*args, **kwargs), timeout_seconds=timeout)

    monkeypatch.setattr(integration, "CandidateEvaluationSpec", evaluator_spec)
    admission, request = integration.fixture(tmp_path, harness=harness)
    with pytest.raises(CandidateEvaluationError, match=f"^candidate_evaluation_{error}$"):
        evaluate_candidate_execution(admission, **request)
    paths = list(request["evaluation_root"].iterdir())
    assert len(paths) == 1
    assert not (paths[0] / "evaluation.json").exists()
    with pytest.raises(CandidateEvaluationError, match="^candidate_evaluation_incomplete$"):
        inspect_candidate_evaluation(paths[0])
    assert (request["workspace_path"] / "count").read_text() == "x"


@pytest.mark.parametrize(("format_name", "content", "fields", "valid"), [
    ("csv", b"value,other\n9,x\n", ["value"], True),
    ("csv", b"other\n9\n", ["value"], False),
    ("jsonl", b'{"value":9}\n{"value":10}\n', ["value"], True),
    ("jsonl", b'{"value":9}\n{"other":10}\n', ["value"], False),
    ("jsonl", b'{"value":9,"value":10}\n', ["value"], False),
    ("jsonl", b'{"value":NaN}\n', ["value"], False),
    ("text", "可复现结果\n".encode(), [], True),
    ("text", b"", [], False),
    ("text", b"\xff", [], False),
], ids=["csv-valid", "csv-field-missing", "jsonl-valid", "jsonl-field-missing",
        "jsonl-duplicate", "jsonl-nonfinite", "text-valid", "text-empty", "text-invalid-utf8"])
def test_declared_output_formats_control_whether_the_harness_is_invoked(
    tmp_path, format_name, content, fields, valid,
):
    report = {
        "schema_version": "1", "evaluator_id": "exact", "validity": 1, "quality": None,
        "combined_score": 9, "detailed_scores": {}, "error_info": [],
    }
    harness = ("print(" + repr(json.dumps(report)) + ")\n").encode()
    target = f"output/result.{format_name}"
    admission, request = integration.fixture(
        tmp_path, harness=harness,
        outputs=[{"path": target, "format": format_name, "fields": fields}],
    )
    (request["workspace_path"] / target).write_bytes(content)
    result = evaluate_candidate_execution(admission, **request)
    assert result.to_dict()["output_contract_valid"] is valid
    assert result.to_dict()["harness_invoked"] is valid
    assert result.report.validity == int(valid)
    assert result.report.combined_score == (9 if valid else 0)
    assert inspect_candidate_evaluation(result.evaluation_path) == result
    assert (result.evaluation_path / target).read_bytes() == content
    assert (request["workspace_path"] / "count").read_text() == "x"
