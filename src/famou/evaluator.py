"""Structured, local evaluation and safe artifact-acceptance contracts."""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

MAX_CONTRACT_BYTES = 20_000
MAX_RULES = 32
MAX_RULE_DEPTH = 8
MAX_TEXT_BYTES = 8_000
MAX_PATH_BYTES = 512
MAX_JSON_KEYS = 16
MAX_ARTIFACT_BYTES = 256 * 1024
MAX_OUTPUT_FIELDS = 32
OUTPUT_FORMATS = frozenset({"json", "jsonl", "csv", "text"})
ROLE_EVIDENCE_FORMATS = frozenset({"json", "jsonl", "csv", "text"})
_SECRET_RE = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._-]{12,}|api[_-]?key\s*[:=]\s*\S+)"
)


@dataclass(frozen=True)
class Evaluation:
    passed: bool
    evidence: tuple[str, ...]
    reason: str
    details: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "evidence": list(self.evidence),
            "reason": self.reason,
            "details": self.details,
        }


class Evaluator(Protocol):
    def evaluate(self, result: str, workspace: Path) -> Evaluation:
        """Return an evidence-backed decision for one candidate result."""


class NonEmptyEvaluator:
    """Baseline local evaluator used when a task does not request stronger checks."""

    def evaluate(self, result: str, workspace: Path) -> Evaluation:
        del workspace
        passed = bool(result.strip())
        return Evaluation(
            passed=passed,
            evidence=("result.txt contains non-empty output",) if passed else (),
            reason="result is non-empty" if passed else "result is empty",
            details={"kind": "non_empty", "passed": passed},
        )


class ContainsEvaluator:
    """Accept a result only when it contains a required text fragment."""

    def __init__(self, expected: str) -> None:
        self.expected = expected

    def evaluate(self, result: str, workspace: Path) -> Evaluation:
        del workspace
        passed = self.expected in result
        return Evaluation(
            passed=passed,
            evidence=(f"result contains {self.expected!r}",) if passed else (),
            reason=(
                f"result contains required text {self.expected!r}"
                if passed
                else f"result does not contain required text {self.expected!r}"
            ),
            details={"kind": "result_contains", "passed": passed},
        )


def _bounded_text(value: object, field_name: str, *, limit: int = MAX_TEXT_BYTES) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    value = value.strip()
    if not value:
        raise ValueError(f"{field_name} must not be empty")
    if len(value.encode("utf-8")) > limit:
        raise ValueError(f"{field_name} exceeds {limit} bytes")
    if _SECRET_RE.search(value):
        raise ValueError(f"{field_name} contains credential-like content")
    return value


def _safe_relative_path(value: object, field_name: str = "artifact path") -> str:
    path = _bounded_text(value, field_name, limit=MAX_PATH_BYTES)
    if "\\" in path or "\x00" in path:
        raise ValueError(f"{field_name} must be a portable relative path")
    candidate = Path(path)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in path.split("/")):
        raise ValueError(f"{field_name} must stay below the attempt workspace")
    return path


def _object(value: object, field_name: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        expected = ", ".join(sorted(keys))
        raise ValueError(f"{field_name} must contain exactly: {expected}")
    return value


def _normalise_input(value: str | dict[str, Any]) -> object:
    if isinstance(value, dict):
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True)
        if len(encoded.encode("utf-8")) > MAX_CONTRACT_BYTES:
            raise ValueError(f"acceptance exceeds {MAX_CONTRACT_BYTES} bytes")
        if _SECRET_RE.search(encoded):
            raise ValueError("acceptance contains credential-like content")
        return value
    text = _bounded_text(value, "acceptance", limit=MAX_CONTRACT_BYTES)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        # Plain strings are the Feature 005/006 shorthand. An object/array-looking input is
        # unambiguously intended as JSON and should fail rather than quietly becoming a substring.
        if text.startswith(("{", "[")):
            raise ValueError("acceptance JSON is malformed") from exc
        return text
    if isinstance(parsed, str):
        return _bounded_text(parsed, "acceptance")
    if not isinstance(parsed, dict):
        raise TypeError("acceptance JSON must be a string or object")
    return _normalise_input(parsed)


def _compile_rule(value: object, depth: int, count: list[int]) -> dict[str, Any]:
    if depth > MAX_RULE_DEPTH:
        raise ValueError(f"acceptance rule depth exceeds {MAX_RULE_DEPTH}")
    if not isinstance(value, dict) or len(value) != 1:
        raise ValueError("acceptance rule must be an object with exactly one rule")
    count[0] += 1
    if count[0] > MAX_RULES:
        raise ValueError(f"acceptance has more than {MAX_RULES} rules")
    rule, payload = next(iter(value.items()))
    if rule == "contains":
        return {"result_contains": _bounded_text(payload, "acceptance contains")}
    if rule == "result_contains":
        return {rule: _bounded_text(payload, "acceptance result_contains")}
    if rule == "artifact_exists":
        return {rule: _safe_relative_path(payload)}
    if rule == "artifact_text_contains":
        item = _object(payload, "artifact_text_contains", {"path", "contains"})
        return {
            rule: {
                "path": _safe_relative_path(item["path"]),
                "contains": _bounded_text(item["contains"], "artifact_text_contains contains"),
            }
        }
    if rule == "json_parse":
        return {rule: _safe_relative_path(payload)}
    if rule == "json_has_keys":
        item = _object(payload, "json_has_keys", {"path", "keys"})
        keys = item["keys"]
        if not isinstance(keys, list) or not keys or len(keys) > MAX_JSON_KEYS:
            raise ValueError(f"json_has_keys keys must be a non-empty array of at most {MAX_JSON_KEYS}")
        normalized_keys = [_bounded_text(key, "json_has_keys key") for key in keys]
        if len(set(normalized_keys)) != len(normalized_keys):
            raise ValueError("json_has_keys keys must be unique")
        return {rule: {"path": _safe_relative_path(item["path"]), "keys": normalized_keys}}
    if rule == "output_valid":
        item = _object(payload, "output_valid", {"path", "format", "fields"})
        path = _safe_relative_path(item["path"])
        if not path.startswith("output/"):
            raise ValueError("output_valid path must be below the output/ directory")
        output_format = _bounded_text(item["format"], "output_valid format", limit=32).lower()
        if output_format not in OUTPUT_FORMATS:
            raise ValueError("output_valid format must be json, jsonl, csv, or text")
        fields = item["fields"]
        if not isinstance(fields, list) or len(fields) > MAX_OUTPUT_FIELDS or any(not isinstance(field, str) for field in fields):
            raise ValueError("output_valid fields must be a bounded string array")
        normalized_fields = [_bounded_text(field, "output_valid field", limit=128) for field in fields]
        if len(set(normalized_fields)) != len(normalized_fields):
            raise ValueError("output_valid fields must be unique")
        if output_format == "text" and normalized_fields:
            raise ValueError("text output_valid rules cannot declare fields")
        return {rule: {"path": path, "format": output_format, "fields": normalized_fields}}
    if rule == "artifact_valid":
        item = _object(payload, "artifact_valid", {"path", "format", "fields"})
        path = _safe_relative_path(item["path"])
        artifact_format = _bounded_text(item["format"], "artifact_valid format", limit=32).lower()
        if artifact_format not in ROLE_EVIDENCE_FORMATS:
            raise ValueError("artifact_valid format must be json, jsonl, csv, or text")
        fields = item["fields"]
        if (
            not isinstance(fields, list)
            or len(fields) > MAX_OUTPUT_FIELDS
            or any(not isinstance(field, str) for field in fields)
        ):
            raise ValueError("artifact_valid fields must be a bounded string array")
        normalized_fields = [_bounded_text(field, "artifact_valid field", limit=128) for field in fields]
        if len(set(normalized_fields)) != len(normalized_fields):
            raise ValueError("artifact_valid fields must be unique")
        if artifact_format == "text" and normalized_fields:
            raise ValueError("text artifact_valid rules cannot declare fields")
        return {rule: {"path": path, "format": artifact_format, "fields": normalized_fields}}
    if rule == "data_profile_valid":
        path = _safe_relative_path(payload)
        if not path.startswith("data/processed/") or path == "data/processed/":
            raise ValueError("data_profile_valid path must be below data/processed/")
        return {rule: path}
    if rule == "evaluation_report_valid":
        path = _safe_relative_path(payload)
        if not path.startswith("evaluate/") or path == "evaluate/":
            raise ValueError("evaluation_report_valid path must be below evaluate/")
        return {rule: path}
    if rule in {"all", "any"}:
        if not isinstance(payload, list) or not payload:
            raise ValueError(f"{rule} must be a non-empty rule array")
        return {rule: [_compile_rule(child, depth + 1, count) for child in payload]}
    raise ValueError(f"unsupported acceptance rule: {rule}")


def compile_acceptance(value: str | dict[str, Any] | None) -> dict[str, Any] | None:
    """Validate and canonicalize one task acceptance value without reading artifacts."""
    if value is None:
        return None
    normalized = _normalise_input(value)
    if isinstance(normalized, str):
        return {"result_contains": normalized}
    return _compile_rule(normalized, 1, [0])


def validate_acceptance(value: str | dict[str, Any] | None) -> None:
    """Validate an acceptance input at a plan/run creation boundary."""
    compile_acceptance(value)


def _workspace_path(workspace: Path, relative_path: str) -> Path:
    if workspace.is_symlink():
        raise ValueError("attempt workspace must not be a symlink")
    root = workspace.resolve(strict=False)
    candidate = (root / relative_path).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("artifact path resolves outside the attempt workspace") from exc
    return candidate


def _raw_path_has_symlink(root: Path, path: Path) -> bool:
    current = path
    while True:
        if current.exists() and current.is_symlink():
            return True
        if current == root:
            return False
        if current.parent == current:
            return True
        current = current.parent


def _artifact_file(workspace: Path, relative_path: str) -> tuple[Path | None, str | None]:
    try:
        path = _workspace_path(workspace, relative_path)
    except ValueError as exc:
        return None, str(exc)
    root = workspace.resolve(strict=False)
    if _raw_path_has_symlink(root, workspace / relative_path):
        return None, "artifact path contains a symlink"
    if not path.is_file():
        return None, "artifact does not exist as a regular file"
    return path, None


def _read_artifact(workspace: Path, relative_path: str) -> tuple[str | None, str | None]:
    path, error = _artifact_file(workspace, relative_path)
    if error:
        return None, error
    try:
        assert path is not None
        if path.stat().st_size > MAX_ARTIFACT_BYTES:
            return None, f"artifact exceeds {MAX_ARTIFACT_BYTES} inspection bytes"
        return path.read_text(encoding="utf-8"), None
    except (OSError, UnicodeError):
        return None, "artifact is unreadable or not UTF-8 text"


def _detail(rule: str, passed: bool, reason: str, **metadata: object) -> dict[str, object]:
    return {"rule": rule, "passed": passed, "reason": reason, **metadata}


def _structured_content_check(
    content: str, output_format: str, fields: list[str]
) -> tuple[str | None, int | None, list[str]]:
    """Validate one bounded text/JSON/JSONL/CSV payload without exposing its contents."""
    error: str | None = None
    row_count: int | None = None
    observed_fields: list[str] = []
    if output_format == "text":
        if not content.strip():
            error = "text artifact is empty"
    elif output_format == "json":
        try:
            parsed = json.loads(content or "")
        except json.JSONDecodeError:
            error = "JSON artifact is invalid"
        else:
            if isinstance(parsed, dict):
                row_count = 1
                observed_fields = [str(key) for key in parsed]
                missing = [field for field in fields if field not in parsed]
                if missing:
                    error = f"JSON artifact is missing fields: {', '.join(missing)}"
            elif isinstance(parsed, list):
                row_count = len(parsed)
                for index, item in enumerate(parsed):
                    if not isinstance(item, dict):
                        error = f"JSON artifact row {index} is not an object"
                        break
                    if index == 0:
                        observed_fields = [str(key) for key in item]
                    missing = [field for field in fields if field not in item]
                    if missing:
                        error = f"JSON artifact row {index} is missing fields: {', '.join(missing)}"
                        break
            else:
                error = "JSON artifact root must be an object or array"
    elif output_format == "jsonl":
        row_count = 0
        for index, line in enumerate(content.splitlines()):
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                error = f"JSONL artifact line {index + 1} is invalid"
                break
            if not isinstance(parsed, dict):
                error = f"JSONL artifact line {index + 1} is not an object"
                break
            row_count += 1
            if not observed_fields:
                observed_fields = [str(key) for key in parsed]
            missing = [field for field in fields if field not in parsed]
            if missing:
                error = f"JSONL artifact line {index + 1} is missing fields: {', '.join(missing)}"
                break
        if error is None and row_count == 0:
            error = "JSONL artifact contains no records"
    elif output_format == "csv":
        try:
            reader = csv.DictReader(io.StringIO(content))
            observed_fields = [field for field in (reader.fieldnames or []) if field is not None]
            if not observed_fields:
                error = "CSV artifact has no header"
            else:
                missing = [field for field in fields if field not in observed_fields]
                if missing:
                    error = f"CSV artifact is missing fields: {', '.join(missing)}"
                else:
                    row_count = sum(1 for _ in reader)
        except (csv.Error, UnicodeError):
            error = "CSV artifact is invalid"
    return error, row_count, observed_fields


def _validate_data_profile(content: str) -> tuple[str | None, dict[str, object]]:
    """Validate the compact DataDiscovery profile schema used by the built-in role DAG."""
    try:
        payload = json.loads(content or "")
    except json.JSONDecodeError:
        return "data profile is not valid JSON", {}
    if not isinstance(payload, dict):
        return "data profile root must be an object", {}
    if set(payload) - {"schema_version", "inputs", "notes"}:
        return "data profile contains unknown top-level fields", {}
    if payload.get("schema_version") != "1":
        return "data profile schema_version must be '1'", {}
    inputs = payload.get("inputs")
    if not isinstance(inputs, list) or not inputs or len(inputs) > 64:
        return "data profile inputs must be a non-empty bounded array", {}
    for index, item in enumerate(inputs):
        if not isinstance(item, dict) or set(item) != {"path", "format", "row_count", "columns", "issues"}:
            return f"data profile input {index} has an invalid shape", {}
        path = item["path"]
        if (
            not isinstance(path, str)
            or not path.startswith("data/raw/")
            or path == "data/raw/"
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or "\\" in path
            or "\x00" in path
        ):
            return f"data profile input {index} path is invalid", {}
        if not isinstance(item["format"], str) or not item["format"].strip() or len(item["format"].encode("utf-8")) > 32:
            return f"data profile input {index} format is invalid", {}
        row_count = item["row_count"]
        if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 0:
            return f"data profile input {index} row_count is invalid", {}
        columns = item["columns"]
        if not isinstance(columns, list) or len(columns) > 128 or any(
            not isinstance(column, str) or not column.strip() or len(column.encode("utf-8")) > 128
            for column in columns
        ):
            return f"data profile input {index} columns are invalid", {}
        if len(set(columns)) != len(columns):
            return f"data profile input {index} columns must be unique", {}
        issues = item["issues"]
        if not isinstance(issues, list) or len(issues) > 32 or any(
            not isinstance(issue, str) or not issue.strip() or len(issue.encode("utf-8")) > 512
            for issue in issues
        ):
            return f"data profile input {index} issues are invalid", {}
    notes = payload.get("notes", "")
    if not isinstance(notes, str) or len(notes.encode("utf-8")) > 2_000:
        return "data profile notes are invalid", {}
    if _SECRET_RE.search(content):
        return "data profile contains credential-like content", {}
    return None, {
        "schema_version": "1",
        "input_count": len(inputs),
        "row_counts": [item["row_count"] for item in inputs],
    }


def _validate_evaluation_report(content: str) -> tuple[str | None, dict[str, object]]:
    """Parse the existing validity-first EvaluationReport contract without leaking its payload."""
    try:
        payload = json.loads(content or "")
    except json.JSONDecodeError:
        return "evaluation report is not valid JSON", {}
    try:
        # Local import keeps algorithm.py independent from the acceptance interpreter.
        from .algorithm import EvaluationReport

        report = EvaluationReport.from_dict(payload)
    except (TypeError, ValueError) as exc:
        return f"evaluation report is invalid: {str(exc)[:512]}", {}
    return None, {
        "schema_version": report.schema_version,
        "evaluator_id": report.evaluator_id,
        "validity": report.validity,
        "combined_score": report.combined_score,
        "detailed_score_count": len(report.detailed_scores),
        "error_count": len(report.error_info),
    }


def _evaluate_rule(
    rule: dict[str, Any], result: str, workspace: Path
) -> tuple[bool, tuple[str, ...], str, dict[str, object]]:
    name, payload = next(iter(rule.items()))
    if name == "result_contains":
        passed = payload in result
        reason = (
            f"result contains required text {payload!r}"
            if passed
            else f"result does not contain required text {payload!r}"
        )
        return passed, ((f"result contains {payload!r}",) if passed else ()), reason, _detail(
            name, passed, reason
        )
    if name == "artifact_exists":
        _, error = _artifact_file(workspace, payload)
        passed = error is None
        reason = f"artifact exists: {payload}" if passed else f"artifact {payload!r}: {error}"
        return passed, ((f"artifact exists: {payload}",) if passed else ()), reason, _detail(
            name, passed, reason, path=payload
        )
    if name == "artifact_text_contains":
        content, error = _read_artifact(workspace, payload["path"])
        passed = error is None and payload["contains"] in (content or "")
        reason = (
            f"artifact {payload['path']!r} contains required text"
            if passed
            else (
                f"artifact {payload['path']!r}: {error}"
                if error
                else f"artifact {payload['path']!r} does not contain required text {payload['contains']!r}"
            )
        )
        return passed, ((f"artifact {payload['path']} contains required text",) if passed else ()), reason, _detail(
            name, passed, reason, path=payload["path"]
        )
    if name in {"json_parse", "json_has_keys"}:
        path = payload if name == "json_parse" else payload["path"]
        content, error = _read_artifact(workspace, path)
        parsed: object | None = None
        if error is None:
            try:
                parsed = json.loads(content or "")
            except json.JSONDecodeError:
                error = "artifact does not contain valid JSON"
        if name == "json_parse":
            passed = error is None
            reason = f"artifact {path!r} parses as JSON" if passed else f"artifact {path!r}: {error}"
            return passed, ((f"artifact parses as JSON: {path}",) if passed else ()), reason, _detail(
                name, passed, reason, path=path
            )
        required = payload["keys"]
        missing = [key for key in required if not isinstance(parsed, dict) or key not in parsed]
        passed = error is None and not missing
        if error is not None:
            reason = f"artifact {path!r}: {error}"
        elif not isinstance(parsed, dict):
            reason = f"artifact {path!r} JSON root is not an object"
        elif missing:
            reason = f"artifact {path!r} JSON is missing top-level keys: {', '.join(missing)}"
        else:
            reason = f"artifact {path!r} JSON has required top-level keys"
        return passed, ((f"artifact JSON has required keys: {path}",) if passed else ()), reason, _detail(
            name, passed, reason, path=path, keys=required, missing=missing
        )
    if name == "output_valid":
        path = payload["path"]
        output_format = payload["format"]
        fields = payload["fields"]
        content, error = _read_artifact(workspace, path)
        row_count: int | None = None
        observed_fields: list[str] = []
        if error is None:
            error, row_count, observed_fields = _structured_content_check(
                content or "", output_format, fields
            )
            if error is not None:
                error = error.replace(" artifact", " output")
        passed = error is None
        reason = f"output {path!r} is a valid {output_format} artifact" if passed else f"output {path!r}: {error}"
        return passed, ((f"output valid: {path}",) if passed else ()), reason, _detail(
            name,
            passed,
            reason,
            path=path,
            format=output_format,
            fields=fields,
            row_count=row_count,
            observed_fields=observed_fields[:MAX_OUTPUT_FIELDS],
        )
    if name == "artifact_valid":
        path = payload["path"]
        artifact_format = payload["format"]
        fields = payload["fields"]
        content, error = _read_artifact(workspace, path)
        row_count: int | None = None
        observed_fields: list[str] = []
        if error is None:
            error, row_count, observed_fields = _structured_content_check(
                content or "", artifact_format, fields
            )
        passed = error is None
        reason = (
            f"artifact {path!r} is a valid {artifact_format} artifact"
            if passed
            else f"artifact {path!r}: {error}"
        )
        return passed, ((f"artifact valid: {path}",) if passed else ()), reason, _detail(
            name,
            passed,
            reason,
            path=path,
            format=artifact_format,
            fields=fields,
            row_count=row_count,
            observed_fields=observed_fields[:MAX_OUTPUT_FIELDS],
        )
    if name == "data_profile_valid":
        path = payload
        content, error = _read_artifact(workspace, path)
        metadata: dict[str, object] = {}
        if error is None:
            error, metadata = _validate_data_profile(content or "")
        passed = error is None
        reason = f"data profile {path!r} is valid" if passed else f"data profile {path!r}: {error}"
        return passed, ((f"data profile valid: {path}",) if passed else ()), reason, _detail(
            name, passed, reason, path=path, **metadata
        )
    if name == "evaluation_report_valid":
        path = payload
        content, error = _read_artifact(workspace, path)
        metadata: dict[str, object] = {}
        if error is None:
            error, metadata = _validate_evaluation_report(content or "")
        passed = error is None
        reason = f"evaluation report {path!r} is valid" if passed else f"evaluation report {path!r}: {error}"
        return passed, ((f"evaluation report valid: {path}",) if passed else ()), reason, _detail(
            name, passed, reason, path=path, **metadata
        )
    children = [_evaluate_rule(child, result, workspace) for child in payload]
    child_passed = [item[0] for item in children]
    passed = all(child_passed) if name == "all" else any(child_passed)
    child_evidence = tuple(evidence for item in children for evidence in item[1])
    failures = [item[2] for item in children if not item[0]]
    if passed:
        reason = (
            f"all {len(children)} acceptance rules passed"
            if name == "all"
            else "at least one acceptance rule passed"
        )
    elif name == "all":
        reason = f"all acceptance rule failed: {failures[0]}"
    else:
        reason = f"no any acceptance rule passed: {failures[0]}"
    detail = _detail(name, passed, reason, children=[item[3] for item in children])
    return passed, child_evidence, reason, detail


class AcceptanceEvaluator:
    """Evaluate a pre-validated declarative contract inside one attempt workspace."""

    def __init__(self, contract: dict[str, Any]) -> None:
        self.contract = contract

    def evaluate(self, result: str, workspace: Path) -> Evaluation:
        passed, evidence, reason, check = _evaluate_rule(self.contract, result, workspace)
        return Evaluation(
            passed,
            evidence,
            reason,
            details={"kind": "acceptance_contract", "contract": self.contract, "check": check},
        )


def acceptance_evaluator(value: str | dict[str, Any] | None) -> AcceptanceEvaluator | None:
    """Build the bounded local acceptance evaluator used by JSON plans.

    Legacy strings and ``{"contains": "..."}`` continue to mean result-text containment.
    Canonical rules are documented in ``specs/008-artifact-acceptance-contracts/contracts``.
    """
    contract = compile_acceptance(value)
    return AcceptanceEvaluator(contract) if contract is not None else None
