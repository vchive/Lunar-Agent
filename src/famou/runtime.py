"""Execution boundary for local Famou runtimes.

The module intentionally contains no Hermes/OpenCode/Codex discovery. A runtime is either a
repository-owned deterministic mock, an explicitly configured subprocess, or an explicitly
configured OpenAI-compatible HTTP endpoint.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class RuntimeResult:
    text: str
    artifacts: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)


class Runtime(Protocol):
    name: str

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        """Execute one bounded task inside ``workspace``."""

    def cancel(self) -> None:
        """Request cancellation of the active invocation, when supported."""

    def process_info(self) -> tuple[int | None, int | None]:
        """Return local PID/PGID for detached cancellation, or ``(None, None)``."""

    def set_process_observer(
        self, observer: Callable[[int, int | None], None] | None
    ) -> None:
        """Observe a spawned local process, if the adapter supports one."""


class RuntimeExecutionError(RuntimeError):
    """A runtime returned a non-successful or unusable result."""


class MockRuntime:
    """Deterministic runtime used for smoke runs and controller tests."""

    name = "mock"

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        del timeout
        workspace.mkdir(parents=True, exist_ok=True)
        excerpt = " ".join(prompt.strip().split())[:240]
        return RuntimeResult(
            text=f"Mock runtime completed the task: {excerpt}",
            metadata={"provider": "repository-mock"},
        )

    def cancel(self) -> None:
        return None

    def process_info(self) -> tuple[int | None, int | None]:
        return (None, None)

    def set_process_observer(
        self, observer: Callable[[int, int | None], None] | None
    ) -> None:
        del observer


class SubprocessRuntime:
    """Run an explicitly configured command, without searching agent-specific global state."""

    name = "subprocess"

    def __init__(self, command: str | list[str] | tuple[str, ...] | None = None) -> None:
        configured = command if command is not None else os.environ.get("FAMOU_RUNTIME_COMMAND")
        if isinstance(configured, str):
            self.command = tuple(shlex.split(configured))
        elif configured:
            self.command = tuple(configured)
        else:
            self.command = ()
        if not self.command:
            raise ValueError(
                "subprocess runtime requires FAMOU_RUNTIME_COMMAND or an explicit command"
            )
        self._process: subprocess.Popen[str] | None = None
        self._process_observer: Callable[[int, int | None], None] | None = None

    def set_process_observer(
        self, observer: Callable[[int, int | None], None] | None
    ) -> None:
        self._process_observer = observer

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        workspace.mkdir(parents=True, exist_ok=True)
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                self.command,
                cwd=workspace,
                text=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self._process = process
            if self._process_observer is not None:
                try:
                    pgid = os.getpgid(process.pid)
                except OSError:
                    pgid = None
                try:
                    self._process_observer(process.pid, pgid)
                except Exception as observer_error:  # noqa: BLE001 - metadata must not break execution
                    del observer_error
            stdout, stderr = process.communicate(input=prompt, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            if process is not None:
                process.kill()
                process.communicate()
            raise RuntimeExecutionError(f"runtime timed out after {timeout}s") from exc
        except OSError as exc:
            raise RuntimeExecutionError(f"could not start runtime: {exc}") from exc
        finally:
            self._process = None
        if process.returncode != 0:
            detail = stderr.strip()[-2000:]
            suffix = f": {detail}" if detail else ""
            raise RuntimeExecutionError(
                f"runtime exited with code {process.returncode}{suffix}"
            )
        output = stdout.strip()
        if not output:
            raise RuntimeExecutionError("runtime returned empty stdout")
        return RuntimeResult(
            text=output,
            metadata={"provider": "explicit-subprocess", "command": self.command[0]},
        )

    def cancel(self) -> None:
        if self._process and self._process.poll() is None:
            self._process.terminate()

    def process_info(self) -> tuple[int | None, int | None]:
        process = self._process
        if process is None or process.poll() is not None:
            return (None, None)
        try:
            return (process.pid, os.getpgid(process.pid))
        except OSError:
            return (process.pid, None)


class OpenAICompatibleRuntime:
    """Call an explicitly configured OpenAI-compatible chat endpoint.

    This adapter intentionally uses only the standard library. It works with local Ollama/vLLM/
    LM Studio servers as well as hosted gateways, while keeping endpoint and credential discovery
    explicit and independent from Hermes/OpenCode/Codex.
    """

    name = "openai-compatible"

    def __init__(
        self,
        endpoint: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        configured_endpoint = endpoint or os.environ.get("FAMOU_MODEL_ENDPOINT")
        if not configured_endpoint or not configured_endpoint.strip():
            raise ValueError(
                "openai-compatible runtime requires --endpoint or FAMOU_MODEL_ENDPOINT"
            )
        parsed = urlparse(configured_endpoint.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("model endpoint must be an absolute http(s) URL")
        self.endpoint = self._chat_endpoint(configured_endpoint.strip())
        self.model = (model or os.environ.get("FAMOU_MODEL") or "local").strip()
        if not self.model:
            raise ValueError("model must not be empty")
        self.api_key = api_key if api_key is not None else os.environ.get("FAMOU_API_KEY")

    @staticmethod
    def _chat_endpoint(endpoint: str) -> str:
        parsed = urlparse(endpoint)
        path = parsed.path.rstrip("/")
        if path.endswith("/chat/completions"):
            return endpoint
        updated = parsed._replace(path=f"{path}/chat/completions")
        return urlunparse(updated)

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        workspace.mkdir(parents=True, exist_ok=True)
        body = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "lunar-agent/0.1",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(self.endpoint, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=timeout) as response:
                status = response.getcode()
                raw = response.read(8 * 1024 * 1024)
        except HTTPError as exc:
            detail = self._redact(self._read_error_body(exc))
            suffix = f": {detail}" if detail else ""
            raise RuntimeExecutionError(f"model endpoint returned HTTP {exc.code}{suffix}") from exc
        except (TimeoutError, URLError, OSError) as exc:
            detail = self._redact(str(exc))
            raise RuntimeExecutionError(f"could not reach model endpoint: {detail}") from exc
        if status < 200 or status >= 300:
            raise RuntimeExecutionError(f"model endpoint returned HTTP {status}")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeExecutionError("model endpoint returned malformed JSON") from exc
        text = self._extract_text(payload)
        if not text:
            raise RuntimeExecutionError("model endpoint returned empty content")
        return RuntimeResult(
            text=text,
            metadata={"provider": "openai-compatible", "model": self.model},
        )

    def cancel(self) -> None:
        # urllib does not expose a portable cancellation handle. Detached cancellation terminates
        # the controller process group; synchronous callers can only mark the run cancelled.
        return None

    def process_info(self) -> tuple[int | None, int | None]:
        return (None, None)

    def set_process_observer(
        self, observer: Callable[[int, int | None], None] | None
    ) -> None:
        del observer

    def _read_error_body(self, error: HTTPError) -> str:
        try:
            return error.read(2_000).decode("utf-8", errors="replace")
        except OSError:
            return ""

    def _redact(self, detail: str) -> str:
        if self.api_key:
            detail = detail.replace(self.api_key, "[REDACTED]")
        return detail[-2_000:]

    @staticmethod
    def _extract_text(payload: object) -> str:
        if not isinstance(payload, dict):
            return ""
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            choice = choices[0]
            if isinstance(choice, dict):
                message = choice.get("message")
                if isinstance(message, dict):
                    content = OpenAICompatibleRuntime._content_to_text(message.get("content"))
                    if content:
                        return content
                content = OpenAICompatibleRuntime._content_to_text(choice.get("text"))
                if content:
                    return content
        message = payload.get("message")
        if isinstance(message, dict):
            content = OpenAICompatibleRuntime._content_to_text(message.get("content"))
            if content:
                return content
        return OpenAICompatibleRuntime._content_to_text(payload.get("response"))

    @staticmethod
    def _content_to_text(content: object) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and isinstance(item.get("text"), str)
            ]
            return "".join(parts).strip()
        return ""


def build_runtime(
    name: str,
    command: str | None = None,
    endpoint: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> Runtime:
    if name == "mock":
        return MockRuntime()
    if name == "subprocess":
        return SubprocessRuntime(command)
    if name == "openai-compatible":
        return OpenAICompatibleRuntime(endpoint, model, api_key)
    raise ValueError(f"unknown runtime {name!r}; choose mock, subprocess, or openai-compatible")
