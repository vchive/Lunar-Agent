from __future__ import annotations

import pytest

from famou.candidate_generation_receipt import (
    CandidateGenerationReceiptError,
    build_candidate_generation_receipt,
    generation_event_id,
    inspect_candidate_generation_events,
)
from famou.store import Store

RUN_ID = "a" * 32
TASK_ID = "task-generation-001"
BUDGET_ID = "candidate-00000001-0001"
BUNDLE_SHA = "b" * 64


def completed_payload() -> dict[str, object]:
    return {
        "schema_version": "1",
        "stage": "candidate_generation",
        "outcome": "completed",
        "reason": "completed",
        "completion": True,
        "budget_id": BUDGET_ID,
        "max_tool_steps": 12,
        "tool_steps_used": 7,
        "tool_steps_remaining": 5,
        "attempted_tool_calls": 7,
        "candidate_id": "candidate-0001",
        "source_bundle_sha256": BUNDLE_SHA,
        "phase": "response",
    }


def failed_payload() -> dict[str, object]:
    return {
        "schema_version": "1",
        "stage": "candidate_generation",
        "outcome": "failed",
        "reason": "worker_failed",
        "completion": False,
        "budget_id": BUDGET_ID,
        "max_tool_steps": 12,
        "tool_steps_used": None,
        "tool_steps_remaining": None,
        "attempted_tool_calls": None,
    }


def test_completed_receipt_allows_bound_bundle_digest() -> None:
    receipt = build_candidate_generation_receipt(
        completed_payload(), run_id=RUN_ID, task_id=TASK_ID
    )

    assert receipt["outcome"] == "completed"
    assert receipt["candidate_id"] == "candidate-0001"
    assert receipt["source_bundle_sha256"] == BUNDLE_SHA
    assert receipt["run_id"] == RUN_ID
    assert receipt["task_id"] == TASK_ID
    assert generation_event_id(receipt).startswith("event-agent-candidate-generation-")


def test_failed_receipt_never_carries_candidate_or_source_digest() -> None:
    receipt = build_candidate_generation_receipt(
        failed_payload(), run_id=RUN_ID, task_id=TASK_ID
    )

    assert receipt["outcome"] == "failed"
    assert "candidate_id" not in receipt
    assert "source_bundle_sha256" not in receipt


@pytest.mark.parametrize("field", ["candidate_id", "source_bundle_sha256"])
def test_failed_receipt_rejects_even_null_identity_fields(field: str) -> None:
    payload = failed_payload()
    payload[field] = None
    with pytest.raises(
        CandidateGenerationReceiptError, match="failed_receipt_contains_candidate_identity"
    ):
        build_candidate_generation_receipt(payload, run_id=RUN_ID, task_id=TASK_ID)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tool_steps_remaining", 4),
        ("candidate_id", None),
        ("source_bundle_sha256", None),
    ],
)
def test_completed_receipt_rejects_incomplete_budget_or_identity(field: str, value: object) -> None:
    payload = completed_payload()
    payload[field] = value
    with pytest.raises(CandidateGenerationReceiptError):
        build_candidate_generation_receipt(payload, run_id=RUN_ID, task_id=TASK_ID)


def test_private_or_unknown_diagnostic_fields_are_not_persisted() -> None:
    payload = completed_payload()
    payload["model_response"] = "private response"
    with pytest.raises(CandidateGenerationReceiptError, match="diagnostic_schema_invalid"):
        build_candidate_generation_receipt(payload, run_id=RUN_ID, task_id=TASK_ID)


@pytest.mark.parametrize("field", ["schema_version", "stage"])
def test_schema_identity_is_fixed(field: str) -> None:
    payload = completed_payload()
    payload[field] = "forged"
    with pytest.raises(CandidateGenerationReceiptError, match="diagnostic_schema_invalid"):
        build_candidate_generation_receipt(payload, run_id=RUN_ID, task_id=TASK_ID)


def test_read_only_inspection_rejects_duplicate_or_unbound_event() -> None:
    receipt = build_candidate_generation_receipt(
        completed_payload(), run_id=RUN_ID, task_id=TASK_ID
    )
    event = {
        "id": generation_event_id(receipt),
        "type": "agent_candidate_generation",
        "payload": receipt,
    }
    assert inspect_candidate_generation_events([event], run_id=RUN_ID, task_id=TASK_ID) == {
        "receipt_count": 1,
        "completed": 1,
    }
    with pytest.raises(CandidateGenerationReceiptError, match="duplicate_generation_receipt"):
        inspect_candidate_generation_events([event, event], run_id=RUN_ID, task_id=TASK_ID)

    tampered = {**event, "id": "event-unbound"}
    with pytest.raises(CandidateGenerationReceiptError, match="event_identity_mismatch"):
        inspect_candidate_generation_events([tampered], run_id=RUN_ID, task_id=TASK_ID)


def test_read_only_inspection_rejects_missing_receipt() -> None:
    with pytest.raises(CandidateGenerationReceiptError, match="generation_receipt_missing"):
        inspect_candidate_generation_events([], run_id=RUN_ID, task_id=TASK_ID)


def test_store_binds_receipt_to_task_run_and_is_idempotent(tmp_path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("receipt test", tasks=[{"id": TASK_ID, "title": "generation", "prompt": "x"}])
    assert run.id != RUN_ID
    payload = completed_payload()
    assert store.append_candidate_generation_event(run.id, TASK_ID, payload) is True
    assert store.append_candidate_generation_event(run.id, TASK_ID, payload) is False
    events = [event for event in store.list_events(run.id) if event["type"] == "agent_candidate_generation"]
    assert len(events) == 1
    with pytest.raises(ValueError, match="not bound to run"):
        store.append_candidate_generation_event("other-run", TASK_ID, payload)


def test_store_append_is_idempotent_and_rejects_budget_conflicts(tmp_path) -> None:
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("receipt", tmp_path / "run")
    task = store.next_task(run.id)
    assert task is not None
    payload = completed_payload()
    assert store.append_candidate_generation_event(run.id, task.id, payload)
    assert not store.append_candidate_generation_event(run.id, task.id, payload)
    conflict = {**payload, "source_bundle_sha256": "c" * 64}
    with pytest.raises(ValueError, match="identity conflict"):
        store.append_candidate_generation_event(run.id, task.id, conflict)
    events = [item for item in store.list_events(run.id) if item["type"] == "agent_candidate_generation"]
    assert len(events) == 1
    assert events[0]["payload"]["run_id"] == run.id
    assert events[0]["payload"]["task_id"] == task.id
