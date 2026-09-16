"""The installed candidate-bundle run command stays before normal state initialization."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from famou import (
    CandidateEvaluatorPin,
    CandidateExecutionBudget,
    CandidateExecutionInput,
    CandidateSourceBundle,
    CandidateSourceFile,
    build_candidate_execution_admission,
    build_candidate_workspace_plan,
    cli,
)


def _fixture(tmp_path: Path):
    workspace = tmp_path / "workspace"
    inputs = tmp_path / "inputs"
    workspace.mkdir()
    inputs.mkdir()
    script = b"#!/bin/sh\ncat \"$LUNAR_CANDIDATE_INPUT_ROOT/value\"\n"
    (workspace / "run.sh").write_bytes(script)
    (inputs / "value").write_bytes(b"cli-ok")
    bundle = CandidateSourceBundle(
        "a" * 64, "run.sh", (CandidateSourceFile("run.sh", len(script), hashlib.sha256(script).hexdigest()),)
    )
    plan = build_candidate_workspace_plan(
        bundle, command=("/bin/sh",), contract_sha256="a" * 64,
        timeout_seconds=2, max_output_bytes=1024,
    )
    admission = build_candidate_execution_admission(
        plan,
        inputs=[CandidateExecutionInput("value", "fixture", 6, hashlib.sha256(b"cli-ok").hexdigest())],
        dependency_sha256="b" * 64, environment_sha256="c" * 64,
        evaluator=CandidateEvaluatorPin("source-only", "d" * 64),
        budget=CandidateExecutionBudget(2, 1024, 1024, 1),
    )
    plan_path = tmp_path / "plan.json"
    admission_path = tmp_path / "admission.json"
    plan_path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")
    admission_path.write_text(json.dumps(admission.to_dict()), encoding="utf-8")
    args = [
        "candidate-bundle", "run", str(admission_path), "--plan", str(plan_path),
        "--workspace", str(workspace), "--input-root", str(inputs), "--json",
    ]
    return args, plan, admission, workspace, inputs


def test_cli_run_returns_path_free_telemetry_without_home(tmp_path, monkeypatch, capsys):
    args, plan, admission, workspace, inputs = _fixture(tmp_path)
    home = tmp_path / "must-not-exist"
    args.extend(["--home", str(home), "--plan-sha256", plan.digest(), "--admission-sha256", admission.digest()])
    monkeypatch.setattr(cli, "_config", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("initialized")))
    assert cli.main(args) == 0
    output = capsys.readouterr()
    payload = json.loads(output.out)
    assert payload["status"] == "succeeded"
    assert payload["execution"]["stdout_bytes"] == 6
    assert str(tmp_path) not in output.out
    assert str(workspace) not in output.out
    assert str(inputs) not in output.out
    assert not home.exists()


def test_installed_cli_run_executes_one_fixture_process(tmp_path):
    args, _plan, _admission, _workspace, _inputs = _fixture(tmp_path)
    launcher = Path(sys.executable).parent / "lunar-agent"
    if not launcher.is_file():
        return
    completed = subprocess.run(
        [str(launcher), *args], cwd=tmp_path, capture_output=True, text=True, timeout=15, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "succeeded"
    assert completed.stderr == ""
