"""Local, runtime-neutral evolution strategies.

The strategy layer deliberately knows nothing about Hermes, OpenCode, Codex, or a remote service.
It consumes an algorithm contract, an injected candidate generator, and an injected evaluator.  The
native loop and population implementations share an append-only candidate archive; OpenEvolve is an
optional subprocess adapter rather than a package dependency.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import signal
import subprocess
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from .algorithm import EVOLUTION_STRATEGIES, AlgorithmProblemContract, EvaluationReport

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
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SECRET_OUTPUT = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._-]{12,}|"
    r"api[_-]?key\s*[:=]\s*\S+)"
)


class EvolutionError(RuntimeError):
    """A bounded, actionable strategy error."""


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
        if current.exists() and current.is_symlink():
            raise EvolutionError(f"{field_name} must not contain a symlink")
        current = current.parent


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


@dataclass(frozen=True)
class EvolutionConfig:
    """Explicit, bounded knobs shared by all strategies."""

    strategy: Literal["loop", "population", "openevolve"] = "loop"
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
        if self.strategy not in EVOLUTION_STRATEGIES:
            raise ValueError("strategy must be loop, population, or openevolve")
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
        if self.strategy == "openevolve" and not self.command:
            raise ValueError("openevolve strategy requires an explicit command")

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
    """Population-only knobs kept separate for callers that do not need loop settings."""

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

    def __init__(self, command: Sequence[str], timeout_seconds: float = 900.0) -> None:
        command = tuple(command)
        if not command or len(command) > MAX_COMMAND_ARGS:
            raise ValueError("evaluator command must be a non-empty bounded argument sequence")
        executable = Path(command[0])
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            raise ValueError("evaluator command must start with an existing absolute executable path")
        self.command = command
        self.timeout_seconds = timeout_seconds

    def __call__(self, candidate_path: Path, contract: AlgorithmProblemContract) -> EvaluationReport:
        del contract
        try:
            completed = subprocess.run(
                [*self.command, str(candidate_path)],
                cwd=candidate_path.parent,
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


class CandidateArchive:
    """Append-only candidate records and atomic strategy state for one run."""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        if self.workspace.is_symlink():
            raise EvolutionError("evolution workspace must not be a symlink")
        self.root = self.workspace / "evolution"
        self.candidates_root = self.root / "candidates"
        self.archive_path = self.root / "archive.jsonl"
        self.state_path = self.root / "state.json"
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
        strategy: Literal["loop", "population", "openevolve"],
        iteration: int,
        generation: int,
        parent_id: str | None = None,
        island_id: int | None = None,
        evaluation: EvaluationReport,
    ) -> Candidate:
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

    def best(self) -> Candidate | None:
        valid = [candidate for candidate in self.records() if candidate.evaluation.validity == 1]
        if not valid:
            return None
        return max(valid, key=lambda candidate: candidate.evaluation.combined_score)

    def write_state(self, payload: dict[str, Any]) -> None:
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
        try:
            report = _report(self.evaluator(candidate, contract))
        except Exception as exc:  # noqa: BLE001 - evaluator failures are invalid evidence
            return _invalid_report(exc)
        if execution.status != "succeeded":
            detail = execution.error or f"execution_{execution.status}"
            return _invalid_report(detail)
        return report


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
    name: Literal["loop", "population", "openevolve"]

    def __init__(self, context: EvolutionContext) -> None:
        self.context = context
        self.archive = CandidateArchive(context.workspace)
        self.config = context.config

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
        evaluation_override: EvaluationReport | None = None,
    ) -> Candidate:
        candidate_id = self.archive.next_id()
        path = self.archive.candidate_source_path(candidate_id, draft.filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(draft.source, encoding="utf-8")
        try:
            evaluation = evaluation_override or _report(self.context.evaluate(path, self.context.contract))
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

    def _state(self, status: str, iteration: int, **extra: Any) -> None:
        payload = {
            "schema_version": "1",
            "strategy": self.name,
            "status": status,
            "iteration": iteration,
            "contract_sha256": self.context.contract.digest(),
            "config": self.config.to_dict(),
            **extra,
        }
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


class LoopStrategy(_BaseStrategy):
    """WebAgent-style independent rounds with an archive-as-population."""

    name: Literal["loop"] = "loop"

    def run(self) -> StrategyResult:
        state = self._load_state()
        terminal = self._terminal(state)
        if terminal:
            return terminal
        iteration = int(state.get("iteration", 0))
        stagnation = int(state.get("stagnation", 0))
        error: str | None = state.get("error")
        previous_best = self.archive.best()
        previous_score = previous_best.evaluation.combined_score if previous_best else None

        while iteration < self.config.max_rounds:
            if self._cancelled():
                self._state("cancelled", iteration, stagnation=stagnation, error="cancelled")
                return self.archive.result(self.name, "cancelled", iteration, "cancelled")
            iteration += 1
            parent = self.archive.best()
            request = GenerationRequest(
                iteration=iteration,
                parent=parent,
                inspirations=(),
                archive=tuple(self.archive.records()),
                workspace=self.context.workspace,
            )
            try:
                drafts = _drafts(self.context.generate(request))
            except Exception as exc:  # noqa: BLE001 - generator is an injected boundary
                drafts = ()
                error = _bounded_error(exc)
            for draft in drafts:
                self._persist(
                    draft,
                    iteration=iteration,
                    generation=(parent.generation + 1 if parent else 0),
                    parent=parent,
                    island_id=None,
                )
            current_best = self.archive.best()
            current_score = current_best.evaluation.combined_score if current_best else None
            if current_score is not None and (previous_score is None or current_score > previous_score):
                stagnation = 0
            else:
                stagnation += 1
            previous_score = current_score
            self._state("running", iteration, stagnation=stagnation, error=error)
            if stagnation >= self.config.stagnation_rounds:
                self._state("stagnated", iteration, stagnation=stagnation, error=error)
                return self.archive.result(self.name, "stagnated", iteration, error)

        status = "completed" if self.archive.best() is not None else "failed"
        self._state(status, iteration, stagnation=stagnation, error=error or ("no valid candidate" if status == "failed" else None))
        return self.archive.result(self.name, status, iteration, error or ("no valid candidate" if status == "failed" else None))

    def resume(self) -> StrategyResult:
        return self.run()


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

    def _capacity(self, island: int) -> int:
        base, remainder = divmod(self.config.population_size, self.config.num_islands)
        return base + (1 if island < remainder else 0)

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
            ),
            reverse=True,
        )

    def _trim(self, active: dict[int, list[str]]) -> None:
        all_active = self._candidates(item for ids in active.values() for item in ids)
        for island in range(self.config.num_islands):
            candidates = self._candidates(active[island])
            ranked = self._rank(candidates, all_active)
            active[island] = [item.candidate_id for item in ranked[: self._capacity(island)]]

    def _select_parent(self, active: dict[int, list[str]], island: int) -> Candidate | None:
        candidates = self._candidates(active[island])
        if not candidates:
            candidates = self._candidates(item for ids in active.values() for item in ids)
        if not candidates:
            return None
        ranked = self._rank(candidates, self._candidates(item for ids in active.values() for item in ids))
        return self.rng.choice(ranked[: min(3, len(ranked))])

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
        ranked = sorted(
            candidates,
            key=lambda item: _novelty(item, [parent] if parent else (), self.context.workspace),
            reverse=True,
        )
        return tuple(ranked[:2])

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
        state = self._load_state()
        terminal = self._terminal(state)
        if terminal:
            return terminal
        active = self._active(state)
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
                    except Exception as exc:  # noqa: BLE001 - generator/evaluator boundary
                        error = _bounded_error(exc)
                self._trim(active)
        best_score = self.archive.best().evaluation.combined_score if self.archive.best() else None
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

        while iteration < self.config.max_rounds:
            if self._cancelled():
                self._state("cancelled", iteration, active_ids={str(k): v for k, v in active.items()}, stagnation=stagnation, error="cancelled")
                return self.archive.result(self.name, "cancelled", iteration, "cancelled")
            iteration += 1
            for offset in range(self.config.offspring_per_iteration):
                island = offset % self.config.num_islands
                parent = self._select_parent(active, island)
                request = GenerationRequest(
                    iteration=iteration,
                    parent=parent,
                    inspirations=self._inspirations(active, island, parent),
                    archive=tuple(self.archive.records()),
                    workspace=self.context.workspace,
                )
                try:
                    draft = _drafts(self.context.generate(request))[0]
                    child = self._persist(
                        draft,
                        iteration=iteration,
                        generation=(parent.generation + 1 if parent else 0),
                        parent=parent,
                        island_id=island,
                    )
                    active[island].append(child.candidate_id)
                except Exception as exc:  # noqa: BLE001 - generator/evaluator boundary
                    error = _bounded_error(exc)
            self._trim(active)
            if self._migrate(active, iteration):
                migration_watermark = iteration
            current = self.archive.best()
            current_score = current.evaluation.combined_score if current else None
            if current_score is not None and (best_score is None or current_score > best_score):
                best_score = current_score
                stagnation = 0
            else:
                stagnation += 1
            self._state(
                "running",
                iteration,
                active_ids={str(k): v for k, v in active.items()},
                stagnation=stagnation,
                error=error,
                best_candidate_id=current.candidate_id if current else None,
                rng_seed=self.config.rng_seed,
                last_migration_iteration=migration_watermark,
            )
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
    """Run an explicitly configured local OpenEvolve command and import one result."""

    name: Literal["openevolve"] = "openevolve"

    def _external_root(self) -> Path:
        root = self.archive.root / "external" / "openevolve"
        if root.exists() and root.is_symlink():
            raise EvolutionError("OpenEvolve adapter directory must not be a symlink")
        root.mkdir(parents=True, exist_ok=True)
        return root

    def run(self) -> StrategyResult:
        state = self._load_state()
        terminal = self._terminal(state)
        if terminal:
            return terminal
        command = self.config.command
        executable = Path(command[0])
        if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
            error = "OpenEvolve command must start with an existing absolute executable path"
            self._state("failed", 0, error=error)
            return self.archive.result(self.name, "failed", 0, error)
        if self._cancelled():
            self._state("cancelled", 0, error="cancelled")
            return self.archive.result(self.name, "cancelled", 0, "cancelled")
        external = self._external_root()
        config_path = external / "config.json"
        result_path = external / "result.json"
        if config_path.exists() and config_path.is_symlink():
            error = "OpenEvolve config path must not be a symlink"
            self._state("failed", 0, error=error)
            return self.archive.result(self.name, "failed", 0, error)
        config_payload = {
            "schema_version": "1",
            "contract": self.context.contract.to_dict(),
            "workspace": str(external),
            "result_path": "result.json",
        }
        config_path.write_text(json.dumps(config_payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        try:
            completed = subprocess.run(
                [*command, str(config_path)],
                cwd=external,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=self.config.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            error = f"OpenEvolve command timed out after {self.config.timeout_seconds:g}s"
            self._state("failed", 0, error=error)
            return self.archive.result(self.name, "failed", 0, error)
        except OSError as exc:
            error = _bounded_error(exc)
            self._state("failed", 0, error=error)
            return self.archive.result(self.name, "failed", 0, error)
        if completed.returncode != 0:
            detail = _bounded_error(completed.stderr or completed.stdout or f"exit code {completed.returncode}")
            self._state("failed", 0, error=detail)
            return self.archive.result(self.name, "failed", 0, detail)
        if not result_path.is_file() or result_path.is_symlink() or result_path.stat().st_size > MAX_EXTERNAL_RESULT_BYTES:
            error = "OpenEvolve did not produce a bounded result.json"
            self._state("failed", 0, error=error)
            return self.archive.result(self.name, "failed", 0, error)
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise EvolutionError("OpenEvolve result must be an object")
            relative = _safe_relative_path(payload.get("candidate_path"), "OpenEvolve candidate path")
            source_path = _confined(external, external / relative, "OpenEvolve candidate path")
            if not source_path.is_file() or source_path.is_symlink():
                raise EvolutionError("OpenEvolve candidate path is not a regular file")
            source = source_path.read_text(encoding="utf-8")
            draft = CandidateDraft(source=source, filename=source_path.name, metadata={"source": "openevolve"})
            raw_evaluation = payload.get("evaluation")
            evaluation = _report(raw_evaluation) if raw_evaluation is not None else None
            candidate = self._persist(draft, iteration=1, generation=0, parent=None, island_id=None, evaluation_override=evaluation)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, EvolutionError, TypeError, ValueError) as exc:
            error = _bounded_error(exc)
            self._state("failed", 0, error=error)
            return self.archive.result(self.name, "failed", 0, error)
        status = "completed" if candidate.evaluation.validity == 1 else "failed"
        error = None if status == "completed" else "OpenEvolve produced no valid candidate"
        self._state(status, 1, error=error)
        return self.archive.result(self.name, status, 1, error)

    def resume(self) -> StrategyResult:
        return self.run()


def build_strategy(context: EvolutionContext) -> EvolutionStrategy:
    """Construct the strategy selected by an explicit context configuration."""

    if context.config.strategy == "loop":
        return LoopStrategy(context)
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
    "Candidate",
    "CandidateArchive",
    "CandidateDraft",
    "CandidateEvaluator",
    "CandidateGenerator",
    "CommandCandidateEvaluator",
    "CommandCandidateGenerator",
    "EvolutionConfig",
    "EvolutionContext",
    "EvolutionError",
    "EvolutionStrategy",
    "GenerationRequest",
    "LoopStrategy",
    "OpenEvolveStrategy",
    "PopulationConfig",
    "PopulationState",
    "PopulationStrategy",
    "StrategyResult",
    "build_strategy",
    "config_from_contract",
]
