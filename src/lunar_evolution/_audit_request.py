"""Strict, filesystem-free request binding for the retained acceptance auditor.

An audit request is an observation contract, not launch authorization or proof of
preregistration. Its caller supplies the complete frozen-identity denylist.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from .acceptance_observer import AcceptanceObservationError, parse_acceptance_manifest
from .holdout_audit import HoldoutAuditError, parse_holdout_declaration

SCHEMA_VERSION = "1"
MAX_AUDIT_REQUEST_BYTES = 128 * 1024
MAX_FROZEN_IDENTITIES = 128
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_PAYLOAD_KEYS = frozenset({
    "schema_version", "scope", "manifest", "identities", "paths", "pins",
    "holdout_declaration", "frozen_identities",
})
_IDENTITY_KEYS = frozenset({
    "parent_run_id", "child_run_id", "generation_task_id", "orchestration_task_id",
    "candidate_id", "solve_execution_id", "generation_budget_id",
})
_PATH_KEYS = frozenset({
    "parent_workspace", "child_workspace", "plan", "admission", "execution", "evaluation",
})
_PIN_KEYS = frozenset({
    "contract_sha256", "profile_sha256", "bundle_sha256", "plan_sha256",
    "admission_sha256", "completion_sha256", "evaluation_sha256", "selection_sha256",
    "delivery_sha256",
})
_FROZEN_KEYS = frozenset({
    "registration_id", "campaign_id", "campaign_root", "parent_run_id", "child_run_id",
})


class AcceptanceAuditError(ValueError):
    """A bounded public code; no supplied path, payload or exception is exposed."""

    def __init__(self, code: str) -> None:
        self.code = code if type(code) is str and re.fullmatch(r"[a-z0-9_]{1,64}", code) else "invalid"
        super().__init__(self.code)


def _fail(code: str) -> None:
    raise AcceptanceAuditError(code)


def _canonical(value: Mapping[str, Any]) -> bytes:
    try:
        raw = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise AcceptanceAuditError("audit_request_json_invalid") from None
    if len(raw) > MAX_AUDIT_REQUEST_BYTES:
        _fail("audit_request_too_large")
    return raw


def _json(value: str) -> dict[str, Any]:
    if len(value) > MAX_AUDIT_REQUEST_BYTES:
        _fail("audit_request_too_large")
    try:
        if len(value.encode("utf-8")) > MAX_AUDIT_REQUEST_BYTES:
            _fail("audit_request_too_large")
    except UnicodeError:
        raise AcceptanceAuditError("audit_request_json_invalid") from None

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in items:
            if key in result:
                _fail("audit_request_duplicate_key")
            result[key] = item
        return result

    try:
        parsed = json.loads(value, object_pairs_hook=pairs)
    except AcceptanceAuditError:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise AcceptanceAuditError("audit_request_json_invalid") from None
    if not isinstance(parsed, dict):
        _fail("audit_request_schema_invalid")
    if _canonical(parsed).decode("utf-8") != value:
        _fail("audit_request_noncanonical")
    return parsed


def _object(value: object, keys: frozenset[str], code: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        _fail(code)
    return dict(value)


def _text(value: object, pattern: re.Pattern[str], code: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        _fail(code)
    return value


def _path(value: object) -> str:
    if type(value) is not str or not 1 <= len(value) <= 512:
        _fail("audit_path_invalid")
    if any(character in value for character in ("\\", ":")) or any(
        ord(character) < 32 or ord(character) == 127 for character in value
    ):
        _fail("audit_path_invalid")
    parts = value.split("/")
    if len(parts) > 16 or any(part in {"", ".", ".."} for part in parts):
        _fail("audit_path_invalid")
    return value


def _payload(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _object(value, _PAYLOAD_KEYS, "audit_request_schema_invalid")
    if payload["schema_version"] != SCHEMA_VERSION or payload["scope"] != "acceptance_audit_request":
        _fail("audit_request_schema_invalid")
    # Bound the whole nested input before invoking its native parsers. The exact
    # schemas below leave no extension fields for private data or provider bodies.
    _canonical(payload)
    if not isinstance(payload["manifest"], Mapping):
        _fail("audit_manifest_invalid")
    try:
        manifest = parse_acceptance_manifest(payload["manifest"])
    except AcceptanceObservationError:
        raise AcceptanceAuditError("audit_manifest_invalid") from None
    identities = _object(payload["identities"], _IDENTITY_KEYS, "audit_identities_invalid")
    for identity in identities.values():
        _text(identity, _ID, "audit_identity_invalid")
    paths = _object(payload["paths"], _PATH_KEYS, "audit_paths_invalid")
    paths = {key: _path(path) for key, path in paths.items()}
    pins = _object(payload["pins"], _PIN_KEYS, "audit_pins_invalid")
    for pin in pins.values():
        _text(pin, _SHA, "audit_pin_invalid")
    if not isinstance(payload["holdout_declaration"], Mapping):
        _fail("audit_holdout_declaration_invalid")
    try:
        declaration = parse_holdout_declaration(payload["holdout_declaration"])
    except HoldoutAuditError:
        raise AcceptanceAuditError("audit_holdout_declaration_invalid") from None
    if manifest["task_sha256"] != pins["contract_sha256"]:
        _fail("audit_contract_mismatch")
    if (
        declaration["manifest_sha256"] != manifest["manifest_sha256"]
        or declaration["evaluator_sha256"] != manifest["evaluator_sha256"]
        or declaration["candidate_id"] != identities["candidate_id"]
        or declaration["execution_sha256"] != pins["completion_sha256"]
    ):
        _fail("audit_holdout_binding_mismatch")
    frozen = _object(payload["frozen_identities"], _FROZEN_KEYS, "audit_frozen_identities_invalid")
    frozen_copy: dict[str, list[str]] = {}
    for key, entries in frozen.items():
        if type(entries) is not list or len(entries) > MAX_FROZEN_IDENTITIES:
            _fail("audit_frozen_identities_invalid")
        parsed_entries = [_text(entry, _ID, "audit_frozen_identity_invalid") for entry in entries]
        if len(set(parsed_entries)) != len(parsed_entries):
            _fail("audit_frozen_identity_duplicate")
        frozen_copy[key] = parsed_entries
    for key in ("registration_id", "campaign_id", "campaign_root"):
        if manifest[key] in frozen_copy[key]:
            _fail("audit_frozen_identity_reused")
    # Parent and child run identities share a namespace: changing a historical
    # run's role must not turn it into a fresh identity.
    old_runs = set(frozen_copy["parent_run_id"]) | set(frozen_copy["child_run_id"])
    if any(identities[key] in old_runs for key in ("parent_run_id", "child_run_id")):
        _fail("audit_frozen_identity_reused")
    return {
        **payload, "manifest": manifest, "identities": identities, "paths": paths,
        "pins": pins, "holdout_declaration": declaration, "frozen_identities": frozen_copy,
    }


def build_acceptance_audit_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a digest-free payload and bind all audit declarations canonically.

    Workspace paths are relative to a separately supplied audit root; artifact
    paths are relative to the child workspace. This parser performs no I/O and
    does not replace the auditor's symlink, confinement or native identity checks.
    """
    parsed = _payload(payload)
    result = {**parsed, "audit_request_sha256": hashlib.sha256(_canonical(parsed)).hexdigest()}
    _canonical(result)
    return result


def parse_acceptance_audit_request(value: Mapping[str, Any] | str) -> dict[str, Any]:
    """Verify a canonical request and its digest without opening retained files."""
    if isinstance(value, str):
        value = _json(value)
    parsed = _object(value, _PAYLOAD_KEYS | {"audit_request_sha256"}, "audit_request_schema_invalid")
    _canonical(parsed)
    digest = _text(parsed.pop("audit_request_sha256"), _SHA, "audit_request_digest_invalid")
    payload = _payload(parsed)
    if hashlib.sha256(_canonical(payload)).hexdigest() != digest:
        _fail("audit_request_digest_mismatch")
    return {**payload, "audit_request_sha256": digest}


__all__ = [
    "AcceptanceAuditError", "build_acceptance_audit_request", "parse_acceptance_audit_request",
]
