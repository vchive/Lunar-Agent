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
    assert status_payload["tasks"][0]["evaluation"]["details"]["kind"] == "non_empty"

    assert main(["events", run_payload["run_id"], "--json", "--home", str(tmp_path)]) == 0
    events = json.loads(capsys.readouterr().out)
    evaluation = next(event for event in events if event["type"] == "task_evaluated")
    assert evaluation["payload"]["details"]["kind"] == "non_empty"


def test_cli_status_json_exposes_route_profiles_and_budget(tmp_path: Path, capsys) -> None:
    assert main(["run", "analyze this CSV", "--runtime", "mock", "--json", "--home", str(tmp_path)]) == 0
    run_id = json.loads(capsys.readouterr().out)["run_id"]
    assert main(["status", run_id, "--json", "--home", str(tmp_path)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["route"]["domain"] == "data"
    assert status["run"]["evaluator_profile"] == "data"
    assert status["budget"]["max_tool_steps"] == 40


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


def test_detached_agent_loop_options_propagate(tmp_path: Path, capsys, monkeypatch) -> None:
    calls = []

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return object()

    monkeypatch.setattr("famou.cli.subprocess.Popen", fake_popen)
    assert (
        main(
            [
                "run",
                "long model goal",
                "--runtime",
                "openai-compatible",
                "--endpoint",
                "http://127.0.0.1:1234/v1",
                "--model",
                "fixture",
                "--agent-loop",
                "--max-steps",
                "7",
                "--allow-exec",
                "--memory",
                "--session-history",
                "--detach",
                "--json",
                "--home",
                str(tmp_path),
            ]
        )
        == 0
    )
    capsys.readouterr()
    command = calls[0][0]
    assert "--agent-loop" in command
    assert command[command.index("--max-steps") + 1] == "7"
    assert "--allow-exec" in command and "--memory" in command
    assert "--session-history" in command


def test_cli_memory_inspection_is_json(tmp_path: Path, capsys) -> None:
    from famou.memory import MemoryStore

    memory = MemoryStore(tmp_path / "state.db")
    memory.initialize()
    memory.remember("remembered deployment decision", source="test")
    assert main(["memory", "deployment", "--json", "--home", str(tmp_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    assert payload[0]["content"] == "remembered deployment decision"


def test_cli_master_decide_and_plan_revision_commands(tmp_path: Path, capsys) -> None:
    assert main(["decide", "What is SQLite WAL?", "--json", "--home", str(tmp_path)]) == 0
    decision = json.loads(capsys.readouterr().out)
    assert decision["action"] == "answer"
    assert "plan" not in decision

    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "goal": "create a report and verify it",
                "plan_id": "plan-cli",
                "tasks": [{"id": "one", "title": "One", "prompt": "write one"}],
            }
        ),
        encoding="utf-8",
    )
    assert main(["plan", str(plan_path), "--runtime", "mock", "--json", "--home", str(tmp_path)]) == 0
    created = json.loads(capsys.readouterr().out)
    assert created["plan_version"] == 1
    run_id = created["run_id"]

    assert main(["plan", run_id, "--json", "--home", str(tmp_path)]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["plan_id"] == "plan-cli"
    assert inspected["version"] == 1

    patch_path = tmp_path / "patch.json"
    patch_path.write_text(
        json.dumps(
            {
                "plan_id": "plan-cli",
                "base_version": 1,
                "reason": "add verification",
                "operations": [
                    {"op": "add_task", "task": {"id": "check", "prompt": "verify output", "depends_on": ["one"]}}
                ],
            }
        ),
        encoding="utf-8",
    )
    assert main(["patch", run_id, str(patch_path), "--json", "--home", str(tmp_path)]) == 0
    patched = json.loads(capsys.readouterr().out)
    assert patched["plan_version"] == 2

    assert main(["status", run_id, "--json", "--home", str(tmp_path)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["run"]["current_plan_version"] == 2
    assert status["tasks"][0]["plan_task_id"] == "one"


def test_cli_replan_inherits_plan_id_and_stale_patch_is_json_error(tmp_path: Path, capsys) -> None:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps({"goal": "replan me", "plan_id": "plan-replan", "tasks": [{"id": "one", "prompt": "one"}]}),
        encoding="utf-8",
    )
    assert main(["plan", str(plan_path), "--json", "--home", str(tmp_path)]) == 0
    run_id = json.loads(capsys.readouterr().out)["run_id"]
    replacement = tmp_path / "replacement.json"
    replacement.write_text(
        json.dumps({"goal": "replan me better", "tasks": [{"id": "one", "prompt": "one"}]}),
        encoding="utf-8",
    )
    assert main(["replan", run_id, str(replacement), "--json", "--home", str(tmp_path)]) == 0
    replanned = json.loads(capsys.readouterr().out)
    assert replanned["plan_id"] == "plan-replan" and replanned["plan_version"] == 2

    stale = tmp_path / "stale.json"
    stale.write_text(
        json.dumps(
            {
                "plan_id": "plan-replan",
                "base_version": 1,
                "reason": "stale",
                "operations": [{"op": "update_task", "id": "one", "prompt": "old"}],
            }
        ),
        encoding="utf-8",
    )
    assert main(["patch", run_id, str(stale), "--json", "--home", str(tmp_path)]) == 2
    error = json.loads(capsys.readouterr().err)
    assert "does not match" in error["error"]


def test_cli_deliver_rejects_failed_run(tmp_path: Path, capsys) -> None:
    # An unknown/failed handle must return a machine-readable error rather than a deliver decision.
    assert main(["deliver", "missing-run", "--json", "--home", str(tmp_path)]) == 2
    error = json.loads(capsys.readouterr().err)
    assert "unknown run" in error["error"]
