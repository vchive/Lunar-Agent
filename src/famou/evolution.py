"""Local, runtime-neutral evolution strategies.

The strategy layer deliberately knows nothing about Hermes, OpenCode, Codex, or a remote service.
It consumes an algorithm contract, an injected candidate generator, and an injected evaluator.  The
native population implementation maintains an append-only candidate archive; OpenEvolve is an
optional subprocess adapter rather than a package dependency.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from .algorithm import (
    ALGORITHM_FAMILY_REPERTOIRES,
    EVOLUTION_STRATEGIES,
    MAX_INPUT_FILE_BYTES,
    MAX_INPUT_FILES,
    AlgorithmProblemContract,
    EvaluationReport,
    OutputSpec,
)
from .evaluator import evaluate_output_contract

MAX_SOURCE_BYTES = 512 * 1024
MAX_METADATA_BYTES = 8 * 1024
MAX_ARCHIVE_LINE_BYTES = 64 * 1024
MAX_STATE_BYTES = 64 * 1024
MAX_EXTERNAL_RESULT_BYTES = 64 * 1024
MAX_ERROR_BYTES = 2_000
MAX_COMMAND_ARGS = 32
MAX_EXECUTION_OUTPUT_BYTES = 16 * 1024
MAX_EXECUTION_ERROR_BYTES = 512
MAX_EXECUTION_ARTIFACTS = 32
_SEED_STAGE_NAME = ".evolution-seed-stage-v1"
_SEED_BACKUP_NAME = ".evolution-seed-backup-v1"
# Process creation and interpreter startup can consume a few tens of milliseconds even for an
# empty candidate. A floor prevents a sub-scheduling-quantum budget from timing out before the
# candidate gets a chance to execute; longer budgets retain the requested value exactly.
MIN_PROCESS_TIMEOUT_SECONDS = 0.05
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SECRET_OUTPUT = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._-]{12,}|"
    r"api[_-]?key\s*[:=]\s*\S+)"
)
_OFFSPRING_OUTCOME_CODES = frozenset(
    {
        "evaluated",
        "candidate_failed",
        "evaluator_timeout",
        "worker_unknown",
        "run_failed",
    }
)


class EvolutionError(RuntimeError):
    """A bounded, actionable strategy error."""


class WorkerUnknownError(EvolutionError):
    """Explicit signal that an evaluator worker's terminal state cannot be reconciled."""


def _bounded_error(error: object) -> str:
    text = " ".join(str(error).split())
    return text[-MAX_ERROR_BYTES:] if text else "unknown evolution error"


def _bounded_output(value: object, limit: int = MAX_EXECUTION_OUTPUT_BYTES) -> str:
    """Redact and cap process output before it crosses the execution evidence boundary."""
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value) if value is not None else ""
    text = _SECRET_OUTPUT.sub("[REDACTED]", text)
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", errors="ignore")


def _safe_id(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise EvolutionError(f"{field_name} must be a safe identifier")
    return value


def _safe_relative_path(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise EvolutionError(f"{field_name} must be a relative path")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise EvolutionError(f"{field_name} must be a relative path")
    return path.as_posix()


def _confined(root: Path, value: Path, field_name: str) -> Path:
    candidate = value.resolve(strict=False)
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise EvolutionError(f"{field_name} escapes the run workspace") from exc
    return candidate


def _reject_symlink_components(path: Path, stop: Path, field_name: str) -> None:
    """Reject pre-existing symlink components before writing a confined artifact."""
    current = path
    stop = stop.resolve()
    while current != stop and current != current.parent:
        if current.is_symlink():
            raise EvolutionError(f"{field_name} must not contain a symlink")
        current = current.parent


@dataclass(frozen=True)
class CandidateInputArtifact:
    """One immutable, run-relative input admitted to candidate execution."""

    path: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        relative = _safe_relative_path(self.path, "candidate input path")
        if not relative.startswith("data/raw/") or relative == "data/raw/":
            raise ValueError("candidate input path must be below data/raw/")
        if len(relative.encode("utf-8")) > 1_024:
            raise ValueError("candidate input path exceeds the bounded path limit")
        if (
            isinstance(self.size, bool)
            or not isinstance(self.size, int)
            or not 0 <= self.size <= MAX_INPUT_FILE_BYTES
        ):
            raise ValueError("candidate input size is invalid")
        if not isinstance(self.sha256, str) or not _SHA256.fullmatch(self.sha256):
            raise ValueError("candidate input sha256 must be a lowercase SHA-256 digest")
        object.__setattr__(self, "path", relative)


def stage_candidate_inputs(
    source_workspace: Path,
    destination_workspace: Path,
    inputs: Sequence[CandidateInputArtifact],
) -> tuple[str, ...]:
    """Digest-check and atomically copy immutable inputs between private workspaces."""
    raw_source_root = Path(source_workspace).expanduser()
    raw_destination_root = Path(destination_workspace).expanduser()
    if raw_source_root.is_symlink() or raw_destination_root.is_symlink():
        raise EvolutionError("candidate input workspace must not be a symlink")
    source_root = raw_source_root.resolve(strict=False)
    destination_root = raw_destination_root.resolve(strict=False)
    if not source_root.is_dir():
        raise EvolutionError("candidate input source workspace is missing")
    destination_root.mkdir(parents=True, exist_ok=True)
    if len(inputs) > MAX_INPUT_FILES:
        raise EvolutionError("candidate input list exceeds the bounded file limit")

    copied: list[str] = []
    for descriptor in inputs:
        if not isinstance(descriptor, CandidateInputArtifact):
            raise TypeError("candidate inputs must contain CandidateInputArtifact records")
        raw_source = source_root / descriptor.path
        _reject_symlink_components(raw_source, source_root, "candidate input source path")
        source = _confined(source_root, raw_source, "candidate input source path")
        if raw_source.is_symlink() or not source.is_file():
            raise EvolutionError(f"candidate input source is missing or unsafe: {descriptor.path}")
        content = source.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if len(content) != descriptor.size or digest != descriptor.sha256:
            raise EvolutionError(f"candidate input digest does not match: {descriptor.path}")

        raw_target = destination_root / descriptor.path
        _reject_symlink_components(raw_target, destination_root, "candidate input target path")
        target = _confined(destination_root, raw_target, "candidate input target path")
        target.parent.mkdir(parents=True, exist_ok=True)
        _reject_symlink_components(raw_target, destination_root, "candidate input target path")
        if raw_target.is_symlink():
            raise EvolutionError(f"candidate input target is unsafe: {descriptor.path}")
        if target.exists():
            if not target.is_file():
                raise EvolutionError(f"candidate input target is unsafe: {descriptor.path}")
            existing = target.read_bytes()
            if len(existing) != descriptor.size or hashlib.sha256(existing).hexdigest() != digest:
                raise EvolutionError(
                    f"candidate input target already contains different data: {descriptor.path}"
                )
        else:
            temporary = target.with_name(f".{target.name}.input.tmp")
            if temporary.is_symlink():
                raise EvolutionError(f"candidate input temporary path is unsafe: {descriptor.path}")
            if temporary.exists():
                stale = temporary.read_bytes() if temporary.is_file() else b""
                if len(stale) != descriptor.size or hashlib.sha256(stale).hexdigest() != digest:
                    raise EvolutionError(
                        f"candidate input temporary path contains different data: {descriptor.path}"
                    )
            else:
                with temporary.open("xb") as stream:
                    stream.write(content)
            try:
                os.link(temporary, target)
            except FileExistsError:
                concurrent = target.read_bytes() if target.is_file() else b""
                if (
                    len(concurrent) != descriptor.size
                    or hashlib.sha256(concurrent).hexdigest() != digest
                ):
                    raise EvolutionError(
                        f"candidate input target already contains different data: {descriptor.path}"
                    )
            else:
                temporary.unlink()
        if target.stat().st_size != descriptor.size or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise EvolutionError(f"candidate input copy digest does not match: {descriptor.path}")
        copied.append(descriptor.path)
    return tuple(copied)


def contract_candidate_runner_fingerprint(
    contract: AlgorithmProblemContract,
    inputs: Sequence[CandidateInputArtifact],
) -> str:
    """Return a path- and credential-free identity for the built-in search protocol."""
    if not isinstance(contract, AlgorithmProblemContract):
        raise TypeError("contract must be an AlgorithmProblemContract")
    normalized = tuple(inputs)
    if len(normalized) > MAX_INPUT_FILES:
        raise ValueError("candidate input list exceeds the bounded file limit")
    if any(not isinstance(item, CandidateInputArtifact) for item in normalized):
        raise TypeError("inputs must contain CandidateInputArtifact records")
    if len({item.path for item in normalized}) != len(normalized):
        raise ValueError("candidate input paths must be unique")
    payload = {
        "protocol": "contract-candidate-runner-v1",
        "python": {
            "implementation": sys.implementation.name,
            "version": [sys.version_info.major, sys.version_info.minor, sys.version_info.micro],
        },
        "contract_sha256": contract.digest(),
        "inputs": [
            {"path": item.path, "size": item.size, "sha256": item.sha256}
            for item in sorted(normalized, key=lambda item: item.path)
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CandidateDraft:
    """Unpersisted source returned by a candidate generator."""

    source: str
    filename: str = "candidate.py"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip():
            raise EvolutionError("candidate source must be non-empty text")
        if len(self.source.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise EvolutionError("candidate source exceeds the bounded source limit")
        _safe_relative_path(self.filename, "candidate filename")
        encoded = json.dumps(self.metadata, ensure_ascii=False, sort_keys=True).encode("utf-8")
        if len(encoded) > MAX_METADATA_BYTES:
            raise EvolutionError("candidate metadata exceeds the bounded metadata limit")


@dataclass(frozen=True)
class CandidateExecution:
    """Bounded evidence from one candidate process invocation."""

    status: Literal["succeeded", "failed", "timed_out"]
    exit_code: int | None
    duration_ms: int
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    artifacts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in {"succeeded", "failed", "timed_out"}:
            raise ValueError("execution status must be succeeded, failed, or timed_out")
        if self.exit_code is not None and (
            isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int)
        ):
            raise ValueError("execution exit_code must be an integer or null")
        if (
            isinstance(self.duration_ms, bool)
            or not isinstance(self.duration_ms, int)
            or self.duration_ms < 0
            or self.duration_ms > 86_400_000
        ):
            raise ValueError("execution duration_ms must be a bounded non-negative integer")
        if not isinstance(self.stdout, str) or not isinstance(self.stderr, str):
            raise TypeError("execution stdout and stderr must be text")
        normalized_stdout = _bounded_output(self.stdout)
        normalized_stderr = _bounded_output(self.stderr)
        object.__setattr__(self, "stdout", normalized_stdout)
        object.__setattr__(self, "stderr", normalized_stderr)
        if self.error is not None and not isinstance(self.error, str):
            raise TypeError("execution error must be text or null")
        if self.error is not None:
            object.__setattr__(self, "error", _bounded_output(self.error, MAX_EXECUTION_ERROR_BYTES).strip())
        for name, value in (("stdout", normalized_stdout), ("stderr", normalized_stderr)):
            if len(value.encode("utf-8")) > MAX_EXECUTION_OUTPUT_BYTES:
                raise ValueError(f"execution {name} exceeds the bounded output limit")
        if self.error is not None and len(self.error.encode("utf-8")) > MAX_EXECUTION_ERROR_BYTES:
            raise ValueError("execution error must be bounded text")
        if len(self.artifacts) > MAX_EXECUTION_ARTIFACTS:
            raise ValueError("execution has too many artifacts")
        if len(set(self.artifacts)) != len(self.artifacts):
            raise ValueError("execution artifact paths must be unique")
        for relative in self.artifacts:
            _safe_relative_path(relative, "execution artifact path")

    @property
    def stdout_bytes(self) -> int:
        return len(self.stdout.encode("utf-8"))

    @property
    def stderr_bytes(self) -> int:
        return len(self.stderr.encode("utf-8"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "status": self.status,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "stdout_bytes": self.stdout_bytes,
            "stderr_bytes": self.stderr_bytes,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error": self.error,
            "artifacts": list(self.artifacts),
        }

    @classmethod
    def from_dict(cls, value: object) -> CandidateExecution:
        if not isinstance(value, dict):
            raise TypeError("candidate execution must be an object")
        artifacts = value.get("artifacts", [])
        if not isinstance(artifacts, list) or any(not isinstance(item, str) for item in artifacts):
            raise TypeError("execution artifacts must be a string array")
        return cls(
            status=value.get("status"),  # type: ignore[arg-type]
            exit_code=value.get("exit_code"),  # type: ignore[arg-type]
            duration_ms=value.get("duration_ms"),  # type: ignore[arg-type]
            stdout=value.get("stdout", ""),  # type: ignore[arg-type]
            stderr=value.get("stderr", ""),  # type: ignore[arg-type]
            error=value.get("error"),  # type: ignore[arg-type]
            artifacts=tuple(artifacts),
        )


class CandidateRunner(Protocol):
    """Execute a candidate in a bounded, run-scoped workspace."""

    def run(
        self, candidate_path: Path, workspace: Path, timeout: float | None = None
    ) -> CandidateExecution:
        ...


def _write_execution_evidence(workspace: Path, execution: CandidateExecution) -> Path:
    raw_workspace = Path(workspace).expanduser()
    if raw_workspace.is_symlink():
        raise EvolutionError("candidate execution workspace must not be a symlink")
    workspace = raw_workspace.resolve(strict=False)
    workspace.mkdir(parents=True, exist_ok=True)
    evidence = workspace / "execution.json"
    if evidence.exists() and evidence.is_symlink():
        raise EvolutionError("candidate execution evidence must not be a symlink")
    temporary = workspace / ".execution.json.tmp"
    if temporary.exists() and temporary.is_symlink():
        raise EvolutionError("candidate execution temporary evidence must not be a symlink")
    temporary.write_text(
        json.dumps(execution.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(evidence)
    return evidence


def _collect_declared_artifacts(workspace: Path) -> tuple[str, ...]:
    """Validate the optional execution-artifacts.json manifest emitted by a runner."""
    manifest = workspace / "execution-artifacts.json"
    if not manifest.exists():
        return ()
    if manifest.is_symlink():
        raise EvolutionError("candidate execution artifact manifest must not be a symlink")
    if manifest.stat().st_size > MAX_EXECUTION_OUTPUT_BYTES:
        raise EvolutionError("candidate execution artifact manifest exceeds the bounded size")
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvolutionError("candidate execution artifact manifest is invalid") from exc
    if not isinstance(payload, list) or len(payload) > MAX_EXECUTION_ARTIFACTS:
        raise EvolutionError("candidate execution artifact manifest must be a bounded array")
    output: list[str] = []
    for value in payload:
        relative = _safe_relative_path(value, "execution artifact path")
        if relative in output:
            raise EvolutionError("execution artifact paths must be unique")
        path = (workspace / relative).resolve(strict=False)
        _confined(workspace, path, "execution artifact path")
        if (workspace / relative).is_symlink() or not path.is_file():
            raise EvolutionError("execution artifact must be a regular file")
        output.append(relative)
    return tuple(output)


class CommandCandidateRunner:
    """Run a candidate through an explicit local command without a shell."""

    def __init__(
        self,
        command: Sequence[str],
        timeout_seconds: float = 900.0,
        max_output_bytes: int = MAX_EXECUTION_OUTPUT_BYTES,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        command = tuple(command)
        if not command or len(command) > MAX_COMMAND_ARGS:
            raise ValueError("candidate runner command must be a non-empty bounded argument sequence")
        executable = Path(command[0]).expanduser()
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError("candidate runner command must start with an existing absolute executable path")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or timeout_seconds <= 0
        ):
            raise ValueError("candidate runner timeout must be positive")
        if (
            isinstance(max_output_bytes, bool)
            or not isinstance(max_output_bytes, int)
            or not 1 <= max_output_bytes <= MAX_EXECUTION_OUTPUT_BYTES
        ):
            raise ValueError("candidate runner output limit is invalid")
        self.command = command
        self.timeout_seconds = float(timeout_seconds)
        self.max_output_bytes = max_output_bytes
        if environment is None:
            self.environment = None
        else:
            if len(environment) > 64:
                raise ValueError("candidate runner environment has too many entries")
            normalized_environment: dict[str, str] = {}
            for key, value in environment.items():
                if (
                    not isinstance(key, str)
                    or not key
                    or "=" in key
                    or "\x00" in key
                    or not isinstance(value, str)
                    or "\x00" in value
                ):
                    raise ValueError("candidate runner environment is invalid")
                if len(key.encode("utf-8")) > 128 or len(value.encode("utf-8")) > 4_096:
                    raise ValueError("candidate runner environment entry is too large")
                normalized_environment[key] = value
            self.environment = normalized_environment

    def run(
        self, candidate_path: Path, workspace: Path, timeout: float | None = None
    ) -> CandidateExecution:
        raw_workspace = Path(workspace).expanduser()
        if raw_workspace.is_symlink():
            raise EvolutionError("candidate runner workspace must not be a symlink")
        workspace = raw_workspace.resolve(strict=False)
        raw_candidate = Path(candidate_path).expanduser()
        if raw_candidate.is_symlink():
            raise EvolutionError("candidate runner path must not be a symlink")
        candidate = raw_candidate.resolve(strict=False)
        if not candidate.is_file():
            raise EvolutionError("candidate runner received a missing candidate path")
        _confined(workspace, candidate, "candidate runner path")
        effective_timeout = self.timeout_seconds if timeout is None else timeout
        if (
            isinstance(effective_timeout, bool)
            or not isinstance(effective_timeout, (int, float))
            or not math.isfinite(float(effective_timeout))
            or effective_timeout <= 0
        ):
            raise ValueError("candidate runner timeout must be positive")
        effective_timeout = max(float(effective_timeout), MIN_PROCESS_TIMEOUT_SECONDS)
        workspace.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        process: subprocess.Popen[str] | None = None
        stdout = ""
        stderr = ""
        error: str | None = None
        status: Literal["succeeded", "failed", "timed_out"] = "failed"
        exit_code: int | None = None
        try:
            process = subprocess.Popen(
                [*self.command, str(candidate)],
                cwd=workspace,
                env=self.environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=True,
            )
            stdout, stderr = process.communicate(timeout=float(effective_timeout))
            exit_code = process.returncode
            output_overflow = (
                len(str(stdout).encode("utf-8")) > self.max_output_bytes
                or len(str(stderr).encode("utf-8")) > self.max_output_bytes
            )
            stdout = _bounded_output(stdout, self.max_output_bytes).strip()
            stderr = _bounded_output(stderr, self.max_output_bytes).strip()
            if output_overflow:
                error = "output_limit_exceeded"
            elif exit_code == 0:
                status = "succeeded"
            else:
                error = "candidate_process_failed"
        except subprocess.TimeoutExpired as exc:
            if process is not None:
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except (AttributeError, OSError, ProcessLookupError):
                    process.kill()
                raw_stdout, raw_stderr = process.communicate()
                stdout = _bounded_output(raw_stdout, self.max_output_bytes).strip()
                stderr = _bounded_output(raw_stderr, self.max_output_bytes).strip()
            else:
                stdout = _bounded_output(exc.stdout, self.max_output_bytes).strip()
                stderr = _bounded_output(exc.stderr, self.max_output_bytes).strip()
            error = "candidate_process_timed_out"
            status = "timed_out"
        except OSError as exc:
            error = "runner_start_failed"
            stderr = _bounded_output(str(exc), self.max_output_bytes).strip()
        artifacts: tuple[str, ...] = ()
        try:
            artifacts = _collect_declared_artifacts(workspace)
        except EvolutionError as exc:
            status = "failed"
            error = "artifact_manifest_invalid"
            stderr = _bounded_output(str(exc), self.max_output_bytes).strip()
        duration_ms = min(86_400_000, max(0, round((time.monotonic() - started) * 1000)))
        execution = CandidateExecution(
            status=status,
            exit_code=exit_code,
            duration_ms=duration_ms,
            stdout=stdout,
            stderr=stderr,
            error=error,
            artifacts=artifacts,
        )
        _write_execution_evidence(workspace, execution)
        return execution


class ContractCandidateRunner:
    """Run Python candidates against copied inputs and an immutable output contract."""

    def __init__(
        self,
        source_workspace: Path,
        inputs: Sequence[CandidateInputArtifact],
        outputs: Sequence[OutputSpec],
        timeout_seconds: float = 900.0,
    ) -> None:
        raw_source = Path(source_workspace).expanduser()
        if raw_source.is_symlink():
            raise EvolutionError("candidate input source workspace must not be a symlink")
        normalized_inputs = tuple(inputs)
        normalized_outputs = tuple(outputs)
        if len(normalized_inputs) > MAX_INPUT_FILES:
            raise ValueError("candidate input list exceeds the bounded file limit")
        if any(not isinstance(item, CandidateInputArtifact) for item in normalized_inputs):
            raise TypeError("inputs must contain CandidateInputArtifact records")
        if len({item.path for item in normalized_inputs}) != len(normalized_inputs):
            raise ValueError("candidate input paths must be unique")
        if len(normalized_outputs) > MAX_EXECUTION_ARTIFACTS:
            raise ValueError("candidate output list exceeds the bounded file limit")
        if any(not isinstance(item, OutputSpec) for item in normalized_outputs):
            raise TypeError("outputs must contain OutputSpec records")
        if len({item.path for item in normalized_outputs}) != len(normalized_outputs):
            raise ValueError("candidate output paths must be unique")
        self.source_workspace = raw_source.resolve(strict=False)
        self.inputs = normalized_inputs
        self.outputs = normalized_outputs
        self.timeout_seconds = timeout_seconds
        self.process_runner = CommandCandidateRunner(
            (sys.executable, "-I"),
            timeout_seconds=timeout_seconds,
            environment={
                "PYTHONHASHSEED": "0",
                "PYTHONIOENCODING": "utf-8",
            },
        )

    def stage_inputs(self, destination_workspace: Path) -> tuple[str, ...]:
        """Expose the same verified copy boundary to Agent generation workspaces."""
        return stage_candidate_inputs(
            self.source_workspace,
            destination_workspace,
            self.inputs,
        )

    def run(
        self, candidate_path: Path, workspace: Path, timeout: float | None = None
    ) -> CandidateExecution:
        raw_candidate = Path(candidate_path).expanduser()
        if raw_candidate.suffix.lower() != ".py":
            raise EvolutionError("contract candidate runner requires a .py candidate")
        self.stage_inputs(workspace)
        execution = self.process_runner.run(raw_candidate, workspace, timeout)
        if execution.status != "succeeded":
            normalized = CandidateExecution(
                status=execution.status,
                exit_code=execution.exit_code,
                duration_ms=execution.duration_ms,
                stdout=execution.stdout,
                stderr=execution.stderr,
                error=execution.error,
                artifacts=(),
            )
            _write_execution_evidence(workspace, normalized)
            return normalized

        validation = evaluate_output_contract(self.outputs, Path(workspace))
        if not validation.passed:
            stderr = "\n".join(
                value for value in (execution.stderr, validation.reason) if value
            )
            failed = CandidateExecution(
                status="failed",
                exit_code=execution.exit_code,
                duration_ms=execution.duration_ms,
                stdout=execution.stdout,
                stderr=_bounded_output(stderr, MAX_EXECUTION_OUTPUT_BYTES),
                error="output_contract_invalid",
                artifacts=(),
            )
            _write_execution_evidence(workspace, failed)
            return failed

        artifacts = tuple(
            output.path
            for output in self.outputs
            if (Path(workspace) / output.path).is_file()
            and not (Path(workspace) / output.path).is_symlink()
        )
        succeeded = CandidateExecution(
            status="succeeded",
            exit_code=execution.exit_code,
            duration_ms=execution.duration_ms,
            stdout=execution.stdout,
            stderr=execution.stderr,
            artifacts=artifacts,
        )
        _write_execution_evidence(workspace, succeeded)
        return succeeded


@dataclass(frozen=True)
class EvolutionConfig:
    """Explicit, bounded knobs shared by all strategies."""

    strategy: Literal["population", "openevolve"] = "population"
    max_rounds: int = 5
    stagnation_rounds: int = 3
    population_size: int = 8
    offspring_per_iteration: int = 1
    num_islands: int = 1
    migration_interval: int = 0
    migration_rate: float = 0.1
    rng_seed: int | None = None
    timeout_seconds: float = 900.0
    command: tuple[str, ...] = ()
    generator_fingerprint: str | None = None
    evaluator_fingerprint: str | None = None
    runner_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if self.strategy == "loop":
            raise ValueError("loop_strategy_retired: use population or explicit openevolve; legacy loop runs are read-only")
        if self.strategy not in {"population", "openevolve"}:
            raise ValueError("strategy must be population or openevolve")
        for name, value, maximum in (
            ("max_rounds", self.max_rounds, 10_000),
            ("stagnation_rounds", self.stagnation_rounds, 1_000),
            ("population_size", self.population_size, 10_000),
            ("offspring_per_iteration", self.offspring_per_iteration, 256),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
                raise ValueError(f"{name} must be a positive bounded integer")
        if isinstance(self.num_islands, bool) or not isinstance(self.num_islands, int):
            raise TypeError("num_islands must be a positive bounded integer")
        if not 1 <= self.num_islands <= 64 or self.num_islands > self.population_size:
            raise ValueError("num_islands must be between 1 and population_size")
        if isinstance(self.migration_interval, bool) or not isinstance(self.migration_interval, int):
            raise TypeError("migration_interval must be a non-negative integer")
        if not 0 <= self.migration_interval <= 10_000:
            raise ValueError("migration_interval must be a non-negative bounded integer")
        if isinstance(self.migration_rate, bool) or not isinstance(self.migration_rate, (int, float)):
            raise TypeError("migration_rate must be a number between 0 and 1")
        if not math.isfinite(float(self.migration_rate)) or not 0 <= self.migration_rate <= 1:
            raise ValueError("migration_rate must be a number between 0 and 1")
        if self.rng_seed is not None and (isinstance(self.rng_seed, bool) or not isinstance(self.rng_seed, int)):
            raise ValueError("rng_seed must be an integer or null")
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)):
            raise TypeError("timeout_seconds must be positive")
        if not math.isfinite(float(self.timeout_seconds)) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if not isinstance(self.command, tuple) or len(self.command) > MAX_COMMAND_ARGS:
            raise ValueError("command must be a bounded argument tuple")
        if any(not isinstance(arg, str) or not arg for arg in self.command):
            raise ValueError("command arguments must be non-empty strings")
        for name, fingerprint in (
            ("generator_fingerprint", self.generator_fingerprint),
            ("evaluator_fingerprint", self.evaluator_fingerprint),
            ("runner_fingerprint", self.runner_fingerprint),
        ):
            if fingerprint is not None and (
                not isinstance(fingerprint, str) or not _SHA256.fullmatch(fingerprint)
            ):
                raise ValueError(f"{name} must be a lowercase SHA-256 hex digest or null")
        if self.strategy == "openevolve":
            if not self.command:
                raise ValueError("openevolve strategy requires an explicit command")
            if self.evaluator_fingerprint is None:
                raise ValueError("openevolve strategy requires a pinned local evaluator fingerprint")

    def to_dict(self) -> dict[str, Any]:
        """Return a credential-safe configuration snapshot for resume validation."""
        command_digest = None
        if self.command:
            command_digest = hashlib.sha256(
                json.dumps(list(self.command), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
        payload = {
            "strategy": self.strategy,
            "max_rounds": self.max_rounds,
            "stagnation_rounds": self.stagnation_rounds,
            "population_size": self.population_size,
            "offspring_per_iteration": self.offspring_per_iteration,
            "num_islands": self.num_islands,
            "migration_interval": self.migration_interval,
            "migration_rate": self.migration_rate,
            "rng_seed": self.rng_seed,
            "timeout_seconds": self.timeout_seconds,
            "command_sha256": command_digest,
        }
        if self.generator_fingerprint is not None:
            payload["generator_fingerprint"] = self.generator_fingerprint
        if self.evaluator_fingerprint is not None:
            payload["evaluator_fingerprint"] = self.evaluator_fingerprint
        if self.runner_fingerprint is not None:
            payload["runner_fingerprint"] = self.runner_fingerprint
        return payload


@dataclass(frozen=True)
class PopulationConfig:
    """Bounded native population settings."""

    population_size: int = 8
    offspring_per_iteration: int = 1
    num_islands: int = 1
    migration_interval: int = 0
    migration_rate: float = 0.1
    rng_seed: int | None = None

    def __post_init__(self) -> None:
        # Reuse the canonical bounds and type checks without duplicating policy in two models.
        EvolutionConfig(
            strategy="population",
            population_size=self.population_size,
            offspring_per_iteration=self.offspring_per_iteration,
            num_islands=self.num_islands,
            migration_interval=self.migration_interval,
            migration_rate=self.migration_rate,
            rng_seed=self.rng_seed,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "population_size": self.population_size,
            "offspring_per_iteration": self.offspring_per_iteration,
            "num_islands": self.num_islands,
            "migration_interval": self.migration_interval,
            "migration_rate": self.migration_rate,
            "rng_seed": self.rng_seed,
        }


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    code_path: str
    parent_id: str | None
    generation: int
    iteration: int
    strategy: Literal["loop", "population", "openevolve"]
    island_id: int | None
    evaluation: EvaluationReport
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        _safe_id(self.candidate_id, "candidate_id")
        _safe_relative_path(self.code_path, "candidate code path")
        if self.parent_id is not None:
            _safe_id(self.parent_id, "parent_id")
        if isinstance(self.generation, bool) or not isinstance(self.generation, int) or self.generation < 0:
            raise ValueError("generation must be a non-negative integer")
        if isinstance(self.iteration, bool) or not isinstance(self.iteration, int) or self.iteration < 0:
            raise ValueError("iteration must be a non-negative integer")
        if self.strategy not in EVOLUTION_STRATEGIES:
            raise ValueError("candidate strategy is unsupported")
        if self.island_id is not None and (isinstance(self.island_id, bool) or not isinstance(self.island_id, int) or self.island_id < 0):
            raise ValueError("island_id must be a non-negative integer or null")
        encoded = json.dumps(self.metadata, ensure_ascii=False, sort_keys=True).encode("utf-8")
        if len(encoded) > MAX_METADATA_BYTES:
            raise ValueError("candidate metadata exceeds the bounded metadata limit")

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "code_path": self.code_path,
            "parent_id": self.parent_id,
            "generation": self.generation,
            "iteration": self.iteration,
            "strategy": self.strategy,
            "island_id": self.island_id,
            "evaluation": self.evaluation.to_dict(),
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: object) -> Candidate:
        if not isinstance(value, dict):
            raise EvolutionError("candidate record must be an object")
        return cls(
            candidate_id=value.get("candidate_id"),  # type: ignore[arg-type]
            code_path=value.get("code_path"),  # type: ignore[arg-type]
            parent_id=value.get("parent_id"),  # type: ignore[arg-type]
            generation=value.get("generation"),  # type: ignore[arg-type]
            iteration=value.get("iteration"),  # type: ignore[arg-type]
            strategy=value.get("strategy"),  # type: ignore[arg-type]
            island_id=value.get("island_id"),  # type: ignore[arg-type]
            evaluation=EvaluationReport.from_dict(value.get("evaluation")),
            metadata=value.get("metadata", {}),  # type: ignore[arg-type]
            created_at=value.get("created_at", time.time()),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class StrategyResult:
    strategy: str
    status: Literal["running", "completed", "stagnated", "cancelled", "failed"]
    iterations: int
    evaluated_candidates: int
    valid_candidates: int
    best_candidate_id: str | None
    best_score: float | None
    archive_path: str
    error: str | None = None
    best_candidate_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "status": self.status,
            "iterations": self.iterations,
            "evaluated_candidates": self.evaluated_candidates,
            "valid_candidates": self.valid_candidates,
            "best_candidate_id": self.best_candidate_id,
            "best_score": self.best_score,
            "best_candidate_path": self.best_candidate_path,
            "archive_path": self.archive_path,
            "error": _bounded_error(self.error) if self.error else None,
        }


@dataclass(frozen=True)
class PopulationState:
    """JSON-safe view of the mutable active population persisted by ``PopulationStrategy``."""

    iteration: int
    population_size: int
    offspring_per_iteration: int
    num_islands: int
    active_ids: dict[str, tuple[str, ...]]
    best_candidate_id: str | None = None
    rng_seed: int | None = None
    last_migration_iteration: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.iteration, bool) or not isinstance(self.iteration, int) or self.iteration < 0:
            raise ValueError("population iteration must be a non-negative integer")
        config = PopulationConfig(
            population_size=self.population_size,
            offspring_per_iteration=self.offspring_per_iteration,
            num_islands=self.num_islands,
            rng_seed=self.rng_seed,
        )
        del config
        if self.best_candidate_id is not None:
            _safe_id(self.best_candidate_id, "best_candidate_id")
        if isinstance(self.last_migration_iteration, bool) or not isinstance(self.last_migration_iteration, int) or self.last_migration_iteration < 0:
            raise ValueError("last_migration_iteration must be a non-negative integer")
        expected = {str(index) for index in range(self.num_islands)}
        if set(self.active_ids) != expected:
            raise ValueError("active_ids must contain one entry for every island")
        if sum(len(ids) for ids in self.active_ids.values()) > self.population_size:
            raise ValueError("active population exceeds population_size")
        all_ids = [candidate_id for ids in self.active_ids.values() for candidate_id in ids]
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("active candidate IDs must be unique")
        for ids in self.active_ids.values():
            for candidate_id in ids:
                _safe_id(candidate_id, "active candidate id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "population_size": self.population_size,
            "offspring_per_iteration": self.offspring_per_iteration,
            "num_islands": self.num_islands,
            "active_ids": {key: list(value) for key, value in self.active_ids.items()},
            "best_candidate_id": self.best_candidate_id,
            "rng_seed": self.rng_seed,
            "last_migration_iteration": self.last_migration_iteration,
        }


@dataclass(frozen=True)
class OffspringOutcome:
    """One durable, prose-free terminal result for a configured offspring attempt."""

    iteration: int
    attempt: int
    island_id: int
    code: Literal[
        "evaluated",
        "candidate_failed",
        "evaluator_timeout",
        "worker_unknown",
        "run_failed",
    ]
    candidate_id: str | None = None
    schema_version: str = "1"

    def __post_init__(self) -> None:
        if self.schema_version != "1":
            raise ValueError("offspring outcome schema is unsupported")
        if (
            isinstance(self.iteration, bool)
            or not isinstance(self.iteration, int)
            or self.iteration < 1
        ):
            raise ValueError("offspring outcome iteration is invalid")
        if (
            isinstance(self.attempt, bool)
            or not isinstance(self.attempt, int)
            or not 0 <= self.attempt < 256
        ):
            raise ValueError("offspring outcome attempt is invalid")
        if (
            isinstance(self.island_id, bool)
            or not isinstance(self.island_id, int)
            or not 0 <= self.island_id < 64
        ):
            raise ValueError("offspring outcome island is invalid")
        if self.code not in _OFFSPRING_OUTCOME_CODES:
            raise ValueError("offspring outcome code is invalid")
        if self.code == "evaluated":
            _safe_id(self.candidate_id, "offspring outcome candidate_id")
        elif self.candidate_id is not None:
            raise ValueError("failed offspring outcome must not claim a candidate")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "iteration": self.iteration,
            "attempt": self.attempt,
            "island_id": self.island_id,
            "code": self.code,
            "candidate_id": self.candidate_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> OffspringOutcome:
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "iteration",
            "attempt",
            "island_id",
            "code",
            "candidate_id",
        }:
            raise ValueError("offspring outcome record is invalid")
        return cls(
            schema_version=value["schema_version"],  # type: ignore[arg-type]
            iteration=value["iteration"],  # type: ignore[arg-type]
            attempt=value["attempt"],  # type: ignore[arg-type]
            island_id=value["island_id"],  # type: ignore[arg-type]
            code=value["code"],  # type: ignore[arg-type]
            candidate_id=value["candidate_id"],  # type: ignore[arg-type]
        )


class EvolutionStrategy(Protocol):
    """Runtime-neutral strategy boundary shared by native and external implementations."""

    name: str

    def run(self) -> StrategyResult:
        ...

    def resume(self) -> StrategyResult:
        ...


@dataclass(frozen=True)
class GenerationRequest:
    iteration: int
    parent: Candidate | None
    inspirations: tuple[Candidate, ...]
    archive: tuple[Candidate, ...]
    workspace: Path


class CandidateGenerator(Protocol):
    def __call__(self, request: GenerationRequest) -> CandidateDraft | Sequence[CandidateDraft]:
        """Return one or more candidate drafts for an isolated generation context."""


class CandidateEvaluator(Protocol):
    def __call__(self, candidate_path: Path, contract: AlgorithmProblemContract) -> EvaluationReport | dict[str, Any]:
        """Evaluate a candidate and return the validity-first report."""


class SeedEvidenceRecord(Protocol):
    """JSON projection supplied by the verified seed admission boundary."""

    def to_dict(self) -> dict[str, Any]:
        ...


class AdmittedSeedInput(Protocol):
    """Structural input accepted from ``seed_handoff.AdmittedSeed`` without importing it."""

    candidate_id: str
    draft: CandidateDraft
    evaluation: EvaluationReport
    receipt: SeedEvidenceRecord
    provenance: SeedEvidenceRecord
    handoff_sha256: str
    generation: int
    iteration: int
    parent_id: None
    strategy: Literal["population"]
    island_id: int


class CommandCandidateGenerator:
    """Adapt an explicit local command that emits a draft as JSON or plain source text."""

    def __init__(self, command: Sequence[str], timeout_seconds: float = 900.0) -> None:
        command = tuple(command)
        if not command or len(command) > MAX_COMMAND_ARGS:
            raise ValueError("generator command must be a non-empty bounded argument sequence")
        executable = Path(command[0])
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError("generator command must start with an existing absolute executable path")
        self.command = command
        self.timeout_seconds = timeout_seconds

    def __call__(self, request: GenerationRequest) -> CandidateDraft | Sequence[CandidateDraft]:
        request_dir = request.workspace / "evolution" / "external" / "generator"
        request_dir.mkdir(parents=True, exist_ok=True)
        request_path = request_dir / f"request-{request.iteration:04d}.json"
        payload = {
            "iteration": request.iteration,
            "parent": request.parent.to_dict() if request.parent else None,
            "inspirations": [item.to_dict() for item in request.inspirations],
            "archive": [item.to_dict() for item in request.archive[-32:]],
            "workspace": str(request.workspace),
        }
        request_path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        try:
            completed = subprocess.run(
                [*self.command, str(request_path)],
                cwd=request.workspace,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise EvolutionError(f"candidate generator timed out after {self.timeout_seconds:g}s") from exc
        except OSError as exc:
            raise EvolutionError(_bounded_error(exc)) from exc
        if completed.returncode != 0:
            raise EvolutionError(_bounded_error(completed.stderr or completed.stdout or f"generator exited with {completed.returncode}"))
        output = completed.stdout.strip()
        if not output:
            raise EvolutionError("candidate generator returned empty output")
        try:
            decoded = json.loads(output)
        except json.JSONDecodeError:
            return CandidateDraft(output)
        if isinstance(decoded, dict) and "source" in decoded:
            return CandidateDraft(decoded["source"], decoded.get("filename", "candidate.py"), decoded.get("metadata", {}))
        if isinstance(decoded, list):
            return tuple(
                CandidateDraft(item["source"], item.get("filename", "candidate.py"), item.get("metadata", {}))
                for item in decoded
                if isinstance(item, dict) and "source" in item
            )
        raise EvolutionError("candidate generator JSON must contain source or a source array")


class CommandCandidateEvaluator:
    """Adapt an explicit local command that emits an EvaluationReport JSON object."""

    def __init__(
        self,
        command: Sequence[str],
        timeout_seconds: float = 900.0,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        command = tuple(command)
        if not command or len(command) > MAX_COMMAND_ARGS:
            raise ValueError("evaluator command must be a non-empty bounded argument sequence")
        executable = Path(command[0])
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError("evaluator command must start with an existing absolute executable path")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or timeout_seconds <= 0
        ):
            raise ValueError("candidate evaluator timeout must be positive")
        self.command = command
        self.timeout_seconds = float(timeout_seconds)
        if environment is None:
            self.environment = None
        else:
            if len(environment) > 64:
                raise ValueError("candidate evaluator environment has too many entries")
            normalized_environment: dict[str, str] = {}
            for key, value in environment.items():
                if (
                    not isinstance(key, str)
                    or not key
                    or "=" in key
                    or "\x00" in key
                    or not isinstance(value, str)
                    or "\x00" in value
                ):
                    raise ValueError("candidate evaluator environment is invalid")
                if len(key.encode("utf-8")) > 128 or len(value.encode("utf-8")) > 4_096:
                    raise ValueError("candidate evaluator environment entry is too large")
                normalized_environment[key] = value
            self.environment = normalized_environment

    def __call__(self, candidate_path: Path, contract: AlgorithmProblemContract) -> EvaluationReport:
        del contract
        try:
            completed = subprocess.run(
                [*self.command, str(candidate_path)],
                cwd=candidate_path.parent,
                env=self.environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise EvolutionError(f"candidate evaluator timed out after {self.timeout_seconds:g}s") from exc
        except OSError as exc:
            raise EvolutionError(_bounded_error(exc)) from exc
        if completed.returncode != 0:
            raise EvolutionError(_bounded_error(completed.stderr or completed.stdout or f"evaluator exited with {completed.returncode}"))
        if len(completed.stdout.encode("utf-8")) > MAX_EXTERNAL_RESULT_BYTES:
            raise EvolutionError("candidate evaluator output exceeds the bounded result size")
        try:
            return _report(json.loads(completed.stdout))
        except (json.JSONDecodeError, TypeError, ValueError, EvolutionError) as exc:
            raise EvolutionError("candidate evaluator did not return a valid evaluation report") from exc


@dataclass(frozen=True)
class EvolutionContext:
    contract: AlgorithmProblemContract
    workspace: Path
    generate: CandidateGenerator
    evaluate: CandidateEvaluator
    config: EvolutionConfig = field(default_factory=EvolutionConfig)
    cancelled: Callable[[], bool] = lambda: False
    # Optional audit hook used by the SQLite controller.  The strategy remains runtime-neutral;
    # callers that do not need a ledger can leave this unset.
    observe: Callable[[str, dict[str, Any]], None] = lambda event, payload: None
    initial_seeds: Sequence[AdmittedSeedInput] = ()

    def __post_init__(self) -> None:
        try:
            seeds = tuple(self.initial_seeds)
        except TypeError as exc:
            raise TypeError("initial_seeds must be a bounded sequence") from exc
        if len(seeds) > 32:
            raise ValueError("initial_seeds exceeds the bounded seed limit")
        object.__setattr__(self, "initial_seeds", seeds)


_SEED_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "candidate_id",
        "source_sha256",
        "contract_sha256",
        "evaluator_kind",
        "evaluator_fingerprint",
        "dependency_sha256",
        "environment_sha256",
        "report_schema_version",
        "evaluator_id",
        "validity",
        "quality",
        "combined_score",
        "detailed_scores",
        "error_info",
        "receipt_sha256",
    }
)
_SEED_PROVENANCE_FIELDS = frozenset(
    {
        "origin_kind",
        "producer_id",
        "producer_fingerprint",
        "producer_run_id",
        "material_refs",
        "external_evidence",
    }
)
_SEED_METADATA_FIELDS = frozenset(
    {
        "schema_version",
        "candidate_id",
        "source_sha256",
        "contract_sha256",
        "evaluator_kind",
        "evaluator_fingerprint",
        "dependency_sha256",
        "environment_sha256",
        "lineage",
        "provenance",
        "provenance_sha256",
        "handoff_sha256",
        "receipt_sha256",
    }
)


def _canonical_seed_bytes(value: object) -> bytes:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return encoded.encode("utf-8")


def _canonical_seed_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_seed_bytes(value)).hexdigest()


def _seed_evidence_mapping(
    value: SeedEvidenceRecord,
    *,
    fields: frozenset[str],
) -> dict[str, Any]:
    payload = value.to_dict()
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ValueError("seed evidence schema mismatch")
    encoded = _canonical_seed_bytes(payload)
    if len(encoded) > MAX_ARCHIVE_LINE_BYTES:
        raise ValueError("seed evidence exceeds the bounded record size")
    return json.loads(encoded.decode("utf-8"))


@dataclass(frozen=True)
class _PreparedInitialSeed:
    candidate: Candidate
    source: str
    filename: str
    receipt: dict[str, Any]
    provenance: dict[str, Any]
    handoff_sha256: str

    @property
    def candidate_dir(self) -> str:
        return f"candidates/{self.candidate.candidate_id}"


def _prepare_initial_seed(
    value: AdmittedSeedInput,
    *,
    canonical_strategy: Literal["population", "openevolve"] = "population",
) -> _PreparedInitialSeed:
    if canonical_strategy not in {"population", "openevolve"}:
        raise ValueError("verified seed canonical strategy is invalid")
    candidate_id = _safe_id(value.candidate_id, "verified seed candidate_id")
    if not isinstance(value.draft, CandidateDraft):
        raise TypeError("verified seed draft is invalid")
    if not isinstance(value.evaluation, EvaluationReport):
        raise TypeError("verified seed evaluation is invalid")
    if value.evaluation.validity != 1 or not math.isfinite(
        float(value.evaluation.combined_score)
    ):
        raise ValueError("verified seed must have a usable local evaluation")
    if value.evaluation.error_info:
        raise ValueError("verified seed evaluation must not persist evaluator error prose")
    if (
        value.generation != 0
        or value.iteration != 0
        or value.parent_id is not None
        or value.strategy != "population"
        or isinstance(value.island_id, bool)
        or not isinstance(value.island_id, int)
        or value.island_id < 0
    ):
        raise ValueError("verified seed population fields are invalid")

    filename = _safe_relative_path(value.draft.filename, "verified seed filename")
    if Path(filename).name in {"record.json", "receipt.json"}:
        raise ValueError("verified seed filename is reserved")
    source = value.draft.source
    source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
    receipt = _seed_evidence_mapping(value.receipt, fields=_SEED_RECEIPT_FIELDS)
    provenance = _seed_evidence_mapping(value.provenance, fields=_SEED_PROVENANCE_FIELDS)

    if receipt["schema_version"] != "1" or receipt["candidate_id"] != candidate_id:
        raise ValueError("verified seed receipt identity mismatch")
    for field_name in (
        "source_sha256",
        "contract_sha256",
        "evaluator_fingerprint",
        "dependency_sha256",
        "environment_sha256",
        "receipt_sha256",
    ):
        if not isinstance(receipt[field_name], str) or not _SHA256.fullmatch(
            receipt[field_name]
        ):
            raise ValueError("verified seed receipt digest is invalid")
    if receipt["source_sha256"] != source_sha256:
        raise ValueError("verified seed source digest mismatch")
    receipt_payload = {
        key: item for key, item in receipt.items() if key != "receipt_sha256"
    }
    if receipt["receipt_sha256"] != _canonical_seed_sha256(receipt_payload):
        raise ValueError("verified seed receipt digest mismatch")
    if (
        receipt["validity"] != 1
        or isinstance(receipt["combined_score"], bool)
        or not isinstance(receipt["combined_score"], (int, float))
        or not math.isfinite(float(receipt["combined_score"]))
        or float(receipt["combined_score"]) < 0
    ):
        raise ValueError("verified seed receipt score is invalid")
    if (
        receipt["report_schema_version"] != value.evaluation.schema_version
        or receipt["evaluator_id"] != value.evaluation.evaluator_id
        or receipt["validity"] != value.evaluation.validity
        or receipt["quality"] != value.evaluation.quality
        or receipt["combined_score"] != value.evaluation.combined_score
        or receipt["detailed_scores"] != value.evaluation.detailed_scores
        or [item.get("code") for item in receipt["error_info"]]
        != [item.get("code") for item in value.evaluation.error_info]
    ):
        raise ValueError("verified seed receipt does not describe its local evaluation")
    if receipt["error_info"]:
        raise ValueError("verified seed receipt must not contain evaluator error prose")

    if provenance["origin_kind"] not in {"local", "external"}:
        raise ValueError("verified seed provenance origin is invalid")
    _safe_id(provenance["producer_id"], "verified seed producer_id")
    producer_run_id = provenance["producer_run_id"]
    if producer_run_id is not None:
        _safe_id(producer_run_id, "verified seed producer_run_id")
    if not isinstance(provenance["producer_fingerprint"], str) or not _SHA256.fullmatch(
        provenance["producer_fingerprint"]
    ):
        raise ValueError("verified seed producer fingerprint is invalid")
    if provenance["origin_kind"] == "external" and receipt["evaluator_kind"] != "exact_harness":
        raise ValueError("external verified seed requires the exact harness")
    provenance_sha256 = _canonical_seed_sha256(provenance)

    metadata = value.draft.metadata
    if not isinstance(metadata, dict):
        raise TypeError("verified seed metadata is invalid")
    handoff = metadata.get("seed_handoff")
    if not isinstance(handoff, dict) or set(handoff) != _SEED_METADATA_FIELDS:
        raise ValueError("verified seed metadata schema mismatch")
    if (
        handoff["schema_version"] != "1"
        or handoff["candidate_id"] != candidate_id
        or handoff["source_sha256"] != source_sha256
        or handoff["contract_sha256"] != receipt["contract_sha256"]
        or handoff["evaluator_kind"] != receipt["evaluator_kind"]
        or handoff["evaluator_fingerprint"] != receipt["evaluator_fingerprint"]
        or handoff["dependency_sha256"] != receipt["dependency_sha256"]
        or handoff["environment_sha256"] != receipt["environment_sha256"]
        or handoff["provenance_sha256"] != provenance_sha256
        or handoff["receipt_sha256"] != receipt["receipt_sha256"]
    ):
        raise ValueError("verified seed metadata identity mismatch")
    lineage = handoff["lineage"]
    if not isinstance(lineage, list) or any(not isinstance(item, str) for item in lineage):
        raise ValueError("verified seed lineage is invalid")
    identity_payload = {
        "schema_version": "1",
        "source_sha256": source_sha256,
        "contract_sha256": receipt["contract_sha256"],
        "evaluator_kind": receipt["evaluator_kind"],
        "evaluator_fingerprint": receipt["evaluator_fingerprint"],
        "dependency_sha256": receipt["dependency_sha256"],
        "environment_sha256": receipt["environment_sha256"],
        "lineage": lineage,
    }
    if candidate_id != f"seed-{_canonical_seed_sha256(identity_payload)}":
        raise ValueError("verified seed derived identity mismatch")
    projection = {
        "origin_kind": provenance["origin_kind"],
        "producer_id": provenance["producer_id"],
        "producer_fingerprint": provenance["producer_fingerprint"],
        "producer_run_id": provenance["producer_run_id"],
        "material_refs_sha256": _canonical_seed_sha256(provenance["material_refs"]),
        "external_evidence_sha256": _canonical_seed_sha256(
            provenance["external_evidence"]
        ),
    }
    if handoff["provenance"] != projection:
        raise ValueError("verified seed provenance projection mismatch")
    expected_handoff = _canonical_seed_sha256(
        {
            "schema_version": "1",
            "candidate_id": candidate_id,
            "provenance": provenance,
        }
    )
    if (
        not isinstance(value.handoff_sha256, str)
        or not _SHA256.fullmatch(value.handoff_sha256)
        or value.handoff_sha256 != expected_handoff
        or handoff["handoff_sha256"] != expected_handoff
    ):
        raise ValueError("verified seed handoff fingerprint mismatch")

    candidate = Candidate(
        candidate_id=candidate_id,
        code_path=(Path("evolution") / "candidates" / candidate_id / filename).as_posix(),
        parent_id=None,
        generation=0,
        iteration=0 if canonical_strategy == "population" else 1,
        strategy=canonical_strategy,
        island_id=value.island_id if canonical_strategy == "population" else None,
        evaluation=value.evaluation,
        metadata=metadata,
    )
    if len(_canonical_seed_bytes(candidate.to_dict())) > MAX_ARCHIVE_LINE_BYTES:
        raise ValueError("verified seed candidate record is too large")
    return _PreparedInitialSeed(
        candidate=candidate,
        source=source,
        filename=filename,
        receipt=receipt,
        provenance=provenance,
        handoff_sha256=expected_handoff,
    )


def _prepare_initial_seeds(
    values: Sequence[AdmittedSeedInput],
    *,
    canonical_strategy: Literal["population", "openevolve"] = "population",
) -> tuple[_PreparedInitialSeed, ...]:
    try:
        seeds = tuple(values)
        if not seeds or len(seeds) > 32:
            raise ValueError("verified seed batch size is invalid")
        prepared = tuple(
            _prepare_initial_seed(seed, canonical_strategy=canonical_strategy) for seed in seeds
        )
        candidate_ids = [item.candidate.candidate_id for item in prepared]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("verified seed candidate IDs must be unique")
        authority = {
            (
                item.receipt["contract_sha256"],
                item.receipt["evaluator_kind"],
                item.receipt["evaluator_fingerprint"],
                item.receipt["dependency_sha256"],
                item.receipt["environment_sha256"],
            )
            for item in prepared
        }
        if len(authority) != 1:
            raise ValueError("verified seed authority must be uniform")
        return prepared
    except Exception as exc:
        raise EvolutionError("verified_seed_invalid") from exc


def _seed_admission_summary(
    prepared: Sequence[_PreparedInitialSeed],
) -> dict[str, Any]:
    records = [
        {
            "candidate_id": item.candidate.candidate_id,
            "receipt_sha256": item.receipt["receipt_sha256"],
            "handoff_sha256": item.handoff_sha256,
            "provenance_sha256": _canonical_seed_sha256(item.provenance),
        }
        for item in sorted(prepared, key=lambda item: item.candidate.candidate_id)
    ]
    payload = {
        "schema_version": "1",
        "seeds": records,
    }
    return {**payload, "admission_sha256": _canonical_seed_sha256(payload)}


class CandidateArchive:
    """Append-only candidate records and atomic strategy state for one run."""

    def __init__(self, workspace: str | Path) -> None:
        raw_workspace = Path(workspace).expanduser()
        if raw_workspace.is_symlink():
            raise EvolutionError("evolution workspace must not be a symlink")
        raw_workspace.mkdir(parents=True, exist_ok=True)
        self.workspace = raw_workspace.resolve()
        self.root = self.workspace / "evolution"
        self.candidates_root = self.root / "candidates"
        self.archive_path = self.root / "archive.jsonl"
        self.offspring_outcomes_path = self.root / "offspring-outcomes.jsonl"
        self.state_path = self.root / "state.json"
        self.seed_commit_path = self.root / "seed-commit.json"
        self.seed_stage_path = self.workspace / _SEED_STAGE_NAME
        self.seed_backup_path = self.workspace / _SEED_BACKUP_NAME
        self._recover_seed_publication()
        for path in (self.root, self.candidates_root):
            if path.is_symlink():
                raise EvolutionError("evolution archive directory must not be a symlink")

    @staticmethod
    def _path_present(path: Path) -> bool:
        return path.exists() or path.is_symlink()

    @staticmethod
    def _canonical_contract_snapshot(path: Path) -> tuple[bytes, str]:
        try:
            if path.is_symlink() or not path.is_file():
                raise EvolutionError("verified_seed_contract_invalid")
            if path.stat().st_size > MAX_SOURCE_BYTES:
                raise EvolutionError("verified_seed_contract_invalid")
            content = path.read_bytes()
            contract = AlgorithmProblemContract.from_dict(
                json.loads(content.decode("utf-8"))
            )
            canonical = (
                json.dumps(
                    contract.to_dict(),
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")
            if content != canonical:
                raise EvolutionError("verified_seed_contract_invalid")
            return content, contract.digest()
        except EvolutionError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise EvolutionError("verified_seed_contract_invalid") from exc

    @classmethod
    def _contract_only_snapshot(cls, root: Path) -> tuple[bytes, str]:
        try:
            if root.is_symlink() or not root.is_dir():
                raise EvolutionError("verified_seed_recovery_ambiguous")
            entries = tuple(root.iterdir())
            if len(entries) != 1 or entries[0].name != "contract.json":
                raise EvolutionError("verified_seed_recovery_ambiguous")
            return cls._canonical_contract_snapshot(entries[0])
        except EvolutionError:
            raise
        except OSError as exc:
            raise EvolutionError("verified_seed_recovery_ambiguous") from exc

    @staticmethod
    def _reject_seed_tree_links(root: Path) -> None:
        entries = 0
        for current, directories, files in os.walk(root, followlinks=False):
            for name in [*directories, *files]:
                entries += 1
                if entries > 512:
                    raise EvolutionError("verified_seed_recovery_ambiguous")
                path = Path(current) / name
                if path.is_symlink():
                    raise EvolutionError("verified_seed_recovery_ambiguous")
                if name in directories and not path.is_dir():
                    raise EvolutionError("verified_seed_recovery_ambiguous")
                if name in files and not path.is_file():
                    raise EvolutionError("verified_seed_recovery_ambiguous")

    @classmethod
    def _complete_seed_tree_contract(cls, root: Path) -> bytes | None:
        """Recognize only a complete, initial seed tree left by the publish transaction."""

        try:
            if root.is_symlink() or not root.is_dir():
                raise EvolutionError("verified_seed_recovery_ambiguous")
            cls._reject_seed_tree_links(root)
            entries = {path.name: path for path in root.iterdir()}
            required = {"candidates", "archive.jsonl", "state.json", "seed-commit.json"}
            allowed = required | {"contract.json"}
            names = set(entries)
            if names != required and names != allowed:
                raise EvolutionError("verified_seed_recovery_ambiguous")
            if not entries["candidates"].is_dir() or any(
                not entries[name].is_file()
                for name in ("archive.jsonl", "state.json", "seed-commit.json")
            ):
                raise EvolutionError("verified_seed_recovery_ambiguous")
            if (
                entries["state.json"].stat().st_size > MAX_STATE_BYTES
                or entries["seed-commit.json"].stat().st_size > MAX_ARCHIVE_LINE_BYTES
            ):
                raise EvolutionError("verified_seed_recovery_ambiguous")
            marker = json.loads(entries["seed-commit.json"].read_text(encoding="utf-8"))
            state = json.loads(entries["state.json"].read_text(encoding="utf-8"))
            if not isinstance(marker, dict) or set(marker) != {
                "schema_version",
                "admission_sha256",
                "candidate_ids",
                "seed_candidates_sha256",
                "commit_sha256",
            }:
                raise EvolutionError("verified_seed_recovery_ambiguous")
            marker_payload = {
                key: item for key, item in marker.items() if key != "commit_sha256"
            }
            candidate_ids = marker["candidate_ids"]
            if (
                marker["schema_version"] != "1"
                or not isinstance(candidate_ids, list)
                or not candidate_ids
                or len(candidate_ids) > 32
                or candidate_ids != sorted(candidate_ids)
                or len(candidate_ids) != len(set(candidate_ids))
                or any(not isinstance(item, str) or not _SAFE_ID.fullmatch(item) for item in candidate_ids)
                or marker["commit_sha256"] != _canonical_seed_sha256(marker_payload)
                or not isinstance(state, dict)
                or not isinstance(state.get("seed_admission"), dict)
                or state["seed_admission"].get("admission_sha256")
                != marker["admission_sha256"]
            ):
                raise EvolutionError("verified_seed_recovery_ambiguous")
            if entries["archive.jsonl"].stat().st_size > MAX_ARCHIVE_LINE_BYTES * 32:
                raise EvolutionError("verified_seed_recovery_ambiguous")
            archive_lines = [
                line
                for line in entries["archive.jsonl"].read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if any(
                len(line.encode("utf-8")) > MAX_ARCHIVE_LINE_BYTES
                for line in archive_lines
            ):
                raise EvolutionError("verified_seed_recovery_ambiguous")
            candidates = [Candidate.from_dict(json.loads(line)) for line in archive_lines]
            population_seed_tree = bool(candidates) and all(
                candidate.parent_id is None
                and candidate.generation == 0
                and candidate.iteration == 0
                and candidate.strategy == "population"
                and candidate.island_id is not None
                for candidate in candidates
            )
            openevolve_seed_tree = len(candidates) == 1 and all(
                candidate.parent_id is None
                and candidate.generation == 0
                and candidate.iteration == 1
                and candidate.strategy == "openevolve"
                and candidate.island_id is None
                for candidate in candidates
            )
            expected_strategy = "population" if population_seed_tree else "openevolve"
            expected_iteration = 0 if population_seed_tree else 1
            if (
                [candidate.candidate_id for candidate in candidates] != candidate_ids
                or not (population_seed_tree or openevolve_seed_tree)
                or state.get("strategy") != expected_strategy
                or state.get("iteration") != expected_iteration
                or marker["seed_candidates_sha256"]
                != _canonical_seed_sha256([candidate.to_dict() for candidate in candidates])
            ):
                raise EvolutionError("verified_seed_recovery_ambiguous")
            for candidate in candidates:
                relative = Path(candidate.code_path)
                if not relative.parts or relative.parts[0] != "evolution":
                    raise EvolutionError("verified_seed_recovery_ambiguous")
                source = root.joinpath(*relative.parts[1:])
                candidate_root = entries["candidates"] / candidate.candidate_id
                try:
                    source.relative_to(candidate_root)
                except ValueError as exc:
                    raise EvolutionError("verified_seed_recovery_ambiguous") from exc
                if (
                    not source.is_file()
                    or not (source.parent / "record.json").is_file()
                    or not (source.parent / "receipt.json").is_file()
                ):
                    raise EvolutionError("verified_seed_recovery_ambiguous")
            if "contract.json" not in entries:
                return None
            return cls._canonical_contract_snapshot(entries["contract.json"])[0]
        except EvolutionError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise EvolutionError("verified_seed_recovery_ambiguous") from exc

    @staticmethod
    def _remove_recovery_tree(path: Path) -> None:
        try:
            shutil.rmtree(path)
        except OSError as exc:
            raise EvolutionError("verified_seed_recovery_failed") from exc

    def _recover_seed_publication(self) -> None:
        reserved = [
            path
            for path in self.workspace.iterdir()
            if (
                path.name.startswith(".evolution-seed-stage-")
                or path.name.startswith(".evolution-seed-backup-")
            )
            and path not in {self.seed_stage_path, self.seed_backup_path}
        ]
        if reserved:
            raise EvolutionError("verified_seed_recovery_ambiguous")

        stage_present = self._path_present(self.seed_stage_path)
        backup_present = self._path_present(self.seed_backup_path)
        root_present = self._path_present(self.root)
        if not stage_present and not backup_present:
            return
        if self.root.is_symlink() or self.seed_stage_path.is_symlink() or self.seed_backup_path.is_symlink():
            raise EvolutionError("verified_seed_recovery_ambiguous")

        if backup_present:
            backup_contract, _ = self._contract_only_snapshot(self.seed_backup_path)
            if root_present:
                if stage_present:
                    raise EvolutionError("verified_seed_recovery_ambiguous")
                root_contract = self._complete_seed_tree_contract(self.root)
                if root_contract != backup_contract:
                    raise EvolutionError("verified_seed_recovery_ambiguous")
                self._remove_recovery_tree(self.seed_backup_path)
                return

            if stage_present:
                stage_contract = self._complete_seed_tree_contract(self.seed_stage_path)
                if stage_contract != backup_contract:
                    raise EvolutionError("verified_seed_recovery_ambiguous")
            try:
                os.replace(self.seed_backup_path, self.root)
            except OSError as exc:
                raise EvolutionError("verified_seed_recovery_failed") from exc
            if stage_present:
                self._remove_recovery_tree(self.seed_stage_path)
            return

        stage_contract = self._complete_seed_tree_contract(self.seed_stage_path)
        if root_present:
            root_contract, _ = self._contract_only_snapshot(self.root)
            if stage_contract != root_contract:
                raise EvolutionError("verified_seed_recovery_ambiguous")
        elif stage_contract is not None:
            raise EvolutionError("verified_seed_recovery_ambiguous")
        self._remove_recovery_tree(self.seed_stage_path)

    def _ensure_layout(self) -> None:
        for path in (self.root, self.candidates_root):
            if path.exists() and path.is_symlink():
                raise EvolutionError("evolution archive directory must not be a symlink")
            path.mkdir(parents=True, exist_ok=True)

    def records(self) -> list[Candidate]:
        if not self.archive_path.exists():
            return []
        if self.archive_path.is_symlink() or self.archive_path.stat().st_size > MAX_STATE_BYTES * 128:
            raise EvolutionError("evolution archive is invalid or exceeds the bounded size")
        records: list[Candidate] = []
        seen: set[str] = set()
        for line in self.archive_path.read_text(encoding="utf-8").splitlines():
            if len(line.encode("utf-8")) > MAX_ARCHIVE_LINE_BYTES:
                raise EvolutionError("evolution archive record is too large")
            if not line.strip():
                continue
            candidate = Candidate.from_dict(json.loads(line))
            if candidate.candidate_id in seen:
                raise EvolutionError("evolution archive contains a duplicate candidate id")
            seen.add(candidate.candidate_id)
            records.append(candidate)
        return records

    def offspring_outcomes(self) -> tuple[OffspringOutcome, ...]:
        path = self.offspring_outcomes_path
        if not path.exists():
            if path.is_symlink():
                raise EvolutionError("population_outcomes_invalid")
            return ()
        try:
            if path.is_symlink() or not path.is_file():
                raise EvolutionError("population_outcomes_invalid")
            if path.stat().st_size > MAX_STATE_BYTES * 128:
                raise EvolutionError("population_outcomes_invalid")
            outcomes: list[OffspringOutcome] = []
            seen: set[tuple[int, int]] = set()
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                if len(line.encode("utf-8")) > MAX_ARCHIVE_LINE_BYTES:
                    raise EvolutionError("population_outcomes_invalid")
                outcome = OffspringOutcome.from_dict(json.loads(line))
                key = (outcome.iteration, outcome.attempt)
                if key in seen:
                    raise EvolutionError("population_outcomes_invalid")
                seen.add(key)
                outcomes.append(outcome)
            return tuple(outcomes)
        except EvolutionError:
            raise
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise EvolutionError("population_outcomes_invalid") from exc

    def append_offspring_outcome(self, outcome: OffspringOutcome) -> None:
        if not isinstance(outcome, OffspringOutcome):
            raise TypeError("outcome must be an OffspringOutcome")
        self._ensure_layout()
        if any(
            item.iteration == outcome.iteration and item.attempt == outcome.attempt
            for item in self.offspring_outcomes()
        ):
            raise EvolutionError("population_outcome_duplicate")
        line = json.dumps(
            outcome.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if len(line.encode("utf-8")) > MAX_ARCHIVE_LINE_BYTES:
            raise EvolutionError("population_outcomes_invalid")
        if self.offspring_outcomes_path.is_symlink():
            raise EvolutionError("population_outcomes_invalid")
        try:
            with self.offspring_outcomes_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise EvolutionError("population_outcome_persist_failed") from exc

    def next_id(self) -> str:
        numbers = []
        for candidate in self.records():
            match = re.fullmatch(r"candidate-(\d+)", candidate.candidate_id)
            if match:
                numbers.append(int(match.group(1)))
        return f"candidate-{(max(numbers, default=0) + 1):04d}"

    def candidate_source_path(self, candidate_id: str, filename: str) -> Path:
        _safe_id(candidate_id, "candidate_id")
        relative = _safe_relative_path(filename, "candidate filename")
        if self.archive_path.exists() and self.archive_path.is_symlink():
            raise EvolutionError("evolution archive must not be a symlink")
        candidate_dir = self.candidates_root / candidate_id
        _reject_symlink_components(candidate_dir, self.candidates_root, "candidate path")
        result = _confined(self.workspace, candidate_dir / relative, "candidate path")
        _reject_symlink_components(result.parent, candidate_dir, "candidate path")
        record_path = result.parent / "record.json"
        if record_path.exists() and record_path.is_symlink():
            raise EvolutionError("candidate record must not be a symlink")
        return result

    def persist(
        self,
        draft: CandidateDraft,
        *,
        candidate_id: str | None = None,
        strategy: Literal["population", "openevolve"],
        iteration: int,
        generation: int,
        parent_id: str | None = None,
        island_id: int | None = None,
        evaluation: EvaluationReport,
    ) -> Candidate:
        self._ensure_layout()
        if strategy == "loop":
            raise EvolutionError("loop_strategy_retired: legacy loop archives are read-only")
        if strategy not in {"population", "openevolve"}:
            raise EvolutionError("unsupported candidate strategy")
        candidate_id = candidate_id or self.next_id()
        if any(item.candidate_id == candidate_id for item in self.records()):
            raise EvolutionError(f"candidate id already exists: {candidate_id}")
        path = self.candidate_source_path(candidate_id, draft.filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(draft.source, encoding="utf-8")
        candidate = Candidate(
            candidate_id=candidate_id,
            code_path=path.relative_to(self.workspace).as_posix(),
            parent_id=parent_id,
            generation=generation,
            iteration=iteration,
            strategy=strategy,
            island_id=island_id,
            evaluation=evaluation,
            metadata=draft.metadata,
        )
        line = json.dumps(candidate.to_dict(), ensure_ascii=False, sort_keys=True)
        if len(line.encode("utf-8")) > MAX_ARCHIVE_LINE_BYTES:
            raise EvolutionError("candidate record exceeds the bounded archive record size")
        record_path = path.parent / "record.json"
        if self.archive_path.exists() and self.archive_path.is_symlink():
            raise EvolutionError("evolution archive must not be a symlink")
        if record_path.exists() and record_path.is_symlink():
            raise EvolutionError("candidate record must not be a symlink")
        temporary_record = record_path.with_name(".record.json.tmp")
        temporary_record.write_text(line + "\n", encoding="utf-8")
        temporary_record.replace(record_path)
        with self.archive_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return candidate

    def _seed_authority(
        self,
        prepared: Sequence[_PreparedInitialSeed],
        *,
        contract_sha256: str,
        evaluator_fingerprint: str | None,
    ) -> None:
        if not isinstance(contract_sha256, str) or not _SHA256.fullmatch(contract_sha256):
            raise EvolutionError("verified_seed_context_invalid")
        if evaluator_fingerprint is None or not _SHA256.fullmatch(evaluator_fingerprint):
            raise EvolutionError("verified_seed_context_invalid")
        if any(
            item.receipt["contract_sha256"] != contract_sha256
            or item.receipt["evaluator_fingerprint"] != evaluator_fingerprint
            for item in prepared
        ):
            raise EvolutionError("verified_seed_context_mismatch")

    @staticmethod
    def _write_private_bytes(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        if temporary.exists() or temporary.is_symlink():
            raise EvolutionError("verified_seed_commit_failed")
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        try:
            view = memoryview(content)
            written = 0
            while written < len(view):
                written += os.write(descriptor, view[written:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)

    @classmethod
    def _write_private_text(cls, path: Path, content: str) -> None:
        cls._write_private_bytes(path, content.encode("utf-8"))

    def _seed_contract_for_commit(self, contract_sha256: str) -> bytes | None:
        if not self._path_present(self.root):
            return None
        if self.root.is_symlink() or not self.root.is_dir():
            raise EvolutionError("verified_seed_initialization_requires_empty_archive")
        try:
            entries = tuple(self.root.iterdir())
        except OSError as exc:
            raise EvolutionError("verified_seed_initialization_requires_empty_archive") from exc
        if len(entries) != 1 or entries[0].name != "contract.json":
            raise EvolutionError("verified_seed_initialization_requires_empty_archive")
        content, digest = self._canonical_contract_snapshot(entries[0])
        if digest != contract_sha256:
            raise EvolutionError("verified_seed_context_mismatch")
        return content

    def commit_initial_seeds(
        self,
        seeds: Sequence[AdmittedSeedInput],
        *,
        state: dict[str, Any],
        contract_sha256: str,
        evaluator_fingerprint: str | None,
        canonical_strategy: Literal["population", "openevolve"] = "population",
    ) -> tuple[Candidate, ...]:
        """Publish a fully adjudicated seed batch through a directory transaction.

        Every source, candidate record, receipt sidecar, archive line, state snapshot, and commit
        marker is built below a private sibling directory. If a controller has already written the
        canonical contract, its exact bytes are moved through a private backup and restored on a
        failed publication.
        """

        prepared = _prepare_initial_seeds(
            seeds,
            canonical_strategy=canonical_strategy,
        )
        self._seed_authority(
            prepared,
            contract_sha256=contract_sha256,
            evaluator_fingerprint=evaluator_fingerprint,
        )
        contract_content = self._seed_contract_for_commit(contract_sha256)
        if not isinstance(state, dict) or "seed_admission" in state:
            raise EvolutionError("verified_seed_state_invalid")
        candidate_ids = {item.candidate.candidate_id for item in prepared}
        if canonical_strategy == "population":
            active_ids = state.get("active_ids")
            if not isinstance(active_ids, dict):
                raise EvolutionError("verified_seed_state_invalid")
            active_flat = [
                candidate_id
                for values in active_ids.values()
                if isinstance(values, list)
                for candidate_id in values
            ]
            if (
                any(not isinstance(values, list) for values in active_ids.values())
                or len(active_flat) != len(set(active_flat))
                or set(active_flat) != candidate_ids
            ):
                raise EvolutionError("verified_seed_state_invalid")
        elif (
            canonical_strategy != "openevolve"
            or len(candidate_ids) != 1
            or state.get("strategy") != "openevolve"
            or state.get("status") != "completed"
            or state.get("iteration") != 1
            or state.get("best_candidate_id") not in candidate_ids
            or "active_ids" in state
        ):
            raise EvolutionError("verified_seed_state_invalid")

        summary = _seed_admission_summary(prepared)
        state_payload = {**state, "seed_admission": summary}
        state_text = json.dumps(
            state_payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ) + "\n"
        if len(state_text.encode("utf-8")) > MAX_STATE_BYTES:
            raise EvolutionError("verified seed state exceeds the bounded state size")

        ordered = tuple(sorted(prepared, key=lambda item: item.candidate.candidate_id))
        archive_lines = [
            json.dumps(
                item.candidate.to_dict(),
                ensure_ascii=False,
                sort_keys=True,
                allow_nan=False,
            )
            for item in ordered
        ]
        if any(len(line.encode("utf-8")) > MAX_ARCHIVE_LINE_BYTES for line in archive_lines):
            raise EvolutionError("verified seed archive record exceeds the bounded size")
        marker_payload = {
            "schema_version": "1",
            "admission_sha256": summary["admission_sha256"],
            "candidate_ids": [item.candidate.candidate_id for item in ordered],
            "seed_candidates_sha256": _canonical_seed_sha256(
                [item.candidate.to_dict() for item in ordered]
            ),
        }
        marker = {
            **marker_payload,
            "commit_sha256": _canonical_seed_sha256(marker_payload),
        }
        marker_text = json.dumps(
            marker,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ) + "\n"

        if self._path_present(self.seed_stage_path) or self._path_present(self.seed_backup_path):
            raise EvolutionError("verified_seed_recovery_ambiguous")
        try:
            self.seed_stage_path.mkdir(mode=0o700)
        except OSError as exc:
            raise EvolutionError("verified_seed_commit_failed") from exc
        stage = self.seed_stage_path
        root_moved = False
        try:
            os.chmod(stage, 0o700)
            stage_candidates = stage / "candidates"
            stage_candidates.mkdir(mode=0o700)
            if contract_content is not None:
                self._write_private_bytes(stage / "contract.json", contract_content)
            for item in ordered:
                candidate_path = stage / Path(item.candidate.code_path).relative_to("evolution")
                self._write_private_text(candidate_path, item.source)
                evidence = {
                    "schema_version": "1",
                    "provenance": item.candidate.metadata["seed_handoff"]["provenance"],
                    "external_evidence": item.provenance["external_evidence"],
                    "provenance_sha256": _canonical_seed_sha256(item.provenance),
                    "handoff_sha256": item.handoff_sha256,
                    "receipt_sha256": item.receipt["receipt_sha256"],
                }
                record_payload = {
                    **item.candidate.to_dict(),
                    "seed_handoff_evidence": evidence,
                }
                record_text = json.dumps(
                    record_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                    allow_nan=False,
                ) + "\n"
                receipt_text = json.dumps(
                    item.receipt,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                    allow_nan=False,
                ) + "\n"
                if (
                    len(record_text.encode("utf-8")) > MAX_ARCHIVE_LINE_BYTES
                    or len(receipt_text.encode("utf-8")) > MAX_ARCHIVE_LINE_BYTES
                ):
                    raise EvolutionError("verified seed evidence exceeds the bounded size")
                self._write_private_text(candidate_path.parent / "record.json", record_text)
                self._write_private_text(candidate_path.parent / "receipt.json", receipt_text)
            self._write_private_text(stage / "archive.jsonl", "\n".join(archive_lines) + "\n")
            self._write_private_text(stage / "state.json", state_text)
            self._write_private_text(stage / "seed-commit.json", marker_text)
            if contract_content is not None:
                current_contract = self._seed_contract_for_commit(contract_sha256)
                if current_contract != contract_content:
                    raise EvolutionError("verified_seed_contract_changed")
                if self._path_present(self.seed_backup_path):
                    raise EvolutionError("verified_seed_recovery_ambiguous")
                os.replace(self.root, self.seed_backup_path)
                root_moved = True
                backup_contract, backup_digest = self._contract_only_snapshot(
                    self.seed_backup_path
                )
                if backup_contract != contract_content or backup_digest != contract_sha256:
                    raise EvolutionError("verified_seed_contract_changed")
            os.replace(stage, self.root)
        except Exception as exc:
            if root_moved and not self._path_present(self.root):
                try:
                    os.replace(self.seed_backup_path, self.root)
                    root_moved = False
                except OSError:
                    pass
            if stage.exists() and not stage.is_symlink():
                shutil.rmtree(stage, ignore_errors=True)
            if isinstance(exc, EvolutionError):
                raise
            raise EvolutionError("verified_seed_commit_failed") from exc
        if root_moved and self.seed_backup_path.exists():
            try:
                shutil.rmtree(self.seed_backup_path)
            except OSError:
                # The committed tree is canonical. A recognizable backup can be removed safely
                # by the next CandidateArchive initialization after an interruption here.
                pass
        return tuple(item.candidate for item in ordered)

    @staticmethod
    def _read_seed_json(path: Path) -> dict[str, Any]:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ARCHIVE_LINE_BYTES:
            raise EvolutionError("verified_seed_resume_mismatch")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise EvolutionError("verified_seed_resume_mismatch")
        return payload

    def validate_initial_seeds(
        self,
        seeds: Sequence[AdmittedSeedInput],
        *,
        state: dict[str, Any],
        contract_sha256: str,
        evaluator_fingerprint: str | None,
        canonical_strategy: Literal["population", "openevolve"] = "population",
    ) -> tuple[Candidate, ...]:
        """Fail closed unless fresh admissions exactly match the persisted seed transaction."""

        try:
            prepared = _prepare_initial_seeds(
                seeds,
                canonical_strategy=canonical_strategy,
            )
            self._seed_authority(
                prepared,
                contract_sha256=contract_sha256,
                evaluator_fingerprint=evaluator_fingerprint,
            )
            summary = _seed_admission_summary(prepared)
            if state.get("seed_admission") != summary:
                raise EvolutionError("verified_seed_resume_mismatch")
            marker = self._read_seed_json(self.seed_commit_path)
            if set(marker) != {
                "schema_version",
                "admission_sha256",
                "candidate_ids",
                "seed_candidates_sha256",
                "commit_sha256",
            }:
                raise EvolutionError("verified_seed_resume_mismatch")
            marker_payload = {
                key: item for key, item in marker.items() if key != "commit_sha256"
            }
            if (
                marker["schema_version"] != "1"
                or marker["admission_sha256"] != summary["admission_sha256"]
                or marker["commit_sha256"] != _canonical_seed_sha256(marker_payload)
            ):
                raise EvolutionError("verified_seed_resume_mismatch")

            archive = {item.candidate_id: item for item in self.records()}
            expected_ids = {item.candidate.candidate_id for item in prepared}
            if set(marker["candidate_ids"]) != expected_ids or not expected_ids <= set(archive):
                raise EvolutionError("verified_seed_resume_mismatch")
            persisted_seed_candidates = [
                archive[candidate_id].to_dict() for candidate_id in sorted(expected_ids)
            ]
            if marker["seed_candidates_sha256"] != _canonical_seed_sha256(
                persisted_seed_candidates
            ):
                raise EvolutionError("verified_seed_resume_mismatch")

            current_by_id = {item.candidate.candidate_id: item for item in prepared}
            for candidate_id in sorted(expected_ids):
                current = current_by_id[candidate_id]
                persisted = archive[candidate_id]
                if (
                    persisted.parent_id != current.candidate.parent_id
                    or persisted.generation != current.candidate.generation
                    or persisted.iteration != current.candidate.iteration
                    or persisted.strategy != current.candidate.strategy
                    or persisted.island_id != current.candidate.island_id
                    or persisted.evaluation.to_dict() != current.candidate.evaluation.to_dict()
                    or persisted.metadata != current.candidate.metadata
                ):
                    raise EvolutionError("verified_seed_resume_mismatch")
                source_path = _confined(
                    self.workspace,
                    self.workspace / persisted.code_path,
                    "verified seed source path",
                )
                _reject_symlink_components(
                    source_path,
                    self.candidates_root,
                    "verified seed source path",
                )
                if source_path.is_symlink() or not source_path.is_file():
                    raise EvolutionError("verified_seed_resume_mismatch")
                source_bytes = source_path.read_bytes()
                if (
                    len(source_bytes) > MAX_SOURCE_BYTES
                    or source_bytes != current.source.encode("utf-8")
                    or hashlib.sha256(source_bytes).hexdigest()
                    != current.receipt["source_sha256"]
                ):
                    raise EvolutionError("verified_seed_resume_mismatch")
                record = self._read_seed_json(source_path.parent / "record.json")
                receipt = self._read_seed_json(source_path.parent / "receipt.json")
                candidate_payload = persisted.to_dict()
                if any(record.get(key) != item for key, item in candidate_payload.items()):
                    raise EvolutionError("verified_seed_resume_mismatch")
                if set(record) != {*candidate_payload, "seed_handoff_evidence"}:
                    raise EvolutionError("verified_seed_resume_mismatch")
                evidence = record["seed_handoff_evidence"]
                expected_evidence = {
                    "schema_version": "1",
                    "provenance": current.candidate.metadata["seed_handoff"]["provenance"],
                    "external_evidence": current.provenance["external_evidence"],
                    "provenance_sha256": _canonical_seed_sha256(current.provenance),
                    "handoff_sha256": current.handoff_sha256,
                    "receipt_sha256": current.receipt["receipt_sha256"],
                }
                if evidence != expected_evidence or receipt != current.receipt:
                    raise EvolutionError("verified_seed_resume_mismatch")
            return tuple(archive[candidate_id] for candidate_id in sorted(expected_ids))
        except EvolutionError:
            raise
        except Exception as exc:
            raise EvolutionError("verified_seed_resume_mismatch") from exc

    def best(self) -> Candidate | None:
        valid = [candidate for candidate in self.records() if candidate.evaluation.validity == 1]
        if not valid:
            return None
        return max(valid, key=lambda candidate: candidate.evaluation.combined_score)

    def write_state(self, payload: dict[str, Any]) -> None:
        self._ensure_layout()
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        if len(encoded.encode("utf-8")) > MAX_STATE_BYTES:
            raise EvolutionError("evolution state exceeds the bounded state size")
        if self.state_path.exists() and self.state_path.is_symlink():
            raise EvolutionError("evolution state must not be a symlink")
        temporary = self.state_path.with_name(".state.json.tmp")
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(self.state_path)

    def read_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        if self.state_path.is_symlink() or self.state_path.stat().st_size > MAX_STATE_BYTES:
            raise EvolutionError("evolution state is invalid or exceeds the bounded size")
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise EvolutionError("evolution state must be an object")
        return payload

    def result(self, strategy: str, status: str, iterations: int, error: str | None = None) -> StrategyResult:
        records = self.records()
        best = self.best()
        best_path: str | None = None
        if best is not None:
            raw_path = self.workspace / best.code_path
            try:
                _reject_symlink_components(raw_path, self.workspace, "best candidate path")
                resolved = _confined(self.workspace, raw_path, "best candidate path")
                if not resolved.is_file() or resolved.is_symlink():
                    raise EvolutionError("best candidate path is not a regular file")
                best_path = resolved.relative_to(self.workspace).as_posix()
            except (OSError, ValueError, EvolutionError):
                # A stale or tampered archive record must never hand an unverified source to a
                # parent Agent. Treat the selected candidate as unavailable for this result.
                best = None
        return StrategyResult(
            strategy=strategy,
            status=status,  # type: ignore[arg-type]
            iterations=max(0, iterations),
            evaluated_candidates=len(records),
            valid_candidates=sum(item.evaluation.validity == 1 for item in records),
            best_candidate_id=best.candidate_id if best else None,
            best_score=best.evaluation.combined_score if best else None,
            archive_path=self.archive_path.relative_to(self.workspace).as_posix(),
            error=_bounded_error(error) if error else None,
            best_candidate_path=best_path,
        )


def _report(value: EvaluationReport | dict[str, Any]) -> EvaluationReport:
    if isinstance(value, EvaluationReport):
        return value
    if isinstance(value, dict):
        return EvaluationReport.from_dict(value)
    raise EvolutionError("evaluator must return an EvaluationReport or object")


def _invalid_report(message: object) -> EvaluationReport:
    return EvaluationReport.from_dict(
        {
            "schema_version": "1",
            "evaluator_id": "local-evaluator",
            "validity": 0,
            "combined_score": 0,
            "detailed_scores": {},
            "error_info": [{"code": "evaluation_error", "message": _bounded_error(message)[:512]}],
        }
    )


def _caused_by_timeout(error: BaseException) -> bool:
    """Classify a timeout from exception types only, without inspecting secret-bearing prose."""

    current: BaseException | None = error
    seen: set[int] = set()
    for _ in range(8):
        if current is None or id(current) in seen:
            return False
        seen.add(id(current))
        if isinstance(current, (TimeoutError, subprocess.TimeoutExpired)):
            return True
        current = current.__cause__ or current.__context__
    return False


def _caused_by_worker_unknown(error: BaseException) -> bool:
    """Recognize only an explicit typed worker-uncertainty signal in the cause chain."""

    current: BaseException | None = error
    seen: set[int] = set()
    for _ in range(8):
        if current is None or id(current) in seen:
            return False
        seen.add(id(current))
        if isinstance(current, WorkerUnknownError):
            return True
        current = current.__cause__ or current.__context__
    return False


class ExecutionAwareCandidateEvaluator:
    """Compose candidate execution with an existing independent evaluator.

    The wrapped evaluator keeps its historical ``(candidate_path, contract)`` signature and can
    inspect the sibling ``execution.json`` evidence. A valid evaluator report is never allowed to
    override a runner failure.
    """

    def __init__(self, runner: CandidateRunner, evaluator: CandidateEvaluator) -> None:
        if not callable(getattr(runner, "run", None)):
            raise TypeError("runner must implement run")
        if not callable(evaluator):
            raise TypeError("evaluator must be callable")
        self.runner = runner
        self.evaluator = evaluator

    def set_observer(self, observer: Callable[[str, dict[str, Any]], None] | None) -> None:
        """Forward optional Agent evidence observation through the execution wrapper."""
        setter = getattr(self.evaluator, "set_observer", None)
        if callable(setter):
            setter(observer)

    def __call__(
        self, candidate_path: Path, contract: AlgorithmProblemContract
    ) -> EvaluationReport:
        candidate = Path(candidate_path).expanduser().resolve(strict=False)
        workspace = candidate.parent
        try:
            execution = self.runner.run(candidate, workspace)
        except Exception as exc:  # noqa: BLE001 - runner is an injected local boundary
            execution = CandidateExecution(
                status="failed",
                exit_code=None,
                duration_ms=0,
                error="runner_failed",
                stderr=_bounded_output(str(exc), MAX_EXECUTION_OUTPUT_BYTES),
            )
            _write_execution_evidence(workspace, execution)
        if execution.status != "succeeded":
            detail = execution.error or f"execution_{execution.status}"
            return _invalid_report(detail)
        return _report(self.evaluator(candidate, contract))


def _drafts(value: CandidateDraft | Sequence[CandidateDraft]) -> tuple[CandidateDraft, ...]:
    if isinstance(value, CandidateDraft):
        return (value,)
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise EvolutionError("generator must return CandidateDraft or a sequence of drafts")
    output = tuple(value)
    if not output or any(not isinstance(item, CandidateDraft) for item in output):
        raise EvolutionError("generator returned no valid candidate drafts")
    return output


class _BaseStrategy:
    name: Literal["population", "openevolve"]

    def __init__(self, context: EvolutionContext) -> None:
        self.context = context
        self.archive = CandidateArchive(context.workspace)
        self.config = context.config
        self._bind_observer(context.generate)
        self._bind_observer(context.evaluate)

    def _bind_observer(self, target: object) -> None:
        setter = getattr(target, "set_observer", None)
        if callable(setter):
            setter(self.context.observe)

    def _cancelled(self) -> bool:
        try:
            return bool(self.context.cancelled())
        except Exception:  # noqa: BLE001 - cancellation callback is an external boundary
            return True

    def _persist(
        self,
        draft: CandidateDraft,
        *,
        iteration: int,
        generation: int,
        parent: Candidate | None,
        island_id: int | None,
    ) -> Candidate:
        candidate_id = self.archive.next_id()
        path = self.archive.candidate_source_path(candidate_id, draft.filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(draft.source, encoding="utf-8")
        try:
            evaluation = _report(self.context.evaluate(path, self.context.contract))
        except Exception as exc:  # noqa: BLE001 - evaluator is an injected boundary
            evaluation = _invalid_report(exc)
            draft = CandidateDraft(draft.source, draft.filename, {**draft.metadata, "evaluation_error": _bounded_error(exc)})
        candidate = self.archive.persist(
            draft,
            candidate_id=candidate_id,
            strategy=self.name,
            iteration=iteration,
            generation=generation,
            parent_id=parent.candidate_id if parent else None,
            island_id=island_id,
            evaluation=evaluation,
        )
        try:
            self.context.observe("candidate", candidate.to_dict())
        except Exception as exc:  # noqa: BLE001 - optional audit sink
            del exc
        return candidate

    def _state_payload(self, status: str, iteration: int, **extra: Any) -> dict[str, Any]:
        payload = {
            "schema_version": "1",
            "strategy": self.name,
            "status": status,
            "iteration": iteration,
            "contract_sha256": self.context.contract.digest(),
            "config": self.config.to_dict(),
            **extra,
        }
        existing = self.archive.read_state()
        seed_admission = existing.get("seed_admission")
        if seed_admission is not None:
            payload["seed_admission"] = seed_admission
        for name in (
            "outcome_schema_version",
            "outcome_start_iteration",
            "outcome_watermark",
            "outcome_watermark_sha256",
            "outcome_archive_baseline_sha256",
            "failed_offspring_iteration",
            "failed_offspring_sha256",
        ):
            if name in existing and name not in payload:
                payload[name] = existing[name]
        return payload

    def _state(self, status: str, iteration: int, **extra: Any) -> None:
        payload = self._state_payload(status, iteration, **extra)
        self.archive.write_state(payload)
        try:
            self.context.observe("state", payload)
        except Exception as exc:  # noqa: BLE001 - an audit sink must not stop local search
            # The archive/state files are still canonical for standalone callers.  Keep the
            # strategy usable when an optional observer (for example a parent process) disappears.
            del exc

    def _load_state(self) -> dict[str, Any]:
        state = self.archive.read_state()
        if not state:
            return state
        if state.get("strategy") != self.name:
            raise EvolutionError("evolution state strategy does not match the requested strategy")
        digest = state.get("contract_sha256")
        if digest != self.context.contract.digest():
            raise EvolutionError("evolution state contract digest does not match the supplied contract")
        stored_config = state.get("config")
        if stored_config is not None and stored_config != self.config.to_dict():
            raise EvolutionError("evolution state configuration does not match the supplied configuration")
        return state

    def _terminal(self, state: dict[str, Any]) -> StrategyResult | None:
        status = state.get("status")
        if status in {"completed", "stagnated", "cancelled", "failed"}:
            return self.archive.result(self.name, status, int(state.get("iteration", 0)), state.get("error"))
        return None


class LoopStrategy:
    """Read-only compatibility marker for retired single-chain evolution.

    Historical callers may still import the public name while inspecting old archives.  New or
    resumed loop execution is rejected before any candidate or state mutation.
    """

    name: Literal["loop"] = "loop"

    def __init__(self, context: EvolutionContext) -> None:
        self.context = context

    @staticmethod
    def _retired() -> EvolutionError:
        return EvolutionError(
            "loop_strategy_retired: legacy loop runs are read-only; use population or an "
            "explicit external backend"
        )

    def run(self) -> StrategyResult:
        raise self._retired()

    def resume(self) -> StrategyResult:
        raise self._retired()


def _tokens(candidate: Candidate, workspace: Path) -> set[str]:
    try:
        path = _confined(workspace, workspace / candidate.code_path, "candidate code path")
        text = path.read_text(encoding="utf-8")[:MAX_SOURCE_BYTES]
    except (OSError, UnicodeDecodeError, EvolutionError):
        return set()
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+", text))


def _novelty(candidate: Candidate, peers: Iterable[Candidate], workspace: Path) -> float:
    current = _tokens(candidate, workspace)
    if not current:
        return 0.0
    distances = []
    for peer in peers:
        other = _tokens(peer, workspace)
        union = current | other
        distances.append(1.0 if not union else 1.0 - len(current & other) / len(union))
    return min(distances, default=1.0)


class PopulationStrategy(_BaseStrategy):
    """Bounded local population search with optional islands and ring migration."""

    name: Literal["population"] = "population"

    def __init__(self, context: EvolutionContext) -> None:
        super().__init__(context)
        self.rng = random.Random(self.config.rng_seed)

    @staticmethod
    def _outcome_digest(outcomes: Iterable[OffspringOutcome]) -> str:
        ordered = sorted(outcomes, key=lambda item: (item.iteration, item.attempt))
        return _canonical_seed_sha256([item.to_dict() for item in ordered])

    @staticmethod
    def _candidate_digest(candidates: Iterable[Candidate]) -> str:
        ordered = sorted(candidates, key=lambda item: item.candidate_id)
        return _canonical_seed_sha256([item.to_dict() for item in ordered])

    def _capacity(self, island: int) -> int:
        base, remainder = divmod(self.config.population_size, self.config.num_islands)
        return base + (1 if island < remainder else 0)

    def _initial_seed_active(
        self,
        seeds: Sequence[AdmittedSeedInput],
    ) -> dict[int, list[str]]:
        if not seeds or len(seeds) > self.config.population_size:
            raise EvolutionError("verified_seed_population_capacity_exceeded")
        active = {island: [] for island in range(self.config.num_islands)}
        seen: set[str] = set()
        try:
            ordered = sorted(seeds, key=lambda seed: seed.candidate_id)
            for seed in ordered:
                candidate_id = _safe_id(seed.candidate_id, "verified seed candidate_id")
                if candidate_id in seen:
                    raise EvolutionError("verified_seed_invalid")
                seen.add(candidate_id)
                island = seed.island_id
                if (
                    isinstance(island, bool)
                    or not isinstance(island, int)
                    or island not in active
                    or len(active[island]) >= self._capacity(island)
                ):
                    raise EvolutionError("verified_seed_island_mismatch")
                active[island].append(candidate_id)
        except EvolutionError:
            raise
        except Exception as exc:
            raise EvolutionError("verified_seed_invalid") from exc
        return active

    def _commit_initial_seeds(
        self,
        seeds: Sequence[AdmittedSeedInput],
    ) -> dict[str, Any]:
        active = self._initial_seed_active(seeds)
        prepared = _prepare_initial_seeds(seeds)
        best_seed = max(
            (item.candidate for item in prepared),
            key=lambda candidate: (
                candidate.evaluation.combined_score,
                candidate.candidate_id,
            ),
        )
        state = self._state_payload(
            "running",
            0,
            active_ids={str(key): value for key, value in active.items()},
            stagnation=0,
            error=None,
            best_candidate_id=best_seed.candidate_id,
            rng_seed=self.config.rng_seed,
            last_migration_iteration=0,
        )
        candidates = self.archive.commit_initial_seeds(
            seeds,
            state=state,
            contract_sha256=self.context.contract.digest(),
            evaluator_fingerprint=self.config.evaluator_fingerprint,
        )
        for candidate in candidates:
            try:
                self.context.observe("candidate", candidate.to_dict())
            except Exception as exc:  # noqa: BLE001 - optional audit sink
                del exc
        committed_state = self.archive.read_state()
        try:
            self.context.observe("state", committed_state)
        except Exception as exc:  # noqa: BLE001 - optional audit sink
            del exc
        return committed_state

    def _seed_resume_gate(self, state: dict[str, Any]) -> dict[str, Any]:
        seeds = tuple(self.context.initial_seeds)
        has_summary = "seed_admission" in state
        has_marker = self.archive.seed_commit_path.exists() or self.archive.seed_commit_path.is_symlink()
        if has_marker != has_summary:
            raise EvolutionError("verified_seed_resume_mismatch")
        if state:
            if has_summary:
                if not seeds:
                    raise EvolutionError("verified_seed_resume_requires_initial_seeds")
                self.archive.validate_initial_seeds(
                    seeds,
                    state=state,
                    contract_sha256=self.context.contract.digest(),
                    evaluator_fingerprint=self.config.evaluator_fingerprint,
                )
            elif seeds:
                raise EvolutionError("verified_seed_cannot_modify_existing_population")
            return state
        if has_marker:
            raise EvolutionError("verified_seed_resume_mismatch")
        if seeds:
            return self._commit_initial_seeds(seeds)
        existing = self.archive.records()
        if any("seed_handoff" in candidate.metadata for candidate in existing):
            raise EvolutionError("verified_seed_resume_requires_initial_seeds")
        return state

    def _active(self, state: dict[str, Any]) -> dict[int, list[str]]:
        raw = state.get("active_ids", {})
        if not isinstance(raw, dict):
            return {i: [] for i in range(self.config.num_islands)}
        active: dict[int, list[str]] = {}
        for i in range(self.config.num_islands):
            ids = raw.get(str(i), [])
            if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
                raise EvolutionError("population state active_ids must contain string arrays")
            active[i] = list(ids)
        PopulationState(
            iteration=int(state.get("iteration", 0)),
            population_size=self.config.population_size,
            offspring_per_iteration=self.config.offspring_per_iteration,
            num_islands=self.config.num_islands,
            active_ids={str(i): tuple(ids) for i, ids in active.items()},
            best_candidate_id=state.get("best_candidate_id"),
            rng_seed=self.config.rng_seed,
            last_migration_iteration=int(state.get("last_migration_iteration", 0)),
        )
        known_ids = {candidate.candidate_id for candidate in self.archive.records()}
        if any(candidate_id not in known_ids for ids in active.values() for candidate_id in ids):
            raise EvolutionError("population state references an unknown candidate")
        return active

    def _candidates(self, ids: Iterable[str]) -> list[Candidate]:
        by_id = {candidate.candidate_id: candidate for candidate in self.archive.records()}
        return [by_id[item] for item in ids if item in by_id]

    def _rank(self, candidates: list[Candidate], all_active: list[Candidate]) -> list[Candidate]:
        return sorted(
            candidates,
            key=lambda item: (
                item.evaluation.validity,
                item.evaluation.combined_score,
                _novelty(item, [peer for peer in all_active if peer.candidate_id != item.candidate_id], self.context.workspace),
                item.candidate_id,
            ),
            reverse=True,
        )

    def _candidate_family(self, candidate: Candidate) -> str | None:
        """Project one exact canonical family tag from bounded experiment metadata."""
        if not isinstance(candidate.metadata, dict):
            return None
        experiment = candidate.metadata.get("experiment")
        if not isinstance(experiment, dict):
            return None
        change_tags = experiment.get("change_tags")
        if not isinstance(change_tags, list):
            return None
        repertoire = ALGORITHM_FAMILY_REPERTOIRES.get(self.context.contract.problem_type, ())
        return next(
            (
                family
                for family in repertoire
                if any(isinstance(tag, str) and tag == family for tag in change_tags)
            ),
            None,
        )

    def _family_elites(
        self, candidates: list[Candidate], all_active: list[Candidate]
    ) -> list[Candidate]:
        """Return the best valid candidate for every recognized family."""
        ranked = self._rank(candidates, all_active)
        elites: list[Candidate] = []
        seen: set[str] = set()
        for candidate in ranked:
            if candidate.evaluation.validity != 1:
                continue
            family = self._candidate_family(candidate)
            if family is None or family in seen:
                continue
            seen.add(family)
            elites.append(candidate)
        return elites

    def _trim(self, active: dict[int, list[str]]) -> None:
        all_active = self._candidates(item for ids in active.values() for item in ids)
        for island in range(self.config.num_islands):
            candidates = self._candidates(active[island])
            ranked = self._rank(candidates, all_active)
            capacity = self._capacity(island)
            selected: list[Candidate] = []
            selected_ids: set[str] = set()

            valid = [candidate for candidate in ranked if candidate.evaluation.validity == 1]
            if valid:
                selected.append(valid[0])
                selected_ids.add(valid[0].candidate_id)
            for elite in self._family_elites(candidates, all_active):
                if len(selected) >= capacity:
                    break
                if elite.candidate_id not in selected_ids:
                    selected.append(elite)
                    selected_ids.add(elite.candidate_id)
            for candidate in ranked:
                if len(selected) >= capacity:
                    break
                if candidate.candidate_id not in selected_ids:
                    selected.append(candidate)
                    selected_ids.add(candidate.candidate_id)
            active[island] = [item.candidate_id for item in selected]

    def _parent_pool(self, active: dict[int, list[str]], island: int) -> list[Candidate]:
        all_active = self._candidates(item for ids in active.values() for item in ids)
        candidates = self._candidates(active[island]) or all_active
        ranked = self._rank(candidates, all_active)
        elites = self._family_elites(candidates, all_active)
        if not elites:
            return ranked[:3]
        valid_ranked = [candidate for candidate in ranked if candidate.evaluation.validity == 1]
        selected = list(elites)
        selected_ids = {candidate.candidate_id for candidate in selected}
        selected.extend(
            candidate
            for candidate in valid_ranked
            if candidate.candidate_id not in selected_ids
        )
        return selected[:3]

    def _select_parent(self, active: dict[int, list[str]], island: int) -> Candidate | None:
        pool = self._parent_pool(active, island)
        if not pool:
            return None
        return self.rng.choice(pool)

    def _inspirations(self, active: dict[int, list[str]], island: int, parent: Candidate | None) -> tuple[Candidate, ...]:
        candidates = [
            item
            for other in range(self.config.num_islands)
            if other != island
            for item in self._candidates(active[other])
            if parent is None or item.candidate_id != parent.candidate_id
        ]
        if not candidates:
            candidates = [
                item
                for item in self._candidates(item for ids in active.values() for item in ids)
                if parent is None or item.candidate_id != parent.candidate_id
            ]
        valid = [candidate for candidate in candidates if candidate.evaluation.validity == 1]
        remaining = valid or candidates
        parent_family = self._candidate_family(parent) if parent is not None else None
        selected: list[Candidate] = []
        selected_families: set[str] = set()

        while remaining and len(selected) < 2:
            ranked = sorted(
                remaining,
                key=lambda item: (
                    self._candidate_family(item) is not None
                    and self._candidate_family(item) != parent_family
                    and self._candidate_family(item) not in selected_families,
                    self._candidate_family(item) is not None
                    and self._candidate_family(item) != parent_family,
                    self._candidate_family(item) is not None
                    and self._candidate_family(item) not in selected_families,
                    _novelty(
                        item,
                        tuple(([parent] if parent else []) + selected),
                        self.context.workspace,
                    ),
                    item.evaluation.combined_score,
                    item.candidate_id,
                ),
                reverse=True,
            )
            chosen = ranked[0]
            selected.append(chosen)
            family = self._candidate_family(chosen)
            if family is not None:
                selected_families.add(family)
            remaining = [
                candidate
                for candidate in remaining
                if candidate.candidate_id != chosen.candidate_id
            ]
        return tuple(selected)

    @staticmethod
    def _pending_offspring(state: dict[str, Any]) -> tuple[int, int] | None:
        value = state.get("pending_offspring")
        if value is None:
            return None
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "iteration",
            "attempt_count",
        }:
            raise EvolutionError("population_pending_batch_invalid")
        iteration = value["iteration"]
        attempt_count = value["attempt_count"]
        if (
            value["schema_version"] != "1"
            or isinstance(iteration, bool)
            or not isinstance(iteration, int)
            or iteration < 1
            or isinstance(attempt_count, bool)
            or not isinstance(attempt_count, int)
            or not 1 <= attempt_count <= 256
        ):
            raise EvolutionError("population_pending_batch_invalid")
        return iteration, attempt_count

    def _validate_outcome_history(self, state: dict[str, Any]) -> None:
        outcomes = self.archive.offspring_outcomes()
        records = self.archive.records()
        if any(candidate.strategy != "population" for candidate in records):
            raise EvolutionError("population_outcome_state_mismatch")
        pending = self._pending_offspring(state)
        failed_iteration = state.get("failed_offspring_iteration")
        failed_digest = state.get("failed_offspring_sha256")

        binding_fields = {
            "outcome_schema_version",
            "outcome_start_iteration",
            "outcome_watermark",
            "outcome_watermark_sha256",
            "outcome_archive_baseline_sha256",
        }
        present_binding_fields = binding_fields.intersection(state)
        if not present_binding_fields:
            current_iteration = state.get("iteration", 0)
            if (
                outcomes
                or pending is not None
                or failed_iteration is not None
                or failed_digest is not None
                or isinstance(current_iteration, bool)
                or not isinstance(current_iteration, int)
                or current_iteration < 0
                or any(candidate.iteration > current_iteration for candidate in records)
            ):
                raise EvolutionError("population_outcome_state_mismatch")
            # Population states written before the outcome journal was introduced remain
            # resumable. The first new batch establishes a baseline at the next iteration.
            return
        if present_binding_fields != binding_fields:
            raise EvolutionError("population_outcome_state_mismatch")

        current_iteration = state.get("iteration", 0)
        start_iteration = state["outcome_start_iteration"]
        watermark = state["outcome_watermark"]
        watermark_digest = state["outcome_watermark_sha256"]
        baseline_digest = state["outcome_archive_baseline_sha256"]
        if (
            state["outcome_schema_version"] != "1"
            or isinstance(current_iteration, bool)
            or not isinstance(current_iteration, int)
            or current_iteration < 0
            or isinstance(start_iteration, bool)
            or not isinstance(start_iteration, int)
            or start_iteration < 1
            or isinstance(watermark, bool)
            or not isinstance(watermark, int)
            or watermark != current_iteration
            or start_iteration > watermark + 1
            or not isinstance(watermark_digest, str)
            or not _SHA256.fullmatch(watermark_digest)
            or not isinstance(baseline_digest, str)
            or not _SHA256.fullmatch(baseline_digest)
        ):
            raise EvolutionError("population_outcome_state_mismatch")

        if failed_iteration is not None and (
            isinstance(failed_iteration, bool)
            or not isinstance(failed_iteration, int)
            or state.get("status") != "failed"
            or failed_iteration != current_iteration + 1
        ):
            raise EvolutionError("population_outcome_state_mismatch")
        if (failed_iteration is None) != (failed_digest is None) or (
            failed_digest is not None
            and (
                not isinstance(failed_digest, str)
                or not _SHA256.fullmatch(failed_digest)
            )
        ):
            raise EvolutionError("population_outcome_state_mismatch")
        if pending is not None and (
            state.get("status") != "running"
            or failed_iteration is not None
            or pending[0] != current_iteration + 1
            or pending[1] != self.config.offspring_per_iteration
        ):
            raise EvolutionError("population_outcome_state_mismatch")
        if (
            start_iteration == watermark + 1
            and pending is None
            and failed_iteration is None
        ):
            raise EvolutionError("population_outcome_state_mismatch")

        grouped: dict[int, list[OffspringOutcome]] = {}
        for outcome in outcomes:
            if (
                outcome.iteration < start_iteration
                or outcome.attempt >= self.config.offspring_per_iteration
                or outcome.island_id != outcome.attempt % self.config.num_islands
            ):
                raise EvolutionError("population_outcome_state_mismatch")
            grouped.setdefault(outcome.iteration, []).append(outcome)

        expected_attempts = set(range(self.config.offspring_per_iteration))
        for iteration in range(start_iteration, watermark + 1):
            completed = grouped.get(iteration, [])
            if (
                {item.attempt for item in completed} != expected_attempts
                or not any(item.code == "evaluated" for item in completed)
            ):
                raise EvolutionError("population_outcome_state_mismatch")

        completed_prefix = [
            item
            for item in outcomes
            if start_iteration <= item.iteration <= watermark
        ]
        if self._outcome_digest(completed_prefix) != watermark_digest:
            raise EvolutionError("population_outcome_state_mismatch")
        baseline = [
            candidate for candidate in records if candidate.iteration < start_iteration
        ]
        if self._candidate_digest(baseline) != baseline_digest:
            raise EvolutionError("population_outcome_state_mismatch")

        future_iteration = current_iteration + 1
        for iteration, iteration_outcomes in grouped.items():
            if iteration <= watermark:
                continue
            attempts = {item.attempt for item in iteration_outcomes}
            if pending is not None and iteration == future_iteration:
                if not attempts <= expected_attempts:
                    raise EvolutionError("population_outcome_state_mismatch")
                continue
            if failed_iteration == iteration == future_iteration:
                if attempts != expected_attempts or any(
                    item.code == "evaluated" for item in iteration_outcomes
                ):
                    raise EvolutionError("population_outcome_state_mismatch")
                continue
            raise EvolutionError("population_outcome_state_mismatch")

        if failed_iteration is not None:
            failed_outcomes = grouped.get(failed_iteration, [])
            if (
                {item.attempt for item in failed_outcomes} != expected_attempts
                or any(item.code == "evaluated" for item in failed_outcomes)
                or self._outcome_digest(failed_outcomes) != failed_digest
            ):
                raise EvolutionError("population_outcome_state_mismatch")

        candidates_by_id = {item.candidate_id: item for item in records}
        evaluated = [item for item in outcomes if item.code == "evaluated"]
        evaluated_ids = [item.candidate_id for item in evaluated]
        if len(evaluated_ids) != len(set(evaluated_ids)):
            raise EvolutionError("population_outcome_state_mismatch")
        for outcome in evaluated:
            candidate_id = outcome.candidate_id
            assert candidate_id is not None
            candidate = candidates_by_id.get(candidate_id)
            if (
                candidate is None
                or candidate.strategy != "population"
                or candidate.iteration != outcome.iteration
                or candidate.island_id != outcome.island_id
            ):
                raise EvolutionError("population_outcome_state_mismatch")
        evaluated_id_set = set(evaluated_ids)
        if any(
            candidate.strategy == "population"
            and candidate.iteration >= start_iteration
            and candidate.candidate_id not in evaluated_id_set
            for candidate in records
        ):
            raise EvolutionError("population_outcome_state_mismatch")
        for iteration, iteration_outcomes in grouped.items():
            expected_ids = [
                item.candidate_id
                for item in sorted(iteration_outcomes, key=lambda item: item.attempt)
                if item.code == "evaluated"
            ]
            archived_ids = [
                candidate.candidate_id
                for candidate in records
                if candidate.iteration == iteration
            ]
            if archived_ids != expected_ids:
                raise EvolutionError("population_outcome_state_mismatch")

    def _begin_offspring_batch(
        self,
        state: dict[str, Any],
        active: dict[int, list[str]],
    ) -> dict[str, Any]:
        self._validate_outcome_history(state)
        if self._pending_offspring(state) is not None:
            raise EvolutionError("population_pending_batch_invalid")
        target_iteration = int(state.get("iteration", 0)) + 1
        if any(
            item.iteration == target_iteration
            for item in self.archive.offspring_outcomes()
        ):
            raise EvolutionError("population_outcome_state_mismatch")
        records = self.archive.records()
        start_iteration = state.get("outcome_start_iteration", target_iteration)
        watermark_digest = state.get(
            "outcome_watermark_sha256", self._outcome_digest(())
        )
        baseline_digest = state.get(
            "outcome_archive_baseline_sha256",
            self._candidate_digest(
                candidate
                for candidate in records
                if candidate.iteration < start_iteration
            ),
        )
        current = self.archive.best()
        self._state(
            "running",
            target_iteration - 1,
            active_ids={str(key): value for key, value in active.items()},
            stagnation=int(state.get("stagnation", 0)),
            error=None,
            best_candidate_id=current.candidate_id if current else None,
            rng_seed=self.config.rng_seed,
            last_migration_iteration=int(state.get("last_migration_iteration", 0)),
            pending_offspring={
                "schema_version": "1",
                "iteration": target_iteration,
                "attempt_count": self.config.offspring_per_iteration,
            },
            outcome_schema_version="1",
            outcome_start_iteration=start_iteration,
            outcome_watermark=target_iteration - 1,
            outcome_watermark_sha256=watermark_digest,
            outcome_archive_baseline_sha256=baseline_digest,
        )
        return self.archive.read_state()

    def _discard_unarchived_candidate(self, candidate_id: str) -> None:
        path = self.archive.candidates_root / candidate_id
        try:
            if path.is_symlink():
                path.unlink()
            elif path.exists():
                shutil.rmtree(path)
        except OSError:
            pass

    def _attempt_offspring(
        self,
        active: dict[int, list[str]],
        *,
        iteration: int,
        attempt: int,
    ) -> OffspringOutcome:
        island = attempt % self.config.num_islands
        try:
            parent = self._select_parent(active, island)
            request = GenerationRequest(
                iteration=iteration,
                parent=parent,
                inspirations=self._inspirations(active, island, parent),
                archive=tuple(self.archive.records()),
                workspace=self.context.workspace,
            )
        except Exception:  # noqa: BLE001 - no narrower attempt result exists yet
            return OffspringOutcome(iteration, attempt, island, "run_failed")

        try:
            draft = _drafts(self.context.generate(request))[0]
        except Exception:  # noqa: BLE001 - generator prose must not enter durable state
            return OffspringOutcome(iteration, attempt, island, "candidate_failed")

        candidate_id: str | None = None
        try:
            candidate_id = self.archive.next_id()
            path = self.archive.candidate_source_path(candidate_id, draft.filename)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(draft.source, encoding="utf-8")
        except Exception:  # noqa: BLE001 - candidate setup has one controlled outcome
            if candidate_id is not None:
                self._discard_unarchived_candidate(candidate_id)
            return OffspringOutcome(iteration, attempt, island, "candidate_failed")

        try:
            evaluation = _report(self.context.evaluate(path, self.context.contract))
        except Exception as exc:  # noqa: BLE001 - evaluator is an injected boundary
            self._discard_unarchived_candidate(candidate_id)
            if _caused_by_worker_unknown(exc):
                code = "worker_unknown"
            elif _caused_by_timeout(exc):
                code = "evaluator_timeout"
            else:
                code = "run_failed"
            return OffspringOutcome(iteration, attempt, island, code)

        try:
            candidate = self.archive.persist(
                draft,
                candidate_id=candidate_id,
                strategy=self.name,
                iteration=iteration,
                generation=(parent.generation + 1 if parent else 0),
                parent_id=parent.candidate_id if parent else None,
                island_id=island,
                evaluation=evaluation,
            )
        except Exception:  # noqa: BLE001 - persistence failure is controlled and prose-free
            self._discard_unarchived_candidate(candidate_id)
            return OffspringOutcome(iteration, attempt, island, "candidate_failed")
        try:
            self.context.observe("candidate", candidate.to_dict())
        except Exception as exc:  # noqa: BLE001 - optional observer cannot change the outcome
            del exc
        return OffspringOutcome(
            iteration,
            attempt,
            island,
            "evaluated",
            candidate_id=candidate.candidate_id,
        )

    def _finish_offspring_batch(
        self,
        state: dict[str, Any],
        active: dict[int, list[str]],
    ) -> tuple[dict[str, Any], dict[int, list[str]]]:
        self._validate_outcome_history(state)
        pending = self._pending_offspring(state)
        if pending is None:
            raise EvolutionError("population_pending_batch_invalid")
        target_iteration, attempt_count = pending
        outcomes = sorted(
            (
                item
                for item in self.archive.offspring_outcomes()
                if item.iteration == target_iteration
            ),
            key=lambda item: item.attempt,
        )
        if len(outcomes) != attempt_count or [item.attempt for item in outcomes] != list(
            range(attempt_count)
        ):
            raise EvolutionError("population_iteration_incomplete")

        current_iteration = int(state.get("iteration", 0))
        records = self.archive.records()
        by_id = {candidate.candidate_id: candidate for candidate in records}
        evaluated = [item for item in outcomes if item.code == "evaluated"]
        evaluated_ids = [item.candidate_id for item in evaluated]
        if len(evaluated_ids) != len(set(evaluated_ids)) or any(
            candidate_id not in by_id
            or by_id[candidate_id].strategy != "population"
            or by_id[candidate_id].iteration != target_iteration
            or by_id[candidate_id].island_id != outcome.island_id
            for outcome, candidate_id in zip(evaluated, evaluated_ids, strict=True)
        ):
            raise EvolutionError("population_outcome_state_mismatch")
        current_batch_candidates = {
            candidate.candidate_id
            for candidate in records
            if candidate.strategy == "population"
            and candidate.iteration > current_iteration
        }
        if current_batch_candidates != set(evaluated_ids):
            raise EvolutionError("population_outcome_state_mismatch")

        migration_watermark = int(state.get("last_migration_iteration", 0))
        if not evaluated:
            current = self.archive.best()
            self._state(
                "failed",
                current_iteration,
                active_ids={str(key): value for key, value in active.items()},
                stagnation=int(state.get("stagnation", 0)),
                error="offspring_batch_failed",
                best_candidate_id=current.candidate_id if current else None,
                rng_seed=self.config.rng_seed,
                last_migration_iteration=migration_watermark,
                outcome_schema_version="1",
                outcome_start_iteration=state["outcome_start_iteration"],
                outcome_watermark=current_iteration,
                outcome_watermark_sha256=state["outcome_watermark_sha256"],
                outcome_archive_baseline_sha256=state[
                    "outcome_archive_baseline_sha256"
                ],
                failed_offspring_iteration=target_iteration,
                failed_offspring_sha256=self._outcome_digest(outcomes),
            )
            return self.archive.read_state(), active

        previous_valid = [
            candidate
            for candidate in records
            if candidate.iteration <= current_iteration and candidate.evaluation.validity == 1
        ]
        previous_best_score = max(
            (candidate.evaluation.combined_score for candidate in previous_valid),
            default=None,
        )
        for outcome in evaluated:
            candidate_id = outcome.candidate_id
            assert candidate_id is not None
            if candidate_id in {item for ids in active.values() for item in ids}:
                raise EvolutionError("population_outcome_state_mismatch")
            active[outcome.island_id].append(candidate_id)
        self._trim(active)
        if self._migrate(active, target_iteration):
            migration_watermark = target_iteration
        current = self.archive.best()
        current_score = current.evaluation.combined_score if current else None
        stagnation = int(state.get("stagnation", 0))
        if current_score is not None and (
            previous_best_score is None or current_score > previous_best_score
        ):
            stagnation = 0
        else:
            stagnation += 1
        self._state(
            "running",
            target_iteration,
            active_ids={str(key): value for key, value in active.items()},
            stagnation=stagnation,
            error=(
                None
                if len(evaluated) == len(outcomes)
                else "offspring_attempt_failed"
            ),
            best_candidate_id=current.candidate_id if current else None,
            rng_seed=self.config.rng_seed,
            last_migration_iteration=migration_watermark,
            outcome_schema_version="1",
            outcome_start_iteration=state["outcome_start_iteration"],
            outcome_watermark=target_iteration,
            outcome_watermark_sha256=self._outcome_digest(
                item
                for item in self.archive.offspring_outcomes()
                if state["outcome_start_iteration"]
                <= item.iteration
                <= target_iteration
            ),
            outcome_archive_baseline_sha256=state[
                "outcome_archive_baseline_sha256"
            ],
        )
        return self.archive.read_state(), active

    def _resume_offspring_batch(
        self,
        state: dict[str, Any],
        active: dict[int, list[str]],
    ) -> tuple[dict[str, Any], dict[int, list[str]]]:
        self._validate_outcome_history(state)
        pending = self._pending_offspring(state)
        if pending is None:
            return state, active
        completed = sum(
            item.iteration == pending[0]
            for item in self.archive.offspring_outcomes()
        )
        if completed != pending[1]:
            raise EvolutionError("population_iteration_incomplete")
        return self._finish_offspring_batch(state, active)

    def _migrate(self, active: dict[int, list[str]], iteration: int) -> bool:
        if self.config.num_islands <= 1 or not self.config.migration_interval:
            return False
        if iteration % self.config.migration_interval or self.config.migration_rate <= 0:
            return False
        count = max(1, int(self._capacity(0) * self.config.migration_rate))
        moves: list[tuple[int, int, str]] = []
        for source in range(self.config.num_islands):
            candidates = self._rank(self._candidates(active[source]), self._candidates(item for ids in active.values() for item in ids))
            for candidate in candidates[:count]:
                if len(active[source]) > 1:
                    moves.append((source, (source + 1) % self.config.num_islands, candidate.candidate_id))
        for source, target, candidate_id in moves:
            for ids in active.values():
                while candidate_id in ids:
                    ids.remove(candidate_id)
            active[target].append(candidate_id)
        self._trim(active)
        return bool(moves)

    def run(self) -> StrategyResult:
        state = self._seed_resume_gate(self._load_state())
        active = self._active(state)
        if "seed_admission" in state and not any(active.values()):
            raise EvolutionError("verified_seed_active_population_missing")
        state, active = self._resume_offspring_batch(state, active)
        terminal = self._terminal(state)
        if terminal:
            return terminal
        iteration = int(state.get("iteration", 0))
        stagnation = int(state.get("stagnation", 0))
        migration_watermark = int(state.get("last_migration_iteration", 0))
        error: str | None = state.get("error")
        if not any(active.values()):
            existing = self.archive.records()
            if existing:
                for index, candidate in enumerate(existing[-self.config.population_size :]):
                    active[index % self.config.num_islands].append(candidate.candidate_id)
            else:
                for index in range(self.config.population_size):
                    if self._cancelled():
                        self._state("cancelled", iteration, active_ids={str(k): v for k, v in active.items()}, error="cancelled")
                        return self.archive.result(self.name, "cancelled", iteration, "cancelled")
                    request = GenerationRequest(iteration=0, parent=None, inspirations=(), archive=tuple(self.archive.records()), workspace=self.context.workspace)
                    try:
                        drafts = _drafts(self.context.generate(request))
                        draft = drafts[0]
                        candidate = self._persist(draft, iteration=0, generation=0, parent=None, island_id=index % self.config.num_islands)
                        active[index % self.config.num_islands].append(candidate.candidate_id)
                    except Exception:  # noqa: BLE001 - initialization retains one fixed code
                        error = "candidate_failed"
                self._trim(active)
        initial_best = self.archive.best()
        self._state(
            "running",
            iteration,
            active_ids={str(k): v for k, v in active.items()},
            stagnation=stagnation,
            error=error,
            best_candidate_id=initial_best.candidate_id if initial_best else None,
            rng_seed=self.config.rng_seed,
            last_migration_iteration=migration_watermark,
        )
        state = self.archive.read_state()
        if iteration > 0 and stagnation >= self.config.stagnation_rounds:
            current = self.archive.best()
            self._state(
                "stagnated",
                iteration,
                active_ids={str(key): value for key, value in active.items()},
                stagnation=stagnation,
                error=error,
                best_candidate_id=current.candidate_id if current else None,
                rng_seed=self.config.rng_seed,
                last_migration_iteration=migration_watermark,
            )
            return self.archive.result(self.name, "stagnated", iteration, error)

        while iteration < self.config.max_rounds:
            if self._cancelled():
                self._state("cancelled", iteration, active_ids={str(k): v for k, v in active.items()}, stagnation=stagnation, error="cancelled")
                return self.archive.result(self.name, "cancelled", iteration, "cancelled")
            state = self._begin_offspring_batch(state, active)
            target_iteration, _ = self._pending_offspring(state) or (iteration + 1, 0)
            for offset in range(self.config.offspring_per_iteration):
                outcome = self._attempt_offspring(
                    active,
                    iteration=target_iteration,
                    attempt=offset,
                )
                # If this append fails, pending intent remains canonical. Resume rejects the
                # incomplete batch and never repeats an attempt with uncertain terminal state.
                self.archive.append_offspring_outcome(outcome)
                try:
                    self.context.observe("offspring_outcome", outcome.to_dict())
                except Exception as exc:  # noqa: BLE001 - optional audit sink
                    del exc
            state, active = self._finish_offspring_batch(state, active)
            terminal = self._terminal(state)
            if terminal:
                return terminal
            iteration = int(state["iteration"])
            stagnation = int(state.get("stagnation", 0))
            migration_watermark = int(state.get("last_migration_iteration", 0))
            error = state.get("error")
            current = self.archive.best()
            if stagnation >= self.config.stagnation_rounds:
                self._state(
                    "stagnated",
                    iteration,
                    active_ids={str(k): v for k, v in active.items()},
                    stagnation=stagnation,
                    error=error,
                    best_candidate_id=current.candidate_id if current else None,
                    rng_seed=self.config.rng_seed,
                    last_migration_iteration=migration_watermark,
                )
                return self.archive.result(self.name, "stagnated", iteration, error)

        status = "completed" if self.archive.best() is not None else "failed"
        final_error = error or ("no valid candidate" if status == "failed" else None)
        final_best = self.archive.best()
        self._state(
            status,
            iteration,
            active_ids={str(k): v for k, v in active.items()},
            stagnation=stagnation,
            error=final_error,
            best_candidate_id=final_best.candidate_id if final_best else None,
            rng_seed=self.config.rng_seed,
            last_migration_iteration=migration_watermark,
        )
        return self.archive.result(self.name, status, iteration, final_error)

    def resume(self) -> StrategyResult:
        return self.run()


class OpenEvolveStrategy(_BaseStrategy):
    """Run a local OpenEvolve producer and admit one result through the exact harness."""

    name: Literal["openevolve"] = "openevolve"

    def _budget(self) -> dict[str, Any]:
        return {
            "max_rounds": self.config.max_rounds,
            "stagnation_rounds": self.config.stagnation_rounds,
            "population_size": self.config.population_size,
            "offspring_per_iteration": self.config.offspring_per_iteration,
            "num_islands": self.config.num_islands,
            "migration_interval": self.config.migration_interval,
            "migration_rate": self.config.migration_rate,
            "rng_seed": self.config.rng_seed,
            "timeout_seconds": self.config.timeout_seconds,
        }

    def _producer_fingerprint(self) -> str:
        # Import lazily: the handoff adapter depends on the neutral CandidateDraft definitions in
        # this module, so a module-level import would create a cycle.
        from .openevolve_handoff import OPENEVOLVE_RESULT_PROTOCOL

        command_sha256 = self.config.to_dict().get("command_sha256")
        payload = {
            "schema_version": "1",
            "producer_id": "openevolve",
            "wrapper_protocol": OPENEVOLVE_RESULT_PROTOCOL,
            "command_sha256": command_sha256,
            "contract_sha256": self.context.contract.digest(),
            "budget": self._budget(),
        }
        return hashlib.sha256(_canonical_seed_bytes(payload)).hexdigest()

    @staticmethod
    def _stop_producer(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            try:
                process.kill()
            except OSError:
                pass
        try:
            process.wait()
        except OSError:
            pass

    def _run_producer(self, external: Path, config_path: Path) -> str:
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                [*self.config.command, str(config_path)],
                cwd=external,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            deadline = time.monotonic() + float(self.config.timeout_seconds)
            while True:
                if self._cancelled():
                    self._stop_producer(process)
                    return "cancelled"
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._stop_producer(process)
                    return "timed_out"
                try:
                    return "succeeded" if process.wait(timeout=min(0.1, remaining)) == 0 else "failed"
                except subprocess.TimeoutExpired:
                    continue
        except OSError:
            return "start_failed"
        finally:
            if process is not None and process.poll() is None:
                self._stop_producer(process)

    def _failed(self, code: str) -> StrategyResult:
        self._state("failed", 0, error=code)
        return self.archive.result(self.name, "failed", 0, code)

    def _observe_seed_commit(self, candidates: Sequence[Candidate]) -> None:
        for candidate in candidates:
            try:
                self.context.observe("candidate", candidate.to_dict())
            except Exception as exc:  # noqa: BLE001 - optional audit sink
                del exc
        state = self.archive.read_state()
        try:
            self.context.observe("state", state)
        except Exception as exc:  # noqa: BLE001 - optional audit sink
            del exc

    def _fresh_completed_admission(self, state: dict[str, Any]) -> None:
        """Re-evaluate canonical material without invoking the producer again."""

        from .openevolve_handoff import (
            declared_protocol_environment_sha256,
            source_only_dependency_sha256,
        )
        from .seed_handoff import SeedManifest, admit_seed_manifest

        try:
            records = self.archive.records()
            if len(records) != 1:
                raise EvolutionError("openevolve_resume_mismatch")
            candidate = records[0]
            if (
                candidate.strategy != "openevolve"
                or candidate.iteration != 1
                or candidate.generation != 0
                or candidate.parent_id is not None
                or candidate.island_id is not None
            ):
                raise EvolutionError("openevolve_resume_mismatch")
            candidate_root = self.archive.candidates_root / candidate.candidate_id
            source_path = _confined(
                self.archive.workspace,
                self.archive.workspace / candidate.code_path,
                "OpenEvolve canonical source",
            )
            _reject_symlink_components(
                source_path,
                self.archive.candidates_root,
                "OpenEvolve canonical source",
            )
            source_path.relative_to(candidate_root)
            record = self.archive._read_seed_json(source_path.parent / "record.json")
            evidence = record.get("seed_handoff_evidence")
            if not isinstance(evidence, dict) or set(evidence) != {
                "schema_version",
                "provenance",
                "external_evidence",
                "provenance_sha256",
                "handoff_sha256",
                "receipt_sha256",
            }:
                raise EvolutionError("openevolve_resume_mismatch")
            projection = evidence["provenance"]
            external_evidence = evidence["external_evidence"]
            handoff = candidate.metadata.get("seed_handoff")
            seed_metadata = candidate.metadata.get("seed_metadata")
            if (
                evidence["schema_version"] != "1"
                or not isinstance(projection, dict)
                or set(projection) != {
                    "origin_kind",
                    "producer_id",
                    "producer_fingerprint",
                    "producer_run_id",
                    "material_refs_sha256",
                    "external_evidence_sha256",
                }
                or projection["origin_kind"] != "external"
                or projection["producer_id"] != "openevolve"
                or projection["material_refs_sha256"] != _canonical_seed_sha256([])
                or not isinstance(external_evidence, dict)
                or projection["external_evidence_sha256"]
                != _canonical_seed_sha256(external_evidence)
                or not isinstance(handoff, dict)
                or not isinstance(seed_metadata, dict)
                or handoff.get("candidate_id") != candidate.candidate_id
                or not isinstance(handoff.get("lineage"), list)
            ):
                raise EvolutionError("openevolve_resume_mismatch")
            evaluator_fingerprint = self.config.evaluator_fingerprint
            if evaluator_fingerprint is None:
                raise EvolutionError("openevolve_resume_mismatch")
            source_sha256 = handoff.get("source_sha256")
            if not isinstance(source_sha256, str) or not _SHA256.fullmatch(source_sha256):
                raise EvolutionError("openevolve_resume_mismatch")
            dependency_sha256 = source_only_dependency_sha256(source_sha256)
            environment_sha256 = declared_protocol_environment_sha256()
            manifest = SeedManifest.from_dict(
                {
                    "schema_version": "1",
                    "contract_sha256": self.context.contract.digest(),
                    "evaluator": {
                        "kind": "exact_harness",
                        "fingerprint": evaluator_fingerprint,
                    },
                    "dependency_sha256": dependency_sha256,
                    "environment_sha256": environment_sha256,
                    "seeds": [
                        {
                            "identity": candidate.candidate_id,
                            "source_path": source_path.name,
                            "source_sha256": source_sha256,
                            "lineage": handoff["lineage"],
                            "provenance": {
                                "origin_kind": "external",
                                "producer_id": "openevolve",
                                "producer_fingerprint": self._producer_fingerprint(),
                                "producer_run_id": projection["producer_run_id"],
                                "material_refs": [],
                                "external_evidence": external_evidence,
                            },
                            "metadata": seed_metadata,
                        }
                    ],
                },
                source_root=source_path.parent,
            )
            admission = admit_seed_manifest(
                manifest,
                self.context.contract,
                self.context.evaluate,
                evaluator_kind="exact_harness",
                evaluator_fingerprint=evaluator_fingerprint,
                dependency_sha256=dependency_sha256,
                environment_sha256=environment_sha256,
                num_islands=1,
            )
            self.archive.validate_initial_seeds(
                admission.admitted,
                state=state,
                contract_sha256=self.context.contract.digest(),
                evaluator_fingerprint=evaluator_fingerprint,
                canonical_strategy="openevolve",
            )
        except Exception as exc:
            if isinstance(exc, EvolutionError) and str(exc) == "openevolve_resume_mismatch":
                raise
            raise EvolutionError("openevolve_resume_mismatch") from exc

    def run(self) -> StrategyResult:
        state = self._load_state()
        if state.get("status") == "completed":
            if "seed_admission" not in state:
                raise EvolutionError("openevolve_resume_mismatch")
            self._fresh_completed_admission(state)
            return self.archive.result(self.name, "completed", 1)
        terminal = self._terminal(state)
        if terminal:
            return terminal
        command = self.config.command
        executable = Path(command[0])
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            return self._failed("openevolve_command_invalid")
        if self._cancelled():
            self._state("cancelled", 0, error="cancelled")
            return self.archive.result(self.name, "cancelled", 0, "cancelled")
        evaluator_fingerprint = self.config.evaluator_fingerprint
        if evaluator_fingerprint is None:
            return self._failed("openevolve_evaluator_identity_missing")
        from .openevolve_handoff import OpenEvolveHandoffError, admit_openevolve_result
        from .seed_handoff import SeedAdmissionError

        try:
            with tempfile.TemporaryDirectory(prefix="lunar-openevolve-") as temporary:
                external = Path(temporary)
                os.chmod(external, 0o700)
                config_path = external / "config.json"
                config_payload = {
                    "schema_version": "1",
                    "contract": self.context.contract.to_dict(),
                    "workspace": str(external),
                    "result_path": "result.json",
                    "producer": {
                        "id": "openevolve",
                        "fingerprint": self._producer_fingerprint(),
                    },
                    "budget": self._budget(),
                }
                config_text = json.dumps(
                    config_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                    allow_nan=False,
                ) + "\n"
                if len(config_text.encode("utf-8")) > MAX_SOURCE_BYTES:
                    return self._failed("openevolve_config_too_large")
                descriptor = os.open(
                    config_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
                    0o600,
                )
                try:
                    content = memoryview(config_text.encode("utf-8"))
                    written = 0
                    while written < len(content):
                        written += os.write(descriptor, content[written:])
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                producer_status = self._run_producer(external, config_path)
                if producer_status == "cancelled":
                    self._state("cancelled", 0, error="cancelled")
                    return self.archive.result(self.name, "cancelled", 0, "cancelled")
                if producer_status != "succeeded":
                    return self._failed(f"openevolve_command_{producer_status}")

                admitted = admit_openevolve_result(
                    external,
                    self.context.contract,
                    self.context.evaluate,
                    evaluator_fingerprint=evaluator_fingerprint,
                    producer_fingerprint=self._producer_fingerprint(),
                    staging_root=external / "admission",
                    num_islands=1,
                )
        except OSError:
            return self._failed("openevolve_workspace_failed")
        except OpenEvolveHandoffError:
            return self._failed("openevolve_result_invalid")
        except SeedAdmissionError:
            return self._failed("openevolve_local_evaluation_failed")

        state_payload = self._state_payload(
            "completed",
            1,
            error=None,
            best_candidate_id=admitted.candidate_id,
        )
        candidates = self.archive.commit_initial_seeds(
            (admitted,),
            state=state_payload,
            contract_sha256=self.context.contract.digest(),
            evaluator_fingerprint=self.config.evaluator_fingerprint,
            canonical_strategy="openevolve",
        )
        self._observe_seed_commit(candidates)
        return self.archive.result(self.name, "completed", 1)

    def resume(self) -> StrategyResult:
        return self.run()


def build_strategy(context: EvolutionContext) -> EvolutionStrategy:
    """Construct the strategy selected by an explicit context configuration."""

    if context.config.strategy == "population":
        return PopulationStrategy(context)
    if context.config.strategy == "openevolve":
        return OpenEvolveStrategy(context)
    raise ValueError(f"unsupported evolution strategy: {context.config.strategy}")


def config_from_contract(
    contract: AlgorithmProblemContract,
    *,
    population_size: int = 8,
    offspring_per_iteration: int = 1,
    num_islands: int = 1,
    migration_interval: int = 0,
    migration_rate: float = 0.1,
    rng_seed: int | None = None,
    timeout_seconds: float = 900.0,
    command: Sequence[str] = (),
    generator_fingerprint: str | None = None,
    evaluator_fingerprint: str | None = None,
) -> EvolutionConfig:
    """Map the persisted Feature 012 evolution choice to executable strategy knobs."""

    return EvolutionConfig(
        strategy=contract.evolution.strategy,
        max_rounds=contract.evolution.max_rounds,
        stagnation_rounds=contract.evolution.stagnation_rounds,
        population_size=population_size,
        offspring_per_iteration=offspring_per_iteration,
        num_islands=num_islands,
        migration_interval=migration_interval,
        migration_rate=migration_rate,
        rng_seed=rng_seed,
        timeout_seconds=timeout_seconds,
        command=tuple(command),
        generator_fingerprint=generator_fingerprint,
        evaluator_fingerprint=evaluator_fingerprint,
    )


__all__ = [
    "AdmittedSeedInput",
    "Candidate",
    "CandidateArchive",
    "CandidateDraft",
    "CandidateEvaluator",
    "CandidateExecution",
    "CandidateGenerator",
    "CandidateInputArtifact",
    "CandidateRunner",
    "CommandCandidateEvaluator",
    "CommandCandidateGenerator",
    "ContractCandidateRunner",
    "EvolutionConfig",
    "EvolutionContext",
    "EvolutionError",
    "EvolutionStrategy",
    "ExecutionAwareCandidateEvaluator",
    "GenerationRequest",
    "LoopStrategy",
    "OffspringOutcome",
    "OpenEvolveStrategy",
    "PopulationConfig",
    "PopulationState",
    "PopulationStrategy",
    "SeedEvidenceRecord",
    "StrategyResult",
    "WorkerUnknownError",
    "build_strategy",
    "config_from_contract",
    "contract_candidate_runner_fingerprint",
    "stage_candidate_inputs",
]
