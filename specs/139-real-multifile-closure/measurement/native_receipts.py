"""Read-only projections of the native multi-file evidence boundary.

This module deliberately does not launch a solver, call a provider, invoke an
evaluator, or import candidate source.  It describes the minimum durable
facts a Feature 139 receipt must contain after a native run has ended.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from famou.candidate_generation_receipt import (
    CandidateGenerationReceiptError,
    build_candidate_generation_receipt,
    generation_event_id,
)

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SOURCE_ROOT = re.compile(r"^evolution/candidates/[A-Za-z0-9][A-Za-z0-9_.-]*$")
_RUN_ROOT = re.compile(r"^evolution/bundle-attempts/\.bundle-run-[0-9a-f]{24}$")
_GENERATION_EVENT = "agent_candidate_generation"
_EVENT_KEYS = {"id", "task_id", "type", "payload", "created_at"}


class NativeReceiptError(ValueError):
    """A retained native event cannot support the requested measurement claim."""


def _digest(value: object, name: str) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise NativeReceiptError(f"invalid_{name}")
    return value


def _id(value: object, name: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise NativeReceiptError(f"invalid_{name}")
    return value


def _unknown(
    *, run_id: str, task_id: str, budget_id: str, bundle_sha256: str, reason_code: str,
) -> dict[str, object]:
    return {
        "schema_version": "1",
        "stage": "candidate_generation",
        "outcome": "unknown",
        "completion": False,
        "run_id": run_id,
        "task_id": task_id,
        "budget_id": budget_id,
        "bundle_sha256": bundle_sha256,
        "reason_code": reason_code,
    }


def _native_generation_receipt(event: dict[str, Any], *, run_id: str) -> dict[str, Any]:
    """Validate the Store envelope and its exact Feature 140 canonical payload."""
    if (set(event) not in (_EVENT_KEYS, _EVENT_KEYS | {"run_id"})
            or event["type"] != _GENERATION_EVENT
            or type(event["created_at"]) is not str or not event["created_at"]):
        raise NativeReceiptError("candidate_generation_diagnostic_schema_invalid")
    payload = event["payload"]
    if type(payload) is not dict or "run_id" not in payload or "task_id" not in payload:
        raise NativeReceiptError("candidate_generation_diagnostic_schema_invalid")
    if (payload["run_id"] != run_id or event.get("run_id", run_id) != run_id
            or event["task_id"] != payload["task_id"]):
        raise NativeReceiptError("candidate_generation_identity_invalid")
    try:
        receipt = build_candidate_generation_receipt(
            payload, run_id=run_id, task_id=payload["task_id"],
        )
    except (CandidateGenerationReceiptError, TypeError, ValueError):
        raise NativeReceiptError("candidate_generation_diagnostic_schema_invalid") from None
    # The builder also accepts transient generator diagnostics. Retained Store
    # events must already be canonical, with no omitted or discarded fields.
    if receipt != payload:
        raise NativeReceiptError("candidate_generation_diagnostic_schema_invalid")
    if event["id"] != generation_event_id(receipt):
        raise NativeReceiptError("candidate_generation_event_identity_invalid")
    return receipt


def candidate_generation_receipt(
    events: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    task_id: str,
    budget_id: str,
    candidate_id: str,
    bundle_sha256: str,
    max_tool_steps: int,
) -> dict[str, object]:
    """Project a parser-gated completion only from a bound durable diagnostic.

    Feature 140 persists a canonical diagnostic with the parser-accepted source
    digest and a deterministic run/task/budget event ID. ``events`` must be the
    retained Store event list for ``run_id``. Caller pins identify the expected
    generation request and verified native bundle manifest; they cannot be
    inferred from an archive or from the diagnostic being checked. This is a
    read-only evidence projection, not an execution or source-byte verification.
    """
    if type(events) not in (list, tuple):
        raise NativeReceiptError("invalid_events")
    run_id = _id(run_id, "run_id")
    task_id = _id(task_id, "task_id")
    budget_id = _id(budget_id, "budget_id")
    candidate_id = _id(candidate_id, "candidate_id")
    bundle_sha256 = _digest(bundle_sha256, "bundle_sha256")
    if type(max_tool_steps) is not int or not 1 <= max_tool_steps <= 200:
        raise NativeReceiptError("invalid_max_tool_steps")
    expected_id = generation_event_id({
        "run_id": run_id, "task_id": task_id, "budget_id": budget_id,
    })
    identity = {"run_id": run_id, "task_id": task_id, "budget_id": budget_id,
                "bundle_sha256": bundle_sha256}
    matches: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for event in events:
        if type(event) is not dict:
            return _unknown(**identity, reason_code="candidate_generation_diagnostic_schema_invalid")
        if event.get("type") != _GENERATION_EVENT and event.get("id") != expected_id:
            continue
        try:
            payload = _native_generation_receipt(event, run_id=run_id)
        except NativeReceiptError as exc:
            return _unknown(**identity, reason_code=str(exc))
        if event["id"] in seen:
            return _unknown(**identity, reason_code="candidate_generation_diagnostic_ambiguous")
        seen.add(event["id"])
        # Match the request identity before inspecting its outcome/source. A
        # conflicting or failed receipt for this budget must not disappear.
        if payload["task_id"] == task_id and payload["budget_id"] == budget_id:
            matches.append(payload)
    if not matches:
        return _unknown(**identity, reason_code="candidate_generation_diagnostic_missing")
    if len(matches) != 1:
        return _unknown(**identity, reason_code="candidate_generation_diagnostic_ambiguous")
    payload = matches[0]
    if payload["max_tool_steps"] != max_tool_steps:
        return _unknown(**identity, reason_code="candidate_generation_diagnostic_budget_invalid")
    if payload["outcome"] != "completed":
        return _unknown(**identity, reason_code="candidate_generation_not_completed")
    if payload["candidate_id"] != candidate_id:
        return _unknown(**identity, reason_code="candidate_generation_identity_invalid")
    if payload["source_bundle_sha256"] != bundle_sha256:
        return _unknown(**identity, reason_code="candidate_generation_source_mismatch")
    return {
        "schema_version": "1",
        "stage": "candidate_generation",
        "outcome": "succeeded",
        "completion": True,
        **identity,
        "event_id": expected_id,
        "candidate_id": candidate_id,
        **{key: payload[key] for key in (
            "max_tool_steps", "tool_steps_used", "tool_steps_remaining", "attempted_tool_calls",
        )},
        "diagnostic_sha256": hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest(),
    }


def bundle_evidence_receipt(evidence: Mapping[str, Any]) -> dict[str, str]:
    """Validate the immutable bundle execution/evaluation binding shape.

    This is a structural projection only.  Callers that need to establish
    successful execution or scoring must use the product's read-only
    ``validate_candidate_bundle_evidence`` inspection against the retained
    workspace, never this metadata alone.
    """
    if type(evidence) is not dict:
        raise NativeReceiptError("invalid_bundle_evidence")
    expected = {
        "protocol", "bundle_sha256", "bundle_path", "source_root", "run_root",
        "plan_sha256", "admission_sha256", "completion_sha256", "evaluation_path",
        "evaluation_sha256",
    }
    if set(evidence) != expected or evidence.get("protocol") != "lunar-population-bundle-v1":
        raise NativeReceiptError("invalid_bundle_evidence")
    for key in ("bundle_sha256", "plan_sha256", "admission_sha256", "completion_sha256", "evaluation_sha256"):
        _digest(evidence[key], key)
    if (type(evidence["source_root"]) is not str or _SOURCE_ROOT.fullmatch(evidence["source_root"]) is None
            or type(evidence["run_root"]) is not str or _RUN_ROOT.fullmatch(evidence["run_root"]) is None
            or evidence["bundle_path"] != evidence["source_root"] + "/bundle-manifest.json"
            or type(evidence["evaluation_path"]) is not str
            or re.fullmatch(re.escape(evidence["run_root"]) + r"/evaluations/\.candidate-evaluation-[0-9a-f]{24}", evidence["evaluation_path"]) is None):
        raise NativeReceiptError("invalid_bundle_evidence")
    return {key: evidence[key] for key in sorted(expected) if key != "protocol"}
