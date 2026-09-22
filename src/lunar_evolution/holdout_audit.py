"""Provider-free canonical holdout declaration and receipt auditor.

This module only parses retained data and compares digests supplied by a caller.  It
never executes a holdout, evaluator, provider, or subprocess and never mutates a
store or workspace.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA_VERSION = "1"
MAX_HOLDOUTS = 8
MAX_DURATION_MS = 5000
_MAX_JSON_BYTES = 64 * 1024
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")

_DECLARATION_KEYS = frozenset({
    "schema_version", "manifest_sha256", "evaluator_sha256", "evaluator_version",
    "candidate_id", "execution_sha256", "holdouts",
})
_HOLDOUT_KEYS = frozenset({
    "holdout_id", "ordinal", "input_sha256", "expected_output_sha256", "max_duration_ms",
})
_RECEIPT_KEYS = frozenset({
    "schema_version", "manifest_sha256", "evaluator_sha256", "evaluator_version",
    "candidate_id", "execution_sha256", "holdout_id", "ordinal", "input_sha256",
    "expected_output_sha256", "actual_output_sha256", "native_exit_code",
    "process_exit_code", "cleanup", "duration_ms", "outcome", "receipt_sha256",
    "declaration_sha256",
})


class HoldoutAuditError(ValueError):
    """A declaration or receipt is not safe to admit to the auditor."""

    def __init__(self, code: str) -> None:
        self.code = code if re.fullmatch(r"[a-z0-9_]+", code or "") else "invalid"
        super().__init__(self.code)


def _fail(code: str) -> None:
    raise HoldoutAuditError(code)


def _canonical(value: Mapping[str, Any]) -> bytes:
    try:
        result = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise HoldoutAuditError("json_invalid") from exc
    if len(result) > _MAX_JSON_BYTES:
        _fail("json_too_large")
    return result


def _parse_json(value: str, *, kind: str) -> dict[str, Any]:
    if len(value) > _MAX_JSON_BYTES:
        _fail("json_too_large")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as exc:
        raise HoldoutAuditError(f"{kind}_json_invalid") from exc
    if len(encoded) > _MAX_JSON_BYTES:
        _fail("json_too_large")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in items:
            if key in result:
                _fail(f"{kind}_duplicate_key")
            result[key] = item
        return result

    try:
        loaded = json.loads(value, object_pairs_hook=pairs)
    except HoldoutAuditError:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise HoldoutAuditError(f"{kind}_json_invalid") from exc
    if not isinstance(loaded, dict):
        _fail(f"{kind}_schema_invalid")
    if _canonical(loaded).decode("utf-8") != value:
        _fail(f"{kind}_noncanonical")
    return loaded


def _text(value: object, pattern: re.Pattern[str], code: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        _fail(code)
    return value


def _sha(value: object, code: str) -> str:
    return _text(value, _SHA, code)


def _digest_payload(value: Mapping[str, Any], digest_key: str) -> str:
    payload = {key: item for key, item in value.items() if key != digest_key}
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _parse_declaration(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != _DECLARATION_KEYS:
        _fail("declaration_schema_invalid")
    if value.get("schema_version") != SCHEMA_VERSION:
        _fail("declaration_schema_invalid")
    _sha(value.get("manifest_sha256"), "manifest_digest_invalid")
    _sha(value.get("evaluator_sha256"), "evaluator_digest_invalid")
    _text(value.get("evaluator_version"), _ID, "evaluator_version_invalid")
    _text(value.get("candidate_id"), _ID, "candidate_identity_invalid")
    _sha(value.get("execution_sha256"), "execution_digest_invalid")
    entries = value.get("holdouts")
    if not isinstance(entries, list) or len(entries) != MAX_HOLDOUTS:
        _fail("holdout_count_invalid")
    parsed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping) or set(entry) != _HOLDOUT_KEYS:
            _fail("holdout_schema_invalid")
        holdout_id = _text(entry.get("holdout_id"), _ID, "holdout_identity_invalid")
        if holdout_id in seen:
            _fail("duplicate_holdout_id")
        seen.add(holdout_id)
        if type(entry.get("ordinal")) is not int or entry["ordinal"] != index:
            _fail("holdout_order_invalid")
        _sha(entry.get("input_sha256"), "holdout_input_digest_invalid")
        _sha(entry.get("expected_output_sha256"), "holdout_expected_digest_invalid")
        if type(entry.get("max_duration_ms")) is not int or not 1 <= entry["max_duration_ms"] <= MAX_DURATION_MS:
            _fail("holdout_duration_limit_invalid")
        parsed.append(dict(entry))
    return {**value, "holdouts": parsed}


def build_holdout_declaration(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Bind the exact ordered declaration; this is not a preregistration seal."""
    if not isinstance(payload, Mapping):
        _fail("declaration_schema_invalid")
    parsed = _parse_declaration(payload)
    return {**parsed, "declaration_sha256": _digest_payload(parsed, "declaration_sha256")}


def parse_holdout_declaration(value: Mapping[str, Any] | str) -> dict[str, Any]:
    if isinstance(value, str):
        value = _parse_json(value, kind="declaration")
    if not isinstance(value, Mapping) or set(value) != _DECLARATION_KEYS | {"declaration_sha256"}:
        _fail("declaration_schema_invalid")
    parsed = _parse_declaration({key: item for key, item in value.items() if key != "declaration_sha256"})
    digest = _sha(value["declaration_sha256"], "declaration_digest_invalid")
    if digest != _digest_payload(parsed, "declaration_sha256"):
        _fail("declaration_digest_mismatch")
    return {**parsed, "declaration_sha256": digest}


def _parse_receipt(value: Mapping[str, Any], declaration: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if set(value) != _RECEIPT_KEYS:
        _fail("receipt_schema_invalid")
    if value.get("schema_version") != SCHEMA_VERSION:
        _fail("receipt_schema_invalid")
    _sha(value.get("manifest_sha256"), "manifest_digest_invalid")
    _sha(value.get("declaration_sha256"), "declaration_digest_invalid")
    _sha(value.get("evaluator_sha256"), "evaluator_digest_invalid")
    _text(value.get("evaluator_version"), _ID, "evaluator_version_invalid")
    _text(value.get("candidate_id"), _ID, "candidate_identity_invalid")
    _sha(value.get("execution_sha256"), "execution_digest_invalid")
    _text(value.get("holdout_id"), _ID, "holdout_identity_invalid")
    if type(value.get("ordinal")) is not int or not 0 <= value["ordinal"] < MAX_HOLDOUTS:
        _fail("holdout_order_invalid")
    _sha(value.get("input_sha256"), "holdout_input_digest_invalid")
    _sha(value.get("expected_output_sha256"), "holdout_expected_digest_invalid")
    _sha(value.get("actual_output_sha256"), "holdout_actual_digest_invalid")
    for key in ("native_exit_code", "process_exit_code"):
        if value[key] is not None and (type(value[key]) is not int or not -255 <= value[key] <= 255):
            _fail("exit_observation_invalid")
    if type(value.get("cleanup")) is not str or value.get("cleanup") not in {"verified", "failed", "unknown"}:
        _fail("cleanup_observation_invalid")
    if type(value.get("duration_ms")) is not int or not 0 <= value["duration_ms"] <= 86_400_000:
        _fail("duration_invalid")
    if type(value.get("outcome")) is not str or value.get("outcome") not in {"passed", "failed", "unknown"}:
        _fail("outcome_invalid")
    receipt_digest = _sha(value.get("receipt_sha256"), "receipt_digest_invalid")
    if receipt_digest != _digest_payload(value, "receipt_sha256"):
        _fail("receipt_digest_mismatch")
    if declaration is not None:
        for key in ("manifest_sha256", "declaration_sha256", "evaluator_sha256", "evaluator_version", "candidate_id", "execution_sha256"):
            if value[key] != declaration[key]:
                _fail("receipt_identity_mismatch")
        declared = next((item for item in declaration["holdouts"] if item["holdout_id"] == value["holdout_id"]), None)
        if declared is None:
            _fail("receipt_holdout_unbound")
        if any(value[key] != declared[key] for key in ("ordinal", "input_sha256", "expected_output_sha256")):
            _fail("receipt_declaration_mismatch")
        if value["duration_ms"] > declared["max_duration_ms"]:
            _fail("duration_exceeded")
    return dict(value)


def build_holdout_receipt(payload: Mapping[str, Any], *, declaration: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build a receipt, calculating its canonical receipt digest."""
    if not isinstance(payload, Mapping):
        _fail("receipt_schema_invalid")
    value = dict(payload)
    value.pop("receipt_sha256", None)
    # Canonical digest is calculated only after copying the supplied payload.
    value["receipt_sha256"] = _digest_payload(value, "receipt_sha256")
    parsed_declaration = parse_holdout_declaration(declaration) if declaration is not None else None
    return _parse_receipt(value, parsed_declaration)


def parse_holdout_receipt(value: Mapping[str, Any] | str, *, declaration: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(value, str):
        value = _parse_json(value, kind="receipt")
    if not isinstance(value, Mapping):
        _fail("receipt_schema_invalid")
    parsed_declaration = parse_holdout_declaration(declaration) if declaration is not None else None
    parsed = _parse_receipt(value, parsed_declaration)
    if _canonical(parsed) != _canonical(dict(value)):
        _fail("receipt_noncanonical")
    return parsed


def _snapshot_digests(snapshot: object) -> tuple[str, str, str] | None:
    if snapshot is None:
        return None
    if not isinstance(snapshot, Mapping) or set(snapshot) != {"input", "expected_output", "actual_output"}:
        _fail("snapshot_schema_invalid")
    result = []
    for key in ("input", "expected_output", "actual_output"):
        value = snapshot[key]
        if type(value) is not bytes:
            _fail("snapshot_bytes_invalid")
        if len(value) > MAX_SNAPSHOT_BYTES:
            _fail("snapshot_too_large")
        result.append(hashlib.sha256(value).hexdigest())
    return result[0], result[1], result[2]


def audit_holdout_receipts(
    declaration: Mapping[str, Any] | str,
    receipts: Sequence[Mapping[str, Any] | str],
    *,
    retained_snapshots: Mapping[str, object] | None = None,
    primary_eligible: bool = False,
) -> dict[str, Any]:
    """Audit at most eight retained receipts and return bounded eligibility counts.

    ``retained_snapshots`` maps declared holdout IDs to exactly ``input``,
    ``expected_output`` and ``actual_output`` byte strings.  Unknown/missing
    observations never count as passes.  ``primary_eligible`` must originate
    from the independent lifecycle auditor; this function does not verify it.
    Declaration and receipt integrity errors raise bounded ``HoldoutAuditError``
    codes.  Byte-comparison and recorded outcome failures appear in the report.
    """
    parsed_declaration = parse_holdout_declaration(declaration)
    if not isinstance(receipts, Sequence) or isinstance(receipts, (str, bytes)):
        _fail("receipts_invalid")
    if len(receipts) > MAX_HOLDOUTS:
        _fail("receipt_count_invalid")
    if type(primary_eligible) is not bool:
        _fail("primary_eligibility_invalid")
    if retained_snapshots is None:
        retained_snapshots = {}
    declared_ids = {item["holdout_id"] for item in parsed_declaration["holdouts"]}
    if not isinstance(retained_snapshots, Mapping) or not set(retained_snapshots) <= declared_ids:
        _fail("snapshots_schema_invalid")
    snapshot_digests = {key: _snapshot_digests(value) for key, value in retained_snapshots.items()}
    by_id: dict[str, dict[str, Any]] = {}
    statuses: list[dict[str, Any]] = []
    previous_ordinal = -1
    for raw in receipts:
        receipt = parse_holdout_receipt(raw, declaration=parsed_declaration)
        holdout_id = receipt["holdout_id"]
        if holdout_id in by_id:
            _fail("duplicate_receipt_id")
        if receipt["ordinal"] <= previous_ordinal:
            _fail("receipt_order_invalid")
        previous_ordinal = receipt["ordinal"]
        by_id[holdout_id] = receipt
    counts = {"passed": 0, "failed": 0, "unknown": 0, "missing": 0}
    for expected in parsed_declaration["holdouts"]:
        holdout_id = expected["holdout_id"]
        receipt = by_id.get(holdout_id)
        reason = None
        status = "missing"
        if receipt is not None:
            status = "unknown"
            reason = "receipt_not_verified"
            snapshot = snapshot_digests.get(holdout_id)
            if any(receipt[key] not in (None, 0) for key in ("native_exit_code", "process_exit_code")):
                status, reason = "failed", "exit_failed"
            elif receipt["cleanup"] == "failed":
                status, reason = "failed", "cleanup_failed"
            elif receipt["outcome"] == "failed":
                status, reason = "failed", "outcome_failed"
            elif snapshot is not None and snapshot != (receipt["input_sha256"], receipt["expected_output_sha256"], receipt["actual_output_sha256"]):
                status, reason = "failed", "snapshot_digest_mismatch"
            elif receipt["actual_output_sha256"] != receipt["expected_output_sha256"]:
                status, reason = "failed", "output_digest_mismatch"
            elif receipt["native_exit_code"] is None or receipt["process_exit_code"] is None:
                reason = "exit_unknown"
            elif receipt["cleanup"] == "unknown":
                reason = "cleanup_unknown"
            elif receipt["outcome"] == "unknown":
                reason = "outcome_unknown"
            elif snapshot is None:
                reason = "snapshot_missing"
            else:
                status, reason = "passed", None
        counts[status] += 1
        statuses.append({"holdout_id": holdout_id, "ordinal": expected["ordinal"], "status": status, **({"reason": reason} if reason else {})})
    all_passed = counts["passed"] == MAX_HOLDOUTS
    return {
        "schema_version": SCHEMA_VERSION,
        "manifest_sha256": parsed_declaration["manifest_sha256"],
        "declaration_sha256": parsed_declaration["declaration_sha256"],
        "holdout_counts": counts,
        "holdouts": statuses,
        "first_problem": next((item for item in statuses if item["status"] != "passed"), None),
        "joint_eligible": bool(primary_eligible and all_passed),
        "provider_called_during_audit": False,
        "executed_during_audit": False,
        "mutated_during_audit": False,
        "real_acceptance_claimed": False,
    }


__all__ = [
    "MAX_DURATION_MS", "MAX_HOLDOUTS", "MAX_SNAPSHOT_BYTES", "SCHEMA_VERSION", "HoldoutAuditError",
    "audit_holdout_receipts", "build_holdout_declaration", "build_holdout_receipt",
    "parse_holdout_declaration", "parse_holdout_receipt",
]
