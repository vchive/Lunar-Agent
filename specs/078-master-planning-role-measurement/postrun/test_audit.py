"""Rebind the pinned two-slot fixtures; add only Feature 078 wrapper-specific regressions."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from famou.staged_workflow import StagedWorkflowConfig, StagePolicy
from famou.workflow_checkpoint import AggregateUsage, WorkflowController, WorkflowManifest


def load(name):
    path = Path(__file__).with_name(name + ".py")
    spec = importlib.util.spec_from_file_location("test_postrun078_" + name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit, report = load("audit"), load("render_report")
adapter, _legacy = audit.dependencies()
prior_tests = adapter.load_previous_postrun("test_audit")
prior_tests.audit, prior_tests.report = audit, report
_prior_report_fixture = prior_tests.report_fixture


def report_fixture():
    fixture = _prior_report_fixture()
    fixture.update(kind="feature078_postrun_audit", implementation_commit=adapter.IMPLEMENTATION)
    return fixture


prior_tests.report_fixture = report_fixture
# Exercise the original parameterized registration, frozen-byte/runtime, native-stage, fixed-two-slot,
# completion, extra-attempt and null/>1 report gates against these wrappers, without copying tests.
globals().update({name: value for name, value in vars(prior_tests).items()
                  if name.startswith("test_") or name in {"top_level", "registration"}})


def test_current_campaign_source_and_analysis_identity_are_bound(top_level):
    result = prior_tests.inspect(top_level)
    assert result["kind"] == "feature078_postrun_audit"
    assert result["implementation_commit"] == "fba6ab8cf5b27d3bd1b42f353907a6ae21c25ef9"
    assert result["analysis_script_sha256"] == hashlib.sha256(Path(audit.__file__).read_bytes()).hexdigest()
    assert result["summary"]["planned_attempts"] == 2
    assert result["timing"]["exact_master_duration_available"] is False
    assert {"historical_attempts_excluded", "plan_or_build_evidence_does_not_establish_validity"} <= set(result["limitations"])


@pytest.mark.parametrize("prior", ["074-corrected-staged-measurement", "076-public-plan-handoff-measurement"])
def test_prior_campaign_cannot_be_audited_as_current(monkeypatch, prior):
    def must_not_verify(*args):
        raise AssertionError("old campaign reached current registration validator")

    monkeypatch.setattr(audit, "verify_registration", must_not_verify)
    old = adapter.REPO / "specs" / prior / "measurement/manifest.json"
    with pytest.raises(ValueError, match="wrong.*campaign"):
        audit.audit_registered_campaign(old, adapter.CAMPAIGN)


@pytest.mark.parametrize("field,value", [
    ("kind", "feature076_postrun_audit"), ("implementation_commit", "0" * 40),
])
def test_report_rejects_prior_or_unbound_audit(field, value):
    fixture = report_fixture()
    fixture[field] = value
    with pytest.raises(ValueError, match="audit identity"):
        report.render_report(fixture)


def test_current_report_title_preserves_prior_score_and_denominator_contract():
    fixture = report_fixture()
    prior_tests.accept_first(fixture)
    text = report.render_report(fixture)
    assert text.startswith("# Lunar Agent Master 规划职责评测（Feature 078）\n")
    assert "1.0185 | 1.0185" in text and "null | null | null" in text
    assert "固定分母2" in text and "不声称修复因果效果" in text


def test_postrun_loaders_do_not_publish_global_dependency_aliases():
    names = ("prepare", "worker", "campaign", "audit", "adapter", "dry_run")
    before = {name: sys.modules.get(name) for name in names}
    for name in ("audit", "render_report", "test_audit"):
        assert adapter.load_previous_postrun(name).__file__
    assert {name: sys.modules.get(name) for name in names} == before


@pytest.mark.parametrize("name", ["audit", "render_report", "test_audit"])
def test_each_reused_postrun_helper_is_pinned_before_evaluation(monkeypatch, name):
    relative = "postrun/" + name + ".py"
    key = (adapter.PREVIOUS_ROOT / relative).relative_to(adapter.REPO).as_posix()
    assert adapter.HELPER_FILES[key] == adapter.PREVIOUS_FILES[relative]
    monkeypatch.setitem(adapter.PREVIOUS_FILES, relative, "0" * 64)
    with pytest.raises(ValueError, match="pinned measurement helper changed"):
        adapter.load_previous_postrun(name)


def test_public_scorer_plan_and_completed_build_are_audited_without_recovery(tmp_path, monkeypatch):
    campaign, case = tmp_path / "campaign", "sheet_metal_nesting"
    workspace = campaign / f"slots/001/trial/cases/{case}/runs/001/attempts/001/subject"
    manifest = WorkflowManifest(
        run_id="public-plan-fixture", attempt_id="slot-001-attempt-001", source_sha256="a" * 64,
        suite_key="fixture", case_key=case, request_sha256="b" * 64, model_profile_sha256="c" * 64,
        ceilings={"max_wall_seconds": 5400, "max_tool_steps": 200,
                  "max_total_tokens": 8_000_000, "max_cost_micros": None},
    )
    config = StagedWorkflowConfig(manifest, StagePolicy(**adapter.POLICIES["master_1200"]))
    slot = {"index": 1, "arm": "S", "budget_arm": "master_1200", "case_key": case,
            "workflow_config": config.to_dict()}
    controller = WorkflowController(workspace, manifest)
    (controller.workflow / "config.json").write_text(json.dumps(config.to_dict()))
    paths = ["scorer.py", "baseline_solution.py", "_agent_summary.md"]
    controller.write_master(["Implement the public objective scorer and combined_score."], paths)
    stage_validator, legacy = adapter.load_prior_postrun(), adapter.load_legacy("postrun")
    planned = stage_validator.stage_evidence(slot, campaign, legacy.Evidence(tmp_path), legacy)
    assert planned["plan_record_valid"] is True and planned["build_entered_observed"] is False
    controller.transition("build_running")
    for name in paths:
        (workspace / name).write_text("# Synthetic fixture; never executed.\n")
    for name in ("session-transcript.jsonl", "transcript-000001.jsonl"):
        (controller.workflow / name).write_text('{}\n')
    controller.checkpoint(
        stage="build_ready", declared_paths=paths, usage=AggregateUsage(True, 1, 1, 2, None, 1, 1),
        transcript=Path("workflow/transcript-000001.jsonl"),
    )
    before = {p: p.read_bytes() for p in workspace.rglob("*") if p.is_file()}

    def refuse(*args, **kwargs):
        raise AssertionError("observation attempted controller construction or mutation")

    for name in ("__init__", "_write_new", "_write_replace", "transition"):
        monkeypatch.setattr(WorkflowController, name, refuse)
    completed = stage_validator.stage_evidence(
        slot, campaign, legacy.Evidence(tmp_path), legacy, subject_accepted=True,
    )
    assert completed["plan_record_valid"] is completed["build_entered_observed"] is True
    assert completed["workflow_stage"] == "build_ready" and completed["master_duration_seconds"] is None
    assert not {"validity_score", "overall_score", "quality_score"}.intersection(completed)
    assert not (workspace / "receipt.json").exists()
    assert {p: p.read_bytes() for p in workspace.rglob("*") if p.is_file()} == before
