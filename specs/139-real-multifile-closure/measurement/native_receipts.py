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

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SOURCE_ROOT = re.compile(r"^evolution/candidates/[A-Za-z0-9][A-Za-z0-9_.-]*$")
_RUN_ROOT = re.compile(r"^evolution/bundle-attempts/\.bundle-run-[0-9a-f]{24}$")


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


def _unknown(*, budget_id: str, bundle_sha256: str, reason_code: str) -> dict[str, object]:
    return {
        "schema_version": "1",
        "stage": "candidate_generation",
        "outcome": "unknown",
        "completion": False,
        "budget_id": budget_id,
        "bundle_sha256": bundle_sha256,
        "reason_code": reason_code,
    }


def candidate_generation_receipt(
    events: Sequence[Mapping[str, Any]],
    *,
    budget_id: str,
    bundle_sha256: str,
) -> dict[str, object]:
    """Project a parser-gated completion only from a bound durable diagnostic.

    ``AgentEvolutionGenerator`` emits a safe completion diagnostic, but the
    current controller does not persist it and the emitted payload lacks the
    parsed source-bundle digest.  A candidate archive record proves later
    persistence, execution, and evaluation; it cannot supply that missing
    generation predicate.  Those current events therefore produce an explicit
    unknown result rather than a synthetic completed receipt.
    """
    if type(events) not in (list, tuple):
        raise NativeReceiptError("invalid_events")
    budget_id = _id(budget_id, "budget_id")
    bundle_sha256 = _digest(bundle_sha256, "bundle_sha256")
    matches: list[Mapping[str, Any]] = []
    for event in events:
        if type(event) is not dict or event.get("type") != "agent_candidate_generation":
            continue
        payload = event.get("payload")
        if type(payload) is not dict:
            continue
        # A future product event needs this link to the source bundle accepted
        # by the native parser.  The Feature 136 event has neither field.
        if payload.get("budget_id") == budget_id and payload.get("source_bundle_sha256") == bundle_sha256:
            matches.append(payload)
    if not matches:
        return _unknown(
            budget_id=budget_id,
            bundle_sha256=bundle_sha256,
            reason_code="candidate_generation_diagnostic_unpersisted_or_unbound",
        )
    if len(matches) != 1:
        return _unknown(
            budget_id=budget_id,
            bundle_sha256=bundle_sha256,
            reason_code="candidate_generation_diagnostic_ambiguous",
        )
    payload = matches[0]
    required = {
        "schema_version", "stage", "outcome", "reason", "completion", "budget_id",
        "max_tool_steps", "tool_steps_used", "tool_steps_remaining", "attempted_tool_calls",
        "source_bundle_sha256", "candidate_id",
    }
    if set(payload) != required:
        return _unknown(
            budget_id=budget_id,
            bundle_sha256=bundle_sha256,
            reason_code="candidate_generation_diagnostic_schema_invalid",
        )
    if (payload["schema_version"] != "1" or payload["stage"] != "candidate_generation"
            or payload["outcome"] != "completed" or payload["reason"] != "completed"
            or payload["completion"] is not True):
        return _unknown(
            budget_id=budget_id,
            bundle_sha256=bundle_sha256,
            reason_code="candidate_generation_not_completed",
        )
    if (type(payload["max_tool_steps"]) is not int or payload["max_tool_steps"] < 1
            or type(payload["tool_steps_used"]) is not int or payload["tool_steps_used"] < 0
            or type(payload["tool_steps_remaining"]) is not int or payload["tool_steps_remaining"] < 0
            or payload["tool_steps_used"] + payload["tool_steps_remaining"]
            != payload["max_tool_steps"]
            or (payload["attempted_tool_calls"] is not None
                and (type(payload["attempted_tool_calls"]) is not int
                     or payload["attempted_tool_calls"] < 0))):
        return _unknown(
            budget_id=budget_id,
            bundle_sha256=bundle_sha256,
            reason_code="candidate_generation_diagnostic_budget_invalid",
        )
    try:
        candidate_id = _id(payload["candidate_id"], "candidate_id")
    except NativeReceiptError:
        return _unknown(
            budget_id=budget_id,
            bundle_sha256=bundle_sha256,
            reason_code="candidate_generation_identity_invalid",
        )
    return {
        "schema_version": "1",
        "stage": "candidate_generation",
        "outcome": "succeeded",
        "completion": True,
        "budget_id": budget_id,
        "bundle_sha256": bundle_sha256,
        "candidate_id": candidate_id,
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
