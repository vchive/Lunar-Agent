from pathlib import Path

import pytest

from famou.benchmark_comparison import BenchmarkComparisonPlan
from famou.benchmark_result import (
    BenchmarkComparisonResult,
    BenchmarkResultError,
    ComparisonArmResult,
    admit_benchmark_comparison_result,
    parse_benchmark_comparison_result,
)
from tests.test_benchmark_comparison import env


def _plan() -> BenchmarkComparisonPlan:
    return BenchmarkComparisonPlan.from_envelopes({"sky": env(), "llm4ad": env("llm4ad")})


def _result(plan: BenchmarkComparisonPlan) -> BenchmarkComparisonResult:
    arms = tuple(ComparisonArmResult(a.id, "completed", 10, 2, 1, 0.5, "e" * 64) for a in plan.arms)
    from famou import benchmark_result as module
    rid = module._result_id(plan.comparison_id, arms)
    return BenchmarkComparisonResult(plan.comparison_id, rid, arms)


def test_result_roundtrip_and_plan_admission(tmp_path: Path):
    plan = _plan()
    result = _result(plan)
    assert parse_benchmark_comparison_result(result.to_dict()).digest() == result.digest()
    assert admit_benchmark_comparison_result(result, plan) == result


def test_result_rejects_missing_or_extra_arm():
    plan = _plan()
    result = _result(plan)
    arm = result.arms[0]
    with pytest.raises(BenchmarkResultError):
        admit_benchmark_comparison_result(BenchmarkComparisonResult(plan.comparison_id, result.result_id, (arm,)), plan)


def test_result_parser_rejects_duplicate_keys(tmp_path: Path):
    path = tmp_path / "result.json"
    path.write_text('{"schema_version":"1","schema_version":"1"}')
    with pytest.raises(BenchmarkResultError):
        parse_benchmark_comparison_result(path)
