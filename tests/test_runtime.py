import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar, Self

import pytest

from famou.artifacts import ArtifactError, ArtifactStore
from famou.runtime import (
    MockRuntime,
    ModelTurn,
    OpenAICompatibleRuntime,
    RuntimeExecutionError,
    SubprocessRuntime,
)
from famou.store import Store


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


def test_artifact_paths_are_confined_to_run_workspace(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("goal", tmp_path / "workspace")
    artifacts = ArtifactStore(run.workspace, store, run.id)
    with pytest.raises(ArtifactError):
        artifacts.safe_path("../outside.txt")
