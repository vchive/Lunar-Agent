"""Reject double-encoded argv without changing command execution or model-led correction."""

import json
import shlex
import subprocess
from copy import deepcopy

import pytest

from famou.agent_loop import AgentLoopRuntime
from famou.model_profile import UsageLedger
from famou.profiles import ModelProfile
from famou.runtime import ModelTurn, ToolCall
from famou.tools import LocalToolRegistry
from famou.transcript import SessionTranscript

SECRET = "CALLER-PRIVATE-SENTINEL"


@pytest.mark.parametrize("command", [
    '["python3", "--version"]', ' \n ["python3", "--version"] \t', "[]", "[1, null, true]",
    '[{"private": "' + SECRET + '"}]', json.dumps(["fixture", SECRET]),
])
def test_json_encoded_arrays_return_static_correctable_error_without_dispatch(tmp_path, monkeypatch, command):
    calls = []

    def process(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr("famou.tools.subprocess.run", process)
    result = LocalToolRegistry(allow_exec=True).execute("run_command", {"command": command}, tmp_path)
    assert not result.success and not result.artifacts
    assert calls == []
    assert "Pass the argv array directly" in result.output
    assert '{"command": ["python3", "--version"]}' in result.output
    assert "ordinary command string" in result.output
    assert SECRET not in result.output and len(result.output.encode()) <= 512
    reference = LocalToolRegistry(allow_exec=True).execute("run_command", {"command": "[]"}, tmp_path)
    assert result.output == reference.output
    assert calls == []


@pytest.mark.parametrize("command", [
    "fixture --check", '[ -f "file with spaces" ]', "[fixture --check]", '["fixture", --check]',
    '{"fixture": true}', "null", "42", '"fixture --check"', '["fixture"] trailing',
])
def test_non_array_json_and_ordinary_strings_preserve_shlex_and_process_contract(tmp_path, monkeypatch, command):
    calls = []
    environment = {"TASK_SETTING": "fixture-value"}

    def process(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 7, stdout="fixture-stdout", stderr="fixture-stderr")

    monkeypatch.setattr("famou.tools.subprocess.run", process)
    monkeypatch.setattr("famou.tools.time.monotonic", lambda: 100)
    registry = LocalToolRegistry(allow_exec=True, command_timeout=30, command_environment=environment)
    with registry.execution_deadline(103):
        result = registry.execute("run_command", {"command": command}, tmp_path)
    assert calls == [(shlex.split(command), {
        "cwd": tmp_path, "env": environment, "shell": False, "text": True,
        "capture_output": True, "timeout": 3, "check": False,
    })]
    assert not result.success and not result.artifacts
    assert result.output == "exit_code=7\nstdout:\nfixture-stdout\nstderr:\nfixture-stderr"


@pytest.mark.parametrize("command", [
    ["fixture", "an argument with spaces"], ["[", "-f", "file with spaces", "]"],
    ['["literal-executable"]', "--check"],
])
def test_actual_argv_arrays_remain_exact(tmp_path, monkeypatch, command):
    calls = []

    def process(argv, **kwargs):
        calls.append(argv)
        assert kwargs["shell"] is False
        return subprocess.CompletedProcess(argv, 0, stdout="fixture", stderr="")

    monkeypatch.setattr("famou.tools.subprocess.run", process)
    result = LocalToolRegistry(allow_exec=True).execute("run_command", {"command": command}, tmp_path)
    assert result.success and calls == [command]


def test_deep_json_probe_failure_keeps_existing_string_path(tmp_path, monkeypatch):
    command = "[" * 20000 + "]" * 20000
    with pytest.raises(RecursionError):
        json.loads(command)
    calls = []

    def process(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="fixture", stderr="")

    monkeypatch.setattr("famou.tools.subprocess.run", process)
    result = LocalToolRegistry(allow_exec=True).execute("run_command", {"command": command}, tmp_path)
    assert result.success and calls == [shlex.split(command)]


def test_json_value_error_probe_keeps_existing_string_path(tmp_path, monkeypatch):
    command = "[12345]"
    calls = []

    def invalid_integer(*args, **kwargs):
        raise ValueError("fixture integer digit limit")

    def process(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="fixture", stderr="")

    monkeypatch.setattr("famou.tools.json.loads", invalid_integer)
    monkeypatch.setattr("famou.tools.subprocess.run", process)
    result = LocalToolRegistry(allow_exec=True).execute("run_command", {"command": command}, tmp_path)
    assert result.success and calls == [shlex.split(command)]


@pytest.mark.parametrize("command", [[], ["fixture", 1], [None], [True], [["fixture"]]])
def test_invalid_real_arrays_keep_existing_validation(tmp_path, monkeypatch, command):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid arrays must not launch a subprocess")

    monkeypatch.setattr("famou.tools.subprocess.run", forbidden)
    result = LocalToolRegistry(allow_exec=True).execute("run_command", {"command": command}, tmp_path)
    assert not result.success and not result.artifacts
    assert result.output == "tool_error: ToolError: command must be a non-empty string or string array"


def test_disabled_execution_precedes_json_diagnostic(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("disabled commands must not be parsed or dispatched")

    monkeypatch.setattr("famou.tools.json.loads", forbidden)
    monkeypatch.setattr("famou.tools.subprocess.run", forbidden)
    result = LocalToolRegistry().execute("run_command", {"command": "[]"}, tmp_path)
    assert not result.success and "run_command is disabled" in result.output
    assert "argv" not in result.output


def test_model_corrects_next_tool_call_without_hidden_retry_or_usage_reset(tmp_path, monkeypatch):
    argv = ["fixture-executable", "--check"]
    bad_command = json.dumps(argv)
    calls, observed_usage, requests = [], [], []
    profile = ModelProfile(
        "diagnostic-fixture", "fixture", max_steps=2, max_total_tokens=40, max_cost_micros=40,
        input_cost_per_1k_micros=1000, output_cost_per_1k_micros=1000,
    )
    ledger = UsageLedger(profile)

    def process(command, **kwargs):
        calls.append(command)
        assert kwargs["shell"] is False
        return subprocess.CompletedProcess(command, 0, stdout="fixture-success", stderr="")

    class Model:
        def complete(self, messages, tools=(), timeout=None):
            del tools, timeout
            requests.append(deepcopy(messages))
            observed_usage.append(ledger.snapshot.total_tokens)
            usage = {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}
            if len(requests) == 1:
                return ModelTurn("", (ToolCall("bad", "run_command", {"command": bad_command}),),
                                 response_model="fixture", usage=usage)
            if len(requests) == 2:
                assert messages[-1]["role"] == "tool"
                assert "Pass the argv array directly" in messages[-1]["content"]
                assert calls == []
                return ModelTurn("", (ToolCall("corrected", "run_command", {"command": argv}),),
                                 response_model="fixture", usage=usage)
            assert len(requests) == 3 and calls == [argv]
            assert "exit_code=0" in messages[-1]["content"]
            return ModelTurn("completed", response_model="fixture", usage=usage)

    monkeypatch.setattr("famou.tools.subprocess.run", process)
    transcript = SessionTranscript(tmp_path / "transcript.jsonl")
    runtime = AgentLoopRuntime(
        Model(), tools=LocalToolRegistry(allow_exec=True), max_steps=2,
        profile=profile, transcript=transcript,
    )
    result = runtime.run("exercise the fixture command", tmp_path, usage_ledger=ledger)
    assert result.text == "completed" and calls == [argv]
    assert observed_usage == [0, 5, 10]
    assert ledger.snapshot.total_tokens == ledger.snapshot.cost_micros == 15
    assert ledger.snapshot.rounds == 3 and ledger.usage_complete
    assert runtime.last_tool_steps == 2
    assert result.metadata["total_tokens"] == result.metadata["cost_micros"] == "15"
    assert result.metadata["turns"] == "3" and result.metadata["tool_steps"] == "2"
    arguments = [
        json.loads(call["function"]["arguments"])
        for message in transcript.load() for call in message.get("tool_calls", [])
    ]
    assert arguments == [{"command": bad_command}, {"command": argv}]
    assert [message["tool_call_id"] for message in transcript.load() if message["role"] == "tool"] == [
        "bad", "corrected",
    ]
