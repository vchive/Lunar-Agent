"""Offline registration and evidence-chain observer tests."""
from __future__ import annotations

import copy
import json

import pytest

from lunar_evolution.acceptance_observer import (
    DEFAULT_ACCEPTANCE_BUDGETS,
    STAGES,
    AcceptanceObservationError,
    build_acceptance_manifest,
    observe_acceptance_evidence,
    parse_acceptance_manifest,
)
from lunar_evolution.candidate_generation_receipt import (
    build_candidate_generation_receipt,
    generation_event_id,
)

RUN_ID = "run-acceptance-001"
TASK_ID = "task-generation-001"


def manifest() -> dict[str, object]:
    return build_acceptance_manifest({
        "schema_version": "1",
        "scope": "observation_manifest",
        "registration_id": "registration-20260922",
        "campaign_id": "campaign-20260922",
        "attempt_id": "attempt-001",
        "product_commit": "a" * 40,
        "campaign_root": "campaign-20260922",
        "task_sha256": "1" * 64,
        "input_sha256": "2" * 64,
        "evaluator_sha256": "3" * 64,
        "provider": "offline-provider",
        "model": "offline-model",
        "runtime": "python311",
        "budgets": dict(DEFAULT_ACCEPTANCE_BUDGETS),
    })


def receipts(registration: dict[str, object], count: int = 6) -> list[dict[str, object]]:
    result = []
    previous = None
    for stage in STAGES[:count]:
        item = {
            "schema_version": "1",
            "stage": stage,
            "receipt_id": f"receipt-{stage}",
            "outcome": "succeeded",
            "manifest_sha256": registration["manifest_sha256"],
            "preceding_stage_id": previous,
            "artifact_sha256": ("5" if stage == "generation" else "4") * 64,
            "observed_ms": 1,
        }
        result.append(item)
        previous = item["receipt_id"]
    return result


def generation_event(*, completed: bool = True) -> dict[str, object]:
    payload = {
        "schema_version": "1",
        "stage": "candidate_generation",
        "outcome": "completed" if completed else "failed",
        "reason": "completed" if completed else "worker_failed",
        "completion": completed,
        "budget_id": "budget-generation-001",
        "max_tool_steps": 12,
        "tool_steps_used": 1,
        "tool_steps_remaining": 11,
        "attempted_tool_calls": 1,
    }
    if completed:
        payload.update({"candidate_id": "candidate-001", "source_bundle_sha256": "5" * 64})
    receipt = build_candidate_generation_receipt(payload, run_id=RUN_ID, task_id=TASK_ID)
    return {"id": generation_event_id(receipt), "type": "agent_candidate_generation", "payload": receipt}


def test_full_chain_is_ready_and_generation_is_reused_without_side_effects() -> None:
    registration = manifest()
    observed = observe_acceptance_evidence(
        registration, receipts(registration), generation_events=[generation_event()],
        generation_run_id=RUN_ID, generation_task_id=TASK_ID,
    )
    assert observed["status"] == "chain_complete"
    assert observed["chain_complete"] is True
    assert observed["validation_scope"] == "receipt_chain_only"
    assert observed["primary_success"] == "0/1"
    assert observed["joint_success"] == "0/1"
    assert observed["generation_receipt"] == {"receipt_count": 1, "completed": 1}


def test_preparation_prefix_is_reported_incomplete_without_promoting_primary() -> None:
    registration = manifest()
    observed = observe_acceptance_evidence(registration, receipts(registration, count=1))
    assert observed["status"] == "incomplete"
    assert observed["preparation_success"] == "0/1"
    assert observed["primary_success"] == "0/1"
    assert observed["first_problem_stage"] == "generation"


@pytest.mark.parametrize("mutation,code", [
    (lambda item: item.update({"manifest_sha256": "f" * 64}), "manifest_digest_mismatch"),
    (lambda item: item["budgets"].update({"solve_wall_seconds": 3600}), "budgets_do_not_match_plan"),
    (lambda item: item.update({"prompt": "private"}), "manifest_schema_invalid"),
])
def test_manifest_tamper_or_budget_drift_is_rejected(mutation, code) -> None:
    registration = manifest()
    mutation(registration)
    with pytest.raises(AcceptanceObservationError, match=code):
        parse_acceptance_manifest(registration)


def test_receipt_order_and_manifest_binding_are_rejected() -> None:
    registration = manifest()
    chain = receipts(registration)
    swapped = copy.deepcopy(chain)
    swapped[1], swapped[2] = swapped[2], swapped[1]
    with pytest.raises(AcceptanceObservationError, match="receipt_order_invalid"):
        observe_acceptance_evidence(registration, swapped)
    forged = copy.deepcopy(chain)
    forged[0]["manifest_sha256"] = "f" * 64
    with pytest.raises(AcceptanceObservationError, match="receipt_manifest_mismatch"):
        observe_acceptance_evidence(registration, forged)


def test_generation_outcome_must_match_native_generation_receipt() -> None:
    registration = manifest()
    chain = receipts(registration)
    with pytest.raises(AcceptanceObservationError, match="generation_outcome_mismatch"):
        observe_acceptance_evidence(
            registration, chain, generation_events=[generation_event(completed=False)],
            generation_run_id=RUN_ID, generation_task_id=TASK_ID,
        )


def test_json_manifest_requires_canonical_bytes_and_rejects_duplicates() -> None:
    registration = manifest()
    canonical = json.dumps(registration, sort_keys=True, separators=(",", ":"))
    assert parse_acceptance_manifest(canonical) == registration
    with pytest.raises(AcceptanceObservationError):
        parse_acceptance_manifest(json.dumps(registration, indent=2))
    duplicate = canonical[:-1] + ',"schema_version":"1"}'
    with pytest.raises(AcceptanceObservationError):
        parse_acceptance_manifest(duplicate)


def test_observation_does_not_modify_supplied_evidence() -> None:
    registration = manifest()
    chain = receipts(registration)
    before = copy.deepcopy((registration, chain))
    observe_acceptance_evidence(registration, chain)
    assert (registration, chain) == before


@pytest.mark.parametrize("damage", ["duplicate_id", "missing_artifact", "after_failure", "after_unknown"])
def test_structurally_invalid_chains_fail_closed(damage) -> None:
    registration = manifest()
    chain = receipts(registration)
    if damage == "duplicate_id":
        chain[1]["receipt_id"] = chain[0]["receipt_id"]
    elif damage == "missing_artifact":
        chain[0]["artifact_sha256"] = None
    else:
        chain[0]["outcome"] = "failed" if damage == "after_failure" else "unknown"
    with pytest.raises(AcceptanceObservationError):
        observe_acceptance_evidence(registration, chain)


@pytest.mark.parametrize("damage", ["source", "budget"])
def test_generation_digest_and_tool_limit_bind_to_observation(damage) -> None:
    registration = manifest()
    chain = receipts(registration)
    event = generation_event()
    if damage == "source":
        chain[1]["artifact_sha256"] = "9" * 64
    else:
        event["payload"]["max_tool_steps"] = 13
        event["payload"]["tool_steps_remaining"] = 12
    with pytest.raises(AcceptanceObservationError):
        observe_acceptance_evidence(registration, chain, generation_events=[event],
                                    generation_run_id=RUN_ID, generation_task_id=TASK_ID)


def test_budget_constant_is_immutable_and_manifest_owns_copy() -> None:
    with pytest.raises(TypeError):
        DEFAULT_ACCEPTANCE_BUDGETS["solve_wall_seconds"] = 1
    registration = manifest()
    parsed = parse_acceptance_manifest(registration)
    parsed["budgets"]["solve_wall_seconds"] = 1
    assert registration["budgets"]["solve_wall_seconds"] == 3000


def test_generation_events_reject_non_mapping_entries() -> None:
    registration = manifest()
    with pytest.raises(AcceptanceObservationError, match="generation_receipt_invalid"):
        observe_acceptance_evidence(
            registration, receipts(registration), generation_events=[generation_event(), None],
            generation_run_id=RUN_ID, generation_task_id=TASK_ID,
        )
