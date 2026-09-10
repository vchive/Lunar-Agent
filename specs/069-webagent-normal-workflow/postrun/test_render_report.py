"""Pure formatting checks: partial outcomes, unknown scores and descriptive references."""
import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("postrun_render_fixture", HERE / "render_report.py")
render = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render)


def fixture():
    pairs = [("sheet_metal_nesting", "M"), ("china_post_pickup_optimization", "S"),
             ("sheet_metal_nesting", "S"), ("china_post_pickup_optimization", "M")]
    rows = [{"case_key": key, "arm": arm, "started": index < 2, "process_terminated": index == 1,
             "status": "failed" if index == 1 else "started_unresolved" if index == 0 else "not_started",
             "harness_receipt_accepted": False, "extraction_status": None,
             "validity_score": None, "overall_score": None, "quality_score": None}
            for index, (key, arm) in enumerate(pairs)]
    arms = {arm: {"planned": 2, "valid": 0, "subject_receipts": 0,
                  "accepted_harness_receipts": 0} for arm in ("M", "S")}
    audited = {"passed": True, "complete": False, "manifest_sha256": "a" * 64, "summary": {
        "manifest_sha256": "a" * 64, "planned_attempts": 4, "slots": rows, "arms": arms,
    }}
    reference = {"manifest_sha256": "a" * 64, "cases": {
        key: {"platform_runs": [{"overall_score": score} for score in (1.01, 0.8, 0.9)],
              "prior_lunar": {"overall_score": None, "status": "failed"}}
        for key in render.CASE_NAMES
    }}
    return audited, reference


def test_partial_report_keeps_pending_and_unknown_scores_explicit():
    audited, reference = fixture()
    report = render.render_report(audited, reference)
    assert "进行中，尚不能作最终比较" in report
    assert "已启动 2 次，已终止 1 次" in report
    assert "运行中／结果未决 | null | null | null" in report
    assert "尚未启动 | null | null | null" in report
    assert "失败 | null | null | null" in report
    assert "1.01 / 0.8 / 0.9" in report
    assert "历史记录不进入本批分母" in report


@pytest.mark.parametrize("kind", ["unaccepted", "failed_extraction"])
def test_placeholder_score_cannot_be_rendered_as_quality(kind):
    audited, reference = fixture()
    row = audited["summary"]["slots"][1]
    row.update(harness_receipt_accepted=kind == "failed_extraction", extraction_status="failed",
               validity_score=0, overall_score=0, quality_score=0)
    with pytest.raises(ValueError):
        render.render_report(audited, reference)


def test_final_requires_four_terminated_slots_and_matching_registration():
    audited, reference = fixture()
    wrong = deepcopy(audited)
    wrong["complete"] = True
    with pytest.raises(ValueError):
        render.render_report(wrong, reference)
    wrong = deepcopy(audited)
    wrong["passed"] = False
    with pytest.raises(ValueError):
        render.render_report(wrong, reference)
    reference["manifest_sha256"] = "b" * 64
    with pytest.raises(ValueError):
        render.render_report(audited, reference)


def test_completed_valid_score_preserves_value_above_one_without_cross_case_mean():
    audited, reference = fixture()
    audited["complete"] = True
    for row in audited["summary"]["slots"]:
        row.update(started=True, process_terminated=True, status="failed")
    audited["summary"]["slots"][0].update(status="completed", harness_receipt_accepted=True,
        extraction_status="completed", validity_score=1, overall_score=1.0164, quality_score=None)
    audited["summary"]["arms"]["M"].update(valid=1, subject_receipts=1, accepted_harness_receipts=1)
    report = render.render_report(audited, reference)
    assert "已完成并通过结果审计" in report and "流程完成 | 1 | 1.0164 | null" in report
    assert "普通 control | 2 | 1 | 1 | 1" in report
    assert "不同 case 的分数不合并均值" in report


def historical_fixture(tmp_path):
    selection = {"model": "glm-5.2", "experiment_id": "fixture-experiment",
                 "agent_family": "AgentServer/OpenCode", "by_case": {}}
    previous = {"campaign_id": "fixture-old-campaign", "attempts": []}
    reference = {"authority": "descriptive_only", "historical_attempts_in_denominator": 0,
                 "model": "glm-5.2", "prior_lunar_campaign": previous["campaign_id"],
                 "platform": {"experiment_id": selection["experiment_id"],
                              "agent_family": selection["agent_family"], "exact_agent_commit": None},
                 "cases": {}}
    for key in render.CASE_NAMES:
        runs = [{"run_index": index, "validity_score": 1, "overall_score": value}
                for index, value in enumerate((1.02, 0.9, 0.8))]
        selection["by_case"][key] = {"runs": runs}
        prior = {"status": "failed", "subject_receipt_accepted": False,
                 "harness_receipt_accepted": False, "extraction_status": None,
                 "validity_score": None, "overall_score": None, "quality_score": None,
                 "subject_elapsed_seconds": 300.1}
        previous["attempts"].append({"case_key": key, **prior})
        reference["cases"][key] = {"platform_runs": [
            {"source_run_index": row["run_index"], "validity_score": row["validity_score"],
             "overall_score": row["overall_score"]} for row in runs], "prior_lunar": prior}
    sources = {
        ".lunar/high-score-case-selection-20260909/baseline-audit.json": selection,
        ".lunar/real-eval-glm-5.2-high-score-20260909/summary.json": previous,
    }
    digests = {}
    for relative, value in sources.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(value))
        digests[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    reference["source_files_sha256"] = dict(digests)
    return reference, {"historical_files_sha256": digests}


@pytest.mark.parametrize("change", [None, "platform_score", "prior_score", "prior_status",
                                   "digest", "source_bytes", "model", "agent", "denominator"])
def test_historical_reference_must_match_frozen_actual_records(tmp_path, change):
    reference, manifest = historical_fixture(tmp_path)
    case = reference["cases"]["sheet_metal_nesting"]
    if change == "platform_score":
        case["platform_runs"][0]["overall_score"] = 2
    elif change == "prior_score":
        case["prior_lunar"]["overall_score"] = 0
    elif change == "prior_status":
        case["prior_lunar"]["status"] = "completed"
    elif change == "digest":
        reference["source_files_sha256"][next(iter(manifest["historical_files_sha256"]))] = "a" * 64
    elif change == "source_bytes":
        (tmp_path / next(iter(manifest["historical_files_sha256"]))).write_text("{}")
    elif change == "model":
        reference["model"] = "different-model"
    elif change == "agent":
        reference["platform"]["exact_agent_commit"] = "unproven-commit"
    elif change == "denominator":
        reference["historical_attempts_in_denominator"] = 6
    if change is None:
        render.validate_reference(reference, manifest, repo=tmp_path)
    else:
        with pytest.raises(ValueError):
            render.validate_reference(reference, manifest, repo=tmp_path)
