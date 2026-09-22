"""Provider-free structural observer for a draft acceptance evidence chain.

The observer is deliberately read-only: it validates canonical manifest and stage
receipts, and optionally reuses the native candidate-generation receipt parser. It
never launches a model, executes candidate code, evaluates an artifact, or mutates
Store state.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from .candidate_generation_receipt import (
    CandidateGenerationReceiptError,
    inspect_candidate_generation_events,
)

SCHEMA_VERSION = "1"
STAGES = ("preparation", "generation", "execution", "scoring", "selection", "delivery")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_ROOT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_PRIVATE = re.compile(r"(?i)(prompt|response|credential|secret|token|endpoint|url|exception|traceback)")
_BUDGET_KEYS = frozenset({"request_timeout_seconds", "preparation_request_timeout_seconds", "preparation_wall_seconds", "solve_wall_seconds", "request_ceiling", "observed_token_ceiling"})
# Fixed values from the registered real-acceptance plan. A changed value requires a
# separate plan and observer contract; this parser never silently broadens the budget.
DEFAULT_ACCEPTANCE_BUDGETS = MappingProxyType({
    "request_timeout_seconds": 600,
    "preparation_request_timeout_seconds": 900,
    "preparation_wall_seconds": 1860,
    "solve_wall_seconds": 3000,
    "request_ceiling": 20,
    "observed_token_ceiling": 160000,
})
_MANIFEST_KEYS = frozenset({
    "schema_version", "scope", "registration_id", "campaign_id", "attempt_id", "product_commit",
    "campaign_root", "task_sha256", "input_sha256", "evaluator_sha256", "provider", "model",
    "runtime", "budgets", "manifest_sha256",
})
_RECEIPT_KEYS = frozenset({
    "schema_version", "stage", "receipt_id", "outcome", "manifest_sha256",
    "preceding_stage_id", "artifact_sha256", "observed_ms",
})


class AcceptanceObservationError(ValueError):
    """A manifest or evidence receipt is not safe to admit to the observer."""

    def __init__(self, code: str) -> None:
        self.code = code if isinstance(code, str) and re.fullmatch(r"[a-z0-9_]+", code) else "invalid"
        super().__init__(self.code)


def _fail(code: str) -> None:
    raise AcceptanceObservationError(code)


def _canonical(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise AcceptanceObservationError("manifest_not_json") from exc


def _text(value: object, pattern: re.Pattern[str], code: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        _fail(code)
    return value


def _sha(value: object, code: str) -> str:
    return _text(value, _SHA, code)


def _bounded_int(value: object, code: str, *, maximum: int) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        _fail(code)
    return value


def _reject_private(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(key, str) and key not in _BUDGET_KEYS and _PRIVATE.search(key):
                _fail("private_manifest_field")
            _reject_private(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _reject_private(nested)


def _manifest_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _MANIFEST_KEYS - {"manifest_sha256"}:
        _fail("manifest_schema_invalid")
    _reject_private(value)
    if value.get("schema_version") != SCHEMA_VERSION or value.get("scope") != "observation_manifest":
        _fail("manifest_schema_invalid")
    for key in ("registration_id", "campaign_id", "attempt_id"):
        _text(value.get(key), _ID, f"invalid_{key}")
    if value["attempt_id"] != "attempt-001":
        _fail("invalid_attempt_id")
    _text(value.get("product_commit"), _COMMIT, "invalid_product_commit")
    _text(value.get("campaign_root"), _ROOT, "invalid_campaign_root")
    for key in ("task_sha256", "input_sha256", "evaluator_sha256"):
        _sha(value.get(key), f"invalid_{key}")
    _text(value.get("provider"), _ID, "invalid_provider")
    _text(value.get("model"), _ID, "invalid_model")
    _text(value.get("runtime"), _ID, "invalid_runtime")
    budgets = value.get("budgets")
    if not isinstance(budgets, Mapping) or set(budgets) != _BUDGET_KEYS:
        _fail("invalid_budgets")
    if any(type(budgets[key]) is not int for key in _BUDGET_KEYS) or dict(budgets) != DEFAULT_ACCEPTANCE_BUDGETS:
        _fail("budgets_do_not_match_plan")
    return {**value, "budgets": dict(budgets)}


def manifest_sha256(manifest: Mapping[str, Any]) -> str:
    """Return the digest of a manifest payload without its self-referential digest."""
    payload = _manifest_payload({key: value for key, value in manifest.items() if key != "manifest_sha256"})
    return hashlib.sha256(_canonical(payload)).hexdigest()


def build_acceptance_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Canonicalize an observation manifest draft; this is not launch preregistration."""
    value = _manifest_payload(payload)
    digest = hashlib.sha256(_canonical(value)).hexdigest()
    return {**value, "manifest_sha256": digest}


def parse_acceptance_manifest(value: Mapping[str, Any] | str) -> dict[str, Any]:
    """Parse a canonical manifest from a mapping or JSON text without filesystem access."""
    if isinstance(value, str):
        def pairs(items):
            result = {}
            for key, item in items:
                if key in result:
                    _fail("manifest_duplicate_key")
                result[key] = item
            return result
        try:
            loaded = json.loads(value, object_pairs_hook=pairs)
            if _canonical(loaded).decode("utf-8") != value:
                _fail("manifest_noncanonical")
        except AcceptanceObservationError:
            raise
        except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
            raise AcceptanceObservationError("manifest_json_invalid") from exc
        if not isinstance(loaded, dict):
            _fail("manifest_schema_invalid")
        value = loaded
    if not isinstance(value, Mapping) or set(value) != _MANIFEST_KEYS:
        _fail("manifest_schema_invalid")
    payload = _manifest_payload({key: item for key, item in value.items() if key != "manifest_sha256"})
    digest = _sha(value.get("manifest_sha256"), "manifest_digest_invalid")
    if digest != hashlib.sha256(_canonical(payload)).hexdigest():
        _fail("manifest_digest_mismatch")
    if _canonical(value) != _canonical({**payload, "manifest_sha256": digest}):
        _fail("manifest_noncanonical")
    return {**payload, "manifest_sha256": digest}


def _receipt(value: Mapping[str, Any], manifest_digest: str, preceding: str | None) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _RECEIPT_KEYS:
        _fail("receipt_schema_invalid")
    if value.get("schema_version") != SCHEMA_VERSION:
        _fail("receipt_schema_invalid")
    stage = value.get("stage")
    if type(stage) is not str or stage not in STAGES:
        _fail("receipt_stage_invalid")
    _text(value.get("receipt_id"), _ID, "receipt_identity_invalid")
    if type(value.get("outcome")) is not str or value.get("outcome") not in {"succeeded", "failed", "unknown"}:
        _fail("receipt_outcome_invalid")
    if value.get("manifest_sha256") != manifest_digest:
        _fail("receipt_manifest_mismatch")
    if value.get("preceding_stage_id") != preceding:
        _fail("receipt_order_invalid")
    artifact = value.get("artifact_sha256")
    if value["outcome"] == "succeeded" and artifact is None:
        _fail("receipt_artifact_missing")
    if artifact is not None:
        _sha(artifact, "receipt_artifact_invalid")
    _bounded_int(value.get("observed_ms"), "receipt_observation_invalid", maximum=86_400_000)
    return dict(value)


def observe_acceptance_evidence(
    manifest: Mapping[str, Any] | str,
    receipts: Sequence[Mapping[str, Any]],
    *,
    generation_events: Sequence[Mapping[str, Any]] | None = None,
    generation_run_id: str | None = None,
    generation_task_id: str | None = None,
) -> dict[str, Any]:
    """Return a safe read-only stage projection for one registered attempt.

    Receipts must form an ordered prefix of the six planned stages. A missing later
    stage is reported as ``absent``. Structural closure cannot establish primary success;
    an independent artifact audit is still required, so primary/joint remain zero.
    When generation events are supplied they are validated by the native parser.
    """
    parsed_manifest = parse_acceptance_manifest(manifest)
    digest = parsed_manifest["manifest_sha256"]
    if not isinstance(receipts, Sequence) or isinstance(receipts, (str, bytes)):
        _fail("receipts_invalid")
    if len(receipts) > len(STAGES):
        _fail("receipt_count_invalid")
    observed: dict[str, dict[str, Any]] = {}
    preceding = None
    receipt_ids: set[str] = set()
    terminal_stage = False
    for index, raw in enumerate(receipts):
        item = _receipt(raw, digest, preceding)
        if terminal_stage:
            _fail("receipt_after_non_success")
        if item["receipt_id"] in receipt_ids:
            _fail("duplicate_receipt_id")
        receipt_ids.add(item["receipt_id"])
        terminal_stage = item["outcome"] != "succeeded"
        expected_stage = STAGES[index]
        if item["stage"] != expected_stage or item["stage"] in observed:
            _fail("receipt_order_invalid")
        observed[item["stage"]] = item
        preceding = item["receipt_id"]
    generation_summary: dict[str, Any] | None = None
    if generation_events is not None:
        if not isinstance(generation_run_id, str) or not isinstance(generation_task_id, str):
            _fail("generation_identity_missing")
        try:
            generation_summary = inspect_candidate_generation_events(
                list(generation_events), run_id=generation_run_id, task_id=generation_task_id,
            )
        except CandidateGenerationReceiptError as exc:
            raise AcceptanceObservationError("generation_receipt_invalid") from exc
        generation = observed.get("generation")
        if generation is None:
            _fail("generation_stage_missing")
        if generation is not None:
            for event in generation_events:
                if not isinstance(event, Mapping):
                    _fail("generation_receipt_invalid")
                if event.get("type") == "agent_candidate_generation":
                    payload = event["payload"]
                    if payload["max_tool_steps"] != 12:
                        _fail("generation_budget_mismatch")
                    if payload["outcome"] == "completed" and payload["source_bundle_sha256"] != generation["artifact_sha256"]:
                        _fail("generation_source_mismatch")
            completed = generation_summary["completed"] == 1
            if (generation["outcome"] == "succeeded") != completed:
                _fail("generation_outcome_mismatch")
    stages = {
        stage: {
            "outcome": observed[stage]["outcome"] if stage in observed else "absent",
            **({"receipt_id": observed[stage]["receipt_id"]} if stage in observed else {}),
        }
        for stage in STAGES
    }
    first_problem = next((stage for stage in STAGES if stages[stage]["outcome"] in {"failed", "unknown", "absent"}), None)
    complete = first_problem is None
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "chain_complete" if complete else ("failed" if first_problem and stages[first_problem]["outcome"] == "failed" else "incomplete"),
        "registration_id": parsed_manifest["registration_id"],
        "campaign_id": parsed_manifest["campaign_id"],
        "attempt_id": parsed_manifest["attempt_id"],
        "manifest_sha256": digest,
        "stages": stages,
        "first_problem_stage": first_problem,
        "preparation_success": "0/1",
        "validation_scope": "receipt_chain_only",
        "chain_complete": complete,
        "primary_success": "0/1",
        "joint_success": "0/1",
        **({"generation_receipt": generation_summary} if generation_summary is not None else {}),
    }


__all__ = [
    "DEFAULT_ACCEPTANCE_BUDGETS",
    "STAGES",
    "AcceptanceObservationError",
    "build_acceptance_manifest",
    "manifest_sha256",
    "observe_acceptance_evidence",
    "parse_acceptance_manifest",
]
