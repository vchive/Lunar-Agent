"""Offline registration, bounded ledger, and six-stage closure fixtures.

This module is intentionally campaign-local.  It models evidence admission and
public projection; it does not invoke a provider, execute a candidate, or
modify the native product.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .case import (
    ATTEMPT_ID,
    CAMPAIGN_ID,
    CAMPAIGN_ROOT,
    MODEL,
    PRODUCT_COMMIT,
    REGISTRATION_ID,
    default_holdouts,
    expected_input_digest,
    expected_task_digest,
)

SCHEMA_VERSION = "1"
STAGE_ORDER = (
    "preparation",
    "candidate_generation",
    "candidate_execution",
    "independent_scoring",
    "selection",
    "parent_delivery",
)
_ALL_STAGES = (*STAGE_ORDER, "holdouts", "cleanup")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9.-]{2,127}$")
_PRIVATE_NAMES = {
    "prompt",
    "response",
    "response_body",
    "credential",
    "credentials",
    "endpoint",
    "url",
    "source",
    "generated_source",
    "exception",
    "traceback",
    "error_text",
}
_RECEIPT_BASE_KEYS = {
    "schema_version", "registration_id", "campaign_id", "attempt_id", "stage",
    "outcome", "previous_receipt_sha256", "receipt_sha256",
}
_STAGE_PAYLOAD_KEYS = {
    "preparation": {"evaluator_sha256", "holdout_sha256"},
    "candidate_generation": {"candidate_id", "source_sha256", "file_count"},
    "candidate_execution": {
        "candidate_id", "execution_id", "source_sha256", "input_sha256", "output_sha256", "exit_code",
    },
    "independent_scoring": {
        "candidate_id", "execution_id", "evaluation_id", "valid", "score", "report_sha256",
    },
    "selection": {"candidate_id", "execution_id", "evaluation_id"},
    "parent_delivery": {
        "candidate_id", "execution_id", "evaluation_id", "source_sha256", "input_sha256",
        "output_sha256", "evidence_sha256",
    },
    "holdouts": {"delivery_receipt_sha256", "matched_count", "total", "results"},
    "cleanup": {"verified"},
}


class RegistrationError(ValueError):
    """A registration or launch-preflight invariant is not satisfied."""


class CampaignError(ValueError):
    """A receipt, identity, ordering, or projection invariant is not satisfied."""


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_json(value: Any) -> str:
    return digest_bytes(canonical(value).encode("utf-8"))


def _digest(value: Any, *, field_name: str = "digest") -> str:
    if type(value) is not str or not _HEX64.fullmatch(value):
        raise CampaignError(f"invalid_{field_name}")
    return value


def _id(value: Any, field_name: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise RegistrationError(f"invalid_{field_name}")
    return value


def default_manifest() -> dict[str, Any]:
    """Return the fixed, non-secret values proposed by the Feature 139 SDD."""
    return {
        "schema_version": SCHEMA_VERSION,
        "registration_id": REGISTRATION_ID,
        "campaign_id": CAMPAIGN_ID,
        "attempt_id": ATTEMPT_ID,
        "campaign_root": CAMPAIGN_ROOT,
        "product_commit": PRODUCT_COMMIT,
        "provider": {"kind": "openai-compatible", "model": MODEL},
        "task_sha256": expected_task_digest(),
        "input_sha256": expected_input_digest(),
        "budgets": {
            "request_timeout_seconds": 600,
            "preparation_request_timeout_seconds": 900,
            "preparation_wall_seconds": 1860,
            "wall_seconds": 2400,
            "max_requests": 20,
            "observed_token_stop": 160000,
            "candidate_steps": 12,
            "holdout_seconds": 5,
        },
        "population": {"islands": 1, "members": 1, "offspring_per_round": 1, "rounds": 1},
        "planned_attempts": 1,
        "retries_or_replacements": 0,
        "holdouts": default_holdouts(),
    }


def validate_registration(
    manifest: Mapping[str, Any],
    *,
    head: str | None = None,
    origin: str | None = None,
    worktree_clean: bool = True,
    pushed: bool = True,
    existing_roots: set[str] | frozenset[str] = frozenset(),
    existing_ids: set[str] | frozenset[str] = frozenset(),
    historical_ids: set[str] | frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Validate the immutable launch contract before any provider request."""
    value = copy.deepcopy(dict(manifest))
    required = set(default_manifest())
    if set(value) != required:
        raise RegistrationError("manifest_schema_drift")
    if value["schema_version"] != SCHEMA_VERSION:
        raise RegistrationError("schema_version_mismatch")
    for field_name in ("registration_id", "campaign_id", "attempt_id"):
        _id(value[field_name], field_name)
    if value["registration_id"] in existing_ids or value["campaign_id"] in existing_ids:
        raise RegistrationError("duplicate_identity")
    if value["registration_id"] in historical_ids or value["campaign_id"] in historical_ids:
        raise RegistrationError("historical_identity_reuse")
    if value["attempt_id"] != ATTEMPT_ID:
        raise RegistrationError("attempt_slot_mismatch")
    root = value["campaign_root"]
    if (type(root) is not str or not root.startswith(".lunar/") or ".." in root.split("/")
            or root in existing_roots or root.endswith("/")):
        raise RegistrationError("campaign_root_unavailable")
    if root in {".lunar/acceptance131", ".lunar/acceptance134"}:
        raise RegistrationError("historical_root_reuse")
    if value["product_commit"] != PRODUCT_COMMIT:
        raise RegistrationError("product_pin_drift")
    provider = value["provider"]
    if (type(provider) is not dict or set(provider) != {"kind", "model"}
            or provider["kind"] != "openai-compatible" or provider["model"] != MODEL):
        raise RegistrationError("provider_identity_drift")
    if value["task_sha256"] != expected_task_digest() or value["input_sha256"] != expected_input_digest():
        raise RegistrationError("task_or_input_drift")
    budgets = value["budgets"]
    expected_budgets = default_manifest()["budgets"]
    if budgets != expected_budgets:
        raise RegistrationError("budget_drift")
    if value["population"] != default_manifest()["population"]:
        raise RegistrationError("population_drift")
    if value["planned_attempts"] != 1 or value["retries_or_replacements"] != 0:
        raise RegistrationError("one_slot_contract_violation")
    if value["holdouts"] != default_holdouts():
        raise RegistrationError("holdout_contract_drift")
    if not worktree_clean:
        raise RegistrationError("worktree_dirty")
    if (not pushed or type(head) is not str or not head
            or type(origin) is not str or not origin or head != origin):
        raise RegistrationError("registration_not_pushed")
    return value


@dataclass
class RequestLedger:
    """One-shot request accounting with no retry or post-slot admission."""

    max_requests: int = 20
    wall_seconds: float = 2400
    token_stop_threshold: int = 160000
    requests: list[dict[str, Any]] = field(default_factory=list)
    closed: bool = False
    known_observed_tokens: int = 0
    usage_complete: bool = True

    def begin(self, *, index: int | None = None, now: float = 0.0, timeout_seconds: float | None = None) -> dict[str, Any]:
        if self.closed:
            raise CampaignError("request_slot_closed")
        if not isinstance(now, (int, float)) or not math.isfinite(now) or now >= self.wall_seconds:
            self.closed = True
            raise CampaignError("attempt_deadline_reached")
        expected = len(self.requests) + 1
        if index is not None and index != expected:
            raise CampaignError("request_index_not_sequential")
        if any(not row["finished"] for row in self.requests):
            raise CampaignError("pending_request")
        if expected > self.max_requests:
            self.closed = True
            raise CampaignError("request_limit_reached")
        if timeout_seconds is None:
            timeout_seconds = min(600, self.wall_seconds - now)
        if (not isinstance(timeout_seconds, (int, float)) or not math.isfinite(timeout_seconds)
                or timeout_seconds <= 0):
            raise CampaignError("invalid_request_timeout")
        if timeout_seconds > self.wall_seconds - now:
            raise CampaignError("request_timeout_exceeds_attempt_wall")
        row = {"index": expected, "started_at": now, "timeout_seconds": timeout_seconds,
               "finished": False, "finished_at": None, "outcome": None,
               "observed_tokens": None, "transport_status": None}
        self.requests.append(row)
        return copy.deepcopy(row)

    def finish(
        self,
        index: int,
        *,
        outcome: str,
        now: float,
        observed_tokens: int | None = None,
        transport_status: int | None = None,
    ) -> dict[str, Any]:
        if not self.requests or index != len(self.requests):
            raise CampaignError("request_finish_order")
        row = self.requests[index - 1]
        if row["finished"]:
            raise CampaignError("duplicate_request_finish")
        if outcome not in {"completed", "failed", "unknown"}:
            raise CampaignError("invalid_request_outcome")
        if not isinstance(now, (int, float)) or not math.isfinite(now) or now < row["started_at"]:
            raise CampaignError("request_time_invalid")
        if observed_tokens is not None and (type(observed_tokens) is not int or observed_tokens < 0):
            raise CampaignError("invalid_observed_tokens")
        if transport_status is not None and (type(transport_status) is not int or not 100 <= transport_status <= 599):
            raise CampaignError("invalid_transport_status")
        if now > row["started_at"] + row["timeout_seconds"] or now > self.wall_seconds:
            row.update({"finished": True, "finished_at": min(now, self.wall_seconds), "outcome": "unknown",
                        "observed_tokens": None, "transport_status": None})
            self.usage_complete = False
            self.closed = True
            raise CampaignError("request_deadline_exceeded")
        row.update({"finished": True, "finished_at": now, "outcome": outcome,
                    "observed_tokens": observed_tokens, "transport_status": transport_status})
        if observed_tokens is None:
            self.usage_complete = False
        else:
            self.known_observed_tokens += observed_tokens
        if outcome != "completed" or self.known_observed_tokens >= self.token_stop_threshold or now >= self.wall_seconds:
            self.closed = True
        return copy.deepcopy(row)

    def close(self) -> None:
        if any(not row["finished"] for row in self.requests):
            raise CampaignError("pending_request")
        self.closed = True

    def snapshot(self) -> dict[str, Any]:
        pending = [row["index"] for row in self.requests if not row["finished"]]
        return {
            "provider_requests": len(self.requests),
            "finished_requests": len(self.requests) - len(pending),
            "pending_requests": pending,
            "observed_tokens": self.known_observed_tokens if self.usage_complete else None,
            "usage_complete": self.usage_complete,
            "transport_statuses": [row.get("transport_status") for row in self.requests if row["finished"]],
            "closed": self.closed,
        }

    def successful_finalization(self) -> bool:
        return bool(
            self.closed
            and self.requests
            and all(row["finished"] and row.get("outcome") == "completed" for row in self.requests)
        )

    def audit(self) -> dict[str, Any]:
        """Validate append-only request accounting without inferring unknown usage."""
        for expected, row in enumerate(self.requests, start=1):
            if (set(row) != {"index", "started_at", "timeout_seconds", "finished", "finished_at",
                            "outcome", "observed_tokens", "transport_status"}
                    or row["index"] != expected or type(row["finished"]) is not bool):
                raise CampaignError("request_ledger_invalid")
            if (not isinstance(row["started_at"], (int, float)) or not math.isfinite(row["started_at"])
                    or not isinstance(row["timeout_seconds"], (int, float))
                    or not math.isfinite(row["timeout_seconds"]) or row["timeout_seconds"] <= 0
                    or row["timeout_seconds"] > self.wall_seconds - row["started_at"]):
                raise CampaignError("request_ledger_invalid")
            if row["finished"]:
                if (row["outcome"] not in {"completed", "failed", "unknown"}
                        or not isinstance(row["finished_at"], (int, float))
                        or row["finished_at"] < row["started_at"]
                        or row["finished_at"] > row["started_at"] + row["timeout_seconds"]
                        or row["finished_at"] > self.wall_seconds):
                    raise CampaignError("request_ledger_invalid")
            elif any(item["finished"] for item in self.requests[expected:]):
                raise CampaignError("request_ledger_invalid")
        snapshot = self.snapshot()
        if snapshot["pending_requests"] and self.closed:
            raise CampaignError("request_ledger_invalid")
        return snapshot


def _identity(manifest: Mapping[str, Any]) -> dict[str, str]:
    return {key: manifest[key] for key in ("registration_id", "campaign_id", "attempt_id")}


def _private_field(key: str) -> bool:
    lowered = key.lower()
    return lowered in _PRIVATE_NAMES


def _safe_digest(value: Any, name: str) -> str:
    return _digest(value, field_name=name)


def parse_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Accept only a parser-complete, non-empty source bundle."""
    if type(candidate) is not dict:
        raise CampaignError("candidate_not_object")
    if candidate.get("diagnostic") != "completed":
        raise CampaignError("candidate_not_completed")
    candidate_id = candidate.get("candidate_id")
    if type(candidate_id) is not str or not _ID.fullmatch(candidate_id):
        raise CampaignError("candidate_id_invalid")
    files = candidate.get("files")
    if type(files) is not dict or not files:
        raise CampaignError("candidate_source_empty")
    if any(type(path) is not str or not path or path.startswith("/") or ".." in path.split("/")
            or not isinstance(content, str) or not content for path, content in files.items()):
        raise CampaignError("candidate_source_invalid")
    return {"candidate_id": candidate_id, "source_sha256": digest_json(files), "file_count": len(files)}


@dataclass
class ClosureCampaign:
    """Append-only synthetic stage evidence and its bounded public projection."""

    manifest: Mapping[str, Any]
    registration_head: str | None = None
    registration_origin: str | None = None
    receipts: list[dict[str, Any]] = field(default_factory=list)
    ledger: RequestLedger = field(default_factory=RequestLedger)
    _failed: bool = False
    _receipt_chain_sha256: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.manifest = validate_registration(
            self.manifest, head=self.registration_head, origin=self.registration_origin,
        )
        self._identity = _identity(self.manifest)
        self._receipt_chain_sha256 = digest_json({"schema_version": SCHEMA_VERSION, **self._identity})

    @property
    def identity(self) -> dict[str, str]:
        return dict(self._identity)

    def _ensure_stage(self, stage: str) -> None:
        if stage not in _ALL_STAGES:
            raise CampaignError("unknown_stage")
        # Cleanup is an observation of the consumed slot and remains recordable
        # after the first failed/unknown stage.  No productive stage may resume.
        if self._failed and stage != "cleanup":
            raise CampaignError("chain_stopped_after_failure")
        existing = [row["stage"] for row in self.receipts]
        if stage in existing:
            raise CampaignError("duplicate_stage")
        if stage in STAGE_ORDER:
            expected = STAGE_ORDER[len([item for item in existing if item in STAGE_ORDER])]
            if stage != expected:
                raise CampaignError("stage_out_of_order")
        elif stage == "holdouts" and "parent_delivery" not in existing:
            raise CampaignError("holdouts_before_delivery")
        elif stage == "cleanup" and not self._failed:
            if "parent_delivery" not in existing:
                raise CampaignError("cleanup_before_delivery")
            if "holdouts" not in existing:
                raise CampaignError("cleanup_before_holdouts")

    def record(self, stage: str, *, outcome: str = "succeeded", **payload: Any) -> dict[str, Any]:
        self._ensure_stage(stage)
        if outcome not in {"succeeded", "failed", "unknown"}:
            raise CampaignError("invalid_stage_outcome")
        if set(payload) != _STAGE_PAYLOAD_KEYS[stage]:
            raise CampaignError("receipt_schema_invalid")
        if any(_private_field(str(key)) or key in _RECEIPT_BASE_KEYS for key in payload):
            raise CampaignError("private_evidence_not_public")
        receipt = {"schema_version": SCHEMA_VERSION, **self._identity, "stage": stage,
                   "outcome": outcome, "previous_receipt_sha256": self._receipt_chain_sha256,
                   **copy.deepcopy(payload)}
        receipt["receipt_sha256"] = digest_json(receipt)
        self.receipts.append(receipt)
        self._receipt_chain_sha256 = digest_json({"previous": self._receipt_chain_sha256,
                                                  "receipt": receipt["receipt_sha256"]})
        if outcome != "succeeded":
            self._failed = True
        return copy.deepcopy(receipt)

    def preparation(self, *, evaluator_sha256: str, holdout_sha256: str, outcome: str = "succeeded") -> dict[str, Any]:
        return self.record("preparation", outcome=outcome,
                           evaluator_sha256=_safe_digest(evaluator_sha256, "evaluator_digest"),
                           holdout_sha256=_safe_digest(holdout_sha256, "holdout_digest"))

    def candidate_generation(self, candidate: Mapping[str, Any], *, outcome: str = "succeeded") -> dict[str, Any]:
        parsed = parse_candidate(candidate) if outcome == "succeeded" else {
            "candidate_id": None, "source_sha256": None, "file_count": 0,
        }
        return self.record("candidate_generation", outcome=outcome, **parsed)

    def candidate_execution(
        self,
        *,
        candidate_id: str,
        execution_id: str,
        source_sha256: str,
        input_sha256: str,
        output_sha256: str,
        exit_code: int,
        outcome: str = "succeeded",
    ) -> dict[str, Any]:
        previous = self._require_success("candidate_generation")
        if candidate_id != previous.get("candidate_id"):
            raise CampaignError("candidate_identity_mismatch")
        if source_sha256 != previous.get("source_sha256"):
            raise CampaignError("candidate_source_mismatch")
        if input_sha256 != self.manifest["input_sha256"]:
            raise CampaignError("execution_input_mismatch")
        if type(exit_code) is not int:
            raise CampaignError("execution_exit_code_invalid")
        return self.record("candidate_execution", outcome=outcome, candidate_id=candidate_id,
                           execution_id=_id(execution_id, "execution_id"), source_sha256=_safe_digest(source_sha256, "source_digest"),
                           input_sha256=_safe_digest(input_sha256, "input_digest"), output_sha256=_safe_digest(output_sha256, "output_digest"),
                           exit_code=exit_code)

    def independent_scoring(
        self,
        *,
        candidate_id: str,
        execution_id: str,
        evaluation_id: str,
        valid: bool,
        score: float | None,
        report_sha256: str,
        outcome: str = "succeeded",
        producer_score: Any = None,
    ) -> dict[str, Any]:
        execution = self._require_success("candidate_execution")
        if candidate_id != execution.get("candidate_id") or execution_id != execution.get("execution_id"):
            raise CampaignError("evaluation_identity_mismatch")
        if execution.get("exit_code") != 0:
            self._failed = True
            raise CampaignError("execution_not_successful")
        if (type(valid) is not bool
                or (score is not None and (type(score) not in (int, float) or not math.isfinite(score)))
                or (valid and score is None)
                or (not valid and score is not None)):
            raise CampaignError("evaluation_score_invalid")
        # producer_score is deliberately not copied to a receipt or used for ranking.
        del producer_score
        return self.record("independent_scoring", outcome=outcome, candidate_id=candidate_id,
                           execution_id=execution_id, evaluation_id=_id(evaluation_id, "evaluation_id"),
                           valid=valid, score=score, report_sha256=_safe_digest(report_sha256, "report_digest"))

    def selection(self, *, candidate_id: str, execution_id: str, evaluation_id: str, outcome: str = "succeeded") -> dict[str, Any]:
        score = self._require_success("independent_scoring")
        if (candidate_id, execution_id, evaluation_id) != (score.get("candidate_id"), score.get("execution_id"), score.get("evaluation_id")):
            raise CampaignError("selection_identity_mismatch")
        if not score.get("valid"):
            self._failed = True
            raise CampaignError("invalid_candidate_cannot_be_selected")
        if type(score.get("score")) not in (int, float) or not math.isfinite(score["score"]):
            self._failed = True
            raise CampaignError("valid_candidate_score_missing")
        return self.record("selection", outcome=outcome, candidate_id=candidate_id,
                           execution_id=execution_id, evaluation_id=evaluation_id)

    def parent_delivery(
        self,
        *,
        candidate_id: str,
        execution_id: str,
        evaluation_id: str,
        source_sha256: str,
        input_sha256: str,
        output_sha256: str,
        evidence_sha256: str,
        outcome: str = "succeeded",
    ) -> dict[str, Any]:
        selected = self._require_success("selection")
        execution = self._require_success("candidate_execution")
        if (candidate_id, execution_id, evaluation_id) != (selected.get("candidate_id"), selected.get("execution_id"), selected.get("evaluation_id")):
            raise CampaignError("delivery_identity_mismatch")
        if input_sha256 != execution.get("input_sha256") or source_sha256 != execution.get("source_sha256") or output_sha256 != execution.get("output_sha256"):
            raise CampaignError("delivery_integrity_mismatch")
        return self.record("parent_delivery", outcome=outcome, candidate_id=candidate_id,
                           execution_id=execution_id, evaluation_id=evaluation_id,
                           source_sha256=_safe_digest(source_sha256, "source_digest"),
                           input_sha256=_safe_digest(input_sha256, "input_digest"),
                           output_sha256=_safe_digest(output_sha256, "output_digest"),
                           evidence_sha256=_safe_digest(evidence_sha256, "evidence_digest"))

    def holdouts(self, results: list[Mapping[str, Any]]) -> dict[str, Any]:
        self._ensure_stage("holdouts")
        delivery = self._require_success("parent_delivery")
        if len(results) != len(self.manifest["holdouts"]):
            raise CampaignError("holdout_count_mismatch")
        safe = []
        for expected, actual in zip(self.manifest["holdouts"], results):
            if set(actual) != {"index", "matched"} or actual["index"] != expected["index"] or type(actual["matched"]) is not bool:
                raise CampaignError("holdout_evidence_invalid")
            safe.append(dict(actual))
        return self.record("holdouts", delivery_receipt_sha256=delivery["receipt_sha256"],
                           matched_count=sum(item["matched"] for item in safe), total=len(safe), results=safe)

    def cleanup(self, *, verified: bool, outcome: str = "succeeded") -> dict[str, Any]:
        if type(verified) is not bool:
            raise CampaignError("cleanup_evidence_invalid")
        return self.record("cleanup", outcome=outcome, verified=verified)

    def _require_success(self, stage: str) -> dict[str, Any]:
        rows = [row for row in self.receipts if row["stage"] == stage]
        if len(rows) != 1 or rows[0]["outcome"] != "succeeded":
            raise CampaignError(f"{stage}_receipt_missing")
        return rows[0]

    def audit(self) -> dict[str, Any]:
        """Revalidate all retained receipts and return bounded audit facts."""
        chain = digest_json({"schema_version": SCHEMA_VERSION, **self._identity})
        previous = None
        productive_index = 0
        failed = False
        seen_holdouts = False
        rows: dict[str, dict[str, Any]] = {}
        for row in self.receipts:
            stage = row.get("stage")
            if stage not in _ALL_STAGES or set(row) != _RECEIPT_BASE_KEYS | _STAGE_PAYLOAD_KEYS[stage]:
                raise CampaignError("receipt_schema_invalid")
            if set(self._identity) - set(row) or any(row[key] != value for key, value in self._identity.items()):
                raise CampaignError("receipt_identity_mismatch")
            if (row["schema_version"] != SCHEMA_VERSION or row.get("outcome") not in {"succeeded", "failed", "unknown"}
                    or row.get("previous_receipt_sha256") != chain
                    or row.get("receipt_sha256") != digest_json({k: v for k, v in row.items() if k != "receipt_sha256"})):
                raise CampaignError("receipt_digest_mismatch")
            if stage in rows:
                raise CampaignError("receipt_order_mismatch")
            if failed:
                if stage != "cleanup" or previous is None:
                    raise CampaignError("receipt_order_mismatch")
            elif stage in STAGE_ORDER:
                if productive_index >= len(STAGE_ORDER) or stage != STAGE_ORDER[productive_index]:
                    raise CampaignError("receipt_order_mismatch")
                productive_index += 1
            elif stage == "holdouts":
                if productive_index != len(STAGE_ORDER):
                    raise CampaignError("receipt_order_mismatch")
                seen_holdouts = True
            elif stage == "cleanup" and not seen_holdouts:
                # A failed scoring/execution path may terminate before holdouts;
                # cleanup is still the only permitted follow-up receipt.
                scoring = rows.get("independent_scoring")
                if not (scoring is not None and scoring.get("valid") is False):
                    raise CampaignError("receipt_order_mismatch")
            self._audit_stage_payload(stage, row, rows)
            rows[stage] = row
            chain = digest_json({"previous": chain, "receipt": row["receipt_sha256"]})
            if row["outcome"] != "succeeded":
                failed = True
            previous = row
        if chain != self._receipt_chain_sha256:
            raise CampaignError("receipt_chain_anchor_mismatch")
        ledger = self.ledger.audit()
        return {"receipt_count": len(self.receipts), "stages": [row["stage"] for row in self.receipts],
                "one_attempt": self.manifest["planned_attempts"] == 1,
                "ledger_finalized": self.ledger.successful_finalization(),
                "usage_complete": ledger["usage_complete"]}

    def _audit_stage_payload(self, stage: str, row: Mapping[str, Any], rows: Mapping[str, Mapping[str, Any]]) -> None:
        """Recheck semantic bindings from retained safe receipt metadata."""
        try:
            if stage == "preparation":
                _safe_digest(row["evaluator_sha256"], "evaluator_digest")
                _safe_digest(row["holdout_sha256"], "holdout_digest")
            elif stage == "candidate_generation":
                if row["outcome"] == "succeeded":
                    _id(row["candidate_id"], "candidate_id")
                    _safe_digest(row["source_sha256"], "source_digest")
                    if type(row["file_count"]) is not int or row["file_count"] < 1:
                        raise CampaignError("candidate_receipt_invalid")
                elif row["candidate_id"] is not None or row["source_sha256"] is not None or row["file_count"] != 0:
                    raise CampaignError("candidate_receipt_invalid")
            elif stage == "candidate_execution":
                generated = rows.get("candidate_generation")
                if (generated is None or row["candidate_id"] != generated["candidate_id"]
                        or row["source_sha256"] != generated["source_sha256"]
                        or row["input_sha256"] != self.manifest["input_sha256"]
                        or type(row["exit_code"]) is not int):
                    raise CampaignError("execution_receipt_invalid")
                _id(row["execution_id"], "execution_id")
                for key in ("source_sha256", "input_sha256", "output_sha256"):
                    _safe_digest(row[key], key)
            elif stage == "independent_scoring":
                execution = rows.get("candidate_execution")
                if (execution is None or execution["exit_code"] != 0
                        or (row["candidate_id"], row["execution_id"]) != (execution["candidate_id"], execution["execution_id"])
                        or type(row["valid"]) is not bool
                        or (row["valid"] and (type(row["score"]) not in (int, float) or not math.isfinite(row["score"])))
                        or (not row["valid"] and row["score"] is not None)):
                    raise CampaignError("scoring_receipt_invalid")
                _id(row["evaluation_id"], "evaluation_id")
                _safe_digest(row["report_sha256"], "report_digest")
            elif stage == "selection":
                score = rows.get("independent_scoring")
                if (score is None or not score["valid"]
                        or (row["candidate_id"], row["execution_id"], row["evaluation_id"])
                        != (score["candidate_id"], score["execution_id"], score["evaluation_id"])):
                    raise CampaignError("selection_receipt_invalid")
            elif stage == "parent_delivery":
                execution, selection = rows.get("candidate_execution"), rows.get("selection")
                if (execution is None or selection is None
                        or (row["candidate_id"], row["execution_id"], row["evaluation_id"])
                        != (selection["candidate_id"], selection["execution_id"], selection["evaluation_id"])
                        or any(row[key] != execution[key] for key in ("source_sha256", "input_sha256", "output_sha256"))):
                    raise CampaignError("delivery_receipt_invalid")
                _safe_digest(row["evidence_sha256"], "evidence_digest")
            elif stage == "holdouts":
                delivery = rows.get("parent_delivery")
                expected = self.manifest["holdouts"]
                if (delivery is None or row["delivery_receipt_sha256"] != delivery["receipt_sha256"]
                        or row["total"] != len(expected) or type(row["matched_count"]) is not int
                        or not isinstance(row["results"], list) or len(row["results"]) != len(expected)):
                    raise CampaignError("holdout_receipt_invalid")
                if any(type(actual) is not dict or set(actual) != {"index", "matched"}
                       or actual["index"] != wanted["index"] or type(actual["matched"]) is not bool
                       for wanted, actual in zip(expected, row["results"])):
                    raise CampaignError("holdout_receipt_invalid")
                if row["matched_count"] != sum(item["matched"] for item in row["results"]):
                    raise CampaignError("holdout_receipt_invalid")
            elif stage == "cleanup" and type(row["verified"]) is not bool:
                raise CampaignError("cleanup_receipt_invalid")
        except (KeyError, RegistrationError, TypeError):
            raise CampaignError("receipt_semantics_invalid") from None

    def public_result(self) -> dict[str, Any]:
        """Project only allow-listed metadata; private evidence never crosses this boundary."""
        audit = self.audit()
        ledger = self.ledger.snapshot()
        statuses = {stage: "absent" for stage in _ALL_STAGES}
        for row in self.receipts:
            statuses[row["stage"]] = row["outcome"]
        completed_candidate = any(row["stage"] == "candidate_generation" and row["outcome"] == "succeeded" for row in self.receipts)
        primary = (all(statuses[stage] == "succeeded" for stage in STAGE_ORDER)
                   and completed_candidate and audit["ledger_finalized"])
        holdout = next((row for row in self.receipts if row["stage"] == "holdouts"), None)
        cleanup = next((row for row in self.receipts if row["stage"] == "cleanup"), None)
        joint = primary and bool(holdout and holdout.get("matched_count") == holdout.get("total") == 8)
        joint = joint and bool(cleanup and cleanup.get("outcome") == "succeeded" and cleanup.get("verified") is True)
        score = next((row.get("score") for row in self.receipts if row["stage"] == "independent_scoring"), None)
        return {
            **self._identity,
            "planned_attempts": 1,
            "attempts": 1,
            "provider_requests": ledger["provider_requests"],
            "usage": {"observed_tokens": ledger["observed_tokens"], "complete": ledger["usage_complete"]},
            "transport": {"statuses": ledger["transport_statuses"]},
            "stages": statuses,
            "completed_candidate_count": int(completed_candidate),
            "holdouts": {"matched": holdout.get("matched_count", 0) if holdout else 0, "total": holdout.get("total", 8) if holdout else 8},
            "score": score if type(score) in (int, float) and math.isfinite(score) else None,
            "primary_success": "1/1" if primary else "0/1",
            "joint_success": "1/1" if joint else "0/1",
            "receipt_digests": [row["receipt_sha256"] for row in self.receipts],
        }
