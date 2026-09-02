import json
import stat
import sys
from pathlib import Path

from famou.algorithm import AlgorithmProblemContract
from famou.evolution import (
    CandidateArchive,
    CandidateDraft,
    EvolutionConfig,
    EvolutionContext,
    EvolutionStrategy,
    LoopStrategy,
    OpenEvolveStrategy,
    PopulationState,
    PopulationStrategy,
    build_strategy,
)


def _contract(strategy: str = "loop") -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "evolution-fixture",
            "problem_type": "routing",
            "statement": "Improve a deterministic route.",
            "inputs": [{"path": "items.csv", "format": "csv", "fields": {"id": "item id"}}],
            "decision_variables": ["route order"],
            "objective": {"name": "quality", "direction": "maximize"},
            "hard_constraints": [
                {
                    "id": "serve-all",
                    "description": "Serve all items.",
                    "source": "user_confirmed",
                    "verification": "independent",
                }
            ],
            "soft_constraints": [],
            "success_criteria": ["All items are served."],
            "deliverables": ["A route program."],
            "evolution": {"strategy": strategy, "max_rounds": 5, "stagnation_rounds": 3},
        }
    )


def _report(score: float, valid: int = 1) -> dict[str, object]:
    return {
        "schema_version": "1",
        "evaluator_id": "fixture",
        "validity": valid,
        "quality": score if valid else None,
        "combined_score": score if valid else 0,
        "detailed_scores": {"quality": {"value": score, "direction": "maximize"}},
        "error_info": [] if valid else [{"code": "invalid", "message": "fixture candidate is invalid"}],
    }


def test_loop_archives_every_round_and_returns_best_so_far(tmp_path: Path) -> None:
    scores = iter([0.2, 0.9, 0.4])

    def generate(request):
        return CandidateDraft(f"# round {request.iteration}\nscore = {request.iteration}\n")

    def evaluate(path, contract):
        del contract
        return _report(next(scores))

    context = EvolutionContext(
        _contract(), tmp_path, generate, evaluate,
        EvolutionConfig(max_rounds=3, stagnation_rounds=10),
    )
    result = LoopStrategy(context).run()
    assert result.status == "completed"
    assert result.evaluated_candidates == 3
    assert result.best_score == 0.9
    assert result.best_candidate_id == "candidate-0002"
    assert result.best_candidate_path == "evolution/candidates/candidate-0002/candidate.py"
    assert (tmp_path / result.best_candidate_path).is_file()
    assert len((tmp_path / "evolution" / "archive.jsonl").read_text().splitlines()) == 3
    assert json.loads((tmp_path / "evolution" / "state.json").read_text())["status"] == "completed"


def test_public_strategy_and_population_state_contracts_are_json_safe() -> None:
    state = PopulationState(
        iteration=2,
        population_size=4,
        offspring_per_iteration=1,
        num_islands=2,
        active_ids={"0": ("candidate-0001",), "1": ("candidate-0002",)},
        best_candidate_id="candidate-0002",
        rng_seed=7,
        last_migration_iteration=2,
    )
    assert state.to_dict()["active_ids"]["1"] == ["candidate-0002"]
    assert isinstance(LoopStrategy, type)
    assert hasattr(EvolutionStrategy, "run")


def test_loop_invalid_candidate_never_becomes_best(tmp_path: Path) -> None:
    def generate(request):
        return CandidateDraft(f"# {request.iteration}\n")

    def evaluate(path, contract):
        del path, contract
        return _report(10.0, valid=0)

    result = LoopStrategy(
        EvolutionContext(_contract(), tmp_path, generate, evaluate, EvolutionConfig(max_rounds=2, stagnation_rounds=10))
    ).run()
    assert result.status == "failed"
    assert result.best_candidate_id is None
    assert result.best_candidate_path is None
    assert result.valid_candidates == 0


def test_population_is_bounded_and_deterministic(tmp_path: Path) -> None:
    counter = {"value": 0}

    def generate(request):
        counter["value"] += 1
        return CandidateDraft(f"def solve_{counter['value']}():\n    return {counter['value']}\n")

    def evaluate(path, contract):
        del contract
        value = int(path.read_text().split("return ")[1].splitlines()[0])
        return _report(float(value))

    context = EvolutionContext(
        _contract("population"), tmp_path, generate, evaluate,
        EvolutionConfig(
            strategy="population", max_rounds=3, stagnation_rounds=10,
            population_size=4, offspring_per_iteration=2, num_islands=2,
            migration_interval=2, migration_rate=0.5, rng_seed=7,
        ),
    )
    result = PopulationStrategy(context).run()
    state = json.loads((tmp_path / "evolution" / "state.json").read_text())
    active = [item for ids in state["active_ids"].values() for item in ids]
    assert result.status == "completed"
    assert result.evaluated_candidates == 10  # four seeds plus six offspring
    assert len(active) <= 4
    assert len(active) == len(set(active))
    assert result.best_score == 10.0
    assert result.best_candidate_path is not None
    assert (tmp_path / result.best_candidate_path).is_file()


def test_result_does_not_handoff_missing_best_source(tmp_path: Path) -> None:
    def generate(request):
        return CandidateDraft("def solve():\n    return 1\n")

    result = LoopStrategy(
        EvolutionContext(_contract(), tmp_path, generate, lambda path, contract: _report(1), EvolutionConfig(max_rounds=1))
    ).run()
    assert result.best_candidate_path is not None
    (tmp_path / result.best_candidate_path).unlink()
    recovered = CandidateArchive(tmp_path).result("loop", "completed", 1)
    assert recovered.best_candidate_id is None
    assert recovered.best_candidate_path is None


def test_strategy_selector_accepts_openevolve_only_with_explicit_command(tmp_path: Path) -> None:
    contract = _contract("openevolve")
    config = EvolutionConfig(strategy="openevolve", command=(sys.executable, "-c", "pass"))
    context = EvolutionContext(contract, tmp_path, lambda request: CandidateDraft("x"), lambda p, c: _report(1), config)
    assert isinstance(build_strategy(context), OpenEvolveStrategy)
    try:
        EvolutionConfig(strategy="openevolve")
    except ValueError as exc:
        assert "explicit command" in str(exc)
    else:
        raise AssertionError("missing OpenEvolve command must fail")


def test_openevolve_adapter_imports_bounded_result(tmp_path: Path) -> None:
    fake = tmp_path / "fake_openevolve.py"
    fake.write_text(
        "import json, pathlib, sys\n"
        "cfg = json.loads(pathlib.Path(sys.argv[1]).read_text())\n"
        "root = pathlib.Path.cwd()\n"
        "(root / 'candidate.py').write_text('def solve():\\n    return 42\\n')\n"
        "(root / 'result.json').write_text(json.dumps({'candidate_path':'candidate.py'}))\n",
        encoding="utf-8",
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)

    def evaluate(path, contract):
        del contract
        assert path.is_file()
        return _report(0.75)

    context = EvolutionContext(
        _contract("openevolve"), tmp_path, lambda request: CandidateDraft("unused"), evaluate,
        EvolutionConfig(strategy="openevolve", command=(sys.executable, str(fake)), timeout_seconds=5),
    )
    result = OpenEvolveStrategy(context).run()
    assert result.status == "completed"
    assert result.best_score == 0.75
    assert result.best_candidate_path == "evolution/candidates/candidate-0001/candidate.py"
    assert (tmp_path / "evolution" / "candidates" / "candidate-0001" / "candidate.py").is_file()


def test_openevolve_rejects_relative_executable_without_writing_candidate(tmp_path: Path) -> None:
    context = EvolutionContext(
        _contract("openevolve"), tmp_path, lambda request: CandidateDraft("unused"), lambda p, c: _report(1),
        EvolutionConfig(strategy="openevolve", command=("python", "fake.py")),
    )
    result = OpenEvolveStrategy(context).run()
    assert result.status == "failed"
    assert result.evaluated_candidates == 0
    assert not (tmp_path / "evolution" / "archive.jsonl").exists()
