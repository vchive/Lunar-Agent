"""Real local candidate/harness integration without a provider or external framework."""
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.candidate_bundle import CandidateSourceBundle, CandidateSourceFile
from lunar_evolution.candidate_evaluation import (
    evaluate_candidate_execution,
    inspect_candidate_evaluation,
)
from lunar_evolution.candidate_evaluation_spec import (
    CandidateEvaluationError,
    CandidateEvaluationSpec,
    candidate_output_contract_sha256,
)
from lunar_evolution.candidate_execution import (
    CandidateExecutionBudget,
    CandidateExecutionInput,
    build_candidate_execution_admission,
)
from lunar_evolution.candidate_execution_evidence import run_candidate_execution_recorded
from lunar_evolution.candidate_workspace_plan import build_candidate_workspace_plan

SOURCE = b'''import json, os
from pathlib import Path
from helper import square
with Path("count").open("a") as file:
    file.write("x")
Path("output").mkdir(exist_ok=True)
value = int((Path(os.environ["LUNAR_CANDIDATE_INPUT_ROOT"]) / "value").read_text())
Path("output/result.json").write_text(json.dumps({"value": square(value)}))
'''
HARNESS = b'''import json, sys
from pathlib import Path
request = json.loads(Path(sys.argv[1]).read_text())
value = int(Path("inputs/value").read_text())
result = json.loads(Path("output/result.json").read_text())["value"]
valid = int(result == value * value)
print(json.dumps({"schema_version": "1", "evaluator_id": "exact", "validity": valid,
    "quality": None, "combined_score": float(result) if valid else 0.0,
    "detailed_scores": {}, "error_info": [] if valid else [{"code":"wrong", "message":"Incorrect square."}]}))
'''


def fixture(tmp_path, script=None, harness=None, outputs=None):
    root = tmp_path.resolve()
    workspace, inputs, evaluations = (root / name for name in ("workspace", "inputs", "evaluations"))
    for directory in (workspace, inputs, evaluations):
        directory.mkdir(parents=True)
    (workspace / "solve").mkdir()
    files = {"solve/main.py": SOURCE if script is None else script,
             "solve/helper.py": b"def square(value):\n    return value * value\n"}
    for name, content in files.items():
        (workspace / name).write_bytes(content)
    (inputs / "value").write_bytes(b"3")
    contract = AlgorithmProblemContract.from_dict({
        "schema_version": "1", "problem_id": "square", "problem_type": "continuous",
        "statement": "Square the input exactly.",
        "inputs": [{"path": "value", "format": "text", "fields": {"value": "integer"}}],
        "decision_variables": ["result value"], "objective": {"name": "value", "direction": "maximize"},
        "hard_constraints": [], "soft_constraints": [], "success_criteria": ["Correct square"],
        "deliverables": ["output/result.json"], "assumptions": [],
        "outputs": outputs if outputs is not None else [{"path": "output/result.json", "format": "json", "fields": ["value"]}],
    })
    bundle = CandidateSourceBundle(contract.digest(), "solve/main.py", tuple(
        CandidateSourceFile(name, len(content), hashlib.sha256(content).hexdigest())
        for name, content in files.items()
    ))
    plan = build_candidate_workspace_plan(
        bundle, command=(str(Path(sys.executable).resolve()),), contract_sha256=contract.digest(),
        timeout_seconds=2, max_output_bytes=1024,
    )
    harness = HARNESS if harness is None else harness
    harness_path = root / "harness.py"
    harness_path.write_bytes(harness)
    evaluator = CandidateEvaluationSpec(
        hashlib.sha256(harness).hexdigest(), len(harness),
        (str(Path(sys.executable).resolve()), "-I"), timeout_seconds=2,
    )
    admission = build_candidate_execution_admission(
        plan, inputs=(CandidateExecutionInput("value", "fixture", 1, hashlib.sha256(b"3").hexdigest()),),
        dependency_sha256="b" * 64, environment_sha256="c" * 64, evaluator=evaluator.pin(),
        output_contract_sha256=candidate_output_contract_sha256(contract.outputs),
        budget=CandidateExecutionBudget(2, 1024, 1024, 1),
    )
    attempt = root / "attempt"
    record = run_candidate_execution_recorded(
        admission, plan=plan, workspace_path=workspace, input_path=inputs, attempt_path=attempt,
    )
    return admission, {
        "plan": plan, "contract": contract, "evaluator": evaluator, "harness_path": harness_path,
        "workspace_path": workspace, "input_path": inputs, "attempt_path": attempt,
        "evaluation_root": evaluations, "expected_completion_sha256": record.completion_sha256,
    }


def test_multifile_score_is_bound_to_retained_snapshot_without_reexecution(tmp_path):
    admission, request = fixture(tmp_path)
    result = evaluate_candidate_execution(admission, **request)
    assert result.status == "evaluated"
    assert result.report.validity == 1 and result.report.combined_score == 9
    assert result.to_dict()["harness_invoked"] is True
    assert result.to_dict()["observation"] == "evaluation-time"
    assert (request["workspace_path"] / "count").read_text() == "x"
    assert (result.evaluation_path / "output/result.json").read_bytes() == b'{"value": 9}'
    assert not (result.evaluation_path / "solve").exists()
    assert str(tmp_path) not in json.dumps(result.to_dict())
    assert inspect_candidate_evaluation(result.evaluation_path, expected_evaluation_sha256=result.digest()) == result
    # Read-only inspection continues after original workspace/input removal or changes.
    (request["workspace_path"] / "output/result.json").write_text("changed")
    (request["input_path"] / "value").unlink()
    assert inspect_candidate_evaluation(result.evaluation_path) == result


def test_output_observation_is_at_evaluation_time_and_harness_checks_constraints(tmp_path):
    admission, request = fixture(tmp_path)
    (request["workspace_path"] / "output/result.json").write_text('{"value": 81}')
    result = evaluate_candidate_execution(admission, **request)
    assert result.report.validity == 0 and result.report.combined_score == 0
    assert result.to_dict()["output_contract_valid"] is True
    assert result.to_dict()["harness_invoked"] is True
    assert (request["workspace_path"] / "count").read_text() == "x"


@pytest.mark.parametrize("content", [None, b"", b"no", b'{"bad":9}', b'{"value":NaN}', b'{"value":1,"value":9}', b'{"value":1e999}', b'\xff'])
def test_invalid_output_does_not_invoke_high_score_harness(tmp_path, content):
    admission, request = fixture(tmp_path, harness=b'raise RuntimeError("must not run")\n')
    path = request["workspace_path"] / "output/result.json"
    if content is None:
        path.unlink()
    else:
        path.write_bytes(content)
    result = evaluate_candidate_execution(admission, **request)
    assert result.report.validity == 0 and result.report.combined_score == 0
    assert result.to_dict()["harness_invoked"] is False
    assert result.report.error_info[0]["code"] == "output_contract_failed"
    assert inspect_candidate_evaluation(result.evaluation_path) == result


def test_optional_missing_nested_output_is_not_required(tmp_path):
    admission, request = fixture(tmp_path, outputs=[
        {"path": "output/result.json", "format": "json", "fields": ["value"]},
        {"path": "output/missing/detail.txt", "format": "text", "required": False},
    ])
    assert evaluate_candidate_execution(admission, **request).report.validity == 1


@pytest.mark.parametrize("script", [b"raise SystemExit(7)\n", b"import time; time.sleep(3)\n"])
def test_failed_execution_rejected_before_evaluation_allocation(tmp_path, script):
    admission, request = fixture(tmp_path, script=script)
    with pytest.raises(CandidateEvaluationError, match="execution_invalid"):
        evaluate_candidate_execution(admission, **request)
    assert list(request["evaluation_root"].iterdir()) == []


@pytest.mark.parametrize("pin", ["expected_admission_sha256", "expected_plan_sha256", "expected_bundle_sha256", "expected_contract_sha256", "expected_completion_sha256"])
def test_declaration_pin_mismatch_prevents_evaluation(tmp_path, pin):
    admission, request = fixture(tmp_path)
    request[pin] = "0" * 64
    with pytest.raises(CandidateEvaluationError):
        evaluate_candidate_execution(admission, **request)
    assert list(request["evaluation_root"].iterdir()) == []


@pytest.mark.parametrize("name", ["schema_version", "validity", "evaluator_id", "unknown"])
def test_invalid_harness_report_is_not_published(tmp_path, name):
    report = {"schema_version": "1", "evaluator_id": "exact", "validity": 1, "quality": None,
              "combined_score": 9, "detailed_scores": {}, "error_info": []}
    report[name] = {"schema_version": "2", "validity": 1.0, "evaluator_id": "another", "unknown": 1}[name]
    harness = ("print(" + repr(json.dumps(report)) + ")\n").encode()
    admission, request = fixture(tmp_path, harness=harness)
    with pytest.raises(CandidateEvaluationError, match="report_invalid"):
        evaluate_candidate_execution(admission, **request)
    directories = list(request["evaluation_root"].iterdir())
    assert len(directories) == 1
    assert not (directories[0] / "evaluation.json").exists()
    with pytest.raises(CandidateEvaluationError, match="incomplete"):
        inspect_candidate_evaluation(directories[0])


def test_valid_report_above_old_capture_limit(tmp_path):
    report = {"schema_version": "1", "evaluator_id": "exact", "validity": 1, "quality": None,
              "combined_score": 9, "detailed_scores": {}, "error_info": [
                  {"code": "detail", "message": "x" * 510} for _ in range(32)]}
    raw = json.dumps(report).encode()
    assert 16 * 1024 < len(raw) < 32 * 1024
    admission, request = fixture(tmp_path, harness=("print(" + repr(raw.decode()) + ")\n").encode())
    result = evaluate_candidate_execution(admission, **request)
    assert result.report.to_dict() == report
    assert (result.evaluation_path / "report.json").read_bytes() == raw + b"\n"


def test_repeated_evaluation_uses_new_directory_but_never_reruns_candidate(tmp_path):
    admission, request = fixture(tmp_path)
    first = evaluate_candidate_execution(admission, **request)
    second = evaluate_candidate_execution(admission, **request)
    assert first.evaluation_path != second.evaluation_path
    assert first.report == second.report
    assert (request["workspace_path"] / "count").read_text() == "x"


def test_evaluator_implementation_and_output_contract_pins_are_required(tmp_path):
    admission, request = fixture(tmp_path)
    for changed in (replace(admission, output_contract_sha256="f" * 64),
                    replace(admission, evaluator=replace(admission.evaluator, fingerprint="f" * 64))):
        with pytest.raises(CandidateEvaluationError, match="(evaluator|output_contract)_mismatch"):
            evaluate_candidate_execution(changed, **request)
    assert list(request["evaluation_root"].iterdir()) == []


def test_independent_evaluator_preserves_process_ownership_callbacks(tmp_path):
    admission, request = fixture(tmp_path)
    events = []

    result = evaluate_candidate_execution(
        admission, **request,
        process_observer=lambda pid, pgid: events.append(("observed", pid, pgid)),
        process_released=lambda pid, pgid: events.append(("released", pid, pgid)),
    )

    assert result.status == "evaluated"
    assert result.report.validity == 1
    assert len(events) == 2
    assert events[0] == ("observed", events[0][1], events[0][1])
    assert events[0][1] > 0
    assert events[1] == ("released", events[0][1], events[0][2])
    assert (request["workspace_path"] / "count").read_text() == "x"
