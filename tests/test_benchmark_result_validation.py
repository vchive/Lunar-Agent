import copy
import json
from pathlib import Path

import pytest

from lunar_evolution.benchmark_result import (
    BenchmarkResultError,
    bind_benchmark_comparison_result_evidence,
    parse_benchmark_comparison_result,
)
from tests.test_benchmark_result import _plan, _result


@pytest.mark.parametrize("source_kind", ["mapping", "json"])
@pytest.mark.parametrize(
    ("arm_fields", "error_code"),
    [
        ({"status": []}, "benchmark_result_invalid"),
        ({"status": {}}, "benchmark_result_invalid"),
        ({"best_score": 10**400}, "benchmark_result_invalid"),
        (
            {"evidence_path": "\ud800", "evidence_size": 1},
            "benchmark_result_evidence_invalid",
        ),
        (
            {"evidence_path": ".", "evidence_size": 1},
            "benchmark_result_evidence_invalid",
        ),
        (
            {"evidence_path": None, "evidence_size": None},
            "benchmark_result_evidence_invalid",
        ),
        ({"evidence_path": None}, "benchmark_result_evidence_invalid"),
        ({"evidence_size": None}, "benchmark_result_evidence_invalid"),
        ({"evidence_path": "arm.json"}, "benchmark_result_evidence_invalid"),
        ({"evidence_size": 1}, "benchmark_result_evidence_invalid"),
    ],
)
def test_result_malformed_arm_has_stable_error_code(
    tmp_path: Path, source_kind: str, arm_fields: dict[str, object], error_code: str,
):
    payload = copy.deepcopy(_result(_plan()).to_dict())
    payload["arms"][0].update(arm_fields)
    source = payload
    if source_kind == "json":
        source = tmp_path / "result.json"
        source.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BenchmarkResultError) as captured:
        parse_benchmark_comparison_result(source)
    assert captured.value.code == error_code


def test_result_json_integer_limit_has_stable_error_code(tmp_path: Path):
    source = tmp_path / "result.json"
    source.write_text('{"oversized_integer":' + "1" * 5000 + "}", encoding="utf-8")
    with pytest.raises(BenchmarkResultError) as captured:
        parse_benchmark_comparison_result(source)
    assert captured.value.code == "benchmark_result_invalid"


def test_bind_result_requires_evidence_root():
    plan = _plan()
    with pytest.raises(BenchmarkResultError) as captured:
        bind_benchmark_comparison_result_evidence(_result(plan), plan, None)
    assert captured.value.code == "benchmark_result_evidence_unsafe"
