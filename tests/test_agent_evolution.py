import json
from pathlib import Path

import pytest

from famou.agent_evolution import (
    AgentCandidateEvaluator,
    AgentCandidateGenerator,
    AgentEvaluatorEnsemble,
    AgentPortfolioGenerator,
)
from famou.agent_loop import AgentLoopRuntime
from famou.agents import AgentResult, RuntimeAgentAdapter
from famou.algorithm import AlgorithmProblemContract, EvaluationReport
from famou.config import Config
from famou.controller import LocalController
from famou.evolution import (
    Candidate,
    EvolutionConfig,
    EvolutionContext,
    EvolutionError,
    LoopStrategy,
    PopulationStrategy,
)
from famou.runtime import MockRuntime, ModelTurn, ToolCall
from famou.tools import LocalToolRegistry


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


class EvidenceFixtureAgent(FixtureAgent):
    """Agent fixture that emits a redacted transcript/output file."""

    def __init__(self, *, symlink: bool = False, missing: bool = False) -> None:
        super().__init__()
        self.symlink = symlink
        self.missing = missing

    def run(self, request):
        self.requests.append(request)
        request.workspace.mkdir(parents=True, exist_ok=True)
        transcript = request.workspace / "session-transcript.jsonl"
        if not self.missing:
            transcript.write_text('{"role":"assistant","content":"[REDACTED]"}\n', encoding="utf-8")
        if self.symlink:
            link = request.workspace / "session-transcript.jsonl"
            link.unlink(missing_ok=True)
            link.symlink_to(request.workspace.parent / "outside.txt")
        return AgentResult(
            self.name,
            request.role,
            json.dumps({"source": "def solve():\n    return 1\n"}),
            artifacts=("session-transcript.jsonl",),
        )


class EvaluatorEvidenceFixtureAgent(EvaluatorFixtureAgent):
    def run(self, request):
        self.requests.append(request)
        request.workspace.mkdir(parents=True, exist_ok=True)
        (request.workspace / "session-transcript.jsonl").write_text(
            '{"role":"assistant","content":"evaluation"}\n', encoding="utf-8"
        )
        return AgentResult(
            self.name,
            request.role,
            self.response,
            artifacts=("session-transcript.jsonl",),
            status=self.status,
            error=self.error,
        )


class EventModel:
    name = "event-model"
    api_key = "api-secret"

    def __init__(self, turns: list[ModelTurn]) -> None:
        self.turns = list(turns)

    def complete(self, messages, tools=(), timeout=None):
        del messages, tools, timeout
        return self.turns.pop(0)

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


def test_agent_evolution_indexes_declared_transcript_through_observer(tmp_path: Path) -> None:
    contract = _contract()
    root = tmp_path / "run"
    (root / "evolution").mkdir(parents=True)
    (root / "evolution" / "contract.json").write_text(json.dumps(contract.to_dict()), encoding="utf-8")
    agent = EvidenceFixtureAgent()
    generator = AgentCandidateGenerator(agent, contract=contract)
    observed: list[tuple[str, dict[str, object]]] = []
    result = LoopStrategy(
        EvolutionContext(
            contract,
            root,
            generator,
            _report,
            EvolutionConfig(max_rounds=1),
            observe=lambda event, payload: observed.append((event, payload)),
        )
    ).run()
    assert result.best_candidate_id == "candidate-0001"
    artifacts = [payload for event, payload in observed if event == "agent_artifact"]
    assert artifacts and artifacts[0]["kind"] == "evolution_agent_transcript"
    assert artifacts[0]["path"].startswith("evolution/agent/generations/")
    assert artifacts[0]["size"] > 0


@pytest.mark.parametrize("mode", ["missing", "symlink"])
def test_agent_evolution_rejects_unsafe_declared_artifacts(tmp_path: Path, mode: str) -> None:
    contract = _contract()
    root = tmp_path / "run"
    (root / "evolution").mkdir(parents=True)
    (root / "evolution" / "contract.json").write_text(json.dumps(contract.to_dict()), encoding="utf-8")
    if mode == "symlink":
        (root / "outside.txt").write_text("outside", encoding="utf-8")
    agent = EvidenceFixtureAgent(**{mode: True})
    generator = AgentCandidateGenerator(agent, contract=contract)
    with pytest.raises(EvolutionError, match="artifact"):
        generator(
            type(
                "Request",
                (),
                {"iteration": 1, "parent": None, "inspirations": (), "archive": (), "workspace": root},
            )()
        )


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
    assert "return 1" in agent.requests[1].prompt


def test_agent_portfolio_rotates_explicit_solvers_deterministically(tmp_path: Path) -> None:
    contract = _contract("population")
    root = tmp_path / "run"
    (root / "evolution").mkdir(parents=True)
    (root / "evolution" / "contract.json").write_text(
        json.dumps(contract.to_dict()), encoding="utf-8"
    )
    first = FixtureAgent()
    second = FixtureAgent()
    generator = AgentPortfolioGenerator(
        (first, second), contract=contract, role="solver", required_capabilities=("read_files",)
    )
    context = EvolutionContext(
        contract,
        root,
        generator,
        lambda path, ignored: _report(path, contract),
        EvolutionConfig(strategy="population", max_rounds=2, population_size=2),
    )
    result = PopulationStrategy(context).run()
    assert result.status == "completed"
    assert len(first.requests) == 2
    assert len(second.requests) == 2
    assert all(request.role == "solver" for request in first.requests + second.requests)
    assert first.requests[0].task_id.endswith("0001")
    assert second.requests[0].task_id.endswith("0002")
    assert first.requests[1].task_id.endswith("0003")
    assert second.requests[1].task_id.endswith("0004")
    assert len({str(request.workspace) for request in first.requests + second.requests}) == 4


def test_agent_portfolio_requires_two_adapters() -> None:
    with pytest.raises(ValueError, match="at least two"):
        AgentPortfolioGenerator((FixtureAgent(),))


def test_agent_portfolio_member_failure_is_bounded(tmp_path: Path) -> None:
    generator = AgentPortfolioGenerator((FixtureAgent(failed=True), FixtureAgent()))
    with pytest.raises(EvolutionError, match="candidate generation returned failed"):
        generator(
            type(
                "Request",
                (),
                {
                    "iteration": 1,
                    "parent": None,
                    "inspirations": (),
                    "archive": (),
                    "workspace": tmp_path,
                },
            )()
        )


def test_agent_evaluator_ensemble_requires_consensus_and_uses_median(tmp_path: Path) -> None:
    contract = _contract()
    candidate = tmp_path / "candidate.py"
    candidate.write_text("def solve():\n    return 1\n", encoding="utf-8")
    responses = []
    for score in (1, 3, 2):
        responses.append(
            json.dumps(
                {
                    "schema_version": "1",
                    "evaluator_id": f"fixture-{score}",
                    "validity": 1,
                    "quality": score,
                    "combined_score": score,
                    "detailed_scores": {
                        "quality": {"value": score, "direction": "maximize"}
                    },
                    "error_info": [],
                }
            )
        )
    agents = [EvaluatorFixtureAgent(response) for response in responses]
    evaluator = AgentEvaluatorEnsemble(tuple(agents), required_capabilities=("read_files",))
    parsed = evaluator(candidate, contract)
    assert parsed.evaluator_id == "ensemble"
    assert parsed.validity == 1
    assert parsed.combined_score == 2.0
    assert parsed.quality == 2.0
    assert parsed.detailed_scores["quality"]["value"] == 2.0
    assert len({str(agent.requests[0].workspace) for agent in agents}) == 3

    disagreement = AgentEvaluatorEnsemble(
        (
            EvaluatorFixtureAgent(responses[0]),
            EvaluatorFixtureAgent(
                json.dumps(
                    {
                        "schema_version": "1",
                        "evaluator_id": "invalid",
                        "validity": 0,
                        "quality": None,
                        "combined_score": 0,
                        "detailed_scores": {},
                        "error_info": [{"code": "constraint", "message": "failed"}],
                    }
                )
            ),
        )
    )
    rejected = disagreement(candidate, contract)
    assert rejected.validity == 0
    assert rejected.combined_score == 0
    assert any(item["code"] == "evaluator_disagreement" for item in rejected.error_info)


def test_agent_evaluator_ensemble_fails_closed_on_member_error(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.py"
    candidate.write_text("def solve():\n    return 1\n", encoding="utf-8")
    evaluator = AgentEvaluatorEnsemble(
        (
            EvaluatorFixtureAgent(json.dumps(_report(candidate, _contract()))),
            EvaluatorFixtureAgent("", status="failed", error="fixture failure"),
        )
    )
    result = evaluator(candidate, _contract())
    assert result.validity == 0
    assert result.combined_score == 0
    assert any(item["code"] == "evaluator_failure" for item in result.error_info)


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


def test_agent_evaluator_indexes_transcript_artifact(tmp_path: Path) -> None:
    contract = _contract()
    candidate = tmp_path / "evolution" / "candidates" / "candidate-0001" / "candidate.py"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("def solve():\n    return 1\n", encoding="utf-8")
    agent = EvaluatorEvidenceFixtureAgent(json.dumps(_report(candidate, contract)))
    observed: list[tuple[str, dict[str, object]]] = []
    evaluator = AgentCandidateEvaluator(agent)
    evaluator.set_observer(lambda event, payload: observed.append((event, payload)))
    assert evaluator(candidate, contract).validity == 1
    artifacts = [payload for event, payload in observed if event == "agent_artifact"]
    assert artifacts and artifacts[0]["kind"] == "evolution_agent_transcript"
    assert artifacts[0]["path"].endswith(".agent-evaluator/session-transcript.jsonl")


def test_controller_indexes_runtime_agent_evidence_and_redacts_transcript(tmp_path: Path) -> None:
    contract = _contract()
    config = Config(tmp_path / ".famou")
    controller = LocalController(config, MockRuntime())
    run = controller.create_evolution_run(contract, workspace=tmp_path / "run")
    solver_model = EventModel(
        [
            ModelTurn(
                "",
                (ToolCall("1", "write_file", {"path": "solver-trace.txt", "content": "api-secret"}),),
            ),
            ModelTurn(json.dumps({"source": "def solve():\n    return 1\n"}), ()),
        ]
    )
    evaluator_model = EventModel(
        [
            ModelTurn(
                json.dumps(
                    {
                        "schema_version": "1",
                        "evaluator_id": "runtime-fixture",
                        "validity": 1,
                        "quality": 1,
                        "combined_score": 1,
                        "detailed_scores": {},
                        "error_info": [],
                    }
                ),
                (),
            )
        ]
    )
    generator = AgentCandidateGenerator(
        RuntimeAgentAdapter(
            AgentLoopRuntime(
                solver_model,
                tools=LocalToolRegistry(),
                max_steps=3,
                session_history=True,
            ),
            name="solver-loop",
            roles=("solver",),
        ),
        contract=contract,
    )
    evaluator = AgentCandidateEvaluator(
        RuntimeAgentAdapter(
            AgentLoopRuntime(evaluator_model, session_history=True),
            name="evaluator-loop",
            roles=("evaluator",),
        )
    )
    settled, result = controller.run_evolution(
        run.id,
        contract,
        generator,
        evaluator,
        EvolutionConfig(max_rounds=1),
    )
    assert settled.status.value == "succeeded"
    assert result.best_candidate_id == "candidate-0001"
    artifacts = controller.store.list_artifacts(run.id)
    transcripts = [item for item in artifacts if item["kind"] == "evolution_agent_transcript"]
    assert len(transcripts) == 2
    assert all(item["path"].startswith("evolution/") for item in transcripts)
    event_types = [item["type"] for item in controller.store.list_events(run.id)]
    assert "evolution_agent_artifact" in event_types
    assert "agent_model_turn" in event_types
    assert "agent_tool_result" in event_types
    transcript_text = "\n".join(
        (Path(run.workspace) / item["path"]).read_text(encoding="utf-8") for item in transcripts
    )
    assert "api-secret" not in transcript_text
    assert "api-secret" not in str(controller.store.list_events(run.id))


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
