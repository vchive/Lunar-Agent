import json
from pathlib import Path

import pytest

from famou.deep_feedback import (
    FeedbackError,
    build_candidate_manifest,
    build_round_feedback,
    normalize_feedback,
)


def _scored(score, *, validity=1.0, quality=None, extraction="completed", details=None):
    return {
        "extraction_status": extraction,
        "validity_score": validity,
        "overall_score": score,
        "quality_score": quality if quality is not None else score,
        "detail_metrics": details or {},
    }


def test_feedback_filters_private_metrics_and_tracks_best_and_stagnation() -> None:
    first = build_round_feedback(
        1,
        _scored(0.40, details={"objective": 0.40, "private_secret": 123456}),
        candidate_manifest=[{"path": "answer.json", "size_bytes": 2, "sha256": "sha256:" + "a" * 64}],
        prior_rounds=[],
        stagnation_rounds=2,
    )
    assert first["detail_metrics"] == {"objective": 0.40}
    assert first["best_overall_score"] == 0.40
    assert first["best_round_index"] == 1
    assert first["directive"] == "refine_best"

    second = build_round_feedback(
        2,
        _scored(0.40),
        candidate_manifest=[],
        prior_rounds=[{**_scored(0.40), "round_index": 1}],
        stagnation_rounds=2,
    )
    assert second["score_delta"] == pytest.approx(0.0)
    assert second["stagnation"] == {"detected": False, "consecutive_rounds": 1, "window": 2}

    third = build_round_feedback(
        3,
        _scored(0.39),
        candidate_manifest=[],
        prior_rounds=[
            {**_scored(0.40), "round_index": 1},
            {**_scored(0.40), "round_index": 2},
        ],
        stagnation_rounds=2,
    )
    assert third["best_overall_score"] == pytest.approx(0.40)
    assert third["best_round_index"] == 1
    assert third["stagnation"] == {"detected": True, "consecutive_rounds": 2, "window": 2}
    assert third["directive"] == "change_search_strategy"


def test_feedback_prioritizes_invalidity_repair_and_normalizes_legacy() -> None:
    invalid = build_round_feedback(
        2,
        _scored(0.0, validity=0.0, extraction="completed"),
        candidate_manifest=[],
        prior_rounds=[],
        stagnation_rounds=2,
    )
    assert invalid["failure_category"] == "invalid_candidate"
    assert invalid["directive"] == "repair_validity"

    legacy = normalize_feedback(
        {"round_index": 1, "validity_score": 1.0, "overall_score": 0.5, "quality_score": 0.5},
        expected_round=1,
    )
    assert legacy["schema_version"] == "1"
    assert legacy["candidate_manifest"] == []
    assert legacy["directive"] == "preserve_best_and_probe"


def test_candidate_manifest_excludes_control_and_public_files(tmp_path: Path) -> None:
    (tmp_path / "case" / "data").mkdir(parents=True)
    (tmp_path / "case" / "data" / "input.json").write_text("{}", encoding="utf-8")
    (tmp_path / "receipts").mkdir()
    (tmp_path / "receipts" / "001.json").write_text("{}", encoding="utf-8")
    (tmp_path / "request.json").write_text("{}", encoding="utf-8")
    (tmp_path / "answer.json").write_text(json.dumps({"score": 1}), encoding="utf-8")

    manifest = build_candidate_manifest(tmp_path)
    assert [item["path"] for item in manifest] == ["answer.json"]
    assert manifest[0]["sha256"].startswith("sha256:")


def test_feedback_validation_rejects_absolute_or_bad_manifest_paths() -> None:
    feedback = build_round_feedback(
        1,
        _scored(0.4),
        candidate_manifest=[],
        prior_rounds=[],
        stagnation_rounds=2,
    )
    feedback["candidate_manifest"] = [{"path": "/tmp/secret", "size_bytes": 1, "sha256": "sha256:" + "a" * 64}]
    with pytest.raises(FeedbackError, match="relative"):
        normalize_feedback(feedback, expected_round=1)
