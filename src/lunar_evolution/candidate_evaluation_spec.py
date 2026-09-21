"""Pure declarations and strict report parsing for independent candidate evaluation.

An evaluator pin commits to its supplied harness bytes and invocation declarations. It does
not authenticate the host interpreter or dependencies. Parsing never reads paths or runs code.
"""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NoReturn

from .algorithm import MAX_OUTPUTS, MAX_REPORT_BYTES, EvaluationReport, OutputSpec, _safe_segment
from .candidate_execution import CandidateEvaluatorPin, CandidateExecutionError, _target
from .candidate_workspace_plan import CandidateWorkspaceError, _command, _environment

CANDIDATE_EVALUATOR_PROTOCOL = "lunar-candidate-evaluator-v1"
CANDIDATE_EVALUATOR_SCHEMA_VERSION = "1"
MAX_CANDIDATE_EVALUATION_SPEC_BYTES = 128 * 1024
MAX_CANDIDATE_EVALUATOR_HARNESS_BYTES = 1024 * 1024
MAX_CANDIDATE_EVALUATION_OUTPUT_FILE_BYTES = 16 * 1024 * 1024
MAX_CANDIDATE_EVALUATION_TOTAL_OUTPUT_BYTES = 64 * 1024 * 1024
MAX_CANDIDATE_EVALUATION_TIMEOUT_SECONDS = 86_400.0
CANDIDATE_EVALUATOR_KIND = "command-exact-v1"

_SPEC_FIELDS = {
    "schema_version", "protocol", "harness_sha256", "harness_size", "command",
    "evaluator_id", "environment", "timeout_seconds", "max_output_file_bytes",
    "max_total_output_bytes", "max_report_bytes",
}
_REPORT_FIELDS = {
    "schema_version", "evaluator_id", "validity", "quality", "combined_score",
    "detailed_scores", "error_info",
}


class CandidateEvaluationError(ValueError):
    """A fixed public error code with no caller-controlled paths or exception text."""

    _CODES = frozenset({
        "invalid", "plan_mismatch", "admission_mismatch", "contract_mismatch",
        "evaluator_mismatch", "output_contract_mismatch", "execution_invalid",
        "identity_mismatch", "root_unsafe", "source_changed", "input_changed",
        "output_changed", "harness_changed", "snapshot_changed", "report_invalid",
        "process_failed", "process_timed_out", "output_limit_exceeded",
        "process_cleanup_failed", "process_start_failed", "incomplete", "write_failed",
        "unsupported_constraints", "source_constraints_invalid",
    })

    def __init__(self, code: str) -> None:
        suffix = code.removeprefix("candidate_evaluation_") if isinstance(code, str) else ""
        self.code = "candidate_evaluation_" + (suffix if suffix in self._CODES else "invalid")
        super().__init__(self.code)


def _fail(code: str = "invalid") -> NoReturn:
    raise CandidateEvaluationError(code)


def _maximum(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        _fail()
    return value


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def canonical_json(value: object, maximum: int = MAX_CANDIDATE_EVALUATION_SPEC_BYTES) -> bytes:
    """Return compact, sorted, strict UTF-8 JSON within the requested byte bound."""
    _maximum(maximum)
    try:
        content = _json_bytes(value)
        if len(content) > maximum:
            _fail()
        return content
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        _fail()


def strict_json(content: bytes | str, maximum: int = MAX_CANDIDATE_EVALUATION_SPEC_BYTES) -> Any:
    """Decode bounded JSON, rejecting duplicate keys, invalid Unicode and nonfinite numbers."""
    _maximum(maximum)

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in items:
            if key in value:
                _fail()
            value[key] = item
        return value

    def number(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            _fail()
        return parsed

    try:
        if isinstance(content, str):
            content = content.encode("utf-8")
        if not isinstance(content, bytes) or len(content) > maximum:
            _fail()
        value = json.loads(
            content.decode("utf-8"), object_pairs_hook=pairs, parse_float=number,
            parse_constant=lambda _: _fail(),
        )
        # Escaped lone surrogates are accepted by json.loads but are not valid UTF-8 text.
        _json_bytes(value)
        return value
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        _fail()


def _digest(value: object) -> str:
    if (
        not isinstance(value, str) or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        _fail()
    return value


def _evaluator_id(value: object) -> str:
    try:
        normalized = _safe_segment(value, "evaluator id")
        if normalized != value:
            _fail()
        return normalized
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        _fail()


@dataclass(frozen=True)
class CandidateEvaluationSpec:
    harness_sha256: str
    harness_size: int
    command: tuple[str, ...]
    evaluator_id: str = "exact"
    environment: tuple[tuple[str, str], ...] = ()
    timeout_seconds: float = 30.0
    max_output_file_bytes: int = MAX_CANDIDATE_EVALUATION_OUTPUT_FILE_BYTES
    max_total_output_bytes: int = MAX_CANDIDATE_EVALUATION_OUTPUT_FILE_BYTES

    def __post_init__(self) -> None:
        try:
            _digest(self.harness_sha256)
            for value, maximum in (
                (self.harness_size, MAX_CANDIDATE_EVALUATOR_HARNESS_BYTES),
                (self.max_output_file_bytes, MAX_CANDIDATE_EVALUATION_OUTPUT_FILE_BYTES),
                (self.max_total_output_bytes, MAX_CANDIDATE_EVALUATION_TOTAL_OUTPUT_BYTES),
            ):
                if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= maximum:
                    _fail()
            if self.max_output_file_bytes > self.max_total_output_bytes:
                _fail()
            if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)):
                _fail()
            timeout = float(self.timeout_seconds)
            if not math.isfinite(timeout) or not 0 < timeout <= MAX_CANDIDATE_EVALUATION_TIMEOUT_SECONDS:
                _fail()
            object.__setattr__(self, "command", _command(self.command))
            object.__setattr__(self, "environment", _environment(self.environment))
            object.__setattr__(self, "evaluator_id", _evaluator_id(self.evaluator_id))
            object.__setattr__(self, "timeout_seconds", timeout)
            canonical_json(_spec_dict(self))
        except (CandidateWorkspaceError, AttributeError, TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
            _fail()

    def to_dict(self) -> dict[str, object]:
        return _spec_dict(_copy_spec(self))

    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict())).hexdigest()

    def pin(self) -> CandidateEvaluatorPin:
        return CandidateEvaluatorPin(CANDIDATE_EVALUATOR_KIND, self.digest())

    @classmethod
    def from_dict(cls, value: object) -> CandidateEvaluationSpec:
        try:
            if not isinstance(value, dict) or set(value) != _SPEC_FIELDS:
                _fail()
            if (
                value["schema_version"] != CANDIDATE_EVALUATOR_SCHEMA_VERSION
                or value["protocol"] != CANDIDATE_EVALUATOR_PROTOCOL
                or type(value["max_report_bytes"]) is not int
                or value["max_report_bytes"] != MAX_REPORT_BYTES
                or not isinstance(value["command"], list)
                or not isinstance(value["environment"], dict)
            ):
                _fail()
            return cls(
                harness_sha256=value["harness_sha256"], harness_size=value["harness_size"],
                command=value["command"], evaluator_id=value["evaluator_id"],
                environment=value["environment"], timeout_seconds=value["timeout_seconds"],
                max_output_file_bytes=value["max_output_file_bytes"],
                max_total_output_bytes=value["max_total_output_bytes"],
            )
        except (AttributeError, TypeError, ValueError, KeyError, UnicodeError, OverflowError, RecursionError):
            _fail()


def _spec_dict(spec: CandidateEvaluationSpec) -> dict[str, object]:
    return {
        "schema_version": CANDIDATE_EVALUATOR_SCHEMA_VERSION,
        "protocol": CANDIDATE_EVALUATOR_PROTOCOL,
        "harness_sha256": spec.harness_sha256, "harness_size": spec.harness_size,
        "command": list(spec.command), "evaluator_id": spec.evaluator_id,
        "environment": dict(spec.environment), "timeout_seconds": spec.timeout_seconds,
        "max_output_file_bytes": spec.max_output_file_bytes,
        "max_total_output_bytes": spec.max_total_output_bytes,
        "max_report_bytes": MAX_REPORT_BYTES,
    }


def _copy_spec(value: CandidateEvaluationSpec) -> CandidateEvaluationSpec:
    try:
        return CandidateEvaluationSpec(
            value.harness_sha256, value.harness_size, value.command, value.evaluator_id,
            value.environment, value.timeout_seconds, value.max_output_file_bytes,
            value.max_total_output_bytes,
        )
    except (AttributeError, TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        _fail()


def parse_candidate_evaluation_spec(
    source: CandidateEvaluationSpec | Mapping[str, object] | str | bytes,
) -> CandidateEvaluationSpec:
    """Rebuild a declaration or parse JSON content; strings are never treated as paths."""
    try:
        if isinstance(source, CandidateEvaluationSpec):
            return _copy_spec(source)
        if isinstance(source, Mapping):
            return CandidateEvaluationSpec.from_dict(dict(source))
        return CandidateEvaluationSpec.from_dict(strict_json(source))
    except (AttributeError, TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        _fail()


def candidate_output_contract_sha256(outputs: Sequence[OutputSpec]) -> str:
    """Commit to a validated, sorted output contract with portable distinct paths."""
    try:
        if (
            not isinstance(outputs, Sequence) or isinstance(outputs, (str, bytes, bytearray))
            or not 1 <= len(outputs) <= MAX_OUTPUTS
        ):
            _fail()
        rebuilt: list[OutputSpec] = []
        for output in outputs:
            if not isinstance(output, OutputSpec) or not isinstance(output.fields, (tuple, list)):
                _fail()
            _target(output.path)
            item = OutputSpec.from_dict({
                "path": output.path, "format": output.format, "fields": list(output.fields),
                "required": output.required, "description": output.description,
            })
            if item.path != output.path:
                _fail()
            rebuilt.append(item)
        rebuilt.sort(key=lambda item: item.path)
        nodes: dict[str, tuple[str, bool]] = {}
        for item in rebuilt:
            parts = item.path.split("/")
            for depth in range(1, len(parts) + 1):
                prefix = "/".join(parts[:depth])
                folded = unicodedata.normalize("NFC", prefix.casefold())
                is_file = depth == len(parts)
                previous = nodes.get(folded)
                if previous is not None and (previous[0] != prefix or previous[1] or is_file):
                    _fail()
                nodes[folded] = (prefix, is_file)
        return hashlib.sha256(canonical_json([item.to_dict() for item in rebuilt])).hexdigest()
    except (CandidateExecutionError, AttributeError, TypeError, ValueError, UnicodeError, OverflowError, RecursionError):
        _fail()


def parse_candidate_evaluation_report(content: bytes, *, evaluator_id: str) -> EvaluationReport:
    """Parse the full exact report schema without accepting aliases or coercing validity."""
    try:
        _evaluator_id(evaluator_id)
        if not isinstance(content, bytes):
            _fail("report_invalid")
        value = strict_json(content, maximum=MAX_REPORT_BYTES)
        if not isinstance(value, dict) or set(value) != _REPORT_FIELDS:
            _fail("report_invalid")
        if (
            value["schema_version"] != "1" or value["evaluator_id"] != evaluator_id
            or type(value["validity"]) is not int
        ):
            _fail("report_invalid")
        return EvaluationReport.from_dict(value)
    except (AttributeError, TypeError, ValueError, KeyError, UnicodeError, OverflowError, RecursionError):
        _fail("report_invalid")


__all__ = [
    "CANDIDATE_EVALUATOR_KIND",
    "CANDIDATE_EVALUATOR_PROTOCOL",
    "CANDIDATE_EVALUATOR_SCHEMA_VERSION",
    "MAX_CANDIDATE_EVALUATION_OUTPUT_FILE_BYTES",
    "MAX_CANDIDATE_EVALUATION_SPEC_BYTES",
    "MAX_CANDIDATE_EVALUATION_TIMEOUT_SECONDS",
    "MAX_CANDIDATE_EVALUATION_TOTAL_OUTPUT_BYTES",
    "MAX_CANDIDATE_EVALUATOR_HARNESS_BYTES",
    "CandidateEvaluationError",
    "CandidateEvaluationSpec",
    "candidate_output_contract_sha256",
    "canonical_json",
    "parse_candidate_evaluation_report",
    "parse_candidate_evaluation_spec",
    "strict_json",
]
