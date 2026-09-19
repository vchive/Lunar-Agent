"""Feature 139 native-receipt boundary fixtures without a native launch."""
from __future__ import annotations

import copy

import pytest
from measurement139_support import feature139

native_receipts = __import__(f"{feature139.__name__}.native_receipts", fromlist=["*"])


def _diagnostic(*, budget_id="candidate-00000001-0001", bundle="a" * 64):
    return {
        "schema_version": "1",
        "stage": "candidate_generation",
        "outcome": "completed",
        "reason": "completed",
        "completion": True,
        "budget_id": budget_id,
        "max_tool_steps": 12,
        "tool_steps_used": 4,
        "tool_steps_remaining": 8,
        "attempted_tool_calls": 4,
        "source_bundle_sha256": bundle,
        "candidate_id": "candidate-001",
    }


def test_current_native_diagnostic_cannot_be_inferred_from_an_archive_candidate():
    current_payload = _diagnostic()
    current_payload.pop("source_bundle_sha256")
    projected = native_receipts.candidate_generation_receipt(
        [{"type": "agent_candidate_generation", "payload": current_payload}],
        budget_id="candidate-00000001-0001", bundle_sha256="a" * 64,
    )
    assert projected == {
        "schema_version": "1",
        "stage": "candidate_generation",
        "outcome": "unknown",
        "completion": False,
        "budget_id": "candidate-00000001-0001",
        "bundle_sha256": "a" * 64,
        "reason_code": "candidate_generation_diagnostic_unpersisted_or_unbound",
    }


def test_only_one_complete_bound_diagnostic_can_form_a_generation_receipt():
    payload = _diagnostic()
    projected = native_receipts.candidate_generation_receipt(
        [{"type": "agent_candidate_generation", "payload": payload}],
        budget_id="candidate-00000001-0001", bundle_sha256="a" * 64,
    )
    assert projected["outcome"] == "succeeded"
    assert projected["completion"] is True
    assert len(projected["diagnostic_sha256"]) == 64

    duplicate = native_receipts.candidate_generation_receipt(
        [{"type": "agent_candidate_generation", "payload": payload}] * 2,
        budget_id="candidate-00000001-0001", bundle_sha256="a" * 64,
    )
    assert duplicate["outcome"] == "unknown"
    assert duplicate["reason_code"] == "candidate_generation_diagnostic_ambiguous"


def test_bundle_evidence_projection_requires_all_execution_and_evaluation_bindings():
    evidence = {
        "protocol": "lunar-population-bundle-v1",
        "bundle_sha256": "a" * 64,
        "bundle_path": "evolution/candidates/candidate-001/bundle-manifest.json",
        "source_root": "evolution/candidates/candidate-001",
        "run_root": "evolution/bundle-attempts/.bundle-run-0123456789abcdef01234567",
        "plan_sha256": "b" * 64,
        "admission_sha256": "c" * 64,
        "completion_sha256": "d" * 64,
        "evaluation_path": (
            "evolution/bundle-attempts/.bundle-run-0123456789abcdef01234567/"
            "evaluations/.candidate-evaluation-0123456789abcdef01234567"
        ),
        "evaluation_sha256": "e" * 64,
    }
    projected = native_receipts.bundle_evidence_receipt(evidence)
    assert projected["completion_sha256"] == "d" * 64
    broken = copy.deepcopy(evidence)
    broken["bundle_path"] = "different.json"
    with pytest.raises(native_receipts.NativeReceiptError, match="invalid_bundle_evidence"):
        native_receipts.bundle_evidence_receipt(broken)


def test_bundle_evidence_projection_rejects_path_traversal_and_unbound_run_shapes():
    evidence = {
        "protocol": "lunar-population-bundle-v1",
        "bundle_sha256": "a" * 64,
        "bundle_path": "evolution/candidates/candidate-001/bundle-manifest.json",
        "source_root": "evolution/candidates/candidate-001",
        "run_root": "evolution/bundle-attempts/.bundle-run-0123456789abcdef01234567",
        "plan_sha256": "b" * 64,
        "admission_sha256": "c" * 64,
        "completion_sha256": "d" * 64,
        "evaluation_path": "evolution/bundle-attempts/.bundle-run-0123456789abcdef01234567/evaluations/.candidate-evaluation-0123456789abcdef01234567",
        "evaluation_sha256": "e" * 64,
    }
    for key, value in {
        "source_root": "evolution/candidates/../candidate-001",
        "run_root": "evolution/bundle-attempts/.bundle-run-not-a-digest",
        "evaluation_path": "evolution/bundle-attempts/.bundle-run-0123456789abcdef01234567/evaluations/other",
    }.items():
        broken = copy.deepcopy(evidence)
        broken[key] = value
        with pytest.raises(native_receipts.NativeReceiptError, match="invalid_bundle_evidence"):
            native_receipts.bundle_evidence_receipt(broken)
