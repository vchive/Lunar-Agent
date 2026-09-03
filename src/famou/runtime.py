"""Execution boundary for local Famou runtimes.

The module intentionally contains no Hermes/OpenCode/Codex discovery. A runtime is either a
repository-owned deterministic mock, an explicitly configured subprocess, or an explicitly
configured OpenAI-compatible HTTP endpoint.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

MAX_ENVELOPE_ARTIFACTS = 32
MAX_ENVELOPE_BYTES = 256 * 1024
MAX_ENVELOPE_METADATA = 16
MAX_ENVELOPE_METADATA_BYTES = 2_000
_SECRET_RE = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._-]{12,}|api[_-]?key\s*[:=]\s*\S+)"
)


@dataclass(frozen=True)
class RuntimeResult:
    text: str
    artifacts: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class ModelTurn:
    text: str
    tool_calls: tuple[ToolCall, ...] = ()


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
        # Keep the repository-owned smoke runtime useful for the strict specialist role DAG.
        # These fixtures are emitted only when the task prompt explicitly declares the role path;
        # ordinary generic runs remain text-only and therefore exercise the legacy contract.
        if "data/processed/data-profile.json" in prompt:
            profile = workspace / "data" / "processed" / "data-profile.json"
            profile.parent.mkdir(parents=True, exist_ok=True)
            profile.write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "inputs": [
                            {
                                "path": "data/raw/input.json",
                                "format": "json",
                                "row_count": 0,
                                "columns": [],
                                "issues": ["mock runtime did not receive a staged input file"],
                            }
                        ],
                        "notes": "deterministic repository mock profile",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        if "solve/problem-formulation.md" in prompt:
            formulation = workspace / "solve" / "problem-formulation.md"
            formulation.parent.mkdir(parents=True, exist_ok=True)
            formulation.write_text(
                "# Mock formulation\n\nThe validated contract remains authoritative.\n",
                encoding="utf-8",
            )
        if "evaluate/evaluation.json" in prompt:
            report = workspace / "evaluate" / "evaluation.json"
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "evaluator_id": "repository-mock",
                        "validity": 1,
                        "quality": 1.0,
                        "combined_score": 1.0,
                        "detailed_scores": {},
                        "error_info": [],
                    }
                ),
                encoding="utf-8",
            )
        if "evaluate/review.md" in prompt:
            review = workspace / "evaluate" / "review.md"
            review.parent.mkdir(parents=True, exist_ok=True)
            review.write_text(
                "# Mock review\n\nEvidence is bounded and locally verified.\n",
                encoding="utf-8",
            )
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
        turn = self.complete(
            [{"role": "user", "content": prompt}],
            tools=(),
            timeout=timeout,
        )
        if turn.tool_calls:
            raise RuntimeExecutionError(
                "model returned tool calls; use --agent-loop for tool execution"
            )
        if not turn.text:
            raise RuntimeExecutionError("model endpoint returned empty content")
        text, artifacts, envelope_metadata = self._materialize_artifact_envelope(turn.text, workspace)
        return RuntimeResult(
            text=text,
            artifacts=artifacts,
            metadata={
                "provider": "openai-compatible",
                "model": self.model,
                **envelope_metadata,
            },
        )

    def _materialize_artifact_envelope(
        self, text: str, workspace: Path
    ) -> tuple[str, tuple[str, ...], dict[str, str]]:
        """Decode an optional one-shot ``{text, artifacts}`` response and write confined files."""
        try:
            payload = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            return text, (), {}
        if not isinstance(payload, dict) or "artifacts" not in payload:
            return text, (), {}
        if set(payload) - {"text", "artifacts", "metadata"}:
            raise RuntimeExecutionError("artifact envelope contains unknown fields")
        envelope_text = payload.get("text")
        if not isinstance(envelope_text, str):
            raise RuntimeExecutionError("artifact envelope text must be a string")
        raw_artifacts = payload.get("artifacts")
        if not isinstance(raw_artifacts, list) or len(raw_artifacts) > MAX_ENVELOPE_ARTIFACTS:
            raise RuntimeExecutionError(
                f"artifact envelope must contain at most {MAX_ENVELOPE_ARTIFACTS} files"
            )
        root = workspace.expanduser()
        if root.exists() and root.is_symlink():
            raise RuntimeExecutionError("artifact envelope workspace must not be a symlink")
        root = root.resolve(strict=False)
        root.mkdir(parents=True, exist_ok=True)
        entries: list[tuple[str, Path, bytes]] = []
        seen: set[str] = set()
        total_bytes = 0
        for item in raw_artifacts:
            if not isinstance(item, dict) or set(item) != {"path", "content"}:
                raise RuntimeExecutionError("artifact envelope entries require path and content")
            relative = item["path"]
            content = item["content"]
            if not isinstance(relative, str) or not relative.strip():
                raise RuntimeExecutionError("artifact envelope path must be non-empty")
            if (
                "\\" in relative
                or "\x00" in relative
                or Path(relative).is_absolute()
                or any(part in {"", ".", ".."} for part in relative.split("/"))
            ):
                raise RuntimeExecutionError("artifact envelope paths must be portable relative paths")
            if relative in seen:
                raise RuntimeExecutionError(f"artifact envelope contains duplicate path: {relative}")
            seen.add(relative)
            if not isinstance(content, str):
                raise RuntimeExecutionError("artifact envelope content must be a string")
            encoded = content.encode("utf-8")
            total_bytes += len(encoded)
            if total_bytes > MAX_ENVELOPE_BYTES:
                raise RuntimeExecutionError(
                    f"artifact envelope exceeds {MAX_ENVELOPE_BYTES} bytes"
                )
            raw = root / relative
            if self._path_has_symlink(root, raw):
                raise RuntimeExecutionError(f"artifact envelope path is symlinked: {relative}")
            resolved = raw.resolve(strict=False)
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise RuntimeExecutionError(
                    f"artifact envelope path escapes the workspace: {relative}"
                ) from exc
            entries.append((relative, resolved, encoded))
        raw_metadata = payload.get("metadata", {})
        if raw_metadata is None:
            raw_metadata = {}
        if not isinstance(raw_metadata, dict) or len(raw_metadata) > MAX_ENVELOPE_METADATA:
            raise RuntimeExecutionError("artifact envelope metadata must be a bounded string object")
        metadata: dict[str, str] = {}
        for key, value in raw_metadata.items():
            if (
                not isinstance(key, str)
                or not key.strip()
                or key in {"provider", "model", "artifact_envelope"}
                or not isinstance(value, str)
                or len(value.encode("utf-8")) > MAX_ENVELOPE_METADATA_BYTES
                or _SECRET_RE.search(value)
            ):
                raise RuntimeExecutionError("artifact envelope metadata is invalid")
            metadata[f"envelope_{key}"] = value
        for relative, target, encoded in entries:
            if self._path_has_symlink(root, target):
                raise RuntimeExecutionError(f"artifact envelope path is symlinked: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.is_symlink():
                raise RuntimeExecutionError(f"artifact envelope path is symlinked: {relative}")
            temporary = target.with_name(f".{target.name}.tmp")
            temporary.write_bytes(encoded)
            temporary.replace(target)
        if entries:
            metadata["artifact_envelope"] = "true"
        return envelope_text, tuple(relative for relative, _, _ in entries), metadata

    @staticmethod
    def _path_has_symlink(root: Path, path: Path) -> bool:
        current = path
        while True:
            if current.exists() and current.is_symlink():
                return True
            if current == root:
                return False
            if current.parent == current:
                return True
            current = current.parent

    def complete(
        self,
        messages: list[dict[str, object]],
        tools: tuple[dict[str, object], ...] = (),
        timeout: float | None = None,
    ) -> ModelTurn:
        """Request one model turn, preserving structured tool calls for the agent loop."""
        body = json.dumps(
            {
                "model": self.model,
                "messages": messages,
                "stream": False,
                **({"tools": list(tools)} if tools else {}),
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
        text, tool_calls = self._extract_turn(payload)
        if not text and not tool_calls:
            raise RuntimeExecutionError("model endpoint returned empty content")
        return ModelTurn(text=text, tool_calls=tool_calls)

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
    def _extract_turn(payload: object) -> tuple[str, tuple[ToolCall, ...]]:
        if not isinstance(payload, dict):
            return "", ()
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            choice = choices[0]
            if isinstance(choice, dict):
                text = ""
                message = choice.get("message")
                if isinstance(message, dict):
                    text = OpenAICompatibleRuntime._content_to_text(message.get("content"))
                    return text, OpenAICompatibleRuntime._parse_tool_calls(message.get("tool_calls"))
                text = OpenAICompatibleRuntime._content_to_text(choice.get("text"))
                if text:
                    return text, ()
        message = payload.get("message")
        if isinstance(message, dict):
            content = OpenAICompatibleRuntime._content_to_text(message.get("content"))
            if content:
                return content, OpenAICompatibleRuntime._parse_tool_calls(message.get("tool_calls"))
        return OpenAICompatibleRuntime._content_to_text(payload.get("response")), ()

    @staticmethod
    def _extract_text(payload: object) -> str:
        """Compatibility helper for callers of the original one-shot adapter."""
        return OpenAICompatibleRuntime._extract_turn(payload)[0]

    @staticmethod
    def _parse_tool_calls(raw: object) -> tuple[ToolCall, ...]:
        if raw is None:
            return ()
        if not isinstance(raw, list):
            raise RuntimeExecutionError("model returned malformed tool calls")
        calls: list[ToolCall] = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                raise RuntimeExecutionError("model returned malformed tool call")
            function = item.get("function")
            if not isinstance(function, dict) or not isinstance(function.get("name"), str):
                raise RuntimeExecutionError("model returned a tool call without a function name")
            raw_arguments = function.get("arguments", {})
            if isinstance(raw_arguments, str):
                try:
                    raw_arguments = json.loads(raw_arguments)
                except json.JSONDecodeError as exc:
                    raise RuntimeExecutionError("model returned malformed tool arguments") from exc
            if not isinstance(raw_arguments, dict):
                raise RuntimeExecutionError("model tool arguments must be a JSON object")
            call_id = item.get("id")
            calls.append(
                ToolCall(
                    id=call_id if isinstance(call_id, str) and call_id else f"call-{index + 1}",
                    name=function["name"],
                    arguments=raw_arguments,
                )
            )
        return tuple(calls)

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
    command: str | Sequence[str] | None = None,
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
