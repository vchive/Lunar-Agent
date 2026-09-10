"""Deterministic Master envelopes through real agent, subject, and native trial boundaries."""

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from test_effect_trial import _fixture
from test_staged_effect_adapter import _config, _profile, _request

from famou.agent_loop import AgentLoopRuntime
from famou.effect_adapters import EffectAdapterError, run_subject_adapter
from famou.effect_trial import EffectTrialConfig, EffectTrialRunner
from famou.runtime import ModelTurn, RuntimeExecutionError, ToolCall
from famou.staged_workflow import StagedWorkflowRunner
from famou.workflow_checkpoint import WorkflowCheckpointError, WorkflowController


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("famou.staged_workflow.time.monotonic", lambda: now[0])
    monkeypatch.setattr("famou.agent_loop.time.monotonic", lambda: now[0])
    return now


def profile():
    return replace(_profile(), model="glm-5.2")


class EnvelopeSubject:
    """Four fixed responses; no provider, subprocess, or historical candidate is used."""

    model = "glm-5.2"
    api_key = "fixture-known-master-key"

    def __init__(self, clock, envelope, *, failure=None, public_vocabulary=False):
        self.clock, self.envelope, self.failure = clock, envelope, failure
        self.public_vocabulary = public_vocabulary
        self.messages, self.timeouts = [], []
        self.turn = 0

    def master_text(self):
        payload = {
            "plan": ["PLAN_SENTINEL: produce the fixture answer.",
                     f"Remember {self.api_key}.", "Use api_key=sk-1234567890 safely."],
            "expected_paths": ["solution.json", "_agent_summary.md"],
        }
        if self.public_vocabulary:
            payload["plan"].extend([
                "Implement an objective scorer with combined_score using the public evaluator formula.",
                "Start from a baseline heuristic and check public constraints with a local test harness.",
                "Do not read private inputs or persist credential material.",
            ])
            payload["expected_paths"].extend(["scorer.py", "baseline_solution.py"])
        if self.failure == "unsafe_path":
            payload["expected_paths"].append("../escape.json")
        elif self.failure == "reserved_path":
            payload["expected_paths"].append("./workflow/config.json")
        elif self.failure == "missing_summary":
            payload["expected_paths"] = ["solution.json"]
        elif self.failure == "extra_score_field":
            payload["overall_score"] = 999
        elif self.failure == "actual_key_path":
            payload["expected_paths"].append(self.api_key + ".py")
        elif self.failure == "generic_key_path":
            payload["expected_paths"].append("api_key=sk-1234567890.py")
        body = json.dumps(payload)
        fenced = "WRAPPER_SENTINEL with `inline` explanation.\n```json\n" + body + "\n```\nDone."
        if self.failure == "multiple_fences":
            return fenced + "\n```json\n" + body + "\n```"
        if self.failure == "outside_object":
            return "{}\n" + fenced
        return " \n" + body + "\n " if self.envelope == "raw" else fenced

    def complete(self, messages, tools=(), timeout=None):
        del tools
        self.messages.append(json.loads(json.dumps(messages)))
        self.timeouts.append(timeout)
        self.turn += 1
        self.clock[0] += 2.0 if self.turn == 3 else 0.25
        usage = {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}
        if self.turn == 1:
            return ModelTurn("", (ToolCall("master-inspection", "read_file", {
                "path": "case/instruction.md",
            }),), response_model=self.model, usage=usage)
        if self.turn == 2:
            return ModelTurn(self.master_text(), response_model=self.model, usage=usage)
        if self.turn == 3:
            summary = "Final: solution.json"
            if self.public_vocabulary:
                summary += "\nFixture local self-test reports combined_score=999 and validity_score=1.0."
            calls = [
                ToolCall("candidate", "write_file", {"path": "solution.json", "content": '{"answer":42}'}),
                ToolCall("summary", "write_file", {"path": "_agent_summary.md", "content": summary}),
            ]
            if self.public_vocabulary:
                calls.extend([
                    ToolCall("public-scorer", "write_file", {
                        "path": "scorer.py", "content": "# Fixture public objective scorer; never executed.\n",
                    }),
                    ToolCall("baseline-heuristic", "write_file", {
                        "path": "baseline_solution.py", "content": "# Fixture baseline heuristic; never executed.\n",
                    }),
                ])
            return ModelTurn("", tuple(calls), response_model=self.model, usage=usage)
        if self.turn == 4:
            if self.failure == "build_failure":
                raise RuntimeExecutionError("FIXTURE-BUILD-FAILURE-SENTINEL")
            text = "The fixture answer is ready."
            if self.public_vocabulary:
                text += " The fixture local self-test reports combined_score=999."
            return ModelTurn(text, response_model=self.model, usage=usage)
        raise AssertionError("a deterministic envelope must not add provider requests")


@pytest.mark.parametrize("envelope", ["raw", "fenced"])
def test_envelopes_share_original_budget_tool_history_and_existing_redaction(tmp_path, clock, envelope):
    model_profile = profile()
    request = _request(tmp_path / "subject", model_profile)
    config = _config(request, model_profile, checkpoint_after_rounds=1)
    model = EnvelopeSubject(clock, envelope)
    agent = AgentLoopRuntime(model, profile=model_profile, max_steps=model_profile.max_steps)
    controller = WorkflowController(request.parent, config.manifest)
    runner = StagedWorkflowRunner(controller, agent, request.parent, policy=config.policy)

    first = runner.run("PUBLIC_TASK_SENTINEL")

    assert first.status == "checkpointed" and model.turn == 3
    assert model.timeouts == [2, 1.75, 8.5]
    assert controller.state()["usage"]["total_tokens"] == 9
    assert controller.state()["usage"]["tool_steps"] == 3
    build_messages = json.dumps(model.messages[2])
    assert "PUBLIC_TASK_SENTINEL" in build_messages and "PLAN_SENTINEL" in build_messages
    assert "WRAPPER_SENTINEL" not in build_messages and "Planning stage:" not in build_messages
    assert "master-inspection" not in build_messages
    assert model.api_key not in build_messages and "sk-1234567890" not in build_messages
    assert "[REDACTED]" in build_messages
    master = controller.load_master()
    assert master["request_sha256"] == config.manifest.request_sha256
    assert master["expected_paths"] == ["solution.json", "_agent_summary.md"]
    assert model.api_key not in json.dumps(master) and "sk-1234567890" not in json.dumps(master)
    clock[0] += 1.0  # The same attempt's idle time also consumes its aggregate window.

    final = runner.resume()

    assert final.status == "build_ready" and final.resumed is True and model.turn == 4
    assert model.timeouts == [2, 1.75, 8.5, 5.5]
    assert runner.usage_ledger.snapshot.total_tokens == 12
    assert runner.usage_ledger.snapshot.cost_micros == 12
    assert controller.state()["usage"]["tool_steps"] == 3
    assert controller.state()["resume_used"] is True
    assert [message["tool_call_id"] for message in model.messages[3] if message["role"] == "tool"] == [
        "candidate", "summary",
    ]
    assert not (request.parent / "receipt.json").exists()
    with pytest.raises(WorkflowCheckpointError):
        runner.resume()
    assert model.turn == 4


def run_native_trial(
    tmp_path, monkeypatch, clock, envelope, *, failure=None, public_vocabulary=False, receipt_failure=None,
):
    suite, baseline, public, subject_command, harness_command = _fixture(tmp_path)
    model_profile = profile()
    prior = json.loads(baseline.read_text())
    prior["model"].update(requested=model_profile.model, effective=model_profile.model)
    baseline.write_text(json.dumps(prior))
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(model_profile.to_dict()))
    model = EnvelopeSubject(clock, envelope, failure=failure, public_vocabulary=public_vocabulary)
    phases, native_runners = [], []

    class ReceiptBoundaryRunner(StagedWorkflowRunner):
        def resume(self):
            if self.controller.state()["stage"] == "checkpointed":
                assert not (self.workspace / "receipt.json").exists()
                assert not (self.workspace.parent / "harness").exists()
            return super().resume()

    def capture_runner(*args, **kwargs):
        runner = ReceiptBoundaryRunner(*args, **kwargs)
        native_runners.append(runner)
        return runner

    monkeypatch.setattr("famou.effect_adapters.StagedWorkflowRunner", capture_runner)

    def execute(command, *, cwd, env, timeout):
        del env, timeout
        phases.append(cwd.name)
        request = Path(command[-1])
        if cwd.name == "subject":
            try:
                receipt = run_subject_adapter(
                    request, model_runtime=model, model_profile=model_profile,
                    max_steps=model_profile.max_steps,
                    workflow_config=_config(request, model_profile, checkpoint_after_rounds=1),
                )
            except EffectAdapterError:
                return subprocess.CompletedProcess(command, 2)
            assert "validity_score" not in receipt and "overall_score" not in receipt
            if receipt_failure == "missing":
                (cwd / "receipt.json").unlink()
            elif receipt_failure == "extra_score_field":
                (cwd / "receipt.json").write_text(json.dumps({**receipt, "overall_score": 999}))
        else:
            # A deterministic fixture receipt, only after the native subject receipt gate.
            assert cwd.name == "harness" and (cwd.parent / "subject/receipt.json").is_file()
            payload = json.loads(request.read_text())
            (cwd / "receipt.json").write_text(json.dumps({
                "schema_version": "1", "status": "completed",
                **{key: payload[key] for key in ("benchmark", "evaluation_profile", "case", "harness")},
                "extraction_status": "completed", "validity_score": 1.0,
                "overall_score": 0.81, "quality_score": 0.81, "detail_metrics": {},
            }))
        return subprocess.CompletedProcess(command, 0)

    trial = tmp_path / "trial"
    native_trial = EffectTrialRunner(
        suite, baseline, trial, case_sources={"fixture_case": public},
        config=EffectTrialConfig(
            runs_per_case=1, timeout_seconds=model_profile.timeout_seconds, requested_model=model_profile.model,
            subject_model_profile_path=profile_path, subject_command=subject_command, harness_command=harness_command,
        ), process_executor=execute,
    )
    result = native_trial.run().to_dict()
    assert len(result["cases"]) == len(result["cases"][0]["runs"]) == len(native_runners) == 1
    run = result["cases"][0]["runs"][0]
    attempt = trial / run["attempt"]
    assert len(list(attempt.parent.iterdir())) == 1
    return run, attempt, model, native_runners[0], phases


@pytest.mark.parametrize("envelope", ["raw", "fenced"])
def test_envelope_handoff_uses_native_subject_receipt_and_one_harness_dispatch(
    tmp_path, monkeypatch, clock, envelope,
):
    run, attempt, model, runner, phases = run_native_trial(tmp_path, monkeypatch, clock, envelope)

    assert phases == ["subject", "harness"] and model.turn == 4
    assert model.timeouts == [2, 1.75, 8.5, 6.5]
    assert run["status"] == "completed" and run["ready"] is True
    assert run["validity_score"] == 1.0 and run["overall_score"] == 0.81
    assert run["interaction_turns"] == 4 and run["elapsed_ms"] == 2750
    assert run["usage"] == {"input_tokens": 8, "output_tokens": 4, "total_tokens": 12}
    assert run["cost_micros"] == 12
    assert runner.controller.state()["usage"]["tool_steps"] == 3
    assert runner.controller.state()["resume_used"] is True
    assert json.loads((attempt / "subject/solution.json").read_text()) == {"answer": 42}
    receipt = json.loads((attempt / "subject/receipt.json").read_text())
    assert receipt["usage"] == run["usage"] and "validity_score" not in receipt
    assert "WRAPPER_SENTINEL" not in (attempt / "subject/workflow/session-transcript.jsonl").read_text()
    assert (attempt / "harness/receipt.json").is_file()


@pytest.mark.parametrize("envelope", ["raw", "fenced"])
def test_public_plan_vocabulary_and_output_names_resume_with_only_native_harness_scores(
    tmp_path, monkeypatch, clock, envelope,
):
    run, attempt, model, runner, phases = run_native_trial(
        tmp_path, monkeypatch, clock, envelope, public_vocabulary=True,
    )

    assert phases == ["subject", "harness"] and model.turn == 4
    assert run["status"] == "completed" and run["ready"] is True
    assert run["validity_score"] == 1.0 and run["overall_score"] == 0.81
    assert run["usage"] == {"input_tokens": 8, "output_tokens": 4, "total_tokens": 12}
    assert run["cost_micros"] == 12 and model.timeouts == [2, 1.75, 8.5, 6.5]
    subject = attempt / "subject"
    master = runner.controller.load_master()
    state = runner.controller.state()
    assert state["stage"] == "build_ready" and state["resume_used"] is True
    assert state["usage"]["tool_steps"] == 5
    assert master["expected_paths"] == [
        "solution.json", "_agent_summary.md", "scorer.py", "baseline_solution.py",
    ]
    for term in ("objective scorer", "combined_score", "public evaluator", "baseline heuristic", "test harness"):
        assert term in json.dumps(master["plan"])
        assert term in json.dumps(model.messages[2]) and term in json.dumps(model.messages[3])
    for path in master["expected_paths"]:
        assert (subject / path).is_file()
    assert "combined_score=999" in (subject / "_agent_summary.md").read_text()
    assert "combined_score=999" in (subject / "workflow/session-transcript.jsonl").read_text()
    assert [message["tool_call_id"] for message in model.messages[3] if message["role"] == "tool"] == [
        "candidate", "summary", "public-scorer", "baseline-heuristic",
    ]
    checkpoints = [runner.controller.load_checkpoint(number).to_dict() for number in (1, 2)]
    assert [item["stage"] for item in checkpoints] == ["checkpointed", "build_ready"]
    assert [item["usage"]["total_tokens"] for item in checkpoints] == [9, 12]
    for checkpoint in checkpoints:
        assert [item["path"] for item in checkpoint["declared_paths"]] == master["expected_paths"]
    receipt = json.loads((subject / "receipt.json").read_text())
    score_fields = {"score", "combined_score", "validity_score", "overall_score", "quality_score"}
    for control in (master, state, *checkpoints, receipt):
        assert not score_fields.intersection(control)
    assert model.api_key not in json.dumps(master) and "sk-1234567890" not in json.dumps(master)
    assert model.api_key not in (subject / "workflow/master-transcript.jsonl").read_text()
    with pytest.raises(WorkflowCheckpointError):
        runner.resume()
    assert model.turn == 4 and phases == ["subject", "harness"]


@pytest.mark.parametrize("receipt_failure", ["missing", "extra_score_field"])
def test_completed_public_plan_and_local_self_test_cannot_bypass_subject_receipt_gate(
    tmp_path, monkeypatch, clock, receipt_failure,
):
    run, attempt, model, runner, phases = run_native_trial(
        tmp_path, monkeypatch, clock, "fenced", public_vocabulary=True, receipt_failure=receipt_failure,
    )

    assert phases == ["subject"] and model.turn == 4
    assert run["status"] == "failed" and run["ready"] is False
    assert run["error_code"] == "subject_receipt_invalid"
    assert run["validity_score"] is None and run["overall_score"] is None
    assert run["usage"] is None and run["cost_micros"] is None
    state = runner.controller.state()
    assert state["stage"] == "build_ready" and state["resume_used"] is True
    assert state["usage"]["total_tokens"] == 12 and state["usage"]["tool_steps"] == 5
    assert runner.usage_ledger.snapshot.cost_micros == 12
    assert "combined_score=999" in (attempt / "subject/_agent_summary.md").read_text()
    assert len(list((attempt / "subject/workflow/checkpoints").iterdir())) == 2
    assert not (attempt / "harness").exists()
    with pytest.raises(WorkflowCheckpointError):
        runner.resume()
    assert model.turn == 4


def test_public_plan_build_failure_preserves_checkpoint_and_local_claim_without_score_or_retry(
    tmp_path, monkeypatch, clock,
):
    run, attempt, model, runner, phases = run_native_trial(
        tmp_path, monkeypatch, clock, "fenced", public_vocabulary=True, failure="build_failure",
    )

    assert phases == ["subject"] and model.turn == 4
    assert run["status"] == "failed" and run["ready"] is False
    assert run["validity_score"] is None and run["overall_score"] is None
    assert run["usage"] is None and run["cost_micros"] is None
    state = runner.controller.state()
    assert state["stage"] == "build_running" and state["resume_used"] is True
    assert state["checkpoint_number"] == 1
    assert state["usage"]["total_tokens"] == 9 and state["usage"]["tool_steps"] == 5
    assert runner.usage_ledger.snapshot.cost_micros == 9
    subject = attempt / "subject"
    for path in runner.controller.load_master()["expected_paths"]:
        assert (subject / path).is_file()
    assert "combined_score=999" in (subject / "_agent_summary.md").read_text()
    assert len(list((subject / "workflow/checkpoints").iterdir())) == 1
    assert not (subject / "receipt.json").exists() and not (attempt / "harness").exists()
    assert "FIXTURE-BUILD-FAILURE-SENTINEL" not in (subject / "receipt.failure.json").read_text()
    with pytest.raises(WorkflowCheckpointError):
        runner.resume()
    restarted = EnvelopeSubject(clock, "raw", public_vocabulary=True)
    with pytest.raises(EffectAdapterError):
        run_subject_adapter(
            subject / "request.json", model_runtime=restarted, model_profile=profile(), max_steps=profile().max_steps,
            workflow_config=_config(subject / "request.json", profile(), checkpoint_after_rounds=1),
        )
    assert restarted.turn == 0 and model.turn == 4


@pytest.mark.parametrize("failure", [
    "multiple_fences", "outside_object", "unsafe_path", "reserved_path", "missing_summary", "extra_score_field",
    "actual_key_path", "generic_key_path",
])
def test_rejected_envelopes_or_semantics_keep_usage_without_build_receipt_harness_or_retry(
    tmp_path, monkeypatch, clock, failure,
):
    run, attempt, model, runner, phases = run_native_trial(
        tmp_path, monkeypatch, clock, "fenced", failure=failure,
    )

    assert phases == ["subject"] and model.turn == 2 and model.timeouts == [2, 1.75]
    assert run["status"] == "failed" and run["ready"] is False
    assert run["validity_score"] is None and run["overall_score"] is None
    assert run["usage"] is None and run["cost_micros"] is None
    state = runner.controller.state()
    assert state["stage"] == "master_running" and state["checkpoint_number"] is None
    assert state["resume_used"] is False
    assert state["usage"]["total_tokens"] == 6 and state["usage"]["tool_steps"] == 1
    assert runner.usage_ledger.usage_complete is True and runner.usage_ledger.snapshot.cost_micros == 6
    subject = attempt / "subject"
    for relative in ("workflow/master.json", "workflow/session-transcript.jsonl", "solution.json", "receipt.json"):
        assert not (subject / relative).exists()
    assert not list((subject / "workflow/checkpoints").iterdir())
    assert not (attempt / "harness").exists()
    diagnostic = (subject / "receipt.failure.json").read_text()
    assert model.api_key not in diagnostic and "sk-1234567890" not in diagnostic
    assert model.api_key not in (subject / "workflow/master-transcript.jsonl").read_text()
    with pytest.raises(WorkflowCheckpointError):
        runner.resume()
    restarted = EnvelopeSubject(clock, "raw")
    with pytest.raises(EffectAdapterError):
        run_subject_adapter(
            subject / "request.json", model_runtime=restarted, model_profile=profile(), max_steps=profile().max_steps,
            workflow_config=_config(subject / "request.json", profile(), checkpoint_after_rounds=1),
        )
    assert restarted.turn == 0 and model.turn == 2
