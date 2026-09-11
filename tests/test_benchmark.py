import json
import re
import sys
from pathlib import Path

import pytest

from famou.algorithm import AlgorithmProblemContract, EvaluationReport
from famou.benchmark import BenchmarkConfig, BenchmarkError, BenchmarkRun, BenchmarkRunner
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
            "evolution": {"strategy": "population", "max_rounds": 2, "stagnation_rounds": 10},
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


def test_benchmark_runs_population_in_an_isolated_workspace(tmp_path: Path) -> None:
    runner = BenchmarkRunner(
        _contract(),
        tmp_path / "benchmark",
        generator_factory=_generator,
        evaluator_factory=lambda strategy: _evaluator,
        config=BenchmarkConfig(
            strategies=("population",),
            max_rounds=2,
            population_size=2,
            rng_seed=7,
        ),
    )

    report = runner.run()

    assert [item.strategy for item in report.runs] == ["population"]
    assert all(item.status in {"completed", "stagnated"} for item in report.runs)
    assert all(item.best_score is not None for item in report.runs)
    assert (tmp_path / "benchmark" / "strategies" / "population" / "evolution" / "archive.jsonl").is_file()
    payload = json.loads((tmp_path / "benchmark" / "benchmark.json").read_text(encoding="utf-8"))
    assert payload["contract_sha256"] == _contract().digest()
    assert all(not Path(item["workspace"]).is_absolute() for item in payload["runs"])


def test_benchmark_records_population_strategy_failure(tmp_path: Path) -> None:
    def generator_factory(strategy: str):
        del strategy

        def fail(_request):
            raise RuntimeError("fixture generator failed")

        return fail

    report = BenchmarkRunner(
        _contract(),
        tmp_path / "benchmark",
        generator_factory=generator_factory,
        evaluator_factory=lambda strategy: _evaluator,
        config=BenchmarkConfig(strategies=("population",), max_rounds=1, population_size=2),
    ).run()

    assert report.runs[0].status == "failed"
    assert report.runs[0].error == "offspring_batch_failed"
    assert report.runs[0].best_score is None


def test_benchmark_includes_explicit_openevolve_adapter(tmp_path: Path) -> None:
    wrapper = tmp_path / "openevolve-wrapper.py"
    wrapper.write_text(
        "import json, pathlib, sys\n"
        "config_path = pathlib.Path(sys.argv[-1])\n"
        "config = json.loads(config_path.read_text())\n"
        "assert config['budget']['max_rounds'] == 2\n"
        "root = config_path.parent\n"
        "(root / 'candidate.py').write_text('def solve():\\n    return 9\\n')\n"
        "(root / 'result.json').write_text(json.dumps({'candidate_path':'candidate.py'}))\n",
        encoding="utf-8",
    )
    command = (sys.executable, str(wrapper))
    report = BenchmarkRunner(
        _contract(),
        tmp_path / "benchmark",
        generator_factory=_generator,
        evaluator_factory=lambda strategy: _evaluator,
        config=BenchmarkConfig(
            strategies=("population", "openevolve"),
            max_rounds=2,
            population_size=2,
            evaluator_fingerprint="e" * 64,
            strategy_commands={"openevolve": command},
        ),
    ).run()

    assert [item.status for item in report.runs] == ["completed", "completed"]
    assert report.runs[1].best_score == 9.0
    assert report.config.to_dict()["strategy_commands_sha256"]["openevolve"]
    evolution_root = (
        tmp_path / "benchmark" / "strategies" / "openevolve" / "evolution"
    )
    archive = [
        json.loads(line)
        for line in (evolution_root / "archive.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert len(archive) == 1
    candidate = archive[0]
    assert candidate["candidate_id"].startswith("seed-")
    assert candidate["strategy"] == "openevolve"
    assert candidate["evaluation"]["evaluator_id"] == "benchmark-fixture"
    assert candidate["evaluation"]["combined_score"] == 9.0
    candidate_root = evolution_root / "candidates" / candidate["candidate_id"]
    receipt = json.loads((candidate_root / "receipt.json").read_text(encoding="utf-8"))
    record = json.loads((candidate_root / "record.json").read_text(encoding="utf-8"))
    assert receipt["evaluator_kind"] == "exact_harness"
    assert receipt["evaluator_fingerprint"] == "e" * 64
    assert receipt["combined_score"] == 9.0
    assert len(receipt["receipt_sha256"]) == 64
    evidence = record["seed_handoff_evidence"]
    assert evidence["provenance"]["origin_kind"] == "external"
    assert evidence["provenance"]["producer_id"] == "openevolve"
    assert evidence["external_evidence"] == {
        "payload_sha256": None,
        "present": False,
        "score_present": False,
    }
    assert len(evidence["provenance_sha256"]) == 64
    assert not (evolution_root / "external").exists()
    assert str(wrapper) not in json.dumps(report.to_dict())


def test_benchmark_keeps_native_results_when_openevolve_command_fails(tmp_path: Path) -> None:
    report = BenchmarkRunner(
        _contract(),
        tmp_path / "benchmark",
        generator_factory=_generator,
        evaluator_factory=lambda strategy: _evaluator,
        config=BenchmarkConfig(
            strategies=("openevolve",),
            max_rounds=1,
            population_size=2,
            evaluator_fingerprint="e" * 64,
            strategy_commands={"openevolve": (str(tmp_path / "missing-openevolve"),)},
        ),
    ).run()

    assert report.runs[0].status == "failed"
    assert report.runs[0].best_score is None


def test_benchmark_rejects_invalid_selection_and_existing_workspace(tmp_path: Path) -> None:
    with pytest.raises(BenchmarkError, match="at least one"):
        BenchmarkConfig(strategies=())
    with pytest.raises(BenchmarkError, match="unsupported"):
        BenchmarkConfig(strategies=("invalid",))
    with pytest.raises(BenchmarkError, match="retired"):
        BenchmarkConfig(strategies=("loop",))
    with pytest.raises(BenchmarkError, match="pinned local evaluator fingerprint"):
        BenchmarkConfig(
            strategies=("openevolve",),
            strategy_commands={"openevolve": (sys.executable, "wrapper.py")},
        )
    historical = BenchmarkRun(
        strategy="loop",
        status="completed",
        elapsed_ms=1,
        evaluated_candidates=1,
        valid_candidates=1,
        best_score=1.0,
        workspace="strategies/loop",
        archive="strategies/loop/evolution/archive.jsonl",
    )
    assert historical.to_dict()["strategy"] == "loop"
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
