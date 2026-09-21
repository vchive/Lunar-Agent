"""Independent evaluation CLI paths never initialize ordinary runtime state."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from test_candidate_evaluation import fixture

from lunar_evolution import cli
from lunar_evolution.candidate_evaluation_spec import MAX_CANDIDATE_EVALUATION_SPEC_BYTES


def command(tmp_path):
    admission, request = fixture(tmp_path)
    declarations = {
        "admission": admission,
        "plan": request["plan"],
        "contract": request["contract"],
        "evaluator": request["evaluator"],
    }
    paths = {}
    for name, value in declarations.items():
        paths[name] = tmp_path / (name + ".json")
        paths[name].write_text(json.dumps(value.to_dict()))
    evaluate = [
        "candidate-bundle", "evaluate", str(paths["admission"]),
        "--plan", str(paths["plan"]), "--contract", str(paths["contract"]),
        "--evaluator", str(paths["evaluator"]), "--harness", str(request["harness_path"]),
        "--workspace", str(request["workspace_path"]), "--input-root", str(request["input_path"]),
        "--attempt", str(request["attempt_path"]),
        "--evaluation-root", str(request["evaluation_root"]),
        "--json", "--home", str(tmp_path / "no-home"),
    ]
    return request, paths, evaluate


def workspace_bytes(request):
    root = request["workspace_path"]
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_cli_evaluates_and_inspects_without_initialization_or_candidate_relaunch(tmp_path, monkeypatch, capsys):
    request, _paths, evaluate = command(tmp_path)
    before = workspace_bytes(request)
    monkeypatch.setattr(cli, "_config", lambda *_: pytest.fail("initialized Store/home"))
    assert cli.main(evaluate) == 0
    output = capsys.readouterr()
    assert output.err == ""
    payload = json.loads(output.out)
    assert payload["status"] == "evaluated"
    assert payload["report"]["validity"] == 1
    assert payload["harness_invoked"] is True
    assert payload["observation"] == "evaluation-time"
    evaluation_path = Path(payload["evaluation_path"])
    assert evaluation_path.parent == request["evaluation_root"]
    assert cli.main([
        "candidate-bundle", "inspect-evaluation", str(evaluation_path),
        "--evaluation-sha256", payload["evaluation_sha256"],
        "--json", "--home", str(tmp_path / "no-home"),
    ]) == 0
    assert json.loads(capsys.readouterr().out) == payload
    assert workspace_bytes(request) == before
    assert not (tmp_path / "no-home").exists()


def test_cli_invalid_output_is_exit_one_but_inspect_accepts_retained_report(tmp_path, monkeypatch, capsys):
    request, _paths, evaluate = command(tmp_path)
    required = next(item for item in request["contract"].outputs if item.required)
    (request["workspace_path"] / required.path).unlink()
    monkeypatch.setattr(cli, "_config", lambda *_: pytest.fail("initialized Store/home"))
    assert cli.main(evaluate) == 1
    output = capsys.readouterr()
    assert output.err == ""
    payload = json.loads(output.out)
    assert payload["report"]["validity"] == 0
    assert payload["report"]["combined_score"] == 0
    assert payload["harness_invoked"] is False
    assert payload["output_contract_valid"] is False
    assert cli.main([
        "candidate-bundle", "inspect-evaluation", payload["evaluation_path"], "--json",
    ]) == 0
    assert json.loads(capsys.readouterr().out) == payload
    assert not (tmp_path / "no-home").exists()


@pytest.mark.parametrize("flag", [
    "--plan-sha256", "--bundle-sha256", "--contract-sha256", "--admission-sha256",
    "--completion-sha256",
])
def test_cli_passes_all_declaration_and_completion_pins_before_evaluation(tmp_path, monkeypatch, capsys, flag):
    request, _paths, evaluate = command(tmp_path)
    before = list(request["evaluation_root"].iterdir())
    monkeypatch.setattr(cli, "_config", lambda *_: pytest.fail("initialized Store/home"))
    assert cli.main([*evaluate, flag, "0" * 64]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"].startswith("candidate_evaluation_")
    assert str(tmp_path) not in output.err
    assert list(request["evaluation_root"].iterdir()) == before
    assert not (tmp_path / "no-home").exists()


@pytest.mark.parametrize("name", ["admission", "plan", "contract", "evaluator"])
def test_cli_rejects_symlink_declaration_files_without_evaluation(tmp_path, monkeypatch, capsys, name):
    request, paths, evaluate = command(tmp_path)
    path = paths[name]
    original = path.with_suffix(".original.json")
    path.rename(original)
    path.symlink_to(original.name)
    monkeypatch.setattr(cli, "_config", lambda *_: pytest.fail("initialized Store/home"))
    assert cli.main(evaluate) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err) == {"error": "candidate_evaluation_invalid"}
    assert list(request["evaluation_root"].iterdir()) == []
    assert not (tmp_path / "no-home").exists()


@pytest.mark.parametrize("name,content", [
    ("contract", b'{"schema_version":"1","schema_version":"1"}'),
    ("contract", b'{"statement":"\xff"}'),
    ("evaluator", b'{"harness_size":1,"harness_size":2}'),
    ("evaluator", b" " * (MAX_CANDIDATE_EVALUATION_SPEC_BYTES + 1)),
], ids=["contract-duplicate", "contract-non-utf8", "evaluator-duplicate", "evaluator-too-large"])
def test_cli_declaration_decoding_is_bounded_and_strict(tmp_path, monkeypatch, capsys, name, content):
    request, paths, evaluate = command(tmp_path)
    paths[name].write_bytes(content)
    monkeypatch.setattr(cli, "_config", lambda *_: pytest.fail("initialized Store/home"))
    assert cli.main(evaluate) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err) == {"error": "candidate_evaluation_invalid"}
    assert list(request["evaluation_root"].iterdir()) == []


def test_cli_inspect_pin_failure_does_not_change_evidence(tmp_path, monkeypatch, capsys):
    _request, _paths, evaluate = command(tmp_path)
    monkeypatch.setattr(cli, "_config", lambda *_: pytest.fail("initialized Store/home"))
    assert cli.main(evaluate) == 0
    payload = json.loads(capsys.readouterr().out)
    evaluation_path = Path(payload["evaluation_path"])
    before = {str(p.relative_to(evaluation_path)): p.read_bytes() for p in evaluation_path.rglob("*") if p.is_file()}
    assert cli.main([
        "candidate-bundle", "inspect-evaluation", str(evaluation_path),
        "--evaluation-sha256", "0" * 64, "--json",
    ]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err) == {"error": "candidate_evaluation_identity_mismatch"}
    assert before == {str(p.relative_to(evaluation_path)): p.read_bytes() for p in evaluation_path.rglob("*") if p.is_file()}


def test_cli_inspection_rejects_incomplete_evidence_without_repair(tmp_path, monkeypatch, capsys):
    evaluation_path = tmp_path / "incomplete"
    evaluation_path.mkdir()
    monkeypatch.setattr(cli, "_config", lambda *_: pytest.fail("initialized Store/home"))
    assert cli.main([
        "candidate-bundle", "inspect-evaluation", str(evaluation_path),
        "--json", "--home", str(tmp_path / "no-home"),
    ]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err) == {"error": "candidate_evaluation_incomplete"}
    assert list(evaluation_path.iterdir()) == []
    assert not (tmp_path / "no-home").exists()


def test_installed_cli_evaluates_then_inspects_relative_paths(tmp_path):
    request, _paths, evaluate = command(tmp_path)
    launcher = Path(sys.executable).parent / "lunar-evolution"
    if not launcher.is_file():
        pytest.skip("installed CLI unavailable")
    before = workspace_bytes(request)
    local_args = [str(Path(arg).relative_to(tmp_path)) if arg.startswith(str(tmp_path)) else arg for arg in evaluate]
    result = subprocess.run(
        [str(launcher), *local_args], cwd=tmp_path, capture_output=True, text=True,
        timeout=15, check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "evaluated"
    inspected = subprocess.run(
        [str(launcher), "candidate-bundle", "inspect-evaluation",
         str(Path(payload["evaluation_path"]).relative_to(tmp_path)), "--json"],
        cwd=tmp_path, capture_output=True, text=True, timeout=15, check=False,
    )
    assert inspected.returncode == 0, inspected.stderr
    assert json.loads(inspected.stdout) == payload
    assert workspace_bytes(request) == before
    assert not (tmp_path / "no-home").exists()
