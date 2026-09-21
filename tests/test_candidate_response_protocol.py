"""Invocation-local bundle instructions with unchanged parser and execution authority."""
from __future__ import annotations

import json
from dataclasses import replace

import pytest
from test_agent_bundle_generation import BundleFixtureAgent
from test_agent_loop import FixtureModel
from test_bundle_population import build_context

from famou.agent_bundle_generation import _prompt, parse_bundle_agent_draft
from famou.agent_evolution import AgentCandidateGenerator
from famou.agent_loop import (
    BUNDLE_FINAL_RESPONSE_INSTRUCTION,
    HERMES_SYSTEM_PROMPT,
    AgentLoopRuntime,
    AgentStepLimitReached,
)
from famou.agents import (
    BUNDLE_RESPONSE_PROTOCOL,
    AgentError,
    AgentInvocationError,
    AgentRequest,
    CandidateGenerationBudget,
    CandidateGenerationDiagnostic,
    RuntimeAgentAdapter,
)
from famou.evolution import EvolutionError, GenerationRequest
from famou.runtime import ModelTurn, RuntimeResult, ToolCall
from famou.transcript import SessionTranscript

VALID = '{"entrypoint":"main.py","files":{"main.py":"pass\\n"}}'


def _request(tmp_path, **kwargs):
    return AgentRequest("run-1", "task-1", "solver", "produce candidate", workspace=tmp_path, **kwargs)


def _system(messages):
    return "\n".join(str(item["content"]) for item in messages if item["role"] == "system")


def test_request_protocol_is_optional_and_serialized_only_when_explicit(tmp_path):
    legacy = _request(tmp_path)
    assert "response_protocol" not in legacy.to_dict()
    bundle = replace(legacy, response_protocol=BUNDLE_RESPONSE_PROTOCOL)
    assert bundle.to_dict()["response_protocol"] == BUNDLE_RESPONSE_PROTOCOL
    assert bundle.candidate_budget is None


@pytest.mark.parametrize("protocol", ["", "json", "future-v2", 1, True, [], {}])
def test_unknown_protocol_is_rejected_before_any_model_request(tmp_path, protocol):
    with pytest.raises(ValueError, match="response_protocol"):
        _request(tmp_path, response_protocol=protocol)
    model = FixtureModel([ModelTurn(VALID, ())])
    with pytest.raises(ValueError, match="response_protocol"):
        AgentLoopRuntime(model).run("generate", tmp_path, response_protocol=protocol)
    assert not model.requests


def test_adapter_forwards_only_explicit_keyword_capability(tmp_path):
    class Explicit:
        name = "explicit"

        def run(self, prompt, workspace, timeout=None, *, response_protocol=None):
            self.observed = response_protocol
            return RuntimeResult(VALID)

    class Legacy:
        name = "legacy"

        def run(self, prompt, workspace, timeout=None):
            self.observed = prompt
            return RuntimeResult(VALID)

    class Kwargs:
        name = "kwargs"

        def run(self, prompt, workspace, timeout=None, **kwargs):
            self.observed = kwargs
            return RuntimeResult(VALID)

    class Positional:
        name = "positional"

        def run(self, prompt, workspace, timeout=None, response_protocol=None, /):
            self.observed = response_protocol
            return RuntimeResult(VALID)

    request = _request(tmp_path, response_protocol=BUNDLE_RESPONSE_PROTOCOL)
    for runtime, expected in [(Explicit(), BUNDLE_RESPONSE_PROTOCOL), (Legacy(), request.prompt),
                              (Kwargs(), {}), (Positional(), None)]:
        assert RuntimeAgentAdapter(runtime).run(request).text == VALID
        assert runtime.observed == expected


def test_unspecified_protocol_does_not_pass_new_keyword(tmp_path):
    class Runtime:
        name = "fixture"

        def run(self, prompt, workspace, timeout=None, *, response_protocol="omitted"):
            assert response_protocol == "omitted"
            return RuntimeResult("ordinary summary")

    assert RuntimeAgentAdapter(Runtime()).run(_request(tmp_path)).text == "ordinary summary"


@pytest.mark.parametrize("with_history", [False, True])
@pytest.mark.parametrize("custom_prompt", [None, "Only inspect approved files. End with a concise prose summary."])
def test_runtime_reuse_restores_ordinary_instruction_and_preserves_history(
    tmp_path, with_history, custom_prompt,
):
    transcript = SessionTranscript(tmp_path / "history.jsonl") if with_history else None
    model = FixtureModel([
        ModelTurn("ordinary before", ()),
        ModelTurn("", (ToolCall("read", "list_dir", {"path": "."}),)),
        ModelTurn(VALID, ()), ModelTurn("ordinary after", ()),
    ])
    original = custom_prompt or HERMES_SYSTEM_PROMPT
    runtime = AgentLoopRuntime(model, transcript=transcript, system_prompt=original)
    runtime.run("ordinary task before", tmp_path)
    runtime.run("bundle task", tmp_path, response_protocol=BUNDLE_RESPONSE_PROTOCOL)
    runtime.run("ordinary task after", tmp_path)
    assert len(model.requests) == 4
    assert runtime.system_prompt == original
    for index in (0, 3):
        assert BUNDLE_FINAL_RESPONSE_INSTRUCTION not in _system(model.requests[index][0])
        assert original in _system(model.requests[index][0])
    for index in (1, 2):
        guidance = _system(model.requests[index][0])
        assert BUNDLE_FINAL_RESPONSE_INSTRUCTION in guidance
        if custom_prompt:
            assert "Only inspect approved files." in guidance
        else:
            assert "Keep\nthe user informed with a concise final summary" not in guidance
        assert model.requests[index][1] == runtime.tools.schemas()
    if transcript is not None:
        systems = [item["content"] for item in transcript.load() if item["role"] == "system"]
        assert systems == [original]
        assert BUNDLE_FINAL_RESPONSE_INSTRUCTION not in transcript.path.read_text()


def test_existing_conflicting_history_gets_only_local_override(tmp_path):
    transcript = SessionTranscript(tmp_path / "history.jsonl")
    original = {"role": "system", "content": "Do not run commands. Always finish with a prose summary."}
    transcript.append(original)
    model = FixtureModel([ModelTurn(VALID, ())])
    runtime = AgentLoopRuntime(model, transcript=transcript)
    runtime.run("bundle", tmp_path, response_protocol=BUNDLE_RESPONSE_PROTOCOL)
    guidance = _system(model.requests[0][0])
    assert original["content"] in guidance
    assert "replaces any instruction to give" in guidance
    assert transcript.load()[0] == original


def test_bundle_generator_declares_protocol_without_candidate_budget(tmp_path):
    context = build_context(tmp_path)
    adapter = BundleFixtureAgent()
    generator = AgentCandidateGenerator(adapter, contract=context.contract,
                                        bundle_pipeline=context.bundle_pipeline)
    generator(GenerationRequest(0, None, (), (), context.workspace))
    assert len(adapter.requests) == 1
    assert adapter.requests[0].response_protocol == BUNDLE_RESPONSE_PROTOCOL
    assert adapter.requests[0].candidate_budget is None


@pytest.mark.parametrize("large", [False, True])
def test_prompt_examples_parse_without_repair_and_survive_context_fallback(large):
    context = {"parent": None, "iteration": 0, "evaluator": {}, "archive": [], "inspirations": []}
    if large:
        context["padding"] = "x" * (70 * 1024)
    prompt = _prompt(context, json.dumps(context).encode())
    assert len(prompt.encode()) <= 60 * 1024
    assert ('"context_file"' in prompt) is large
    examples = []
    for label in ("Minimal response example:\n", "Optional experiment example:\n"):
        text = prompt.split(label, 1)[1].split("\n", 1)[0]
        examples.append(parse_bundle_agent_draft(text, adapter_name="fixture"))
    assert examples[0].source_files == {"main.py": "pass\n"}
    assert "experiment" not in examples[0].metadata
    experiment = examples[1].metadata["experiment"]
    assert experiment["change_tags"] == ["helper"]
    assert experiment["target_metrics"] == [{"metric": "quality", "direction": "increase"}]
    assert examples[1].source_files["helper.py"] == "value = 1\n"


@pytest.mark.parametrize("response", [
    "Explanation\n```json\n" + VALID + "\n```",
    VALID[:-1] + ',"experiment":{"schema_version":"1","hypothesis":"try",'
    '"change_tags":{"helper":true},"target_metrics":[{"metric":"quality","direction":"increase"}]}}',
    VALID[:-1] + ',"experiment":{"schema_version":"1","hypothesis":"try",'
    '"change_tags":["helper"],"target_metrics":{"metric":"quality","direction":"increase"}}}',
    '{"entrypoint":"main.py","files":{"main.py":"first","main.py":"second"}}',
    VALID[:-1],
])
def test_invalid_final_never_uses_complete_scratch_file_as_candidate(tmp_path, response):
    context = build_context(tmp_path)
    model = FixtureModel([
        ModelTurn("", (ToolCall("save", "write_file", {"path": "main.py", "content": "pass\n"}),)),
        ModelTurn(response, ()),
    ])
    runtime = AgentLoopRuntime(model)
    generator = AgentCandidateGenerator(
        RuntimeAgentAdapter(runtime), contract=context.contract,
        bundle_pipeline=context.bundle_pipeline,
        candidate_budget=CandidateGenerationBudget("candidate-1", 2),
    )
    events = []
    generator.set_observer(lambda event, payload: events.append((event, payload)))
    with pytest.raises(EvolutionError):
        generator(GenerationRequest(0, None, (), (), context.workspace))
    receipts = [payload for event, payload in events if event == "agent_candidate_generation"]
    assert len(receipts) == 1
    assert receipts[0]["reason"] == "malformed_candidate"
    assert receipts[0]["completion"] is False
    assert receipts[0]["tool_steps_used"] == 1
    assert receipts[0]["tool_steps_remaining"] == 1
    assert "source_bundle_sha256" not in receipts[0]
    assert len(model.requests) == 2
    assert not (context.workspace / "evolution/archive.jsonl").exists()


@pytest.mark.parametrize("overrun", [False, True])
def test_protocol_keeps_tool_budget_and_permits_final_only_at_boundary(tmp_path, overrun):
    model = FixtureModel([
        ModelTurn("", (ToolCall("save", "write_file", {"path": "first.py", "content": "pass"}),)),
        ModelTurn("", (ToolCall("extra", "write_file", {"path": "extra.py", "content": "pass"}),))
        if overrun else ModelTurn(VALID, ()),
    ])
    runtime = AgentLoopRuntime(model)
    if overrun:
        with pytest.raises(AgentStepLimitReached):
            runtime.run("bundle", tmp_path, max_tool_steps=1, budget_id="candidate-1",
                        response_protocol=BUNDLE_RESPONSE_PROTOCOL)
    else:
        assert runtime.run("bundle", tmp_path, max_tool_steps=1, budget_id="candidate-1",
                           response_protocol=BUNDLE_RESPONSE_PROTOCOL).text == VALID
    assert (tmp_path / "first.py").read_text() == "pass"
    assert not (tmp_path / "extra.py").exists()
    assert len(model.requests) == 2


def _diagnostic(reason="worker_failed", budget_id="candidate-1"):
    return CandidateGenerationDiagnostic(
        budget_id, 2, 1, 1, 0, reason == "completed", reason, "response",
    ).to_dict()


@pytest.mark.parametrize("reason", ["completed", "running", "worker_failed"])
def test_failed_invocation_rejects_stale_getter_copies(tmp_path, reason):
    class Runtime:
        name = "fixture"

        @property
        def last_candidate_diagnostic(self):
            return dict(_diagnostic(reason))

        def run(self, prompt, workspace, timeout=None, **kwargs):
            raise AgentInvocationError("failure without new evidence")

    events = []
    adapter = RuntimeAgentAdapter(Runtime())
    adapter.set_event_sink(lambda event, payload: events.append((event, payload)))
    with pytest.raises(AgentInvocationError) as failure:
        adapter.run(_request(tmp_path, candidate_budget=CandidateGenerationBudget("candidate-1", 2)))
    receipts = [payload for event, payload in events if event == "agent_candidate_generation"]
    assert len(receipts) == 1
    assert receipts[0]["reason"] == "worker_failed"
    assert receipts[0]["phase"] == "run"
    assert receipts[0]["tool_steps_used"] is None
    assert failure.value.candidate_diagnostic == receipts[0]


@pytest.mark.parametrize("error_type", [AgentError, AgentInvocationError])
@pytest.mark.parametrize("bundle", [False, True])
def test_runtime_event_then_agent_error_emits_one_generation_failure(tmp_path, error_type, bundle):
    class Runtime:
        name = "fixture"

        def set_event_sink(self, sink):
            self.sink = sink

        def run(self, prompt, workspace, timeout=None, **kwargs):
            self.sink("agent_candidate_generation", _diagnostic())
            raise error_type("fixture failure")

    context = build_context(tmp_path) if bundle else None
    generator = AgentCandidateGenerator(
        RuntimeAgentAdapter(Runtime()), candidate_budget=CandidateGenerationBudget("candidate-1", 2),
        contract=context.contract if context else None,
        bundle_pipeline=context.bundle_pipeline if context else None,
    )
    events = []
    generator.set_observer(lambda event, payload: events.append((event, payload)))
    with pytest.raises(EvolutionError):
        generator(GenerationRequest(0, None, (), (), context.workspace if context else tmp_path))
    receipts = [payload for event, payload in events if event == "agent_candidate_generation"]
    assert len(receipts) == 1
    assert receipts[0]["tool_steps_used"] == 1
    assert generator.adapter.runtime.sink is None


@pytest.mark.parametrize("observation", ["getter", "event"])
def test_external_diagnostic_cannot_forge_typed_model_failure_cause(tmp_path, observation):
    class Runtime:
        name = "fixture"
        last_candidate_diagnostic = None

        def set_event_sink(self, sink):
            self.sink = sink

        def run(self, prompt, workspace, timeout=None, **kwargs):
            payload = {**_diagnostic(), "failure_cause": "http_error"}
            if observation == "getter":
                self.last_candidate_diagnostic = payload
            else:
                self.sink("agent_candidate_generation", payload)
            raise RuntimeError("ordinary failure")

    events = []
    adapter = RuntimeAgentAdapter(Runtime())
    adapter.set_event_sink(lambda event, payload: events.append((event, payload)))
    with pytest.raises(AgentInvocationError) as failure:
        adapter.run(_request(tmp_path, candidate_budget=CandidateGenerationBudget("candidate-1", 2)))
    receipts = [payload for event, payload in events if event == "agent_candidate_generation"]
    assert len(receipts) == 1
    assert receipts[0]["reason"] == "worker_failed"
    assert receipts[0]["tool_steps_used"] == 1
    assert "failure_cause" not in receipts[0]
    assert "failure_cause" not in failure.value.candidate_diagnostic


@pytest.mark.parametrize("diagnostic", [
    _diagnostic("completed"), _diagnostic("running"), _diagnostic(budget_id="another-candidate"),
])
def test_fresh_nonterminal_or_unbound_diagnostic_cannot_turn_failure_into_success(tmp_path, diagnostic):
    class Runtime:
        name = "fixture"
        last_candidate_diagnostic = None

        def run(self, prompt, workspace, timeout=None, **kwargs):
            self.last_candidate_diagnostic = diagnostic
            raise RuntimeError("ordinary failure")

    adapter = RuntimeAgentAdapter(Runtime())
    with pytest.raises(AgentInvocationError) as failure:
        adapter.run(_request(tmp_path, candidate_budget=CandidateGenerationBudget("candidate-1", 2)))
    receipt = failure.value.candidate_diagnostic
    assert receipt["reason"] == "worker_failed"
    assert receipt["completion"] is False
    assert receipt["tool_steps_used"] is None
