"""Filesystem and launch-boundary checks for the candidate execution runner."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from famou import (
    CANDIDATE_INPUT_ROOT_ENV,
    CandidateEvaluatorPin,
    CandidateExecutionBudget,
    CandidateExecutionInput,
    CandidateExecutionRunnerError,
    CandidateSourceBundle,
    CandidateSourceFile,
    build_candidate_execution_admission,
    build_candidate_workspace_plan,
    run_candidate_execution,
)


def _fixture(tmp_path: Path, *, environment=None, max_processes: int = 1):
    tmp_path.mkdir(parents=True, exist_ok=True)
    workspace = tmp_path / "workspace"
    inputs = tmp_path / "inputs"
    workspace.mkdir()
    inputs.mkdir()
    script = b"#!/bin/sh\nprintf '%s' \"$PWD\"; cat \"$LUNAR_CANDIDATE_INPUT_ROOT/value\"\n"
    (workspace / "run.sh").write_bytes(script)
    (workspace / "value").write_bytes(b"ok")
    (inputs / "value").write_bytes(b"ok")
    bundle = CandidateSourceBundle(
        "a" * 64, "run.sh", (CandidateSourceFile("run.sh", len(script), hashlib.sha256(script).hexdigest()),)
    )
    plan = build_candidate_workspace_plan(
        bundle, command=("/bin/sh",), contract_sha256="a" * 64,
        timeout_seconds=2, max_output_bytes=1024, environment=environment,
    )
    item = CandidateExecutionInput("value", "fixture", 2, hashlib.sha256(b"ok").hexdigest())
    admission = build_candidate_execution_admission(
        plan, inputs=[item], dependency_sha256="b" * 64, environment_sha256="c" * 64,
        evaluator=CandidateEvaluatorPin("source-only", "d" * 64),
        budget=CandidateExecutionBudget(2, 1024, 1024, max_processes),
    )
    return admission, plan, workspace, inputs


def _assert_code(call, suffix: str):
    with pytest.raises(CandidateExecutionRunnerError) as caught:
        call()
    assert caught.value.code == f"candidate_execution_runner_{suffix}"


def test_shared_parent_is_allowed_but_selected_roots_must_be_disjoint(tmp_path: Path):
    admission, plan, workspace, inputs = _fixture(tmp_path)
    result = run_candidate_execution(admission, plan=plan, workspace_path=workspace, input_path=inputs)
    assert result.execution.status == "succeeded"
    assert str(workspace) in result.execution.stdout

    _assert_code(
        lambda: run_candidate_execution(admission, plan=plan, workspace_path=workspace, input_path=workspace),
        "workspace_unsafe",
    )
    nested = workspace / "nested-input"
    nested.mkdir()
    (nested / "value").write_bytes(b"ok")
    _assert_code(
        lambda: run_candidate_execution(admission, plan=plan, workspace_path=workspace, input_path=nested),
        "workspace_unsafe",
    )


@pytest.mark.parametrize("root_name", ["workspace-link", "input-link"])
def test_symlink_roots_are_rejected(tmp_path: Path, root_name: str):
    admission, plan, workspace, inputs = _fixture(tmp_path)
    link = tmp_path / root_name
    link.symlink_to(workspace if root_name == "workspace-link" else inputs, target_is_directory=True)
    kwargs = {"workspace_path": link if root_name == "workspace-link" else workspace,
              "input_path": link if root_name == "input-link" else inputs}
    expected = "workspace_unsafe" if root_name == "workspace-link" else "input_unsafe"
    _assert_code(lambda: run_candidate_execution(admission, plan=plan, **kwargs), expected)


def test_input_bytes_and_source_bundle_are_rechecked(tmp_path: Path):
    admission, plan, workspace, inputs = _fixture(tmp_path)
    (inputs / "value").write_bytes(b"NO")
    _assert_code(
        lambda: run_candidate_execution(admission, plan=plan, workspace_path=workspace, input_path=inputs),
        "input_changed",
    )

    admission, plan, workspace, inputs = _fixture(tmp_path / "source-drift")
    (workspace / "run.sh").write_bytes(b"#!/bin/sh\nexit 4\n")
    _assert_code(
        lambda: run_candidate_execution(admission, plan=plan, workspace_path=workspace, input_path=inputs),
        "bundle_changed",
    )


def test_reserved_environment_and_process_budget_are_rejected_before_launch(tmp_path: Path):
    admission, plan, workspace, inputs = _fixture(
        tmp_path, environment={CANDIDATE_INPUT_ROOT_ENV: "caller-value"},
    )
    _assert_code(
        lambda: run_candidate_execution(admission, plan=plan, workspace_path=workspace, input_path=inputs),
        "invalid",
    )
    admission, plan, workspace, inputs = _fixture(tmp_path / "budget", max_processes=2)
    _assert_code(
        lambda: run_candidate_execution(admission, plan=plan, workspace_path=workspace, input_path=inputs),
        "invalid",
    )


def test_start_failure_is_fixed_and_does_not_expose_local_details(tmp_path: Path, monkeypatch):
    admission, plan, workspace, inputs = _fixture(tmp_path)
    import famou.candidate_execution_runner as runner

    def fail(*_args, **_kwargs):
        raise OSError("private host detail")

    monkeypatch.setattr(runner.subprocess, "Popen", fail)
    result = run_candidate_execution(admission, plan=plan, workspace_path=workspace, input_path=inputs)
    assert result.execution.error == "process_start_failed"
    assert "private" not in str(result.to_dict())


def test_caller_pin_is_checked_before_process_start(tmp_path: Path, monkeypatch):
    admission, plan, workspace, inputs = _fixture(tmp_path)
    import famou.candidate_execution_runner as runner

    monkeypatch.setattr(runner.subprocess, "Popen", lambda *_a, **_k: pytest.fail("Popen called"))
    _assert_code(
        lambda: run_candidate_execution(
            admission, plan=plan, workspace_path=workspace, input_path=inputs,
            expected_plan_sha256="0" * 64,
        ),
        "plan_mismatch",
    )


def test_fifo_input_root_is_rejected(tmp_path: Path):
    admission, plan, workspace, _inputs = _fixture(tmp_path)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    _assert_code(
        lambda: run_candidate_execution(admission, plan=plan, workspace_path=workspace, input_path=fifo),
        "input_unsafe",
    )
