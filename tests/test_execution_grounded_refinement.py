import hashlib
import json
from pathlib import Path

import pytest

from famou.agent_evolution import AgentCandidateGenerator
from famou.agents import AgentResult
from famou.algorithm import AlgorithmProblemContract, EvaluationReport
from famou.evolution import (
    Candidate,
    CandidateArchive,
    CandidateExecution,
    CandidateInputArtifact,
    ContractCandidateRunner,
    EvolutionConfig,
    EvolutionContext,
    ExecutionAwareCandidateEvaluator,
    LoopStrategy,
    PopulationStrategy,
)


def _contract(strategy: str = "loop") -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "refine-routes",
            "problem_type": "routing",
            "statement": "Assign each order and write the declared route table.",
            "inputs": [
                {"path": "orders.csv", "format": "csv", "fields": {"id": "order ID"}}
            ],
            "decision_variables": ["route per order"],
            "objective": {"name": "quality", "direction": "maximize"},
            "hard_constraints": [],
            "soft_constraints": [],
            "success_criteria": ["Every order is assigned."],
            "deliverables": ["route table"],
            "outputs": [
                {
                    "path": "output/routes.csv",
                    "format": "csv",
                    "fields": ["item_id", "route_id"],
                    "required": True,
                }
            ],
            "evolution": {"strategy": strategy, "max_rounds": 2, "stagnation_rounds": 10},
        }
    )


def _report(*, valid: int = 1, score: float = 1.0, message: str = "") -> EvaluationReport:
    return EvaluationReport.from_dict(
        {
            "schema_version": "1",
            "evaluator_id": "refinement-fixture",
            "validity": valid,
            "quality": score if valid else None,
            "combined_score": score if valid else 0,
            "detailed_scores": {
                "quality": {"value": score if valid else 0, "direction": "maximize"}
            },
            "error_info": []
            if valid
            else [{"code": "evaluation_error", "message": message or "private traceback"}],
        }
    )


def _candidate(candidate_id: str = "candidate-0001") -> Candidate:
    return Candidate(
        candidate_id=candidate_id,
        code_path=f"evolution/candidates/{candidate_id}/candidate.py",
        parent_id=None,
        generation=0,
        iteration=1,
        strategy="loop",
        island_id=None,
        evaluation=_report(valid=0),
    )


def _request(workspace: Path, candidate: Candidate, *, inspirations=(), archive=None):
    return type(
        "Request",
        (),
        {
            "iteration": 2,
            "parent": candidate,
            "inspirations": tuple(inspirations),
            "archive": tuple(archive if archive is not None else (candidate,)),
            "workspace": workspace,
        },
    )()


def _context(prompt: str) -> dict[str, object]:
    return json.loads(prompt.split("Generation context:\n", 1)[1])


class RepairAgent:
    name = "repair-agent"
    roles = frozenset({"solver"})
    capabilities = frozenset({"read_files", "write_artifacts"})

    def __init__(self) -> None:
        self.requests = []

    def run(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            return AgentResult(
                self.name,
                request.role,
                "API_KEY = 'sk-abcdefghijklmnop'\n# first attempt intentionally has no output\n",
            )
        context = _context(request.prompt)
        previous = context["parent"] or context["archive"][-1]
        evidence = previous["refinement_evidence"]
        assert evidence["execution"]["error"] == "output_contract_invalid"
        assert "first attempt intentionally has no output" in evidence["source"]["excerpt"]
        return AgentResult(
            self.name,
            request.role,
            "from pathlib import Path\n"
            "rows = Path('data/raw/orders.csv').read_text().splitlines()[1:]\n"
            "Path('output').mkdir(exist_ok=True)\n"
            "body = 'item_id,route_id\\n' + ''.join(f'{row},r1\\n' for row in rows)\n"
            "Path('output/routes.csv').write_text(body)\n",
        )

    def cancel(self):
        return None

    def process_info(self):
        return (None, None)

    def set_process_observer(self, observer):
        del observer


def test_loop_repairs_candidate_from_persisted_execution_evidence(tmp_path: Path) -> None:
    contract = _contract()
    root = tmp_path / "run"
    source = root / "data" / "raw" / "orders.csv"
    source.parent.mkdir(parents=True)
    source.write_text("id\nraw-input-row-must-not-enter-prompt\n", encoding="utf-8")
    descriptor = CandidateInputArtifact(
        "data/raw/orders.csv",
        source.stat().st_size,
        hashlib.sha256(source.read_bytes()).hexdigest(),
    )
    (root / "evolution").mkdir()
    (root / "evolution" / "contract.json").write_text(
        json.dumps(contract.to_dict()), encoding="utf-8"
    )
    agent = RepairAgent()
    generator = AgentCandidateGenerator(agent, contract=contract, inputs=(descriptor,))
    evaluator_calls = {"count": 0}

    def evaluator(candidate_path, ignored_contract):
        del candidate_path, ignored_contract
        evaluator_calls["count"] += 1
        return _report(score=3)

    grounded = ExecutionAwareCandidateEvaluator(
        ContractCandidateRunner(root, (descriptor,), contract.outputs, timeout_seconds=2),
        evaluator,
    )
    result = LoopStrategy(
        EvolutionContext(
            contract,
            root,
            generator,
            grounded,
            EvolutionConfig(max_rounds=2, stagnation_rounds=10),
        )
    ).run()

    assert result.best_candidate_id == "candidate-0002"
    assert result.valid_candidates == 1
    assert evaluator_calls["count"] == 1
    second_prompt = agent.requests[1].prompt
    assert "output_contract_invalid" in second_prompt
    assert "first attempt intentionally has no output" in second_prompt
    assert "sk-abcdefghijklmnop" not in second_prompt
    assert "[REDACTED]" in second_prompt
    assert "raw-input-row-must-not-enter-prompt" not in second_prompt
    previous = _context(second_prompt)["parent"] or _context(second_prompt)["archive"][-1]
    feedback = previous["evaluation_feedback"]
    assert "private traceback" not in json.dumps(feedback)

    # A fresh generator reconstructs the same refinement evidence from the durable archive.
    reloaded = CandidateArchive(root).records()[0]
    resumed_prompt = AgentCandidateGenerator(RepairAgent(), contract=contract)._prompt(
        _request(root, reloaded)
    )
    assert (
        _context(resumed_prompt)["parent"]["refinement_evidence"]
        == previous["refinement_evidence"]
    )


def test_success_evidence_exposes_output_metadata_but_not_contents(tmp_path: Path) -> None:
    candidate = _candidate()
    root = tmp_path / "run"
    candidate_path = root / candidate.code_path
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_text("print('safe source')\n", encoding="utf-8")
    output = candidate_path.parent / "output" / "routes.csv"
    output.parent.mkdir()
    output.write_text("raw-output-body-must-not-enter-prompt", encoding="utf-8")
    (candidate_path.parent / "execution.json").write_text(
        json.dumps(
            CandidateExecution(
                "succeeded",
                0,
                7,
                stdout="raw-input-row-must-not-enter-prompt",
                stderr="raw-output-body-must-not-enter-prompt",
                artifacts=("output/routes.csv",),
            ).to_dict()
        ),
        encoding="utf-8",
    )

    prompt = AgentCandidateGenerator(RepairAgent(), contract=_contract())._prompt(
        _request(root, candidate)
    )
    evidence = _context(prompt)["parent"]["refinement_evidence"]
    assert evidence["execution"]["status"] == "succeeded"
    assert evidence["execution"]["stdout_bytes"] > 0
    assert evidence["execution"]["stderr_bytes"] > 0
    assert evidence["verified_outputs"] == [
        {
            "path": "output/routes.csv",
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "size": output.stat().st_size,
        }
    ]
    assert "raw-output-body-must-not-enter-prompt" not in prompt
    assert "raw-input-row-must-not-enter-prompt" not in prompt


@pytest.mark.parametrize(
    ("mode", "reason"),
    [
        ("source_symlink", "source_unavailable"),
        ("malformed_execution", "execution_unavailable"),
        ("oversized_execution", "execution_unavailable"),
        ("artifact_symlink", "artifact_unavailable"),
    ],
)
def test_unsafe_refinement_evidence_degrades_without_leaking_exception(
    tmp_path: Path, mode: str, reason: str
) -> None:
    candidate = _candidate()
    root = tmp_path / "run"
    candidate_path = root / candidate.code_path
    candidate_path.parent.mkdir(parents=True)
    candidate_path.write_text("print('safe')\n", encoding="utf-8")
    execution = candidate_path.parent / "execution.json"
    execution.write_text(
        json.dumps(CandidateExecution("failed", 1, 2, error="known_failure").to_dict()),
        encoding="utf-8",
    )
    if mode == "source_symlink":
        outside = tmp_path / "outside.py"
        outside.write_text("do_not_leak_outside_source", encoding="utf-8")
        candidate_path.unlink()
        candidate_path.symlink_to(outside)
    elif mode == "malformed_execution":
        execution.write_text("private malformed exception marker {", encoding="utf-8")
    elif mode == "oversized_execution":
        execution.write_text("x" * (64 * 1024 + 1), encoding="utf-8")
    else:
        outside = tmp_path / "outside-output"
        outside.write_text("do_not_leak_outside_output", encoding="utf-8")
        output = candidate_path.parent / "output"
        output.mkdir()
        (output / "routes.csv").symlink_to(outside)
        execution.write_text(
            json.dumps(
                CandidateExecution(
                    "succeeded", 0, 2, artifacts=("output/routes.csv",)
                ).to_dict()
            ),
            encoding="utf-8",
        )

    prompt = AgentCandidateGenerator(RepairAgent(), contract=_contract())._prompt(
        _request(root, candidate)
    )
    evidence = _context(prompt)["parent"]["refinement_evidence"]
    assert evidence["unavailable_reason"] == reason
    assert "do_not_leak" not in prompt
    assert "private malformed exception marker" not in prompt


def test_refinement_source_is_bounded_and_arbitrary_runner_error_is_generic(
    tmp_path: Path,
) -> None:
    candidate = _candidate()
    root = tmp_path / "run"
    candidate_path = root / candidate.code_path
    candidate_path.parent.mkdir(parents=True)
    source = "# visible\n" + ("x" * 3_000) + "source-tail-must-be-truncated"
    candidate_path.write_text(source, encoding="utf-8")
    (candidate_path.parent / "execution.json").write_text(
        json.dumps(
            CandidateExecution(
                "failed",
                1,
                2,
                error="raw input row and private runner exception must not leak",
            ).to_dict()
        ),
        encoding="utf-8",
    )

    prompt = AgentCandidateGenerator(RepairAgent(), contract=_contract())._prompt(
        _request(root, candidate)
    )
    evidence = _context(prompt)["parent"]["refinement_evidence"]
    assert evidence["source"]["truncated"] is True
    assert len(evidence["source"]["excerpt"].encode()) <= 2 * 1024
    assert "source-tail-must-be-truncated" not in prompt
    assert evidence["execution"]["error"] == "candidate_execution_failed"
    assert "private runner exception" not in prompt


def test_population_parent_and_inspiration_share_refinement_envelope(tmp_path: Path) -> None:
    contract = _contract("population")
    root = tmp_path / "run"
    (root / "evolution").mkdir(parents=True)
    (root / "evolution" / "contract.json").write_text(
        json.dumps(contract.to_dict()), encoding="utf-8"
    )
    class PopulationAgent(RepairAgent):
        def run(self, request):
            self.requests.append(request)
            return AgentResult(
                self.name,
                request.role,
                f"def candidate_{len(self.requests)}():\n    return {len(self.requests)}\n",
            )

    agent = PopulationAgent()
    generator = AgentCandidateGenerator(agent, contract=contract)
    result = PopulationStrategy(
        EvolutionContext(
            contract,
            root,
            generator,
            lambda path, ignored: _report(score=float(path.stat().st_size)),
            EvolutionConfig(
                strategy="population",
                max_rounds=1,
                population_size=2,
                offspring_per_iteration=1,
                stagnation_rounds=10,
                rng_seed=3,
            ),
        )
    ).run()
    assert result.status == "completed"
    offspring = _context(agent.requests[2].prompt)
    assert offspring["parent"]["refinement_evidence"]["source"]["excerpt"]
    assert offspring["inspirations"][0]["refinement_evidence"]["source"]["excerpt"]
    assert (
        offspring["parent"]["refinement_evidence"]["schema_version"]
        == offspring["inspirations"][0]["refinement_evidence"]["schema_version"]
        == "1"
    )
