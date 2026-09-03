import hashlib
import json
import stat
from pathlib import Path

import pytest

from famou.agent_evolution import AgentCandidateGenerator
from famou.agents import AgentResult
from famou.algorithm import AlgorithmProblemContract
from famou.evaluator_bundle import EvaluatorBundleError, SolverScoringContract


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "solver-scoring-fixture",
            "problem_type": "routing",
            "statement": "Assign every order and minimize total cost.",
            "inputs": [
                {
                    "path": "orders.csv",
                    "format": "csv",
                    "fields": {"id": "order ID"},
                    "key": "id",
                }
            ],
            "decision_variables": ["route per order"],
            "objective": {"name": "cost", "direction": "minimize"},
            "hard_constraints": [
                {
                    "id": "serve-all",
                    "description": "Every order appears exactly once.",
                    "source": "user_confirmed",
                    "verification": "independent",
                    "result_fields": ["item_id"],
                }
            ],
            "soft_constraints": [
                {
                    "id": "balance-routes",
                    "description": "Prefer balanced route sizes.",
                    "source": "explicit_assumption",
                    "verification": "partial",
                    "result_fields": ["route_id"],
                }
            ],
            "success_criteria": ["All orders are assigned."],
            "deliverables": ["Route table."],
            "assumptions": ["Costs use the declared input unit."],
            "outputs": [
                {
                    "path": "output/routes.csv",
                    "format": "csv",
                    "fields": ["item_id", "route_id", "cost"],
                    "required": True,
                }
            ],
        }
    )


class CaptureAgent:
    name = "scoring-capture"
    roles = frozenset({"solver"})
    capabilities = frozenset({"read_files"})

    def __init__(self) -> None:
        self.requests = []
        self.scoring_files: dict[str, bytes] = {}
        self.scoring_modes: dict[str, int] = {}

    def run(self, request):
        self.requests.append(request)
        scoring = request.workspace / "scoring"
        self.scoring_files = {
            path.name: path.read_bytes() for path in sorted(scoring.iterdir())
        }
        self.scoring_modes = {
            path.name: stat.S_IMODE(path.stat().st_mode)
            for path in sorted(scoring.iterdir())
        }
        return AgentResult(self.name, request.role, "print('candidate')\n")

    def cancel(self):
        return None

    def process_info(self):
        return (None, None)

    def set_process_observer(self, observer):
        del observer


def _request(root: Path):
    return type(
        "Request",
        (),
        {
            "iteration": 1,
            "parent": None,
            "inspirations": (),
            "archive": (),
            "workspace": root,
        },
    )()


def _prompt_context(prompt: str) -> dict[str, object]:
    return json.loads(prompt.split("Generation context:\n", 1)[1])


def test_persisted_contract_projection_keeps_all_solver_rules(tmp_path: Path) -> None:
    contract = _contract()
    root = tmp_path / "run"
    path = root / "evolution" / "contract.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(contract.to_dict()), encoding="utf-8")
    generator = AgentCandidateGenerator(CaptureAgent(), contract=contract)

    context = _prompt_context(generator._prompt(_request(root)))

    projected = context["contract"]
    assert projected["hard_constraints"] == [
        item.to_dict() for item in contract.hard_constraints
    ]
    assert projected["soft_constraints"] == [
        item.to_dict() for item in contract.soft_constraints
    ]
    assert projected["assumptions"] == list(contract.assumptions)


def test_agent_receives_bounded_hashed_read_only_scoring_contract(tmp_path: Path) -> None:
    objective = "Exact coverage is required; lower total cost is better."
    evaluator_source = (
        "import json\n"
        "def main():\n"
        "    print(json.dumps({'combined_score': 1 / (1 + 7)}))\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
        + "# source-padding\n" * 1_500
        + "# SOURCE_TAIL_MUST_NOT_ENTER_PROMPT\n"
    )
    evaluator_sha256 = hashlib.sha256(evaluator_source.encode()).hexdigest()
    scoring = SolverScoringContract(
        objective=objective,
        evaluator_source=evaluator_source,
        evaluator_sha256=evaluator_sha256,
        bundle_sha256="b" * 64,
    )
    contract = _contract()
    root = tmp_path / "run"
    path = root / "evolution" / "contract.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(contract.to_dict()), encoding="utf-8")
    agent = CaptureAgent()
    generator = AgentCandidateGenerator(agent, contract=contract, scoring=scoring)

    generator(_request(root))

    assert len(agent.requests) == 1
    context = _prompt_context(agent.requests[0].prompt)
    prompt_scoring = context["scoring_contract"]
    assert prompt_scoring["authority"] == "frozen_evaluator"
    assert prompt_scoring["bundle_sha256"] == "b" * 64
    assert prompt_scoring["objective"]["text"] == objective
    assert prompt_scoring["evaluator"]["path"] == "scoring/evaluator.py"
    assert prompt_scoring["evaluator"]["sha256"] == evaluator_sha256
    assert prompt_scoring["evaluator"]["truncated"] is True
    assert "1 / (1 + 7)" in prompt_scoring["evaluator"]["source_excerpt"]
    assert "SOURCE_TAIL_MUST_NOT_ENTER_PROMPT" not in agent.requests[0].prompt
    assert str(tmp_path) not in json.dumps(prompt_scoring)
    assert set(agent.scoring_files) == {"evaluator.py", "manifest.json", "objective.md"}
    assert agent.scoring_files["evaluator.py"] == evaluator_source.encode()
    assert agent.scoring_files["objective.md"] == objective.encode()
    assert set(agent.scoring_modes.values()) == {0o444}
    manifest = json.loads(agent.scoring_files["manifest.json"])
    assert manifest["bundle_sha256"] == "b" * 64
    assert manifest["evaluator"]["path"] == "scoring/evaluator.py"
    serialized = json.dumps({"prompt": prompt_scoring, "manifest": manifest})
    assert "probes.json" not in serialized
    assert "audit.json" not in serialized
    assert "input-profile.json" not in serialized
    assert len(agent.requests[0].prompt.encode()) <= 60 * 1024


@pytest.mark.parametrize("mode", ["conflict", "symlink", "unexpected"])
def test_scoring_stage_fails_closed_on_unsafe_existing_files(
    tmp_path: Path, mode: str
) -> None:
    source = "print('score')\n"
    scoring = SolverScoringContract(
        objective="maximize score",
        evaluator_source=source,
        evaluator_sha256=hashlib.sha256(source.encode()).hexdigest(),
        bundle_sha256="c" * 64,
    )
    workspace = tmp_path / "generation"
    target = workspace / "scoring"
    target.mkdir(parents=True)
    if mode == "conflict":
        (target / "evaluator.py").write_text("different", encoding="utf-8")
    elif mode == "symlink":
        outside = tmp_path / "outside.py"
        outside.write_text(source, encoding="utf-8")
        (target / "evaluator.py").symlink_to(outside)
    else:
        (target / "probes.json").write_text("{}", encoding="utf-8")

    with pytest.raises(EvaluatorBundleError, match="scoring"):
        scoring.stage(workspace)
