"""Caller pins and receipt pins at the static comparison CLI."""

import json

import pytest

from lunar_evolution import cli
from lunar_evolution.benchmark_comparison import parse_benchmark_comparison_plan
from lunar_evolution.benchmark_result import (
    BenchmarkComparisonResult,
    parse_benchmark_comparison_result,
)
from tests.test_benchmark_evidence_cli import _cli_files


@pytest.mark.parametrize("pinned", [False, True])
@pytest.mark.parametrize("evidence", [False, True])
def test_cli_reports_independent_binding_states(tmp_path, monkeypatch, capsys, pinned, evidence):
    args, result_path, _ = _cli_files(tmp_path)
    plan = parse_benchmark_comparison_plan(args[2])
    result = parse_benchmark_comparison_result(result_path)
    if pinned:
        result = BenchmarkComparisonResult.from_plan(plan, result.arms)
        result_path.write_text(json.dumps(result.to_dict()))
        args.extend(["--plan-sha256", plan.digest()])
    if not evidence:
        position = args.index("--evidence-root")
        del args[position:position + 2]
    monkeypatch.setattr(cli, "_config", lambda *_: pytest.fail("initialized home"))
    args.extend(["--home", str(tmp_path / "home"), "--json"])
    assert cli.main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["plan_bound"] is pinned
    assert payload["evidence_bound"] is evidence
    assert payload["plan_sha256"] == plan.digest()
    assert payload["result_id"] == result.result_id
    assert not (tmp_path / "home").exists()


@pytest.mark.parametrize(("failure", "expected"), [
    ("legacy", "benchmark_result_plan_pin_required"),
    ("caller_mismatch", "benchmark_result_identity_mismatch"),
    ("caller_invalid", "benchmark_result_invalid"),
    ("changed_release", "benchmark_result_identity_mismatch"),
])
def test_cli_rejects_exact_plan_mismatch(tmp_path, monkeypatch, capsys, failure, expected):
    args, result_path, _ = _cli_files(tmp_path)
    plan = parse_benchmark_comparison_plan(args[2])
    result = parse_benchmark_comparison_result(result_path)
    if failure != "legacy":
        result = BenchmarkComparisonResult.from_plan(plan, result.arms)
        result_path.write_text(json.dumps(result.to_dict()))
    caller = plan.digest()
    if failure == "caller_mismatch":
        caller = "f" * 64
    elif failure == "caller_invalid":
        caller = "private-invalid-pin"
    elif failure == "changed_release":
        from pathlib import Path

        payload = plan.to_dict()
        payload["arms"][0]["envelope"]["benchmark"]["release_version"] = "different-release"
        Path(args[2]).write_text(json.dumps(payload))
        # The caller supplies the changed plan's legitimate digest; the retained receipt must fail.
        caller = parse_benchmark_comparison_plan(args[2]).digest()
    monkeypatch.setattr(cli, "_config", lambda *_: pytest.fail("initialized home"))
    args.extend(["--plan-sha256", caller, "--home", str(tmp_path / "home"), "--json"])
    assert cli.main(args) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err) == {"error": expected}
    assert not (tmp_path / "home").exists()
