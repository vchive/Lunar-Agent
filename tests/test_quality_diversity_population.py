import json
from pathlib import Path

from famou.algorithm import ALGORITHM_FAMILY_REPERTOIRES, AlgorithmProblemContract, EvaluationReport
from famou.evolution import (
    Candidate,
    CandidateArchive,
    CandidateDraft,
    EvolutionConfig,
    EvolutionContext,
    PopulationStrategy,
)


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "quality-diversity-fixture",
            "problem_type": "routing",
            "statement": "Minimize routing cost.",
            "inputs": [
                {"path": "items.csv", "format": "csv", "fields": {"id": "item ID"}}
            ],
            "decision_variables": ["route order"],
            "objective": {"name": "cost", "direction": "minimize"},
            "hard_constraints": [],
            "soft_constraints": [],
            "success_criteria": ["Feasible route."],
            "deliverables": ["Candidate source."],
        }
    )


def _report(score: float, *, valid: int = 1) -> EvaluationReport:
    return EvaluationReport.from_dict(
        {
            "schema_version": "1",
            "evaluator_id": "quality-diversity-fixture",
            "validity": valid,
            "quality": score if valid else None,
            "combined_score": score if valid else 0,
            "detailed_scores": {"cost": {"value": 100 - score, "direction": "minimize"}},
            "error_info": []
            if valid
            else [{"code": "invalid-route", "message": "verified failure"}],
        }
    )


def _experiment(tag: str) -> dict[str, object]:
    return {
        "schema_version": "1",
        "hypothesis": f"Try {tag}.",
        "change_tags": [tag],
        "target_metrics": [{"metric": "cost", "direction": "decrease"}],
    }


def _candidate(
    number: int,
    family: str | None,
    score: float,
    *,
    valid: int = 1,
    island: int = 0,
) -> Candidate:
    candidate_id = f"candidate-{number:04d}"
    return Candidate(
        candidate_id=candidate_id,
        code_path=f"evolution/candidates/{candidate_id}/candidate.py",
        parent_id=None,
        generation=0,
        iteration=number,
        strategy="population",
        island_id=island,
        evaluation=_report(score, valid=valid),
        metadata={"experiment": _experiment(family)} if family else {},
    )


def _strategy(tmp_path: Path, *, seed: int = 7, population_size: int = 3) -> PopulationStrategy:
    return PopulationStrategy(
        EvolutionContext(
            _contract(),
            tmp_path,
            lambda request: CandidateDraft("print(0)"),
            lambda path, contract: _report(1),
            EvolutionConfig(
                strategy="population",
                population_size=population_size,
                num_islands=1,
                max_rounds=1,
                rng_seed=seed,
            ),
        )
    )


def _persist_fixture(tmp_path: Path, candidates: tuple[Candidate, ...]) -> PopulationStrategy:
    strategy = _strategy(tmp_path, population_size=max(1, len(candidates)))
    archive = CandidateArchive(tmp_path)
    for candidate in candidates:
        path = archive.candidate_source_path(candidate.candidate_id, "candidate.py")
        path.parent.mkdir(parents=True, exist_ok=True)
        source = f"def family_{candidate.candidate_id.replace('-', '_')}():\n    return {candidate.iteration}\n"
        archive.persist(
            CandidateDraft(source, metadata=candidate.metadata),
            candidate_id=candidate.candidate_id,
            strategy="population",
            iteration=candidate.iteration,
            generation=candidate.generation,
            island_id=candidate.island_id,
            evaluation=candidate.evaluation,
        )
    return strategy


def _family(strategy: PopulationStrategy, candidate: Candidate) -> str | None:
    return strategy._candidate_family(candidate)


def test_trim_keeps_global_best_and_distinct_valid_family_elites(tmp_path: Path) -> None:
    candidates = (
        _candidate(1, "nearest_insertion", 100),
        _candidate(2, "nearest_insertion", 99),
        _candidate(3, "savings_merge", 80),
        _candidate(4, "regret_insertion", 70),
    )
    strategy = _persist_fixture(tmp_path, candidates)
    strategy.config = EvolutionConfig(
        strategy="population", population_size=3, max_rounds=1
    )
    active = {0: [candidate.candidate_id for candidate in candidates]}

    strategy._trim(active)

    assert active[0] == ["candidate-0001", "candidate-0003", "candidate-0004"]


def test_trim_never_protects_invalid_or_unknown_tag_candidates(tmp_path: Path) -> None:
    candidates = (
        _candidate(1, "nearest_insertion", 10),
        _candidate(2, "unknown-model-claim", 9),
        _candidate(3, "savings_merge", 0, valid=0),
        _candidate(4, None, 8),
    )
    strategy = _persist_fixture(tmp_path, candidates)
    strategy.config = EvolutionConfig(
        strategy="population", population_size=2, max_rounds=1
    )
    active = {0: [candidate.candidate_id for candidate in candidates]}

    strategy._trim(active)

    assert active[0] == ["candidate-0001", "candidate-0002"]
    records = {candidate.candidate_id: candidate for candidate in strategy.archive.records()}
    assert _family(strategy, records["candidate-0001"]) == "nearest_insertion"
    assert _family(strategy, records["candidate-0002"]) is None
    assert _family(strategy, records["candidate-0003"]) == "savings_merge"


def test_legacy_trim_without_family_tags_matches_rank_order(tmp_path: Path) -> None:
    candidates = (
        _candidate(1, None, 5),
        _candidate(2, None, 9),
        _candidate(3, None, 7),
    )
    strategy = _persist_fixture(tmp_path, candidates)
    strategy.config = EvolutionConfig(
        strategy="population", population_size=2, max_rounds=1
    )
    active = {0: [candidate.candidate_id for candidate in candidates]}

    expected = [
        candidate.candidate_id
        for candidate in strategy._rank(strategy.archive.records(), strategy.archive.records())[:2]
    ]
    strategy._trim(active)

    assert active[0] == expected


def test_parent_pool_contains_one_valid_elite_per_family_before_clones(
    tmp_path: Path,
) -> None:
    candidates = (
        _candidate(1, "nearest_insertion", 100),
        _candidate(2, "nearest_insertion", 99),
        _candidate(3, "savings_merge", 80),
        _candidate(4, "regret_insertion", 70),
    )
    strategy = _persist_fixture(tmp_path, candidates)
    active = {0: [candidate.candidate_id for candidate in candidates]}

    pool = strategy._parent_pool(active, 0)

    assert [candidate.candidate_id for candidate in pool] == [
        "candidate-0001",
        "candidate-0003",
        "candidate-0004",
    ]
    first = strategy._select_parent(active, 0)
    resumed = _persist_fixture(tmp_path / "resumed", candidates)
    second = resumed._select_parent(active, 0)
    assert first is not None and second is not None
    assert first.candidate_id == second.candidate_id
    assert first.candidate_id != "candidate-0002"


def test_inspirations_prefer_valid_distinct_cross_family_candidates(tmp_path: Path) -> None:
    parent = _candidate(1, "nearest_insertion", 100, island=0)
    candidates = (
        parent,
        _candidate(2, "nearest_insertion", 99, island=1),
        _candidate(3, "savings_merge", 70, island=1),
        _candidate(4, "regret_insertion", 60, island=1),
        _candidate(5, "large_neighborhood_search", 0, valid=0, island=1),
    )
    strategy = _persist_fixture(tmp_path, candidates)
    active = {0: ["candidate-0001"], 1: [item.candidate_id for item in candidates[1:]]}
    strategy.config = EvolutionConfig(
        strategy="population", population_size=5, num_islands=2, max_rounds=1
    )

    inspirations = strategy._inspirations(active, 0, strategy.archive.records()[0])

    assert len(inspirations) == 2
    assert {candidate.evaluation.validity for candidate in inspirations} == {1}
    assert {_family(strategy, candidate) for candidate in inspirations} == {
        "savings_merge",
        "regret_insertion",
    }


def test_end_to_end_population_retains_three_algorithm_families(tmp_path: Path) -> None:
    families_and_scores = iter(
        (
            ("nearest_insertion", 100),
            ("nearest_insertion", 90),
            ("savings_merge", 80),
            ("regret_insertion", 70),
            ("nearest_insertion", 95),
        )
    )

    def generate(request):
        del request
        family, score = next(families_and_scores)
        return CandidateDraft(
            f"SCORE = {score}\n",
            metadata={"experiment": _experiment(family)},
        )

    def evaluate(path, contract):
        del contract
        return _report(float(path.read_text().split("=")[1]))

    result = PopulationStrategy(
        EvolutionContext(
            _contract(),
            tmp_path,
            generate,
            evaluate,
            EvolutionConfig(
                strategy="population",
                max_rounds=1,
                stagnation_rounds=10,
                population_size=3,
                offspring_per_iteration=2,
                num_islands=1,
                rng_seed=7,
            ),
        )
    ).run()
    state = json.loads((tmp_path / "evolution" / "state.json").read_text())
    archive = {item.candidate_id: item for item in CandidateArchive(tmp_path).records()}
    active_families = {
        next(
            tag
            for tag in archive[candidate_id].metadata["experiment"]["change_tags"]
            if tag in ALGORITHM_FAMILY_REPERTOIRES["routing"]
        )
        for candidate_id in state["active_ids"]["0"]
    }

    assert result.best_score == 100
    assert active_families == {
        "nearest_insertion",
        "savings_merge",
        "regret_insertion",
    }


def test_quality_diversity_reconstructs_from_archive_after_restart(tmp_path: Path) -> None:
    candidates = (
        _candidate(1, "nearest_insertion", 100),
        _candidate(2, "nearest_insertion", 99),
        _candidate(3, "savings_merge", 80),
        _candidate(4, "regret_insertion", 70),
    )
    first = _persist_fixture(tmp_path, candidates)
    first.config = EvolutionConfig(
        strategy="population", population_size=3, max_rounds=1
    )
    before = {0: [candidate.candidate_id for candidate in candidates]}
    first._trim(before)

    resumed = _strategy(tmp_path, population_size=3)
    after = {0: [candidate.candidate_id for candidate in candidates]}
    resumed._trim(after)

    assert before == after
