import json
from pathlib import Path

import pytest

from famou.agent_evolution import AgentCandidateGenerator
from famou.agents import AgentResult
from famou.algorithm import AlgorithmProblemContract, EvaluationReport
from famou.evolution import Candidate, EvolutionConfig, EvolutionContext, PopulationStrategy

FIRST_FAMILIES = {
    "routing": "nearest_insertion",
    "scheduling": "priority_dispatch",
    "packing": "first_fit_decreasing",
    "assignment": "greedy_min_cost",
    "forecasting": "seasonal_naive",
    "network_flow": "augmenting_path_flow",
    "continuous": "coordinate_descent",
}

DOMAIN_VALIDATION_CHECKS = {
    "routing": "replay_each_visit_once",
    "scheduling": "replay_precedence_and_non_overlap",
    "packing": "replay_item_coverage_once",
    "assignment": "replay_eligibility_and_cardinality",
    "forecasting": "compare_against_naive_baseline",
    "network_flow": "replay_node_flow_balance",
    "continuous": "replay_bounds_and_constraints",
}


def _contract(
    problem_type: str = "routing", *, constraint_count: int = 1
) -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": f"playbook-{problem_type}",
            "problem_type": problem_type,
            "statement": f"Solve one {problem_type} instance.",
            "inputs": [
                {"path": "items.csv", "format": "csv", "fields": {"id": "item ID"}}
            ],
            "decision_variables": ["domain decision"],
            "objective": {"name": "cost", "direction": "minimize"},
            "hard_constraints": [
                {
                    "id": f"constraint-{index:02d}",
                    "description": f"Secret business prose {index}",
                    "source": "user_confirmed",
                    "verification": "independent",
                }
                for index in range(constraint_count)
            ],
            "soft_constraints": [],
            "success_criteria": ["Produce a feasible result."],
            "deliverables": ["Self-contained candidate."],
        }
    )


def _report(score: float, *, valid: int = 1) -> EvaluationReport:
    return EvaluationReport.from_dict(
        {
            "schema_version": "1",
            "evaluator_id": "playbook-fixture",
            "validity": valid,
            "quality": score if valid else None,
            "combined_score": score if valid else 0,
            "detailed_scores": {"cost": {"value": 100 - score, "direction": "minimize"}},
            "error_info": []
            if valid
            else [{"code": "constraint-00", "message": "verified failure"}],
        }
    )


def _experiment(*tags: str) -> dict[str, object]:
    return {
        "schema_version": "1",
        "hypothesis": "Try one attributed algorithm family.",
        "change_tags": list(tags),
        "target_metrics": [{"metric": "cost", "direction": "decrease"}],
    }


def _candidate(
    number: int,
    *,
    family: str | None = None,
    parent: int | None = None,
    score: float = 1,
    valid: int = 1,
) -> Candidate:
    candidate_id = f"candidate-{number:04d}"
    return Candidate(
        candidate_id=candidate_id,
        code_path=f"evolution/candidates/{candidate_id}/candidate.py",
        parent_id=f"candidate-{parent:04d}" if parent is not None else None,
        generation=number - 1,
        iteration=number,
        strategy="population",
        island_id=number % 2,
        evaluation=_report(score, valid=valid),
        metadata={"experiment": _experiment(family)} if family else {},
    )


def _request(
    root: Path,
    archive: tuple[Candidate, ...] = (),
    parent: Candidate | None = None,
    inspirations: tuple[Candidate, ...] = (),
):
    return type(
        "Request",
        (),
        {
            "iteration": len(archive) + 1,
            "parent": parent,
            "inspirations": inspirations,
            "archive": archive,
            "workspace": root,
        },
    )()


def _context(
    contract: AlgorithmProblemContract, root: Path, request
) -> dict[str, object]:
    prompt = AgentCandidateGenerator(PlaybookAgent(), contract=contract)._prompt(request)
    return json.loads(prompt.split("Generation context:\n", 1)[1])


class PlaybookAgent:
    name = "playbook-agent"
    roles = frozenset({"solver"})
    capabilities = frozenset({"read_files"})

    def __init__(self) -> None:
        self.requests = []
        self.families = []

    def run(self, request):
        self.requests.append(request)
        context = json.loads(request.prompt.split("Generation context:\n", 1)[1])
        family = context["algorithm_playbook"]["family_tag"]
        self.families.append(family)
        return AgentResult(
            self.name,
            request.role,
            json.dumps(
                {
                    "source": f"print({len(self.requests)})",
                    "experiment": _experiment(family),
                }
            ),
        )

    def cancel(self):
        return None

    def process_info(self):
        return (None, None)

    def set_process_observer(self, observer):
        del observer


@pytest.mark.parametrize(("problem_type", "first_family"), FIRST_FAMILIES.items())
def test_each_problem_type_gets_a_bounded_domain_playbook(
    tmp_path: Path, problem_type: str, first_family: str
) -> None:
    contract = _contract(problem_type, constraint_count=12)

    context = _context(contract, tmp_path, _request(tmp_path))
    playbook = context["algorithm_playbook"]

    assert playbook["schema_version"] == "1"
    assert playbook["problem_type"] == problem_type
    assert playbook["mode"] == "explore"
    assert playbook["objective_direction"] == "minimize"
    assert playbook["family_tag"] == first_family
    assert playbook["selection_basis"] == "untried_family"
    assert 1 <= len(playbook["alternative_families"]) <= 4
    assert 1 <= len(playbook["modeling_checks"]) <= 8
    assert 1 <= len(playbook["validation_checks"]) <= 8
    assert DOMAIN_VALIDATION_CHECKS[problem_type] in playbook["validation_checks"]
    assert playbook["hard_constraint_ids"] == [
        f"constraint-{index:02d}" for index in range(8)
    ]
    assert "Secret business prose" not in json.dumps(playbook)


def test_playbook_uses_canonical_workspace_contract_without_in_memory_copy(
    tmp_path: Path,
) -> None:
    contract = _contract("scheduling")
    path = tmp_path / "evolution" / "contract.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(contract.to_dict()), encoding="utf-8")

    prompt = AgentCandidateGenerator(PlaybookAgent())._prompt(_request(tmp_path))
    context = json.loads(prompt.split("Generation context:\n", 1)[1])

    assert context["algorithm_playbook"]["problem_type"] == "scheduling"
    assert context["algorithm_playbook"]["family_tag"] == "priority_dispatch"


def test_diversify_allocates_untried_then_least_attempted_family(tmp_path: Path) -> None:
    contract = _contract()
    archive = (_candidate(1, family="nearest_insertion"),)

    first = _context(contract, tmp_path, _request(tmp_path, archive))["algorithm_playbook"]

    assert first["mode"] == "diversify"
    assert first["family_tag"] == "savings_merge"
    assert first["selection_basis"] == "untried_family"

    families = (
        "nearest_insertion",
        "savings_merge",
        "regret_insertion",
        "two_opt_local_search",
        "large_neighborhood_search",
    )
    covered = tuple(
        _candidate(index, family=family)
        for index, family in enumerate(families, start=1)
    )
    repeated = (*covered, _candidate(6, family="nearest_insertion"))

    second = _context(
        contract, tmp_path, _request(tmp_path, repeated)
    )["algorithm_playbook"]

    assert second["family_tag"] == "savings_merge"
    assert second["selection_basis"] == "least_tried_family"


def test_unrelated_tags_cannot_evict_full_archive_family_attempts(tmp_path: Path) -> None:
    contract = _contract()
    archive = [_candidate(1, family="nearest_insertion")]
    archive.extend(
        _candidate(index, family=f"unrelated-{index:03d}")
        for index in range(2, 48)
    )

    context = _context(contract, tmp_path, _request(tmp_path, tuple(archive)))

    assert "nearest_insertion" in context["experiment_memory"]["tag_outcomes"]
    assert len(context["experiment_memory"]["tag_outcomes"]) == 32
    assert context["algorithm_playbook"]["family_tag"] == "savings_merge"


@pytest.mark.parametrize(
    ("valid", "parent", "expected_mode", "expected_basis"),
    [
        (0, True, "repair", "target_family"),
        (1, True, "refine", "parent_family"),
    ],
)
def test_repair_and_refine_preserve_selected_lineage_family(
    tmp_path: Path,
    valid: int,
    parent: bool,
    expected_mode: str,
    expected_basis: str,
) -> None:
    contract = _contract()
    candidate = _candidate(1, family="regret_insertion", valid=valid)

    playbook = _context(
        contract,
        tmp_path,
        _request(tmp_path, (candidate,), candidate if parent else None),
    )["algorithm_playbook"]

    assert playbook["mode"] == expected_mode
    assert playbook["family_tag"] == "regret_insertion"
    assert playbook["selection_basis"] == expected_basis


def test_parentless_repair_preserves_latest_invalid_family(tmp_path: Path) -> None:
    contract = _contract()
    valid = _candidate(1, family="nearest_insertion")
    invalid = _candidate(2, family="large_neighborhood_search", valid=0)

    playbook = _context(
        contract,
        tmp_path,
        _request(tmp_path, (valid, invalid)),
    )["algorithm_playbook"]

    assert playbook["mode"] == "repair"
    assert playbook["family_tag"] == "large_neighborhood_search"
    assert playbook["selection_basis"] == "target_family"


def test_recombine_projects_parent_and_distinct_inspiration_families(tmp_path: Path) -> None:
    contract = _contract()
    parent = _candidate(2, family="two_opt_local_search", parent=1, score=2)
    inspirations = (
        _candidate(1, family="nearest_insertion"),
        _candidate(3, family="savings_merge", parent=1, score=1.5),
    )
    archive = (inspirations[0], parent, inspirations[1])

    playbook = _context(
        contract,
        tmp_path,
        _request(tmp_path, archive, parent, inspirations),
    )["algorithm_playbook"]

    assert playbook["mode"] == "recombine"
    assert playbook["family_tag"] == "two_opt_local_search"
    assert playbook["alternative_families"][:2] == [
        "nearest_insertion",
        "savings_merge",
    ]
    assert playbook["selection_basis"] == "recombination_lineage"


def test_recombine_excludes_invalid_inspiration_family(tmp_path: Path) -> None:
    contract = _contract()
    parent = _candidate(2, family="two_opt_local_search", parent=1, score=2)
    invalid = _candidate(3, family="large_neighborhood_search", valid=0)

    playbook = _context(
        contract,
        tmp_path,
        _request(tmp_path, (parent, invalid), parent, (invalid,)),
    )["algorithm_playbook"]

    assert playbook["mode"] == "recombine"
    assert playbook["family_tag"] == "two_opt_local_search"
    assert "large_neighborhood_search" not in playbook["alternative_families"]


def test_refine_without_lineage_uses_only_evaluator_verified_improvement(
    tmp_path: Path,
) -> None:
    contract = _contract()
    seed = _candidate(1)
    improved = _candidate(2, family="savings_merge", parent=1, score=3)
    regressed = _candidate(3, family="regret_insertion", parent=2, score=2)
    unknown_parent = _candidate(4, parent=3, score=2.5)

    playbook = _context(
        contract,
        tmp_path,
        _request(
            tmp_path,
            (seed, improved, regressed, unknown_parent),
            unknown_parent,
        ),
    )["algorithm_playbook"]

    assert playbook["family_tag"] == "savings_merge"
    assert playbook["selection_basis"] == "verified_improved_family"


def test_population_seed_generations_receive_distinct_algorithm_families(
    tmp_path: Path,
) -> None:
    contract = _contract()
    root = tmp_path / "population"
    (root / "evolution").mkdir(parents=True)
    (root / "evolution" / "contract.json").write_text(
        json.dumps(contract.to_dict()), encoding="utf-8"
    )
    agent = PlaybookAgent()

    result = PopulationStrategy(
        EvolutionContext(
            contract,
            root,
            AgentCandidateGenerator(agent, contract=contract),
            lambda path, ignored: _report(float(path.read_text().count("print"))),
            EvolutionConfig(
                strategy="population",
                max_rounds=1,
                stagnation_rounds=10,
                population_size=2,
                offspring_per_iteration=1,
                num_islands=2,
                rng_seed=7,
            ),
        )
    ).run()

    assert result.evaluated_candidates == 3
    assert agent.families[:2] == ["nearest_insertion", "savings_merge"]
    assert agent.families[2] in agent.families[:2]


def test_playbook_is_restart_stable_and_survives_prompt_compaction(tmp_path: Path) -> None:
    contract = _contract()
    families = tuple(FIRST_FAMILIES.values())
    archive = tuple(
        _candidate(
            index,
            family=families[index % len(families)],
            parent=index - 1 if index > 1 else None,
            score=float(index),
        )
        for index in range(1, 101)
    )
    request = _request(tmp_path, archive, archive[-1])
    generators = (
        AgentCandidateGenerator(PlaybookAgent(), contract=contract),
        AgentCandidateGenerator(PlaybookAgent(), contract=contract),
    )
    prompts = [generator._prompt(request) for generator in generators]
    contexts = [
        json.loads(prompt.split("Generation context:\n", 1)[1]) for prompt in prompts
    ]

    assert contexts[0]["algorithm_playbook"] == contexts[1]["algorithm_playbook"]
    assert contexts[0]["algorithm_playbook"]["mode"] == "refine"
    assert len(prompts[0].encode("utf-8")) <= 60 * 1024
