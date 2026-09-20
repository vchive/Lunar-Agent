"""Local deterministic launch, interruption, and retained telemetry checks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from famou import (
    CandidateEvaluatorPin,
    CandidateExecutionBudget,
    CandidateExecutionEvidenceError,
    CandidateExecutionInput,
    CandidateSourceBundle,
    CandidateSourceFile,
    build_candidate_execution_admission,
    build_candidate_workspace_plan,
    inspect_candidate_execution_record,
    run_candidate_execution_recorded,
)
from famou import candidate_execution_evidence as evidence


def fixture(tmp_path: Path, script: bytes | None = None):
    root = tmp_path.resolve()
    workspace = root / "workspace"
    inputs = root / "inputs"
    workspace.mkdir(parents=True)
    inputs.mkdir()
    if script is None:
        script = b'printf "x" >> count; cat "$LUNAR_CANDIDATE_INPUT_ROOT/value"\n'
    (workspace / "run.sh").write_bytes(script)
    (inputs / "value").write_bytes(b"evidence-fixture")
    bundle = CandidateSourceBundle(
        "a" * 64, "run.sh",
        (CandidateSourceFile("run.sh", len(script), hashlib.sha256(script).hexdigest()),),
    )
    # Linux may alias both /bin and sh; admission names the actual executable identity.
    plan = build_candidate_workspace_plan(
        bundle, command=(str(Path("/bin/sh").resolve(strict=True)),), contract_sha256="a" * 64,
        timeout_seconds=0.2, max_output_bytes=1024,
    )
    item = CandidateExecutionInput("value", "fixture", len(b"evidence-fixture"), hashlib.sha256(b"evidence-fixture").hexdigest())
    admission = build_candidate_execution_admission(
        plan, inputs=[item], dependency_sha256="b" * 64, environment_sha256="c" * 64,
        evaluator=CandidateEvaluatorPin("source-only", "d" * 64),
        budget=CandidateExecutionBudget(0.2, 1024, 1024, 1),
    )
    return admission, {
        "plan": plan, "workspace_path": workspace, "input_path": inputs,
        "attempt_path": root / "attempt",
    }


def inspect(admission, request, **kwargs):
    return inspect_candidate_execution_record(
        request["attempt_path"], admission=admission, plan=request["plan"], **kwargs,
    )


def test_intent_precedes_launch_and_complete_record_round_trips(tmp_path, monkeypatch):
    admission, request = fixture(tmp_path)
    runner = evidence.run_candidate_execution
    def observed(*args, **kwargs):
        intent = request["attempt_path"] / "launch-intent.json"
        assert intent.is_file()
        assert inspect(admission, request).status == "uncertain"
        assert not (request["attempt_path"] / "result.json").exists()
        return runner(*args, **kwargs)
    monkeypatch.setattr(evidence, "run_candidate_execution", observed)
    result = run_candidate_execution_recorded(admission, **request)
    assert result.status == "recorded"
    payload = result.to_dict()
    assert payload["runner_result"]["status"] == "succeeded"
    assert (request["workspace_path"] / "count").read_text() == "x"
    assert inspect(admission, request, expected_completion_sha256=result.completion_sha256) == result
    assert str(tmp_path) not in json.dumps(payload)
    for path in request["attempt_path"].iterdir():
        content = path.read_bytes()
        assert str(tmp_path).encode() not in content
        assert b"evidence-fixture" not in content
        assert b'"stdout"' not in content
        assert content == evidence._encode(json.loads(content))
    # Inspection binds retained pre-launch observation, not the mutable source after execution.
    (request["workspace_path"] / "run.sh").write_text("changed")
    (request["input_path"] / "value").unlink()
    assert inspect(admission, request) == result


def test_existing_attempt_never_relaunches(tmp_path):
    admission, request = fixture(tmp_path)
    run_candidate_execution_recorded(admission, **request)
    for _ in range(2):
        with pytest.raises(CandidateExecutionEvidenceError, match="attempt_exists"):
            run_candidate_execution_recorded(admission, **request)
    assert (request["workspace_path"] / "count").read_text() == "x"


@pytest.mark.parametrize("script,status,error", [
    (b"exit 7\n", "failed", "process_failed"),
    (b"sleep 3\n", "timed_out", "process_timed_out"),
    (b"printf '%2048s' ''\n", "failed", "output_limit_exceeded"),
])
def test_failure_outcomes_are_recorded_without_success_authority(tmp_path, script, status, error):
    admission, request = fixture(tmp_path, script)
    result = run_candidate_execution_recorded(admission, **request)
    assert result.status == "recorded"
    assert result.to_dict()["runner_result"]["execution"]["status"] == status
    assert result.to_dict()["runner_result"]["execution"]["error"] == error
    assert inspect(admission, request) == result


@pytest.mark.parametrize("after_run", [False, True])
def test_runner_interruption_retains_intent_and_refuses_replay(tmp_path, monkeypatch, after_run):
    admission, request = fixture(tmp_path)
    runner = evidence.run_candidate_execution
    def interrupted(*args, **kwargs):
        if after_run:
            runner(*args, **kwargs)
        raise KeyboardInterrupt
    monkeypatch.setattr(evidence, "run_candidate_execution", interrupted)
    with pytest.raises(KeyboardInterrupt):
        run_candidate_execution_recorded(admission, **request)
    assert inspect(admission, request).status == "uncertain"
    with pytest.raises(CandidateExecutionEvidenceError, match="attempt_exists"):
        run_candidate_execution_recorded(admission, **request)
    marker = request["workspace_path"] / "count"
    assert (marker.read_text() if marker.exists() else "") == ("x" if after_run else "")


def test_invalid_pin_is_rejected_before_any_root_io(tmp_path, monkeypatch):
    admission, request = fixture(tmp_path)
    monkeypatch.setattr(evidence, "_open", lambda *_: pytest.fail("unexpected root IO"))
    with pytest.raises(CandidateExecutionEvidenceError, match="admission_mismatch"):
        run_candidate_execution_recorded(admission, **request, expected_plan_sha256="0" * 64)
    assert not request["attempt_path"].exists()


@pytest.mark.parametrize("root,file", [("workspace_path", "run.sh"), ("input_path", "value")])
def test_changed_source_input_fails_before_attempt_or_process(tmp_path, root, file):
    admission, request = fixture(tmp_path)
    (request[root] / file).write_bytes(b"changed")
    with pytest.raises(CandidateExecutionEvidenceError, match="changed"):
        run_candidate_execution_recorded(admission, **request)
    assert not request["attempt_path"].exists()
    assert not (request["workspace_path"] / "count").exists()


@pytest.mark.parametrize("removed", ["result.json", "completed.json"])
def test_incomplete_record_is_readonly_uncertain(tmp_path, removed):
    admission, request = fixture(tmp_path)
    run_candidate_execution_recorded(admission, **request)
    (request["attempt_path"] / removed).unlink()
    if removed == "result.json":
        (request["attempt_path"] / "completed.json").unlink()
    before = {p.name: p.read_bytes() for p in request["attempt_path"].iterdir()}
    assert inspect(admission, request).status == "uncertain"
    assert before == {p.name: p.read_bytes() for p in request["attempt_path"].iterdir()}
    with pytest.raises(CandidateExecutionEvidenceError, match="identity_mismatch"):
        inspect(admission, request, expected_completion_sha256="0" * 64)


def test_completion_pin_and_admission_mismatch_are_rejected(tmp_path):
    admission, request = fixture(tmp_path)
    run_candidate_execution_recorded(admission, **request)
    with pytest.raises(CandidateExecutionEvidenceError, match="identity_mismatch"):
        inspect(admission, request, expected_completion_sha256="0" * 64)
    changed = build_candidate_execution_admission(
        request["plan"], inputs=admission.inputs, dependency_sha256="e" * 64,
        environment_sha256=admission.environment_sha256, evaluator=admission.evaluator,
        budget=admission.budget,
    )
    with pytest.raises(CandidateExecutionEvidenceError, match="identity_mismatch"):
        inspect(changed, request)


def test_recorded_candidate_preserves_process_ownership_callbacks(tmp_path):
    admission, request = fixture(tmp_path)
    events = []

    def observed(pid, pgid):
        events.append((
            "observed", pid, pgid,
            (request["attempt_path"] / "launch-intent.json").is_file(),
            (request["attempt_path"] / "completed.json").exists(),
        ))

    record = run_candidate_execution_recorded(
        admission, **request, process_observer=observed,
        process_released=lambda pid, pgid: events.append(("released", pid, pgid)),
    )

    assert record.status == "recorded"
    assert record.to_dict()["runner_result"]["status"] == "succeeded"
    assert len(events) == 2
    assert events[0] == ("observed", events[0][1], events[0][1], True, False)
    assert events[0][1] > 0
    assert events[1] == ("released", events[0][1], events[0][2])
    assert inspect(admission, request) == record
