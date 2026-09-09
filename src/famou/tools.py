"""Small, local tools exposed to the Build agent loop.

Tools receive a task workspace rather than the process working directory. Every filesystem operation
is resolved and checked before it is performed; command execution is opt-in and never uses a shell.
"""

from __future__ import annotations

import json
import math
import os
import shlex
import sqlite3
import stat
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from .memory import MemoryStore


class ToolError(ValueError):
    """A tool request is invalid or violates the local policy."""


@dataclass(frozen=True)
class ToolResult:
    output: str
    success: bool = True
    artifacts: tuple[str, ...] = ()
    awaiting_input: bool = False
    input_question: str | None = None
    input_options: tuple[str, ...] = ()


class LocalToolRegistry:
    """Registry for confined filesystem tools and an optional command tool."""

    def __init__(
        self,
        allow_exec: bool = False,
        command_timeout: float = 30.0,
        max_output_bytes: int = 20_000,
        memory: MemoryStore | None = None,
        memory_scope: str = "global",
        redactions: tuple[str, ...] = (),
        command_environment: dict[str, str] | None = None,
    ) -> None:
        if command_timeout <= 0:
            raise ValueError("command_timeout must be positive")
        if max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")
        self.allow_exec = allow_exec
        self.command_timeout = command_timeout
        self.max_output_bytes = max_output_bytes
        self.memory = memory
        self.memory_scope = memory_scope
        self.redactions = tuple(secret for secret in redactions if secret)
        self.command_environment = (
            None if command_environment is None else dict(command_environment)
        )
        self._execution_deadline: ContextVar[float | None] = ContextVar(
            "lunar_tool_execution_deadline", default=None
        )

    @contextmanager
    def execution_deadline(self, deadline: float) -> Iterator[None]:
        """Bind an internal invocation deadline without mutating registry configuration."""
        if (
            isinstance(deadline, bool) or not isinstance(deadline, (int, float))
            or not math.isfinite(deadline)
        ):
            raise ValueError("execution deadline must be finite")
        current = self._execution_deadline.get()
        token = self._execution_deadline.set(min(current, deadline) if current is not None else deadline)
        try:
            yield
        finally:
            self._execution_deadline.reset(token)

    def set_memory_scope(self, scope: str) -> None:
        """Set the default scope used by memory tools for the active task."""
        self.memory_scope = scope

    def schemas(self) -> tuple[dict[str, object], ...]:
        schemas: list[dict[str, object]] = [
            self._schema(
                "read_file",
                "Read a UTF-8 text file from the task workspace.",
                {
                    "path": {
                        "type": "string",
                        "description": (
                            "Path to a UTF-8 text file inside the task workspace; prefer a relative "
                            f"path. Preview uses at most the first {self.max_output_bytes} bytes, "
                            "plus a truncation marker if larger. UTF-8 decoding can fail at the "
                            "cutoff. Repeating a call does not retrieve another page."
                        ),
                    }
                },
                ["path"],
            ),
            self._schema(
                "write_file",
                "Write UTF-8 text to a file in the task workspace and return its artifact path.",
                {
                    "path": {
                        "type": "string",
                        "description": (
                            "Destination inside the task workspace; prefer a relative path. "
                            "Creates missing parent directories and atomically replaces one file "
                            "after writing complete content."
                        ),
                    },
                    "content": {
                        "type": "string",
                        "description": "Complete replacement text, at most 1,000,000 UTF-8 bytes.",
                    },
                },
                ["path", "content"],
            ),
            self._schema(
                "list_dir",
                "List entries in a task workspace directory.",
                {
                    "path": {
                        "type": "string",
                        "description": (
                            "Directory inside the task workspace. Omit or use . for its root; "
                            "lists immediate entries only."
                        ),
                    }
                },
                [],
            ),
            self._schema(
                "ask_user",
                "Pause this session and ask the user or parent Agent for a bounded answer.",
                {
                    "question": {
                        "type": "string",
                        "description": (
                            "Non-empty question for the user or parent Agent, at most 8,000 "
                            "UTF-8 bytes. Pauses the session until an answer is supplied."
                        ),
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Optional answer choices: at most 10 non-empty strings, each at most "
                            "200 UTF-8 bytes. Omit for a free-text question."
                        ),
                    },
                },
                ["question"],
            ),
        ]
        if self.memory is not None:
            schemas.extend(
                (
                    self._schema(
                        "recall_memory",
                        "Recall relevant durable notes from this agent's local memory.",
                        {
                            "query": {
                                "type": "string",
                                "description": (
                                    "Search words for notes in the active scope and global scope. "
                                    "An empty string retrieves recent notes."
                                ),
                            },
                            "limit": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 20,
                                "description": "Maximum notes to return, from 1 through 20; default 8.",
                            },
                        },
                        ["query"],
                    ),
                    self._schema(
                        "remember_memory",
                        "Store a concise fact, preference, decision, or progress note for later runs.",
                        {
                            "content": {
                                "type": "string",
                                "description": (
                                    "Non-empty durable fact, preference, decision, or progress note, "
                                    "at most 20,000 UTF-8 bytes. Do not include credentials."
                                ),
                            },
                            "kind": {
                                "type": "string",
                                "description": "Short note category; defaults to note.",
                            },
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Optional string tags used for bounded lexical recall.",
                            },
                            "scope": {
                                "type": "string",
                                "description": (
                                    "Omit to use the active scope (the run when attached, otherwise "
                                    "global). Use global explicitly to share across runs. Other "
                                    "scopes outside global or the active run are rejected."
                                ),
                            },
                        },
                        ["content"],
                    ),
                )
            )
        if self.allow_exec:
            schemas.append(
                self._schema(
                    "run_command",
                    "Run a bounded command without a shell in the task workspace.",
                    {
                        "command": {
                            "oneOf": [
                                {"type": "string"},
                                {"type": "array", "items": {"type": "string"}},
                            ],
                            "description": (
                                "Runs without a shell in the task workspace. Prefer an argv array, "
                                'e.g. ["python3", "-u", "solve.py"]. A string is split into arguments; '
                                "pipes, redirects, wildcards and environment variables are not expanded. "
                                f"Timeout: at most {self.command_timeout:g} seconds, further limited "
                                "by a profiled invocation's remaining time; output is captured until exit."
                            ),
                        },
                    },
                    ["command"],
                )
            )
        return tuple(schemas)

    @staticmethod
    def _schema(
        name: str,
        description: str,
        properties: dict[str, object],
        required: list[str],
    ) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {"type": "object", "properties": properties, "required": required},
            },
        }

    def execute(self, name: str, arguments: dict[str, object], workspace: Path) -> ToolResult:
        try:
            if name == "read_file":
                return self._read_file(arguments, workspace)
            if name == "write_file":
                return self._write_file(arguments, workspace)
            if name == "list_dir":
                return self._list_dir(arguments, workspace)
            if name == "ask_user":
                return self._ask_user(arguments)
            if name == "recall_memory":
                return self._recall_memory(arguments)
            if name == "remember_memory":
                return self._remember_memory(arguments)
            if name == "run_command":
                return self._run_command(arguments, workspace)
            raise ToolError(f"unknown tool: {name}")
        except (OSError, sqlite3.Error, ToolError, TypeError, ValueError) as exc:
            return ToolResult(output=f"tool_error: {type(exc).__name__}: {exc}", success=False)

    def _safe_path(self, workspace: Path, value: object) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise ToolError("path must be a non-empty string")
        root = workspace.resolve()
        candidate = (root / value).resolve(strict=False)
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ToolError(f"path escapes task workspace: {value}") from exc
        return candidate

    def _read_file(self, arguments: dict[str, object], workspace: Path) -> ToolResult:
        path = self._safe_path(workspace, arguments.get("path"))
        if not path.is_file():
            raise ToolError(f"file does not exist: {arguments.get('path')}")
        raw = path.read_bytes()
        if len(raw) > self.max_output_bytes:
            raw = raw[: self.max_output_bytes]
            suffix = "\n[tool output truncated]"
        else:
            suffix = ""
        try:
            output = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ToolError("file is not valid UTF-8 text") from exc
        return ToolResult(output + suffix)

    def _write_file(self, arguments: dict[str, object], workspace: Path) -> ToolResult:
        path = self._safe_path(workspace, arguments.get("path"))
        content = arguments.get("content")
        if not isinstance(content, str):
            raise ToolError("content must be a string")
        encoded = content.encode("utf-8")
        if len(encoded) > 1_000_000:
            raise ToolError("content exceeds 1 MiB")
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = stat.S_IMODE(path.stat().st_mode) if path.is_file() else None
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=path.parent, prefix=".lunar-write-", suffix=".tmp", delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(encoded)
                stream.flush()
                if mode is not None:
                    temporary.chmod(mode)
                os.fsync(stream.fileno())
            # Publish only complete content; a failed write must leave the incumbent intact.
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    # Cleanup failure must not obscure the original publication failure.
                    pass
        relative = path.relative_to(workspace.resolve()).as_posix()
        return ToolResult(output=f"wrote {relative}", artifacts=(relative,))

    def _list_dir(self, arguments: dict[str, object], workspace: Path) -> ToolResult:
        path = self._safe_path(workspace, arguments.get("path", "."))
        if not path.is_dir():
            raise ToolError(f"directory does not exist: {arguments.get('path', '.')}")
        entries = []
        for entry in sorted(path.iterdir(), key=lambda item: item.name):
            entries.append({"name": entry.name, "type": "directory" if entry.is_dir() else "file"})
        return ToolResult(json.dumps(entries, ensure_ascii=False))

    def _ask_user(self, arguments: dict[str, object]) -> ToolResult:
        question = arguments.get("question")
        if not isinstance(question, str) or not question.strip():
            raise ToolError("question must be a non-empty string")
        question = question.strip()
        if len(question.encode("utf-8")) > 8_000:
            raise ToolError("question exceeds 8 KiB")
        options = arguments.get("options", [])
        if not isinstance(options, list) or any(
            not isinstance(option, str) or not option.strip() for option in options
        ):
            raise ToolError("options must be a string array")
        if len(options) > 10 or any(len(option.encode("utf-8")) > 200 for option in options):
            raise ToolError("options exceed the input limit")
        normalized_options = [option.strip() for option in options]
        payload = {"status": "awaiting_input", "question": question, "options": normalized_options}
        return ToolResult(
            self._bounded_text(json.dumps(payload, ensure_ascii=False)),
            awaiting_input=True,
            input_question=question,
            input_options=tuple(normalized_options),
        )

    def _recall_memory(self, arguments: dict[str, object]) -> ToolResult:
        if self.memory is None:
            raise ToolError("memory tools are unavailable")
        query = arguments.get("query")
        if not isinstance(query, str):
            raise ToolError("query must be a string")
        limit = arguments.get("limit", 8)
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ToolError("limit must be an integer")
        limit = max(1, min(limit, 20))
        scopes = (self.memory_scope, "global") if self.memory_scope != "global" else ("global",)
        entries = self.memory.recall(query, scopes=scopes, limit=limit)
        payload = [
            {
                "id": entry.id,
                "scope": entry.scope,
                "kind": entry.kind,
                "content": entry.content,
                "tags": list(entry.tags),
            }
            for entry in entries
        ]
        return ToolResult(self._bounded_text(json.dumps(payload, ensure_ascii=False)))

    def _remember_memory(self, arguments: dict[str, object]) -> ToolResult:
        if self.memory is None:
            raise ToolError("memory tools are unavailable")
        content = arguments.get("content")
        if not isinstance(content, str):
            raise ToolError("content must be a string")
        content = self._redact(content)
        kind = arguments.get("kind", "note")
        if not isinstance(kind, str):
            raise ToolError("kind must be a string")
        tags = arguments.get("tags", [])
        if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
            raise ToolError("tags must be a string array")
        scope = arguments.get("scope", self.memory_scope)
        if not isinstance(scope, str) or not scope.strip():
            raise ToolError("scope must be a non-empty string")
        # A model can opt into global memory explicitly, but arbitrary namespaces are disallowed
        # so one task cannot silently read or mutate another task's private scope.
        if scope != "global" and scope != self.memory_scope:
            raise ToolError("scope must be global or the active run scope")
        entry = self.memory.remember(
            content,
            scope=scope,
            kind=kind,
            tags=tags,
            source="agent-tool",
        )
        return ToolResult(f"remembered {entry.id} in {entry.scope}")

    def _redact(self, value: str) -> str:
        for secret in self.redactions:
            value = value.replace(secret, "[REDACTED]")
        return value

    def _run_command(self, arguments: dict[str, object], workspace: Path) -> ToolResult:
        if not self.allow_exec:
            raise ToolError("run_command is disabled; pass --allow-exec to enable it")
        command = arguments.get("command")
        if isinstance(command, str):
            command = shlex.split(command)
        if not isinstance(command, list) or not command or any(not isinstance(item, str) for item in command):
            raise ToolError("command must be a non-empty string or string array")
        timeout = self.command_timeout
        deadline = self._execution_deadline.get()
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ToolError("command deadline expired before launch")
            timeout = min(timeout, remaining)
        try:
            completed = subprocess.run(
                command,
                cwd=workspace,
                env=self.command_environment,
                shell=False,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            streams = [
                part.decode("utf-8", errors="replace") if isinstance(part, bytes) else part or ""
                for part in (exc.stdout, exc.stderr)
            ]
            output = self._bounded_text("".join(streams))
            return ToolResult(
                output=f"command timed out after {timeout:g}s\n{output}",
                success=False,
            )
        stdout = self._bounded_text(completed.stdout)
        stderr = self._bounded_text(completed.stderr)
        output = f"exit_code={completed.returncode}\nstdout:\n{stdout}"
        if stderr:
            output += f"\nstderr:\n{stderr}"
        return ToolResult(output=output, success=completed.returncode == 0)

    def _bounded_text(self, value: str | bytes) -> str:
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        if len(value) <= self.max_output_bytes:
            return value
        return value[: self.max_output_bytes] + "\n[tool output truncated]"
