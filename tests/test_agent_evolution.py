import json
from pathlib import Path

import pytest

from famou.agent_evolution import AgentCandidateEvaluator, AgentCandidateGenerator
from famou.agents import AgentResult
from famou.algorithm import AlgorithmProblemContract, EvaluationReport
from famou.evolution import (
    Candidate,
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


class EvaluatorFixtureAgent:
    name = "evaluator-fixture"
    roles = frozenset({"evaluator"})
    capabilities = frozenset({"read_files"})

    def __init__(self, response: str, *, status: str = "succeeded", error: str | None = None) -> None:
        self.response = response
        self.status = status
        self.error = error
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        return AgentResult(
            self.name,
            request.role,
            self.response,
            status=self.status,
            error=self.error,
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


def test_agent_generator_receives_verified_evaluation_feedback(tmp_path: Path) -> None:
    contract = _contract()
    root = tmp_path / "run"
    (root / "evolution").mkdir(parents=True)
    (root / "evolution" / "contract.json").write_text(
        json.dumps(contract.to_dict()), encoding="utf-8"
    )
    agent = FixtureAgent()
    evaluations = iter(
        [
            {
                "schema_version": "1",
                "evaluator_id": "fixture",
                "validity": 0,
                "quality": None,
                "combined_score": 0,
                "detailed_scores": {
                    "feasibility": {"value": 0, "direction": "maximize"}
                },
                "error_info": [
                    {"code": "constraint_violation", "message": "serve-all failed"}
                ],
            },
            {
                "schema_version": "1",
                "evaluator_id": "fixture",
                "validity": 1,
                "quality": 1,
                "combined_score": 1,
                "detailed_scores": {
                    "quality": {"value": 1, "direction": "maximize"}
                },
                "error_info": [],
            },
        ]
    )

    def evaluate(path, ignored_contract):
        del path, ignored_contract
        return next(evaluations)

    context = EvolutionContext(
        contract, root, AgentCandidateGenerator(agent, contract=contract), evaluate,
        EvolutionConfig(max_rounds=2, stagnation_rounds=10),
    )
    result = LoopStrategy(context).run()
    assert result.best_candidate_id == "candidate-0002"
    assert len(agent.requests) == 2
    assert "constraint_violation" in agent.requests[1].prompt
    assert "serve-all failed" in agent.requests[1].prompt
    assert "return 1" not in agent.requests[1].prompt


def test_agent_generation_feedback_is_bounded_and_hides_evaluation_errors(tmp_path: Path) -> None:
    detailed_scores = {
        f"metric-{index:02d}": {"value": index, "direction": "maximize"}
        for index in range(12)
    }
    errors = [
        {"code": f"constraint-{index:02d}", "message": f"failure {index}"}
        for index in range(12)
    ]
    errors[0] = {"code": "evaluation_error", "message": "raw adapter exception should not leak"}
    report = EvaluationReport.from_dict(
        {
            "schema_version": "1",
            "evaluator_id": "fixture",
            "validity": 0,
            "quality": None,
            "combined_score": 0,
            "detailed_scores": detailed_scores,
            "error_info": errors,
        }
    )
    candidate = Candidate(
        candidate_id="candidate-0001",
        code_path="evolution/candidates/candidate-0001/candidate.py",
        parent_id=None,
        generation=0,
        iteration=1,
        strategy="loop",
        island_id=None,
        evaluation=report,
        metadata={},
    )
    agent = FixtureAgent()
    generator = AgentCandidateGenerator(agent, contract=_contract())
    prompt = generator._prompt(
        type(
            "Request",
            (),
            {
                "iteration": 2,
                "parent": None,
                "inspirations": (),
                "archive": (candidate,),
                "workspace": tmp_path,
            },
        )()
    )
    encoded = json.loads(prompt.split("Generation context:\n", 1)[1])
    feedback = encoded["archive"][0]["evaluation_feedback"]
    assert len(feedback["detailed_scores"]) == 8
    assert len(feedback["errors"]) == 8
    assert "candidate.py" in prompt
    assert "def solve" not in prompt
    assert "raw adapter exception should not leak" not in prompt


def test_agent_evaluator_parses_strict_report_and_uses_candidate_workspace(tmp_path: Path) -> None:
    contract = _contract()
    candidate = tmp_path / "candidates" / "candidate-0001" / "candidate.py"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("def solve():\n    return 1\n", encoding="utf-8")
    report = json.dumps(_report(candidate, contract))
    agent = EvaluatorFixtureAgent(report)
    evaluator = AgentCandidateEvaluator(agent, required_capabilities=("read_files",))
    parsed = evaluator(candidate, contract)
    assert parsed.validity == 1
    assert agent.requests[0].workspace.is_dir()
    assert str(candidate) in agent.requests[0].prompt


def test_agent_evaluator_rejects_malformed_or_failed_reports(tmp_path: Path) -> None:
    contract = _contract()
    candidate = tmp_path / "candidate.py"
    candidate.write_text("def solve():\n    return 1\n", encoding="utf-8")
    malformed = AgentCandidateEvaluator(EvaluatorFixtureAgent("not json"))
    with pytest.raises(EvolutionError, match="not valid JSON"):
        malformed(candidate, contract)
    failed = AgentCandidateEvaluator(
        EvaluatorFixtureAgent("", status="failed", error="evaluator failed")
    )
    with pytest.raises(EvolutionError, match="returned failed"):
        failed(candidate, contract)
