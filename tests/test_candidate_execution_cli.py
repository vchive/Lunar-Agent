"""Static candidate execution admission CLI remains offline and path-free."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from lunar_evolution import cli
from lunar_evolution.candidate_bundle import CandidateSourceBundle
from lunar_evolution.candidate_execution import CandidateExecutionInput
from lunar_evolution.candidate_workspace_plan import build_candidate_workspace_plan

CONTRACT = "a" * 64
DEPENDENCY = "b" * 64
ENVIRONMENT = "c" * 64
EVALUATOR = "d" * 64
OUTPUT = "e" * 64


def _fixture(tmp_path: Path):
    marker = tmp_path / "private-entrypoint-ran"
    bundle = CandidateSourceBundle.from_dict({
        "schema_version": "1",
        "protocol": "lunar-candidate-source-bundle-v1",
        "contract_sha256": CONTRACT,
        "entrypoint": "main.py",
        "files": [{
            "path": "main.py",
            "size": 0,
            "sha256": hashlib.sha256(b"").hexdigest(),
        }],
    })
    plan = build_candidate_workspace_plan(
        bundle,
        contract_sha256=CONTRACT,
        command=[sys.executable, "main.py", str(marker)],
        timeout_seconds=5,
        max_output_bytes=1024,
    )
    plan_path = tmp_path / "private-plan.json"
    plan_path.write_text(json.dumps(plan.to_dict()), encoding="utf-8")
    input_root = tmp_path / "private-input-root"
    (input_root / "data").mkdir(parents=True)
    content = b"fixture input"
    (input_root / "data/input.bin").write_bytes(content)
    descriptor = CandidateExecutionInput(
        "data/input.bin", "fixture", len(content), hashlib.sha256(content).hexdigest(),
    )
    inputs_path = tmp_path / "private-inputs.json"
    inputs_path.write_text(json.dumps([descriptor.to_dict()]), encoding="utf-8")
    home = tmp_path / "private-home-must-not-be-created"
    args = [
        "candidate-bundle", "admit-execution", str(plan_path),
        "--inputs", str(inputs_path), "--input-root", str(input_root),
        "--dependency-sha256", DEPENDENCY,
        "--environment-sha256", ENVIRONMENT,
        "--evaluator-kind", "exact-harness", "--evaluator-sha256", EVALUATOR,
        "--output-contract-sha256", OUTPUT, "--home", str(home), "--json",
    ]
    return args, plan, descriptor, marker, home, input_root


def _forbid_initialization(monkeypatch):
    def unexpected(*_args, **_kwargs):
        pytest.fail("execution admission initialized home or Store")

    monkeypatch.setattr(cli, "_config", unexpected)
    monkeypatch.setattr(cli.Config, "ensure", unexpected)
    monkeypatch.setattr(cli.Store, "__init__", unexpected)
    monkeypatch.setattr(cli.Store, "initialize", unexpected)


def test_cli_admits_and_verifies_inputs_without_execution_or_initialization(
    tmp_path, monkeypatch, capsys,
):
    args, plan, descriptor, marker, home, input_root = _fixture(tmp_path)
    _forbid_initialization(monkeypatch)

    assert cli.main(args) == 0
    output = capsys.readouterr()
    payload = json.loads(output.out)
    assert output.err == ""
    assert payload == {
        "status": "admitted",
        "admission_sha256": payload["admission_sha256"],
        "plan_sha256": plan.digest(),
        "bundle_sha256": plan.bundle_sha256,
        "contract_sha256": CONTRACT,
        "evaluator_kind": "exact-harness",
        "input_count": 1,
        "total_input_bytes": descriptor.size,
        "inputs_verified": True,
    }
    assert str(tmp_path) not in output.out
    assert not marker.exists()
    assert not home.exists()
    assert input_root.joinpath("data/input.bin").read_bytes() == b"fixture input"


def test_cli_checks_pins_before_input_root_io(tmp_path, monkeypatch, capsys):
    args, _plan, _descriptor, marker, home, input_root = _fixture(tmp_path)
    args[args.index("--input-root") + 1] = str(tmp_path / "missing-input-root")
    args.extend(["--plan-sha256", "f" * 64])
    _forbid_initialization(monkeypatch)

    assert cli.main(args) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err) == {"error": "candidate_execution_plan_mismatch"}
    assert not marker.exists()
    assert not home.exists()
    assert input_root.joinpath("data/input.bin").exists()


def test_cli_checks_plan_pin_before_input_descriptor_io(tmp_path, monkeypatch, capsys):
    args, _plan, _descriptor, marker, home, _input_root = _fixture(tmp_path)
    args[args.index("--inputs") + 1] = str(tmp_path / "missing-inputs.json")
    args.extend(["--plan-sha256", "f" * 64])
    _forbid_initialization(monkeypatch)

    assert cli.main(args) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err) == {"error": "candidate_execution_plan_mismatch"}
    assert not marker.exists()
    assert not home.exists()


def test_cli_reports_changed_input_without_leaking_local_values(tmp_path, monkeypatch, capsys):
    args, _plan, _descriptor, marker, home, input_root = _fixture(tmp_path)
    input_root.joinpath("data/input.bin").write_bytes(b"changed input")
    _forbid_initialization(monkeypatch)

    assert cli.main(args) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err) == {"error": "candidate_execution_input_changed"}
    assert str(tmp_path) not in output.err
    assert "changed input" not in output.err
    assert not marker.exists()
    assert not home.exists()


def test_installed_cli_admits_without_home_or_entrypoint_side_effects(tmp_path):
    args, plan, descriptor, marker, home, _input_root = _fixture(tmp_path)
    launcher = Path(sys.executable).parent / "lunar-evolution"
    if not launcher.is_file():
        pytest.skip("installed lunar-evolution launcher is unavailable")

    completed = subprocess.run(
        [str(launcher), *args], cwd=tmp_path, capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "admitted"
    assert payload["admission_sha256"]
    assert payload["plan_sha256"] == plan.digest()
    assert payload["input_count"] == 1
    assert payload["total_input_bytes"] == descriptor.size
    assert payload["inputs_verified"] is True
    assert str(tmp_path) not in completed.stdout + completed.stderr
    assert not marker.exists()
    assert not home.exists()
