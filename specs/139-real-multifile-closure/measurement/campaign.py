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
    "outcome", "previous_receipt_sha256", "receipt_sha256", "task_sha256",
    "budget_sha256", "request_ledger_sha256", "request_count", "stage_run_sha256",
    "started_at", "finished_at",
}
_STAGE_PAYLOAD_KEYS = {
    "preparation": {"evaluator_sha256", "holdout_sha256"},
    "candidate_generation": {
        "candidate_id", "source_sha256", "file_count", "run_id", "task_id", "budget_id",
    },
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
    "cleanup": {"verified", "native_exit_code", "process_exit_code"},
}
_REQUEST_TIMEOUTS = {"ordinary": 600, "preparation": 900}
_REQUEST_STAGES = {
    "contract_compiler", "evaluator_compiler", "evaluator_auditor", "candidate_generation",
    "unrelated",
}
_PREPARATION_REQUEST_STAGES = {
    "contract_compiler", "evaluator_compiler", "evaluator_auditor",
}
_REQUEST_BOUND_STAGES = {"preparation", "candidate_generation"}


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
    closed_at_index: int | None = None
    known_observed_tokens: int = 0
    usage_complete: bool = True
    preparation_wall_seconds: float = 1860
    campaign_started_at: float | None = None
    provider_finished_at: float | None = None
    preparation_started_at: float | None = None
    preparation_finished_at: float | None = None
    closed_at_time: float | None = None
    closed_reason: str | None = None
    terminal_outcome: str | None = None
    stage_bindings: dict[str, tuple[int, ...]] = field(default_factory=dict)
    _closure_state_digest: str | None = field(default=None, repr=False)

    @property
    def closure_index(self) -> int | None:
        """Stable public alias for the first closure request index."""
        return self.closed_at_index

    @property
    def closure_time(self) -> float | None:
        """Stable public alias for the first closure monotonic timestamp."""
        return self.closed_at_time

    @property
    def closure_reason(self) -> str | None:
        """Stable public alias for the first closure reason."""
        return self.closed_reason

    @property
    def closure_digest(self) -> str | None:
        """Digest of the ledger state captured at first closure."""
        return self._closure_state_digest

    def _state_digest(self) -> str:
        """Hash mutable accounting state without including the closure anchor."""
        return digest_json({
            "max_requests": self.max_requests,
            "wall_seconds": self.wall_seconds,
            "token_stop_threshold": self.token_stop_threshold,
            "preparation_wall_seconds": self.preparation_wall_seconds,
            "requests": self.requests,
            "known_observed_tokens": self.known_observed_tokens,
            "usage_complete": self.usage_complete,
            "campaign_started_at": self.campaign_started_at,
            "provider_finished_at": self.provider_finished_at,
            "preparation_started_at": self.preparation_started_at,
            "preparation_finished_at": self.preparation_finished_at,
        })

    def _closure_anchor_digest(self) -> str:
        return digest_json({
            "state_sha256": self._state_digest(),
            "index": self.closed_at_index,
            "time": self.closed_at_time,
            "reason": self.closed_reason,
            "outcome": self.terminal_outcome,
        })

    def config_digest(self) -> str:
        return digest_json({
            "max_requests": self.max_requests,
            "wall_seconds": self.wall_seconds,
            "token_stop_threshold": self.token_stop_threshold,
            "preparation_wall_seconds": self.preparation_wall_seconds,
            "request_timeout_seconds": _REQUEST_TIMEOUTS["ordinary"],
            "preparation_request_timeout_seconds": _REQUEST_TIMEOUTS["preparation"],
        })

    def prefix_digest(self, count: int | None = None) -> str:
        """Digest the immutable ledger policy and request prefix used by a receipt."""
        if count is None:
            count = len(self.requests)
        if type(count) is not int or count < 0 or count > len(self.requests):
            raise CampaignError("request_ledger_prefix_invalid")
        return digest_json({
            "config": self.config_digest(),
            "request_count": count,
            "requests": self.requests[:count],
            "stage_bindings": {
                stage: indices for stage, indices in self.stage_bindings.items()
                if all(index <= count for index in indices)
            },
        })

    def bind_stage(self, stage: str, request_indices: list[int] | tuple[int, ...]) -> None:
        if stage not in _REQUEST_BOUND_STAGES:
            raise CampaignError("unknown_stage")
        if stage in self.stage_bindings:
            raise CampaignError("duplicate_stage_binding")
        if (type(request_indices) not in (list, tuple) or not request_indices
                or any(type(index) is not int or index < 1 or index > len(self.requests)
                       or not self.requests[index - 1]["finished"] for index in request_indices)
                or len(set(request_indices)) != len(request_indices)):
            raise CampaignError("stage_binding_invalid")
        rows = [self.requests[index - 1] for index in request_indices]
        if stage == "preparation":
            actual = [row["native_stage"] for row in rows]
            expected = ["contract_compiler", "evaluator_compiler", "evaluator_auditor"]
            if (actual != expected[:len(actual)]
                    or any(row["request_kind"] != "preparation" for row in rows)):
                raise CampaignError("stage_binding_invalid")
        elif stage == "candidate_generation":
            identities = {
                (row["run_id"], row["task_id"], row["budget_id"])
                for row in rows
            }
            expected_indices = tuple(range(request_indices[0], request_indices[-1] + 1))
            if (tuple(request_indices) != expected_indices
                    or any(row["native_stage"] != "candidate_generation"
                    or row["request_kind"] != "ordinary"
                    or any(row[key] is None for key in ("run_id", "task_id", "budget_id"))
                    for row in rows)
                    or len(identities) != 1):
                raise CampaignError("stage_binding_invalid")
        for bound_stage, bound_indices in self.stage_bindings.items():
            if (bound_stage in _REQUEST_BOUND_STAGES and stage in _REQUEST_BOUND_STAGES
                    and set(bound_indices) & set(request_indices)):
                raise CampaignError("stage_binding_invalid")
        self.stage_bindings[stage] = tuple(request_indices)

    def _close(
        self,
        index: int,
        *,
        now: float | None = None,
        reason: str = "explicit",
        outcome: str | None = None,
    ) -> None:
        if now is None:
            finished = [row["finished_at"] for row in self.requests if row["finished_at"] is not None]
            now = finished[-1] if finished else self.campaign_started_at
            if now is None:
                now = 0.0
        if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
            raise CampaignError("attempt_time_invalid")
        if self.campaign_started_at is not None and now < self.campaign_started_at:
            raise CampaignError("request_time_invalid")
        if self.closed:
            # A second close is only an idempotent observation of the exact
            # state that produced the first closure proof.
            if (
                index != self.closed_at_index
                or now != self.closed_at_time
                or reason != self.closed_reason
                or (outcome is not None and outcome != self.terminal_outcome)
                or self._closure_anchor_digest() != self._closure_state_digest
            ):
                raise CampaignError("closure_anchor_mismatch")
            return
        self.closed = True
        self.closed_at_index = index
        self.closed_at_time = now
        self.closed_reason = reason
        self.terminal_outcome = outcome or (
            "completed" if self.requests and all(row["finished"] and row["outcome"] == "completed"
                                                  for row in self.requests)
            else "unknown"
        )
        self.provider_finished_at = now
        if self.preparation_started_at is not None and self.preparation_finished_at is None:
            prep_finished = [
                row["finished_at"] for row in self.requests
                if row["request_kind"] == "preparation" and row["finished_at"] is not None
            ]
            if prep_finished:
                self.preparation_finished_at = prep_finished[-1]
        self._closure_state_digest = self._closure_anchor_digest()

    def begin(
        self,
        *,
        index: int | None = None,
        now: float = 0.0,
        timeout_seconds: float | None = None,
        request_kind: str = "ordinary",
        native_stage: str = "unrelated",
        run_id: str | None = None,
        task_id: str | None = None,
        budget_id: str | None = None,
        request_sha256: str | None = None,
    ) -> dict[str, Any]:
        if self.closed:
            raise CampaignError("request_slot_closed")
        if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
            raise CampaignError("attempt_time_invalid")
        if self.campaign_started_at is None:
            # Ledger timestamps are elapsed monotonic seconds from attempt launch.
            self.campaign_started_at = 0.0
        deadline = self.campaign_started_at + self.wall_seconds
        if (self.preparation_started_at is not None and self.preparation_finished_at is None
                and now - self.preparation_started_at >= self.preparation_wall_seconds):
            preparation_deadline = self.preparation_started_at + self.preparation_wall_seconds
            self._close(
                len(self.requests), now=preparation_deadline,
                reason="preparation_wall", outcome="failed",
            )
            raise CampaignError("preparation_wall_exceeded")
        if now >= deadline:
            self._close(len(self.requests), now=now, reason="attempt_wall", outcome="failed")
            raise CampaignError("attempt_deadline_reached")
        expected = len(self.requests) + 1
        if index is not None and (type(index) is not int or index != expected):
            raise CampaignError("request_index_not_sequential")
        if any(not row["finished"] for row in self.requests):
            raise CampaignError("pending_request")
        if self.requests and now < self.requests[-1]["finished_at"]:
            raise CampaignError("request_time_invalid")
        if expected > self.max_requests:
            self._close(len(self.requests), now=now, reason="max_requests", outcome="failed")
            raise CampaignError("request_limit_reached")
        timeout_cap = _REQUEST_TIMEOUTS.get(request_kind) if type(request_kind) is str else None
        if timeout_cap is None:
            raise CampaignError("invalid_request_kind")
        if timeout_seconds is None:
            timeout_seconds = min(timeout_cap, deadline - now)
        if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
                or timeout_seconds <= 0 or timeout_seconds > timeout_cap):
            raise CampaignError("invalid_request_timeout")
        if timeout_seconds > deadline - now:
            raise CampaignError("request_timeout_exceeds_attempt_wall")
        if native_stage not in _REQUEST_STAGES:
            raise CampaignError("invalid_native_request_stage")
        if (request_kind == "preparation") is not (native_stage in _PREPARATION_REQUEST_STAGES):
            raise CampaignError("request_stage_kind_mismatch")
        preparation_rows = [row for row in self.requests if row["request_kind"] == "preparation"]
        if request_kind == "preparation":
            expected_stage = (
                "contract_compiler", "evaluator_compiler", "evaluator_auditor",
            )[len(preparation_rows)] if len(preparation_rows) < 3 else None
            if native_stage != expected_stage:
                raise CampaignError("preparation_request_order_invalid")
        elif native_stage == "candidate_generation" and (
                [row["native_stage"] for row in preparation_rows]
                != ["contract_compiler", "evaluator_compiler", "evaluator_auditor"]
                or any(not row["finished"] or row["outcome"] != "completed"
                       for row in preparation_rows)):
            raise CampaignError("preparation_phase_incomplete")
        identity_values = (run_id, task_id, budget_id)
        if native_stage == "candidate_generation":
            if any(type(value) is not str or not _ID.fullmatch(value) for value in identity_values):
                raise CampaignError("request_identity_invalid")
        elif any(value is not None for value in identity_values):
            raise CampaignError("request_identity_invalid")
        if request_sha256 is None:
            request_sha256 = digest_json({
                "index": expected, "native_stage": native_stage, "run_id": run_id,
                "task_id": task_id, "budget_id": budget_id,
            })
        _safe_digest(request_sha256, "request_digest")
        if request_kind == "preparation":
            if self.preparation_started_at is None:
                self.preparation_started_at = now
            elif now - self.preparation_started_at >= self.preparation_wall_seconds:
                preparation_deadline = self.preparation_started_at + self.preparation_wall_seconds
                self._close(
                    len(self.requests), now=preparation_deadline,
                    reason="preparation_wall", outcome="failed",
                )
                raise CampaignError("preparation_wall_exceeded")
            self.preparation_finished_at = None
        row = {"index": expected, "started_at": now, "timeout_seconds": timeout_seconds,
               "request_kind": request_kind, "native_stage": native_stage,
               "run_id": run_id, "task_id": task_id, "budget_id": budget_id,
               "request_sha256": request_sha256,
               "finished": False, "finished_at": None, "outcome": None,
               "observed_tokens": None, "transport_status": None,
               "terminal_reason": None}
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
        if not self.requests or type(index) is not int or index != len(self.requests):
            raise CampaignError("request_finish_order")
        row = self.requests[index - 1]
        if row["finished"]:
            raise CampaignError("duplicate_request_finish")
        if outcome not in {"completed", "failed", "unknown"}:
            raise CampaignError("invalid_request_outcome")
        if type(now) not in (int, float) or not math.isfinite(now) or now < row["started_at"]:
            raise CampaignError("request_time_invalid")
        if observed_tokens is not None and (type(observed_tokens) is not int or observed_tokens < 0):
            raise CampaignError("invalid_observed_tokens")
        if transport_status is not None and (type(transport_status) is not int or not 100 <= transport_status <= 599):
            raise CampaignError("invalid_transport_status")
        deadline = (self.campaign_started_at if self.campaign_started_at is not None else 0) + self.wall_seconds
        if now > row["started_at"] + row["timeout_seconds"] or now > deadline:
            request_deadline = row["started_at"] + row["timeout_seconds"]
            # The whole-attempt deadline owns an exact tie so the terminal
            # reason stays consistent with the campaign-wide audit policy.
            reason = "request_deadline" if request_deadline < deadline else "attempt_wall"
            row.update({"finished": True, "finished_at": min(now, request_deadline, deadline),
                        "outcome": "unknown", "observed_tokens": None,
                        "transport_status": None, "terminal_reason": reason})
            self.usage_complete = False
            self._close(index, now=row["finished_at"], reason=reason, outcome="failed")
            raise CampaignError("request_deadline_exceeded")
        if row["request_kind"] == "preparation":
            if self.preparation_started_at is None:
                self.preparation_started_at = row["started_at"]
            preparation_deadline = self.preparation_started_at + self.preparation_wall_seconds
            if now >= preparation_deadline:
                self.preparation_finished_at = preparation_deadline
                row.update({"finished": True, "finished_at": preparation_deadline,
                            "outcome": "unknown",
                            "observed_tokens": None, "transport_status": None,
                            "terminal_reason": "preparation_wall"})
                self.usage_complete = False
                self._close(
                    index, now=preparation_deadline,
                    reason="preparation_wall", outcome="failed",
                )
                raise CampaignError("preparation_wall_exceeded")
            self.preparation_finished_at = now
        row.update({"finished": True, "finished_at": now, "outcome": outcome,
                    "observed_tokens": observed_tokens, "transport_status": transport_status,
                    "terminal_reason": None})
        if observed_tokens is None:
            self.usage_complete = False
        else:
            self.known_observed_tokens += observed_tokens
        if (now >= deadline or outcome != "completed"
                or self.known_observed_tokens >= self.token_stop_threshold
                or index == self.max_requests):
            reason = (
                "attempt_wall" if now >= deadline else
                "request_failed" if outcome != "completed" else
                "token_stop" if self.known_observed_tokens >= self.token_stop_threshold else
                "max_requests"
            )
            row["terminal_reason"] = reason
            terminal_outcome = "failed" if reason == "attempt_wall" else outcome
            self._close(index, now=now, reason=reason, outcome=terminal_outcome)
        return copy.deepcopy(row)

    def close(self, *, now: float | None = None) -> None:
        if self.closed:
            if now is not None and now != self.closed_at_time:
                raise CampaignError("closure_anchor_mismatch")
            self.audit()
            return
        if any(not row["finished"] for row in self.requests):
            raise CampaignError("pending_request")
        last_finished = self.requests[-1]["finished_at"] if self.requests else self.campaign_started_at
        if now is None:
            now = last_finished if last_finished is not None else 0.0
        if type(now) not in (int, float) or not math.isfinite(now):
            raise CampaignError("attempt_time_invalid")
        if last_finished is not None and now < last_finished:
            raise CampaignError("request_time_invalid")
        deadline = ((self.campaign_started_at if self.campaign_started_at is not None else now)
                    + self.wall_seconds)
        if now >= deadline:
            self._close(len(self.requests), now=now, reason="attempt_wall", outcome="failed")
        else:
            self._close(len(self.requests), now=now, reason="manual_close", outcome="completed")

    def snapshot(self) -> dict[str, Any]:
        audit = self.audit()
        return {key: audit[key] for key in (
            "provider_requests", "finished_requests", "pending_requests", "observed_tokens",
            "usage_complete", "transport_statuses", "closed",
        )}

    def successful_finalization(self) -> bool:
        return self.audit()["ledger_finalized"]

    def audit(self) -> dict[str, Any]:
        """Validate append-only request accounting without inferring unknown usage."""
        if (type(self.max_requests) is not int or self.max_requests < 1
                or type(self.wall_seconds) not in (int, float) or not math.isfinite(self.wall_seconds)
                or self.wall_seconds <= 0 or type(self.token_stop_threshold) is not int
                or self.token_stop_threshold < 0 or type(self.closed) is not bool
                or (self.closed_at_index is not None
                    and (type(self.closed_at_index) is not int or self.closed_at_index < 0))
                or type(self.known_observed_tokens) is not int or self.known_observed_tokens < 0
                or type(self.usage_complete) is not bool or type(self.requests) is not list
                or type(self.preparation_wall_seconds) not in (int, float)
                or not math.isfinite(self.preparation_wall_seconds) or self.preparation_wall_seconds <= 0
                or len(self.requests) > self.max_requests):
            raise CampaignError("request_ledger_invalid")
        known_observed_tokens = 0
        usage_complete = True
        pending: list[int] = []
        transport_statuses: list[int | None] = []
        previous_finished_at: float | int | None = None
        terminal_index: int | None = None
        derived_campaign_started_at = (
            0.0 if self.requests or self.closed or self.campaign_started_at is not None else None
        )
        deadline = ((derived_campaign_started_at + self.wall_seconds)
                    if derived_campaign_started_at is not None else None)
        preparation_rows: list[dict[str, Any]] = []
        for expected, row in enumerate(self.requests, start=1):
            if terminal_index is not None:
                raise CampaignError("request_ledger_invalid")
            if (type(row) is not dict or set(row) != {
                    "index", "started_at", "timeout_seconds", "request_kind", "native_stage",
                    "run_id", "task_id", "budget_id", "request_sha256", "finished", "finished_at",
                    "outcome", "observed_tokens", "transport_status", "terminal_reason",
                } or type(row["index"]) is not int or row["index"] != expected
                    or type(row["finished"]) is not bool):
                raise CampaignError("request_ledger_invalid")
            timeout_cap = (_REQUEST_TIMEOUTS.get(row["request_kind"])
                           if type(row["request_kind"]) is str else None)
            if (type(row["started_at"]) not in (int, float) or not math.isfinite(row["started_at"])
                    or row["started_at"] < 0
                    or deadline is not None and row["started_at"] >= deadline
                    or previous_finished_at is None and expected > 1
                    or previous_finished_at is not None and row["started_at"] < previous_finished_at
                    or type(row["timeout_seconds"]) not in (int, float)
                    or not math.isfinite(row["timeout_seconds"]) or row["timeout_seconds"] <= 0
                    or timeout_cap is None or row["timeout_seconds"] > timeout_cap
                    or deadline is not None and row["timeout_seconds"] > deadline - row["started_at"]):
                raise CampaignError("request_ledger_invalid")
            if (row["native_stage"] not in _REQUEST_STAGES
                    or (row["request_kind"] == "preparation")
                    is not (row["native_stage"] in _PREPARATION_REQUEST_STAGES)
                    or type(row["request_sha256"]) is not str
                    or _HEX64.fullmatch(row["request_sha256"]) is None):
                raise CampaignError("request_ledger_invalid")
            identities = (row["run_id"], row["task_id"], row["budget_id"])
            if row["native_stage"] == "candidate_generation":
                if any(type(value) is not str or not _ID.fullmatch(value) for value in identities):
                    raise CampaignError("request_ledger_invalid")
            elif any(value is not None for value in identities):
                raise CampaignError("request_ledger_invalid")
            if row["request_kind"] == "preparation":
                preparation_rows.append(row)
                expected_stage = (
                    "contract_compiler", "evaluator_compiler", "evaluator_auditor",
                )[len(preparation_rows) - 1] if len(preparation_rows) <= 3 else None
                if row["native_stage"] != expected_stage:
                    raise CampaignError("request_ledger_invalid")
            elif row["native_stage"] == "candidate_generation" and (
                    [item["native_stage"] for item in preparation_rows]
                    != ["contract_compiler", "evaluator_compiler", "evaluator_auditor"]
                    or any(not item["finished"] or item["outcome"] != "completed"
                           for item in preparation_rows)):
                raise CampaignError("request_ledger_invalid")
            if row["finished"]:
                if (type(row["outcome"]) is not str or row["outcome"] not in {"completed", "failed", "unknown"}
                        or type(row["finished_at"]) not in (int, float)
                        or not math.isfinite(row["finished_at"])
                        or row["finished_at"] < row["started_at"]
                        or row["finished_at"] > row["started_at"] + row["timeout_seconds"]
                        or deadline is not None and row["finished_at"] > deadline
                        or (row["observed_tokens"] is not None
                            and (type(row["observed_tokens"]) is not int or row["observed_tokens"] < 0))
                        or (row["transport_status"] is not None
                            and (type(row["transport_status"]) is not int
                                 or not 100 <= row["transport_status"] <= 599))
                        or (row["terminal_reason"] is not None
                            and row["terminal_reason"] not in {
                                "request_failed", "token_stop", "attempt_wall", "max_requests",
                                "preparation_wall", "request_deadline",
                            })):
                    raise CampaignError("request_ledger_invalid")
                previous_finished_at = row["finished_at"]
                if row["observed_tokens"] is None:
                    usage_complete = False
                else:
                    known_observed_tokens += row["observed_tokens"]
                transport_statuses.append(row["transport_status"])
                inferred_reason = (
                    "attempt_wall" if deadline is not None and row["finished_at"] >= deadline else
                    "request_failed" if row["outcome"] != "completed" else
                    "token_stop" if known_observed_tokens >= self.token_stop_threshold else
                    "max_requests" if expected == self.max_requests else None
                )
                if row["terminal_reason"] in {"request_deadline", "preparation_wall"}:
                    preparation_deadline = (
                        preparation_rows[0]["started_at"] + self.preparation_wall_seconds
                        if preparation_rows else None
                    )
                    if (row["outcome"] != "unknown"
                            or row["observed_tokens"] is not None
                            or row["transport_status"] is not None
                            or row["terminal_reason"] == "request_deadline"
                            and row["finished_at"] != min(
                                row["started_at"] + row["timeout_seconds"], deadline,
                            )
                            or row["terminal_reason"] == "preparation_wall"
                            and (row["request_kind"] != "preparation"
                                 or preparation_deadline is None
                                 or row["finished_at"] != preparation_deadline)):
                        raise CampaignError("request_ledger_invalid")
                    inferred_reason = row["terminal_reason"]
                if row["terminal_reason"] != inferred_reason:
                    raise CampaignError("request_ledger_invalid")
                if inferred_reason is not None:
                    terminal_index = expected
            else:
                if any(row[key] is not None for key in (
                        "finished_at", "outcome", "observed_tokens", "transport_status",
                        "terminal_reason",
                )):
                    raise CampaignError("request_ledger_invalid")
                pending.append(expected)
                previous_finished_at = None
        if (type(self.stage_bindings) is not dict
                or any(type(stage) is not str or stage not in _REQUEST_BOUND_STAGES
                       or type(indices) is not tuple or not indices
                       or len(set(indices)) != len(indices)
                       or any(type(index) is not int or index < 1 or index > len(self.requests)
                              or not self.requests[index - 1]["finished"] for index in indices)
                       for stage, indices in self.stage_bindings.items())):
            raise CampaignError("request_ledger_invalid")
        for stage, indices in self.stage_bindings.items():
            rows = [self.requests[index - 1] for index in indices]
            if (stage == "preparation" and (
                    [row["native_stage"] for row in rows]
                    != ["contract_compiler", "evaluator_compiler", "evaluator_auditor"][:len(rows)]
                    or any(row["request_kind"] != "preparation" for row in rows))):
                raise CampaignError("request_ledger_invalid")
            if (stage == "candidate_generation" and (
                    tuple(indices) != tuple(range(indices[0], indices[-1] + 1))
                    or any(row["native_stage"] != "candidate_generation"
                           or row["request_kind"] != "ordinary"
                           or any(row[key] is None for key in ("run_id", "task_id", "budget_id"))
                           for row in rows)
                    or len({
                        (row["run_id"], row["task_id"], row["budget_id"])
                        for row in rows
                    }) != 1)):
                raise CampaignError("request_ledger_invalid")
        bound_productive = [set(self.stage_bindings.get(stage, ())) for stage in _REQUEST_BOUND_STAGES]
        if bound_productive[0] & bound_productive[1]:
            raise CampaignError("request_ledger_invalid")
        if self.known_observed_tokens != known_observed_tokens or self.usage_complete is not usage_complete:
            raise CampaignError("request_ledger_invalid")
        if self.closed:
            if self.closed_at_index is None or self.closed_at_index > len(self.requests) or pending:
                raise CampaignError("request_ledger_invalid")
            if terminal_index is not None:
                if self.closed_at_index != terminal_index:
                    raise CampaignError("request_ledger_invalid")
            elif self.closed_at_index != len(self.requests):
                raise CampaignError("request_ledger_invalid")
            if (type(self.closed_at_time) not in (int, float) or not math.isfinite(self.closed_at_time)
                    or self.closed_at_time < 0 or type(self.closed_reason) is not str
                    or not self.closed_reason or type(self.terminal_outcome) is not str
                    or self._closure_state_digest != self._closure_anchor_digest()):
                raise CampaignError("request_ledger_invalid")
        elif self.closed_at_index is not None or terminal_index is not None:
            raise CampaignError("request_ledger_invalid")
        if self.campaign_started_at is not None and (
                type(self.campaign_started_at) not in (int, float)
                or not math.isfinite(self.campaign_started_at) or self.campaign_started_at < 0):
            raise CampaignError("request_ledger_invalid")
        for timestamp in (self.provider_finished_at, self.preparation_started_at, self.preparation_finished_at):
            if timestamp is not None and (type(timestamp) not in (int, float)
                                          or not math.isfinite(timestamp) or timestamp < 0):
                raise CampaignError("request_ledger_invalid")
        derived_preparation_started_at = preparation_rows[0]["started_at"] if preparation_rows else None
        derived_preparation_finished_at = (
            preparation_rows[-1]["finished_at"]
            if preparation_rows and all(row["finished"] for row in preparation_rows) else None
        )
        if (self.campaign_started_at != derived_campaign_started_at
                or self.preparation_started_at != derived_preparation_started_at
                or self.preparation_finished_at != derived_preparation_finished_at):
            raise CampaignError("request_ledger_invalid")
        if self.preparation_started_at is not None and self.preparation_finished_at is not None:
            if self.preparation_finished_at < self.preparation_started_at:
                raise CampaignError("request_ledger_invalid")
            if (self.preparation_finished_at - self.preparation_started_at
                    > self.preparation_wall_seconds
                    and not (self.closed and self.closed_reason == "preparation_wall"
                             and self.terminal_outcome == "failed")):
                raise CampaignError("preparation_wall_exceeded")
        if self.closed and self.provider_finished_at != self.closed_at_time:
            raise CampaignError("request_ledger_invalid")
        if self.closed:
            if terminal_index is not None:
                terminal = self.requests[terminal_index - 1]
                expected_reason = terminal["terminal_reason"]
                expected_time = terminal["finished_at"]
                expected_outcome = (
                    "failed" if expected_reason in {
                        "attempt_wall", "request_deadline", "preparation_wall",
                    }
                    else terminal["outcome"]
                )
            else:
                expected_reason = "manual_close"
                expected_time = self.requests[-1]["finished_at"] if self.requests else 0.0
                expected_outcome = "completed"
                if (self.preparation_started_at is not None
                        and self.preparation_finished_at is not None
                        and self.closed_at_time - self.preparation_started_at
                        > self.preparation_wall_seconds):
                    expected_reason = "preparation_wall"
                    expected_time = self.closed_at_time
                    expected_outcome = "failed"
                elif deadline is not None and self.closed_at_time >= deadline:
                    expected_reason = "attempt_wall"
                    expected_time = self.closed_at_time
                    expected_outcome = "failed"
            if (self.closed_reason != expected_reason or self.closed_at_time != expected_time
                    or self.terminal_outcome != expected_outcome):
                raise CampaignError("request_ledger_invalid")
        return {
            "provider_requests": len(self.requests),
            "finished_requests": len(self.requests) - len(pending),
            "pending_requests": pending,
            "observed_tokens": known_observed_tokens if usage_complete else None,
            "usage_complete": usage_complete,
            "transport_statuses": transport_statuses,
            "closed": self.closed,
            "ledger_finalized": bool(
                self.closed and self.requests
                and self.terminal_outcome == "completed"
                and self.closed_reason not in {"attempt_wall", "preparation_wall", "request_deadline",
                                               "max_requests", "request_failed"}
                and all(row["finished"] and row["outcome"] == "completed" for row in self.requests)
            ),
        }


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
    _manifest_sha256: str = field(init=False, repr=False)
    _ledger_object_id: int = field(init=False, repr=False)
    attempt_finished_at: float | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.manifest = validate_registration(
            self.manifest, head=self.registration_head, origin=self.registration_origin,
        )
        self._identity = _identity(self.manifest)
        self._manifest_sha256 = digest_json(self.manifest)
        self._ledger_object_id = id(self.ledger)
        self._receipt_chain_sha256 = digest_json({"schema_version": SCHEMA_VERSION, **self._identity})

    def _assert_manifest_sealed(self) -> None:
        """Reject any mutation of the registered launch contract."""
        try:
            current = digest_json(self.manifest)
        except (TypeError, ValueError, OverflowError):
            raise CampaignError("manifest_digest_mismatch") from None
        if current != self._manifest_sha256:
            raise CampaignError("manifest_digest_mismatch")
        if self._identity != _identity(self.manifest):
            raise CampaignError("manifest_identity_mismatch")

    def _assert_ledger_binding(self) -> None:
        # A caller may replace the ledger to inspect a deliberately failed
        # projection.  Existing receipts still remain immutable evidence; the
        # replacement is audited independently and cannot produce success.
        if id(self.ledger) != self._ledger_object_id:
            return
        budgets = self.manifest["budgets"]
        expected = {
            "max_requests": budgets["max_requests"],
            "wall_seconds": budgets["wall_seconds"],
            "token_stop_threshold": budgets["observed_token_stop"],
            "preparation_wall_seconds": budgets["preparation_wall_seconds"],
        }
        actual = {key: getattr(self.ledger, key) for key in expected}
        if actual != expected:
            raise CampaignError("request_ledger_binding_mismatch")
        if self.ledger.config_digest() != digest_json({
                **expected,
                "request_timeout_seconds": budgets["request_timeout_seconds"],
                "preparation_request_timeout_seconds": budgets["preparation_request_timeout_seconds"],
        }):
            raise CampaignError("request_ledger_binding_mismatch")

    @property
    def identity(self) -> dict[str, str]:
        return dict(self._identity)

    def _ensure_stage(self, stage: str) -> None:
        self._assert_manifest_sealed()
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

    def record(
        self,
        stage: str,
        *,
        outcome: str = "succeeded",
        started_at: float | None = None,
        finished_at: float | None = None,
        **payload: Any,
    ) -> dict[str, Any]:
        self._ensure_stage(stage)
        self._assert_ledger_binding()
        self.ledger.audit()
        if (self.ledger.requests and stage in _REQUEST_BOUND_STAGES
                and stage not in self.ledger.stage_bindings):
            raise CampaignError("stage_request_binding_missing")
        if outcome not in {"succeeded", "failed", "unknown"}:
            raise CampaignError("invalid_stage_outcome")
        if set(payload) != _STAGE_PAYLOAD_KEYS[stage]:
            raise CampaignError("receipt_schema_invalid")
        if any(_private_field(str(key)) or key in _RECEIPT_BASE_KEYS for key in payload):
            raise CampaignError("private_evidence_not_public")
        binding = self.ledger.stage_bindings.get(stage)
        request_count = max(binding) if binding else len(self.ledger.requests)
        if binding:
            bound_rows = [self.ledger.requests[index - 1] for index in binding]
            default_started_at = bound_rows[0]["started_at"]
            default_finished_at = bound_rows[-1]["finished_at"]
        else:
            previous_finished = self.receipts[-1]["finished_at"] if self.receipts else None
            ledger_finished = (
                self.ledger.requests[-1]["finished_at"]
                if self.ledger.requests and self.ledger.requests[-1]["finished"] else None
            )
            default_started_at = previous_finished if previous_finished is not None else ledger_finished
            if default_started_at is None:
                default_started_at = self.ledger.campaign_started_at or 0.0
            default_finished_at = default_started_at
        if started_at is None:
            started_at = default_started_at
        if finished_at is None:
            finished_at = default_finished_at
        if binding and (started_at != default_started_at or finished_at != default_finished_at):
            raise CampaignError("stage_request_time_mismatch")
        origin = self.ledger.campaign_started_at
        if origin is None:
            origin = self.receipts[0]["started_at"] if self.receipts else started_at
        deadline = origin + self.ledger.wall_seconds
        previous_finished = self.receipts[-1]["finished_at"] if self.receipts else origin
        if (type(started_at) not in (int, float) or not math.isfinite(started_at)
                or type(finished_at) not in (int, float) or not math.isfinite(finished_at)
                or started_at < origin or started_at < previous_finished
                or finished_at < started_at or finished_at > deadline):
            raise CampaignError("stage_time_invalid")
        receipt = {"schema_version": SCHEMA_VERSION, **self._identity, "stage": stage,
                   "outcome": outcome, "previous_receipt_sha256": self._receipt_chain_sha256,
                   "task_sha256": self.manifest["task_sha256"],
                   "budget_sha256": digest_json(self.manifest["budgets"]),
                   "request_ledger_sha256": self.ledger.prefix_digest(request_count),
                   "request_count": request_count,
                   "stage_run_sha256": digest_json({"stage": stage, "outcome": outcome,
                                                     "started_at": started_at,
                                                     "finished_at": finished_at,
                                                     "payload": copy.deepcopy(payload)}),
                   "started_at": started_at, "finished_at": finished_at,
                   **copy.deepcopy(payload)}
        receipt["receipt_sha256"] = digest_json(receipt)
        self.receipts.append(receipt)
        self._receipt_chain_sha256 = digest_json({"previous": self._receipt_chain_sha256,
                                                  "receipt": receipt["receipt_sha256"]})
        if outcome != "succeeded":
            self._failed = True
        return copy.deepcopy(receipt)

    def preparation(self, *, evaluator_sha256: str, holdout_sha256: str,
                    outcome: str = "succeeded", started_at: float | None = None,
                    finished_at: float | None = None) -> dict[str, Any]:
        return self.record("preparation", outcome=outcome, started_at=started_at,
                           finished_at=finished_at,
                           evaluator_sha256=_safe_digest(evaluator_sha256, "evaluator_digest"),
                           holdout_sha256=_safe_digest(holdout_sha256, "holdout_digest"))

    def candidate_generation(self, candidate: Mapping[str, Any], *, outcome: str = "succeeded",
                             started_at: float | None = None,
                             finished_at: float | None = None) -> dict[str, Any]:
        parsed = parse_candidate(candidate) if outcome == "succeeded" else {
            "candidate_id": None, "source_sha256": None, "file_count": 0,
        }
        binding = self.ledger.stage_bindings.get("candidate_generation")
        request = self.ledger.requests[binding[0] - 1] if binding else None
        parsed.update({
            "run_id": request["run_id"] if request else None,
            "task_id": request["task_id"] if request else None,
            "budget_id": request["budget_id"] if request else None,
        })
        return self.record("candidate_generation", outcome=outcome, started_at=started_at,
                           finished_at=finished_at, **parsed)

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
        started_at: float | None = None,
        finished_at: float | None = None,
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
        return self.record("candidate_execution", outcome=outcome, started_at=started_at,
                           finished_at=finished_at, candidate_id=candidate_id,
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
        started_at: float | None = None,
        finished_at: float | None = None,
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
        return self.record("independent_scoring", outcome=outcome, started_at=started_at,
                           finished_at=finished_at, candidate_id=candidate_id,
                           execution_id=execution_id, evaluation_id=_id(evaluation_id, "evaluation_id"),
                           valid=valid, score=score, report_sha256=_safe_digest(report_sha256, "report_digest"))

    def selection(self, *, candidate_id: str, execution_id: str, evaluation_id: str,
                  outcome: str = "succeeded", started_at: float | None = None,
                  finished_at: float | None = None) -> dict[str, Any]:
        score = self._require_success("independent_scoring")
        if (candidate_id, execution_id, evaluation_id) != (score.get("candidate_id"), score.get("execution_id"), score.get("evaluation_id")):
            raise CampaignError("selection_identity_mismatch")
        if not score.get("valid"):
            self._failed = True
            raise CampaignError("invalid_candidate_cannot_be_selected")
        if type(score.get("score")) not in (int, float) or not math.isfinite(score["score"]):
            self._failed = True
            raise CampaignError("valid_candidate_score_missing")
        return self.record("selection", outcome=outcome, started_at=started_at,
                           finished_at=finished_at, candidate_id=candidate_id,
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
        started_at: float | None = None,
        finished_at: float | None = None,
    ) -> dict[str, Any]:
        selected = self._require_success("selection")
        execution = self._require_success("candidate_execution")
        if (candidate_id, execution_id, evaluation_id) != (selected.get("candidate_id"), selected.get("execution_id"), selected.get("evaluation_id")):
            raise CampaignError("delivery_identity_mismatch")
        if input_sha256 != execution.get("input_sha256") or source_sha256 != execution.get("source_sha256") or output_sha256 != execution.get("output_sha256"):
            raise CampaignError("delivery_integrity_mismatch")
        return self.record("parent_delivery", outcome=outcome, started_at=started_at,
                           finished_at=finished_at, candidate_id=candidate_id,
                           execution_id=execution_id, evaluation_id=evaluation_id,
                           source_sha256=_safe_digest(source_sha256, "source_digest"),
                           input_sha256=_safe_digest(input_sha256, "input_digest"),
                           output_sha256=_safe_digest(output_sha256, "output_digest"),
                           evidence_sha256=_safe_digest(evidence_sha256, "evidence_digest"))

    def holdouts(self, results: list[Mapping[str, Any]], *, outcome: str = "succeeded",
                 started_at: float | None = None,
                 finished_at: float | None = None) -> dict[str, Any]:
        self._ensure_stage("holdouts")
        delivery = self._require_success("parent_delivery")
        if len(results) != len(self.manifest["holdouts"]):
            raise CampaignError("holdout_count_mismatch")
        safe = []
        for expected, actual in zip(self.manifest["holdouts"], results):
            if (type(actual) is not dict
                    or set(actual) != {"index", "actual_value", "elapsed_seconds"}
                    or actual["index"] != expected["index"]
                    or type(actual["actual_value"]) is not int
                    or type(actual["elapsed_seconds"]) not in (int, float)
                    or not math.isfinite(actual["elapsed_seconds"])
                    or not 0 <= actual["elapsed_seconds"] <= self.manifest["budgets"]["holdout_seconds"]):
                raise CampaignError("holdout_evidence_invalid")
            safe.append({
                "index": actual["index"],
                "expected_value": expected["expected_value"],
                "actual_value": actual["actual_value"],
                "matched": actual["actual_value"] == expected["expected_value"],
                "elapsed_seconds": actual["elapsed_seconds"],
            })
        return self.record("holdouts", outcome=outcome, started_at=started_at,
                           finished_at=finished_at,
                           delivery_receipt_sha256=delivery["receipt_sha256"],
                           matched_count=sum(item["matched"] for item in safe), total=len(safe), results=safe)

    def cleanup(self, *, verified: bool, outcome: str = "succeeded",
                native_exit_code: int | None = 0, process_exit_code: int | None = 0,
                started_at: float | None = None,
                finished_at: float | None = None) -> dict[str, Any]:
        if (type(verified) is not bool
                or native_exit_code is not None and type(native_exit_code) is not int
                or process_exit_code is not None and type(process_exit_code) is not int):
            raise CampaignError("cleanup_evidence_invalid")
        receipt = self.record(
            "cleanup", outcome=outcome, started_at=started_at,
            finished_at=finished_at, verified=verified,
            native_exit_code=native_exit_code, process_exit_code=process_exit_code,
        )
        self.attempt_finished_at = receipt["finished_at"]
        return receipt

    def _require_success(self, stage: str) -> dict[str, Any]:
        rows = [row for row in self.receipts if row["stage"] == stage]
        if len(rows) != 1 or rows[0]["outcome"] != "succeeded":
            raise CampaignError(f"{stage}_receipt_missing")
        return rows[0]

    def audit(self) -> dict[str, Any]:
        """Revalidate all retained receipts and return bounded audit facts."""
        self._assert_manifest_sealed()
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
            origin = self.ledger.campaign_started_at
            if origin is None:
                origin = self.receipts[0]["started_at"] if self.receipts else 0.0
            if (type(row.get("started_at")) not in (int, float)
                    or not math.isfinite(row["started_at"])
                    or type(row.get("finished_at")) not in (int, float)
                    or not math.isfinite(row["finished_at"])
                    or row["started_at"] < origin
                    or previous is not None and row["started_at"] < previous["finished_at"]
                    or row["finished_at"] < row["started_at"]
                    or row["finished_at"] > origin + self.ledger.wall_seconds):
                raise CampaignError("receipt_time_invalid")
            self._assert_ledger_binding()
            self.ledger.audit()
            ledger_identity_matches = id(self.ledger) == self._ledger_object_id
            binding = self.ledger.stage_bindings.get(stage)
            if ledger_identity_matches and self.ledger.requests:
                if stage in _REQUEST_BOUND_STAGES:
                    if not binding:
                        raise CampaignError("receipt_request_binding_missing")
                    bound_rows = [self.ledger.requests[index - 1] for index in binding]
                    if (row["request_count"] != max(binding)
                            or row["started_at"] != bound_rows[0]["started_at"]
                            or row["finished_at"] != bound_rows[-1]["finished_at"]):
                        raise CampaignError("receipt_request_binding_mismatch")
                elif row["request_count"] != len(self.ledger.requests):
                    raise CampaignError("receipt_request_binding_mismatch")
            if ledger_identity_matches and (row.get("task_sha256") != self.manifest["task_sha256"]
                    or row.get("budget_sha256") != digest_json(self.manifest["budgets"])
                    or type(row.get("request_count")) is not int
                    or row["request_count"] < 0
                    or row["request_count"] > len(self.ledger.requests)
                    or row.get("request_ledger_sha256") != self.ledger.prefix_digest(row["request_count"])
                    or row.get("stage_run_sha256") != digest_json({
                        "stage": stage, "outcome": row["outcome"],
                        "started_at": row["started_at"], "finished_at": row["finished_at"],
                        "payload": {key: row[key] for key in _STAGE_PAYLOAD_KEYS[stage]},
                    })):
                raise CampaignError("receipt_binding_mismatch")
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
        cleanup = rows.get("cleanup")
        if (cleanup is None and self.attempt_finished_at is not None
                or cleanup is not None and self.attempt_finished_at != cleanup["finished_at"]):
            raise CampaignError("attempt_completion_anchor_mismatch")
        ledger = self.ledger.audit()
        return {"receipt_count": len(self.receipts), "stages": [row["stage"] for row in self.receipts],
                "one_attempt": self.manifest["planned_attempts"] == 1,
                "ledger_finalized": ledger["ledger_finalized"], "usage_complete": ledger["usage_complete"]}

    def _audit_stage_payload(self, stage: str, row: Mapping[str, Any], rows: Mapping[str, Mapping[str, Any]]) -> None:
        """Recheck semantic bindings from retained safe receipt metadata."""
        try:
            if stage == "preparation":
                _safe_digest(row["evaluator_sha256"], "evaluator_digest")
                _safe_digest(row["holdout_sha256"], "holdout_digest")
            elif stage == "candidate_generation":
                binding = self.ledger.stage_bindings.get("candidate_generation")
                request = (
                    self.ledger.requests[binding[0] - 1]
                    if binding else None
                )
                if request is not None and any(
                        row[key] != request[key] for key in ("run_id", "task_id", "budget_id")):
                    raise CampaignError("candidate_receipt_invalid")
                if row["outcome"] == "succeeded":
                    _id(row["candidate_id"], "candidate_id")
                    _safe_digest(row["source_sha256"], "source_digest")
                    if (type(row["file_count"]) is not int or row["file_count"] < 1
                            or request is not None and any(
                                type(row[key]) is not str or not _ID.fullmatch(row[key])
                                for key in ("run_id", "task_id", "budget_id")
                            )
                            or request is None and id(self.ledger) == self._ledger_object_id and any(
                                row[key] is not None for key in ("run_id", "task_id", "budget_id")
                            )):
                        raise CampaignError("candidate_receipt_invalid")
                elif (row["candidate_id"] is not None or row["source_sha256"] is not None
                      or row["file_count"] != 0):
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
                if any(type(actual) is not dict
                       or actual.get("index") != wanted["index"]
                       or type(actual.get("matched")) is not bool
                       for wanted, actual in zip(expected, row["results"])):
                    raise CampaignError("holdout_receipt_invalid")
                for wanted, actual in zip(expected, row["results"]):
                    if (set(actual) != {
                            "index", "expected_value", "actual_value", "matched",
                            "elapsed_seconds",
                    } or actual["expected_value"] != wanted["expected_value"]
                            or type(actual["actual_value"]) is not int
                            or actual["matched"]
                            is not (actual["actual_value"] == wanted["expected_value"])
                            or type(actual["elapsed_seconds"]) not in (int, float)
                            or not math.isfinite(actual["elapsed_seconds"])
                            or not 0 <= actual["elapsed_seconds"]
                            <= self.manifest["budgets"]["holdout_seconds"]):
                        raise CampaignError("holdout_receipt_invalid")
                if row["matched_count"] != sum(item["matched"] for item in row["results"]):
                    raise CampaignError("holdout_receipt_invalid")
            elif stage == "cleanup":
                if (type(row["verified"]) is not bool
                        or row["native_exit_code"] is not None
                        and type(row["native_exit_code"]) is not int
                        or row["process_exit_code"] is not None
                        and type(row["process_exit_code"]) is not int):
                    raise CampaignError("cleanup_receipt_invalid")
        except (KeyError, RegistrationError, TypeError):
            raise CampaignError("receipt_semantics_invalid") from None

    def public_result(self) -> dict[str, Any]:
        """Project only allow-listed metadata; private evidence never crosses this boundary."""
        audit = self.audit()
        ledger = self.ledger.audit()
        ledger_bound = id(self.ledger) == self._ledger_object_id
        statuses = {stage: "absent" for stage in _ALL_STAGES}
        for row in self.receipts:
            statuses[row["stage"]] = row["outcome"]
        completed_candidate = any(row["stage"] == "candidate_generation" and row["outcome"] == "succeeded" for row in self.receipts)
        required_bindings = set(_REQUEST_BOUND_STAGES)
        bound_indices = [
            index for stage in required_bindings
            for index in self.ledger.stage_bindings.get(stage, ())
        ]
        all_requests_bound_once = (
            len(bound_indices) == len(set(bound_indices)) == len(self.ledger.requests)
            and set(bound_indices) == set(range(1, len(self.ledger.requests) + 1))
        )
        primary = (all(statuses[stage] == "succeeded" for stage in STAGE_ORDER)
                   and completed_candidate and audit["ledger_finalized"] and ledger_bound
                   and required_bindings <= set(self.ledger.stage_bindings)
                   and all_requests_bound_once)
        holdout = next((row for row in self.receipts if row["stage"] == "holdouts"), None)
        cleanup = next((row for row in self.receipts if row["stage"] == "cleanup"), None)
        expected_holdout_count = len(self.manifest["holdouts"])
        joint = primary and bool(
            holdout
            and holdout.get("outcome") == "succeeded"
            and holdout.get("matched_count") == holdout.get("total") == expected_holdout_count
        )
        joint = joint and bool(
            cleanup and cleanup.get("outcome") == "succeeded"
            and cleanup.get("verified") is True
            and cleanup.get("native_exit_code") == 0
            and cleanup.get("process_exit_code") == 0
        )
        score = next((row.get("score") for row in self.receipts if row["stage"] == "independent_scoring"), None)
        return {
            **self._identity,
            "planned_attempts": self.manifest["planned_attempts"],
            "attempts": 1,
            "provider_requests": ledger["provider_requests"],
            "usage": {"observed_tokens": ledger["observed_tokens"], "complete": ledger["usage_complete"]},
            "transport": {"statuses": ledger["transport_statuses"]},
            "stages": statuses,
            "completed_candidate_count": int(completed_candidate),
            "holdouts": {"matched": holdout.get("matched_count", 0) if holdout else 0,
                         "total": holdout.get("total", expected_holdout_count) if holdout else expected_holdout_count},
            "score": score if type(score) in (int, float) and math.isfinite(score) else None,
            "primary_success": "1/1" if primary else "0/1",
            "joint_success": "1/1" if joint else "0/1",
            "receipt_digests": [row["receipt_sha256"] for row in self.receipts],
        }
