"""Feature 139 native-receipt boundary fixtures without a native launch."""
from __future__ import annotations

import copy
import hashlib
import json

import pytest
from measurement139_support import feature139

from famou.candidate_bundle import CandidateSourceBundle, CandidateSourceFile
from famou.candidate_generation_receipt import (
    build_candidate_generation_receipt,
    generation_event_id,
)
from famou.store import Store

native_receipts = __import__(f"{feature139.__name__}.native_receipts", fromlist=["*"])
RUN_ID = "a" * 32
TASK_ID = "task-generation-001"
BUDGET_ID = "candidate-00000001-0001"
CANDIDATE_ID = "candidate-001"
BUNDLE_SHA = "a" * 64


def _diagnostic(*, budget_id=BUDGET_ID, bundle=BUNDLE_SHA):
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
        "candidate_id": CANDIDATE_ID,
    }


def _event(payload=None, *, run_id=RUN_ID, task_id=TASK_ID):
    receipt = build_candidate_generation_receipt(
        _diagnostic() if payload is None else payload, run_id=run_id, task_id=task_id,
    )
    return {
        "id": generation_event_id(receipt),
        "task_id": task_id,
        "type": "agent_candidate_generation",
        "payload": receipt,
        "created_at": "2026-09-19T00:00:00+00:00",
    }


def _project(events, **pins):
    return native_receipts.candidate_generation_receipt(events, **{
        "run_id": RUN_ID, "task_id": TASK_ID, "budget_id": BUDGET_ID,
        "candidate_id": CANDIDATE_ID, "bundle_sha256": BUNDLE_SHA, "max_tool_steps": 12,
        **pins,
    })


def _assert_unknown(projected, reason=None):
    assert projected["outcome"] == "unknown"
    assert projected["completion"] is False
    assert "candidate_id" not in projected
    assert "diagnostic_sha256" not in projected
    if reason is not None:
        assert projected["reason_code"] == reason


def test_feature140_store_receipt_projects_bound_completion_without_execution(tmp_path):
    # Build only manifest metadata for fresh synthetic bytes; no source is run.
    sources = {"main.py": b"from helper import value\n", "helper.py": b"value = 3\n"}
    bundle = CandidateSourceBundle(
        "b" * 64, "main.py", tuple(
            CandidateSourceFile(path, len(content), hashlib.sha256(content).hexdigest())
            for path, content in sources.items()
        ),
    )
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("offline generation receipt", tmp_path / "workspace")
    task = store.next_task(run.id)
    assert task is not None
    store.append_candidate_generation_event(
        run.id, task.id, _diagnostic(bundle=bundle.digest()),
    )
    events = store.list_events(run.id)
    before = copy.deepcopy(events)
    projected = _project(events, run_id=run.id, task_id=task.id, bundle_sha256=bundle.digest())
    event = next(row for row in events if row["type"] == "agent_candidate_generation")
    payload = event["payload"]
    assert projected == {
        "schema_version": "1", "stage": "candidate_generation", "outcome": "succeeded",
        "completion": True, "run_id": run.id, "task_id": task.id, "budget_id": BUDGET_ID,
        "bundle_sha256": bundle.digest(), "event_id": event["id"], "candidate_id": CANDIDATE_ID,
        "max_tool_steps": 12, "tool_steps_used": 4, "tool_steps_remaining": 8,
        "attempted_tool_calls": 4,
        "diagnostic_sha256": hashlib.sha256(json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode()).hexdigest(),
    }
    assert events == before
    assert store.list_events(run.id) == before


def test_missing_generation_is_not_inferred_from_archive_or_execution():
    _assert_unknown(_project([
        {"type": "evolution_candidate_archived", "payload": _diagnostic()},
        {"type": "candidate_executed", "payload": _diagnostic()},
    ]), "candidate_generation_diagnostic_missing")


def test_legacy_unbound_generator_diagnostic_cannot_become_a_durable_receipt():
    _assert_unknown(_project([
        {"type": "agent_candidate_generation", "payload": _diagnostic()},
    ]), "candidate_generation_diagnostic_schema_invalid")


@pytest.mark.parametrize("other_payload", [
    _diagnostic(),
    _diagnostic(bundle="b" * 64),
    {
        **{key: value for key, value in _diagnostic().items()
           if key not in {"candidate_id", "source_bundle_sha256"}},
        "outcome": "failed", "reason": "timed_out", "completion": False,
    },
])
@pytest.mark.parametrize("reverse", [False, True])
def test_same_budget_conflicts_are_not_hidden_by_digest_or_outcome_filter(other_payload, reverse):
    events = [_event(), _event(other_payload)]
    if reverse:
        events.reverse()
    _assert_unknown(_project(events), "candidate_generation_diagnostic_ambiguous")


@pytest.mark.parametrize(("field", "value"), [
    ("id", "event-forged"),
    ("id", None),
    ("task_id", "other-task"),
    ("run_id", "other-run"),
    ("type", "evolution_candidate_archived"),
    ("created_at", None),
    ("payload", []),
])
def test_store_envelope_tampering_cannot_form_a_receipt(field, value):
    event = _event()
    event[field] = value
    _assert_unknown(_project([event]))


@pytest.mark.parametrize("field", ["id", "task_id", "created_at", "payload"])
def test_missing_store_envelope_fields_cannot_form_a_receipt(field):
    event = _event()
    del event[field]
    _assert_unknown(_project([event]))


@pytest.mark.parametrize(("field", "value"), [
    ("run_id", "other-run"),
    ("task_id", "other-task"),
    ("budget_id", "other-budget"),
    ("candidate_id", "other-candidate"),
    ("source_bundle_sha256", "b" * 64),
])
def test_recomputed_event_id_cannot_override_expected_identity_or_source(field, value):
    event = _event()
    event["payload"][field] = value
    if field in {"run_id", "task_id"}:
        event[field] = value
    event["id"] = generation_event_id(event["payload"])
    _assert_unknown(_project([event]))


def test_valid_other_task_or_budget_does_not_replace_target_receipt():
    other_task = _event(task_id="other-task")
    other_budget = _event(_diagnostic(budget_id="candidate-00000002-0001"))
    _assert_unknown(_project([other_task, other_budget]), "candidate_generation_diagnostic_missing")
    assert _project([other_task, other_budget, _event()])["outcome"] == "succeeded"


@pytest.mark.parametrize(("field", "value"), [
    ("schema_version", "2"), ("stage", "selection"), ("outcome", "failed"),
    ("reason", "worker_failed"), ("completion", 1), ("max_tool_steps", True),
    ("max_tool_steps", 201), ("tool_steps_used", True), ("tool_steps_used", None),
    ("tool_steps_remaining", 7), ("tool_steps_remaining", -1),
    ("attempted_tool_calls", -1), ("attempted_tool_calls", False),
    ("candidate_id", "../candidate"), ("source_bundle_sha256", "A" * 64),
    ("source_bundle_sha256", None), ("phase", "response"),
    ("response_body", "private provider text"),
])
def test_only_exact_canonical_completed_payload_is_accepted(field, value):
    event = _event()
    event["payload"][field] = value
    projected = _project([event])
    _assert_unknown(projected)
    assert "private provider text" not in repr(projected)


@pytest.mark.parametrize("field", [
    "run_id", "task_id", "source_bundle_sha256", "candidate_id", "budget_id",
    "attempted_tool_calls", "reason",
])
def test_missing_canonical_payload_fields_do_not_receive_inferred_defaults(field):
    event = _event()
    del event["payload"][field]
    _assert_unknown(_project([event]), "candidate_generation_diagnostic_schema_invalid")


def test_registered_tool_ceiling_must_match_even_when_native_arithmetic_is_valid():
    event = _event({**_diagnostic(), "max_tool_steps": 13, "tool_steps_remaining": 9})
    _assert_unknown(_project([event]), "candidate_generation_diagnostic_budget_invalid")


@pytest.mark.parametrize(("outcome", "reason"), [
    ("failed", "timed_out"), ("failed", "tool_step_limit_reached"),
    ("failed", "empty_final_response"), ("unknown", "unknown"),
])
def test_valid_failed_or_unknown_receipt_never_infers_candidate_from_expected_digest(outcome, reason):
    payload = {
        key: value for key, value in _diagnostic().items()
        if key not in {"candidate_id", "source_bundle_sha256"}
    }
    payload.update(outcome=outcome, reason=reason, completion=False,
                   tool_steps_used=None, tool_steps_remaining=None, attempted_tool_calls=None)
    _assert_unknown(_project([_event(payload)]), "candidate_generation_not_completed")


@pytest.mark.parametrize(("field", "value"), [
    ("run_id", None), ("task_id", "bad/task"), ("budget_id", ""),
    ("candidate_id", "bad candidate"), ("bundle_sha256", "A" * 64),
    ("max_tool_steps", True), ("max_tool_steps", 0), ("max_tool_steps", 201),
])
def test_caller_identity_and_registered_budget_pins_must_be_valid(field, value):
    with pytest.raises(native_receipts.NativeReceiptError, match=f"invalid_{field}"):
        _project([_event()], **{field: value})


def test_corrupt_event_list_cannot_be_silently_skipped():
    _assert_unknown(_project([None, _event()]), "candidate_generation_diagnostic_schema_invalid")
    with pytest.raises(native_receipts.NativeReceiptError, match="invalid_events"):
        _project({"event": _event()})


def test_explicit_store_run_envelope_and_nullable_attempt_count_are_supported():
    event = _event({**_diagnostic(), "attempted_tool_calls": None})
    event["run_id"] = RUN_ID
    projected = _project((event,))
    assert projected["outcome"] == "succeeded"
    assert projected["attempted_tool_calls"] is None


def test_source_digest_is_not_a_hash_of_raw_candidate_text():
    event = _event()
    _assert_unknown(
        _project([event], bundle_sha256=hashlib.sha256(b"value = 3\n").hexdigest()),
        "candidate_generation_source_mismatch",
    )


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
