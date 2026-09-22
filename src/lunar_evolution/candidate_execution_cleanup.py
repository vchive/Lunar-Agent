"""Canonical, provider-free observations for one candidate process cleanup.

This module only validates a retained cleanup observation.  It does not probe a process,
signal a process group, read a workspace, or infer cleanup from an execution exit code.  A
future execution supervisor may use :func:`build_candidate_execution_cleanup` after its own
bounded process observation and persist the returned payload beside the native execution
record.  Older execution records have no cleanup payload and remain ``unknown``.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any, NoReturn

SCHEMA_VERSION = "1"
PROTOCOL = "lunar-candidate-execution-cleanup-v1"
MAX_CLEANUP_RECEIPT_BYTES = 16 * 1024
MAX_OBSERVED_MS = 86_400_000
MAX_PROCESS_ID = 2**63 - 1
MIN_PROCESS_ID = 2

_SHA = re.compile(r"^[0-9a-f]{64}$")
_PAYLOAD_KEYS = frozenset({
    "protocol", "schema_version", "launch_intent_sha256", "result_sha256",
    "native_exit_code", "process_exit_code", "observer_identity", "release_identity",
    "group_probe", "ownership_release", "cleanup", "observed_ms",
})
_RECEIPT_KEYS = _PAYLOAD_KEYS | {"receipt_sha256"}
_PROBES = frozenset({"absent", "present", "unknown"})
_RELEASES = frozenset({"observed", "not_observed", "unknown"})
_CLEANUP = frozenset({"verified", "failed", "unknown"})


class CandidateExecutionCleanupError(ValueError):
    """Fixed, path-free error raised for malformed cleanup observations."""

    _CODES = frozenset({
        "invalid", "json_invalid", "json_noncanonical", "json_too_large",
        "schema_invalid", "protocol_invalid", "digest_invalid", "digest_mismatch",
        "launch_intent_mismatch", "result_mismatch", "exit_invalid",
        "process_identity_invalid", "probe_invalid", "release_invalid",
        "cleanup_invalid", "duration_invalid", "cleanup_claim_invalid",
    })

    def __init__(self, code: str) -> None:
        self.code = code if code in self._CODES else "invalid"
        super().__init__(self.code)


def _fail(code: str) -> NoReturn:
    raise CandidateExecutionCleanupError(code)


def _canonical(value: Mapping[str, Any]) -> bytes:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail("json_invalid")
    if len(encoded) > MAX_CLEANUP_RECEIPT_BYTES:
        _fail("json_too_large")
    return encoded


def _parse_json(value: str) -> dict[str, Any]:
    try:
        encoded = value.encode("utf-8")
    except UnicodeError:
        _fail("json_invalid")
    if len(encoded) > MAX_CLEANUP_RECEIPT_BYTES:
        _fail("json_too_large")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in items:
            if key in result:
                _fail("json_invalid")
            result[key] = item
        return result

    try:
        loaded = json.loads(
            value, object_pairs_hook=pairs,
            parse_constant=lambda _constant: _fail("json_invalid"),
        )
    except CandidateExecutionCleanupError:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail("json_invalid")
    if not isinstance(loaded, dict):
        _fail("schema_invalid")
    if _canonical(loaded) != encoded:
        _fail("json_noncanonical")
    return loaded


def _digest(value: object, code: str = "digest_invalid") -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        _fail(code)
    return value


def _exit(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not -(2**31) <= value < 2**31:
        _fail("exit_invalid")
    return value


def _identity(value: object) -> dict[str, int] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"pid", "pgid"}:
        _fail("process_identity_invalid")
    result: dict[str, int] = {}
    for key in ("pid", "pgid"):
        item = value[key]
        if type(item) is not int or not MIN_PROCESS_ID <= item <= MAX_PROCESS_ID:
            _fail("process_identity_invalid")
        result[key] = item
    return result


def _payload(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _PAYLOAD_KEYS:
        _fail("schema_invalid")
    if value.get("protocol") != PROTOCOL or value.get("schema_version") != SCHEMA_VERSION:
        _fail("protocol_invalid")
    _digest(value.get("launch_intent_sha256"))
    _digest(value.get("result_sha256"))
    native = _exit(value.get("native_exit_code"))
    process = _exit(value.get("process_exit_code"))
    observer_identity = _identity(value.get("observer_identity"))
    release_identity = _identity(value.get("release_identity"))
    if type(value.get("group_probe")) is not str or value["group_probe"] not in _PROBES:
        _fail("probe_invalid")
    if type(value.get("ownership_release")) is not str or value["ownership_release"] not in _RELEASES:
        _fail("release_invalid")
    cleanup = value.get("cleanup")
    if type(cleanup) is not str or cleanup not in _CLEANUP:
        _fail("cleanup_invalid")
    observed_ms = value.get("observed_ms")
    if type(observed_ms) is not int or not 0 <= observed_ms <= MAX_OBSERVED_MS:
        _fail("duration_invalid")

    # The receipt is a conservative observation, not a claim that can be repaired by a
    # later result.  These implications reject a receipt that claims verified cleanup while
    # retaining an explicitly live group or while lacking any process identity/exit.
    if cleanup == "verified" and (
        observer_identity is None
        or release_identity is None
        or observer_identity != release_identity
        or native is None
        or process is None
        or native != process
        or value["group_probe"] != "absent"
        or value["ownership_release"] != "observed"
    ):
        _fail("cleanup_claim_invalid")
    if value["group_probe"] == "present" and cleanup == "verified":
        _fail("cleanup_claim_invalid")
    if value["ownership_release"] == "observed" and (
        observer_identity is None or release_identity is None
    ):
        _fail("cleanup_claim_invalid")
    if value["ownership_release"] != "observed" and release_identity is not None:
        _fail("cleanup_claim_invalid")
    if observer_identity is None and release_identity is not None:
        _fail("cleanup_claim_invalid")
    return {
        "protocol": PROTOCOL,
        "schema_version": SCHEMA_VERSION,
        "launch_intent_sha256": value["launch_intent_sha256"],
        "result_sha256": value["result_sha256"],
        "native_exit_code": native,
        "process_exit_code": process,
        "observer_identity": observer_identity,
        "release_identity": release_identity,
        "group_probe": value["group_probe"],
        "ownership_release": value["ownership_release"],
        "cleanup": cleanup,
        "observed_ms": observed_ms,
    }


def _receipt_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def build_candidate_execution_cleanup(
    payload: Mapping[str, Any], *,
    expected_launch_intent_sha256: str | None = None,
    expected_result_sha256: str | None = None,
) -> dict[str, Any]:
    """Canonicalize one independent cleanup observation and calculate its digest.

    The builder accepts only observations supplied by the process supervisor.  It never probes
    the process itself, so callers must obtain ``group_probe`` and ``ownership_release`` through
    their own bounded observer before calling this function.
    """
    parsed = _payload(payload)
    if expected_launch_intent_sha256 is not None:
        _digest(expected_launch_intent_sha256)
        if parsed["launch_intent_sha256"] != expected_launch_intent_sha256:
            _fail("launch_intent_mismatch")
    if expected_result_sha256 is not None:
        _digest(expected_result_sha256)
        if parsed["result_sha256"] != expected_result_sha256:
            _fail("result_mismatch")
    return {**parsed, "receipt_sha256": _receipt_digest(parsed)}


def parse_candidate_execution_cleanup(
    value: Mapping[str, Any] | str | bytes, *,
    expected_launch_intent_sha256: str | None = None,
    expected_result_sha256: str | None = None,
) -> dict[str, Any]:
    """Parse a canonical retained cleanup receipt without filesystem or process access."""
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeError:
            _fail("json_invalid")
    if isinstance(value, str):
        value = _parse_json(value)
    if not isinstance(value, Mapping) or set(value) != _RECEIPT_KEYS:
        _fail("schema_invalid")
    parsed = _payload({key: item for key, item in value.items() if key != "receipt_sha256"})
    digest = _digest(value.get("receipt_sha256"))
    if digest != _receipt_digest(parsed):
        _fail("digest_mismatch")
    if expected_launch_intent_sha256 is not None:
        _digest(expected_launch_intent_sha256)
        if parsed["launch_intent_sha256"] != expected_launch_intent_sha256:
            _fail("launch_intent_mismatch")
    if expected_result_sha256 is not None:
        _digest(expected_result_sha256)
        if parsed["result_sha256"] != expected_result_sha256:
            _fail("result_mismatch")
    result = {**parsed, "receipt_sha256": digest}
    if isinstance(value, Mapping) and _canonical(result) != _canonical(dict(value)):
        _fail("json_noncanonical")
    return result


def audit_candidate_execution_cleanup(
    value: Mapping[str, Any] | str | bytes, *,
    expected_launch_intent_sha256: str | None = None,
    expected_result_sha256: str | None = None,
) -> dict[str, Any]:
    """Return a bounded read-only projection of one parsed cleanup receipt.

    ``verified`` is the only status that can satisfy an execution boundary.  Failed or missing
    observations must remain distinguishable from malformed/unverifiable evidence at the caller.
    """
    try:
        receipt = parse_candidate_execution_cleanup(
            value,
            expected_launch_intent_sha256=expected_launch_intent_sha256,
            expected_result_sha256=expected_result_sha256,
        )
    except CandidateExecutionCleanupError as exc:
        return {"status": "unverifiable", "reason": "cleanup_evidence_" + exc.code}
    if receipt["cleanup"] == "verified":
        return {
            "status": "verified", "reason": None,
            "cleanup_sha256": receipt["receipt_sha256"],
        }
    if receipt["cleanup"] == "failed":
        return {
            "status": "failed", "reason": "execution_cleanup_failed",
            "cleanup_sha256": receipt["receipt_sha256"],
        }
    return {
        "status": "unverifiable", "reason": "execution_cleanup_unknown",
        "cleanup_sha256": receipt["receipt_sha256"],
    }


__all__ = [
    "MAX_CLEANUP_RECEIPT_BYTES", "MAX_OBSERVED_MS", "PROTOCOL", "SCHEMA_VERSION",
    "CandidateExecutionCleanupError", "audit_candidate_execution_cleanup",
    "build_candidate_execution_cleanup", "parse_candidate_execution_cleanup",
]
