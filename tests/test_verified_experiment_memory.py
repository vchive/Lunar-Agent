import json
from pathlib import Path

import pytest

from famou.agent_evolution import AgentCandidateGenerator
from famou.agents import AgentResult
from famou.algorithm import AlgorithmProblemContract, EvaluationReport
from famou.evolution import (
    Candidate,
    CandidateArchive,
    EvolutionConfig,
    EvolutionContext,
    EvolutionError,
    LoopStrategy,
    PopulationStrategy,
)


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "experiment-memory-fixture",
            "problem_type": "routing",
            "statement": "Minimize route distance.",
            "inputs": [
                {"path": "items.csv", "format": "csv", "fields": {"id": "item ID"}}
            ],
            "decision_variables": ["route order"],
            "objective": {"name": "distance", "direction": "minimize"},
            "hard_constraints": [],
            "soft_constraints": [],
            "success_criteria": ["Return a valid route."],
            "deliverables": ["Route program."],
            "evolution": {"strategy": "loop", "max_rounds": 3, "stagnation_rounds": 10},
        }
    )


def _report(score: float, distance: float, *, valid: int = 1) -> EvaluationReport:
    return EvaluationReport.from_dict(
        {
            "schema_version": "1",
            "evaluator_id": "experiment-fixture",
            "validity": valid,
            "quality": score if valid else None,
            "combined_score": score if valid else 0,
            "detailed_scores": {
                "distance": {"value": distance, "direction": "minimize"}
            },
            "error_info": []
            if valid
            else [{"code": "invalid-route", "message": "route is infeasible"}],
        }
    )


def _experiment(tag: str, hypothesis: str | None = None) -> dict[str, object]:
    return {
        "schema_version": "1",
        "hypothesis": hypothesis or f"Changing {tag} should reduce distance.",
        "change_tags": [tag],
        "target_metrics": [{"metric": "distance", "direction": "decrease"}],
    }


def _context(prompt: str) -> dict[str, object]:
    return json.loads(prompt.split("Generation context:\n", 1)[1])


class ExperimentAgent:
    name = "experiment-agent"
    roles = frozenset({"solver"})
    capabilities = frozenset({"read_files"})

    def __init__(self) -> None:
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        tag = ("greedy-seed", "two-opt", "random-restart")[len(self.requests) - 1]
        return AgentResult(
            self.name,
            request.role,
            json.dumps(
                {
                    "source": f"# {tag}\nprint({len(self.requests)})\n",
                    "metadata": {
                        "outcome": "MODEL_CLAIM_MUST_NOT_WIN",
                        "combined_score_delta": 999,
                    },
                    "experiment": _experiment(tag),
                }
            ),
        )

    def cancel(self):
        return None

    def process_info(self):
        return (None, None)

    def set_process_observer(self, observer):
        del observer


def _request(root: Path, archive: tuple[Candidate, ...]):
    return type(
        "Request",
        (),
        {
            "iteration": len(archive) + 1,
            "parent": archive[-1] if archive else None,
            "inspirations": (),
            "archive": archive,
            "workspace": root,
        },
    )()


def test_loop_derives_experiment_outcomes_from_evaluator_and_resume(
    tmp_path: Path,
) -> None:
    root = tmp_path / "run"
    (root / "evolution").mkdir(parents=True)
    (root / "evolution" / "contract.json").write_text(
        json.dumps(_contract().to_dict()), encoding="utf-8"
    )
    agent = ExperimentAgent()
    reports = iter((_report(1, 100), _report(3, 80), _report(2, 90)))
    result = LoopStrategy(
        EvolutionContext(
            _contract(),
            root,
            AgentCandidateGenerator(agent, contract=_contract()),
            lambda path, contract: next(reports),
            EvolutionConfig(max_rounds=3, stagnation_rounds=10),
        )
    ).run()

    assert result.best_candidate_id == "candidate-0002"
    second_memory = _context(agent.requests[1].prompt)["experiment_memory"]
    assert [card["outcome"] for card in second_memory["recent"]] == ["seed"]
    third_memory = _context(agent.requests[2].prompt)["experiment_memory"]
    assert [card["outcome"] for card in third_memory["recent"]] == [
        "seed",
        "improved",
    ]
    improved = third_memory["recent"][1]
    assert improved["combined_score_delta"] == 2
    assert improved["metrics"]["distance"] == {
        "before": 100.0,
        "after": 80.0,
        "delta": -20.0,
        "direction": "minimize",
        "improved": True,
    }
    assert "MODEL_CLAIM_MUST_NOT_WIN" not in json.dumps(third_memory)
    assert "999" not in json.dumps(third_memory)

    archive = tuple(CandidateArchive(root).records())
    resumed = AgentCandidateGenerator(ExperimentAgent(), contract=_contract())._prompt(
        _request(root, archive)
    )
    memory = _context(resumed)["experiment_memory"]
    assert [card["outcome"] for card in memory["recent"]] == [
        "seed",
        "improved",
        "regressed",
    ]
    assert memory["tag_outcomes"] == {
        "greedy-seed": {"seed": 1},
        "random-restart": {"regressed": 1},
        "two-opt": {"improved": 1},
    }


def test_invalid_experiment_never_claims_improvement(tmp_path: Path) -> None:
    parent = Candidate(
        "candidate-0001",
        "evolution/candidates/candidate-0001/candidate.py",
        None,
        0,
        1,
        "loop",
        None,
        _report(1, 100),
        {"experiment": _experiment("seed")},
    )
    child = Candidate(
        "candidate-0002",
        "evolution/candidates/candidate-0002/candidate.py",
        parent.candidate_id,
        1,
        2,
        "loop",
        None,
        _report(0, 50, valid=0),
        {"experiment": _experiment("unsafe-shortcut")},
    )

    prompt = AgentCandidateGenerator(ExperimentAgent(), contract=_contract())._prompt(
        _request(tmp_path, (parent, child))
    )
    invalid = _context(prompt)["experiment_memory"]["recent"][1]
    assert invalid["outcome"] == "invalid"
    assert invalid["combined_score_delta"] is None
    assert invalid["metrics"]["distance"]["improved"] is True


def test_unchanged_outcome_and_only_declared_metric_are_projected(tmp_path: Path) -> None:
    before = _report(2, 90)
    after = EvaluationReport.from_dict(
        {
            **_report(2, 90).to_dict(),
            "detailed_scores": {
                "distance": {"value": 90, "direction": "minimize"},
                "unrelated": {"value": 999, "direction": "maximize"},
            },
        }
    )
    parent = Candidate(
        "candidate-0001",
        "evolution/candidates/candidate-0001/candidate.py",
        None,
        0,
        1,
        "loop",
        None,
        before,
        {"experiment": _experiment("seed")},
    )
    child = Candidate(
        "candidate-0002",
        "evolution/candidates/candidate-0002/candidate.py",
        parent.candidate_id,
        1,
        2,
        "loop",
        None,
        after,
        {"experiment": _experiment("no-op")},
    )

    prompt = AgentCandidateGenerator(ExperimentAgent(), contract=_contract())._prompt(
        _request(tmp_path, (parent, child))
    )
    card = _context(prompt)["experiment_memory"]["recent"][1]
    assert card["outcome"] == "unchanged"
    assert card["combined_score_delta"] == 0
    assert set(card["metrics"]) == {"distance"}


def test_agent_experiment_parser_is_strict_bounded_and_backward_compatible() -> None:
    generator = AgentCandidateGenerator(ExperimentAgent(), contract=_contract())
    legacy = generator._draft("print('legacy')")
    assert "experiment" not in legacy.metadata

    secret = generator._draft(
        json.dumps(
            {
                "source": "print('safe')",
                "experiment": _experiment(
                    "two-opt", "Try sk-abcdefghijklmnop without retaining the credential."
                ),
            }
        )
    )
    assert "sk-abcdefghijklmnop" not in json.dumps(secret.metadata)
    assert "[REDACTED]" in json.dumps(secret.metadata)

    mutations = [
        {**_experiment("two-opt"), "outcome": "improved"},
        {**_experiment("two-opt"), "change_tags": ["../unsafe"]},
        {**_experiment("two-opt"), "hypothesis": "x" * 2_000},
        {**_experiment("two-opt"), "target_metrics": []},
    ]
    for experiment in mutations:
        with pytest.raises(EvolutionError, match="experiment"):
            generator._draft(json.dumps({"source": "print(1)", "experiment": experiment}))


def test_population_and_large_archive_share_bounded_experiment_memory(
    tmp_path: Path,
) -> None:
    contract = AlgorithmProblemContract.from_dict(
        {
            **_contract().to_dict(),
            "evolution": {
                "strategy": "population",
                "max_rounds": 1,
                "stagnation_rounds": 10,
            },
        }
    )
    root = tmp_path / "population"
    (root / "evolution").mkdir(parents=True)
    (root / "evolution" / "contract.json").write_text(
        json.dumps(contract.to_dict()), encoding="utf-8"
    )

    class PopulationExperimentAgent(ExperimentAgent):
        def run(self, request):
            self.requests.append(request)
            return AgentResult(
                self.name,
                request.role,
                json.dumps(
                    {
                        "source": f"print({len(self.requests)})",
                        "experiment": _experiment(f"tag-{len(self.requests):02d}"),
                    }
                ),
            )

    agent = PopulationExperimentAgent()
    result = PopulationStrategy(
        EvolutionContext(
            contract,
            root,
            AgentCandidateGenerator(agent, contract=contract),
            lambda path, ignored: _report(float(path.read_text().count("print")), 100),
            EvolutionConfig(
                strategy="population",
                max_rounds=1,
                stagnation_rounds=10,
                population_size=2,
                offspring_per_iteration=2,
                num_islands=2,
            ),
        )
    ).run()

    assert result.evaluated_candidates == 4
    final_memory = _context(agent.requests[-1].prompt)["experiment_memory"]
    assert final_memory["recent"]
    assert all("plan" in card and "outcome" in card for card in final_memory["recent"])

    archive: list[Candidate] = []
    for index in range(100):
        archive.append(
            Candidate(
                f"candidate-{index + 1:04d}",
                f"evolution/candidates/candidate-{index + 1:04d}/candidate.py",
                f"candidate-{index:04d}" if index else None,
                index,
                index + 1,
                "population",
                index % 2,
                _report(index + 1, 100 - index),
                {"experiment": _experiment(f"large-tag-{index:03d}")},
            )
        )
    prompt = AgentCandidateGenerator(PopulationExperimentAgent(), contract=contract)._prompt(
        _request(root, tuple(archive))
    )
    memory = _context(prompt)["experiment_memory"]
    assert len(memory["recent"]) == 8
    assert len(memory["tag_outcomes"]) <= 32
    assert len(prompt.encode()) <= 60 * 1024
