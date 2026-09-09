from pathlib import Path

import pytest

from famou.model_profile import UsageLedger
from famou.profiles import ModelProfile
from famou.runtime import RuntimeExecutionError, RuntimeResult
from famou.staged_workflow import StagedWorkflowRunner
from famou.workflow_checkpoint import WorkflowCheckpointError, WorkflowController, WorkflowManifest


def _digest(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()


def _manifest() -> WorkflowManifest:
    return WorkflowManifest(
        run_id="run-1", attempt_id="attempt-1", source_sha256=_digest("source"),
        suite_key="suite", case_key="case", request_sha256=_digest("request"),
        model_profile_sha256=_digest("profile"),
        ceilings={"max_wall_seconds": 30.0, "max_tool_steps": 10,
                   "max_total_tokens": 100, "max_cost_micros": 1000},
    )


class FakeAgent:
    last_tool_steps = 0

    def __init__(self, fail_build: bool = False) -> None:
        self.fail_build = fail_build
        self.calls: list[str] = []

    def run(self, prompt, workspace: Path, timeout=None, *, usage_ledger=None, tool_steps_offset=0):
        del timeout
        self.calls.append(prompt)
        self.last_tool_steps = tool_steps_offset + 1
        if usage_ledger is not None:
            usage_ledger.record({"input_tokens": 2, "output_tokens": 1, "total_tokens": 3})
        if prompt == "build" and self.fail_build:
            (workspace / "candidate.py").write_text("candidate", encoding="utf-8")
            raise RuntimeExecutionError("stage timeout")
        return RuntimeResult("done")


def _runner(tmp_path: Path, *, fail_build: bool) -> tuple[StagedWorkflowRunner, FakeAgent, UsageLedger]:
    profile = ModelProfile("fixture", "fixture", max_total_tokens=100)
    ledger = UsageLedger(profile)
    controller = WorkflowController(tmp_path / "subject", _manifest())
    agent = FakeAgent(fail_build=fail_build)
    runner = StagedWorkflowRunner(controller, agent, tmp_path / "subject", usage_ledger=ledger)
    return runner, agent, ledger


def test_timeout_preserves_candidate_and_resume_uses_same_ledger(tmp_path: Path) -> None:
    runner, agent, ledger = _runner(tmp_path, fail_build=True)
    result = runner.run(
        master_prompt="master", plan=["save candidate"], expected_paths=["candidate.py"],
        build_prompt="build", declared_paths=["candidate.py"],
    )
    assert result.status == "checkpointed"
    assert (tmp_path / "subject" / "candidate.py").is_file()
    assert ledger.snapshot.total_tokens == 6
    assert runner.controller.state()["stage"] == "checkpointed"

    agent.fail_build = False
    resumed = runner.resume(prompt="resume", declared_paths=["candidate.py"])
    assert resumed.status == "build_ready"
    assert ledger.snapshot.total_tokens == 9
    assert runner.controller.state()["stage"] == "build_ready"
    with pytest.raises(WorkflowCheckpointError):
        runner.resume(prompt="resume again", declared_paths=["candidate.py"])


def test_successful_staged_run_does_not_authorize_harness(tmp_path: Path) -> None:
    runner, _agent, _ledger = _runner(tmp_path, fail_build=False)
    result = runner.run(
        master_prompt="master", plan=["save candidate"], expected_paths=[],
        build_prompt="build",
    )
    assert result.status == "build_ready"
    assert runner.controller.state()["stage"] == "build_ready"
    with pytest.raises(WorkflowCheckpointError, match="EffectTrialRunner"):
        runner.controller.transition("harness_pending")
