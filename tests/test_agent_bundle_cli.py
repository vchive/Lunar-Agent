"""Explicit Agent source producers keep bundle execution and exact evaluation authority."""
from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

import pytest
from test_bundle_population import MAIN_SOURCE, draft_for_score
from test_bundle_population_cli import command

from famou import cli
from famou.evolution import CandidateArchive
from famou.runtime import MockRuntime, ModelTurn, OpenAICompatibleRuntime, RuntimeResult


def agent_command(tmp_path, mode="command"):
    context, args = command(tmp_path)
    index = args.index("--generator-command")
    del args[index:index + 2]
    worker = tmp_path / "source-agent.py"
    worker.write_text(
        "import json, sys\nfrom pathlib import Path\n"
        "raw = sys.stdin.read()\n"
        "if sys.argv[1] == 'command':\n"
        "    request = json.loads(raw)\n"
        "    workspace = Path(request['workspace'])\n"
        "    prompt = request['prompt']\n"
        "else:\n"
        "    workspace = Path.cwd()\n"
        "    prompt = raw\n"
        "assert (workspace / 'context/inputs/value').read_text() == '10'\n"
        "counter = Path(__file__).with_name('source-agent-calls')\n"
        "count = len(counter.read_text()) if counter.exists() else 0\n"
        "if count >= 2:\n"
        "    assert (workspace / 'context/parent/source/solve/helper.py').is_file()\n"
        "    assert (workspace / 'context/parent/files.json').is_file()\n"
        "assert not (workspace / 'harness.py').exists()\n"
        "assert 'bundle-population-fixture' in prompt\n"
        "score = [1, 2, 999, 9][count]\n"
        "counter.write_text('x' * (count + 1))\n"
        "helper = f'def choose(limit):\\n    return {score}\\n'\n"
        f"draft = {{'files': {{'solve/main.py': {MAIN_SOURCE!r}, 'solve/helper.py': helper}}, "
        "'entrypoint': 'solve/main.py', 'metadata': {'producer_score_claim': 999999}}\n"
        "print(json.dumps(draft))\n"
    )
    executable = shlex.join((str(Path(sys.executable).resolve()), str(worker), mode))
    if mode == "command":
        args.extend(("--agent-command", executable))
    else:
        args.extend(("--agent-runtime", "subprocess", "--agent-runtime-command", executable))
    args.extend(("--agent-name", "source-fixture", "--agent-role", "solver",
                 "--agent-capability", "read_files"))
    return context, args


@pytest.mark.parametrize("mode", ["command", "subprocess"])
def test_cli_agent_generates_complete_bundles_and_resumes_without_invocation(tmp_path, monkeypatch, capsys, mode):
    context, args = agent_command(tmp_path, mode)
    monkeypatch.chdir(tmp_path)
    args[args.index("--workspace") + 1] = "run"
    assert cli.main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "completed"
    assert result["best_score"] == 9
    assert result["evaluated_candidates"] == 4
    assert result["valid_candidates"] == 3
    archive = CandidateArchive(context.workspace)
    assert [item.evaluation.combined_score for item in archive.records()] == [1, 2, 0, 9]
    assert all(item.bundle_evidence is not None for item in archive.records())
    assert archive.read_state()["config"]["evaluator_fingerprint"] == context.bundle_pipeline.evaluator.digest()
    delivered = Path(result["delivery"]["delivery_path"])
    assert json.loads((delivered / "output/result.json").read_text())["value"] == 9
    assert (tmp_path / "source-agent-calls").read_text() == "xxxx"
    candidate_calls = {str(path): path.read_bytes() for path in context.workspace.rglob("count")}
    assert len(candidate_calls) == 4

    assert cli.main([*args, "--resume", "--run-id", result["run_id"]]) == 0
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["best_candidate_id"] == result["best_candidate_id"]
    assert resumed["delivery"]["delivery_sha256"] == result["delivery"]["delivery_sha256"]
    assert (tmp_path / "source-agent-calls").read_text() == "xxxx"
    assert {str(path): path.read_bytes() for path in context.workspace.rglob("count")} == candidate_calls


def test_cli_native_mock_adapter_only_generates_source_and_uses_profile_harness(tmp_path, monkeypatch, capsys):
    context, args = command(tmp_path)
    index = args.index("--generator-command")
    del args[index:index + 2]
    args.extend(("--agent-runtime", "mock"))
    requests = []

    class SourceRuntime(MockRuntime):
        def run(self, prompt, workspace, timeout=None):
            requests.append((prompt, workspace, timeout))
            assert (workspace / "context/inputs/value").read_text() == "10"
            source = draft_for_score((1, 2, 999, 9)[len(requests) - 1])
            return RuntimeResult(json.dumps({"entrypoint": source.filename, "files": source.source_files}))

    runtime = SourceRuntime()
    monkeypatch.setattr(cli, "build_runtime", lambda *_: runtime)
    assert cli.main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["best_score"] == 9
    assert len(requests) == 4
    assert all(timeout == 3 for _, _, timeout in requests)
    assert CandidateArchive(context.workspace).best().evaluation.evaluator_id == "bundle-population-fixture"


def test_cli_openai_loop_options_use_offline_source_fixture_and_keep_evaluator_pin(tmp_path, monkeypatch, capsys):
    context, args = command(tmp_path)
    index = args.index("--generator-command")
    del args[index:index + 2]
    key = "sk-source-fixture-secret-1234567890123456"
    args.extend((
        "--agent-runtime", "openai-compatible", "--agent-runtime-endpoint", "http://example.invalid/v1",
        "--agent-runtime-model", "offline-fixture", "--agent-runtime-api-key", key,
        "--agent-runtime-loop", "--agent-runtime-max-steps", "2", "--agent-runtime-allow-exec",
        "--agent-runtime-memory", "--agent-runtime-session-history",
    ))
    calls = []

    class OfflineModel(OpenAICompatibleRuntime):
        def complete(self, messages, tools=(), timeout=None):
            calls.append((messages, tools, timeout))
            source = draft_for_score((1, 2, 999, 9)[len(calls) - 1])
            return ModelTurn(json.dumps({"entrypoint": source.filename, "files": source.source_files}))

    def build(name, command=None, endpoint=None, model=None, api_key=None):
        del command
        return OfflineModel(endpoint, model, api_key) if name == "openai-compatible" else MockRuntime()

    monkeypatch.setattr(cli, "build_runtime", build)
    assert cli.main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["best_score"] == 9
    assert len(calls) == 4 and all(tools for _, tools, _ in calls)
    state = CandidateArchive(context.workspace).read_state()
    assert state["config"]["evaluator_fingerprint"] == context.bundle_pipeline.evaluator.digest()
    assert len(state["config"]["generator_fingerprint"]) == 64
    assert key not in json.dumps(state)
    assert len(list(context.workspace.rglob("session-transcript.jsonl"))) == 4


@pytest.mark.parametrize("source_mode,target_mode", [
    ("command-generator", "agent-command"),
    ("agent-command", "agent-runtime"),
    ("agent-runtime", "command-generator"),
])
def test_cli_bundle_resume_rejects_producer_mode_change(tmp_path, capsys, source_mode, target_mode):
    if source_mode == "command-generator":
        context, args = command(tmp_path)
    else:
        context, args = agent_command(tmp_path, "command" if source_mode == "agent-command" else "subprocess")
    assert cli.main(args) == 0
    result = json.loads(capsys.readouterr().out)
    previous = CandidateArchive(context.workspace).read_state()["config"]["generator_fingerprint"]
    changed = list(args)
    source_flag = {
        "command-generator": "--generator-command", "agent-command": "--agent-command",
        "agent-runtime": "--agent-runtime-command",
    }[source_mode]
    same_command = args[args.index(source_flag) + 1]
    agent_settings = []
    for flag in ("--agent-name", "--agent-role", "--agent-capability"):
        if flag in args:
            agent_settings.extend((flag, args[args.index(flag) + 1]))
    for name in ("--generator-command", "--agent-command", "--agent-runtime", "--agent-runtime-command",
                 "--agent-name", "--agent-role", "--agent-capability"):
        if name in changed:
            index = changed.index(name)
            del changed[index:index + 2]
    if target_mode == "command-generator":
        changed.extend(("--generator-command", same_command))
    elif target_mode == "agent-command":
        changed.extend(("--agent-command", same_command, *agent_settings))
    else:
        changed.extend(("--agent-runtime", "subprocess", "--agent-runtime-command", same_command,
                        *agent_settings))

    assert cli.main([*changed, "--resume", "--run-id", result["run_id"]]) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "terminal_evolution_state_mismatch"
    assert CandidateArchive(context.workspace).read_state()["config"]["generator_fingerprint"] == previous
    assert sum(len(path.read_bytes()) for path in context.workspace.rglob("count")) == 4


@pytest.mark.parametrize("options", [
    ["--agent-runtime-command", "unused"],
    ["--agent-runtime-endpoint", "http://localhost:9"],
    ["--agent-runtime-api-key", "unused"],
    ["--agent-runtime-max-steps", "40"],
    ["--agent-runtime-loop"],
    ["--agent-runtime-allow-exec"],
    ["--agent-runtime-memory"],
    ["--agent-runtime-session-history"],
    ["--agent-name", "unused"],
    ["--agent-role", "solver"],
    ["--agent-capability", "read_files"],
])
def test_command_generator_rejects_unused_agent_settings_before_initialization(tmp_path, capsys, options):
    context, args = command(tmp_path)
    assert cli.main([*args, *options]) == 2
    assert json.loads(capsys.readouterr().err)["error"]
    assert not (tmp_path / "home").exists()
    assert not (context.workspace / "evolution").exists()


@pytest.mark.parametrize("options", [
    ["--agent-runtime", "subprocess"],
    ["--agent-runtime", "mock", "--agent-runtime-command", "unused"],
    ["--agent-runtime", "mock", "--agent-runtime-model", "unused"],
    ["--agent-runtime", "mock", "--agent-runtime-loop"],
    ["--agent-runtime", "mock", "--agent-runtime-max-steps", "0"],
    ["--agent-runtime", "mock", "--agent-runtime-max-steps", "201"],
    ["--agent-runtime", "subprocess", "--agent-runtime-command", "relative-command"],
    ["--agent-runtime", "openai-compatible", "--agent-runtime-command", "unused"],
    ["--agent-runtime", "openai-compatible", "--agent-runtime-endpoint", "invalid"],
    ["--agent-runtime", "openai-compatible", "--agent-runtime-endpoint", ""],
    ["--agent-runtime", "openai-compatible", "--agent-runtime-endpoint", "http://localhost:9", "--agent-runtime-model", " "],
    ["--agent-runtime", "mock", "--agent-name", "bad name"],
    ["--agent-runtime", "mock", "--agent-name", ""],
    ["--agent-runtime", "mock", "--agent-role", "bad role"],
    ["--agent-runtime", "mock", "--agent-capability", "read_files", "--agent-capability", "read_files"],
    ["--agent-command", "relative-command"],
])
def test_cli_rejects_invalid_agent_runtime_settings_before_initialization(tmp_path, capsys, options):
    context, args = command(tmp_path)
    index = args.index("--generator-command")
    del args[index:index + 2]
    assert cli.main([*args, *options]) == 2
    assert json.loads(capsys.readouterr().err)["error"]
    assert not (tmp_path / "home").exists()
    assert not (context.workspace / "evolution").exists()


def test_cli_requires_exactly_one_bundle_source_producer(tmp_path, capsys):
    _, args = command(tmp_path)
    with pytest.raises(SystemExit) as error:
        cli.main([*args, "--agent-runtime", "mock"])
    assert error.value.code == 2
    assert "not allowed" in capsys.readouterr().err
    index = args.index("--generator-command")
    del args[index:index + 2]
    with pytest.raises(SystemExit) as error:
        cli.main(args)
    assert error.value.code == 2
    assert "required" in capsys.readouterr().err
    assert not (tmp_path / "home").exists()
