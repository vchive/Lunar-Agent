import json
import sys
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


def test_cli_detach_returns_durable_handle_before_execution(tmp_path: Path, capsys, monkeypatch) -> None:
    calls = []

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return object()

    monkeypatch.setattr("famou.cli.subprocess.Popen", fake_popen)
    assert (
        main(
            [
                "run",
                "long goal",
                "--runtime",
                "mock",
                "--detach",
                "--json",
                "--home",
                str(tmp_path),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pending"
    assert payload["run_id"]
    assert calls[0][0][:4] == [sys.executable, "-m", "famou", "resume"]
    assert calls[0][1]["start_new_session"] is True

    assert main(["status", payload["run_id"], "--json", "--home", str(tmp_path)]) == 0
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["run"]["status"] == "pending"


def test_cli_accepts_json_plan_and_rejects_malformed_plan(tmp_path: Path, capsys) -> None:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "goal": "cli plan",
                "tasks": [
                    {"id": "one", "prompt": "one"},
                    {"id": "two", "prompt": "two", "depends_on": ["one"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    assert main(["run", "--plan", str(plan_path), "--runtime", "mock", "--json", "--home", str(tmp_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "succeeded"

    bad_path = tmp_path / "bad.json"
    bad_path.write_text(
        '{"goal":"bad","tasks":[{"id":"a","prompt":"a","depends_on":["a"]}]}',
        encoding="utf-8",
    )
    assert main(["run", "--plan", str(bad_path), "--json", "--home", str(tmp_path / "bad-home")]) == 2
    assert "depend" in capsys.readouterr().err


def test_detached_model_options_propagate_without_api_key_in_argv(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    calls = []

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return object()

    monkeypatch.setattr("famou.cli.subprocess.Popen", fake_popen)
    assert (
        main(
            [
                "run",
                "model goal",
                "--runtime",
                "openai-compatible",
                "--endpoint",
                "http://127.0.0.1:1234/v1",
                "--model",
                "fixture",
                "--api-key",
                "secret-key",
                "--detach",
                "--json",
                "--home",
                str(tmp_path),
            ]
        )
        == 0
    )
    capsys.readouterr()
    command, kwargs = calls[0]
    assert "--endpoint" in command and "--model" in command
    assert "--api-key" not in command
    assert kwargs["env"]["FAMOU_API_KEY"] == "secret-key"
