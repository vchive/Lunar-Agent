"""Canonical execution and evaluation receipts for producer bundle publication.

The native multi-file pipeline already retains the authoritative plan, admission, execution
attempt, and independent evaluation trees.  This module projects those records into small,
portable receipts consumed by :mod:`producer_bundle_staging`.  The projection is deliberately
hash-oriented: it carries no process IDs, paths outside the journal, evaluator stdout, or
producer claims.  Receipt construction only inspects retained evidence and never executes or
retries a candidate.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import _benchmark_files as _files
from .candidate_evaluation import CandidateEvaluationResult
from .candidate_execution import admit_candidate_execution
from .candidate_execution_evidence import (
    CandidateExecutionRecord,
    inspect_candidate_execution_record,
)
from .candidate_workspace_plan import parse_candidate_workspace_plan
from .evolution import Candidate, CandidateIntegrityAuthority

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_MAX_RECEIPT_BYTES = 64 * 1024
_EXECUTION_FIELDS = {
    "schema_version", "protocol", "candidate_id", "bundle_sha256", "plan_sha256",
    "admission_sha256", "completion_sha256", "launch_intent_sha256", "result_sha256",
    "runner_result_sha256", "cleanup_sha256", "status", "runner_status", "cleanup_status",
    "receipt_sha256",
}
_EVALUATION_FIELDS = {
    "schema_version", "protocol", "candidate_id", "bundle_sha256", "plan_sha256",
    "admission_sha256", "completion_sha256", "evaluation_sha256", "binding", "report",
    "output_contract_valid", "harness_invoked", "status", "receipt_sha256",
}
_EXECUTION_PROTOCOL = "lunar-producer-bundle-execution-receipt-v1"
_EVALUATION_PROTOCOL = "lunar-producer-bundle-evaluation-receipt-v1"


class ProducerBundleReceiptError(ValueError):
    """Fixed-code failure while projecting retained native candidate evidence."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise ProducerBundleReceiptError(code)


def _digest(value: object, code: str = "producer_bundle_receipt_digest_invalid") -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail(code)
    return value


def _identifier(value: object, code: str = "producer_bundle_receipt_identifier_invalid") -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        _fail(code)
    return value


def _canonical(value: object) -> bytes:
    try:
        data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise ProducerBundleReceiptError("producer_bundle_receipt_canonical_invalid") from exc
    if len(data) > _MAX_RECEIPT_BYTES:
        _fail("producer_bundle_receipt_too_large")
    return data


def _object(value: object, fields: set[str], code: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        _fail(code)
    return value


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _digest_payload(value: Mapping[str, Any], digest_name: str) -> str:
    payload = {key: value[key] for key in value if key != digest_name}
    return _sha(payload)


def _mapping(value: object, code: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail(code)
    try:
        # Round-trip through canonical JSON to detach nested caller-owned containers as well as
        # the top-level mapping.  A shallow copy would let a later nested mutation invalidate the
        # receipt identity after construction.
        encoded = _canonical(dict(value))
        result = json.loads(encoded)
        if not isinstance(result, dict):
            _fail(code)
        return result
    except ProducerBundleReceiptError:
        raise
    except Exception as exc:
        raise ProducerBundleReceiptError(code) from exc


def _receipt_value(value: object, *, fields: set[str], protocol: str, code: str) -> dict[str, Any]:
    raw = _object(value, fields, code)
    if raw.get("schema_version") != "1" or raw.get("protocol") != protocol:
        _fail(code)
    _digest(raw.get("receipt_sha256"), code)
    if _digest_payload(raw, "receipt_sha256") != raw["receipt_sha256"]:
        _fail("producer_bundle_receipt_digest_mismatch")
    _canonical(raw)
    return raw


def _normal_report(value: object) -> dict[str, Any]:
    report = _mapping(value, "producer_bundle_evaluation_report_invalid")
    # The native report parser already normalizes evaluator error prose.  Keep only the bounded
    # public report shape; receipt parsing re-checks canonical JSON at every boundary.
    required = {"schema_version", "evaluator_id", "validity", "quality", "combined_score", "detailed_scores", "error_info"}
    if set(report) != required or report.get("schema_version") != "1":
        _fail("producer_bundle_evaluation_report_invalid")
    if type(report["validity"]) is not int or report["validity"] not in (0, 1):
        _fail("producer_bundle_evaluation_report_invalid")
    if not isinstance(report["evaluator_id"], str) or not _ID.fullmatch(report["evaluator_id"]):
        _fail("producer_bundle_evaluation_report_invalid")
    if not isinstance(report["detailed_scores"], dict) or not isinstance(report["error_info"], list):
        _fail("producer_bundle_evaluation_report_invalid")
    _canonical(report)
    return report


@dataclass(frozen=True, slots=True)
class ProducerBundleExecutionReceipt:
    """Portable projection of one verified native execution attempt."""

    candidate_id: str
    bundle_sha256: str
    plan_sha256: str
    admission_sha256: str
    completion_sha256: str
    launch_intent_sha256: str
    result_sha256: str
    runner_result_sha256: str
    cleanup_sha256: str
    status: str = "recorded"
    runner_status: str = "succeeded"
    cleanup_status: str = "verified"
    schema_version: str = "1"
    protocol: str = _EXECUTION_PROTOCOL
    receipt_sha256: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.candidate_id)
        for field in (
            "bundle_sha256", "plan_sha256", "admission_sha256", "completion_sha256",
            "launch_intent_sha256", "result_sha256", "runner_result_sha256", "cleanup_sha256",
        ):
            _digest(getattr(self, field), "producer_bundle_execution_receipt_digest_invalid")
        if self.schema_version != "1" or self.protocol != _EXECUTION_PROTOCOL:
            _fail("producer_bundle_execution_receipt_schema_invalid")
        if self.status != "recorded" or self.runner_status != "succeeded":
            _fail("producer_bundle_execution_receipt_status_invalid")
        if self.cleanup_status != "verified":
            _fail("producer_bundle_execution_receipt_cleanup_invalid")
        expected = _digest_payload(self.to_dict(include_receipt_sha256=False), "receipt_sha256")
        if self.receipt_sha256 is None:
            object.__setattr__(self, "receipt_sha256", expected)
        elif self.receipt_sha256 != expected:
            _fail("producer_bundle_receipt_digest_mismatch")
        _canonical(self.to_dict())

    def to_dict(self, *, include_receipt_sha256: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": self.schema_version, "protocol": self.protocol,
            "candidate_id": self.candidate_id, "bundle_sha256": self.bundle_sha256,
            "plan_sha256": self.plan_sha256, "admission_sha256": self.admission_sha256,
            "completion_sha256": self.completion_sha256,
            "launch_intent_sha256": self.launch_intent_sha256,
            "result_sha256": self.result_sha256, "runner_result_sha256": self.runner_result_sha256,
            "cleanup_sha256": self.cleanup_sha256, "status": self.status,
            "runner_status": self.runner_status, "cleanup_status": self.cleanup_status,
        }
        if include_receipt_sha256:
            value["receipt_sha256"] = self.receipt_sha256
        return value

    def digest(self) -> str:
        return str(self.receipt_sha256)

    @classmethod
    def from_dict(cls, value: object) -> ProducerBundleExecutionReceipt:
        raw = _receipt_value(value, fields=_EXECUTION_FIELDS, protocol=_EXECUTION_PROTOCOL,
                             code="producer_bundle_execution_receipt_schema_invalid")
        return cls(**raw)


@dataclass(frozen=True, slots=True)
class ProducerBundleEvaluationReceipt:
    """Portable projection of one independent native evaluation snapshot."""

    candidate_id: str
    bundle_sha256: str
    plan_sha256: str
    admission_sha256: str
    completion_sha256: str
    evaluation_sha256: str
    binding: dict[str, Any]
    report: dict[str, Any]
    output_contract_valid: bool
    harness_invoked: bool
    status: str = "evaluated"
    schema_version: str = "1"
    protocol: str = _EVALUATION_PROTOCOL
    receipt_sha256: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.candidate_id)
        for field in (
            "bundle_sha256", "plan_sha256", "admission_sha256", "completion_sha256", "evaluation_sha256",
        ):
            _digest(getattr(self, field), "producer_bundle_evaluation_receipt_digest_invalid")
        if self.schema_version != "1" or self.protocol != _EVALUATION_PROTOCOL:
            _fail("producer_bundle_evaluation_receipt_schema_invalid")
        if self.status != "evaluated" or type(self.output_contract_valid) is not bool or type(self.harness_invoked) is not bool:
            _fail("producer_bundle_evaluation_receipt_status_invalid")
        binding = _mapping(self.binding, "producer_bundle_evaluation_binding_invalid")
        report = _normal_report(self.report)
        object.__setattr__(self, "binding", binding)
        object.__setattr__(self, "report", report)
        expected = _digest_payload(self.to_dict(include_receipt_sha256=False), "receipt_sha256")
        if self.receipt_sha256 is None:
            object.__setattr__(self, "receipt_sha256", expected)
        elif self.receipt_sha256 != expected:
            _fail("producer_bundle_receipt_digest_mismatch")
        _canonical(self.to_dict())

    def to_dict(self, *, include_receipt_sha256: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": self.schema_version, "protocol": self.protocol,
            "candidate_id": self.candidate_id, "bundle_sha256": self.bundle_sha256,
            "plan_sha256": self.plan_sha256, "admission_sha256": self.admission_sha256,
            "completion_sha256": self.completion_sha256,
            "evaluation_sha256": self.evaluation_sha256, "binding": self.binding,
            "report": self.report, "output_contract_valid": self.output_contract_valid,
            "harness_invoked": self.harness_invoked, "status": self.status,
        }
        if include_receipt_sha256:
            value["receipt_sha256"] = self.receipt_sha256
        return value

    def digest(self) -> str:
        return str(self.receipt_sha256)

    @classmethod
    def from_dict(cls, value: object) -> ProducerBundleEvaluationReceipt:
        raw = _receipt_value(value, fields=_EVALUATION_FIELDS, protocol=_EVALUATION_PROTOCOL,
                             code="producer_bundle_evaluation_receipt_schema_invalid")
        return cls(**raw)


def _verified_candidate_evidence(workspace: str | Path, candidate: Candidate) -> tuple[dict[str, Any], Any, Any, CandidateExecutionRecord, CandidateEvaluationResult]:
    """Return the exact retained plan/admission/attempt/evaluation evidence for a candidate."""
    if not isinstance(candidate, Candidate) or candidate.bundle_evidence is None or not isinstance(candidate.integrity, dict):
        _fail("producer_bundle_receipt_candidate_invalid")
    from .bundle_evolution import validate_bundle_evidence_shape, validate_candidate_bundle_evidence

    try:
        value = validate_bundle_evidence_shape(candidate.bundle_evidence)
        authority_fields = set(CandidateIntegrityAuthority.__dataclass_fields__)
        authority = CandidateIntegrityAuthority.from_dict({name: candidate.integrity[name] for name in authority_fields})
        root = _files.absolute_path(workspace)
        # This verifies source bytes, archive receipt, execution and evaluation binding before
        # constructing either portable receipt.
        result = validate_candidate_bundle_evidence(
            root, value, code_path=candidate.code_path, evaluation=candidate.evaluation, authority=authority,
        )
        run = root / value["run_root"]
        plan = parse_candidate_workspace_plan(run / "plan.json")
        admission = admit_candidate_execution(
            _files.read_regular_file(run / "admission.json", 256 * 1024), plan=plan,
            expected_admission_sha256=value["admission_sha256"], expected_plan_sha256=value["plan_sha256"],
            expected_bundle_sha256=value["bundle_sha256"], expected_contract_sha256=authority.contract_sha256,
        ).admission
        record = inspect_candidate_execution_record(
            run / "attempt", plan=plan, admission=admission,
            expected_completion_sha256=value["completion_sha256"],
        )
        return value, plan, admission, record, result
    except ProducerBundleReceiptError:
        raise
    except Exception as exc:
        raise ProducerBundleReceiptError("producer_bundle_receipt_evidence_invalid") from exc


def build_producer_bundle_execution_receipt(
    workspace: str | Path, candidate: Candidate,
) -> ProducerBundleExecutionReceipt:
    """Project a successful, independently cleaned native attempt into a receipt."""
    value, _plan, _admission, record, _result = _verified_candidate_evidence(workspace, candidate)
    projection = record.to_dict()
    runner = projection.get("runner_result")
    if not isinstance(runner, dict):
        _fail("producer_bundle_execution_receipt_evidence_invalid")
    try:
        return ProducerBundleExecutionReceipt(
            candidate_id=candidate.candidate_id, bundle_sha256=value["bundle_sha256"],
            plan_sha256=value["plan_sha256"], admission_sha256=value["admission_sha256"],
            completion_sha256=value["completion_sha256"],
            launch_intent_sha256=record.launch_intent_sha256,  # type: ignore[arg-type]
            result_sha256=record.result_sha256,  # type: ignore[arg-type]
            runner_result_sha256=record.runner_result_sha256,  # type: ignore[arg-type]
            cleanup_sha256=record.cleanup_sha256,  # type: ignore[arg-type]
            status=projection.get("status", "unknown"), runner_status=runner.get("status", "unknown"),
            cleanup_status=projection.get("cleanup", record.cleanup_status),
        )
    except ProducerBundleReceiptError:
        raise
    except (TypeError, ValueError) as exc:
        raise ProducerBundleReceiptError("producer_bundle_execution_receipt_evidence_invalid") from exc


def build_producer_bundle_evaluation_receipt(
    workspace: str | Path, candidate: Candidate,
) -> ProducerBundleEvaluationReceipt:
    """Project one retained independent evaluation snapshot into a portable receipt."""
    value, _plan, _admission, _record, result = _verified_candidate_evidence(workspace, candidate)
    projection = result.to_dict()
    try:
        return ProducerBundleEvaluationReceipt(
            candidate_id=candidate.candidate_id, bundle_sha256=value["bundle_sha256"],
            plan_sha256=value["plan_sha256"], admission_sha256=value["admission_sha256"],
            completion_sha256=value["completion_sha256"], evaluation_sha256=result.digest(),
            binding=dict(projection["binding"]), report=dict(projection["report"]),
            output_contract_valid=projection["output_contract_valid"],
            harness_invoked=projection["harness_invoked"], status=projection["status"],
        )
    except ProducerBundleReceiptError:
        raise
    except (TypeError, ValueError, KeyError) as exc:
        raise ProducerBundleReceiptError("producer_bundle_evaluation_receipt_evidence_invalid") from exc


def build_producer_bundle_publication_artifact(archive: Any, candidate: Candidate):
    """Adapt one persisted pipeline candidate to Feature 153's publication artifact.

    The archive and candidate are read only.  Execution/evaluation receipts are attached as
    dedicated sidecars by the staging layer; native record/receipt bytes remain unchanged.
    """
    from .bundle_evolution import read_candidate_source_files
    from .producer_bundle_staging import ProducerBundlePublicationArtifact

    try:
        execution = build_producer_bundle_execution_receipt(archive.workspace, candidate)
        evaluation = build_producer_bundle_evaluation_receipt(archive.workspace, candidate)
        sources = {name: content.encode("utf-8") for name, content in read_candidate_source_files(archive.workspace, candidate).items()}
        receipt = archive.read_candidate_receipt(candidate.candidate_id, source_path=archive.workspace / candidate.code_path)
        if receipt.candidate_id != candidate.candidate_id or receipt.receipt_sha256 != candidate.receipt_sha256:
            _fail("producer_bundle_receipt_candidate_invalid")
        return ProducerBundlePublicationArtifact(
            candidate_id=candidate.candidate_id, source_files=sources,
            record=candidate.to_dict(), receipt=receipt.to_dict(),
            execution_receipt=execution.to_dict(), evaluation_receipt=evaluation.to_dict(),
            execution_receipt_sha256=execution.digest(), evaluation_receipt_sha256=evaluation.digest(),
        )
    except ProducerBundleReceiptError:
        raise
    except Exception as exc:
        raise ProducerBundleReceiptError("producer_bundle_receipt_artifact_invalid") from exc


__all__ = [
    "ProducerBundleEvaluationReceipt", "ProducerBundleExecutionReceipt", "ProducerBundleReceiptError",
    "build_producer_bundle_evaluation_receipt", "build_producer_bundle_execution_receipt",
    "build_producer_bundle_publication_artifact",
]
