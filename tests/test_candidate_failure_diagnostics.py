"""Strict candidate failure receipts preserve safe observations and historical identity."""

import json

import pytest

from famou.agent_evolution import AgentCandidateGenerator
from famou.agent_loop import AgentLoopRuntime
from famou.agents import (
    AgentResult,
    CandidateGenerationBudget,
    RuntimeAgentAdapter,
    candidate_model_failure_cause,
)
from famou.candidate_generation_receipt import (
    CandidateGenerationReceiptError,
    build_candidate_generation_receipt,
    generation_event_id,
    inspect_candidate_generation_events,
)
from famou.evolution import EvolutionError, GenerationRequest
from famou.runtime import MODEL_FAILURE_REASONS, ModelFailureEvidence, ModelRequestFailure
from famou.store import Store

RUN_ID = "candidate-diagnostic-run"
TASK_ID = "candidate-diagnostic-task"


def failed_payload(**changes):
    return {
        "schema_version": "1", "stage": "candidate_generation",
        "outcome": "failed", "reason": "worker_failed", "completion": False,
        "budget_id": "candidate-1", "max_tool_steps": 12,
        "tool_steps_used": None, "tool_steps_remaining": None, "attempted_tool_calls": None,
        **changes,
    }


def receipt(payload):
    return build_candidate_generation_receipt(payload, run_id=RUN_ID, task_id=TASK_ID)


def event(payload):
    return {"id": generation_event_id(payload), "type": "agent_candidate_generation", "payload": payload}


def test_legacy_receipt_canonical_bytes_and_event_identity_are_unchanged():
    payload = failed_payload()
    expected = {**payload, "run_id": RUN_ID, "task_id": TASK_ID}
    projected = receipt(payload)
    assert json.dumps(projected, sort_keys=True) == json.dumps(expected, sort_keys=True)
    assert "phase" not in projected and "failure_cause" not in projected
    extended = receipt({**payload, "phase": "model_turn", "failure_cause": "http_error"})
    assert generation_event_id(extended) == generation_event_id(expected)


@pytest.mark.parametrize("alias,canonical", [
    ("timeout", "timed_out"), ("tool_failed", "tool_execution_failed"),
    ("empty_response", "empty_final_response"),
])
def test_transient_failure_alias_is_normalized_but_retained_alias_is_rejected(alias, canonical):
    transient = failed_payload(outcome=canonical, reason=alias, phase="model_turn")
    canonical_payload = receipt(transient)
    assert canonical_payload["reason"] == canonical
    assert canonical_payload["outcome"] == "failed"
    assert canonical_payload["phase"] == "model_turn"
    assert inspect_candidate_generation_events(
        [event(canonical_payload)], run_id=RUN_ID, task_id=TASK_ID,
    ) == {"receipt_count": 1, "completed": 0}
    with pytest.raises(CandidateGenerationReceiptError, match="noncanonical"):
        inspect_candidate_generation_events(
            [event({**canonical_payload, "reason": alias})], run_id=RUN_ID, task_id=TASK_ID,
        )


@pytest.mark.parametrize("phase", ["model_turn", "tool", "tool_batch", "response", "run"])
def test_only_observed_allowlisted_failure_phases_are_preserved(phase):
    assert receipt(failed_payload(phase=phase))["phase"] == phase


@pytest.mark.parametrize("cause", sorted(MODEL_FAILURE_REASONS))
def test_allowlisted_model_failure_causes_are_preserved(cause):
    result = receipt(failed_payload(phase="model_turn", failure_cause=cause))
    assert result["failure_cause"] == cause
    assert "candidate_id" not in result and "source_bundle_sha256" not in result


@pytest.mark.parametrize("field,value", [
    ("phase", None), ("phase", "provider endpoint https://private.example"),
    ("phase", True), ("phase", []),
    ("failure_cause", None), ("failure_cause", "api_key=private-secret"),
    ("failure_cause", True), ("failure_cause", {"reason": "http_error"}),
])
def test_invalid_optional_failure_fields_are_rejected_without_echoing_private_values(field, value):
    with pytest.raises(CandidateGenerationReceiptError) as rejected:
        receipt(failed_payload(**{field: value}))
    assert "private" not in str(rejected.value)


def test_completed_receipt_keeps_legacy_shape_and_rejects_a_failure_cause():
    payload = failed_payload(
        outcome="completed", reason="completed", completion=True,
        tool_steps_used=4, tool_steps_remaining=8, attempted_tool_calls=0,
        candidate_id="candidate-1", source_bundle_sha256="a" * 64, phase="response",
    )
    completed = receipt(payload)
    assert "phase" not in completed
    with pytest.raises(CandidateGenerationReceiptError):
        receipt({**payload, "failure_cause": "http_error"})
    with pytest.raises(CandidateGenerationReceiptError, match="noncanonical"):
        inspect_candidate_generation_events(
            [event({**completed, "phase": "response"})], run_id=RUN_ID, task_id=TASK_ID,
        )


@pytest.mark.parametrize("reason", ["timed_out", "cancelled", "tool_step_limit_reached"])
def test_failure_observations_cannot_create_completion(reason):
    with pytest.raises(CandidateGenerationReceiptError):
        receipt(failed_payload(reason=reason, completion=True, phase="model_turn"))


def test_store_persists_one_exact_failure_receipt_and_rejects_changed_cause(tmp_path):
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("safe failure", tmp_path / "run")
    task = store.list_tasks(run.id)[0]
    payload = failed_payload(phase="model_turn", failure_cause="invalid_json")
    assert store.append_candidate_generation_event(run.id, task.id, payload)
    assert not store.append_candidate_generation_event(run.id, task.id, payload)
    with pytest.raises(ValueError, match="identity conflict"):
        store.append_candidate_generation_event(run.id, task.id, {**payload, "failure_cause": "http_error"})
    events = store.list_events(run.id)
    stored = [item for item in events if item["type"] == "agent_candidate_generation"]
    assert len(stored) == 1
    assert stored[0]["payload"]["failure_cause"] == "invalid_json"
    assert stored[0]["payload"]["phase"] == "model_turn"


def test_single_file_parser_failure_preserves_valid_runtime_budget_counts(tmp_path):
    class InvalidCandidateAdapter:
        name = "invalid-candidate"
        roles = frozenset({"solver"})
        capabilities = frozenset()

        def cancel(self):
            return None

        def process_info(self):
            return None, None

        def set_process_observer(self, observer):
            pass

        def run(self, request):
            return AgentResult(self.name, request.role, "{broken JSON", metadata={
                "candidate_max_tool_steps": "4", "candidate_tool_steps_used": "3",
                "candidate_tool_steps_remaining": "1", "candidate_attempted_tool_calls": "0",
            })

    generator = AgentCandidateGenerator(
        InvalidCandidateAdapter(), candidate_budget=CandidateGenerationBudget("candidate-1", 12),
    )
    observed = []
    generator.set_observer(lambda kind, payload: observed.append((kind, receipt(payload))))
    with pytest.raises(EvolutionError):
        generator(GenerationRequest(1, None, (), (), tmp_path, "candidate-1"))
    assert len(observed) == 1
    failure = observed[0][1]
    assert failure["reason"] == "malformed_candidate"
    assert failure["phase"] == "response"
    assert failure["max_tool_steps"] == 12
    assert failure["tool_steps_used"] == 3 and failure["tool_steps_remaining"] == 9
    assert failure["attempted_tool_calls"] == 0
    assert "candidate_id" not in failure and "source_bundle_sha256" not in failure


@pytest.mark.parametrize("cause", sorted(MODEL_FAILURE_REASONS))
def test_typed_model_failure_reaches_one_durable_receipt_without_exception_text(tmp_path, cause):
    secret_text = "secret credential https://private.example response body"

    class FailingModel:
        def complete(self, messages, tools=(), timeout=None):
            raise ModelRequestFailure(secret_text, cause)

    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("typed model failure", tmp_path / "run")
    task = store.list_tasks(run.id)[0]
    runtime = AgentLoopRuntime(FailingModel())
    generator = AgentCandidateGenerator(
        RuntimeAgentAdapter(runtime), candidate_budget=CandidateGenerationBudget("candidate-1", 12),
    )

    def observe(kind, payload):
        if kind == "agent_candidate_generation":
            store.append_candidate_generation_event(run.id, task.id, payload)

    generator.set_observer(observe)
    with pytest.raises(EvolutionError):
        generator(GenerationRequest(1, None, (), (), run.workspace, "candidate-1"))
    observed = [item for item in store.list_events(run.id) if item["type"] == "agent_candidate_generation"]
    assert len(observed) == 1
    diagnostic = observed[0]["payload"]
    assert diagnostic["outcome"] == "failed"
    assert diagnostic["reason"] == ("timed_out" if cause == "transport_timeout" else "worker_failed")
    assert diagnostic["failure_cause"] == cause
    assert diagnostic["phase"] == "model_turn"
    assert diagnostic["tool_steps_used"] == 0 and diagnostic["tool_steps_remaining"] == 12
    assert secret_text not in json.dumps(diagnostic)
    assert "private.example" not in json.dumps(diagnostic)
    assert inspect_candidate_generation_events(observed, run_id=run.id, task_id=task.id) == {
        "receipt_count": 1, "completed": 0,
    }


def test_unknown_model_exception_does_not_infer_a_cause_from_text_or_fake_evidence(tmp_path):
    class UnknownFailure(RuntimeError):
        evidence = ModelFailureEvidence("http_error", 503)

    class FailingModel:
        def complete(self, messages, tools=(), timeout=None):
            raise UnknownFailure("HTTP 503 transport_timeout api_key=private-secret")

    runtime = AgentLoopRuntime(FailingModel())
    generator = AgentCandidateGenerator(
        RuntimeAgentAdapter(runtime), candidate_budget=CandidateGenerationBudget("candidate-1", 12),
    )
    diagnostics = []
    generator.set_observer(lambda kind, payload: diagnostics.append(receipt(payload))
                           if kind == "agent_candidate_generation" else None)
    with pytest.raises(EvolutionError):
        generator(GenerationRequest(1, None, (), (), tmp_path, "candidate-1"))
    assert len(diagnostics) == 1
    assert diagnostics[0]["reason"] == "worker_failed"
    assert diagnostics[0]["phase"] == "model_turn"
    assert "failure_cause" not in diagnostics[0]
    assert "private-secret" not in json.dumps(diagnostics)


def test_typed_cause_projector_does_not_stringify_or_infer_from_wrapped_or_invalid_evidence():
    class UnprintableError(RuntimeError):
        evidence = ModelFailureEvidence("http_error", 503)

        def __str__(self):
            raise AssertionError("exception text must never be inspected")

    unknown = UnprintableError()
    unknown.__cause__ = ModelRequestFailure("private text", "http_error", 503)
    assert candidate_model_failure_cause(unknown) is None
    invalid = ModelRequestFailure("private text", "unbounded custom reason")
    assert candidate_model_failure_cause(invalid) is None
    invalid.evidence = {"reason": "http_error", "response_status": 503}
    assert candidate_model_failure_cause(invalid) is None
