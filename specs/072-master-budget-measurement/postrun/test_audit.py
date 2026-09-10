"""Offline phase evidence and report boundaries; never run candidate code or providers."""
import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from famou.staged_workflow import StagedWorkflowConfig, StagePolicy
from famou.workflow_checkpoint import AggregateUsage, WorkflowController, WorkflowManifest


def load(name):
    spec = importlib.util.spec_from_file_location("test_postrun072_" + name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = load("audit")
report = load("render_report")


@pytest.fixture
def stage(tmp_path):
    _adapter, legacy = audit.dependencies()
    campaign = tmp_path / "campaign"
    slot = {"index": 1, "arm": "S", "budget_arm": "master_300", "case_key": "sheet_metal_nesting"}
    workspace = campaign / "slots/001/trial/cases/sheet_metal_nesting/runs/001/attempts/001/subject"
    manifest = WorkflowManifest(
        run_id="fixture-slot-001", attempt_id="slot-001-attempt-001", source_sha256="a" * 64,
        suite_key="famou-bench", case_key=slot["case_key"], request_sha256="b" * 64,
        model_profile_sha256="c" * 64,
        ceilings={"max_wall_seconds": 5400, "max_tool_steps": 200,
                  "max_total_tokens": 8_000_000, "max_cost_micros": None},
    )
    controller = WorkflowController(workspace, manifest)
    config = StagedWorkflowConfig(manifest, StagePolicy(300, 2400, 120, 32)).to_dict()
    slot["workflow_config"] = config
    (workspace / "workflow/config.json").write_text(json.dumps(config))
    controller.transition("master_running")
    return campaign, slot, controller, legacy, legacy.Evidence(tmp_path)


def inspect(stage):
    campaign, slot, _controller, legacy, evidence = stage
    return audit.stage_evidence(slot, campaign, legacy.Evidence(evidence.repo), legacy)


def test_master_timeout_evidence_does_not_invent_plan_build_or_elapsed(stage):
    result = inspect(stage)
    assert result["workflow_stage"] == "master_running"
    assert result["master_duration_seconds"] is None
    assert result["plan_record_valid"] is result["build_entered_observed"] is False


def test_valid_master_and_build_stage_are_distinct_and_reader_cannot_recover(stage, monkeypatch):
    controller = stage[2]
    controller.write_master(["Read public inputs and write a candidate"], ["solution.py", "_agent_summary.md"])
    result = inspect(stage)
    assert result["plan_record_valid"] is True and result["build_entered_observed"] is False
    controller.transition("build_running")
    workflow = controller.workspace / "workflow"
    (workflow / "session-transcript.jsonl").write_text('{"role":"user","content":"fixture"}\n')
    # An orphan/control artifact must not be repaired or removed by observation.
    (workflow / "orphan.tmp").write_text("preserve")
    before = {p: p.read_bytes() for p in controller.workspace.rglob("*") if p.is_file()}

    def refuse(*args, **kwargs):
        raise AssertionError("read-only audit constructed a mutating controller")

    monkeypatch.setattr(WorkflowController, "__init__", refuse)
    result = inspect(stage)
    assert result["build_entered_observed"] is result["build_transcript_present"] is True
    assert result["master_duration_seconds"] is None
    assert {p: p.read_bytes() for p in controller.workspace.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("change", ["digest", "identity", "unsafe_path", "missing_plan", "config", "linked_transcript"])
def test_phase_tampering_is_rejected(stage, change):
    controller = stage[2]
    controller.write_master(["Implement public constraints"], ["solution.py", "_agent_summary.md"])
    controller.transition("build_running")
    root = controller.workspace / "workflow"
    master = root / "master.json"
    if change == "missing_plan":
        master.unlink()
    elif change == "linked_transcript":
        (root / "session-transcript.jsonl").symlink_to(master)
    elif change == "config":
        value = json.loads((root / "config.json").read_text())
        value["policy"]["master_seconds"] = 1200
        (root / "config.json").write_text(json.dumps(value))
    else:
        value = json.loads(master.read_text())
        if change == "digest":
            value["plan_sha256"] = "d" * 64
        elif change == "identity":
            value["attempt_id"] = "slot-002-attempt-001"
        else:
            value["expected_paths"] = ["case/input.json", "_agent_summary.md"]
            value["plan_sha256"] = hashlib.sha256(stage[3].canonical(
                {k: v for k, v in value.items() if k != "plan_sha256"})).hexdigest()
        master.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        inspect(stage)


def test_empty_unstarted_stage_is_unobserved(tmp_path):
    _adapter, legacy = audit.dependencies()
    slot = {"index": 1, "budget_arm": "master_300", "case_key": "sheet_metal_nesting"}
    result = audit.stage_evidence(slot, tmp_path, legacy.Evidence(tmp_path), legacy)
    assert result["workflow_stage"] is None and result["resume_used"] is None
    assert result["master_duration_seconds"] is None and result["plan_record_valid"] is False
    with pytest.raises(ValueError, match="lacks workflow"):
        audit.stage_evidence(slot, tmp_path, legacy.Evidence(tmp_path), legacy, subject_accepted=True)


@pytest.mark.parametrize("resumed", [False, True])
def test_accepted_subject_requires_final_native_checkpoint(stage, resumed):
    campaign, slot, controller, legacy, evidence = stage
    workspace = controller.workspace
    controller.write_master(["Implement public constraints"], ["solution.py", "_agent_summary.md"])
    controller.transition("build_running")
    (workspace / "solution.py").write_text("candidate")
    (workspace / "_agent_summary.md").write_text("summary")
    (workspace / "workflow/session-transcript.jsonl").write_text("{}\n")
    first = workspace / "workflow/transcript-000001.jsonl"
    first.write_text("{}\n")
    paths = ["solution.py", "_agent_summary.md"]
    controller.checkpoint(stage="checkpointed" if resumed else "build_ready", declared_paths=paths,
                          usage=AggregateUsage(True, 10, 4, 14, None, 1, 1, 1000),
                          transcript=first.relative_to(workspace))
    number = 1
    if resumed:
        controller.resume(1)
        controller.transition("build_running")
        (workspace / "solution.py").write_text("improved candidate")
        second = workspace / "workflow/transcript-000002.jsonl"
        second.write_text("{}\n{}\n")
        (workspace / "workflow/session-transcript.jsonl").write_bytes(second.read_bytes())
        controller.checkpoint(stage="build_ready", declared_paths=paths,
                              usage=AggregateUsage(True, 20, 8, 28, None, 2, 2, 2000),
                              transcript=second.relative_to(workspace))
        number = 2
    result = audit.stage_evidence(slot, campaign, legacy.Evidence(evidence.repo), legacy, subject_accepted=True)
    assert result["plan_record_valid"] is result["build_entered_observed"] is True
    assert result["resume_used"] is resumed
    (workspace / f"workflow/checkpoints/{number:06d}.json").unlink()
    with pytest.raises(ValueError):
        audit.stage_evidence(slot, campaign, legacy.Evidence(evidence.repo), legacy, subject_accepted=True)


def report_fixture():
    rows, stages = [], []
    for index, (arm, case) in enumerate((
        ("master_300", "sheet_metal_nesting"), ("master_1200", "china_post_pickup_optimization"),
        ("master_1200", "sheet_metal_nesting"), ("master_300", "china_post_pickup_optimization"),
    ), 1):
        rows.append({"index": index, "budget_arm": arm, "case_key": case, "status": "not_started",
                     "process_terminated": False,
                     "harness_receipt_accepted": False, "extraction_status": None,
                     "validity_score": None, "overall_score": None, "quality_score": None})
        stages.append({"index": index, "budget_arm": arm, "master_duration_seconds": None,
                       "plan_record_valid": False, "build_entered_observed": False})
    return {"passed": True, "complete": False, "manifest_sha256": "a" * 64, "stages": stages,
            "summary": {"manifest_sha256": "a" * 64, "planned_attempts": 4,
                        "all_slots_terminated": False, "slots": rows,
                        "budget_arms": {key: {"planned": 2, "terminated": 0, "valid": 0}
                                        for key in ("master_300", "master_1200")}}}


def test_report_preserves_partial_null_and_above_one():
    fixture = report_fixture()
    text = report.render_report(fixture)
    assert "尚不能作最终比较" in text and "null" in text
    row = fixture["summary"]["slots"][1]
    row.update(status="completed", harness_receipt_accepted=True, extraction_status="completed",
               validity_score=1, overall_score=1.0185, quality_score=1.0185)
    with pytest.raises(ValueError):
        report.render_report(fixture)  # A row and its registered group must agree.
    fixture["summary"]["budget_arms"]["master_1200"]["valid"] = 1
    assert "1.0185" in report.render_report(fixture)
    row["harness_receipt_accepted"] = False
    with pytest.raises(ValueError):
        report.render_report(fixture)


@pytest.mark.parametrize("change", ["final", "duration", "group"])
def test_report_refuses_unsupported_final_duration_or_group(change):
    fixture = deepcopy(report_fixture())
    if change == "final":
        fixture["complete"] = True
    elif change == "duration":
        fixture["stages"][0]["master_duration_seconds"] = 301
    else:
        fixture["stages"][0]["budget_arm"] = "master_1200"
    with pytest.raises(ValueError):
        report.render_report(fixture)


@pytest.fixture
def top_level(tmp_path, monkeypatch):
    actual_adapter, legacy = audit.dependencies()
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    measurement = tmp_path / "measurement"
    measurement.mkdir()
    slots = [{"index": index, "arm": "S", "budget_arm": arm, "case_key": case}
             for index, (arm, case) in enumerate(actual_adapter.ORDER, 1)]
    manifest = {"slots": slots}
    digest = "d" * 64
    summary = {"manifest_sha256": digest, "planned_attempts": 4, "all_slots_terminated": False,
               "slots": [{**slot, "started": False, "process_terminated": False,
                          "report_sha256": None, "subject_receipt_accepted": False,
                          "harness_receipt_accepted": False} for slot in slots]}
    calls = []
    dispatcher = SimpleNamespace(REPO=tmp_path, CAMPAIGN=campaign, summarize=lambda: deepcopy(summary))
    worker = SimpleNamespace(verify_bindings=lambda *args, **kwargs: calls.append((args[4]["index"], kwargs)))
    checks = []
    preaudit = SimpleNamespace(
        check_schedule=lambda *args: checks.append("schedule"),
        check_frozen=lambda *args: checks.append("frozen"),
        check_history=lambda *args: checks.append("history"),
    )
    adapter = SimpleNamespace(REPO=tmp_path, CAMPAIGN=campaign, IMPLEMENTATION=actual_adapter.IMPLEMENTATION,
                              load_campaign=lambda: dispatcher, load_worker=lambda: worker,
                              load_current=lambda name: preaudit)
    monkeypatch.setattr(audit, "MEASUREMENT", measurement)
    monkeypatch.setattr(audit, "dependencies", lambda: (adapter, legacy))
    monkeypatch.setattr(legacy, "verify_registration", lambda *args: (
        manifest, digest, {"registration_commit": "c" * 40, "started_unix_seconds": 100.0}))
    monkeypatch.setattr(legacy, "verify_runtime_import", lambda repo: None)
    return SimpleNamespace(repo=tmp_path, campaign=campaign, measurement=measurement, manifest=manifest,
                           summary=summary, calls=calls, checks=checks, legacy=legacy, digest=digest)


def test_top_level_partial_keeps_all_four_checks_and_refuses_final(top_level):
    t = top_level
    result = audit.audit_registered_campaign(t.measurement / "manifest.json", t.campaign)
    assert result["passed"] is True and result["complete"] is False and result["final_acceptance"] is False
    assert t.calls == [(i, {"require_started": False}) for i in range(1, 5)]
    assert t.checks == ["schedule", "frozen", "history"]
    assert result["files_written"] == result["model_calls"] == 0 and len(result["stages"]) == 4
    with pytest.raises(ValueError, match="incomplete"):
        audit.audit_registered_campaign(t.measurement / "manifest.json", t.campaign, require_complete=True)


def test_top_level_accepted_subject_flag_reaches_stage_validator(top_level, monkeypatch):
    t = top_level
    t.summary["slots"][1]["subject_receipt_accepted"] = True
    monkeypatch.setattr(t.legacy, "verify_slot", lambda *args: ({"index": args[0]["index"]}, None, None))
    with pytest.raises(ValueError, match="accepted staged subject lacks workflow"):
        audit.audit_registered_campaign(t.measurement / "manifest.json", t.campaign)


def test_top_level_final_requires_full_matching_outer_evidence(top_level):
    t = top_level
    endings = []
    for index, start in enumerate((101.0, 101.1, 104.0, 104.1), 1):
        began = {"index": index, "manifest_sha256": t.digest, "started_unix_seconds": start}
        ended = {"index": index, "manifest_sha256": t.digest, "elapsed_seconds": 1.0,
                 "exit_code": None, "failure": "slot_timeout_or_launch_failure"}
        (t.campaign / f"slot-{index:03d}-started.json").write_bytes(t.legacy.canonical(began))
        (t.campaign / f"slot-{index:03d}-terminated.json").write_bytes(t.legacy.canonical(ended))
        t.summary["slots"][index - 1].update(started=True, process_terminated=True)
        endings.append(ended)
    t.summary["all_slots_terminated"] = True
    (t.campaign / "terminated.json").write_bytes(t.legacy.canonical({
        "manifest_sha256": t.digest, "terminated_unix_seconds": 106.0, "slots": endings}))
    (t.campaign / "summary.json").write_bytes(t.legacy.canonical(t.summary))
    result = audit.audit_registered_campaign(t.measurement / "manifest.json", t.campaign, require_complete=True)
    assert result["complete"] is True and result["final_acceptance"] is True
    (t.campaign / "slot-004-terminated.json").unlink()
    with pytest.raises(ValueError):
        audit.audit_registered_campaign(t.measurement / "manifest.json", t.campaign, require_complete=True)
