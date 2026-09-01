import json
from io import StringIO
from pathlib import Path

from famou.cli import main


def test_cli_run_and_status_use_repository_runtime(tmp_path: Path, capsys) -> None:
    assert main(["run", "cli goal", "--runtime", "mock", "--home", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    run_id = next(line.split(": ", 1)[1] for line in output.splitlines() if line.startswith("run_id:"))

    assert main(["status", run_id, "--home", str(tmp_path)]) == 0
    status_output = capsys.readouterr().out
    assert "status: succeeded" in status_output


def test_cli_json_contract_and_stdin_goal(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdin", StringIO("stdin goal"))
    assert main(["run", "-", "--runtime", "mock", "--json", "--home", str(tmp_path)]) == 0
    run_payload = json.loads(capsys.readouterr().out)
    assert run_payload["status"] == "succeeded"

    assert main(["status", run_payload["run_id"], "--json", "--home", str(tmp_path)]) == 0
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["run"]["goal"] == "stdin goal"
    assert status_payload["tasks"][0]["state"] == "succeeded"
