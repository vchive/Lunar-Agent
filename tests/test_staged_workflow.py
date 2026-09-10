"""Exercise the runner with real AgentLoopRuntime and deterministic provider responses."""
import hashlib
import json
from dataclasses import replace

import pytest
from test_staged_effect_adapter import StagedSubject, _config, _profile, _request

from famou.agent_loop import AgentLoopRuntime
from famou.runtime import ModelTurn, RuntimeExecutionError
from famou.staged_workflow import StagedWorkflowConfig, StagedWorkflowRunner, StagePolicy
from famou.workflow_checkpoint import WorkflowCheckpointError, WorkflowController


def rig(tmp_path, *, model=None, policy=None):
    profile = _profile()
    request = _request(tmp_path / "subject", profile)
    config = _config(request, profile)
    agent = AgentLoopRuntime(model or StagedSubject(), profile=profile)
    controller = WorkflowController(request.parent, config.manifest)
    runner = StagedWorkflowRunner(
        controller, agent, request.parent, policy=policy or config.policy,
    )
    return runner, agent, request


def test_durable_boundary_replays_pairs_with_same_identity_and_no_budget_reset(tmp_path):
    runner, agent, request = rig(tmp_path)
    first = runner.run("public task")
    assert first.status == "checkpointed" and first.runtime is None
    state = runner.controller.state()
    assert state["usage"]["total_tokens"] == 6
    assert state["usage"]["tool_steps"] == 2
    checkpoint_path = request.parent / "workflow/checkpoints/000001.json"
    checkpoint_bytes = checkpoint_path.read_bytes()
    transcript = request.parent / "workflow/transcript-000001.jsonl"
    transcript_bytes = transcript.read_bytes()
    final = runner.resume()
    assert final.runtime.metadata["turns"] == "3"
    assert final.runtime.metadata["total_tokens"] == "9"
    assert final.runtime.metadata["cost_micros"] == "9"
    assert runner.controller.state()["resume_used"] is True
    assert transcript.read_bytes() == transcript_bytes
    assert checkpoint_path.read_bytes() == checkpoint_bytes
    assert hashlib.sha256(transcript_bytes).hexdigest() == json.loads(checkpoint_bytes)["transcript"]["sha256"]
    resumed_messages = agent.model.messages[-1]
    assert [message["tool_call_id"] for message in resumed_messages if message["role"] == "tool"] == ["candidate", "summary"]
    assert "MODEL_PLAN_SENTINEL" in json.dumps(resumed_messages)
    assert "Planning stage:" not in json.dumps(resumed_messages)
    assert not (request.parent / "receipt.json").exists()
    assert not (request.parent / "harness").exists()
    with pytest.raises(WorkflowCheckpointError):
        runner.resume()
    with pytest.raises(WorkflowCheckpointError):
        runner.run("different prompt")
    assert agent.model.turn == 3


@pytest.mark.parametrize("target", ["usage", "transcript", "candidate"])
def test_changed_checkpoint_context_blocks_resume_without_provider_request(tmp_path, target):
    runner, agent, request = rig(tmp_path)
    runner.run("public task")
    if target == "usage":
        runner.usage_ledger.record({"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})
    elif target == "transcript":
        agent._transcript.append({"role": "user", "content": "unregistered change"})
    else:
        (request.parent / "solution.json").write_text("changed candidate")
    with pytest.raises(WorkflowCheckpointError):
        runner.resume()
    assert agent.model.turn == 2


def test_resume_deadline_does_not_restart_and_idle_time_counts(tmp_path, monkeypatch):
    now = [0.0]
    monkeypatch.setattr("famou.staged_workflow.time.monotonic", lambda: now[0])
    runner, agent, _request_path = rig(tmp_path)
    now[0] = 100  # Construction time is not attempt time.
    runner.run("public task")
    now[0] = 110
    with pytest.raises(RuntimeExecutionError, match="deadline"):
        runner.resume()
    assert agent.model.turn == 2


def test_schedule_and_profile_must_bind_before_model_calls(tmp_path):
    runner, agent, request = rig(tmp_path)
    with pytest.raises(WorkflowCheckpointError, match="reservations"):
        StagedWorkflowConfig(runner.config.manifest, StagePolicy(5, 5, 1))
    wrong = replace(runner.config.manifest, model_profile_sha256="0" * 64)
    different_workspace = tmp_path / "wrong"
    controller = WorkflowController(different_workspace, wrong)
    with pytest.raises(WorkflowCheckpointError, match="profile"):
        StagedWorkflowRunner(controller, agent, different_workspace, policy=runner.config.policy)
    with pytest.raises(WorkflowCheckpointError, match="workspace"):
        StagedWorkflowRunner(runner.controller, agent, request.parent / "other", policy=runner.config.policy)
    assert agent.model.turn == 0


def test_provider_timeout_never_becomes_cooperative_resume(tmp_path):
    class TimedOut(StagedSubject):
        def complete(self, messages, tools=(), timeout=None):
            if self.turn == 2:
                self.turn += 1
                raise TimeoutError("unobserved usage")
            return super().complete(messages, tools, timeout)

    runner, agent, request = rig(tmp_path, model=TimedOut(), policy=StagePolicy(2, 5, 1))
    with pytest.raises(TimeoutError):
        runner.run("public task")
    assert (request.parent / "solution.json").exists()
    assert not runner.usage_ledger.usage_complete
    with pytest.raises(WorkflowCheckpointError):
        runner.resume()
    assert agent.model.turn == 3


@pytest.mark.parametrize("content", ["not json", '{"plan":[],"expected_paths":[]}', '{"plan":["x"],"expected_paths":["../escape"]}'])
def test_invalid_model_plan_is_terminal_before_build(tmp_path, content):
    class InvalidPlan(StagedSubject):
        def complete(self, messages, tools=(), timeout=None):
            self.turn += 1
            return ModelTurn(content, usage={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3})

    runner, agent, _request_path = rig(tmp_path, model=InvalidPlan())
    with pytest.raises((WorkflowCheckpointError, ValueError)):
        runner.run("public task")
    assert agent.model.turn == 1
    assert runner.controller.state()["usage"]["total_tokens"] == 3
    with pytest.raises(WorkflowCheckpointError):
        runner.resume()


def test_reconstructed_runner_cannot_reset_an_existing_attempt(tmp_path):
    runner, agent, request = rig(tmp_path)
    runner.run("public task")
    with pytest.raises(WorkflowCheckpointError, match="fresh attempt"):
        StagedWorkflowRunner(runner.controller, agent, request.parent, policy=runner.config.policy)


@pytest.mark.parametrize("target", ["config", "master"])
@pytest.mark.parametrize("at_turn", [2, 3])
def test_control_evidence_changed_during_model_turn_cannot_publish_receipt(tmp_path, target, at_turn):
    from famou.effect_adapters import EffectAdapterError, run_subject_adapter

    profile = _profile()
    request = _request(tmp_path / "subject", profile)
    config = _config(request, profile, checkpoint_after_rounds=1 if at_turn == 2 else None)

    class MutatesControl(StagedSubject):
        def complete(self, messages, tools=(), timeout=None):
            result = super().complete(messages, tools, timeout)
            if self.turn == at_turn:
                path = request.parent / "workflow" / f"{target}.json"
                content = json.loads(path.read_text())
                if target == "config":
                    content["policy"]["build_seconds"] = 1
                else:
                    content["plan"] = ["changed plan"]
                    payload = {key: value for key, value in content.items() if key != "plan_sha256"}
                    content["plan_sha256"] = hashlib.sha256((json.dumps(
                        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                    ) + "\n").encode()).hexdigest()
                path.write_text(json.dumps(content))
            return result

    model = MutatesControl()
    with pytest.raises(EffectAdapterError):
        run_subject_adapter(
            request, model_runtime=model, model_profile=profile, workflow_config=config,
        )
    assert model.turn == at_turn
    assert not (request.parent / "receipt.json").exists()
    assert not list((request.parent / "workflow/checkpoints").iterdir())
