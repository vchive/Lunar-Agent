"""Static, path-free admission for a future candidate execution.

Only optional input-byte verification reads the filesystem. Neither parsing nor admission starts
a process, imports candidate code, resolves packages, inspects the host, or calls an evaluator.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from . import _benchmark_files as _files
from ._candidate_workspace_io import DirectoryChain
from .algorithm import MAX_INPUT_FILE_BYTES, MAX_INPUT_FILES
from .candidate_bundle import CandidateBundleError, CandidateSourceBundle
from .candidate_workspace_plan import (
    CandidateWorkspaceError,
    CandidateWorkspacePlan,
    validate_candidate_workspace_plan,
)

CANDIDATE_EXECUTION_PROTOCOL = "lunar-candidate-execution-admission-v1"
CANDIDATE_EXECUTION_SCHEMA_VERSION = "1"
EXECUTION_PROTOCOL = CANDIDATE_EXECUTION_PROTOCOL
EXECUTION_SCHEMA_VERSION = CANDIDATE_EXECUTION_SCHEMA_VERSION
MAX_EXECUTION_ADMISSION_BYTES = 128 * 1024
MAX_EXECUTION_INPUTS = MAX_INPUT_FILES
MAX_EXECUTION_TARGET_BYTES = 1024
MAX_EXECUTION_SOURCE_LABEL_BYTES = 256
MAX_EXECUTION_EVALUATOR_KIND_BYTES = 128
MAX_EXECUTION_TIMEOUT_SECONDS = 86_400.0
MAX_EXECUTION_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_EXECUTION_INPUT_BYTES = 16 * 1024 * 1024
MAX_EXECUTION_PROCESSES = 1024
SOURCE_ONLY_EVALUATOR_KIND = "source-only"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_KIND = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
_SECRET = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{8,}|bearer\s+[A-Za-z0-9._-]{8,}|"
    r"api[_-]?key\s*[:=]\s*\S+|(?:password|secret|access[_-]?token|token)\s*[:=]\s*\S+)"
)
_UNSET = object()
_FIELDS = {
    "schema_version", "protocol", "workspace_plan_sha256", "bundle_sha256",
    "contract_sha256", "inputs", "dependency_sha256", "environment_sha256",
    "evaluator", "output_contract_sha256", "budget",
}


class CandidateExecutionError(ValueError):
    """A fixed public code; no exception text carries a caller-controlled value."""

    _CODES = frozenset({
        "invalid", "too_large", "plan_mismatch", "bundle_mismatch", "contract_mismatch",
        "input_invalid", "input_missing", "input_changed", "input_unsafe",
        "dependency_mismatch", "environment_mismatch", "evaluator_mismatch",
        "output_contract_mismatch", "budget_invalid", "identity_mismatch",
    })

    def __init__(self, code: str) -> None:
        suffix = code.removeprefix("candidate_execution_") if isinstance(code, str) else ""
        self.code = "candidate_execution_" + (suffix if suffix in self._CODES else "invalid")
        super().__init__(self.code)


def _fail(code: str) -> NoReturn:
    raise CandidateExecutionError(code)


def _digest(value: object, code: str = "invalid") -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(code)
    return value


def _commitment(value: object, code: str) -> str:
    digest = _digest(value, code)
    if digest == "0" * 64:
        _fail(code)
    return digest


def _canonical(value: object) -> bytes:
    try:
        content = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        _fail("invalid")
    if len(content) > MAX_EXECUTION_ADMISSION_BYTES:
        _fail("too_large")
    return content


def _text(value: object, maximum: int, code: str) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        _fail(code)
    try:
        if len(value.encode("utf-8")) > maximum:
            _fail(code)
    except UnicodeEncodeError:
        _fail(code)
    return value


def _strict(value: object, fields: set[str], code: str = "invalid") -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or any(not isinstance(key, str) for key in value)
        or set(value) != fields
    ):
        _fail(code)
    return value


def _target(value: object) -> str:
    raw = _text(value, MAX_EXECUTION_TARGET_BYTES, "input_invalid")
    if (
        "\\" in raw or ":" in raw
        or unicodedata.normalize("NFC", raw) != raw
        or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in raw)
        or any(part in {"", ".", ".."} or part.casefold() == ".git" for part in raw.split("/"))
    ):
        _fail("input_unsafe")
    return raw


def _identifier(value: object, *, evaluator: bool = False) -> str:
    maximum = MAX_EXECUTION_EVALUATOR_KIND_BYTES if evaluator else MAX_EXECUTION_SOURCE_LABEL_BYTES
    code = "evaluator_mismatch" if evaluator else "input_invalid"
    raw = _text(value, maximum, code)
    pattern = _KIND if evaluator else _LABEL
    if pattern.fullmatch(raw) is None or _SECRET.search(raw):
        _fail(code)
    return raw


@dataclass(frozen=True)
class CandidateExecutionInput:
    """A logical destination and opaque label; it never contains a host source path."""

    target: str
    source_label: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        _target(self.target)
        _identifier(self.source_label)
        if (
            isinstance(self.size, bool) or not isinstance(self.size, int)
            or not 0 <= self.size <= MAX_INPUT_FILE_BYTES
        ):
            _fail("input_invalid")
        _digest(self.sha256, "input_invalid")

    def to_dict(self) -> dict[str, object]:
        item = _copy_input(self)
        return _input_dict(item)

    @classmethod
    def from_dict(cls, value: object) -> CandidateExecutionInput:
        item = _strict(value, {"target", "source_label", "size", "sha256"}, "input_invalid")
        return cls(item["target"], item["source_label"], item["size"], item["sha256"])


def _input_dict(item: CandidateExecutionInput) -> dict[str, object]:
    return {"target": item.target, "source_label": item.source_label, "size": item.size, "sha256": item.sha256}


def _copy_input(value: object) -> CandidateExecutionInput:
    try:
        if not isinstance(value, CandidateExecutionInput):
            _fail("input_invalid")
        return CandidateExecutionInput(value.target, value.source_label, value.size, value.sha256)
    except (AttributeError, TypeError, OverflowError, RecursionError):
        _fail("input_invalid")


def _inputs(value: object) -> tuple[CandidateExecutionInput, ...]:
    if not isinstance(value, (tuple, list)) or len(value) > MAX_EXECUTION_INPUTS:
        _fail("input_invalid")
    inputs = tuple(sorted((_copy_input(item) for item in value), key=lambda item: item.target))
    nodes: dict[str, tuple[str, bool]] = {}
    for item in inputs:
        parts = item.target.split("/")
        for depth in range(1, len(parts) + 1):
            prefix = "/".join(parts[:depth])
            folded = unicodedata.normalize("NFC", prefix.casefold())
            is_file = depth == len(parts)
            previous = nodes.get(folded)
            if previous is not None and (previous[0] != prefix or previous[1] or is_file):
                _fail("input_unsafe")
            nodes[folded] = (prefix, is_file)
    return inputs


@dataclass(frozen=True)
class CandidateEvaluatorPin:
    kind: str
    fingerprint: str

    def __post_init__(self) -> None:
        _identifier(self.kind, evaluator=True)
        _digest(self.fingerprint, "evaluator_mismatch")

    def to_dict(self) -> dict[str, str]:
        pin = _copy_evaluator(self)
        return {"kind": pin.kind, "fingerprint": pin.fingerprint}

    @classmethod
    def from_dict(cls, value: object) -> CandidateEvaluatorPin:
        item = _strict(value, {"kind", "fingerprint"}, "evaluator_mismatch")
        return cls(item["kind"], item["fingerprint"])


def _copy_evaluator(value: object) -> CandidateEvaluatorPin:
    try:
        if isinstance(value, CandidateEvaluatorPin):
            return CandidateEvaluatorPin(value.kind, value.fingerprint)
        if isinstance(value, Mapping):
            return CandidateEvaluatorPin.from_dict(dict(value))
        _fail("evaluator_mismatch")
    except (AttributeError, TypeError, OverflowError, RecursionError):
        _fail("evaluator_mismatch")


@dataclass(frozen=True)
class CandidateExecutionBudget:
    timeout_seconds: float
    max_output_bytes: int
    max_input_bytes: int
    max_processes: int

    def __post_init__(self) -> None:
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)):
            _fail("budget_invalid")
        try:
            timeout = float(self.timeout_seconds)
        except (ValueError, OverflowError):
            _fail("budget_invalid")
        if not math.isfinite(timeout) or not 0 < timeout <= MAX_EXECUTION_TIMEOUT_SECONDS:
            _fail("budget_invalid")
        for value, maximum in (
            (self.max_output_bytes, MAX_EXECUTION_OUTPUT_BYTES),
            (self.max_input_bytes, MAX_EXECUTION_INPUT_BYTES),
            (self.max_processes, MAX_EXECUTION_PROCESSES),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= maximum:
                _fail("budget_invalid")
        object.__setattr__(self, "timeout_seconds", timeout)

    def to_dict(self) -> dict[str, object]:
        return _budget_dict(_copy_budget(self))

    @classmethod
    def from_dict(cls, value: object) -> CandidateExecutionBudget:
        item = _strict(
            value, {"timeout_seconds", "max_output_bytes", "max_input_bytes", "max_processes"},
            "budget_invalid",
        )
        return cls(item["timeout_seconds"], item["max_output_bytes"], item["max_input_bytes"], item["max_processes"])


def _budget_dict(budget: CandidateExecutionBudget) -> dict[str, object]:
    return {
        "timeout_seconds": budget.timeout_seconds, "max_output_bytes": budget.max_output_bytes,
        "max_input_bytes": budget.max_input_bytes, "max_processes": budget.max_processes,
    }


def _copy_budget(value: object) -> CandidateExecutionBudget:
    try:
        if isinstance(value, CandidateExecutionBudget):
            return CandidateExecutionBudget(
                value.timeout_seconds, value.max_output_bytes, value.max_input_bytes, value.max_processes,
            )
        if isinstance(value, Mapping):
            return CandidateExecutionBudget.from_dict(dict(value))
        _fail("budget_invalid")
    except (AttributeError, TypeError, OverflowError, RecursionError):
        _fail("budget_invalid")


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
        if self.schema_version != EXECUTION_SCHEMA_VERSION or self.protocol != EXECUTION_PROTOCOL:
            _fail("invalid")
        _digest(self.workspace_plan_sha256, "plan_mismatch")
        _digest(self.bundle_sha256, "bundle_mismatch")
        _digest(self.contract_sha256, "contract_mismatch")
        _commitment(self.dependency_sha256, "dependency_mismatch")
        _commitment(self.environment_sha256, "environment_mismatch")
        evaluator = _copy_evaluator(self.evaluator)
        budget = _copy_budget(self.budget)
        inputs = _inputs(self.inputs)
        if self.output_contract_sha256 is None:
            if evaluator.kind != SOURCE_ONLY_EVALUATOR_KIND:
                _fail("output_contract_mismatch")
        else:
            _digest(self.output_contract_sha256, "output_contract_mismatch")
        if sum(item.size for item in inputs) > budget.max_input_bytes:
            _fail("budget_invalid")
        object.__setattr__(self, "inputs", inputs)
        object.__setattr__(self, "evaluator", evaluator)
        object.__setattr__(self, "budget", budget)
        # The returned envelope adds a fixed-size self digest. Reserve those bytes now so every
        # successfully constructed declaration can be serialized and parsed again at the limit.
        _canonical({**_admission_dict(self), "admission_sha256": "0" * 64})

    def to_dict(self, *, include_admission_sha256: bool = True) -> dict[str, object]:
        parsed = validate_candidate_execution_admission(self)
        result = _admission_dict(parsed)
        if include_admission_sha256:
            result["admission_sha256"] = hashlib.sha256(_canonical(result)).hexdigest()
        return result

    def digest(self) -> str:
        parsed = validate_candidate_execution_admission(self)
        return hashlib.sha256(_canonical(_admission_dict(parsed))).hexdigest()

    @property
    def admission_sha256(self) -> str:
        return self.digest()

    @classmethod
    def from_dict(cls, value: object) -> CandidateExecutionAdmission:
        if not isinstance(value, dict):
            _fail("invalid")
        has_digest = "admission_sha256" in value
        item = _strict(value, _FIELDS | ({"admission_sha256"} if has_digest else set()))
        raw_inputs = item["inputs"]
        if not isinstance(raw_inputs, list) or len(raw_inputs) > MAX_EXECUTION_INPUTS:
            _fail("input_invalid")
        _canonical(item)
        parsed = cls(
            item["workspace_plan_sha256"], item["bundle_sha256"], item["contract_sha256"],
            tuple(CandidateExecutionInput.from_dict(entry) for entry in raw_inputs),
            item["dependency_sha256"], item["environment_sha256"],
            CandidateEvaluatorPin.from_dict(item["evaluator"]), item["output_contract_sha256"],
            CandidateExecutionBudget.from_dict(item["budget"]), item["schema_version"], item["protocol"],
        )
        if has_digest and _digest(item["admission_sha256"], "identity_mismatch") != parsed.digest():
            _fail("identity_mismatch")
        return parsed


def _admission_dict(admission: CandidateExecutionAdmission) -> dict[str, object]:
    return {
        "schema_version": admission.schema_version, "protocol": admission.protocol,
        "workspace_plan_sha256": admission.workspace_plan_sha256,
        "bundle_sha256": admission.bundle_sha256, "contract_sha256": admission.contract_sha256,
        "inputs": [_input_dict(item) for item in admission.inputs],
        "dependency_sha256": admission.dependency_sha256, "environment_sha256": admission.environment_sha256,
        "evaluator": {"kind": admission.evaluator.kind, "fingerprint": admission.evaluator.fingerprint},
        "output_contract_sha256": admission.output_contract_sha256, "budget": _budget_dict(admission.budget),
    }


def validate_candidate_execution_admission(admission: CandidateExecutionAdmission) -> CandidateExecutionAdmission:
    """Deeply reconstruct typed fields in memory, including nested values changed after creation."""
    try:
        if not isinstance(admission, CandidateExecutionAdmission):
            _fail("invalid")
        return CandidateExecutionAdmission(
            admission.workspace_plan_sha256, admission.bundle_sha256, admission.contract_sha256,
            admission.inputs, admission.dependency_sha256, admission.environment_sha256,
            admission.evaluator, admission.output_contract_sha256, admission.budget,
            admission.schema_version, admission.protocol,
        )
    except CandidateExecutionError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError, RecursionError):
        _fail("invalid")


def _loads(source: str | bytes) -> object:
    try:
        if isinstance(source, str):
            if len(source) > MAX_EXECUTION_ADMISSION_BYTES:
                _fail("too_large")
            content = source.encode("utf-8")
        elif isinstance(source, bytes):
            content = source
        else:
            _fail("invalid")
        if len(content) > MAX_EXECUTION_ADMISSION_BYTES:
            _fail("too_large")

        def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, item in items:
                if key in result:
                    _fail("invalid")
                result[key] = item
            return result

        return json.loads(
            content.decode("utf-8"), object_pairs_hook=pairs,
            parse_constant=lambda _: _fail("invalid"),
        )
    except CandidateExecutionError:
        raise
    except (UnicodeError, TypeError, ValueError, OverflowError, RecursionError):
        _fail("invalid")


def parse_candidate_execution_admission(source: str | bytes | Mapping[str, object]) -> CandidateExecutionAdmission:
    """Parse a mapping or bounded JSON text/bytes. Strings are JSON, never filesystem paths."""
    try:
        value = dict(source) if isinstance(source, Mapping) else _loads(source)
        return CandidateExecutionAdmission.from_dict(value)
    except CandidateExecutionError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError, RecursionError):
        _fail("invalid")


def _validated_plan(value: CandidateWorkspacePlan | Mapping[str, object]) -> CandidateWorkspacePlan:
    try:
        if isinstance(value, Mapping):
            value = CandidateWorkspacePlan.from_dict(dict(value))
        if not isinstance(value, CandidateWorkspacePlan) or not isinstance(value.bundle, CandidateSourceBundle):
            _fail("plan_mismatch")
        # Reconstruct bundle and source attributes before the older plan validator serializes
        # them. Caller DTO subclasses cannot conceal altered raw fields through to_dict().
        bundle = CandidateSourceBundle(
            value.bundle.contract_sha256, value.bundle.entrypoint, value.bundle.files,
            value.bundle.schema_version, value.bundle.protocol,
        )
        detached = CandidateWorkspacePlan(
            bundle, value.command, value.environment, value.timeout_seconds,
            value.max_output_bytes, value.workspace_cwd, value.schema_version, value.protocol,
        )
        return validate_candidate_workspace_plan(detached)
    except (CandidateBundleError, CandidateWorkspaceError, AttributeError, KeyError, TypeError, ValueError, OverflowError, RecursionError):
        _fail("plan_mismatch")


def _check_plan(admission: CandidateExecutionAdmission, plan: CandidateWorkspacePlan) -> None:
    if admission.workspace_plan_sha256 != plan.digest():
        _fail("plan_mismatch")
    if admission.bundle_sha256 != plan.bundle_sha256:
        _fail("bundle_mismatch")
    if admission.contract_sha256 != plan.contract_sha256:
        _fail("contract_mismatch")
    # A declaration cannot request plan limits outside its physical admission ceiling.
    if plan.timeout_seconds > admission.budget.timeout_seconds or plan.max_output_bytes > admission.budget.max_output_bytes:
        _fail("budget_invalid")


def _check_pins(
    admission: CandidateExecutionAdmission, *,
    expected_plan_sha256: str | None,
    expected_bundle_sha256: str | None,
    expected_contract_sha256: str | None,
    expected_dependency_sha256: str | None,
    expected_environment_sha256: str | None,
    expected_evaluator: CandidateEvaluatorPin | Mapping[str, object] | None,
    expected_evaluator_sha256: str | None,
    expected_evaluator_kind: str | None,
    expected_output_contract_sha256: object,
    expected_admission_sha256: str | None,
) -> None:
    for expected, actual, code in (
        (expected_plan_sha256, admission.workspace_plan_sha256, "plan_mismatch"),
        (expected_bundle_sha256, admission.bundle_sha256, "bundle_mismatch"),
        (expected_contract_sha256, admission.contract_sha256, "contract_mismatch"),
        (expected_dependency_sha256, admission.dependency_sha256, "dependency_mismatch"),
        (expected_environment_sha256, admission.environment_sha256, "environment_mismatch"),
        (expected_evaluator_sha256, admission.evaluator.fingerprint, "evaluator_mismatch"),
    ):
        if expected is not None and _digest(expected, code) != actual:
            _fail(code)
    if expected_evaluator is not None and _copy_evaluator(expected_evaluator) != admission.evaluator:
        _fail("evaluator_mismatch")
    if expected_evaluator_kind is not None and _identifier(expected_evaluator_kind, evaluator=True) != admission.evaluator.kind:
        _fail("evaluator_mismatch")
    if expected_output_contract_sha256 is not _UNSET:
        expected_output = (
            None if expected_output_contract_sha256 is None
            else _digest(expected_output_contract_sha256, "output_contract_mismatch")
        )
        if expected_output != admission.output_contract_sha256:
            _fail("output_contract_mismatch")
    if expected_admission_sha256 is not None and _digest(expected_admission_sha256, "identity_mismatch") != admission.digest():
        _fail("identity_mismatch")


def build_candidate_execution_admission(
    plan: CandidateWorkspacePlan | Mapping[str, object], *,
    inputs: tuple[CandidateExecutionInput, ...] | list[CandidateExecutionInput],
    dependency_sha256: str, environment_sha256: str,
    evaluator: CandidateEvaluatorPin | Mapping[str, object],
    budget: CandidateExecutionBudget | Mapping[str, object],
    output_contract_sha256: str | None = None,
    expected_plan_sha256: str | None = None,
    expected_bundle_sha256: str | None = None,
    expected_contract_sha256: str | None = None,
    expected_dependency_sha256: str | None = None,
    expected_environment_sha256: str | None = None,
    expected_evaluator: CandidateEvaluatorPin | Mapping[str, object] | None = None,
    expected_evaluator_sha256: str | None = None,
    expected_evaluator_kind: str | None = None,
    expected_output_contract_sha256: object = _UNSET,
    expected_admission_sha256: str | None = None,
) -> CandidateExecutionAdmission:
    """Build and pin a declaration from a complete plan without opening any local path."""
    parsed_plan = _validated_plan(plan)
    admission = CandidateExecutionAdmission(
        parsed_plan.digest(), parsed_plan.bundle_sha256, parsed_plan.contract_sha256,
        inputs, dependency_sha256, environment_sha256, _copy_evaluator(evaluator),
        output_contract_sha256, _copy_budget(budget),
    )
    _check_plan(admission, parsed_plan)
    _check_pins(
        admission, expected_plan_sha256=expected_plan_sha256,
        expected_bundle_sha256=expected_bundle_sha256, expected_contract_sha256=expected_contract_sha256,
        expected_dependency_sha256=expected_dependency_sha256, expected_environment_sha256=expected_environment_sha256,
        expected_evaluator=expected_evaluator, expected_evaluator_sha256=expected_evaluator_sha256,
        expected_evaluator_kind=expected_evaluator_kind,
        expected_output_contract_sha256=expected_output_contract_sha256,
        expected_admission_sha256=expected_admission_sha256,
    )
    return admission


@dataclass(frozen=True)
class VerifiedCandidateExecutionAdmission:
    """A validated declaration; observed_inputs is None unless byte verification occurred."""

    admission: CandidateExecutionAdmission
    admission_sha256: str
    observed_inputs: tuple[CandidateExecutionInput, ...] | None

    def __post_init__(self) -> None:
        admission = validate_candidate_execution_admission(self.admission)
        if _digest(self.admission_sha256, "identity_mismatch") != admission.digest():
            _fail("identity_mismatch")
        observed = None if self.observed_inputs is None else _inputs(self.observed_inputs)
        if observed is not None and observed != admission.inputs:
            _fail("input_changed")
        object.__setattr__(self, "admission", admission)
        object.__setattr__(self, "observed_inputs", observed)

    @property
    def inputs_verified(self) -> bool:
        return self.observed_inputs is not None

    @property
    def input_count(self) -> int:
        return len(self.admission.inputs)

    @property
    def total_input_bytes(self) -> int:
        return sum(item.size for item in self.admission.inputs)

    def to_dict(self) -> dict[str, object]:
        checked = VerifiedCandidateExecutionAdmission(self.admission, self.admission_sha256, self.observed_inputs)
        return {
            "admission": checked.admission.to_dict(), "admission_sha256": checked.admission_sha256,
            "inputs_verified": checked.inputs_verified,
            "input_count": checked.input_count, "total_input_bytes": checked.total_input_bytes,
            "observed_inputs": (
                None if checked.observed_inputs is None
                else [_input_dict(item) for item in checked.observed_inputs]
            ),
        }


def _verify_input(root: Path, item: CandidateExecutionInput) -> CandidateExecutionInput:
    try:
        content = _files.read_regular_file(_files.absolute_path(root / item.target), item.size, exact_size=True)
    except _files.BenchmarkFileError as exc:
        _fail({"missing": "input_missing", "unsafe": "input_unsafe"}.get(exc.reason, "input_changed"))
    except OSError:
        _fail("input_changed")
    digest = hashlib.sha256(content).hexdigest()
    if len(content) != item.size or digest != item.sha256:
        _fail("input_changed")
    return CandidateExecutionInput(item.target, item.source_label, len(content), digest)


def _verify_inputs(
    root_value: str | os.PathLike[str], inputs: tuple[CandidateExecutionInput, ...],
) -> tuple[CandidateExecutionInput, ...]:
    # Hold the whole directory chain even for an empty input set. Each shared bounded file read
    # separately verifies its complete path before and after reading; no atomic set is claimed.
    try:
        root = _files.absolute_path(root_value)
        chain = DirectoryChain(root, "input_unsafe")
    except FileNotFoundError:
        _fail("input_missing")
    except (OSError, _files.BenchmarkFileError, CandidateWorkspaceError):
        _fail("input_unsafe")
    try:
        observed: list[CandidateExecutionInput] = []
        for item in inputs:
            chain.check()
            observed.append(_verify_input(root, item))
            chain.check()
        chain.check()
        return tuple(observed)
    except (OSError, CandidateWorkspaceError):
        _fail("input_changed")
    finally:
        try:
            chain.close()
        except OSError:
            _fail("input_changed")


def admit_candidate_execution(
    admission: CandidateExecutionAdmission | CandidateWorkspacePlan | Mapping[str, object] | str | bytes, *,
    plan: CandidateWorkspacePlan | Mapping[str, object] | None = None,
    input_root: str | os.PathLike[str] | None = None,
    inputs: tuple[CandidateExecutionInput, ...] | list[CandidateExecutionInput] | None = None,
    dependency_sha256: str | None = None,
    environment_sha256: str | None = None,
    evaluator: CandidateEvaluatorPin | Mapping[str, object] | None = None,
    output_contract_sha256: str | None = None,
    budget: CandidateExecutionBudget | Mapping[str, object] | None = None,
    expected_plan_sha256: str | None = None,
    expected_bundle_sha256: str | None = None,
    expected_contract_sha256: str | None = None,
    expected_dependency_sha256: str | None = None,
    expected_environment_sha256: str | None = None,
    expected_evaluator: CandidateEvaluatorPin | Mapping[str, object] | None = None,
    expected_evaluator_sha256: str | None = None,
    expected_evaluator_kind: str | None = None,
    expected_output_contract_sha256: object = _UNSET,
    expected_admission_sha256: str | None = None,
) -> VerifiedCandidateExecutionAdmission:
    """Validate the complete plan and every caller pin before optional, read-only input checks.

    Pass a plan as the first argument with explicit declaration fields to build and admit at once.
    Replaying an existing admission requires its plan through the plan keyword. Omit input_root
    for structural admission only; the result then has observed_inputs=None.
    """
    is_plan = isinstance(admission, CandidateWorkspacePlan) or (
        isinstance(admission, Mapping) and admission.get("protocol") == "lunar-candidate-workspace-plan-v1"
    )
    if is_plan:
        if plan is not None:
            _fail("invalid")
        parsed_plan = _validated_plan(admission)
        if inputs is None or dependency_sha256 is None or environment_sha256 is None or evaluator is None or budget is None:
            _fail("invalid")
        parsed = build_candidate_execution_admission(
            parsed_plan, inputs=inputs, dependency_sha256=dependency_sha256,
            environment_sha256=environment_sha256, evaluator=evaluator,
            output_contract_sha256=output_contract_sha256, budget=budget,
        )
    else:
        parsed = (
            validate_candidate_execution_admission(admission)
            if isinstance(admission, CandidateExecutionAdmission)
            else parse_candidate_execution_admission(admission)
        )
        if plan is None:
            _fail("plan_mismatch")
        parsed_plan = _validated_plan(plan)
        # Declaration fields are construction inputs, not silently ignored replay pins.
        if any(value is not None for value in (inputs, dependency_sha256, environment_sha256, evaluator, budget, output_contract_sha256)):
            _fail("invalid")
    _check_plan(parsed, parsed_plan)
    _check_pins(
        parsed, expected_plan_sha256=expected_plan_sha256,
        expected_bundle_sha256=expected_bundle_sha256, expected_contract_sha256=expected_contract_sha256,
        expected_dependency_sha256=expected_dependency_sha256, expected_environment_sha256=expected_environment_sha256,
        expected_evaluator=expected_evaluator, expected_evaluator_sha256=expected_evaluator_sha256,
        expected_evaluator_kind=expected_evaluator_kind,
        expected_output_contract_sha256=expected_output_contract_sha256,
        expected_admission_sha256=expected_admission_sha256,
    )
    observed = None if input_root is None else _verify_inputs(input_root, parsed.inputs)
    return VerifiedCandidateExecutionAdmission(parsed, parsed.digest(), observed)


admit_candidate_execution_admission = admit_candidate_execution

__all__ = [
    "CANDIDATE_EXECUTION_PROTOCOL",
    "CANDIDATE_EXECUTION_SCHEMA_VERSION",
    "EXECUTION_PROTOCOL",
    "EXECUTION_SCHEMA_VERSION",
    "MAX_EXECUTION_ADMISSION_BYTES",
    "MAX_EXECUTION_EVALUATOR_KIND_BYTES",
    "MAX_EXECUTION_INPUTS",
    "MAX_EXECUTION_INPUT_BYTES",
    "MAX_EXECUTION_OUTPUT_BYTES",
    "MAX_EXECUTION_PROCESSES",
    "MAX_EXECUTION_SOURCE_LABEL_BYTES",
    "MAX_EXECUTION_TARGET_BYTES",
    "MAX_EXECUTION_TIMEOUT_SECONDS",
    "SOURCE_ONLY_EVALUATOR_KIND",
    "CandidateEvaluatorPin",
    "CandidateExecutionAdmission",
    "CandidateExecutionBudget",
    "CandidateExecutionError",
    "CandidateExecutionInput",
    "VerifiedCandidateExecutionAdmission",
    "admit_candidate_execution",
    "admit_candidate_execution_admission",
    "build_candidate_execution_admission",
    "parse_candidate_execution_admission",
    "validate_candidate_execution_admission",
]
