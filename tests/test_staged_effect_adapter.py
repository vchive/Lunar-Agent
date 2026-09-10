"""Offline staged-subject integration across the unchanged effect receipt gate."""

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from test_effect_adapters import SubjectModel, _subject_request
from test_effect_trial import _fixture

from famou.effect_adapters import EffectAdapterError, run_subject_adapter
from famou.effect_trial import EffectTrialConfig, EffectTrialRunner
from famou.profiles import ModelProfile
from famou.runtime import ModelTurn, RuntimeExecutionError, ToolCall
from famou.staged_workflow import StagedWorkflowConfig, StagePolicy
from famou.workflow_checkpoint import WorkflowManifest


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _profile() -> ModelProfile:
    return ModelProfile(
        "staged-fixture", "gpt-5.6-sol", timeout_seconds=10, max_steps=8,
        max_total_tokens=100, input_cost_per_1k_micros=1000,
        output_cost_per_1k_micros=1000,
    )


def _profile_sha(profile: ModelProfile) -> str:
    return _sha(json.dumps(
        profile.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode())


def _config(
    request: Path, profile: ModelProfile, *, checkpoint_after_rounds: int | None = 1,
) -> StagedWorkflowConfig:
    payload = json.loads(request.read_text())
    return StagedWorkflowConfig(
        manifest=WorkflowManifest(
            run_id="offline-staged-comparison", attempt_id="attempt-001",
            source_sha256=_sha(b"offline-source-fixture"),
            suite_key=payload["benchmark"]["name"], case_key=payload["case"]["key"],
            request_sha256=_sha(request.read_bytes()), model_profile_sha256=_profile_sha(profile),
            ceilings={
                "max_wall_seconds": 10.0, "max_tool_steps": 8,
                "max_total_tokens": 100, "max_cost_micros": None,
            },
        ),
        policy=StagePolicy(
            master_seconds=2, build_seconds=5, reserve_seconds=1,
            checkpoint_after_rounds=checkpoint_after_rounds,
        ),
    )


def _request(root: Path, profile: ModelProfile) -> Path:
    request = _subject_request(root)
    payload = json.loads(request.read_text())
    payload["model_profile_sha256"] = _profile_sha(profile)
    request.write_text(json.dumps(payload))
    return request


class StagedSubject(SubjectModel):
    """The only generated answer is the existing public fixture's requested value."""

    def __init__(self, *, failure: str | None = None) -> None:
        super().__init__()
        self.failure = failure
        self.messages: list[list[dict]] = []

    def complete(self, messages, tools=(), timeout=None):
        del tools, timeout
        self.messages.append(json.loads(json.dumps(messages)))
        self.turn += 1
        if self.turn == 1:
            return ModelTurn(
                json.dumps({
                    "plan": ["MODEL_PLAN_SENTINEL: preserve the requested candidate early"],
                    "expected_paths": ["solution.json", "_agent_summary.md"],
                }),
                response_model="openai/gpt-5.6-sol",
                usage={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
            )
        if self.turn == 2:
            calls = [
                ToolCall("candidate", "write_file", {
                    "path": "solution.json", "content": '{"answer":42}',
                }),
                ToolCall("summary", "write_file", {
                    "path": "_agent_summary.md", "content": "Final: solution.json",
                }),
            ]
            if self.failure == "public_mutation":
                calls.append(ToolCall("mutate", "write_file", {
                    "path": "case/data/instance.json", "content": '{"changed":true}',
                }))
            return ModelTurn(
                "", tuple(calls), response_model="openai/gpt-5.6-sol",
                usage={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
            )
        if self.failure == "provider":
            raise RuntimeExecutionError("SECRET-PROVIDER-ERROR-SENTINEL")
        usage = {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}
        if self.failure == "missing_usage":
            usage = None
        elif self.failure == "budget":
            usage = {"input_tokens": 100, "output_tokens": 1, "total_tokens": 101}
        return ModelTurn(
            "The requested candidate is ready.", response_model="openai/gpt-5.6-sol",
            usage=usage,
        )


@pytest.mark.parametrize("checkpoint_after_rounds", [None, 1])
def test_staged_adapter_aggregates_master_build_and_optional_resume(
    tmp_path: Path, checkpoint_after_rounds: int | None,
) -> None:
    profile = _profile()
    request = _request(tmp_path / "subject", profile)
    model = StagedSubject()
    config = _config(request, profile, checkpoint_after_rounds=checkpoint_after_rounds)

    receipt = run_subject_adapter(
        request, model_runtime=model, model_profile=profile, max_steps=8,
        workflow_config=config,
    )

    assert model.turn == 3
    assert "MODEL_PLAN_SENTINEL" in json.dumps(model.messages[1])
    assert receipt["interaction_turns"] == 3
    assert receipt["usage"] == {"input_tokens": 6, "output_tokens": 3, "total_tokens": 9}
    assert receipt["cost_micros"] == 9
    assert receipt["effective_model"] == "openai/gpt-5.6-sol"
    assert receipt["model_profile_sha256"] == _profile_sha(profile)
    assert json.loads((request.parent / "receipt.json").read_text()) == receipt
    assert "score" not in receipt and "workflow" not in receipt
    state = json.loads((request.parent / "workflow/state.json").read_text())
    assert state["stage"] == "build_ready"
    assert state["resume_used"] is (checkpoint_after_rounds is not None)
    assert state["usage"]["total_tokens"] == 9
    assert state["usage"]["tool_steps"] == 2
    master = json.loads((request.parent / "workflow/master.json").read_text())
    assert master["plan"] == ["MODEL_PLAN_SENTINEL: preserve the requested candidate early"]
    assert master["request_sha256"] == _sha(request.read_bytes())


@pytest.mark.parametrize("failure", ["provider", "missing_usage", "budget", "public_mutation"])
def test_staged_failure_preserves_candidate_without_implicit_retry_or_receipt(
    tmp_path: Path, failure: str,
) -> None:
    profile = _profile()
    request = _request(tmp_path / "subject", profile)
    model = StagedSubject(failure=failure)
    config = _config(request, profile, checkpoint_after_rounds=None)

    with pytest.raises(EffectAdapterError):
        run_subject_adapter(
            request, model_runtime=model, model_profile=profile, max_steps=8,
            workflow_config=config,
        )

    assert model.turn == 3
    assert json.loads((request.parent / "solution.json").read_text()) == {"answer": 42}
    assert not (request.parent / "receipt.json").exists()
    assert not (request.parent / "harness").exists()
    diagnostic = (request.parent / "receipt.failure.json").read_text()
    assert "SECRET-PROVIDER-ERROR-SENTINEL" not in diagnostic
    state = json.loads((request.parent / "workflow/state.json").read_text())
    assert state["resume_used"] is False
    restarted_model = StagedSubject()
    with pytest.raises(EffectAdapterError):
        run_subject_adapter(
            request, model_runtime=restarted_model, model_profile=profile, max_steps=8,
            workflow_config=config,
        )
    assert restarted_model.turn == 0


@pytest.mark.parametrize("binding", ["request", "case", "suite", "profile", "ceilings"])
def test_staged_config_mismatch_fails_before_first_model_request(
    tmp_path: Path, binding: str,
) -> None:
    profile = _profile()
    request = _request(tmp_path / "subject", profile)
    model = StagedSubject()
    config = _config(request, profile)
    changes = {
        "request": {"request_sha256": "0" * 64},
        "case": {"case_key": "another-case"},
        "suite": {"suite_key": "another-benchmark"},
        "profile": {"model_profile_sha256": "0" * 64},
        "ceilings": {"ceilings": {**config.manifest.ceilings, "max_tool_steps": 9}},
    }
    config = replace(config, manifest=replace(config.manifest, **changes[binding]))

    with pytest.raises((EffectAdapterError, ValueError)):
        run_subject_adapter(
            request, model_runtime=model, model_profile=profile, max_steps=8,
            workflow_config=config,
        )

    assert model.turn == 0
    assert not (request.parent / "receipt.json").exists()


@pytest.mark.parametrize("reserved_path", [
    "./workflow/config.json", "./case/data/instance.json", "./request.json", "./receipt.json",
])
def test_master_cannot_disguise_reserved_paths_with_dot_prefix(
    tmp_path: Path, reserved_path: str,
) -> None:
    profile = _profile()
    request = _request(tmp_path / "subject", profile)

    class ReservedMaster(StagedSubject):
        def complete(self, messages, tools=(), timeout=None):
            turn = super().complete(messages, tools, timeout)
            if self.turn == 1:
                payload = json.loads(turn.text)
                payload["expected_paths"].append(reserved_path)
                return replace(turn, text=json.dumps(payload))
            return turn

    model = ReservedMaster()
    with pytest.raises(EffectAdapterError):
        run_subject_adapter(
            request, model_runtime=model, model_profile=profile, max_steps=8,
            workflow_config=_config(request, profile),
        )

    assert model.turn == 1
    assert not (request.parent / "receipt.json").exists()
    assert not (request.parent / "solution.json").exists()


def test_master_must_declare_the_delivery_summary(tmp_path: Path) -> None:
    profile = _profile()
    request = _request(tmp_path / "subject", profile)

    class MissingSummaryMaster(StagedSubject):
        def complete(self, messages, tools=(), timeout=None):
            turn = super().complete(messages, tools, timeout)
            if self.turn == 1:
                payload = json.loads(turn.text)
                payload["expected_paths"] = ["solution.json"]
                return replace(turn, text=json.dumps(payload))
            return turn

    model = MissingSummaryMaster()
    with pytest.raises(EffectAdapterError):
        run_subject_adapter(
            request, model_runtime=model, model_profile=profile, max_steps=8,
            workflow_config=_config(request, profile),
        )

    assert model.turn == 1
    assert not (request.parent / "receipt.json").exists()


def test_staged_transcript_rejects_workflow_directory_replacement(tmp_path: Path) -> None:
    profile = _profile()
    request = _request(tmp_path / "subject", profile)
    escaped = tmp_path / "escaped-workflow"
    initial_history: list[bytes] = []

    class ReplacingSubject(StagedSubject):
        def complete(self, messages, tools=(), timeout=None):
            turn = super().complete(messages, tools, timeout)
            if self.turn == 2:
                workflow = request.parent / "workflow"
                initial_history.append((workflow / "session-transcript.jsonl").read_bytes())
                workflow.rename(escaped)
                workflow.symlink_to(escaped, target_is_directory=True)
            return turn

    model = ReplacingSubject()
    with pytest.raises(EffectAdapterError):
        run_subject_adapter(
            request, model_runtime=model, model_profile=profile, max_steps=8,
            workflow_config=_config(request, profile),
        )

    assert model.turn == 2
    assert (escaped / "session-transcript.jsonl").read_bytes() == initial_history[0]
    assert not list(escaped.glob("transcript-*.jsonl"))
    assert not (request.parent / "receipt.json").exists()


@pytest.mark.parametrize("failure", [None, "provider"])
def test_effect_trial_accepts_only_completed_staged_receipt_and_calls_harness_once(
    tmp_path: Path, failure: str | None,
) -> None:
    suite, baseline, public, subject_command, harness_command = _fixture(tmp_path)
    profile = _profile()
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile.to_dict()))
    model = StagedSubject(failure=failure)
    invocations: list[str] = []

    def executor(command, *, cwd, env, timeout):
        del env, timeout
        request = Path(command[-1])
        if cwd.name == "subject":
            invocations.append("subject")
            try:
                run_subject_adapter(
                    request, model_runtime=model, model_profile=profile, max_steps=8,
                    workflow_config=_config(
                        request, profile,
                        checkpoint_after_rounds=1 if failure is None else None,
                    ),
                )
            except EffectAdapterError:
                return subprocess.CompletedProcess(command, 2)
        else:
            invocations.append("harness")
            assert (cwd.parent / "subject/receipt.json").is_file()
            payload = json.loads(request.read_text())
            (cwd / "receipt.json").write_text(json.dumps({
                "schema_version": "1", "status": "completed",
                "benchmark": payload["benchmark"],
                "evaluation_profile": payload["evaluation_profile"],
                "case": payload["case"], "harness": payload["harness"],
                "extraction_status": "completed", "validity_score": 1.0,
                "overall_score": 0.81, "quality_score": 0.81, "detail_metrics": {},
            }))
        return subprocess.CompletedProcess(command, 0)

    trial = tmp_path / "trial-staged"
    report = EffectTrialRunner(
        suite, baseline, trial, case_sources={"fixture_case": public},
        config=EffectTrialConfig(
            runs_per_case=1, timeout_seconds=10, requested_model=profile.model,
            subject_model_profile_path=profile_path,
            subject_command=subject_command, harness_command=harness_command,
        ),
        process_executor=executor,
    ).run().to_dict()

    runs = report["cases"][0]["runs"]
    assert len(runs) == 1
    run = runs[0]
    attempt = trial / run["attempt"]
    assert model.turn == 3
    assert (attempt / "subject/solution.json").is_file()
    if failure is None:
        assert invocations == ["subject", "harness"]
        assert run["status"] == "completed" and run["ready"] is True
        assert run["interaction_turns"] == 3
        assert run["usage"]["total_tokens"] == 9
        assert run["cost_micros"] == 9
        assert run["validity_score"] == 1.0 and run["overall_score"] == 0.81
    else:
        assert invocations == ["subject"]
        assert run["status"] == "failed" and run["ready"] is False
        assert not (attempt / "subject/receipt.json").exists()
        assert not (attempt / "harness").exists()
        assert run["overall_score"] is None and run["validity_score"] is None
        assert report["cases"][0]["lunar_best"] is None
