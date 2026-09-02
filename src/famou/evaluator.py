"""Structured, local evaluation and safe artifact-acceptance contracts."""

from __future__ import annotations

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


def _artifact_file(workspace: Path, relative_path: str) -> tuple[Path | None, str | None]:
    try:
        path = _workspace_path(workspace, relative_path)
    except ValueError as exc:
        return None, str(exc)
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
