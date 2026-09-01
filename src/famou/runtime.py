"""Execution boundary for local Famou runtimes.

The module intentionally contains no Hermes/OpenCode/Codex discovery. A runtime is either the
repository-owned deterministic mock or an explicitly configured subprocess.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol


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
                except Exception:  # noqa: BLE001 - metadata observation must not break execution
                    pass
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


def build_runtime(name: str, command: str | None = None) -> Runtime:
    if name == "mock":
        return MockRuntime()
    if name == "subprocess":
        return SubprocessRuntime(command)
    raise ValueError(f"unknown runtime {name!r}; choose mock or subprocess")
