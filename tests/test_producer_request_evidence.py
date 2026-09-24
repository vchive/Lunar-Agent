from __future__ import annotations

import json

import pytest

from lunar_evolution.producer_request_evidence import (
    ProducerRequestEvidenceError,
    assess_producer_request_evidence,
    parse_producer_request_evidence,
    validate_producer_request_evidence,
)

INTENT = "a" * 64


def _payload(*, coverage: str = "complete", status: str = "completed", duration_ms: int = 25):
    return {
        "schema_version": "1",
        "protocol": "lunar-producer-request-evidence-v1",
        "launch_id": "launch-001",
        "journal_id": "journal-001",
        "run_id": "run-001",
        "parent_task_id": "parent-001",
        "task_id": "task-001",
        "intent_sha256": INTENT,
        "request_timeout_seconds": 1,
        "max_requests": 2,
        "observed_request_count": 1,
        "coverage": coverage,
        "clock_source": "producer_sdk_monotonic",
        "events": [{"sequence": 1, "request_id": "request-001", "status": status, "duration_ms": duration_ms}],
        "evidence_sha256": None,
    }


def _signed(payload):
    item = parse_producer_request_evidence(payload)
    return item.to_dict()


def test_request_evidence_round_trips_with_stable_digest():
    evidence = parse_producer_request_evidence(_signed(_payload()))
    assert evidence.evidence_sha256 == evidence.digest()
    assert parse_producer_request_evidence(json.dumps(evidence.to_dict())).to_dict() == evidence.to_dict()
    assessment = assess_producer_request_evidence(evidence)
    assert assessment.status == "within_declared_limits"
    assert assessment.enforcement == "cooperative_declaration"


def test_binding_requires_the_exact_launch_tuple_and_budget():
    evidence = parse_producer_request_evidence(_signed(_payload()))
    bound = validate_producer_request_evidence(
        evidence,
        expected_launch_id="launch-001",
        expected_journal_id="journal-001",
        expected_run_id="run-001",
        expected_parent_task_id="parent-001",
        expected_task_id="task-001",
        expected_intent_sha256=INTENT,
        expected_request_timeout_seconds=1,
        expected_max_requests=2,
    )
    assert bound == evidence
    with pytest.raises(ProducerRequestEvidenceError) as exc:
        validate_producer_request_evidence(
            evidence,
            expected_launch_id="launch-001",
            expected_journal_id="journal-001",
            expected_run_id="run-001",
            expected_parent_task_id="parent-001",
            expected_task_id="task-001",
            expected_intent_sha256=INTENT,
            expected_request_timeout_seconds=2,
            expected_max_requests=2,
        )
    assert exc.value.code == "producer_request_evidence_binding_mismatch"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("coverage", "partial", None),
        ("clock_source", "controller_monotonic", "producer_request_evidence_clock_invalid"),
        ("observed_request_count", 2, "producer_request_evidence_count_mismatch"),
        ("events", [{"sequence": 2, "request_id": "request-001", "status": "completed", "duration_ms": 1}], "producer_request_evidence_sequence_invalid"),
    ],
)
def test_malformed_or_incomplete_evidence_is_never_upgraded(field, value, code):
    payload = _payload()
    payload[field] = value
    if code is None:
        evidence = parse_producer_request_evidence(_signed(payload))
        assert assess_producer_request_evidence(evidence).status == "insufficient_evidence"
    else:
        with pytest.raises(ProducerRequestEvidenceError) as exc:
            parse_producer_request_evidence(_signed(payload))
        assert exc.value.code == code


def test_declared_timeout_and_over_budget_are_explicit():
    timed_out = parse_producer_request_evidence(_signed(_payload(status="timed_out", duration_ms=1000)))
    assert assess_producer_request_evidence(timed_out).status == "declared_limit_exceeded"
    slow_completed = parse_producer_request_evidence(_signed(_payload(duration_ms=1001)))
    assert assess_producer_request_evidence(slow_completed).status == "declared_limit_exceeded"


def test_duplicate_keys_and_tampered_digest_are_rejected():
    payload = _signed(_payload())
    duplicate = json.dumps(payload).replace('"launch_id": "launch-001"', '"launch_id": "launch-001", "launch_id": "launch-001"')
    with pytest.raises(ProducerRequestEvidenceError) as exc:
        parse_producer_request_evidence(duplicate)
    assert exc.value.code == "producer_request_evidence_duplicate_key"
    payload["events"][0]["duration_ms"] = 26
    with pytest.raises(ProducerRequestEvidenceError) as exc:
        parse_producer_request_evidence(payload)
    assert exc.value.code == "producer_request_evidence_digest_mismatch"
