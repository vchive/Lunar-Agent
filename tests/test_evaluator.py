import json
from pathlib import Path

import pytest

from famou.evaluator import (
    MAX_ARTIFACT_BYTES,
    acceptance_evaluator,
    compile_acceptance,
    validate_acceptance,
)


def test_legacy_acceptance_forms_compile_to_result_contains(tmp_path: Path) -> None:
    for value in ("complete", {"contains": "complete"}, '"complete"'):
        evaluator = acceptance_evaluator(value)
        assert evaluator is not None
        evaluation = evaluator.evaluate("task is complete", tmp_path)
        assert evaluation.passed
        assert evaluation.details["contract"] == {"result_contains": "complete"}


def test_artifact_contract_checks_text_json_and_composition(tmp_path: Path) -> None:
    workspace = tmp_path / "attempt"
    workspace.mkdir()
    (workspace / "report.json").write_text(
        json.dumps({"summary": "verified source report", "sources": []}), encoding="utf-8"
    )
    evaluator = acceptance_evaluator(
        {
            "all": [
                {"result_contains": "report written"},
                {"artifact_exists": "report.json"},
                {"artifact_text_contains": {"path": "report.json", "contains": "verified"}},
                {"json_parse": "report.json"},
                {"json_has_keys": {"path": "report.json", "keys": ["summary", "sources"]}},
            ]
        }
    )

    assert evaluator is not None
    evaluation = evaluator.evaluate("report written", workspace)

    assert evaluation.passed
    check = evaluation.details["check"]
    assert isinstance(check, dict)
    assert check["rule"] == "all"
    assert len(check["children"]) == 5
    assert all(child["passed"] for child in check["children"])


def test_output_valid_acceptance_checks_structured_data_formats(tmp_path: Path) -> None:
    workspace = tmp_path / "attempt"
    (workspace / "output").mkdir(parents=True)
    (workspace / "output" / "routes.csv").write_text(
        "item_id,route_id\n1,r1\n2,r2\n", encoding="utf-8"
    )
    csv_evaluator = acceptance_evaluator(
        {"output_valid": {"path": "output/routes.csv", "format": "csv", "fields": ["item_id", "route_id"]}}
    )
    assert csv_evaluator is not None
    csv_result = csv_evaluator.evaluate("route data", workspace)
    assert csv_result.passed
    assert csv_result.details["check"]["row_count"] == 2

    (workspace / "output" / "summary.jsonl").write_text(
        '{"distance": 12, "vehicle": "v1"}\n', encoding="utf-8"
    )
    jsonl_evaluator = acceptance_evaluator(
        {"output_valid": {"path": "output/summary.jsonl", "format": "jsonl", "fields": ["distance"]}}
    )
    assert jsonl_evaluator is not None and jsonl_evaluator.evaluate("route data", workspace).passed

    (workspace / "output" / "summary.json").write_text("[1, 2]", encoding="utf-8")
    invalid = acceptance_evaluator(
        {"output_valid": {"path": "output/summary.json", "format": "json", "fields": ["distance"]}}
    )
    assert invalid is not None
    assert not invalid.evaluate("route data", workspace).passed


def test_output_valid_rejects_non_output_paths_and_invalid_format() -> None:
    with pytest.raises(ValueError, match="output/"):
        validate_acceptance({"output_valid": {"path": "report.json", "format": "json", "fields": []}})
    with pytest.raises(ValueError, match="format"):
        validate_acceptance({"output_valid": {"path": "output/report.bin", "format": "binary", "fields": []}})


def test_any_keeps_evidence_for_every_alternative(tmp_path: Path) -> None:
    workspace = tmp_path / "attempt"
    workspace.mkdir()
    (workspace / "alternate.txt").write_text("available", encoding="utf-8")
    evaluator = acceptance_evaluator(
        {"any": [{"artifact_exists": "missing.txt"}, {"artifact_exists": "alternate.txt"}]}
    )

    assert evaluator is not None
    evaluation = evaluator.evaluate("output", workspace)

    assert evaluation.passed
    check = evaluation.details["check"]
    assert isinstance(check, dict)
    assert [child["passed"] for child in check["children"]] == [False, True]


@pytest.mark.parametrize(
    "value, match",
    [
        ({"artifact_exists": "../outside.txt"}, "workspace"),
        ({"artifact_exists": "/tmp/outside.txt"}, "workspace"),
        ({"unknown_rule": "value"}, "unsupported"),
        ({"artifact_text_contains": {"path": "a.txt"}}, "exactly"),
        ("{bad json", "malformed"),
        ({"result_contains": "sk-abcdefghijklmnop"}, "credential"),
    ],
)
def test_unsafe_or_malformed_contracts_are_rejected(value: object, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        validate_acceptance(value)  # type: ignore[arg-type]


def test_contract_rejects_symlink_escape_without_reading_target(tmp_path: Path) -> None:
    workspace = tmp_path / "attempt"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private content", encoding="utf-8")
    (workspace / "escape.txt").symlink_to(outside)
    evaluator = acceptance_evaluator({"artifact_text_contains": {"path": "escape.txt", "contains": "private"}})

    assert evaluator is not None
    evaluation = evaluator.evaluate("output", workspace)

    assert not evaluation.passed
    assert "outside the attempt workspace" in evaluation.reason
    assert "private content" not in json.dumps(evaluation.details)


def test_contract_rejects_a_symlinked_attempt_workspace(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "report.txt").write_text("private content", encoding="utf-8")
    workspace = tmp_path / "attempt"
    workspace.symlink_to(outside, target_is_directory=True)
    evaluator = acceptance_evaluator({"artifact_exists": "report.txt"})

    assert evaluator is not None
    evaluation = evaluator.evaluate("output", workspace)

    assert not evaluation.passed
    assert "workspace must not be a symlink" in evaluation.reason


def test_json_contract_fails_for_malformed_or_incomplete_artifact(tmp_path: Path) -> None:
    workspace = tmp_path / "attempt"
    workspace.mkdir()
    (workspace / "report.json").write_text('{"summary": "ok"}', encoding="utf-8")
    evaluator = acceptance_evaluator(
        {"json_has_keys": {"path": "report.json", "keys": ["summary", "sources"]}}
    )

    assert evaluator is not None
    missing_key = evaluator.evaluate("output", workspace)
    assert not missing_key.passed
    assert "sources" in missing_key.reason

    (workspace / "report.json").write_text("{not JSON", encoding="utf-8")
    malformed = evaluator.evaluate("output", workspace)
    assert not malformed.passed
    assert "valid JSON" in malformed.reason


def test_oversized_artifacts_fail_closed(tmp_path: Path) -> None:
    workspace = tmp_path / "attempt"
    workspace.mkdir()
    (workspace / "large.txt").write_bytes(b"x" * (MAX_ARTIFACT_BYTES + 1))
    evaluator = acceptance_evaluator({"artifact_text_contains": {"path": "large.txt", "contains": "x"}})

    assert evaluator is not None
    evaluation = evaluator.evaluate("output", workspace)

    assert not evaluation.passed
    assert "inspection bytes" in evaluation.reason


def test_composite_limits_are_rejected() -> None:
    value: object = {"result_contains": "done"}
    for _ in range(8):
        value = {"all": [value]}
    with pytest.raises(ValueError, match="depth"):
        compile_acceptance(value)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="more than"):
        compile_acceptance({"all": [{"result_contains": str(index)} for index in range(33)]})
