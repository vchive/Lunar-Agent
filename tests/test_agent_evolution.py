import json
from pathlib import Path

import pytest

from famou.agent_evolution import AgentCandidateGenerator
from famou.agents import AgentResult
from famou.algorithm import AlgorithmProblemContract
from famou.evolution import (
    EvolutionConfig,
    EvolutionContext,
    EvolutionError,
    LoopStrategy,
    PopulationStrategy,
)


def _contract(strategy: str = "loop") -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "agent-evolution-fixture",
            "problem_type": "routing",
            "statement": "Improve a route with no constraint violations.",
            "inputs": [{"path": "items.csv", "format": "csv", "fields": {"id": "item id"}}],
            "decision_variables": ["route order"],
            "objective": {"name": "quality", "direction": "maximize"},
            "hard_constraints": [
                {
                    "id": "serve-all",
                    "description": "Serve every item.",
                    "source": "user_confirmed",
                    "verification": "independent",
                }
            ],
            "success_criteria": ["All items are served."],
            "deliverables": ["A route program."],
            "evolution": {"strategy": strategy, "max_rounds": 2, "stagnation_rounds": 10},
        }
    )


class FixtureAgent:
    name = "solver-fixture"
    roles = frozenset({"solver"})
    capabilities = frozenset({"read_files", "write_artifacts"})

    def __init__(self, *, failed: bool = False) -> None:
        self.failed = failed
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        if self.failed:
            return AgentResult(self.name, request.role, "", status="failed", error="fixture failure")
        return AgentResult(
            self.name,
            request.role,
            json.dumps({"source": f"def solve():\n    return {len(self.requests)}\n"}),
        )

    def cancel(self):
        return None

    def process_info(self):
        return (None, None)

    def set_process_observer(self, observer):
        del observer


def _report(path: Path, contract: AlgorithmProblemContract) -> dict[str, object]:
    del contract
    score = float(path.read_text().count("return"))
    return {
        "schema_version": "1",
        "evaluator_id": "fixture",
        "validity": 1,
        "quality": score,
        "combined_score": score,
        "detailed_scores": {"quality": {"value": score, "direction": "maximize"}},
        "error_info": [],
    }


def test_agent_generator_injects_bounded_context_and_returns_draft(tmp_path: Path) -> None:
    contract = _contract()
    root = tmp_path / "run"
    (root / "evolution").mkdir(parents=True)
    (root / "evolution" / "contract.json").write_text(json.dumps(contract.to_dict()), encoding="utf-8")
    agent = FixtureAgent()
    generator = AgentCandidateGenerator(agent, contract=contract, required_capabilities=("read_files",))
    context = EvolutionContext(contract, root, generator, _report, EvolutionConfig(max_rounds=1))
    result = LoopStrategy(context).run()
    assert result.best_candidate_id == "candidate-0001"
    assert len(agent.requests) == 1
    assert "Improve a route" in agent.requests[0].prompt
    assert agent.requests[0].workspace.is_dir()
    assert (root / "evolution" / "candidates" / "candidate-0001" / "candidate.py").is_file()


def test_agent_generator_works_with_population_and_rejected_agent_never_becomes_candidate(
    tmp_path: Path,
) -> None:
    contract = _contract("population")
    root = tmp_path / "run"
    (root / "evolution").mkdir(parents=True)
    (root / "evolution" / "contract.json").write_text(json.dumps(contract.to_dict()), encoding="utf-8")
    agent = FixtureAgent()
    generator = AgentCandidateGenerator(agent, contract=contract)
    context = EvolutionContext(
        contract,
        root,
        generator,
        lambda path, _: {**_report(path, contract), "validity": 0, "combined_score": 0, "quality": None,
                         "error_info": [{"code": "rejected", "message": "fixture"}]},
        EvolutionConfig(strategy="population", max_rounds=1, population_size=2),
    )
    result = PopulationStrategy(context).run()
    assert result.best_candidate_id is None
    assert result.valid_candidates == 0


def test_agent_generator_fails_closed_on_failed_agent(tmp_path: Path) -> None:
    contract = _contract()
    agent = FixtureAgent(failed=True)
    generator = AgentCandidateGenerator(agent, contract=contract)
    with pytest.raises(EvolutionError, match="candidate generation returned failed"):
        generator(
            type(
                "Request",
                (),
                {"iteration": 1, "parent": None, "inspirations": (), "archive": (), "workspace": tmp_path},
            )()
        )
