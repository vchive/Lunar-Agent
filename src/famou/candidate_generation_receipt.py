"""Safe, durable projection for native candidate-generation attempts.

The generator may observe provider/runtime diagnostics, but only this module decides which
metadata is allowed to cross into the Store.  Source text, prompts, transport details, and
exception prose are deliberately excluded.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

SCHEMA_VERSION = "1"
STAGE = "candidate_generation"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_OUTCOMES = frozenset({"completed", "failed", "unknown"})
_REASONS = frozenset({
    "completed", "worker_failed", "cancelled", "malformed_candidate", "tool_execution_failed",
    "tool_step_limit_reached", "timed_out", "empty_final_response", "candidate_failed",
    "unknown", "running",
})
_PRIVATE = re.compile(r"(?i)(prompt|response|credential|secret|token|endpoint|url|exception|traceback)")
_ALLOWED_INPUT_KEYS = frozenset({
    "schema_version", "stage", "outcome", "reason", "completion", "budget_id",
    "max_tool_steps", "tool_steps_used", "tool_steps_remaining", "attempted_tool_calls",
    "candidate_id", "source_bundle_sha256", "phase", "elapsed_ms", "timeout_ms",
    "run_id", "task_id",
})


class CandidateGenerationReceiptError(ValueError):
    """A generation diagnostic cannot be admitted to durable evidence."""


def _safe_id(value: object, name: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise CandidateGenerationReceiptError(f"invalid_{name}")
    return value


def _digest(value: object, name: str) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise CandidateGenerationReceiptError(f"invalid_{name}")
    return value


def _int(value: object, name: str, *, nullable: bool = False) -> int | None:
    if value is None and nullable:
        return None
    if type(value) is not int or value < 0:
        raise CandidateGenerationReceiptError(f"invalid_{name}")
    return value


def build_candidate_generation_receipt(
    payload: Mapping[str, Any],
    *,
    run_id: str,
    task_id: str,
) -> dict[str, Any]:
    """Return the strict safe event payload used by the Store observer.

    ``candidate_id`` and ``source_bundle_sha256`` are admitted only for parser-accepted
    completed bundles.  Failed/unknown attempts intentionally carry neither field.
    """
    if not isinstance(payload, Mapping):
        raise CandidateGenerationReceiptError("diagnostic_not_mapping")
    if any(key not in _ALLOWED_INPUT_KEYS for key in payload):
        raise CandidateGenerationReceiptError("diagnostic_schema_invalid")
    # ``source_bundle_sha256`` is the one source-related field allowed across the
    # evidence boundary.  Other source/response/credential-shaped names are
    # private diagnostics and must never be persisted.
    if any(
        isinstance(key, str)
        and key != "source_bundle_sha256"
        and _PRIVATE.search(key)
        for key in payload
    ):
        raise CandidateGenerationReceiptError("private_diagnostic_field")
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("stage") != STAGE:
        raise CandidateGenerationReceiptError("diagnostic_schema_invalid")
    run_id = _safe_id(run_id, "run_id")
    task_id = _safe_id(task_id, "task_id")
    if "run_id" in payload and payload["run_id"] != run_id:
        raise CandidateGenerationReceiptError("run_identity_mismatch")
    if "task_id" in payload and payload["task_id"] != task_id:
        raise CandidateGenerationReceiptError("task_identity_mismatch")
    raw_outcome = payload.get("outcome")
    reason = payload.get("reason", raw_outcome)
    if raw_outcome not in _OUTCOMES | _REASONS or reason not in _REASONS:
        raise CandidateGenerationReceiptError("invalid_outcome")
    if raw_outcome == "completed":
        outcome = "completed"
    elif raw_outcome == "unknown" or reason in {"unknown", "running"}:
        outcome = "unknown"
    else:
        outcome = "failed"
    if outcome == "completed" and reason != "completed":
        raise CandidateGenerationReceiptError("completed_reason_mismatch")
    completion = payload.get("completion")
    if type(completion) is not bool or completion != (outcome == "completed"):
        raise CandidateGenerationReceiptError("completion_outcome_mismatch")
    budget_id = _safe_id(payload.get("budget_id"), "budget_id")
    max_tool_steps = _int(payload.get("max_tool_steps"), "max_tool_steps")
    if max_tool_steps is None or not 1 <= max_tool_steps <= 200:
        raise CandidateGenerationReceiptError("invalid_max_tool_steps")
    used = _int(payload.get("tool_steps_used"), "tool_steps_used", nullable=True)
    remaining = _int(payload.get("tool_steps_remaining"), "tool_steps_remaining", nullable=True)
    attempted = _int(payload.get("attempted_tool_calls"), "attempted_tool_calls", nullable=True)
    if outcome == "completed":
        if used is None or remaining is None or used + remaining != max_tool_steps:
            raise CandidateGenerationReceiptError("invalid_tool_budget")
        candidate_id = _safe_id(payload.get("candidate_id"), "candidate_id")
        source_sha = _digest(payload.get("source_bundle_sha256"), "source_bundle_sha256")
    else:
        if "candidate_id" in payload or "source_bundle_sha256" in payload:
            raise CandidateGenerationReceiptError("failed_receipt_contains_candidate_identity")
        candidate_id = None
        source_sha = None
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "stage": STAGE,
        "run_id": run_id,
        "task_id": task_id,
        "budget_id": budget_id,
        "outcome": outcome,
        "reason": reason,
        "completion": completion,
        "max_tool_steps": max_tool_steps,
        "tool_steps_used": used,
        "tool_steps_remaining": remaining,
        "attempted_tool_calls": attempted,
    }
    if outcome == "completed":
        receipt["candidate_id"] = candidate_id
        receipt["source_bundle_sha256"] = source_sha
    return receipt


def generation_event_id(receipt: Mapping[str, Any]) -> str:
    """Derive an idempotency key from the bound run/task/budget identity."""
    try:
        identity = {key: receipt[key] for key in ("run_id", "task_id", "budget_id")}
    except KeyError as exc:
        raise CandidateGenerationReceiptError("receipt_identity_missing") from exc
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "event-agent-candidate-generation-" + hashlib.sha256(encoded).hexdigest()


def inspect_candidate_generation_events(
    events: list[Mapping[str, Any]], *, run_id: str, task_id: str,
) -> dict[str, Any]:
    """Read-only validation for retained generation receipts."""
    receipts: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, Mapping) or event.get("type") != "agent_candidate_generation":
            continue
        payload = event.get("payload")
        receipt = build_candidate_generation_receipt(payload, run_id=run_id, task_id=task_id)
        if event.get("id") != generation_event_id(receipt):
            raise CandidateGenerationReceiptError("event_identity_mismatch")
        receipts.append(receipt)
    if not receipts:
        raise CandidateGenerationReceiptError("generation_receipt_missing")
    budgets = [item["budget_id"] for item in receipts]
    if len(budgets) != len(set(budgets)):
        raise CandidateGenerationReceiptError("duplicate_generation_receipt")
    if any(item["outcome"] == "completed" for item in receipts) and len(receipts) != 1:
        raise CandidateGenerationReceiptError("conflicting_generation_receipts")
    return {"receipt_count": len(receipts), "completed": sum(item["outcome"] == "completed" for item in receipts)}


__all__ = [
    "CandidateGenerationReceiptError", "build_candidate_generation_receipt",
    "generation_event_id", "inspect_candidate_generation_events",
]
