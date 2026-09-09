import hashlib
import json
from pathlib import Path

import pytest

from famou.workflow_checkpoint import (
    AggregateUsage,
    WorkflowCheckpointError,
    WorkflowController,
    WorkflowManifest,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _manifest() -> WorkflowManifest:
    return WorkflowManifest(
        run_id="run-1", attempt_id="attempt-1", source_sha256=_digest("source"),
        suite_key="suite", case_key="case", request_sha256=_digest("request"),
        model_profile_sha256=_digest("profile"),
        ceilings={"max_wall_seconds": 100.0, "max_tool_steps": 10,
                   "max_total_tokens": 1_000, "max_cost_micros": 10_000},
    )


def _controller(tmp_path: Path) -> WorkflowController:
    controller = WorkflowController(tmp_path / "subject", _manifest())
    controller.write_master(["inspect public input", "save candidate early"], ["candidate.py"])
    controller.transition("build_running")
    (tmp_path / "subject" / "candidate.py").write_text("candidate", encoding="utf-8")
    return controller


def test_master_and_checkpoint_are_bound_and_resume_once(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    master = controller.load_master()
    assert master["kind"] == "workflow_master"
    checkpoint = controller.checkpoint(
        stage="checkpointed", declared_paths=["candidate.py"],
        usage=AggregateUsage(True, 10, 4, 14, 2, 1, 1),
    )
    assert controller.load_checkpoint(1).checkpoint_sha256 == checkpoint.checkpoint_sha256
    resumed = controller.resume()
    assert resumed.number == 1
    assert controller.state()["resume_used"] is True
    with pytest.raises(WorkflowCheckpointError, match="only once"):
        controller.resume()


def test_rejects_malformed_out_of_order_duplicate_and_cross_run(tmp_path: Path) -> None:
    controller = WorkflowController(tmp_path / "subject", _manifest())
    with pytest.raises(WorkflowCheckpointError, match="out-of-order"):
        controller.transition("build_running")
    controller.write_master(["plan"], [])
    controller.transition("build_running")
    (tmp_path / "subject" / "candidate.py").write_text("x", encoding="utf-8")
    controller.checkpoint(stage="checkpointed", declared_paths=["candidate.py"], usage=AggregateUsage.zero())
    duplicate = tmp_path / "subject" / "workflow" / "checkpoints" / "000001.json"
    with pytest.raises(WorkflowCheckpointError, match="already exists"):
        controller._write_new(duplicate, json.loads(duplicate.read_text()))
    raw = json.loads((tmp_path / "subject" / "workflow" / "checkpoints" / "000001.json").read_text())
    raw["run_id"] = "other"
    (tmp_path / "subject" / "workflow" / "checkpoints" / "000001.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(WorkflowCheckpointError, match="binding mismatch"):
        controller.load_checkpoint(1)


def test_rejects_symlink_over_budget_and_ledger_reset(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    outside = tmp_path / "outside"
    outside.write_text("secret", encoding="utf-8")
    (tmp_path / "subject" / "link").symlink_to(outside)
    with pytest.raises(WorkflowCheckpointError, match="symlink"):
        controller.checkpoint(stage="checkpointed", declared_paths=["link"], usage=AggregateUsage.zero())
    with pytest.raises(WorkflowCheckpointError, match="ceiling"):
        controller.checkpoint(stage="checkpointed", declared_paths=["candidate.py"], usage=AggregateUsage(True, 900, 200, 1100, 1, 1, 1))
    with pytest.raises(WorkflowCheckpointError, match="wall-time"):
        controller.checkpoint(stage="checkpointed", declared_paths=["candidate.py"], usage=AggregateUsage(True, 1, 1, 2, 0, 1, 1, 100_001))
    controller.checkpoint(stage="checkpointed", declared_paths=["candidate.py"], usage=AggregateUsage(True, 10, 1, 11, 0, 1, 1))
    with pytest.raises(WorkflowCheckpointError, match="backwards|reset"):
        controller.checkpoint(stage="checkpointed", declared_paths=["candidate.py"], usage=AggregateUsage(True, 0, 0, 0, 0, 0, 0))


def test_master_redacts_secret_and_rejects_score_evidence(tmp_path: Path) -> None:
    controller = WorkflowController(tmp_path / "subject", _manifest())
    with pytest.raises(WorkflowCheckpointError, match="forbidden"):
        controller.write_master(["use baseline overall score"], [])
    payload = controller.write_master(["use api_key=sk-1234567890 safely"], [])
    assert "sk-1234567890" not in json.dumps(payload)
    assert "[REDACTED]" in json.dumps(payload)


def test_cost_cannot_disappear_from_an_available_ledger() -> None:
    previous = AggregateUsage(True, 1, 1, 2, 5, 1, 1)
    current = AggregateUsage(True, 2, 2, 4, None, 2, 2)
    assert not current.monotonic_from(previous)


def test_harness_transition_is_owned_by_runner(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    with pytest.raises(WorkflowCheckpointError, match="EffectTrialRunner"):
        controller.transition("harness_pending")
