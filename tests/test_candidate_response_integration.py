"""Offline bundle protocol and failure receipts across the actual Agent execution chain."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest
from test_bundle_population import build_context, draft_for_score

from lunar_evolution.agent_evolution import AgentCandidateGenerator
from lunar_evolution.agent_loop import AgentLoopRuntime
from lunar_evolution.agents import CandidateGenerationBudget, RuntimeAgentAdapter
from lunar_evolution.candidate_generation_receipt import inspect_candidate_generation_events
from lunar_evolution.evolution import EvolutionError, GenerationRequest, PopulationStrategy
from lunar_evolution.runtime import MODEL_FAILURE_REASONS, ModelRequestFailure, ModelTurn, ToolCall
from lunar_evolution.store import Store


class ScriptedModel:
    name = "offline-bundle-response"

    def __init__(self, actions):
        self.actions = list(actions)
        self.requests = []

    def complete(self, messages, tools=(), timeout=None):
        self.requests.append(copy.deepcopy(messages))
        action = self.actions.pop(0)
        if isinstance(action, BaseException):
            raise action
        return action

    def cancel(self):
        return None

    def process_info(self):
        return None, None

    def set_process_observer(self, observer):
        del observer


def _response(*, experiment=False):
    draft = draft_for_score(7)
    payload = {"entrypoint": draft.filename, "files": draft.source_files}
    if experiment:
        payload["experiment"] = {
            "schema_version": "1", "hypothesis": "Choosing seven satisfies the input bound.",
            "change_tags": ["helper"],
            "target_metrics": [{"metric": "quality", "direction": "increase"}],
        }
    return payload


def _read_context_turn():
    return ModelTurn("", (ToolCall("read-context", "list_dir", {"path": "context"}),))


def _chain(tmp_path, actions, monkeypatch, *, max_steps=3):
    context = build_context(tmp_path)
    store = Store(tmp_path / "receipts.db")
    store.initialize()
    run = store.create_run("offline candidate protocol", context.workspace)
    task = store.next_task(run.id)
    assert task is not None
    model = ScriptedModel(actions)
    runtime = AgentLoopRuntime(model, max_steps=6)
    generator = AgentCandidateGenerator(
        RuntimeAgentAdapter(runtime), contract=context.contract,
        bundle_pipeline=context.bundle_pipeline,
        candidate_budget=CandidateGenerationBudget("candidate-generation", max_steps),
    )
    receipt_emissions = []

    def sink(kind, payload):
        if kind == "agent_candidate_generation":
            receipt_emissions.append(copy.deepcopy(payload))
            store.append_candidate_generation_event(run.id, task.id, payload)
        else:
            store.append_event(run.id, kind, payload, task_id=task.id)

    generator.set_observer(sink)
    strategy = PopulationStrategy(context)
    downstream = []
    original_persist = context.bundle_pipeline.persist

    def persist(*args, **kwargs):
        downstream.append("execution-and-independent-evaluation")
        return original_persist(*args, **kwargs)

    monkeypatch.setattr(context.bundle_pipeline, "persist", persist)
    request = GenerationRequest(1, None, (), (), context.workspace, "candidate-protocol")

    def attempt():
        draft = generator(request)
        return strategy._persist(draft, iteration=1, generation=1, parent=None, island_id=0)

    return SimpleNamespace(
        context=context, store=store, run=run, task=task, model=model, runtime=runtime,
        generator=generator, downstream=downstream, receipt_emissions=receipt_emissions,
        attempt=attempt,
    )


def _receipt(chain, *, completed):
    events = [event for event in chain.store.list_events(chain.run.id)
              if event["type"] == "agent_candidate_generation"]
    assert len(chain.receipt_emissions) == len(events) == 1
    assert inspect_candidate_generation_events(
        events, run_id=chain.run.id, task_id=chain.task.id,
    ) == {"receipt_count": 1, "completed": int(completed)}
    receipt = events[0]["payload"]
    assert receipt["run_id"] == chain.run.id and receipt["task_id"] == chain.task.id
    assert receipt["completion"] is completed
    if not completed:
        assert receipt["outcome"] == "failed"
        assert "candidate_id" not in receipt and "source_bundle_sha256" not in receipt
        assert chain.downstream == []
        assert not list(chain.context.workspace.rglob("launch-intent.json"))
        assert not list(chain.context.workspace.rglob("count"))
    return receipt


@pytest.mark.parametrize("experiment", [False, True])
def test_valid_bundle_crosses_model_adapter_store_and_independent_evaluation(
    tmp_path, monkeypatch, experiment,
):
    chain = _chain(tmp_path, [
        _read_context_turn(), ModelTurn(json.dumps(_response(experiment=experiment))),
    ], monkeypatch)

    candidate = chain.attempt()

    assert candidate.evaluation.validity == 1
    assert candidate.evaluation.combined_score == 7
    assert chain.downstream == ["execution-and-independent-evaluation"]
    receipt = _receipt(chain, completed=True)
    assert receipt["reason"] == "completed"
    assert receipt["tool_steps_used"] == 1 and receipt["tool_steps_remaining"] == 2
    assert "phase" not in receipt and "failure_cause" not in receipt
    assert len(receipt["source_bundle_sha256"]) == 64
    assert len(chain.model.requests) == 2 and not chain.model.actions
    for messages in chain.model.requests:
        system = "\n".join(message["content"] for message in messages if message["role"] == "system")
        assert "lunar-evolution-bundle-generation-v1" in system
        assert "Return only one strict JSON object" in system
    # The real candidate executed once; acceptance came from the independent harness.
    assert [path.read_text() for path in chain.context.workspace.rglob("count")] == ["x"]


@pytest.mark.parametrize("damage", ["change_tags", "target_metrics", "prose", "fence"])
def test_rejected_final_response_keeps_counts_and_cannot_reach_execution(
    tmp_path, monkeypatch, damage,
):
    payload = _response(experiment=True)
    if damage in {"change_tags", "target_metrics"}:
        payload["experiment"][damage] = {"quality": "increase"}
    response = json.dumps(payload)
    if damage == "prose":
        response = "Here is the result.\n" + response
    elif damage == "fence":
        response = "```json\n" + response + "\n```"
    chain = _chain(tmp_path, [_read_context_turn(), ModelTurn(response)], monkeypatch)

    with pytest.raises(EvolutionError):
        chain.attempt()

    receipt = _receipt(chain, completed=False)
    assert receipt["reason"] == "malformed_candidate" and receipt["phase"] == "response"
    assert receipt["tool_steps_used"] == 1 and receipt["tool_steps_remaining"] == 2
    assert "failure_cause" not in receipt
    assert len(chain.model.requests) == 2 and not chain.model.actions


@pytest.mark.parametrize("cause", sorted(MODEL_FAILURE_REASONS))
def test_typed_model_failure_persists_only_allowlisted_cause(tmp_path, monkeypatch, cause):
    secret = "private-provider-detail https://secret.invalid/token"
    chain = _chain(tmp_path, [
        _read_context_turn(), ModelRequestFailure(secret, cause, response_status=429),
    ], monkeypatch)

    with pytest.raises(EvolutionError):
        chain.attempt()

    receipt = _receipt(chain, completed=False)
    assert receipt["reason"] == ("timed_out" if cause == "transport_timeout" else "worker_failed")
    assert receipt["phase"] == "model_turn" and receipt["failure_cause"] == cause
    assert receipt["tool_steps_used"] == 1 and receipt["tool_steps_remaining"] == 2
    assert "private-provider-detail" not in json.dumps(receipt)
    assert "secret.invalid" not in json.dumps(receipt)
    assert len(chain.model.requests) == 2


@pytest.mark.parametrize("failure,reason,phase,used", [
    ("tool", "tool_execution_failed", "tool", 1),
    ("empty", "empty_final_response", "response", 0),
    ("timeout", "timed_out", "model_turn", 0),
    ("unknown", "worker_failed", "model_turn", 0),
])
def test_runtime_failure_aliases_remain_single_durable_failures(
    tmp_path, monkeypatch, failure, reason, phase, used,
):
    action = {
        "tool": ModelTurn("", (ToolCall("missing", "read_file", {"path": "missing.txt"}),)),
        "empty": ModelTurn(""),
        "timeout": TimeoutError("private timeout detail"),
        "unknown": RuntimeError("invalid_json transport_timeout http_error must not classify me"),
    }[failure]
    chain = _chain(tmp_path, [action, ModelTurn(json.dumps(_response()))], monkeypatch)

    with pytest.raises(EvolutionError):
        chain.attempt()

    receipt = _receipt(chain, completed=False)
    assert receipt["reason"] == reason and receipt["phase"] == phase
    assert receipt["tool_steps_used"] == used and receipt["tool_steps_remaining"] == 3 - used
    assert "failure_cause" not in receipt
    assert len(chain.model.requests) == 1 and len(chain.model.actions) == 1


def test_oversized_tool_batch_is_rejected_before_any_file_write(tmp_path, monkeypatch):
    calls = tuple(ToolCall(str(index), "write_file", {
        "path": f"must-not-write-{index}.txt", "content": "forbidden",
    }) for index in range(3))
    chain = _chain(tmp_path, [ModelTurn("", calls), ModelTurn(json.dumps(_response()))],
                   monkeypatch, max_steps=2)

    with pytest.raises(EvolutionError):
        chain.attempt()

    receipt = _receipt(chain, completed=False)
    assert receipt["reason"] == "tool_step_limit_reached" and receipt["phase"] == "tool_batch"
    assert receipt["tool_steps_used"] == 0 and receipt["tool_steps_remaining"] == 2
    assert receipt["attempted_tool_calls"] == 3
    assert not list(chain.context.workspace.rglob("must-not-write-*"))
    assert len(chain.model.requests) == 1 and len(chain.model.actions) == 1
