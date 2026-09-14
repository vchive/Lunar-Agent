"""Bounded offline benchmark/task envelopes for external algorithm frameworks.

This module defines the static identity exchanged by SkyDiscover/LLM4AD-style adapters.  It does
not launch a producer, model, evaluator, network client, or benchmark campaign.  Admission only
checks the pinned identities and verifies declared input bytes in a local workspace.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BENCHMARK_TASK_PROTOCOL = "lunar-benchmark-task-v1"
BENCHMARK_TASK_SCHEMA_VERSION = "1"
MAX_TASK_ENVELOPE_BYTES = 128 * 1024
MAX_TASK_INPUTS = 64
MAX_TASK_PATH_BYTES = 1024
MAX_TASK_ID_BYTES = 128
MAX_ATTEMPTS = 10_000
MAX_TIMEOUT_SECONDS = 86_400.0
MAX_TOTAL_TOKENS = 100_000_000_000
MAX_COST_MICROS = 1_000_000_000_000_000_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_OBJECT_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SECRET = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{8,}|bearer\s+[A-Za-z0-9._-]{8,}|"
    r"api[_-]?key\s*[:=]\s*\S+|(?:password|secret|access[_-]?token|token)\s*[:=]\s*\S+)"
)


class BenchmarkTaskError(ValueError):
    """A fixed-code task envelope or input admission failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise BenchmarkTaskError(code)


def _text(value: object, *, safe_id: bool = False, max_bytes: int = 8_000) -> str:
    if not isinstance(value, str) or not value:
        _fail("benchmark_task_envelope_invalid")
    try:
        if len(value.encode("utf-8")) > max_bytes:
            _fail("benchmark_task_envelope_invalid")
    except UnicodeEncodeError:
        _fail("benchmark_task_envelope_invalid")
    if "\x00" in value or _SECRET.search(value):
        _fail("benchmark_task_envelope_invalid")
    if safe_id and _SAFE_ID.fullmatch(value) is None:
        _fail("benchmark_task_envelope_invalid")
    return value


def _digest(value: object, *, prefixed: bool = False) -> str:
    pattern = _OBJECT_SHA256 if prefixed else _SHA256
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        _fail("benchmark_task_envelope_invalid")
    return value


def _relative_path(value: object) -> str:
    raw = _text(value, max_bytes=MAX_TASK_PATH_BYTES)
    if "\\" in raw:
        _fail("benchmark_task_envelope_invalid")
    path = Path(raw)
    if path.is_absolute() or raw != path.as_posix() or any(part in {"", ".", ".."} for part in path.parts):
        _fail("benchmark_task_envelope_invalid")
    return path.as_posix()


def _private_path(path: str) -> bool:
    parts = tuple(part.lower() for part in Path(path).parts)
    return bool(
        "tests" in parts
        or ".harness" in parts
        or parts[-1] in {"gt.json", "evaluator.py", "extractor_agent.py"}
    )


def _public_candidate_path(value: object) -> str:
    path = _relative_path(value)
    if _private_path(path) or Path(path).name.lower() == "extractor.py":
        _fail("benchmark_task_envelope_invalid")
    return path


def _strict_object(value: object, allowed: set[str], required: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        _fail("benchmark_task_envelope_invalid")
    if set(value) - allowed or required - set(value):
        _fail("benchmark_task_envelope_invalid")
    return value


def _canonical_bytes(value: object) -> bytes:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        result = encoded.encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        _fail("benchmark_task_envelope_invalid")
    if len(result) > MAX_TASK_ENVELOPE_BYTES:
        _fail("benchmark_task_envelope_too_large")
    if _SECRET.search(encoded):
        _fail("benchmark_task_envelope_invalid")
    return result


def _strict_loads(content: bytes) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                _fail("benchmark_task_envelope_invalid")
            result[key] = value
        return result

    def constant(_value: str) -> object:
        _fail("benchmark_task_envelope_invalid")

    try:
        return json.loads(content.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    except BenchmarkTaskError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        _fail("benchmark_task_envelope_invalid")


@dataclass(frozen=True)
class TaskInput:
    path: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        path = _relative_path(self.path)
        if _private_path(path):
            _fail("benchmark_task_envelope_invalid")
        if isinstance(self.size, bool) or not isinstance(self.size, int) or not 0 <= self.size <= 16 * 1024 * 1024:
            _fail("benchmark_task_envelope_invalid")
        digest = _digest(self.sha256)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "sha256", digest)

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "size": self.size, "sha256": self.sha256}

    @classmethod
    def from_dict(cls, value: object) -> TaskInput:
        item = _strict_object(value, {"path", "size", "sha256"}, {"path", "size", "sha256"})
        return cls(item["path"], item["size"], item["sha256"])  # type: ignore[arg-type]


@dataclass(frozen=True)
class TaskIdentity:
    key: str
    revision_id: str
    digest: str
    entrypoint: str | None = None

    def __post_init__(self) -> None:
        _text(self.key, safe_id=True, max_bytes=MAX_TASK_ID_BYTES)
        _text(self.revision_id, safe_id=True, max_bytes=MAX_TASK_ID_BYTES)
        _digest(self.digest, prefixed=True)
        if self.entrypoint is not None:
            _relative_path(self.entrypoint)

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"key": self.key, "revision_id": self.revision_id, "digest": self.digest}
        if self.entrypoint is not None:
            result["entrypoint"] = self.entrypoint
        return result

    @classmethod
    def from_dict(cls, value: object) -> TaskIdentity:
        item = _strict_object(value, {"key", "revision_id", "digest", "entrypoint"}, {"key", "revision_id", "digest"})
        entrypoint = item.get("entrypoint")
        if entrypoint is not None and not isinstance(entrypoint, str):
            _fail("benchmark_task_envelope_invalid")
        return cls(item["key"], item["revision_id"], item["digest"], entrypoint)  # type: ignore[arg-type]


@dataclass(frozen=True)
class ModelIdentity:
    requested: str
    profile_sha256: str | None = None

    def __post_init__(self) -> None:
        _text(self.requested, max_bytes=MAX_TASK_ID_BYTES)
        if self.profile_sha256 is not None:
            _digest(self.profile_sha256)

    def to_dict(self) -> dict[str, object]:
        return {"requested": self.requested, "profile_sha256": self.profile_sha256}

    @classmethod
    def from_dict(cls, value: object) -> ModelIdentity:
        item = _strict_object(value, {"requested", "profile_sha256"}, {"requested", "profile_sha256"})
        profile = item["profile_sha256"]
        if profile is not None and not isinstance(profile, str):
            _fail("benchmark_task_envelope_invalid")
        return cls(item["requested"], profile)  # type: ignore[arg-type]


@dataclass(frozen=True)
class EvaluatorIdentity:
    kind: str
    extractor_sha256: str
    evaluator_sha256: str

    def __post_init__(self) -> None:
        if self.kind != "exact_harness":
            _fail("benchmark_task_envelope_invalid")
        _digest(self.extractor_sha256)
        _digest(self.evaluator_sha256)

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "extractor_sha256": self.extractor_sha256, "evaluator_sha256": self.evaluator_sha256}

    @classmethod
    def from_dict(cls, value: object) -> EvaluatorIdentity:
        item = _strict_object(value, {"kind", "extractor_sha256", "evaluator_sha256"}, {"kind", "extractor_sha256", "evaluator_sha256"})
        return cls(item["kind"], item["extractor_sha256"], item["evaluator_sha256"])  # type: ignore[arg-type]


@dataclass(frozen=True)
class PhysicalAttemptBudget:
    attempts: int
    timeout_seconds: float
    max_total_tokens: int | None = None
    max_cost_micros: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.attempts, bool) or not isinstance(self.attempts, int) or not 1 <= self.attempts <= MAX_ATTEMPTS:
            _fail("benchmark_task_envelope_invalid")
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)) or not math.isfinite(float(self.timeout_seconds)) or not 0 < self.timeout_seconds <= MAX_TIMEOUT_SECONDS:
            _fail("benchmark_task_envelope_invalid")
        for value, maximum in ((self.max_total_tokens, MAX_TOTAL_TOKENS), (self.max_cost_micros, MAX_COST_MICROS)):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= maximum):
                _fail("benchmark_task_envelope_invalid")

    def to_dict(self) -> dict[str, object]:
        return {"attempts": self.attempts, "timeout_seconds": float(self.timeout_seconds), "max_total_tokens": self.max_total_tokens, "max_cost_micros": self.max_cost_micros}

    @classmethod
    def from_dict(cls, value: object) -> PhysicalAttemptBudget:
        item = _strict_object(value, {"attempts", "timeout_seconds", "max_total_tokens", "max_cost_micros"}, {"attempts", "timeout_seconds", "max_total_tokens", "max_cost_micros"})
        return cls(item["attempts"], item["timeout_seconds"], item["max_total_tokens"], item["max_cost_micros"])  # type: ignore[arg-type]


@dataclass(frozen=True)
class BenchmarkTaskEnvelope:
    benchmark: Mapping[str, object]
    task: TaskIdentity
    contract_sha256: str
    inputs: tuple[TaskInput, ...]
    model: ModelIdentity
    evaluator: EvaluatorIdentity
    candidate: Mapping[str, object]
    budget: PhysicalAttemptBudget
    schema_version: str = BENCHMARK_TASK_SCHEMA_VERSION
    protocol: str = BENCHMARK_TASK_PROTOCOL

    def __post_init__(self) -> None:
        if self.schema_version != BENCHMARK_TASK_SCHEMA_VERSION or self.protocol != BENCHMARK_TASK_PROTOCOL:
            _fail("benchmark_task_envelope_invalid")
        if not isinstance(self.benchmark, Mapping):
            _fail("benchmark_task_envelope_invalid")
        benchmark = dict(self.benchmark)
        _strict_object(benchmark, {"name", "release_version", "publication_digest"}, {"name", "release_version", "publication_digest"})
        _text(benchmark["name"], safe_id=True)
        _text(benchmark["release_version"], safe_id=True)
        _digest(benchmark["publication_digest"], prefixed=True)
        if not 1 <= len(self.inputs) <= MAX_TASK_INPUTS:
            _fail("benchmark_task_envelope_invalid")
        if any(not isinstance(item, TaskInput) for item in self.inputs) or len({item.path for item in self.inputs}) != len(self.inputs):
            _fail("benchmark_task_envelope_invalid")
        _digest(self.contract_sha256)
        candidate = dict(self.candidate) if isinstance(self.candidate, Mapping) else None
        if candidate is None:
            _fail("benchmark_task_envelope_invalid")
        _strict_object(candidate, {"kind", "filename"}, {"kind", "filename"})
        if candidate["kind"] != "single_file":
            _fail("benchmark_task_envelope_invalid")
        _public_candidate_path(candidate["filename"])
        object.__setattr__(self, "benchmark", benchmark)
        object.__setattr__(self, "candidate", candidate)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "protocol": self.protocol,
            "benchmark": dict(self.benchmark),
            "task": self.task.to_dict(),
            "contract_sha256": self.contract_sha256,
            "inputs": [item.to_dict() for item in sorted(self.inputs, key=lambda value: value.path)],
            "model": self.model.to_dict(),
            "evaluator": self.evaluator.to_dict(),
            "candidate": dict(self.candidate),
            "budget": self.budget.to_dict(),
        }

    def canonical_json(self) -> str:
        return _canonical_bytes(self.to_dict()).decode("utf-8")

    def digest(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def comparison_digest(self) -> str:
        payload = {
            "protocol": self.protocol,
            "task": self.task.to_dict(),
            "contract_sha256": self.contract_sha256,
            "input_manifest_sha256": _input_manifest_digest(self.inputs),
            "model": self.model.to_dict(),
            "evaluator": self.evaluator.to_dict(),
            "budget": self.budget.to_dict(),
        }
        return hashlib.sha256(_canonical_bytes(payload)).hexdigest()

    # Descriptive alias for callers that prefer an explicit SHA-256 suffix.
    comparison_sha256 = comparison_digest

    @classmethod
    def from_dict(cls, value: object) -> BenchmarkTaskEnvelope:
        item = _strict_object(value, {"schema_version", "protocol", "benchmark", "task", "contract_sha256", "inputs", "model", "evaluator", "candidate", "budget"}, {"schema_version", "protocol", "benchmark", "task", "contract_sha256", "inputs", "model", "evaluator", "candidate", "budget"})
        raw_inputs = item["inputs"]
        if not isinstance(raw_inputs, list):
            _fail("benchmark_task_envelope_invalid")
        return cls(
            item["benchmark"], TaskIdentity.from_dict(item["task"]), item["contract_sha256"],
            tuple(TaskInput.from_dict(value) for value in raw_inputs), ModelIdentity.from_dict(item["model"]),
            EvaluatorIdentity.from_dict(item["evaluator"]), item["candidate"], PhysicalAttemptBudget.from_dict(item["budget"]),
            item["schema_version"], item["protocol"],
        )  # type: ignore[arg-type]


def _input_manifest_digest(inputs: tuple[TaskInput, ...]) -> str:
    payload = [item.to_dict() for item in sorted(inputs, key=lambda value: value.path)]
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


@dataclass(frozen=True)
class AdmittedBenchmarkTask:
    envelope_sha256: str
    comparison_sha256: str
    contract_sha256: str
    inputs: tuple[TaskInput, ...]


def parse_benchmark_task_envelope(source: str | os.PathLike[str] | Mapping[str, object]) -> BenchmarkTaskEnvelope:
    """Parse one bounded strict JSON envelope or mapping without executing anything."""
    if isinstance(source, Mapping):
        envelope = BenchmarkTaskEnvelope.from_dict(dict(source))
        _canonical_bytes(envelope.to_dict())
        return envelope
    path = Path(source).expanduser()
    if path.is_symlink() or not path.is_file():
        _fail("benchmark_task_envelope_invalid")
    try:
        content = path.read_bytes()
    except OSError:
        _fail("benchmark_task_envelope_invalid")
    if not content or len(content) > MAX_TASK_ENVELOPE_BYTES:
        _fail("benchmark_task_envelope_too_large")
    return BenchmarkTaskEnvelope.from_dict(_strict_loads(content))


def _verify_input(root: Path, item: TaskInput) -> None:
    raw = root / item.path
    current = raw
    while current != root:
        if current.is_symlink():
            _fail("benchmark_task_input_unsafe")
        current = current.parent
    try:
        resolved = raw.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, ValueError):
        _fail("benchmark_task_input_unsafe")
    if raw.is_symlink() or not resolved.is_file():
        _fail("benchmark_task_input_missing")
    try:
        descriptor = resolved.stat()
        if not stat.S_ISREG(descriptor.st_mode):
            _fail("benchmark_task_input_unsafe")
        if descriptor.st_size > 16 * 1024 * 1024:
            _fail("benchmark_task_input_changed")
        with resolved.open("rb") as stream:
            content = stream.read(item.size + 1)
    except OSError:
        _fail("benchmark_task_input_missing")
    if len(content) != item.size:
        _fail("benchmark_task_input_changed")
    if hashlib.sha256(content).hexdigest() != item.sha256:
        _fail("benchmark_task_input_changed")


def admit_benchmark_task_envelope(
    envelope: BenchmarkTaskEnvelope | Mapping[str, object] | str | os.PathLike[str],
    *,
    contract_sha256: str,
    input_root: str | os.PathLike[str],
    model_profile_sha256: str | None = None,
    evaluator_sha256: str | None = None,
    evaluator_fingerprint: str | None = None,
    budget: PhysicalAttemptBudget | Mapping[str, object] | None = None,
) -> AdmittedBenchmarkTask:
    """Verify pinned identities and input bytes; never run a producer/model/evaluator."""
    parsed = envelope if isinstance(envelope, BenchmarkTaskEnvelope) else parse_benchmark_task_envelope(envelope)
    expected_contract = _digest(contract_sha256)
    if parsed.contract_sha256 != expected_contract:
        _fail("benchmark_task_contract_mismatch")
    if (parsed.model.profile_sha256 is None) != (model_profile_sha256 is None) or (
        parsed.model.profile_sha256 is not None
        and _digest(model_profile_sha256) != parsed.model.profile_sha256
    ):
        _fail("benchmark_task_model_mismatch")
    expected_evaluator = evaluator_sha256 if evaluator_sha256 is not None else evaluator_fingerprint
    if expected_evaluator is None or _digest(expected_evaluator) != parsed.evaluator.evaluator_sha256:
        _fail("benchmark_task_evaluator_mismatch")
    if budget is not None:
        expected_budget = budget if isinstance(budget, PhysicalAttemptBudget) else PhysicalAttemptBudget.from_dict(dict(budget))
        if expected_budget != parsed.budget:
            _fail("benchmark_task_budget_mismatch")
    raw_root = Path(input_root).expanduser()
    if raw_root.is_symlink() or not raw_root.is_dir():
        _fail("benchmark_task_input_unsafe")
    root = raw_root.resolve(strict=False)
    for item in parsed.inputs:
        _verify_input(root, item)
    return AdmittedBenchmarkTask(parsed.digest(), parsed.comparison_digest(), parsed.contract_sha256, parsed.inputs)


__all__ = [
    "BENCHMARK_TASK_PROTOCOL",
    "BENCHMARK_TASK_SCHEMA_VERSION",
    "AdmittedBenchmarkTask",
    "BenchmarkTaskEnvelope",
    "BenchmarkTaskError",
    "EvaluatorIdentity",
    "ModelIdentity",
    "PhysicalAttemptBudget",
    "TaskIdentity",
    "TaskInput",
    "admit_benchmark_task_envelope",
    "parse_benchmark_task_envelope",
]
