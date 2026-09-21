"""Automatic background entry points retain policy and once-only answer admission."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_conversational_automatic_bundle import automatic_setup
from test_preparation_recovery_cli import fail_stage, run_cli, runtime_calls, snapshot

from lunar_evolution import automatic_solve_worker, cli
from lunar_evolution.automatic_solve_lifecycle import (
    AutomaticSolveAlreadyRunning,
    own_automatic_solve,
)
from lunar_evolution.store import Store


def _followup(tmp_path, run_id, command, *extra):
    prefix = {
        "solve": ["solve", "--resume", "--run-id", run_id],
        "resume": ["resume", run_id],
        "answer": ["answer", run_id, "maximize value"],
    }[command]
    return [*prefix, *extra, "--runtime", "mock", "--home", str(tmp_path / "home"), "--json"]


def _waiting(tmp_path, monkeypatch, capsys, *extra):
    runtime, arguments = automatic_setup(tmp_path, monkeypatch, clarify=True)
    code, payload, error = run_cli(capsys, [*arguments, *extra])
    assert code == 0 and error == "" and payload["status"] == "awaiting_input"
    return runtime, Store(tmp_path / "home/state.db"), payload


def test_fresh_detach_stages_under_owner_and_restores_recorded_policy(tmp_path, monkeypatch, capsys):
    runtime, arguments = automatic_setup(tmp_path, monkeypatch)
    secret = "private-detached-cli-fixture-key"
    launches = []
    original_stage = cli._stage_input_files

    def stage(run, store, inputs):
        with pytest.raises(AutomaticSolveAlreadyRunning), own_automatic_solve(run.id, run.workspace):
            pytest.fail("input staging must hold the automatic owner")
        return original_stage(run, store, inputs)

    def launch(config, args, controller, run, owner):
        assert owner.parent_id == run.id and owner.lock_fd is not None
        assert (run.workspace / "data/raw/value").read_text() == "10"
        command = cli._automatic_runtime_command(config, args, run)
        assert "--api-key" not in command and secret not in " ".join(command)
        for option in (
            "--multi-file", "--solve-wall-timeout", "--candidate-generation-max-steps",
            "--evaluator-preparation-timeout", "--evaluator-preparation-wall-timeout",
        ):
            assert option not in command, "the durable handoff is the policy authority"
        request = cli._latest_evolution_request(controller.store, run.id)
        restored = cli._evolution_args(cli.build_parser().parse_args(command), request)
        assert restored.multi_file and restored.evolve and restored.compile_evaluator
        assert (restored.timeout, restored.evaluator_preparation_timeout,
                restored.evaluator_preparation_wall_timeout, restored.solve_wall_timeout,
                restored.candidate_generation_max_steps) == (3, 2, 4, 30, 12)
        assert secret not in json.dumps(controller.store.list_events(run.id))
        assert runtime_calls(runtime) == (0, 0, 0, 0, 0)
        launches.append(run.id)

    monkeypatch.setattr(cli, "_stage_input_files", stage)
    monkeypatch.setattr(automatic_solve_worker, "launch_automatic_solve", launch)
    code, payload, error = run_cli(capsys, [
        *arguments, "--detach", "--api-key", secret, "--solve-wall-timeout", "30",
        "--evaluator-preparation-timeout", "2", "--evaluator-preparation-wall-timeout", "4",
        "--candidate-generation-max-steps", "12",
    ])
    assert code == 0 and error == "" and payload["detached"] is True
    assert launches == [payload["run_id"]]
    assert payload["status"] == payload["run_status"] == "pending"
    assert secret not in json.dumps(payload)


@pytest.mark.parametrize("command", [["solve", "goal"], ["answer", "parent", "continue"]])
def test_child_runtime_arguments_preserve_identity_and_tool_settings(tmp_path, command):
    args = cli.build_parser().parse_args([
        *command, "--runtime", "openai-compatible", "--endpoint", "http://127.0.0.1:1/v1",
        "--model", "fixture-model", "--model-profile", str(tmp_path / "profile.json"),
        "--api-key", "private-fixture-key", "--agent-loop", "--max-steps", "17",
        "--allow-exec", "--memory", "--session-history", "--workers", "2",
    ])
    argv = cli._automatic_runtime_command(SimpleNamespace(home=tmp_path), args, SimpleNamespace(id="parent"))
    assert "private-fixture-key" not in " ".join(argv) and "--api-key" not in argv
    child = cli.build_parser().parse_args(argv)
    for name in (
        "runtime", "endpoint", "model", "model_profile", "agent_loop", "max_steps",
        "allow_exec", "memory", "session_history", "workers",
    ):
        assert getattr(child, name) == getattr(args, name)
    assert child.command == "solve" and child.resume and child.run_id == "parent"


@pytest.mark.parametrize("options", [
    ["--solve-wall-timeout", "31"], ["--candidate-generation-max-steps", "13"],
    ["--evaluator-preparation-timeout", "3"], ["--evaluator-command", "/not-used"],
])
def test_detached_answer_rejects_static_mismatch_without_consuming_input(
    tmp_path, monkeypatch, capsys, options,
):
    runtime, store, waiting = _waiting(
        tmp_path, monkeypatch, capsys, "--solve-wall-timeout", "30",
        "--candidate-generation-max-steps", "12", "--evaluator-preparation-timeout", "2",
    )
    parent, workspace = waiting["run_id"], Path(waiting["workspace"])
    before, pending = snapshot(store, parent, workspace), store.pending_input(parent)
    monkeypatch.setattr(cli, "build_runtime", lambda *a, **k: pytest.fail("invalid policy built a runtime"))
    monkeypatch.setattr(automatic_solve_worker, "launch_automatic_solve", lambda *a: pytest.fail("invalid policy launched"))
    code, payload, error = run_cli(capsys, _followup(tmp_path, parent, "answer", "--detach", *options))
    assert code == 2 and payload is None and json.loads(error)["error"]
    assert snapshot(store, parent, workspace) == before and store.pending_input(parent) == pending
    assert runtime_calls(runtime) == (1, 0, 0, 0, 1)


def test_detached_answer_returns_accepted_handle_before_more_model_work(tmp_path, monkeypatch, capsys):
    runtime, store, waiting = _waiting(tmp_path, monkeypatch, capsys)
    parent = waiting["run_id"]
    launches = []

    def launch(config, args, controller, run, owner):
        assert run.id == owner.parent_id == parent and owner.lock_fd is not None
        assert store.pending_input(parent) is None
        answer = [item for item in store.list_artifacts(parent) if item["kind"] == "input" and item["path"].endswith("/input-answer.json")]
        assert len(answer) == 1
        assert json.loads((run.workspace / answer[0]["path"]).read_text()) == {"answer": "maximize value"}
        assert runtime_calls(runtime) == (1, 0, 0, 0, 1)
        launches.append(parent)

    monkeypatch.setattr(automatic_solve_worker, "launch_automatic_solve", launch)
    code, accepted, error = run_cli(capsys, _followup(tmp_path, parent, "answer", "--detach"))
    assert code == 0 and error == "" and accepted["detached"] is True
    assert accepted["run_id"] == parent and accepted["answer_path"] and launches == [parent]
    assert accepted["input_request"] is None
    code, payload, error = run_cli(capsys, _followup(tmp_path, parent, "answer", "--detach"))
    assert code == 2 and payload is None and "not awaiting input" in json.loads(error)["error"]
    assert launches == [parent]


def test_launch_failure_retains_accepted_answer_for_explicit_resume(tmp_path, monkeypatch, capsys):
    runtime, store, waiting = _waiting(tmp_path, monkeypatch, capsys)
    parent = waiting["run_id"]

    def failed_launch(*args, **kwargs):
        raise OSError("fixture process launch failure")

    with monkeypatch.context() as patch:
        patch.setattr(automatic_solve_worker.subprocess, "Popen", failed_launch)
        code, payload, error = run_cli(capsys, _followup(tmp_path, parent, "answer", "--detach"))
    assert code == 2 and payload is None and "explicit resume" in json.loads(error)["error"]
    assert store.pending_input(parent) is None
    assert store.get_run(parent).status.value not in {"failed", "cancelled"}
    assert store.get_run(parent).runner_pid is None
    answers = [item for item in store.list_artifacts(parent) if item["kind"] == "input" and item["path"].endswith("/input-answer.json")]
    assert len(answers) == 1 and runtime_calls(runtime) == (1, 0, 0, 0, 1)
    code, resumed, error = run_cli(capsys, _followup(tmp_path, parent, "resume"))
    assert code == 0 and error == "" and resumed["run_id"] == parent
    assert resumed["status"] == "succeeded"
    assert [item for item in store.list_artifacts(parent) if item["kind"] == "input" and item["path"].endswith("/input-answer.json")] == answers
    assert runtime.contract_calls == 2


@pytest.mark.parametrize("command", ["solve", "resume"])
def test_accepted_recovery_launch_does_not_inherit_previous_preparation_exit_code(
    tmp_path, monkeypatch, capsys, command,
):
    runtime, arguments = automatic_setup(tmp_path, monkeypatch)
    with monkeypatch.context() as patch:
        fail_stage(patch, runtime, "evaluator_compile")
        code, failed, error = run_cli(capsys, arguments)
    assert code == 1 and error == "" and failed["status"] == "failed"
    assert failed["evolution"]["preparation"]["recoverable"] is True
    launches = []
    monkeypatch.setattr(
        automatic_solve_worker, "launch_automatic_solve",
        lambda config, args, controller, run, owner: launches.append(run.id),
    )
    code, accepted, error = run_cli(capsys, _followup(tmp_path, failed["run_id"], command, "--detach"))
    assert code == 0 and error == "" and launches == [failed["run_id"]]
    assert accepted["launch_status"] == "accepted" and accepted["detached"] is True
    assert accepted["evolution"]["preparation"] == failed["evolution"]["preparation"]


@pytest.mark.parametrize("command", ["solve", "resume", "answer"])
@pytest.mark.parametrize("marker", [None, True, 2])
def test_detach_rejects_legacy_or_malformed_lifecycle_before_runtime(
    tmp_path, monkeypatch, capsys, command, marker,
):
    _, store, waiting = _waiting(tmp_path, monkeypatch, capsys)
    parent, workspace = waiting["run_id"], Path(waiting["workspace"])
    request = cli._latest_evolution_request(store, parent)
    if marker is None:
        request.pop("automatic_lifecycle_version")
    else:
        request["automatic_lifecycle_version"] = marker
    with store._connect() as connection:
        connection.execute(
            "UPDATE events SET payload = ? WHERE run_id = ? AND type = 'evolution_requested'",
            (json.dumps(request), parent),
        )
    before = snapshot(store, parent, workspace)
    monkeypatch.setattr(cli, "build_runtime", lambda *a, **k: pytest.fail("legacy detach built a runtime"))
    code, payload, error = run_cli(capsys, _followup(tmp_path, parent, command, "--detach"))
    assert code == 2 and payload is None and "lifecycle-enabled" in json.loads(error)["error"]
    assert snapshot(store, parent, workspace) == before


@pytest.mark.parametrize("state", ["awaiting_input", "cancelled", "failed"])
def test_detach_resume_does_not_launch_waiting_or_terminal_parent(tmp_path, monkeypatch, capsys, state):
    runtime, store, waiting = _waiting(tmp_path, monkeypatch, capsys, "--solve-wall-timeout", "1")
    parent, workspace = waiting["run_id"], Path(waiting["workspace"])
    if state == "cancelled":
        assert store.cancel_run(parent)
    elif state == "failed":
        assert store.fail_budget(parent, "solve_wall_timeout", 2, 1, "fixture exhausted")
    before, calls = snapshot(store, parent, workspace), runtime_calls(runtime)
    monkeypatch.setattr(automatic_solve_worker, "launch_automatic_solve", lambda *a: pytest.fail("inactive parent launched"))
    for command in ("solve", "resume"):
        code, payload, error = run_cli(capsys, _followup(tmp_path, parent, command, "--detach"))
        assert code == (0 if state == "awaiting_input" else 1) and error == "", error
        assert payload["status"] == state and "detached" not in payload
    assert snapshot(store, parent, workspace) == before and runtime_calls(runtime) == calls


@pytest.mark.parametrize("command", ["solve", "resume", "answer"])
def test_detach_continuation_rejects_ordinary_conversation(tmp_path, monkeypatch, capsys, command):
    runtime, _ = automatic_setup(tmp_path, monkeypatch, clarify=True)
    code, waiting, error = run_cli(capsys, [
        "solve", "Choose an objective", "--runtime", "mock",
        "--home", str(tmp_path / "home"), "--json",
    ])
    assert code == 0 and error == "" and waiting["status"] == "awaiting_input"
    store = Store(tmp_path / "home/state.db")
    parent, workspace = waiting["run_id"], Path(waiting["workspace"])
    before, calls = snapshot(store, parent, workspace), runtime_calls(runtime)
    monkeypatch.setattr(cli, "build_runtime", lambda *a, **k: pytest.fail("unsupported detach built runtime"))
    code, payload, error = run_cli(capsys, _followup(tmp_path, parent, command, "--detach"))
    assert code == 2 and payload is None and "automatic multi-file" in json.loads(error)["error"]
    assert snapshot(store, parent, workspace) == before and runtime_calls(runtime) == calls


def test_detach_successful_resume_is_read_only(tmp_path, monkeypatch, capsys):
    runtime, arguments = automatic_setup(tmp_path, monkeypatch)
    code, completed, error = run_cli(capsys, arguments)
    assert code == 0 and error == "" and completed["status"] == "succeeded"
    store = Store(tmp_path / "home/state.db")
    parent, workspace = completed["run_id"], Path(completed["workspace"])
    before, calls = snapshot(store, parent, workspace), runtime_calls(runtime)
    monkeypatch.setattr(automatic_solve_worker, "launch_automatic_solve", lambda *a: pytest.fail("successful parent launched"))
    for command in ("solve", "resume"):
        code, payload, error = run_cli(capsys, _followup(tmp_path, parent, command, "--detach"))
        assert code == 0 and error == "" and payload["status"] == "succeeded"
        assert "detached" not in payload
    assert snapshot(store, parent, workspace) == before and runtime_calls(runtime) == calls


def test_private_worker_owner_rejects_a_different_parent_before_initialization(tmp_path, capsys):
    owner = SimpleNamespace(parent_id="reserved-parent")
    assert cli.main(_followup(tmp_path, "other-parent", "solve"), _automatic_owner=owner) == 2
    assert "invalid automatic solve worker" in json.loads(capsys.readouterr().err)["error"]
    assert not (tmp_path / "home/state.db").exists()
