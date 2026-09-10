"""Freeze Feature072's stage-budget behavior using native runners and a fake provider."""

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from test_effect_trial import _fixture
from test_staged_effect_adapter import StagedSubject, _config, _profile, _request

from famou.agent_loop import AgentLoopRuntime
from famou.effect_adapters import EffectAdapterError, run_subject_adapter
from famou.effect_trial import EffectTrialConfig, EffectTrialRunner
from famou.staged_workflow import StagedWorkflowRunner, StagePolicy
from famou.workflow_checkpoint import WorkflowCheckpointError, WorkflowController


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    # Both native stages and AgentLoop must observe the same clock; only the fake provider
    # advances it. No test waits for the registered wall-clock durations.
    monkeypatch.setattr("famou.staged_workflow.time.monotonic", lambda: now[0])
    monkeypatch.setattr("famou.agent_loop.time.monotonic", lambda: now[0])
    return now


def measurement_profile():
    return replace(
        _profile(), model="GLM-5.2", timeout_seconds=5400, max_steps=200,
        max_total_tokens=8_000_000, input_cost_per_1k_micros=None,
        output_cost_per_1k_micros=None,
    )


def measurement_config(request, profile, master_seconds):
    fixture = _config(request, profile)
    return replace(
        fixture,
        manifest=replace(fixture.manifest, ceilings={
            "max_wall_seconds": 5400, "max_tool_steps": 200,
            "max_total_tokens": 8_000_000, "max_cost_micros": None,
        }),
        policy=StagePolicy(master_seconds, 2400, 120, checkpoint_after_rounds=32),
    )


class TimedSubject(StagedSubject):
    model = "GLM-5.2"

    def __init__(self, clock, *, master_duration=120, build_duration=0,
                 invalid_plan=False, timeout_stage=None):
        super().__init__()
        self.clock = clock
        self.master_duration = master_duration
        self.build_duration = build_duration
        self.invalid_plan = invalid_plan
        self.timeout_stage = timeout_stage
        self.timeouts = []

    def complete(self, messages, tools=(), timeout=None):
        self.timeouts.append(timeout)
        if (self.turn == 0 and self.timeout_stage == "master") or (
            self.turn == 2 and self.timeout_stage == "build"
        ):
            self.clock[0] += timeout
            raise TimeoutError("provider request ended without a usage response")
        self.clock[0] += (
            self.master_duration if self.turn == 0 else self.build_duration if self.turn == 1 else 0
        )
        turn = super().complete(messages, tools, timeout)
        return replace(
            turn, response_model=self.model,
            text="not a JSON plan" if self.invalid_plan and self.turn == 1 else turn.text,
        )


def native_runner(tmp_path, model, master_seconds):
    profile = measurement_profile()
    request = _request(tmp_path / "subject", profile)
    payload = json.loads(request.read_text())
    payload["requested_model"] = profile.model
    request.write_text(json.dumps(payload))
    config = measurement_config(request, profile, master_seconds)
    agent = AgentLoopRuntime(model, profile=profile, max_steps=profile.max_steps)
    controller = WorkflowController(request.parent, config.manifest)
    return StagedWorkflowRunner(controller, agent, request.parent, policy=config.policy), request


@pytest.mark.parametrize("master_seconds,master_duration,build_remaining,resume_remaining", [
    (300, 120, 5160, 2735),
    (1200, 120, 5160, 2735),
    (1200, 900, 4380, 1955),
])
def test_registered_master_caps_share_actual_elapsed_budget_with_build_and_resume(
    tmp_path, clock, master_seconds, master_duration, build_remaining, resume_remaining,
):
    model = TimedSubject(clock, master_duration=master_duration, build_duration=2400)
    runner, request = native_runner(tmp_path, model, master_seconds)

    outcome = runner.run("PUBLIC_TASK_SENTINEL")

    assert outcome.status == "checkpointed"
    assert model.timeouts == [master_seconds, build_remaining]
    build_messages = json.dumps(model.messages[1])
    assert "PUBLIC_TASK_SENTINEL" in build_messages
    assert "MODEL_PLAN_SENTINEL" in build_messages
    assert "Planning stage:" not in build_messages
    # The existing 2400-second policy pauses after a complete tool round, even below 32 rounds.
    assert runner.controller.state()["usage"]["total_tokens"] == 6
    clock[0] += 25  # Idle time between the cooperative pause and continuation also consumes time.
    final = runner.resume()

    assert final.status == "build_ready" and final.resumed is True
    assert model.timeouts == [master_seconds, build_remaining, resume_remaining]
    assert final.runtime.metadata["total_tokens"] == "9"
    assert runner.controller.state()["usage"]["tool_steps"] == 2
    assert runner.usage_ledger.snapshot.cost_micros is None
    assert not (request.parent / "receipt.json").exists()


@pytest.mark.parametrize("master_seconds", [300, 1200])
def test_longer_master_cap_does_not_admit_malformed_plan_to_build(tmp_path, clock, master_seconds):
    model = TimedSubject(clock, invalid_plan=True)
    runner, request = native_runner(tmp_path, model, master_seconds)

    with pytest.raises(WorkflowCheckpointError):
        runner.run("public task")

    assert model.timeouts == [master_seconds]
    assert runner.usage_ledger.snapshot.total_tokens == 3
    assert not (request.parent / "workflow/master.json").exists()
    assert not (request.parent / "workflow/session-transcript.jsonl").exists()
    with pytest.raises(WorkflowCheckpointError):
        runner.resume()


@pytest.mark.parametrize("master_seconds", [300, 1200])
@pytest.mark.parametrize("timeout_stage", ["master", "build"])
def test_unknown_usage_timeout_has_no_resume_receipt_or_harness_under_either_master_cap(
    tmp_path, monkeypatch, clock, master_seconds, timeout_stage,
):
    suite, baseline, public, subject_command, harness_command = _fixture(tmp_path)
    profile = measurement_profile()
    baseline_payload = json.loads(baseline.read_text())
    baseline_payload["model"].update(requested=profile.model, effective=profile.model)
    baseline.write_text(json.dumps(baseline_payload))
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile.to_dict()))
    model = TimedSubject(clock, timeout_stage=timeout_stage)
    invocations, native_runners = [], []

    def capture_runner(*args, **kwargs):
        runner = StagedWorkflowRunner(*args, **kwargs)
        native_runners.append(runner)
        return runner

    monkeypatch.setattr("famou.effect_adapters.StagedWorkflowRunner", capture_runner)

    def executor(command, *, cwd, env, timeout):
        invocations.append(cwd.name)
        assert cwd.name == "subject", "unknown usage must never authorize harness execution"
        request = Path(command[-1])
        with pytest.raises(EffectAdapterError):
            run_subject_adapter(
                request, model_runtime=model, model_profile=profile, max_steps=200,
                workflow_config=measurement_config(request, profile, master_seconds),
            )
        return subprocess.CompletedProcess(command, 2)

    trial = tmp_path / "trial"
    report = EffectTrialRunner(
        suite, baseline, trial, case_sources={"fixture_case": public},
        config=EffectTrialConfig(
            runs_per_case=1, timeout_seconds=5400, requested_model=profile.model,
            subject_model_profile_path=profile_path,
            subject_command=subject_command, harness_command=harness_command,
        ),
        process_executor=executor,
    ).run().to_dict()

    assert invocations == ["subject"] and len(native_runners) == 1
    runner = native_runners[0]
    assert not runner.usage_ledger.usage_complete
    with pytest.raises(WorkflowCheckpointError):
        runner.resume()
    assert model.timeouts == ([master_seconds] if timeout_stage == "master" else [
        master_seconds, 5160, 5160,
    ])
    assert runner.controller.state()["resume_used"] is False
    assert runner.controller.state()["checkpoint_number"] is None
    runs = report["cases"][0]["runs"]
    assert len(runs) == 1 and runs[0]["status"] == "failed" and runs[0]["ready"] is False
    assert runs[0]["validity_score"] is None and runs[0]["overall_score"] is None
    assert runs[0]["usage"] is None and runs[0]["cost_micros"] is None
    attempt = trial / runs[0]["attempt"]
    assert (attempt / "subject/solution.json").exists() is (timeout_stage == "build")
    assert not (attempt / "subject/receipt.json").exists()
    assert not (attempt / "harness").exists()
