import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

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


def test_unavailable_usage_cannot_authorize_resume(tmp_path: Path) -> None:
    """A candidate checkpoint without provider usage is diagnostic evidence only."""
    controller = _controller(tmp_path)
    controller.checkpoint(
        stage="checkpointed", declared_paths=["candidate.py"],
        usage=AggregateUsage.unavailable(rounds=1, tool_steps=1),
    )
    with pytest.raises(WorkflowCheckpointError, match="unavailable usage"):
        controller.resume()
    state = controller.state()
    assert state["stage"] == "checkpointed"
    assert state["resume_used"] is False


def test_unavailable_observed_usage_cannot_be_replaced_by_later_sample(tmp_path: Path) -> None:
    """Later provider counters do not account for an earlier unobserved round."""
    controller = _controller(tmp_path)
    controller.checkpoint(
        stage="checkpointed", declared_paths=["candidate.py"],
        usage=AggregateUsage.unavailable(rounds=1, tool_steps=1),
    )
    observed = AggregateUsage(True, 3, 2, 5, 0, 2, 2)
    with pytest.raises(WorkflowCheckpointError, match="backwards|reset"):
        controller.checkpoint(stage="checkpointed", declared_paths=["candidate.py"], usage=observed)
    assert not AggregateUsage.from_dict(controller.state()["usage"]).available


def _rewrite_checkpoint(path: Path, **changes: object) -> None:
    payload = json.loads(path.read_text())
    payload.update(changes)
    body = {key: value for key, value in payload.items() if key != "checkpoint_sha256"}
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    payload["checkpoint_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_historical_checkpoint_load_does_not_require_latest_usage(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    first = controller.checkpoint(
        stage="checkpointed", declared_paths=["candidate.py"],
        usage=AggregateUsage(True, 10, 1, 11, 1, 1, 1, 100),
    )
    second = controller.checkpoint(
        stage="checkpointed", declared_paths=["candidate.py"],
        usage=AggregateUsage(True, 20, 2, 22, 2, 2, 2, 200),
    )
    assert controller.load_checkpoint(1) == first
    assert controller.load_checkpoint(2) == second
    with pytest.raises(WorkflowCheckpointError, match="does not match current state"):
        controller.resume(1)
    assert controller.resume(2) == second


@pytest.mark.parametrize("tokens", [9, 11])
def test_resume_rejects_state_checkpoint_usage_mismatch(tmp_path: Path, tokens: int) -> None:
    controller = _controller(tmp_path)
    controller.checkpoint(
        stage="checkpointed", declared_paths=["candidate.py"],
        usage=AggregateUsage(True, 10, 1, 11, 1, 1, 1),
    )
    state_path = controller.workflow / "state.json"
    state = json.loads(state_path.read_text())
    state["usage"] = AggregateUsage(True, tokens, 1, tokens + 1, 1, 1, 1).to_dict()
    state_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(WorkflowCheckpointError, match="does not match current state"):
        controller.resume()
    assert controller.state()["resume_used"] is False


def test_resume_rejects_checkpoint_stage_mismatch_and_master_tampering(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    controller.checkpoint(stage="checkpointed", declared_paths=[], usage=AggregateUsage.zero())
    checkpoint_path = controller.checkpoints / "000001.json"
    _rewrite_checkpoint(checkpoint_path, stage="build_ready")
    with pytest.raises(WorkflowCheckpointError, match="does not match current state"):
        controller.resume()
    _rewrite_checkpoint(checkpoint_path, stage="checkpointed")
    master_path = controller.workflow / "master.json"
    master = json.loads(master_path.read_text())
    master["plan"] = ["changed plan"]
    master_path.write_text(json.dumps(master), encoding="utf-8")
    with pytest.raises(WorkflowCheckpointError, match="master plan digest mismatch"):
        controller.resume()


def test_transitions_cannot_bypass_or_repeat_resume_guard(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    with pytest.raises(WorkflowCheckpointError, match="duplicate"):
        controller.transition("build_running")
    with pytest.raises(WorkflowCheckpointError, match="durable checkpoint"):
        controller.transition("checkpointed")
    assert controller.state()["stage"] == "build_running"
    controller.checkpoint(stage="checkpointed", declared_paths=[], usage=AggregateUsage.zero())
    with pytest.raises(WorkflowCheckpointError, match="resume.*guard"):
        controller.transition("resuming")
    assert controller.state()["resume_used"] is False
    controller.resume()
    with pytest.raises(WorkflowCheckpointError, match="resume.*guard"):
        controller.transition("resuming")
    controller.transition("build_running")
    controller.checkpoint(stage="checkpointed", declared_paths=[], usage=AggregateUsage.zero())
    reopened = WorkflowController(controller.workspace, _manifest())
    with pytest.raises(WorkflowCheckpointError, match="only once"):
        reopened.resume()


@pytest.mark.parametrize(
    ("usage", "ceiling"),
    [
        (AggregateUsage(True, 999, 1, 1000, 1, 1, 1), "token"),
        (AggregateUsage(True, 1, 1, 2, 1, 1, 10), "tool-step"),
        (AggregateUsage(True, 1, 1, 2, 1, 1, 1, 100_000), "wall-time"),
        (AggregateUsage(True, 1, 1, 2, 10_000, 1, 1), "cost"),
        (AggregateUsage(True, 1, 1, 2, None, 1, 1), "cost"),
    ],
)
def test_resume_requires_known_headroom(tmp_path: Path, usage: AggregateUsage, ceiling: str) -> None:
    controller = _controller(tmp_path)
    controller.checkpoint(stage="checkpointed", declared_paths=[], usage=usage)
    with pytest.raises(WorkflowCheckpointError, match=f"headroom.*{ceiling} ceiling"):
        controller.resume()
    assert controller.state()["resume_used"] is False


def test_usage_cannot_discard_known_tokens_or_cost() -> None:
    previous = AggregateUsage(True, 1, 1, 2, 5, 1, 1)
    assert not AggregateUsage.unavailable(rounds=2, tool_steps=2).monotonic_from(previous)
    assert not AggregateUsage(True, 2, 2, 4, 4, 2, 2).monotonic_from(previous)
    assert not AggregateUsage(True, 0, 3, 3, 5, 2, 2).monotonic_from(previous)
    assert AggregateUsage(True, 2, 2, 4, 5, 2, 2).monotonic_from(previous)
    assert previous.monotonic_from(AggregateUsage.unavailable())
    assert not previous.monotonic_from(AggregateUsage.unavailable(elapsed_ms=1))


def test_manifest_ceilings_are_detached_and_immutable() -> None:
    payload = _manifest().to_dict()
    manifest = WorkflowManifest.from_dict(payload)
    payload["ceilings"]["max_total_tokens"] = 2000
    assert manifest.ceilings["max_total_tokens"] == 1000
    with pytest.raises(TypeError):
        manifest.ceilings["max_total_tokens"] = 2000
    projected = manifest.to_dict()
    projected["ceilings"]["max_total_tokens"] = 3000
    assert manifest.ceilings["max_total_tokens"] == 1000


@pytest.mark.parametrize("path", [".", "./candidate.py", "dir//candidate.py", "candidate.py/", "../candidate.py", "dir/../candidate.py"])
def test_paths_must_be_canonical_and_confined(tmp_path: Path, path: str) -> None:
    controller = _controller(tmp_path)
    with pytest.raises(WorkflowCheckpointError, match="confined POSIX"):
        controller.checkpoint(stage="checkpointed", declared_paths=[path], usage=AggregateUsage.zero())


def test_transcript_accepts_relative_path_object_and_rejects_escape(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    transcript_path = controller.workspace / "transcript.json"
    transcript_path.write_text("{}", encoding="utf-8")
    checkpoint = controller.checkpoint(
        stage="checkpointed", declared_paths=[], usage=AggregateUsage.zero(),
        transcript=Path("transcript.json"),
    )
    assert checkpoint.transcript["path"] == "transcript.json"
    assert controller.load_checkpoint(1) == checkpoint
    with pytest.raises(WorkflowCheckpointError, match="confined POSIX"):
        controller.checkpoint(
            stage="checkpointed", declared_paths=[], usage=AggregateUsage.zero(),
            transcript=transcript_path,
        )
    (controller.workspace / "linked").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(WorkflowCheckpointError, match="symlink"):
        controller.checkpoint(
            stage="checkpointed", declared_paths=[], usage=AggregateUsage.zero(),
            transcript=Path("linked/other.json"),
        )


@pytest.mark.parametrize("tamper_usage", [False, True])
def test_interrupted_state_write_recovers_only_monotonic_orphan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper_usage: bool,
) -> None:
    controller = _controller(tmp_path)
    previous = AggregateUsage(True, 10, 1, 11, 1, 1, 1, 100)
    controller.checkpoint(stage="checkpointed", declared_paths=["candidate.py"], usage=previous)
    current = AggregateUsage(True, 20, 2, 22, 2, 2, 2, 200)

    def fail_state_write(*args: object, **kwargs: object) -> None:
        raise OSError("simulated interrupted state replacement")

    monkeypatch.setattr(controller, "_write_replace", fail_state_write)
    with pytest.raises(OSError, match="interrupted"):
        controller.checkpoint(stage="checkpointed", declared_paths=["candidate.py"], usage=current)
    assert controller.state()["checkpoint_number"] == 1
    assert (controller.checkpoints / "000002.json").is_file()
    if tamper_usage:
        _rewrite_checkpoint(controller.checkpoints / "000002.json", usage=AggregateUsage.zero().to_dict())
        with pytest.raises(WorkflowCheckpointError, match="orphan checkpoint usage.*backwards"):
            WorkflowController(controller.workspace, _manifest())
    else:
        recovered = WorkflowController(controller.workspace, _manifest())
        assert recovered.state()["checkpoint_number"] == 2
        assert AggregateUsage.from_dict(recovered.state()["usage"]) == current
        assert recovered.load_checkpoint(1).usage == previous
        assert recovered.resume().number == 2


def test_master_usage_survives_rejected_plan_and_enforces_budget(tmp_path: Path) -> None:
    controller = WorkflowController(tmp_path / "subject", _manifest())
    usage = AggregateUsage(True, 10, 2, 12, 2, 1, 0, 100)
    with pytest.raises(WorkflowCheckpointError, match="master stage"):
        controller.record_usage(usage)
    controller.transition("master_running")
    controller.record_usage(usage.to_dict())
    with pytest.raises(WorkflowCheckpointError, match="forbidden"):
        controller.write_master(["use private score"], [])
    assert AggregateUsage.from_dict(controller.state()["usage"]) == usage
    with pytest.raises(WorkflowCheckpointError, match="backwards|reset"):
        controller.record_usage(AggregateUsage.zero())
    with pytest.raises(WorkflowCheckpointError, match="token ceiling"):
        controller.record_usage(AggregateUsage(True, 1000, 10, 1010, 10, 2, 0, 200))
    controller.write_master(["inspect public input"], [])
    controller.record_usage(AggregateUsage(True, 20, 4, 24, 4, 2, 0, 200))
    controller.transition("build_running")
    with pytest.raises(WorkflowCheckpointError, match="master stage"):
        controller.record_usage(usage)


def test_tampered_state_cannot_exceed_ceilings_or_create_unused_resume(tmp_path: Path) -> None:
    controller = _controller(tmp_path)
    controller.checkpoint(stage="checkpointed", declared_paths=[], usage=AggregateUsage.zero())
    state_path = controller.workflow / "state.json"
    original = json.loads(state_path.read_text())
    state = dict(original)
    state["usage"] = AggregateUsage(True, 1000, 1, 1001, 1, 1, 1).to_dict()
    state_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(WorkflowCheckpointError, match="token ceiling"):
        controller.resume()
    state = dict(original)
    state["stage"] = "resuming"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(WorkflowCheckpointError, match="consumed resume guard"):
        controller.transition("build_running")


@pytest.mark.parametrize("directory", ["workspace", "workflow", "checkpoints"])
def test_replaced_control_directory_blocks_subsequent_reads_and_writes(
    tmp_path: Path, directory: str,
) -> None:
    controller = _controller(tmp_path)
    control_path = getattr(controller, directory)
    outside = tmp_path / "outside"
    control_path.rename(outside)
    control_path.symlink_to(outside, target_is_directory=True)
    original = {path.relative_to(outside): path.read_bytes() for path in outside.rglob("*") if path.is_file()}
    with pytest.raises(WorkflowCheckpointError, match="symlinks"):
        controller.assert_paths_safe()
    with pytest.raises(WorkflowCheckpointError, match="symlinks"):
        controller._read_json(controller.workflow / "master.json")
    with pytest.raises(WorkflowCheckpointError, match="symlinks"):
        controller._write_replace(controller.workflow / "state.json", {"replaced": True})
    with pytest.raises(WorkflowCheckpointError, match="symlinks"):
        controller._write_new(controller.checkpoints / "000001.json", {"new": True})
    assert {path.relative_to(outside): path.read_bytes() for path in outside.rglob("*") if path.is_file()} == original


@pytest.mark.parametrize("operation", ["_read_json", "_write_replace", "_write_new"])
@pytest.mark.parametrize("escape", ["symlink_parent", "outside", "parent_traversal"])
def test_record_helpers_reject_unsafe_destination_parents(
    tmp_path: Path, operation: str, escape: str,
) -> None:
    controller = _controller(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    existing = outside / "record.json"
    existing.write_text('{"original": true}', encoding="utf-8")
    if escape == "symlink_parent":
        (controller.workflow / "nested").symlink_to(outside, target_is_directory=True)
        destination = controller.workflow / "nested" / "record.json"
    elif escape == "outside":
        destination = existing
    else:
        destination = controller.workspace / ".." / "outside" / "record.json"
    arguments = (destination,) if operation == "_read_json" else (destination, {"changed": True})
    with pytest.raises(WorkflowCheckpointError, match="symlinks|escapes workspace|confined"):
        getattr(controller, operation)(*arguments)
    assert existing.read_text() == '{"original": true}'
    assert tuple(outside.iterdir()) == (existing,)


@pytest.mark.parametrize("operation", ["_write_replace", "_write_new"])
def test_preexisting_temporary_symlink_is_not_followed_or_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    controller = _controller(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_text("original", encoding="utf-8")
    destination = controller.workflow / "new.json"
    temporary = destination.with_name(".new.json.collision.tmp")
    temporary.symlink_to(outside)
    monkeypatch.setattr("famou.workflow_checkpoint.uuid.uuid4", lambda: SimpleNamespace(hex="collision"))
    with pytest.raises((OSError, WorkflowCheckpointError)):
        getattr(controller, operation)(destination, {"changed": True})
    assert outside.read_text() == "original"
    assert temporary.is_symlink()
    assert not destination.exists()
