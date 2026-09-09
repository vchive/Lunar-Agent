import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar, Self

import pytest

from famou.agent_loop import AgentLoopRuntime
from famou.algorithm import AlgorithmProblemContract
from famou.artifacts import ArtifactError, ArtifactStore
from famou.config import Config
from famou.controller import LocalController
from famou.memory import MemoryStore
from famou.policy import PlanDocument, PlanTask
from famou.profiles import ModelProfile
from famou.runtime import (
    MockRuntime,
    ModelTurn,
    OpenAICompatibleRuntime,
    RuntimeExecutionError,
    SubprocessRuntime,
)
from famou.store import Store
from famou.tools import LocalToolRegistry


def test_mock_runtime_is_deterministic_without_external_environment(tmp_path: Path) -> None:
    result = MockRuntime().run("  hello   local agent ", tmp_path)
    assert result.text == "Mock runtime completed the task: hello local agent"
    assert result.metadata["provider"] == "repository-mock"


def test_subprocess_runtime_uses_explicit_command_and_workspace(tmp_path: Path) -> None:
    command = [sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"]
    result = SubprocessRuntime(command).run("hello", tmp_path)
    assert result.text == "HELLO"


def test_subprocess_runtime_requires_explicit_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FAMOU_RUNTIME_COMMAND", raising=False)
    with pytest.raises(ValueError, match="requires FAMOU_RUNTIME_COMMAND"):
        SubprocessRuntime()


def test_subprocess_runtime_reports_nonzero_exit(tmp_path: Path) -> None:
    command = [sys.executable, "-c", "import sys; print('bad', file=sys.stderr); sys.exit(3)"]
    with pytest.raises(RuntimeExecutionError, match="code 3"):
        SubprocessRuntime(command).run("hello", tmp_path)


def test_subprocess_runtime_enforces_timeout(tmp_path: Path) -> None:
    command = [sys.executable, "-c", "import time; time.sleep(1)"]
    with pytest.raises(RuntimeExecutionError, match="timed out"):
        SubprocessRuntime(command).run("hello", tmp_path, timeout=0.01)


class ModelHandler(BaseHTTPRequestHandler):
    response_status = 200
    response_body: bytes = b'{"choices":[{"message":{"content":"model result"}}]}'
    delay = 0.0
    observed: ClassVar[dict[str, object]] = {}

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.__class__.observed = {
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "body": json.loads(body),
        }
        if self.delay:
            time.sleep(self.delay)
        self.send_response(self.response_status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.response_body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


class ModelServer:
    def __init__(self, handler: type[ModelHandler]) -> None:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}"

    def __enter__(self) -> Self:
        self.thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def test_openai_compatible_runtime_calls_explicit_endpoint(tmp_path: Path) -> None:
    ModelHandler.response_status = 200
    ModelHandler.response_body = b'{"choices":[{"message":{"content":"model result"}}]}'
    ModelHandler.delay = 0.0
    with ModelServer(ModelHandler) as server:
        runtime = OpenAICompatibleRuntime(server.url, "fixture-model", "do-not-leak")
        result = runtime.run("hello model", tmp_path, timeout=1)
    assert result.text == "model result"
    assert result.metadata == {"provider": "openai-compatible", "model": "fixture-model"}
    assert ModelHandler.observed["path"] == "/chat/completions"
    assert ModelHandler.observed["authorization"] == "Bearer do-not-leak"
    assert ModelHandler.observed["body"] == {
        "model": "fixture-model",
        "messages": [{"role": "user", "content": "hello model"}],
        "stream": False,
    }


@pytest.mark.parametrize("allow_exec", [False, True])
@pytest.mark.parametrize("enable_memory", [False, True])
def test_tool_parameter_descriptions_reach_provider_request(
    tmp_path: Path, allow_exec: bool, enable_memory: bool
) -> None:
    ModelHandler.response_status = 200
    ModelHandler.response_body = b'{"choices":[{"message":{"content":"model result"}}]}'
    ModelHandler.delay = 0.0
    memory = MemoryStore(tmp_path / "memory.db") if enable_memory else None
    registry = LocalToolRegistry(
        allow_exec=allow_exec, memory=memory, command_timeout=7.5, max_output_bytes=127
    )
    schemas = registry.schemas()
    with ModelServer(ModelHandler) as server:
        AgentLoopRuntime(
            OpenAICompatibleRuntime(server.url, "fixture-model"), tools=registry
        ).run("inspect", tmp_path / "workspace", timeout=2)

    sent = ModelHandler.observed["body"]["tools"]
    assert sent == list(schemas)
    names = {tool["function"]["name"] for tool in sent}
    assert ("run_command" in names) is allow_exec
    assert ("remember_memory" in names) is enable_memory
    assert ("recall_memory" in names) is enable_memory
    properties_by_name = {}
    for tool in sent:
        properties = tool["function"]["parameters"]["properties"]
        properties_by_name[tool["function"]["name"]] = properties
        assert properties
        for value in properties.values():
            description = value.get("description")
            assert isinstance(description, str) and description.strip()
            assert len(description.encode("utf-8")) <= 512
    if allow_exec:
        command = properties_by_name["run_command"]["command"]["description"]
        assert "without a shell" in command
        assert "7.5 seconds" in command
    assert "127 bytes" in properties_by_name["read_file"]["path"]["description"]
    if enable_memory:
        scope = properties_by_name["remember_memory"]["scope"]["description"]
        assert "global" in scope and "active run" in scope
        assert "rejected" in scope


@pytest.mark.parametrize("mode,with_profile", [("run", True), ("run", False), ("run_isolated", True)])
@pytest.mark.parametrize("allow_exec", [False, True])
def test_current_profile_budget_reaches_http_request_only_for_normal_profiled_loop(
    tmp_path: Path, mode: str, with_profile: bool, allow_exec: bool,
) -> None:
    ModelHandler.response_status = 200
    ModelHandler.response_body = json.dumps({
        "choices": [{"message": {"content": "model result"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }).encode()
    ModelHandler.delay = 0.0
    profile = ModelProfile(
        "fixture-budget", "fixture-model", timeout_seconds=5, max_steps=8,
        max_total_tokens=100, max_cost_micros=200,
        input_cost_per_1k_micros=1_000, output_cost_per_1k_micros=1_000,
    ) if with_profile else None
    registry = LocalToolRegistry(allow_exec=allow_exec, command_timeout=7.5)
    secret = "HTTP-BUDGET-SECRET-SENTINEL"
    with ModelServer(ModelHandler) as server:
        runtime = AgentLoopRuntime(
            OpenAICompatibleRuntime(server.url, "fixture-model", secret),
            tools=registry, profile=profile,
        )
        result = getattr(runtime, mode)("inspect", tmp_path / "workspace", timeout=2)

    assert result.text == "model result"
    messages = ModelHandler.observed["body"]["messages"]
    assert [message["role"] for message in messages] == ["system", "user"]
    assert messages[1] == {"role": "user", "content": "inspect"}
    assert secret not in json.dumps(ModelHandler.observed["body"])
    system = messages[0]["content"]
    opening, closing = "<lunar_runtime_budget>\n", "\n</lunar_runtime_budget>"
    if mode != "run" or not with_profile:
        assert "lunar_runtime_budget" not in system
        return

    assert system.count(opening) == system.count(closing) == 1
    snapshot = json.loads(system.split(opening, 1)[1].split(closing, 1)[0])
    fields = {
        "remaining_seconds", "tool_steps_remaining", "command_timeout_seconds",
        "tokens_remaining", "cost_micros_remaining",
    }
    assert fields <= snapshot.keys()
    assert all(
        snapshot[key] is None or type(snapshot[key]) in {int, float}
        for key in fields
    )
    assert 0 < snapshot["remaining_seconds"] <= 2
    assert snapshot["tool_steps_remaining"] == 8
    assert snapshot["tokens_remaining"] == 100
    assert snapshot["cost_micros_remaining"] == 200
    if allow_exec:
        assert 0 < snapshot["command_timeout_seconds"] <= snapshot["remaining_seconds"]
    else:
        assert snapshot["command_timeout_seconds"] is None


def test_openai_compatible_runtime_redacts_http_errors(tmp_path: Path) -> None:
    ModelHandler.response_status = 500
    ModelHandler.response_body = b'{"error":"secret"}'
    ModelHandler.delay = 0.0
    with ModelServer(ModelHandler) as server, pytest.raises(
        RuntimeExecutionError, match="HTTP 500"
    ) as exc_info:
        OpenAICompatibleRuntime(server.url, "model", "secret").run("hello", tmp_path, timeout=1)
    assert "secret" not in str(exc_info.value)


def test_openai_compatible_runtime_rejects_malformed_and_timed_out_responses(tmp_path: Path) -> None:
    ModelHandler.response_status = 200
    ModelHandler.response_body = b"not-json"
    ModelHandler.delay = 0.0
    with ModelServer(ModelHandler) as server, pytest.raises(
        RuntimeExecutionError, match="malformed JSON"
    ):
        OpenAICompatibleRuntime(server.url, "model").run("hello", tmp_path, timeout=1)

    ModelHandler.response_body = b'{"choices":[{"message":{"content":"late"}}]}'
    ModelHandler.delay = 0.5
    with ModelServer(ModelHandler) as server, pytest.raises(
        RuntimeExecutionError, match="could not reach"
    ):
        OpenAICompatibleRuntime(server.url, "model").run("hello", tmp_path, timeout=0.01)


def test_openai_compatible_runtime_parses_structured_tool_calls(tmp_path: Path) -> None:
    ModelHandler.response_status = 200
    ModelHandler.delay = 0.0
    ModelHandler.response_body = (
        b'{"choices":[{"message":{"content":"",'
        b'"tool_calls":[{"id":"call-1","type":"function",'
        b'"function":{"name":"read_file","arguments":"{\\"path\\":\\"a.txt\\"}"}}]}}]}'
    )
    with ModelServer(ModelHandler) as server:
        turn = OpenAICompatibleRuntime(server.url, "model").complete(
            [{"role": "user", "content": "read a.txt"}],
            tools=({"type": "function", "function": {"name": "read_file"}},),
            timeout=1,
        )
    assert isinstance(turn, ModelTurn)
    assert turn.text == ""
    assert turn.tool_calls[0].name == "read_file"
    assert turn.tool_calls[0].arguments == {"path": "a.txt"}


def test_openai_compatible_runtime_preserves_provider_model_and_usage() -> None:
    ModelHandler.response_status = 200
    ModelHandler.delay = 0.0
    ModelHandler.response_body = json.dumps(
        {
            "model": "provider/fixture-model",
            "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
            "choices": [{"message": {"content": "measured"}}],
        }
    ).encode()
    with ModelServer(ModelHandler) as server:
        turn = OpenAICompatibleRuntime(server.url, "fixture-model").complete(
            [{"role": "user", "content": "measure"}], timeout=1
        )

    assert turn.response_model == "provider/fixture-model"
    assert turn.usage == {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15}


def test_openai_compatible_runtime_rejects_inconsistent_provider_usage() -> None:
    ModelHandler.response_status = 200
    ModelHandler.delay = 0.0
    ModelHandler.response_body = json.dumps(
        {
            "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 99},
            "choices": [{"message": {"content": "bad telemetry"}}],
        }
    ).encode()
    with ModelServer(ModelHandler) as server, pytest.raises(
        RuntimeExecutionError, match="usage"
    ):
        OpenAICompatibleRuntime(server.url, "fixture-model").complete(
            [{"role": "user", "content": "measure"}], timeout=1
        )


def test_openai_compatible_runtime_materializes_one_shot_artifact_envelope(tmp_path: Path) -> None:
    ModelHandler.response_status = 200
    ModelHandler.delay = 0.0
    ModelHandler.response_body = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "text": "route table generated",
                                "artifacts": [
                                    {
                                        "path": "output/routes.csv",
                                        "content": "order_id,route_id\n1,r1\n",
                                    }
                                ],
                                "metadata": {"mode": "batch"},
                            }
                        )
                    }
                }
            ]
        }
    ).encode()
    with ModelServer(ModelHandler) as server:
        result = OpenAICompatibleRuntime(server.url, "model").run("write routes", tmp_path, timeout=1)

    assert result.text == "route table generated"
    assert result.artifacts == ("output/routes.csv",)
    assert result.metadata["artifact_envelope"] == "true"
    assert (tmp_path / "output" / "routes.csv").read_text(encoding="utf-8").startswith("order_id")


def test_one_shot_envelope_completes_structured_output_promotion(tmp_path: Path) -> None:
    ModelHandler.response_status = 200
    ModelHandler.delay = 0.0
    ModelHandler.response_body = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "text": "route table generated",
                                "artifacts": [
                                    {
                                        "path": "output/routes.csv",
                                        "content": "item_id,route_id\n1,r1\n",
                                    }
                                ],
                            }
                        )
                    }
                }
            ]
        }
    ).encode()
    contract = AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "envelope-output",
            "problem_type": "routing",
            "statement": "Assign every item to a route.",
            "inputs": [{"path": "items.csv", "format": "csv", "fields": {"id": "item id"}}],
            "decision_variables": ["route per item"],
            "objective": {"name": "distance", "direction": "minimize"},
            "hard_constraints": [],
            "soft_constraints": [],
            "success_criteria": ["Every item appears."],
            "deliverables": ["Route table."],
            "outputs": [{"path": "output/routes.csv", "format": "csv", "fields": ["item_id", "route_id"]}],
        }
    )
    plan = PlanDocument(
        goal="solve envelope routes",
        plan_id="plan-envelope-output",
        tasks=(PlanTask("solver", "Solver", "write routes"),),
        algorithm_problem=contract.to_dict(),
    )
    with ModelServer(ModelHandler) as server:
        controller = LocalController(
            Config(tmp_path / "home"), OpenAICompatibleRuntime(server.url, "model")
        )
        run = controller.start_plan(plan)

    assert run.status.value == "succeeded"
    assert (run.workspace / "output" / "routes.csv").is_file()
    assert controller.deliver(run.id).action == "deliver"


@pytest.mark.parametrize(
    "artifact, match",
    [
        ({"path": "../escape.txt", "content": "bad"}, "relative"),
        ({"path": "/tmp/escape.txt", "content": "bad"}, "relative"),
        ({"path": "output/a.txt", "content": "a"}, "duplicate"),
    ],
)
def test_openai_compatible_runtime_rejects_unsafe_artifact_envelopes(
    tmp_path: Path, artifact: dict[str, str], match: str
) -> None:
    ModelHandler.response_status = 200
    ModelHandler.delay = 0.0
    duplicate = artifact | {"path": "output/a.txt"}
    envelope = {
        "text": "done",
        "artifacts": [artifact, duplicate] if match == "duplicate" else [artifact],
    }
    ModelHandler.response_body = json.dumps(
        {"choices": [{"message": {"content": json.dumps(envelope)}}]}
    ).encode()
    with ModelServer(ModelHandler) as server, pytest.raises(RuntimeExecutionError, match=match):
        OpenAICompatibleRuntime(server.url, "model").run("write", tmp_path, timeout=1)
    assert not (tmp_path / "escape.txt").exists()


def test_openai_compatible_runtime_rejects_oversized_envelope_content(tmp_path: Path) -> None:
    ModelHandler.response_status = 200
    ModelHandler.delay = 0.0
    envelope = {"text": "done", "artifacts": [{"path": "large.txt", "content": "x" * (256 * 1024 + 1)}]}
    ModelHandler.response_body = json.dumps(
        {"choices": [{"message": {"content": json.dumps(envelope)}}]}
    ).encode()
    with ModelServer(ModelHandler) as server, pytest.raises(RuntimeExecutionError, match="bytes"):
        OpenAICompatibleRuntime(server.url, "model").run("write", tmp_path, timeout=1)
    assert not (tmp_path / "large.txt").exists()


def test_openai_compatible_runtime_rejects_symlinked_envelope_directory(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)
    ModelHandler.response_status = 200
    ModelHandler.delay = 0.0
    envelope = {"text": "done", "artifacts": [{"path": "link/secret.txt", "content": "bad"}]}
    ModelHandler.response_body = json.dumps(
        {"choices": [{"message": {"content": json.dumps(envelope)}}]}
    ).encode()
    with ModelServer(ModelHandler) as server, pytest.raises(RuntimeExecutionError, match="symlink"):
        OpenAICompatibleRuntime(server.url, "model").run("write", tmp_path, timeout=1)
    assert not (outside / "secret.txt").exists()


def test_artifact_paths_are_confined_to_run_workspace(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("goal", tmp_path / "workspace")
    artifacts = ArtifactStore(run.workspace, store, run.id)
    with pytest.raises(ArtifactError):
        artifacts.safe_path("../outside.txt")
