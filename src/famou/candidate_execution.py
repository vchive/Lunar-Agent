"""Static, path-free admission for a future candidate execution."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import _benchmark_files as _files
from .algorithm import MAX_INPUT_FILE_BYTES, MAX_INPUT_FILES
from .candidate_workspace_plan import (
    CandidateWorkspaceError,
    CandidateWorkspacePlan,
    parse_candidate_workspace_plan,
    validate_candidate_workspace_plan,
)

EXECUTION_PROTOCOL = "lunar-candidate-execution-admission-v1"
EXECUTION_SCHEMA_VERSION = "1"
MAX_EXECUTION_ADMISSION_BYTES = 128 * 1024
MAX_EXECUTION_INPUTS = MAX_INPUT_FILES
MAX_EXECUTION_TARGET_BYTES = 1024
MAX_EXECUTION_SOURCE_LABEL_BYTES = 256
MAX_EXECUTION_TIMEOUT_SECONDS = 86_400.0
MAX_EXECUTION_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_EXECUTION_INPUT_BYTES = 16 * 1024 * 1024
MAX_EXECUTION_PROCESSES = 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SECRET = re.compile(r"(?i)(?:sk-[A-Za-z0-9_-]{8,}|bearer\s+[A-Za-z0-9._-]{8,}|api[_-]?key\s*[:=]\s*\S+|(?:password|secret|access[_-]?token|token)\s*[:=]\s*\S+)")


class CandidateExecutionError(ValueError):
    _CODES = frozenset({
        "candidate_execution_invalid", "candidate_execution_too_large", "candidate_execution_plan_mismatch",
        "candidate_execution_bundle_mismatch", "candidate_execution_contract_mismatch", "candidate_execution_input_invalid",
        "candidate_execution_input_missing", "candidate_execution_input_changed", "candidate_execution_input_unsafe",
        "candidate_execution_dependency_mismatch", "candidate_execution_environment_mismatch",
        "candidate_execution_evaluator_mismatch", "candidate_execution_output_contract_mismatch",
        "candidate_execution_budget_invalid", "candidate_execution_identity_mismatch",
    })
    def __init__(self, code: str) -> None:
        code = code if code.startswith("candidate_execution_") else "candidate_execution_" + code
        self.code = code if code in self._CODES else "candidate_execution_invalid"
        super().__init__(self.code)


def _fail(code: str) -> None:
    raise CandidateExecutionError(code)


def _digest(value: object, code: str = "invalid") -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(code)
    return value


def _canonical(value: object) -> bytes:
    try:
        content = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        _fail("invalid")
    if len(content) > MAX_EXECUTION_ADMISSION_BYTES:
        _fail("too_large")
    return content


def _text(value: object, maximum: int, code: str = "invalid") -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail(code)
    try:
        if len(value.encode("utf-8")) > maximum:
            _fail(code)
    except UnicodeEncodeError:
        _fail(code)
    return value


def _strict(value: object, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value) or set(value) != fields:
        _fail("invalid")
    return value


def _target(value: object) -> str:
    raw = _text(value, MAX_EXECUTION_TARGET_BYTES, "input_invalid")
    if "\\" in raw or ":" in raw or unicodedata.normalize("NFC", raw) != raw or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in raw):
        _fail("input_unsafe")
    path = Path(raw)
    if path.is_absolute() or path.as_posix() != raw or any(part in {"", ".", ".."} for part in path.parts):
        _fail("input_unsafe")
    return raw


def _label(value: object) -> str:
    raw = _text(value, MAX_EXECUTION_SOURCE_LABEL_BYTES, "input_invalid")
    if _SECRET.search(raw) or any(char in raw for char in "/\\:") or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in raw):
        _fail("input_invalid")
    return raw


@dataclass(frozen=True)
class CandidateExecutionInput:
    target: str
    source_label: str
    size: int
    sha256: str
    def __post_init__(self) -> None:
        object.__setattr__(self, "target", _target(self.target))
        object.__setattr__(self, "source_label", _label(self.source_label))
        if isinstance(self.size, bool) or not isinstance(self.size, int) or not 0 <= self.size <= MAX_INPUT_FILE_BYTES:
            _fail("input_invalid")
        object.__setattr__(self, "sha256", _digest(self.sha256, "input_invalid"))
    def to_dict(self) -> dict[str, object]:
        return {"target": self.target, "source_label": self.source_label, "size": self.size, "sha256": self.sha256}
    @classmethod
    def from_dict(cls, value: object) -> CandidateExecutionInput:
        item = _strict(value, {"target", "source_label", "size", "sha256"})
        return cls(item["target"], item["source_label"], item["size"], item["sha256"])


@dataclass(frozen=True)
class CandidateEvaluatorPin:
    kind: str
    fingerprint: str
    def __post_init__(self) -> None:
        kind = _text(self.kind, 256, "evaluator_mismatch")
        if _SECRET.search(kind) or any(char in kind for char in "/\\:=?&#%\n\r"):
            _fail("evaluator_mismatch")
        object.__setattr__(self, "kind", kind)
        _digest(self.fingerprint, "evaluator_mismatch")
    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "fingerprint": self.fingerprint}
    @classmethod
    def from_dict(cls, value: object) -> CandidateEvaluatorPin:
        item = _strict(value, {"kind", "fingerprint"})
        return cls(item["kind"], item["fingerprint"])


@dataclass(frozen=True)
class CandidateExecutionBudget:
    timeout_seconds: float
    max_output_bytes: int
    max_input_bytes: int
    max_processes: int
    def __post_init__(self) -> None:
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)):
            _fail("budget_invalid")
        try: timeout = float(self.timeout_seconds)
        except (TypeError, ValueError, OverflowError): _fail("budget_invalid")
        if not math.isfinite(timeout) or not 0 < timeout <= MAX_EXECUTION_TIMEOUT_SECONDS:
            _fail("budget_invalid")
        for value, maximum in ((self.max_output_bytes, MAX_EXECUTION_OUTPUT_BYTES), (self.max_input_bytes, MAX_EXECUTION_INPUT_BYTES), (self.max_processes, MAX_EXECUTION_PROCESSES)):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= maximum:
                _fail("budget_invalid")
        object.__setattr__(self, "timeout_seconds", timeout)
    def to_dict(self) -> dict[str, object]:
        return {"timeout_seconds": self.timeout_seconds, "max_output_bytes": self.max_output_bytes, "max_input_bytes": self.max_input_bytes, "max_processes": self.max_processes}
    @classmethod
    def from_dict(cls, value: object) -> CandidateExecutionBudget:
        item = _strict(value, {"timeout_seconds", "max_output_bytes", "max_input_bytes", "max_processes"})
        return cls(item["timeout_seconds"], item["max_output_bytes"], item["max_input_bytes"], item["max_processes"])


def _check_aliases(inputs: tuple[CandidateExecutionInput, ...]) -> None:
    seen: dict[str, tuple[str, bool]] = {}
    for item in inputs:
        parts = item.target.split("/")
        for depth in range(1, len(parts) + 1):
            prefix = "/".join(parts[:depth]); folded = unicodedata.normalize("NFC", prefix.casefold()); is_file = depth == len(parts)
            previous = seen.get(folded)
            if previous is not None and (previous[0] != prefix or previous[1] or is_file): _fail("input_unsafe")
            seen[folded] = (prefix, is_file)


@dataclass(frozen=True)
class CandidateExecutionAdmission:
    workspace_plan_sha256: str
    bundle_sha256: str
    contract_sha256: str
    inputs: tuple[CandidateExecutionInput, ...]
    dependency_sha256: str
    environment_sha256: str
    evaluator: CandidateEvaluatorPin
    output_contract_sha256: str | None
    budget: CandidateExecutionBudget
    schema_version: str = EXECUTION_SCHEMA_VERSION
    protocol: str = EXECUTION_PROTOCOL
    def __post_init__(self) -> None:
        if self.schema_version != EXECUTION_SCHEMA_VERSION or self.protocol != EXECUTION_PROTOCOL: _fail("invalid")
        _digest(self.workspace_plan_sha256, "plan_mismatch"); _digest(self.bundle_sha256, "bundle_mismatch"); _digest(self.contract_sha256, "contract_mismatch")
        _digest(self.dependency_sha256, "dependency_mismatch"); _digest(self.environment_sha256, "environment_mismatch")
        if not isinstance(self.evaluator, CandidateEvaluatorPin): _fail("evaluator_mismatch")
        if self.output_contract_sha256 is not None: _digest(self.output_contract_sha256, "output_contract_mismatch")
        if not isinstance(self.budget, CandidateExecutionBudget): _fail("budget_invalid")
        if not isinstance(self.inputs, (tuple, list)) or len(self.inputs) > MAX_EXECUTION_INPUTS or any(not isinstance(item, CandidateExecutionInput) for item in self.inputs): _fail("input_invalid")
        inputs = tuple(sorted(self.inputs, key=lambda item: item.target)); _check_aliases(inputs)
        if len({item.target for item in inputs}) != len(inputs): _fail("input_invalid")
        if sum(item.size for item in inputs) > self.budget.max_input_bytes: _fail("budget_invalid")
        object.__setattr__(self, "inputs", inputs); _canonical(self._canonical_dict())
    def _canonical_dict(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "protocol": self.protocol, "workspace_plan_sha256": self.workspace_plan_sha256, "bundle_sha256": self.bundle_sha256, "contract_sha256": self.contract_sha256, "inputs": [item.to_dict() for item in self.inputs], "dependency_sha256": self.dependency_sha256, "environment_sha256": self.environment_sha256, "evaluator": self.evaluator.to_dict(), "output_contract_sha256": self.output_contract_sha256, "budget": self.budget.to_dict()}
    @property
    def admission_sha256(self) -> str: return hashlib.sha256(_canonical(self._canonical_dict())).hexdigest()
    def digest(self) -> str: return self.admission_sha256
    def to_dict(self, *, include_admission_sha256: bool = True) -> dict[str, object]:
        result = self._canonical_dict()
        if include_admission_sha256: result["admission_sha256"] = self.admission_sha256
        return result
    @classmethod
    def from_dict(cls, value: object) -> CandidateExecutionAdmission:
        allowed = {"schema_version", "protocol", "workspace_plan_sha256", "bundle_sha256", "contract_sha256", "inputs", "dependency_sha256", "environment_sha256", "evaluator", "output_contract_sha256", "budget", "admission_sha256"}
        if not isinstance(value, dict) or set(value) - allowed or (allowed - {"admission_sha256"}) - set(value): _fail("invalid")
        if not isinstance(value["inputs"], list): _fail("input_invalid")
        parsed = cls(value["workspace_plan_sha256"], value["bundle_sha256"], value["contract_sha256"], tuple(CandidateExecutionInput.from_dict(item) for item in value["inputs"]), value["dependency_sha256"], value["environment_sha256"], CandidateEvaluatorPin.from_dict(value["evaluator"]), value["output_contract_sha256"], CandidateExecutionBudget.from_dict(value["budget"]), value["schema_version"], value["protocol"])
        if "admission_sha256" in value and value["admission_sha256"] != parsed.admission_sha256: _fail("identity_mismatch")
        return parsed


def validate_candidate_execution_admission(admission: CandidateExecutionAdmission) -> CandidateExecutionAdmission:
    if not isinstance(admission, CandidateExecutionAdmission): _fail("invalid")
    try: return CandidateExecutionAdmission.from_dict(admission.to_dict())
    except CandidateExecutionError: raise
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError, RecursionError): _fail("invalid")


def _validated_plan(value: CandidateWorkspacePlan | Mapping[str, object] | str | os.PathLike[str]) -> CandidateWorkspacePlan:
    try: return validate_candidate_workspace_plan(value if isinstance(value, CandidateWorkspacePlan) else parse_candidate_workspace_plan(value))
    except (CandidateWorkspaceError, AttributeError, KeyError, TypeError, ValueError, OverflowError, RecursionError): _fail("plan_mismatch")


def build_candidate_execution_admission(plan: CandidateWorkspacePlan | Mapping[str, object] | str | os.PathLike[str], *, inputs: tuple[CandidateExecutionInput, ...] | list[CandidateExecutionInput], dependency_sha256: str, environment_sha256: str, evaluator: CandidateEvaluatorPin | Mapping[str, object], output_contract_sha256: str | None = None, budget: CandidateExecutionBudget | Mapping[str, object], expected_plan_sha256: str | None = None, expected_bundle_sha256: str | None = None, expected_contract_sha256: str | None = None, expected_dependency_sha256: str | None = None, expected_environment_sha256: str | None = None, expected_evaluator: CandidateEvaluatorPin | Mapping[str, object] | None = None, expected_evaluator_sha256: str | None = None, expected_evaluator_kind: str | None = None, expected_output_contract_sha256: str | None = None) -> CandidateExecutionAdmission:
    parsed_plan = _validated_plan(plan); plan_digest = parsed_plan.digest(); bundle_digest = parsed_plan.bundle_sha256; contract_digest = parsed_plan.contract_sha256
    if expected_plan_sha256 is not None and _digest(expected_plan_sha256) != plan_digest: _fail("plan_mismatch")
    if expected_bundle_sha256 is not None and _digest(expected_bundle_sha256) != bundle_digest: _fail("bundle_mismatch")
    if expected_contract_sha256 is not None and _digest(expected_contract_sha256) != contract_digest: _fail("contract_mismatch")
    evaluator_pin = evaluator if isinstance(evaluator, CandidateEvaluatorPin) else CandidateEvaluatorPin.from_dict(dict(evaluator)); execution_budget = budget if isinstance(budget, CandidateExecutionBudget) else CandidateExecutionBudget.from_dict(dict(budget))
    dependency_digest = _digest(dependency_sha256, "dependency_mismatch"); environment_digest = _digest(environment_sha256, "environment_mismatch")
    if expected_dependency_sha256 is not None and _digest(expected_dependency_sha256, "dependency_mismatch") != dependency_digest: _fail("dependency_mismatch")
    if expected_environment_sha256 is not None and _digest(expected_environment_sha256, "environment_mismatch") != environment_digest: _fail("environment_mismatch")
    if expected_evaluator is not None and (expected_evaluator if isinstance(expected_evaluator, CandidateEvaluatorPin) else CandidateEvaluatorPin.from_dict(dict(expected_evaluator))) != evaluator_pin: _fail("evaluator_mismatch")
    if expected_evaluator_sha256 is not None and _digest(expected_evaluator_sha256, "evaluator_mismatch") != evaluator_pin.fingerprint: _fail("evaluator_mismatch")
    if expected_evaluator_kind is not None and expected_evaluator_kind != evaluator_pin.kind: _fail("evaluator_mismatch")
    if expected_output_contract_sha256 is not None and output_contract_sha256 != _digest(expected_output_contract_sha256, "output_contract_mismatch"): _fail("output_contract_mismatch")
    try: return CandidateExecutionAdmission(plan_digest, bundle_digest, contract_digest, tuple(inputs), dependency_digest, environment_digest, evaluator_pin, output_contract_sha256, execution_budget)
    except CandidateExecutionError: raise
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError, RecursionError): _fail("invalid")


@dataclass(frozen=True)
class VerifiedCandidateExecutionAdmission:
    admission: CandidateExecutionAdmission
    admission_sha256: str
    observed_inputs: tuple[CandidateExecutionInput, ...]
    def __post_init__(self) -> None:
        if not isinstance(self.admission, CandidateExecutionAdmission) or self.admission_sha256 != self.admission.admission_sha256: _fail("identity_mismatch")
        if tuple(self.observed_inputs) != self.admission.inputs: _fail("input_changed")
    @property
    def input_count(self) -> int: return len(self.observed_inputs)
    @property
    def total_input_bytes(self) -> int: return sum(item.size for item in self.observed_inputs)
    def to_dict(self) -> dict[str, object]: return {"admission": self.admission.to_dict(), "admission_sha256": self.admission_sha256, "input_count": self.input_count, "total_input_bytes": self.total_input_bytes}


def _verify_input(root: Path, item: CandidateExecutionInput) -> None:
    try: content = _files.read_regular_file(_files.absolute_path(root / item.target), item.size, exact_size=True)
    except _files.BenchmarkFileError as exc:
        _fail({"missing": "input_missing", "unsafe": "input_unsafe"}.get(exc.reason, "input_changed"))
    if len(content) != item.size or hashlib.sha256(content).hexdigest() != item.sha256: _fail("input_changed")


def admit_candidate_execution(admission: CandidateExecutionAdmission | Mapping[str, object] | str | os.PathLike[str], *, input_root: str | os.PathLike[str] | None = None, expected_admission_sha256: str | None = None) -> VerifiedCandidateExecutionAdmission:
    try:
        parsed = admission if isinstance(admission, CandidateExecutionAdmission) else CandidateExecutionAdmission.from_dict(dict(admission)) if isinstance(admission, Mapping) else parse_candidate_execution_admission(admission)
        parsed = validate_candidate_execution_admission(parsed)
    except CandidateExecutionError: raise
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError, RecursionError): _fail("invalid")
    if expected_admission_sha256 is not None and _digest(expected_admission_sha256) != parsed.admission_sha256: _fail("identity_mismatch")
    if input_root is None: return VerifiedCandidateExecutionAdmission(parsed, parsed.admission_sha256, parsed.inputs)
    try:
        root = _files.absolute_path(input_root)
        if not stat.S_ISDIR(root.lstat().st_mode): _fail("input_unsafe")
    except (OSError, _files.BenchmarkFileError): _fail("input_unsafe")
    for item in parsed.inputs: _verify_input(root, item)
    return VerifiedCandidateExecutionAdmission(parsed, parsed.admission_sha256, parsed.inputs)


def parse_candidate_execution_admission(source: str | os.PathLike[str] | Mapping[str, object]) -> CandidateExecutionAdmission:
    if isinstance(source, Mapping): return CandidateExecutionAdmission.from_dict(dict(source))
    try: content = _files.read_regular_file(_files.absolute_path(source), MAX_EXECUTION_ADMISSION_BYTES)
    except _files.BenchmarkFileError as exc: _fail("too_large" if exc.reason == "too_large" else "invalid")
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in items:
            if key in result: _fail("invalid")
            result[key] = item
        return result
    try: value = json.loads(content.decode("utf-8"), object_pairs_hook=pairs, parse_constant=lambda _: _fail("invalid"))
    except CandidateExecutionError: raise
    except (UnicodeDecodeError, ValueError, RecursionError): _fail("invalid")
    return CandidateExecutionAdmission.from_dict(value)


admit_candidate_execution_admission = admit_candidate_execution
__all__ = ["EXECUTION_PROTOCOL", "EXECUTION_SCHEMA_VERSION", "MAX_EXECUTION_ADMISSION_BYTES", "MAX_EXECUTION_INPUTS", "MAX_EXECUTION_INPUT_BYTES", "MAX_EXECUTION_OUTPUT_BYTES", "MAX_EXECUTION_PROCESSES", "MAX_EXECUTION_SOURCE_LABEL_BYTES", "MAX_EXECUTION_TARGET_BYTES", "MAX_EXECUTION_TIMEOUT_SECONDS", "CandidateEvaluatorPin", "CandidateExecutionAdmission", "CandidateExecutionBudget", "CandidateExecutionError", "CandidateExecutionInput", "VerifiedCandidateExecutionAdmission", "admit_candidate_execution", "admit_candidate_execution_admission", "build_candidate_execution_admission", "parse_candidate_execution_admission", "validate_candidate_execution_admission"]
