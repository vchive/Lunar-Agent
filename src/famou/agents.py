"""Runtime-neutral local Agent adapters.

The control plane owns task state; this module only defines how an explicitly selected worker is
invoked.  Nothing here searches PATH, a user's home directory, or a remote service.
"""

from __future__ import annotations

import inspect
import json
import math
import os
import re
import shlex
import signal
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from .runtime import Runtime, RuntimeResult

MAX_PROMPT_BYTES = 64 * 1024
MAX_TEXT_BYTES = 1024 * 1024
MAX_METADATA_BYTES = 16 * 1024
MAX_METADATA_ITEMS = 64
MAX_ARTIFACTS = 64
MAX_ARTIFACT_PATH_BYTES = 512
MAX_TIMEOUT_SECONDS = 24 * 60 * 60
MAX_CANDIDATE_TOOL_STEPS = 200
DEFAULT_RUNTIME_CAPABILITIES = (
    "read_files",
    "write_files",
    "run_tests",
    "write_artifacts",
    "analyze_data",
    "gather_sources",
)
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_SECRET_TEXT = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._-]{12,}|"
    r"api[_-]?key\s*[:=]\s*\S+)"
)


class AgentError(RuntimeError):
    """Base class for bounded Agent adapter failures."""


class AgentSelectionError(AgentError):
    """No explicitly registered adapter satisfies a role/capability request."""


class AgentInvocationError(AgentError):
    """An adapter could not start, complete, or normalize a worker invocation."""

    def __init__(self, message: str, *, candidate_diagnostic: Mapping[str, object] | None = None) -> None:
        super().__init__(message)
        self.candidate_diagnostic = dict(candidate_diagnostic) if isinstance(candidate_diagnostic, Mapping) else None


@dataclass(frozen=True, slots=True)
class CandidateGenerationBudget:
    """Authority-bound budget for one candidate-generation request."""

    budget_id: str
    max_tool_steps: int
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "budget_id", _bounded_text(self.budget_id, "budget_id", 256, allow_empty=False))
        if isinstance(self.max_tool_steps, bool) or not isinstance(self.max_tool_steps, int):
            raise TypeError("max_tool_steps must be an integer")
        if not 1 <= self.max_tool_steps <= MAX_CANDIDATE_TOOL_STEPS:
            raise ValueError(
                f"max_tool_steps must be between 1 and {MAX_CANDIDATE_TOOL_STEPS}"
            )
        if self.timeout_seconds is not None:
            if (isinstance(self.timeout_seconds, bool)
                    or not isinstance(self.timeout_seconds, (int, float))
                    or not math.isfinite(float(self.timeout_seconds))
                    or self.timeout_seconds <= 0
                    or self.timeout_seconds > MAX_TIMEOUT_SECONDS):
                raise ValueError(
                    f"timeout_seconds must be between 0 and {MAX_TIMEOUT_SECONDS} seconds"
                )
            object.__setattr__(self, "timeout_seconds", float(self.timeout_seconds))

    def to_dict(self) -> dict[str, object]:
        return {
            "budget_id": self.budget_id,
            "max_tool_steps": self.max_tool_steps,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True, slots=True)
class CandidateGenerationDiagnostic:
    """Safe completion projection for a candidate-generation budget."""

    budget_id: str
    max_tool_steps: int
    tool_steps_used: int
    tool_steps_remaining: int
    attempted_tool_calls: int | None
    completion: bool
    reason: str
    phase: str
    schema_version: str = "1"
    stage: str = "candidate_generation"
    outcome: str | None = None
    elapsed_ms: int | None = None
    timeout_ms: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "budget_id", _bounded_text(self.budget_id, "budget_id", 256, allow_empty=False))
        if isinstance(self.max_tool_steps, bool) or not isinstance(self.max_tool_steps, int) or not 1 <= self.max_tool_steps <= MAX_CANDIDATE_TOOL_STEPS:
            raise ValueError("invalid candidate diagnostic max_tool_steps")
        for value, label in ((self.tool_steps_used, "tool_steps_used"),
                             (self.tool_steps_remaining, "tool_steps_remaining")):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"invalid candidate diagnostic {label}")
        if self.attempted_tool_calls is not None and (
            isinstance(self.attempted_tool_calls, bool)
            or not isinstance(self.attempted_tool_calls, int)
            or self.attempted_tool_calls < 0
        ):
            raise ValueError("invalid candidate diagnostic attempted_tool_calls")
        if not isinstance(self.completion, bool):
            raise TypeError("invalid candidate diagnostic completion")
        if self.schema_version != "1":
            raise ValueError("invalid candidate diagnostic schema_version")
        if self.stage != "candidate_generation":
            raise ValueError("invalid candidate diagnostic stage")
        outcome = self.outcome or _candidate_outcome(self.reason)
        if outcome not in {
            "running", "completed", "tool_step_limit_reached", "tool_execution_failed",
            "timed_out", "cancelled", "empty_final_response", "malformed_candidate", "worker_failed",
        }:
            raise ValueError("invalid candidate diagnostic reason")
        object.__setattr__(self, "outcome", outcome)
        if self.elapsed_ms is not None and (
            isinstance(self.elapsed_ms, bool) or not isinstance(self.elapsed_ms, int) or self.elapsed_ms < 0
        ):
            raise ValueError("invalid candidate diagnostic elapsed_ms")
        if self.timeout_ms is not None and (
            isinstance(self.timeout_ms, bool) or not isinstance(self.timeout_ms, int) or self.timeout_ms <= 0
        ):
            raise ValueError("invalid candidate diagnostic timeout_ms")
        if not isinstance(self.phase, str) or not self.phase or len(self.phase) > 64:
            raise ValueError("invalid candidate diagnostic phase")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "budget_id": self.budget_id,
            "stage": self.stage,
            "outcome": self.outcome,
            "max_tool_steps": self.max_tool_steps,
            "tool_steps_used": self.tool_steps_used,
            "tool_steps_remaining": self.tool_steps_remaining,
            "attempted_tool_calls": self.attempted_tool_calls,
            "completion": self.completion,
            "reason": self.reason,
            "phase": self.phase,
            "elapsed_ms": self.elapsed_ms,
            "timeout_ms": self.timeout_ms,
        }


def _candidate_outcome(reason: str) -> str:
    return {
        "tool_failed": "tool_execution_failed",
        "timeout": "timed_out",
        "empty_response": "empty_final_response",
    }.get(reason, reason)


def candidate_failure_reason(error: BaseException) -> str:
    """Classify only typed/local failure boundaries; never inspect arbitrary prose."""
    if isinstance(error, TimeoutError):
        return "timeout"
    if type(error).__name__ in {"CancelledError", "CancellationError"}:
        return "cancelled"
    evidence = getattr(error, "evidence", None)
    if getattr(evidence, "reason", None) == "transport_timeout":
        return "timeout"
    return "worker_failed"


def _bounded_text(value: object, label: str, maximum: int, *, allow_empty: bool = True) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if "\x00" in value:
        raise ValueError(f"{label} must not contain NUL bytes")
    if not allow_empty and not value.strip():
        raise ValueError(f"{label} must not be empty")
    if len(value.encode("utf-8")) > maximum:
        raise ValueError(f"{label} exceeds {maximum} bytes")
    return value


def _safe_event_text(value: str, maximum: int = 512) -> str:
    """Bound and redact scalar text before it crosses the durable event boundary."""
    redacted = _SECRET_TEXT.sub("[REDACTED]", value)
    encoded = redacted.encode("utf-8")
    if len(encoded) <= maximum:
        return redacted
    suffix = "\n[truncated]"
    budget = max(1, maximum - len(suffix.encode("utf-8")))
    return encoded[:budget].decode("utf-8", errors="ignore") + suffix


def _safe_event_error(error: object) -> str:
    return _safe_event_text(" ".join(str(error).split()), 512)


def _token(value: object, label: str) -> str:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise ValueError(f"{label} must be a non-empty safe token")
    return value


def _tokens(values: Sequence[str] | set[str] | frozenset[str], label: str) -> frozenset[str]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{label} must be a sequence of strings")
    if len(values) > MAX_METADATA_ITEMS:
        raise ValueError(f"{label} contains too many entries")
    result = frozenset(_token(item, f"{label} entry") for item in values)
    if len(result) != len(values):
        raise ValueError(f"{label} contains duplicate entries")
    return result


def _artifact_path(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("artifact paths must be strings")
    if not value or "\x00" in value or "\\" in value:
        raise ValueError("artifact path is invalid")
    path = Path(value)
    windows_absolute = bool(re.match(r"^[A-Za-z]:[/\\]", value))
    if path.is_absolute() or windows_absolute or "." in path.parts or ".." in path.parts:
        raise ValueError(f"artifact path must be run-relative: {value!r}")
    normalized = path.as_posix()
    if not normalized or len(normalized.encode("utf-8")) > MAX_ARTIFACT_PATH_BYTES:
        raise ValueError("artifact path is empty or too long")
    return normalized


def _metadata(value: Mapping[str, object] | None) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("metadata must be an object")
    if len(value) > MAX_METADATA_ITEMS:
        raise ValueError("metadata contains too many entries")
    result: dict[str, object] = {}
    for key, item in value.items():
        safe_key = _token(key, "metadata key")
        if not isinstance(item, (str, int, float, bool)) and item is not None:
            raise ValueError("metadata values must be scalar")
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError("metadata float values must be finite")
        if isinstance(item, str):
            _bounded_text(item, f"metadata value for {safe_key}", 2_000)
        result[safe_key] = item
    try:
        encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("metadata is not JSON serializable") from exc
    if len(encoded.encode("utf-8")) > MAX_METADATA_BYTES:
        raise ValueError(f"metadata exceeds {MAX_METADATA_BYTES} bytes")
    return result


@dataclass(frozen=True, slots=True)
class AgentRequest:
    """Bounded immutable input sent to one selected Agent worker."""

    run_id: str
    task_id: str
    role: str
    prompt: str
    required_capabilities: tuple[str, ...] = ()
    workspace: Path = field(default_factory=Path.cwd)
    timeout: float | None = None
    candidate_budget: CandidateGenerationBudget | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _bounded_text(self.run_id, "run_id", 256, allow_empty=False))
        object.__setattr__(self, "task_id", _bounded_text(self.task_id, "task_id", 256, allow_empty=False))
        object.__setattr__(self, "role", _token(self.role, "role"))
        object.__setattr__(self, "prompt", _bounded_text(self.prompt, "prompt", MAX_PROMPT_BYTES, allow_empty=False))
        capabilities = _tokens(self.required_capabilities, "required_capabilities")
        object.__setattr__(self, "required_capabilities", tuple(sorted(capabilities)))
        workspace = Path(self.workspace).expanduser()
        if not workspace.is_absolute():
            raise ValueError("workspace must be an absolute path")
        if "\x00" in str(workspace):
            raise ValueError("workspace must not contain NUL bytes")
        object.__setattr__(self, "workspace", workspace.resolve(strict=False))
        if self.timeout is not None:
            if isinstance(self.timeout, bool) or not isinstance(self.timeout, (int, float)):
                raise ValueError("timeout must be a positive number")
            if self.timeout <= 0 or self.timeout > MAX_TIMEOUT_SECONDS:
                raise ValueError(f"timeout must be between 0 and {MAX_TIMEOUT_SECONDS} seconds")
            object.__setattr__(self, "timeout", float(self.timeout))
        if self.candidate_budget is not None and not isinstance(
            self.candidate_budget, CandidateGenerationBudget
        ):
            raise TypeError("candidate_budget must be a CandidateGenerationBudget or None")

    def to_dict(self) -> dict[str, object]:
        value = {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "role": self.role,
            "prompt": self.prompt,
            "required_capabilities": list(self.required_capabilities),
            "workspace": str(self.workspace),
            "timeout": self.timeout,
        }
        if self.candidate_budget is not None:
            value["candidate_budget"] = self.candidate_budget.to_dict()
        return value


@dataclass(frozen=True, slots=True)
class AgentResult:
    """Bounded normalized output returned by an Agent adapter."""

    adapter_name: str
    role: str
    text: str
    artifacts: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)
    status: str = "succeeded"
    error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "adapter_name", _token(self.adapter_name, "adapter_name"))
        object.__setattr__(self, "role", _token(self.role, "role"))
        status = _token(self.status, "status")
        if status not in {"succeeded", "failed", "cancelled"}:
            raise ValueError("status must be succeeded, failed, or cancelled")
        object.__setattr__(self, "status", status)
        text = _bounded_text(self.text, "text", MAX_TEXT_BYTES)
        if status == "succeeded" and not text.strip():
            raise ValueError("successful Agent results require non-empty text")
        object.__setattr__(self, "text", text)
        if len(self.artifacts) > MAX_ARTIFACTS:
            raise ValueError("too many artifacts")
        normalized = tuple(_artifact_path(item) for item in self.artifacts)
        if len(set(normalized)) != len(normalized):
            raise ValueError("artifacts contain duplicate paths")
        object.__setattr__(self, "artifacts", normalized)
        object.__setattr__(self, "metadata", _metadata(self.metadata))
        if self.error is not None:
            object.__setattr__(self, "error", _bounded_text(self.error, "error", 8_000, allow_empty=False))
        if status in {"failed", "cancelled"} and not self.error:
            raise ValueError(f"{status} Agent results require an error")
        if status == "succeeded" and self.error is not None:
            raise ValueError("successful Agent results must not contain an error")

    def to_dict(self) -> dict[str, object]:
        return {
            "adapter_name": self.adapter_name,
            "role": self.role,
            "status": self.status,
            "text": self.text,
            "artifacts": list(self.artifacts),
            "metadata": dict(self.metadata),
            "error": self.error,
        }


ProcessObserver = Callable[[int, int | None], None]


@runtime_checkable
class AgentAdapter(Protocol):
    """Small lifecycle contract implemented by explicit local workers."""

    name: str
    roles: frozenset[str]
    capabilities: frozenset[str]

    def run(self, request: AgentRequest) -> AgentResult:
        ...

    def cancel(self) -> None:
        ...

    def process_info(self) -> tuple[int | None, int | None]:
        ...

    def set_process_observer(self, observer: ProcessObserver | None) -> None:
        ...


class RuntimeAgentAdapter:
    """Expose an existing Runtime through the role-bearing Agent contract."""

    def __init__(
        self,
        runtime: Runtime,
        *,
        name: str | None = None,
        roles: Sequence[str] = ("worker", "solver", "general"),
        capabilities: Sequence[str] = DEFAULT_RUNTIME_CAPABILITIES,
    ) -> None:
        self.runtime = runtime
        self.name = _token(name or getattr(runtime, "name", "runtime"), "adapter name")
        self.roles = _tokens(roles, "roles")
        self.capabilities = _tokens(capabilities, "capabilities")
        self._event_sink: Callable[[str, dict[str, object]], None] | None = None

    def set_event_sink(
        self, sink: Callable[[str, dict[str, object]], None] | None
    ) -> None:
        """Forward bounded runtime lifecycle events to an owning evolution observer."""
        if sink is not None and not callable(sink):
            raise TypeError("event sink must be callable or None")
        self._event_sink = sink

    def run(self, request: AgentRequest) -> AgentResult:
        if not isinstance(request, AgentRequest):
            raise TypeError("request must be an AgentRequest")
        set_runtime_event_sink = getattr(self.runtime, "set_event_sink", None)
        runtime_event_sink: Callable[[str, dict[str, object]], None] | None = None
        runtime_event_emitted = False
        if callable(set_runtime_event_sink):
            def forward_runtime_event(event_type: str, payload: dict[str, object]) -> None:
                nonlocal runtime_event_emitted
                runtime_event_emitted = True
                self._forward_event(request, event_type, payload)

            runtime_event_sink = forward_runtime_event
            set_runtime_event_sink(runtime_event_sink)
        try:
            set_context = getattr(self.runtime, "set_context", None)
            if callable(set_context):
                set_context(request.run_id, request.task_id, request.prompt)
            set_session_path = getattr(self.runtime, "set_session_path", None)
            if callable(set_session_path):
                set_session_path(request.workspace / "session-transcript.jsonl")
            runtime_timeout = request.timeout
            budget = request.candidate_budget
            if budget is not None and budget.timeout_seconds is not None:
                runtime_timeout = (
                    budget.timeout_seconds
                    if runtime_timeout is None
                    else min(runtime_timeout, budget.timeout_seconds)
                )
            runtime_run = self.runtime.run
            kwargs: dict[str, object] = {}
            if budget is not None:
                try:
                    parameters = inspect.signature(runtime_run).parameters
                except (TypeError, ValueError):
                    parameters = {}
                accepts_kwargs = any(
                    parameter.kind is inspect.Parameter.VAR_KEYWORD
                    for parameter in parameters.values()
                )
                if "max_tool_steps" not in parameters and not accepts_kwargs:
                    raise AgentInvocationError(
                        "runtime does not support candidate tool-step budgets"
                    )
                kwargs["max_tool_steps"] = budget.max_tool_steps
                kwargs["budget_id"] = budget.budget_id
            result = runtime_run(request.prompt, request.workspace, runtime_timeout, **kwargs)
        except Exception as exc:
            diagnostic = getattr(self.runtime, "last_candidate_diagnostic", None)
            if callable(diagnostic):
                diagnostic = diagnostic()
            if isinstance(diagnostic, Mapping):
                self._forward_event(request, "agent_candidate_generation", diagnostic)
            if not runtime_event_emitted:
                self._forward_event(
                    request,
                    "agent_runtime_failure",
                    {"phase": "run", "error": _safe_event_error(exc)},
                )
            if isinstance(exc, AgentError):
                raise
            candidate_diagnostic = diagnostic if isinstance(diagnostic, Mapping) else None
            raise AgentInvocationError(
                _bounded_error(str(exc)), candidate_diagnostic=candidate_diagnostic,
            ) from exc
        finally:
            if runtime_event_sink is not None:
                # A Runtime instance may be reused by a caller; never leave an old evolution
                # observer attached to a later role or run.
                set_runtime_event_sink(None)
        if not isinstance(result, RuntimeResult):
            raise AgentInvocationError("runtime returned an invalid result")
        try:
            declared_artifacts = list(result.artifacts)
            session_path = getattr(self.runtime, "session_path", None)
            if callable(session_path):
                transcript = session_path()
                if transcript is not None and Path(transcript).is_file():
                    raw_transcript = Path(transcript).expanduser()
                    if raw_transcript.is_symlink():
                        raise AgentInvocationError("runtime session artifact must not be a symlink")
                    resolved = raw_transcript.resolve(strict=False)
                    try:
                        relative = resolved.relative_to(request.workspace.resolve())
                    except ValueError as exc:
                        raise AgentInvocationError("runtime session artifact escapes workspace") from exc
                    if relative.as_posix() not in declared_artifacts:
                        declared_artifacts.append(relative.as_posix())
            metadata = {**result.metadata, "runtime": self.name}
            diagnostic = getattr(self.runtime, "last_candidate_diagnostic", None)
            if callable(diagnostic):
                diagnostic = diagnostic()
            if isinstance(diagnostic, Mapping):
                for key, value in diagnostic.items():
                    if isinstance(key, str) and isinstance(value, (str, int, float, bool)):
                        metadata[f"candidate_{key}"] = str(value).lower() if isinstance(value, bool) else str(value)
            return AgentResult(
                adapter_name=self.name,
                role=request.role,
                text=result.text,
                artifacts=tuple(declared_artifacts),
                metadata=metadata,
            )
        except (TypeError, ValueError) as exc:
            raise AgentInvocationError(_bounded_error(str(exc))) from exc

    def _forward_event(
        self, request: AgentRequest, event_type: str, payload: Mapping[str, object]
    ) -> None:
        if self._event_sink is None:
            return
        bounded: dict[str, object] = {
            "adapter": self.name,
            "role": request.role,
            "run_id": request.run_id,
            "task_id": request.task_id,
        }
        if request.candidate_budget is not None:
            bounded["budget_id"] = request.candidate_budget.budget_id
            bounded["max_tool_steps"] = request.candidate_budget.max_tool_steps
        if isinstance(payload, Mapping):
            for key, value in list(payload.items())[:16]:
                if not isinstance(key, str) or not _TOKEN.fullmatch(key):
                    continue
                if isinstance(value, (bool, int, float)) or value is None:
                    bounded[key] = value
                elif isinstance(value, str):
                    bounded[key] = _safe_event_text(value)
        self._event_sink(event_type, bounded)

    def cancel(self) -> None:
        self.runtime.cancel()

    def process_info(self) -> tuple[int | None, int | None]:
        return self.runtime.process_info()

    def set_process_observer(self, observer: ProcessObserver | None) -> None:
        self.runtime.set_process_observer(observer)


class CommandAgentAdapter:
    """Invoke an explicitly configured executable using one JSON stdin/stdout exchange."""

    def __init__(
        self,
        command: str | Sequence[str],
        roles: Sequence[str] = ("worker", "solver", "general"),
        capabilities: Sequence[str] = (),
        *,
        name: str = "command",
        max_output_bytes: int = MAX_TEXT_BYTES,
    ) -> None:
        if isinstance(command, str):
            # A string is accepted only as one executable token; callers that need arguments can
            # pass a sequence or use the CLI's explicit shell-like parser.
            command = (command,)
        if not command or isinstance(command, (bytes, bytearray)):
            raise ValueError("command must not be empty")
        normalized = tuple(str(item) for item in command)
        if any(not item or "\x00" in item for item in normalized):
            raise ValueError("command arguments must be non-empty and NUL-free")
        executable = Path(normalized[0]).expanduser()
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError("command must start with an existing absolute executable path")
        if isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int) or max_output_bytes < 1:
            raise ValueError("max_output_bytes must be a positive integer")
        self.command = normalized
        self.name = _token(name, "adapter name")
        self.roles = _tokens(roles, "roles")
        self.capabilities = _tokens(capabilities, "capabilities")
        self.max_output_bytes = max_output_bytes
        self._process: subprocess.Popen[bytes] | None = None
        self._observer: ProcessObserver | None = None

    @classmethod
    def from_shell_like(
        cls,
        command: str,
        *,
        name: str = "command",
        roles: Sequence[str] = ("worker", "solver", "general"),
        capabilities: Sequence[str] = (),
        max_output_bytes: int = MAX_TEXT_BYTES,
    ) -> CommandAgentAdapter:
        try:
            parts = tuple(shlex.split(command))
        except ValueError as exc:
            raise ValueError(f"command is not valid shell-like argument text: {exc}") from exc
        return cls(parts, roles, capabilities, name=name, max_output_bytes=max_output_bytes)

    def set_process_observer(self, observer: ProcessObserver | None) -> None:
        self._observer = observer

    def process_info(self) -> tuple[int | None, int | None]:
        process = self._process
        if process is None or process.poll() is not None:
            return (None, None)
        try:
            return (process.pid, os.getpgid(process.pid))
        except OSError:
            return (process.pid, None)

    def run(self, request: AgentRequest) -> AgentResult:
        if not isinstance(request, AgentRequest):
            raise TypeError("request must be an AgentRequest")
        request.workspace.mkdir(parents=True, exist_ok=True)
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                self.command,
                cwd=request.workspace,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            self._process = process
            if self._observer is not None:
                try:
                    self._observer(process.pid, os.getpgid(process.pid))
                except OSError:
                    self._observer(process.pid, None)
            payload = json.dumps(request.to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")
            stdout, stderr = process.communicate(input=payload, timeout=request.timeout)
        except subprocess.TimeoutExpired as exc:
            if process is not None:
                self._terminate(process)
                stdout, stderr = process.communicate()
            else:
                stdout, stderr = b"", b""
            del stdout, stderr
            raise AgentInvocationError(
                f"agent {self.name} timed out after {request.timeout}s"
            ) from exc
        except OSError as exc:
            raise AgentInvocationError(_bounded_error(f"could not start agent: {exc}")) from exc
        finally:
            self._process = None
        if len(stdout) > self.max_output_bytes:
            raise AgentInvocationError(f"agent stdout exceeds {self.max_output_bytes} bytes")
        if len(stderr) > 16_000:
            raise AgentInvocationError("agent stderr exceeds 16000 bytes")
        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()[-2_000:]
            suffix = f": {detail}" if detail else ""
            raise AgentInvocationError(
                f"agent exited with code {process.returncode}{suffix}"
            )
        try:
            output = stdout.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise AgentInvocationError("agent stdout is not valid UTF-8") from exc
        if not output:
            raise AgentInvocationError("agent returned empty stdout")
        return self._normalize_output(output, request)

    def cancel(self) -> None:
        process = self._process
        if process is not None and process.poll() is None:
            self._terminate(process)

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes]) -> None:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (OSError, ProcessLookupError):
            try:
                process.terminate()
            except OSError:
                return

    def _normalize_output(self, output: str, request: AgentRequest) -> AgentResult:
        payload: object
        if output[:1] in {"{", "["}:
            try:
                payload = json.loads(output)
            except json.JSONDecodeError as exc:
                raise AgentInvocationError("agent stdout contains malformed JSON") from exc
            if not isinstance(payload, dict):
                raise AgentInvocationError("agent JSON response must be an object")
        else:
            payload = {"status": "succeeded", "text": output}
        assert isinstance(payload, dict)
        raw_status = payload.get("status")
        raw_error = payload.get("error")
        status = raw_status if raw_status is not None else ("failed" if raw_error else "succeeded")
        if "text" in payload:
            text = payload["text"]
        elif "result" in payload:
            text = payload["result"]
        elif "files" in payload:
            # Bundle generation validates the complete object itself. Preserve its original
            # JSON so duplicate fields and mixed single-/multi-file shapes cannot be erased
            # by adapter normalization before the bundle parser sees them.
            text = output
        elif "source" in payload:
            # Preserve optional candidate filename/metadata for AgentCandidateGenerator while
            # keeping the shared AgentResult text contract unchanged.
            text = json.dumps(
                {
                    "source": payload["source"],
                    **({"filename": payload["filename"]} if "filename" in payload else {}),
                    **({"metadata": payload["metadata"]} if "metadata" in payload else {}),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        else:
            text = ""
        artifacts = payload.get("artifacts", ())
        metadata = payload.get("metadata", {})
        if not isinstance(status, str):
            raise AgentInvocationError("agent response status must be a string")
        if not isinstance(text, str):
            raise AgentInvocationError("agent response text must be a string")
        if not isinstance(artifacts, (list, tuple)):
            raise AgentInvocationError("agent response artifacts must be an array")
        if raw_error is not None and not isinstance(raw_error, str):
            raise AgentInvocationError("agent response error must be a string")
        if not isinstance(metadata, Mapping):
            raise AgentInvocationError("agent response metadata must be an object")
        try:
            return AgentResult(
                adapter_name=self.name,
                role=request.role,
                text=text,
                artifacts=tuple(artifacts),
                metadata={**dict(metadata), "command": self.command[0]},
                status=status,
                error=raw_error,
            )
        except (TypeError, ValueError) as exc:
            raise AgentInvocationError(_bounded_error(str(exc))) from exc


class AgentRegistry:
    """Explicit deterministic registry of local Agent adapters."""

    def __init__(self, adapters: Sequence[AgentAdapter] = ()) -> None:
        self._adapters: dict[str, AgentAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: AgentAdapter) -> AgentAdapter:
        name = _token(getattr(adapter, "name", None), "adapter name")
        roles = _tokens(getattr(adapter, "roles", ()), "roles")
        capabilities = _tokens(getattr(adapter, "capabilities", ()), "capabilities")
        required_methods = ("run", "cancel", "process_info", "set_process_observer")
        if any(not callable(getattr(adapter, method, None)) for method in required_methods):
            raise TypeError("adapter does not implement the AgentAdapter lifecycle")
        if name in self._adapters:
            raise ValueError(f"duplicate adapter name: {name}")
        # Validate declarations even when an adapter supplied mutable sets.
        try:
            adapter.roles = roles
            adapter.capabilities = capabilities
        except (AttributeError, TypeError):
            pass
        self._adapters[name] = adapter
        return adapter

    def get(self, name: str) -> AgentAdapter | None:
        return self._adapters.get(name)

    @property
    def adapters(self) -> tuple[AgentAdapter, ...]:
        """Return registered adapters in deterministic name order."""
        return tuple(self._adapters[name] for name in sorted(self._adapters))

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    def select(
        self,
        role: str,
        required_capabilities: Sequence[str] = (),
        preferred: str | None = None,
    ) -> AgentAdapter:
        role = _token(role, "role")
        required = _tokens(required_capabilities, "required_capabilities")

        def compatible(adapter: AgentAdapter) -> bool:
            return role in frozenset(adapter.roles) and required.issubset(
                frozenset(adapter.capabilities)
            )

        if preferred is not None:
            preferred_name = _token(preferred, "preferred adapter")
            adapter = self._adapters.get(preferred_name)
            if adapter is None:
                raise AgentSelectionError(f"preferred adapter is not registered: {preferred_name}")
            if not compatible(adapter):
                missing = sorted(required - frozenset(adapter.capabilities))
                reason = f"missing capabilities: {', '.join(missing)}" if missing else "role mismatch"
                raise AgentSelectionError(
                    f"preferred adapter {preferred_name} is incompatible ({reason})"
                )
            return adapter
        candidates = [adapter for adapter in self._adapters.values() if compatible(adapter)]
        if not candidates:
            requested = ", ".join(sorted(required)) or "none"
            raise AgentSelectionError(
                f"no registered adapter supports role {role!r} and capabilities {requested}"
            )
        return min(candidates, key=lambda item: (item.name, item.__class__.__name__))


def _bounded_error(value: object) -> str:
    text = " ".join(str(value).split()).strip() or "agent invocation failed"
    return text[-8_000:]


__all__ = [
    "AgentAdapter",
    "AgentError",
    "AgentInvocationError",
    "AgentRegistry",
    "AgentRequest",
    "AgentResult",
    "AgentSelectionError",
    "CandidateGenerationBudget",
    "CandidateGenerationDiagnostic",
    "CommandAgentAdapter",
    "RuntimeAgentAdapter",
]
