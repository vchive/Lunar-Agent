import json
import re
from pathlib import Path

import pytest

from famou.algorithm import AlgorithmProblemContract, EvaluationReport
from famou.benchmark import BenchmarkConfig, BenchmarkError, BenchmarkRunner
from famou.evolution import CandidateDraft


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "benchmark-fixture",
            "problem_type": "routing",
            "statement": "Find a bounded fixture candidate.",
            "inputs": [{"path": "items.csv", "format": "csv", "fields": {"id": "item id"}}],
            "decision_variables": ["value"],
            "objective": {"name": "quality", "direction": "maximize"},
            "hard_constraints": [],
            "soft_constraints": [],
            "success_criteria": ["The candidate is valid."],
            "deliverables": ["candidate source"],
            "evolution": {"strategy": "loop", "max_rounds": 2, "stagnation_rounds": 10},
        }
    )


def _evaluator(candidate_path: Path, contract: AlgorithmProblemContract) -> EvaluationReport:
    del contract
    source = candidate_path.read_text(encoding="utf-8")
    score = float(re.search(r"return (\d+)", source).group(1))
    return EvaluationReport.from_dict(
        {
            "schema_version": "1",
            "evaluator_id": "benchmark-fixture",
            "validity": 1,
            "quality": score,
            "combined_score": score,
            "detailed_scores": {},
            "error_info": [],
        }
    )


def _generator(strategy: str):
    del strategy

    def generate(request):
        value = request.iteration + len(request.archive)
        return CandidateDraft(f"def solve():\n    return {value}\n")

    return generate


def test_benchmark_compares_strategies_in_isolated_workspaces(tmp_path: Path) -> None:
    runner = BenchmarkRunner(
        _contract(),
        tmp_path / "benchmark",
        generator_factory=_generator,
        evaluator_factory=lambda strategy: _evaluator,
        config=BenchmarkConfig(
            strategies=("loop", "population"),
            max_rounds=2,
            population_size=2,
            rng_seed=7,
        ),
    )

    report = runner.run()

    assert [item.strategy for item in report.runs] == ["loop", "population"]
    assert all(item.status in {"completed", "stagnated"} for item in report.runs)
    assert all(item.best_score is not None for item in report.runs)
    assert report.runs[0].workspace != report.runs[1].workspace
    assert (tmp_path / "benchmark" / "strategies" / "loop" / "evolution" / "archive.jsonl").is_file()
    assert (tmp_path / "benchmark" / "strategies" / "population" / "evolution" / "archive.jsonl").is_file()
    payload = json.loads((tmp_path / "benchmark" / "benchmark.json").read_text(encoding="utf-8"))
    assert payload["contract_sha256"] == _contract().digest()
    assert all(not Path(item["workspace"]).is_absolute() for item in payload["runs"])


def test_benchmark_records_one_strategy_failure_and_continues(tmp_path: Path) -> None:
    def generator_factory(strategy: str):
        if strategy == "loop":
            def fail(_request):
                raise RuntimeError("fixture generator failed")

            return fail
        return _generator(strategy)

    report = BenchmarkRunner(
        _contract(),
        tmp_path / "benchmark",
        generator_factory=generator_factory,
        evaluator_factory=lambda strategy: _evaluator,
        config=BenchmarkConfig(strategies=("loop", "population"), max_rounds=1, population_size=2),
    ).run()

    assert report.runs[0].status == "failed"
    assert "fixture generator failed" in (report.runs[0].error or "")
    assert report.runs[1].status in {"completed", "stagnated"}
    assert report.runs[1].best_score is not None


def test_benchmark_rejects_invalid_selection_and_existing_workspace(tmp_path: Path) -> None:
    with pytest.raises(BenchmarkError, match="at least one"):
        BenchmarkConfig(strategies=())
    with pytest.raises(BenchmarkError, match="unsupported"):
        BenchmarkConfig(strategies=("openevolve",))
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "keep.txt").write_text("do not overwrite", encoding="utf-8")
    with pytest.raises(BenchmarkError, match="not empty"):
        BenchmarkRunner(
            _contract(),
            existing,
            generator_factory=_generator,
            evaluator_factory=lambda strategy: _evaluator,
        )
