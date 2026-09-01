"""Small, local tools exposed to the Build agent loop.

Tools receive a task workspace rather than the process working directory. Every filesystem operation
is resolved and checked before it is performed; command execution is opt-in and never uses a shell.
"""

from __future__ import annotations

import json
import shlex
import sqlite3
import subprocess
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

    def set_memory_scope(self, scope: str) -> None:
        """Set the default scope used by memory tools for the active task."""
        self.memory_scope = scope

    def schemas(self) -> tuple[dict[str, object], ...]:
        schemas: list[dict[str, object]] = [
            self._schema(
                "read_file",
                "Read a UTF-8 text file from the task workspace.",
                {"path": {"type": "string"}},
                ["path"],
            ),
            self._schema(
                "write_file",
                "Write UTF-8 text to a file in the task workspace and return its artifact path.",
                {"path": {"type": "string"}, "content": {"type": "string"}},
                ["path", "content"],
            ),
            self._schema(
                "list_dir",
                "List entries in a task workspace directory.",
                {"path": {"type": "string"}},
                [],
            ),
        ]
        if self.memory is not None:
            schemas.extend(
                (
                    self._schema(
                        "recall_memory",
                        "Recall relevant durable notes from this agent's local memory.",
                        {
                            "query": {"type": "string"},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                        },
                        ["query"],
                    ),
                    self._schema(
                        "remember_memory",
                        "Store a concise fact, preference, decision, or progress note for later runs.",
                        {
                            "content": {"type": "string"},
                            "kind": {"type": "string"},
                            "tags": {"type": "array", "items": {"type": "string"}},
                            "scope": {"type": "string"},
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
                            ]
                        }
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
        if len(content.encode("utf-8")) > 1_000_000:
            raise ToolError("content exceeds 1 MiB")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
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
        try:
            completed = subprocess.run(
                command,
                cwd=workspace,
                shell=False,
                text=True,
                capture_output=True,
                timeout=self.command_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            output = self._bounded_text((exc.stdout or "") + (exc.stderr or ""))
            return ToolResult(
                output=f"command timed out after {self.command_timeout}s\n{output}",
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
