"""Admission replay and public API contracts for private candidate input staging."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import FrozenInstanceError

import pytest

import famou
from famou import candidate_input_staging as staging
from famou.candidate_bundle import CandidateSourceBundle
from famou.candidate_execution import (
    CandidateEvaluatorPin,
    CandidateExecutionBudget,
    CandidateExecutionError,
    CandidateExecutionInput,
    admit_candidate_execution,
    build_candidate_execution_admission,
)
from famou.candidate_input_staging import (
    CandidateInputStagingError,
    StagedCandidateExecutionInputs,
    stage_candidate_execution_inputs,
)
from famou.candidate_workspace_plan import build_candidate_workspace_plan


def _fixture(tmp_path):
    source = tmp_path / "inputs"
    parent = tmp_path / "staged-inputs"
    source.mkdir()
    parent.mkdir()
    content = b"\x00\xff\x80private fixture payload"
    (source / "main.py").write_bytes(content)
    bundle = CandidateSourceBundle.from_dict({
        "schema_version": "1", "protocol": "lunar-candidate-source-bundle-v1",
        "contract_sha256": "a" * 64, "entrypoint": "main.py",
        "files": [{"path": "main.py", "size": 0, "sha256": hashlib.sha256(b"").hexdigest()}],
    })
    plan = build_candidate_workspace_plan(
        bundle, contract_sha256="a" * 64, command=["/absent/runner", "main.py"],
        timeout_seconds=5, max_output_bytes=1024,
    )
    admission = build_candidate_execution_admission(
        plan, inputs=[CandidateExecutionInput(
            "main.py", "source-label", len(content), hashlib.sha256(content).hexdigest(),
        )],
        dependency_sha256="b" * 64, environment_sha256="c" * 64,
        evaluator=CandidateEvaluatorPin("exact-harness", "d" * 64),
        output_contract_sha256="e" * 64,
        budget=CandidateExecutionBudget(5, 1024, 1024, 1),
    )
    return source, parent, plan, admission, content


@pytest.mark.parametrize("representation", ["dto", "mapping", "text", "bytes"])
@pytest.mark.parametrize("plan_mapping", [False, True])
def test_supported_declarations_stage_with_complete_matching_pins(
    tmp_path, representation, plan_mapping,
):
    source, parent, plan, admission, content = _fixture(tmp_path)
    value = {
        "dto": admission,
        "mapping": admission.to_dict(),
        "text": json.dumps(admission.to_dict()),
        "bytes": json.dumps(admission.to_dict()).encode(),
    }[representation]
    result = stage_candidate_execution_inputs(
        value, plan=plan.to_dict() if plan_mapping else plan,
        input_root=source, staging_root=parent,
        expected_admission_sha256=admission.digest(), expected_plan_sha256=plan.digest(),
        expected_bundle_sha256=plan.bundle_sha256, expected_contract_sha256=plan.contract_sha256,
    )
    assert isinstance(result, StagedCandidateExecutionInputs)
    assert result.admission == admission
    assert result.admission is not admission
    assert result.input_path.parent == parent
    assert result.input_path.name.startswith(".candidate-inputs-")
    assert (result.input_path / "main.py").read_bytes() == content
    assert result.to_dict() == {
        "status": "staged", "admission_sha256": admission.digest(),
        "plan_sha256": plan.digest(), "bundle_sha256": plan.bundle_sha256,
        "contract_sha256": plan.contract_sha256, "input_count": 1,
        "total_input_bytes": len(content),
    }
    assert result.workspace_plan_sha256 == result.plan_sha256 == plan.digest()
    serialized = json.dumps(result.to_dict())
    assert "input_path" not in serialized
    assert str(tmp_path) not in serialized
    assert "private fixture payload" not in serialized
    assert "main.py" not in serialized
    assert "source-label" not in serialized


def test_repeated_staging_allocates_independent_trees_with_the_same_identity(tmp_path):
    source, parent, plan, admission, content = _fixture(tmp_path)
    first, second = [
        stage_candidate_execution_inputs(admission, plan=plan, input_root=source, staging_root=parent)
        for _ in range(2)
    ]
    assert first.input_path != second.input_path
    assert first.to_dict() == second.to_dict()
    (first.input_path / "main.py").write_bytes(b"caller edit")
    assert (second.input_path / "main.py").read_bytes() == content
    assert (source / "main.py").read_bytes() == content


def test_empty_inputs_still_allocate_one_empty_private_directory(tmp_path):
    source, parent, plan, admission, _ = _fixture(tmp_path)
    payload = admission.to_dict(include_admission_sha256=False)
    payload["inputs"] = []
    result = stage_candidate_execution_inputs(
        payload, plan=plan, input_root=source, staging_root=parent,
    )
    assert result.input_path.parent == parent
    assert list(result.input_path.iterdir()) == []
    assert list(parent.iterdir()) == [result.input_path]
    assert result.input_count == result.total_input_bytes == 0
    assert result.to_dict()["status"] == "staged"
    assert result.to_dict()["input_count"] == result.to_dict()["total_input_bytes"] == 0


@pytest.mark.parametrize(("pin", "code"), [
    ("expected_admission_sha256", "identity_mismatch"),
    ("expected_plan_sha256", "plan_mismatch"),
    ("expected_bundle_sha256", "bundle_mismatch"),
    ("expected_contract_sha256", "contract_mismatch"),
])
@pytest.mark.parametrize("value", ["f" * 64, "invalid-digest"])
def test_every_caller_pin_fails_before_either_root_is_touched(tmp_path, monkeypatch, pin, code, value):
    source, parent, plan, admission, _ = _fixture(tmp_path)
    monkeypatch.setattr(staging._files, "absolute_path", lambda *_a, **_kw: pytest.fail("root IO"))
    with pytest.raises(CandidateExecutionError, match=f"^candidate_execution_{code}$"):
        stage_candidate_execution_inputs(
            admission, plan=plan, input_root=source, staging_root=parent, **{pin: value},
        )
    assert list(parent.iterdir()) == []


def test_changed_valid_plan_is_rejected_before_io(tmp_path, monkeypatch):
    source, parent, plan, admission, _ = _fixture(tmp_path)
    changed = build_candidate_workspace_plan(
        plan.bundle, contract_sha256=plan.contract_sha256, command=["/absent/other-runner", "main.py"],
        timeout_seconds=5, max_output_bytes=1024,
    )
    monkeypatch.setattr(staging._files, "absolute_path", lambda *_a, **_kw: pytest.fail("root IO"))
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_plan_mismatch$"):
        stage_candidate_execution_inputs(admission, plan=changed, input_root=source, staging_root=parent)


@pytest.mark.parametrize("mutation", ["input", "budget", "plan-source"])
def test_replay_revalidates_nested_dtos_before_filesystem_io(tmp_path, monkeypatch, mutation):
    source, parent, plan, admission, _ = _fixture(tmp_path)
    if mutation == "input":
        object.__setattr__(admission.inputs[0], "target", "../outside")
        code = "input_unsafe"
    elif mutation == "budget":
        object.__setattr__(admission.budget, "max_input_bytes", True)
        code = "budget_invalid"
    else:
        object.__setattr__(plan.bundle.files[0], "path", "../outside")
        code = "plan_mismatch"
    monkeypatch.setattr(staging._files, "absolute_path", lambda *_a, **_kw: pytest.fail("root IO"))
    with pytest.raises(CandidateExecutionError, match=f"^candidate_execution_{code}$"):
        stage_candidate_execution_inputs(admission, plan=plan, input_root=source, staging_root=parent)


def test_a_prior_verified_admission_does_not_skip_fresh_source_checks(tmp_path):
    source, parent, plan, admission, content = _fixture(tmp_path)
    prior = admit_candidate_execution(admission, plan=plan, input_root=source)
    assert prior.inputs_verified
    (source / "main.py").write_bytes(b"x" * len(content))
    with pytest.raises(CandidateInputStagingError, match="^candidate_input_staging_input_changed$"):
        stage_candidate_execution_inputs(
            prior.admission, plan=plan, input_root=source, staging_root=parent,
        )
    assert list(parent.iterdir()) == []


def test_strings_are_json_not_paths_and_cannot_implicitly_open_a_declaration(tmp_path, monkeypatch):
    source, parent, plan, admission, _ = _fixture(tmp_path)
    declaration = tmp_path / "admission.json"
    declaration.write_text(json.dumps(admission.to_dict()))
    monkeypatch.setattr(staging._files, "absolute_path", lambda *_a, **_kw: pytest.fail("root IO"))
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_invalid$"):
        stage_candidate_execution_inputs(
            str(declaration), plan=plan, input_root=source, staging_root=parent,
        )


def test_staging_never_executes_candidate_or_initializes_control_state(tmp_path, monkeypatch):
    source, parent, plan, admission, content = _fixture(tmp_path)
    home = tmp_path / "unused-home"
    monkeypatch.setenv("LUNAR_HOME", str(home))
    monkeypatch.setenv("FAMOU_HOME", str(home))
    monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_kw: pytest.fail("process started"))
    monkeypatch.setattr(os, "system", lambda *_a, **_kw: pytest.fail("shell started"))
    result = stage_candidate_execution_inputs(
        admission, plan=plan, input_root=source, staging_root=parent,
    )
    assert (result.input_path / "main.py").read_bytes() == content
    assert not home.exists()
    assert sorted(path.name for path in tmp_path.iterdir()) == ["inputs", "staged-inputs"]
    assert sorted(path.name for path in result.input_path.iterdir()) == ["main.py"]


def test_result_is_frozen_and_serialization_revalidates_its_admission(tmp_path):
    source, parent, plan, admission, _ = _fixture(tmp_path)
    result = stage_candidate_execution_inputs(
        admission, plan=plan, input_root=source, staging_root=parent,
    )
    with pytest.raises(FrozenInstanceError):
        result.input_path = source
    object.__setattr__(admission.inputs[0], "target", "../changed-source-dto")
    assert result.to_dict()["input_count"] == 1
    object.__setattr__(result.admission.inputs[0], "size", True)
    with pytest.raises(CandidateExecutionError, match="^candidate_execution_input_invalid$"):
        result.to_dict()


@pytest.mark.parametrize("interruption", [OSError, KeyboardInterrupt, SystemExit])
def test_initialization_failure_cleans_a_directory_with_known_opened_identity(
    tmp_path, monkeypatch, interruption,
):
    source, parent, plan, admission, _ = _fixture(tmp_path)
    acquired = []
    closed = []
    original_open = os.open
    original_close = os.close

    def open_file(*args, **kwargs):
        descriptor = original_open(*args, **kwargs)
        acquired.append(descriptor)
        return descriptor

    def close_file(descriptor):
        closed.append(descriptor)
        return original_close(descriptor)

    def fail_chmod(*_args, **_kwargs):
        raise interruption("private initialization failure")

    monkeypatch.setattr(os, "open", open_file)
    monkeypatch.setattr(os, "close", close_file)
    monkeypatch.setattr(os, "fchmod", fail_chmod)
    expected = CandidateInputStagingError if interruption is OSError else interruption
    with pytest.raises(expected) as error:
        stage_candidate_execution_inputs(
            admission, plan=plan, input_root=source, staging_root=parent,
        )
    if interruption is OSError:
        assert str(error.value) == "candidate_input_staging_destination_write_failed"
    assert list(parent.iterdir()) == []
    assert sorted(acquired) == sorted(closed)


@pytest.mark.parametrize("code", ["private /tmp/path", "", 42, None])
def test_error_codes_never_include_unknown_caller_values(code):
    error = CandidateInputStagingError(code)
    assert error.code == str(error) == "candidate_input_staging_invalid"


def test_staging_api_is_publicly_exported():
    assert famou.stage_candidate_execution_inputs is stage_candidate_execution_inputs
    assert famou.StagedCandidateExecutionInputs is StagedCandidateExecutionInputs
    assert famou.CandidateInputStagingError is CandidateInputStagingError
