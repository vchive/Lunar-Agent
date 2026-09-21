"""Installed static CLI copies declared inputs without initializing or executing a runner."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from lunar_evolution import cli
from lunar_evolution.candidate_bundle import CandidateSourceBundle
from lunar_evolution.candidate_execution import (
    MAX_EXECUTION_ADMISSION_BYTES,
    CandidateEvaluatorPin,
    CandidateExecutionBudget,
    CandidateExecutionInput,
    build_candidate_execution_admission,
)
from lunar_evolution.candidate_workspace_plan import build_candidate_workspace_plan


def _fixture(tmp_path):
    marker = tmp_path / "runner-was-started"
    plan = build_candidate_workspace_plan(
        CandidateSourceBundle.from_dict({
            "schema_version": "1", "protocol": "lunar-candidate-source-bundle-v1",
            "contract_sha256": "a" * 64, "entrypoint": "main.py",
            "files": [{"path": "main.py", "size": 0, "sha256": hashlib.sha256(b"").hexdigest()}],
        }),
        contract_sha256="a" * 64,
        command=[sys.executable, "-c", f"open({str(marker)!r}, 'w').write('executed')"],
        timeout_seconds=5, max_output_bytes=1024,
    )
    source = tmp_path / "source"
    (source / "data").mkdir(parents=True)
    body = b"\x00\xff\x01fixture"
    (source / "data/input.bin").write_bytes(body)
    (source / "ignored.txt").write_text("not declared")
    staging = tmp_path / "staging"
    staging.mkdir()
    home = tmp_path / "home-must-not-exist"
    admission = build_candidate_execution_admission(
        plan,
        inputs=[CandidateExecutionInput("data/input.bin", "fixture", len(body), hashlib.sha256(body).hexdigest())],
        dependency_sha256="b" * 64, environment_sha256="c" * 64,
        evaluator=CandidateEvaluatorPin("exact-harness", "d" * 64),
        output_contract_sha256="e" * 64,
        budget=CandidateExecutionBudget(5, 1024, 1024, 1),
    )
    plan_path = tmp_path / "plan.json"
    admission_path = tmp_path / "admission.json"
    plan_path.write_text(json.dumps(plan.to_dict()))
    admission_path.write_text(json.dumps(admission.to_dict()))
    args = [
        "candidate-bundle", "stage-inputs", str(admission_path),
        "--plan", str(plan_path), "--input-root", str(source), "--staging-root", str(staging),
        "--home", str(home), "--json",
    ]
    return args, plan, admission, body, source, staging, marker, home


def _forbid_initialization(monkeypatch):
    def unexpected(*_args, **_kwargs):
        pytest.fail("static staging initialized state or started a subprocess")

    monkeypatch.setattr(cli, "_config", unexpected)
    monkeypatch.setattr(cli.Config, "ensure", unexpected)
    monkeypatch.setattr(cli.Store, "__init__", unexpected)
    monkeypatch.setattr(cli.Store, "initialize", unexpected)
    monkeypatch.setattr(subprocess, "Popen", unexpected)


def test_cli_stages_binary_inputs_without_control_state(tmp_path, monkeypatch, capsys):
    args, plan, admission, body, source, staging, marker, home = _fixture(tmp_path)
    _forbid_initialization(monkeypatch)
    args.extend([
        "--plan-sha256", plan.digest(), "--admission-sha256", admission.digest(),
        "--bundle-sha256", plan.bundle_sha256, "--contract-sha256", plan.contract_sha256,
    ])
    assert cli.main(args) == 0
    output = capsys.readouterr()
    assert output.err == ""
    payload = json.loads(output.out)
    input_path = Path(payload.pop("input_path"))
    assert input_path.parent == staging
    assert (input_path / "data/input.bin").read_bytes() == body
    assert (source / "data/input.bin").read_bytes() == body
    assert not (input_path / "ignored.txt").exists()
    assert payload == {
        "status": "staged", "admission_sha256": admission.digest(), "plan_sha256": plan.digest(),
        "bundle_sha256": plan.bundle_sha256, "contract_sha256": plan.contract_sha256,
        "input_count": 1, "total_input_bytes": len(body),
    }
    assert str(tmp_path) not in json.dumps(payload)
    assert not marker.exists() and not home.exists()


@pytest.mark.parametrize(("flag", "code"), [
    ("--plan-sha256", "plan_mismatch"),
    ("--bundle-sha256", "bundle_mismatch"),
    ("--contract-sha256", "contract_mismatch"),
    ("--admission-sha256", "identity_mismatch"),
])
def test_cli_pin_mismatch_before_source_or_staging_io(tmp_path, monkeypatch, capsys, flag, code):
    args, _plan, _admission, _body, _source, staging, marker, home = _fixture(tmp_path)
    _forbid_initialization(monkeypatch)
    args[args.index("--input-root") + 1] = str(tmp_path / "missing-source")
    args[args.index("--staging-root") + 1] = str(tmp_path / "missing-parent")
    args.extend([flag, "f" * 64])
    assert cli.main(args) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err) == {"error": f"candidate_execution_{code}"}
    assert not list(staging.iterdir())
    assert not marker.exists() and not home.exists()


@pytest.mark.parametrize(("kind", "code"), [
    ("missing", "invalid"), ("link", "invalid"), ("malformed", "invalid"),
    ("duplicate", "invalid"), ("too_large", "too_large"),
])
def test_cli_admission_file_errors_are_bounded_and_private(tmp_path, capsys, kind, code):
    args, _plan, _admission, _body, _source, staging, marker, home = _fixture(tmp_path)
    path = Path(args[2])
    if kind == "missing":
        path.unlink()
    elif kind == "link":
        saved = path.with_suffix(".saved")
        path.rename(saved)
        path.symlink_to(saved)
    elif kind == "too_large":
        path.write_bytes(b" " * (MAX_EXECUTION_ADMISSION_BYTES + 1))
    elif kind == "duplicate":
        path.write_text('{"private":1,"private":2}')
    else:
        path.write_text("private malformed body")
    assert cli.main(args) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err) == {"error": f"candidate_execution_{code}"}
    assert not list(staging.iterdir())
    assert not marker.exists() and not home.exists()


def test_cli_missing_plan_has_fixed_error_and_creates_nothing(tmp_path, capsys):
    args, _plan, _admission, _body, _source, staging, marker, home = _fixture(tmp_path)
    Path(args[args.index("--plan") + 1]).unlink()
    assert cli.main(args) == 2
    output = capsys.readouterr()
    assert json.loads(output.err) == {"error": "candidate_execution_plan_mismatch"}
    assert not list(staging.iterdir())
    assert not marker.exists() and not home.exists()


def test_cli_changed_input_returns_fixed_error_without_partial_tree(tmp_path, capsys):
    args, _plan, _admission, body, source, staging, marker, home = _fixture(tmp_path)
    (source / "data/input.bin").write_bytes(b"x" * len(body))
    assert cli.main(args) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err) == {"error": "candidate_input_staging_input_changed"}
    assert not list(staging.iterdir())
    assert not marker.exists() and not home.exists()


def test_installed_cli_stages_inputs_without_launch_or_home(tmp_path):
    args, plan, admission, body, _source, staging, marker, home = _fixture(tmp_path)
    launcher = Path(sys.executable).parent / "lunar-evolution"
    assert launcher.is_file(), "run tests using the repository's installed .venv"
    completed = subprocess.run(
        [str(launcher), *args], cwd=tmp_path, capture_output=True, text=True, timeout=15, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    payload = json.loads(completed.stdout)
    input_path = Path(payload["input_path"])
    assert input_path.parent == staging
    assert (input_path / "data/input.bin").read_bytes() == body
    assert payload["status"] == "staged"
    assert payload["plan_sha256"] == plan.digest()
    assert payload["admission_sha256"] == admission.digest()
    assert not marker.exists() and not home.exists()
