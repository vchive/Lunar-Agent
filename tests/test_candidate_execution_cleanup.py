"""Provider-free canonical cleanup-v1 schema checks."""
from __future__ import annotations

import json

import pytest
from test_candidate_execution_evidence import fixture

from lunar_evolution import candidate_execution_evidence as evidence
from lunar_evolution.candidate_execution_cleanup import (
    CandidateExecutionCleanupError,
    audit_candidate_execution_cleanup,
    build_candidate_execution_cleanup,
    parse_candidate_execution_cleanup,
)

LAUNCH = "a" * 64
RESULT = "b" * 64


def payload(**changes):
    result = {
        "protocol": "lunar-candidate-execution-cleanup-v1",
        "schema_version": "1",
        "launch_intent_sha256": LAUNCH,
        "result_sha256": RESULT,
        "native_exit_code": 0,
        "process_exit_code": 0,
        "observer_identity": {"pid": 101, "pgid": 101},
        "release_identity": {"pid": 101, "pgid": 101},
        "group_probe": "absent",
        "ownership_release": "observed",
        "cleanup": "verified",
        "observed_ms": 2,
    }
    result.update(changes)
    return result


def test_verified_receipt_round_trips_and_binds_both_prior_records():
    receipt = build_candidate_execution_cleanup(
        payload(), expected_launch_intent_sha256=LAUNCH, expected_result_sha256=RESULT,
    )
    assert receipt["receipt_sha256"]
    assert parse_candidate_execution_cleanup(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")),
        expected_launch_intent_sha256=LAUNCH,
        expected_result_sha256=RESULT,
    ) == receipt
    assert audit_candidate_execution_cleanup(receipt) == {
        "status": "verified", "reason": None, "cleanup_sha256": receipt["receipt_sha256"],
    }


@pytest.mark.parametrize(
    ("cleanup", "expected"),
    [("failed", {"status": "failed", "reason": "execution_cleanup_failed"}),
     ("unknown", {"status": "unverifiable", "reason": "execution_cleanup_unknown"})],
)
def test_failed_and_unknown_are_not_promoted(cleanup, expected):
    value = build_candidate_execution_cleanup(payload(cleanup=cleanup))
    result = audit_candidate_execution_cleanup(value)
    assert result == {**expected, "cleanup_sha256": value["receipt_sha256"]}


@pytest.mark.parametrize("field", ["launch_intent_sha256", "result_sha256"])
def test_prior_record_binding_is_strict(field):
    value = build_candidate_execution_cleanup(payload())
    with pytest.raises(CandidateExecutionCleanupError) as error:
        parse_candidate_execution_cleanup(value, **{
            "expected_launch_intent_sha256" if field == "launch_intent_sha256" else "expected_result_sha256": "c" * 64,
        })
    assert error.value.code == ("launch_intent_mismatch" if field == "launch_intent_sha256" else "result_mismatch")


@pytest.mark.parametrize("field,value", [
    ("group_probe", "present"),
    ("ownership_release", "not_observed"),
    ("observer_identity", None),
    ("native_exit_code", None),
    ("process_exit_code", None),
    ("process_exit_code", 1),
])
def test_verified_claim_requires_complete_independent_observation(field, value):
    item = payload(**{field: value})
    with pytest.raises(CandidateExecutionCleanupError, match="cleanup_claim_invalid"):
        build_candidate_execution_cleanup(item)


def test_release_identity_must_match_observer_for_verified_cleanup():
    with pytest.raises(CandidateExecutionCleanupError, match="cleanup_claim_invalid"):
        build_candidate_execution_cleanup(payload(release_identity={"pid": 102, "pgid": 102}))


def test_release_identity_cannot_appear_without_observed_release():
    with pytest.raises(CandidateExecutionCleanupError, match="cleanup_claim_invalid"):
        build_candidate_execution_cleanup(payload(
            cleanup="unknown", ownership_release="not_observed", release_identity={"pid": 101, "pgid": 101},
        ))


@pytest.mark.parametrize("field", ["protocol", "schema_version", "group_probe", "ownership_release", "cleanup"])
def test_invalid_enums_and_protocol_are_rejected(field):
    item = payload(**{field: "invalid"})
    with pytest.raises(CandidateExecutionCleanupError):
        build_candidate_execution_cleanup(item)


def test_digest_tampering_and_noncanonical_json_are_rejected():
    value = build_candidate_execution_cleanup(payload())
    altered = dict(value)
    altered["receipt_sha256"] = "c" * 64
    with pytest.raises(CandidateExecutionCleanupError, match="digest_mismatch"):
        parse_candidate_execution_cleanup(altered)
    raw = json.dumps(value, indent=2)
    with pytest.raises(CandidateExecutionCleanupError, match="json_noncanonical"):
        parse_candidate_execution_cleanup(raw)


def test_canonical_bytes_are_supported_and_invalid_utf8_is_rejected():
    receipt = build_candidate_execution_cleanup(payload())
    raw = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    assert parse_candidate_execution_cleanup(raw) == receipt
    assert audit_candidate_execution_cleanup(raw)["status"] == "verified"
    with pytest.raises(CandidateExecutionCleanupError, match="json_invalid"):
        parse_candidate_execution_cleanup(b"\xff")


def test_public_projection_redacts_process_identity_and_has_fixed_errors():
    # The parser retains process identity only in the private receipt; the audit projection is
    # bounded and exposes only its digest/status.  Malformed data cannot leak arbitrary text.
    value = build_candidate_execution_cleanup(payload())
    result = audit_candidate_execution_cleanup({**value, "observer_identity": "secret/path"})
    assert result["status"] == "unverifiable"
    assert "secret/path" not in str(result)
    assert set(result) == {"status", "reason"}


def test_missing_or_legacy_cleanup_is_not_fabricated():
    result = audit_candidate_execution_cleanup(None)
    assert result == {"status": "unverifiable", "reason": "cleanup_evidence_schema_invalid"}


def test_optional_cleanup_descriptor_is_bound_by_native_completion(tmp_path):
    admission, request = fixture(tmp_path)
    record = evidence.run_candidate_execution_recorded(admission, **request)
    attempt = request["attempt_path"]
    cleanup = json.loads((attempt / "cleanup.json").read_bytes())
    inspected = evidence.inspect_candidate_execution_record(
        attempt, admission=admission, plan=request["plan"],
    )
    assert record.cleanup_status == "verified"
    assert inspected.cleanup_status == "verified"
    assert inspected.cleanup_sha256 == cleanup["receipt_sha256"]
    # The detached projection contains only the status and digest, never PID/PGID evidence.
    assert inspected.to_dict()["cleanup"] == "verified"
    assert "observer_identity" not in json.dumps(inspected.to_dict())

    (attempt / "cleanup.json").write_bytes(
        json.dumps({**cleanup, "cleanup": "unknown"}, sort_keys=True, separators=(",", ":")).encode(),
    )
    with pytest.raises(evidence.CandidateExecutionEvidenceError, match="identity_mismatch"):
        evidence.inspect_candidate_execution_record(attempt, admission=admission, plan=request["plan"])
