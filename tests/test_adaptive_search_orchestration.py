import json
from pathlib import Path

import pytest

from famou.agent_evolution import AgentCandidateGenerator
from famou.agents import AgentResult
from famou.algorithm import AlgorithmProblemContract, EvaluationReport
from famou.evolution import (
    Candidate,
    EvolutionConfig,
    EvolutionContext,
    LoopStrategy,
    PopulationStrategy,
)


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "directive-fixture",
            "problem_type": "routing",
            "statement": "Minimize distance with a feasible route.",
            "inputs": [
                {"path": "items.csv", "format": "csv", "fields": {"id": "item ID"}}
            ],
            "decision_variables": ["route order"],
            "objective": {"name": "distance", "direction": "minimize"},
            "hard_constraints": [
                {
                    "id": "serve-all",
                    "description": "Serve each item once.",
                    "source": "user_confirmed",
                    "verification": "independent",
                }
            ],
            "soft_constraints": [],
            "success_criteria": ["Feasible route."],
            "deliverables": ["Route program."],
        }
    )


def _report(score: float, *, valid: int = 1, code: str = "serve-all") -> EvaluationReport:
    return EvaluationReport.from_dict(
        {
            "schema_version": "1",
            "evaluator_id": "directive-fixture",
            "validity": valid,
            "quality": score if valid else None,
            "combined_score": score if valid else 0,
            "detailed_scores": {
                "distance": {"value": 1 / score if score else 999, "direction": "minimize"}
            },
            "error_info": []
            if valid
            else [{"code": code, "message": "verified failure"}],
        }
    )


def _experiment(tag: str) -> dict[str, object]:
    return {
        "schema_version": "1",
        "hypothesis": f"Try {tag}.",
        "change_tags": [tag],
        "target_metrics": [{"metric": "distance", "direction": "decrease"}],
    }


def _candidate(
    number: int,
    *,
    valid: int = 1,
    score: float = 1,
    parent: int | None = None,
    tag: str | None = None,
    code: str = "serve-all",
) -> Candidate:
    candidate_id = f"candidate-{number:04d}"
    return Candidate(
        candidate_id,
        f"evolution/candidates/{candidate_id}/candidate.py",
        f"candidate-{parent:04d}" if parent is not None else None,
        number - 1,
        number,
        "population",
        number % 2,
        _report(score, valid=valid, code=code),
        {"experiment": _experiment(tag)} if tag else {},
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


def _directive(generator: AgentCandidateGenerator, request) -> dict[str, object]:
    prompt = generator._prompt(request)
    return json.loads(prompt.split("Generation context:\n", 1)[1])["search_directive"]


class DirectiveAgent:
    name = "directive-agent"
    roles = frozenset({"solver"})
    capabilities = frozenset({"read_files"})

    def __init__(self) -> None:
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        return AgentResult(
            self.name,
            request.role,
            json.dumps(
                {
                    "source": f"print({len(self.requests)})",
                    "experiment": _experiment(f"attempt-{len(self.requests):02d}"),
                }
            ),
        )

    def cancel(self):
        return None

    def process_info(self):
        return (None, None)

    def set_process_observer(self, observer):
        del observer


@pytest.mark.parametrize(
    ("mode", "parent", "inspirations", "archive", "expected"),
    [
        ("explore", None, (), (), {"priority": "establish_feasible_baseline"}),
        (
            "diversify",
            None,
            (),
            (_candidate(1),),
            {"priority": "increase_algorithmic_diversity"},
        ),
        (
            "repair",
            None,
            (),
            (
                _candidate(1),
                _candidate(2, valid=0, score=0, code="serve-all"),
            ),
            {"priority": "restore_feasibility", "target_candidate_id": "candidate-0002"},
        ),
        (
            "refine",
            _candidate(1),
            (),
            (_candidate(1),),
            {"priority": "improve_verified_objective", "parent_id": "candidate-0001"},
        ),
        (
            "recombine",
            _candidate(2, parent=1),
            (_candidate(1),),
            (_candidate(1), _candidate(2, parent=1)),
            {"priority": "combine_complementary_evidence", "parent_id": "candidate-0002"},
        ),
    ],
)
def test_search_directive_mode_table(
    tmp_path: Path,
    mode: str,
    parent: Candidate | None,
    inspirations: tuple[Candidate, ...],
    archive: tuple[Candidate, ...],
    expected: dict[str, str],
) -> None:
    generator = AgentCandidateGenerator(DirectiveAgent(), contract=_contract())

    directive = _directive(generator, _request(tmp_path, archive, parent, inspirations))

    assert directive["mode"] == mode
    for key, value in expected.items():
        assert directive[key] == value
    assert directive["inspiration_ids"] == [
        item.candidate_id for item in inspirations
    ]
    if mode == "repair":
        assert directive["error_codes"] == ["serve-all"]


def test_repair_uses_invalid_parent_and_bounded_sorted_error_codes(tmp_path: Path) -> None:
    errors = [
        {"code": f"failure-{index % 10:02d}", "message": "verified failure"}
        for index in range(16)
    ]
    parent = _candidate(1, valid=0, score=0)
    parent = Candidate(
        parent.candidate_id,
        parent.code_path,
        parent.parent_id,
        parent.generation,
        parent.iteration,
        parent.strategy,
        parent.island_id,
        EvaluationReport.from_dict(
            {
                **parent.evaluation.to_dict(),
                "error_info": errors,
            }
        ),
        parent.metadata,
    )

    directive = _directive(
        AgentCandidateGenerator(DirectiveAgent(), contract=_contract()),
        _request(tmp_path, (parent,), parent),
    )

    assert directive["mode"] == "repair"
    assert directive["target_candidate_id"] == "candidate-0001"
    assert directive["parent_id"] is None
    assert directive["error_codes"] == [f"failure-{index:02d}" for index in range(8)]


def test_directive_tag_policy_uses_verified_outcomes_and_is_bounded(tmp_path: Path) -> None:
    archive = [_candidate(1, tag="seed")]
    archive.extend(
        [
            _candidate(2, score=3, parent=1, tag="proven"),
            _candidate(3, score=2, parent=2, tag="regressed"),
            _candidate(4, valid=0, score=0, parent=3, tag="invalid"),
        ]
    )
    for index in range(5, 25):
        archive.append(
            _candidate(index, score=2, parent=3, tag=f"failed-{index:02d}")
        )
    generator = AgentCandidateGenerator(DirectiveAgent(), contract=_contract())

    directive = _directive(generator, _request(tmp_path, tuple(archive), archive[1]))

    assert directive["proven_change_tags"] == ["proven"]
    assert set(directive["avoid_change_tags"]) >= {"regressed", "invalid"}
    assert len(directive["avoid_change_tags"]) == 8
    assert all("MODEL_CLAIM" not in value for value in directive["avoid_change_tags"])


def test_loop_changes_repair_directive_to_refine_after_feasibility(tmp_path: Path) -> None:
    root = tmp_path / "loop"
    (root / "evolution").mkdir(parents=True)
    (root / "evolution" / "contract.json").write_text(
        json.dumps(_contract().to_dict()), encoding="utf-8"
    )
    agent = DirectiveAgent()
    reports = iter((_report(0, valid=0), _report(1), _report(2)))
    LoopStrategy(
        EvolutionContext(
            _contract(),
            root,
            AgentCandidateGenerator(agent, contract=_contract()),
            lambda path, contract: next(reports),
            EvolutionConfig(max_rounds=3, stagnation_rounds=10),
        )
    ).run()

    directives = [
        json.loads(request.prompt.split("Generation context:\n", 1)[1])["search_directive"]
        for request in agent.requests
    ]
    assert [item["mode"] for item in directives] == ["explore", "repair", "refine"]
    assert directives[1]["target_candidate_id"] == "candidate-0001"
    assert directives[2]["parent_id"] == "candidate-0002"


def test_population_allocates_explore_diversify_and_recombine_roles(
    tmp_path: Path,
) -> None:
    root = tmp_path / "population"
    (root / "evolution").mkdir(parents=True)
    (root / "evolution" / "contract.json").write_text(
        json.dumps(_contract().to_dict()), encoding="utf-8"
    )
    agent = DirectiveAgent()
    result = PopulationStrategy(
        EvolutionContext(
            _contract(),
            root,
            AgentCandidateGenerator(agent, contract=_contract()),
            lambda path, contract: _report(float(path.read_text().count("print"))),
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

    directives = [
        json.loads(request.prompt.split("Generation context:\n", 1)[1])["search_directive"]
        for request in agent.requests
    ]
    assert result.evaluated_candidates == 3
    assert [item["mode"] for item in directives] == [
        "explore",
        "diversify",
        "recombine",
    ]
    assert directives[2]["parent_id"] == "candidate-0001"
    assert directives[2]["inspiration_ids"] == ["candidate-0002"]


def test_search_directive_is_reconstructed_after_generator_restart(tmp_path: Path) -> None:
    archive = (
        _candidate(1, tag="baseline"),
        _candidate(2, score=2, parent=1, tag="two-opt"),
        _candidate(3, score=1, parent=2, tag="unsafe-shortcut"),
    )
    request = _request(tmp_path, archive, archive[1], (archive[0],))

    before = _directive(AgentCandidateGenerator(DirectiveAgent(), contract=_contract()), request)
    after = _directive(AgentCandidateGenerator(DirectiveAgent(), contract=_contract()), request)

    assert before == after
    assert before["mode"] == "recombine"
    assert before["proven_change_tags"] == ["two-opt"]
    assert before["avoid_change_tags"] == ["unsafe-shortcut"]


def test_prompt_compaction_preserves_search_directive(tmp_path: Path) -> None:
    archive = tuple(
        _candidate(
            index,
            score=float(index),
            parent=index - 1 if index > 1 else None,
            tag=f"large-tag-{index:03d}",
        )
        for index in range(1, 101)
    )

    prompt = AgentCandidateGenerator(DirectiveAgent(), contract=_contract())._prompt(
        _request(tmp_path, archive, archive[-1])
    )
    context = json.loads(prompt.split("Generation context:\n", 1)[1])

    assert len(prompt.encode("utf-8")) <= 60 * 1024
    assert context["search_directive"]["mode"] == "refine"
    assert context["search_directive"]["parent_id"] == "candidate-0100"
