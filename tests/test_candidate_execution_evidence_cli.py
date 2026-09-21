"""The CLI records and inspects without ordinary config or Store initialization."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_candidate_execution_evidence import fixture

from lunar_evolution import cli


def command(tmp_path):
    admission, request = fixture(tmp_path)
    admission_path = tmp_path / "admission.json"
    plan_path = tmp_path / "plan.json"
    admission_path.write_text(json.dumps(admission.to_dict()))
    plan_path.write_text(json.dumps(request["plan"].to_dict()))
    common = [
        str(admission_path), "--plan", str(plan_path), "--attempt", str(request["attempt_path"]),
        "--json", "--home", str(tmp_path / "no-home"),
    ]
    run = [
        "candidate-bundle", "run-recorded", *common, "--workspace", str(request["workspace_path"]),
        "--input-root", str(request["input_path"]),
    ]
    inspect = ["candidate-bundle", "inspect-execution", *common]
    return request, run, inspect


def test_cli_records_and_inspects_no_initialization(tmp_path, monkeypatch, capsys):
    request, run, inspect = command(tmp_path)
    monkeypatch.setattr(cli, "_config", lambda *_: pytest.fail("initialized Store/home"))
    assert cli.main(run) == 0
    output = capsys.readouterr()
    recorded = json.loads(output.out)
    assert output.err == ""
    assert recorded["status"] == "recorded"
    assert recorded["runner_result"]["status"] == "succeeded"
    assert str(tmp_path) not in output.out
    assert cli.main([*inspect, "--completion-sha256", recorded["completion_sha256"]]) == 0
    assert json.loads(capsys.readouterr().out) == recorded
    assert cli.main(run) != 0
    output = capsys.readouterr()
    assert "candidate_execution_evidence_attempt_exists" in output.err
    assert str(tmp_path) not in output.err
    assert (request["workspace_path"] / "count").read_text() == "x"
    assert not (tmp_path / "no-home").exists()


def test_cli_inspection_of_incomplete_attempt_is_readonly(tmp_path, monkeypatch, capsys):
    request, _run, inspect = command(tmp_path)
    request["attempt_path"].mkdir()
    monkeypatch.setattr(cli, "_config", lambda *_: pytest.fail("initialized"))
    assert cli.main(inspect) == 0
    assert json.loads(capsys.readouterr().out) == {"status": "uncertain"}
    assert list(request["attempt_path"].iterdir()) == []
    assert not (request["workspace_path"] / "count").exists()


def test_installed_cli_records_then_inspects_relative_paths(tmp_path):
    request, run, inspect = command(tmp_path)
    launcher = Path(sys.executable).parent / "lunar-evolution"
    if not launcher.is_file():
        pytest.skip("installed CLI unavailable")
    def local_args(args):
        return [str(Path(arg).relative_to(tmp_path)) if arg.startswith(str(tmp_path)) else arg for arg in args]
    result = subprocess.run(
        [str(launcher), *local_args(run)], cwd=tmp_path, capture_output=True, text=True,
        timeout=15, check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "recorded"
    inspected = subprocess.run(
        [str(launcher), *local_args(inspect)], cwd=tmp_path, capture_output=True, text=True,
        timeout=15, check=False,
    )
    assert inspected.returncode == 0, inspected.stderr
    assert json.loads(inspected.stdout) == payload
    assert (request["workspace_path"] / "count").read_text() == "x"
    assert not (tmp_path / "no-home").exists()
