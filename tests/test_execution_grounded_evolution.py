import hashlib
import json
from pathlib import Path

import pytest

from famou.algorithm import AlgorithmProblemContract, EvaluationReport
from famou.cli import main
from famou.evolution import (
    CandidateExecution,
    CandidateInputArtifact,
    ContractCandidateRunner,
    EvolutionError,
    ExecutionAwareCandidateEvaluator,
    contract_candidate_runner_fingerprint,
)
from famou.runtime import RuntimeResult
from famou.store import Store


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "grounded-routes",
            "problem_type": "routing",
            "statement": "Assign every observed order to one route.",
            "inputs": [
                {"path": "orders.csv", "format": "csv", "fields": {"id": "order ID"}}
            ],
            "decision_variables": ["route per order"],
            "objective": {"name": "distance", "direction": "minimize"},
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
            "evolution": {"strategy": "loop", "max_rounds": 2, "stagnation_rounds": 3},
        }
    )


def _report(score: float = 0.5) -> dict[str, object]:
    return {
        "schema_version": "1",
        "evaluator_id": "grounded-fixture",
        "validity": 1,
        "quality": score,
        "combined_score": score,
        "detailed_scores": {},
        "error_info": [],
    }


class GroundedRuntime:
    name = "grounded-runtime"

    def __init__(self) -> None:
        self.generation_calls = 0
        self.evaluation_prompts: list[str] = []

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        del timeout
        if "algorithm contract compiler" in prompt:
            return RuntimeResult(
                json.dumps({"status": "compiled", "contract": _contract().to_dict()})
            )
        if "solver in a bounded local algorithm-evolution run" in prompt:
            self.generation_calls += 1
            if self.generation_calls == 1:
                # A model evaluator would accept this fixture, but the local output gate must
                # invalidate it without spending an evaluator call.
                return RuntimeResult("pass\n")
            return RuntimeResult(
                "import os\n"
                "from pathlib import Path\n"
                "assert 'FAMOU_API_KEY' not in os.environ\n"
                "rows = Path('data/raw/orders.csv').read_text().splitlines()[1:]\n"
                "Path('output').mkdir(exist_ok=True)\n"
                "body = 'item_id,route_id\\n' + ''.join(f'{row},route-a\\n' for row in rows)\n"
                "Path('output/routes.csv').write_text(body)\n"
            )
        if "Return exactly one JSON EvaluationReport object" in prompt:
            self.evaluation_prompts.append(prompt)
            return RuntimeResult(json.dumps(_report()))
        raise AssertionError("unexpected runtime prompt")

    def cancel(self) -> None:
        return None

    def process_info(self) -> tuple[None, None]:
        return (None, None)

    def set_process_observer(self, observer) -> None:
        del observer


def test_conversational_evolution_executes_and_gates_each_native_candidate(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    runtime = GroundedRuntime()
    monkeypatch.setattr("famou.cli.build_runtime", lambda *args, **kwargs: runtime)
    monkeypatch.setenv("FAMOU_API_KEY", "sk-must-not-reach-candidate")
    orders = tmp_path / "orders.csv"
    orders.write_text("id\nsecret-order-42\n", encoding="utf-8")
    home = tmp_path / "home"

    assert (
        main(
            [
                "solve",
                "optimize observed orders and return routes.csv",
                "--runtime",
                "mock",
                "--input",
                str(orders),
                "--evolve",
                "--strategy",
                "loop",
                "--max-rounds",
                "2",
                "--stagnation-rounds",
                "3",
                "--timeout",
                "2",
                "--json",
                "--home",
                str(home),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    child = Path(payload["evolution"]["workspace"])
    archive = [
        json.loads(line)
        for line in (child / "evolution" / "archive.jsonl").read_text().splitlines()
    ]

    assert [item["evaluation"]["validity"] for item in archive] == [0, 1]
    assert archive[0]["evaluation"]["combined_score"] == 0
    assert payload["evolution"]["result"]["best_candidate_id"] == "candidate-0002"
    assert len(runtime.evaluation_prompts) == 1
    evaluator_context = runtime.evaluation_prompts[0]
    assert "candidate_source" in evaluator_context
    assert "execution" in evaluator_context
    assert "output/routes.csv" in evaluator_context
    assert "secret-order-42" not in evaluator_context
    assert "sk-must-not-reach-candidate" not in evaluator_context

    for candidate_id in ("candidate-0001", "candidate-0002"):
        candidate_root = child / "evolution" / "candidates" / candidate_id
        assert (candidate_root / "execution.json").is_file()
        assert (candidate_root / "data" / "raw" / "orders.csv").read_bytes() == orders.read_bytes()
    generations = sorted((child / "evolution" / "agent" / "generations").iterdir())
    assert len(generations) == 2
    assert all((item / "data" / "raw" / "orders.csv").read_bytes() == orders.read_bytes() for item in generations)

    child_artifacts = Store(home / "state.db").list_artifacts(payload["evolution"]["run_id"])
    assert sum(item["kind"] == "candidate_execution" for item in child_artifacts) == 2
    assert any(
        item["kind"] == "candidate_execution_output"
        and item["path"].endswith("candidate-0002/output/routes.csv")
        for item in child_artifacts
    )
    state = json.loads((child / "evolution" / "state.json").read_text(encoding="utf-8"))
    assert len(state["config"]["runner_fingerprint"]) == 64

    final_attempt = child / payload["evolution"]["materialization"]["attempt_path"]
    assert final_attempt != child / "evolution" / "candidates" / "candidate-0002"
    assert (final_attempt / "execution.json").is_file()
    assert (Path(payload["workspace"]) / "output" / "routes.csv").is_file()


def test_contract_candidate_runner_stages_input_and_validates_outputs(tmp_path: Path) -> None:
    root = tmp_path / "run"
    source = root / "data" / "raw" / "orders.csv"
    source.parent.mkdir(parents=True)
    source.write_text("id\norder-1\n", encoding="utf-8")
    descriptor = CandidateInputArtifact(
        "data/raw/orders.csv",
        source.stat().st_size,
        hashlib.sha256(source.read_bytes()).hexdigest(),
    )
    candidate_root = root / "evolution" / "candidates" / "candidate-0001"
    candidate_root.mkdir(parents=True)
    candidate = candidate_root / "candidate.py"
    candidate.write_text(
        "from pathlib import Path\n"
        "assert Path('data/raw/orders.csv').read_text().startswith('id')\n"
        "Path('output').mkdir()\n"
        "Path('output/routes.csv').write_text('item_id,route_id\\norder-1,r1\\n')\n",
        encoding="utf-8",
    )
    runner = ContractCandidateRunner(root, (descriptor,), _contract().outputs, timeout_seconds=2)

    execution = runner.run(candidate, candidate_root)

    assert execution.status == "succeeded"
    assert execution.artifacts == ("output/routes.csv",)
    assert (candidate_root / "data" / "raw" / "orders.csv").read_bytes() == source.read_bytes()
    evidence = json.loads((candidate_root / "execution.json").read_text(encoding="utf-8"))
    assert evidence["artifacts"] == ["output/routes.csv"]


def test_contract_candidate_runner_rejects_output_and_input_tampering(tmp_path: Path) -> None:
    root = tmp_path / "run"
    source = root / "data" / "raw" / "orders.csv"
    source.parent.mkdir(parents=True)
    source.write_text("id\norder-1\n", encoding="utf-8")
    descriptor = CandidateInputArtifact(
        "data/raw/orders.csv",
        source.stat().st_size,
        hashlib.sha256(source.read_bytes()).hexdigest(),
    )
    candidate_root = root / "evolution" / "candidates" / "candidate-0001"
    candidate_root.mkdir(parents=True)
    candidate = candidate_root / "candidate.py"
    candidate.write_text(
        "from pathlib import Path\n"
        "Path('output').mkdir()\n"
        "Path('output/routes.csv').write_text('wrong\\nvalue\\n')\n",
        encoding="utf-8",
    )
    runner = ContractCandidateRunner(root, (descriptor,), _contract().outputs, timeout_seconds=2)
    execution = runner.run(candidate, candidate_root)
    assert execution.status == "failed"
    assert execution.error == "output_contract_invalid"
    assert execution.artifacts == ()

    tampered_root = tmp_path / "tampered"
    tampered_source = tampered_root / "data" / "raw" / "orders.csv"
    tampered_source.parent.mkdir(parents=True)
    tampered_source.write_text("changed", encoding="utf-8")
    tampered_candidate = tampered_root / "candidate.py"
    tampered_candidate.write_text("pass\n", encoding="utf-8")
    with pytest.raises(EvolutionError, match="digest"):
        ContractCandidateRunner(
            tampered_root,
            (descriptor,),
            _contract().outputs,
            timeout_seconds=2,
        ).run(tampered_candidate, tampered_root)


def test_execution_aware_evaluator_skips_downstream_after_runner_failure(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.py"
    candidate.write_text("pass\n", encoding="utf-8")

    class FailedRunner:
        def run(self, candidate_path: Path, workspace: Path, timeout: float | None = None):
            del candidate_path, workspace, timeout
            return CandidateExecution("failed", 2, 1, error="candidate_process_failed")

    calls = {"count": 0}

    def evaluator(candidate_path: Path, contract: AlgorithmProblemContract) -> EvaluationReport:
        del candidate_path, contract
        calls["count"] += 1
        return EvaluationReport.from_dict(_report(99))

    report = ExecutionAwareCandidateEvaluator(FailedRunner(), evaluator)(candidate, _contract())

    assert calls["count"] == 0
    assert report.validity == 0
    assert report.combined_score == 0


def test_conversational_population_uses_the_same_execution_gate(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    runtime = GroundedRuntime()
    monkeypatch.setattr("famou.cli.build_runtime", lambda *args, **kwargs: runtime)
    orders = tmp_path / "orders.csv"
    orders.write_text("id\norder-1\n", encoding="utf-8")
    home = tmp_path / "home"

    assert main(
        [
            "solve",
            "optimize observed orders and return routes.csv",
            "--runtime",
            "mock",
            "--input",
            str(orders),
            "--evolve",
            "--strategy",
            "population",
            "--population-size",
            "2",
            "--max-rounds",
            "1",
            "--timeout",
            "2",
            "--json",
            "--home",
            str(home),
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    child = Path(payload["evolution"]["workspace"])
    archive = [
        json.loads(line)
        for line in (child / "evolution" / "archive.jsonl").read_text().splitlines()
    ]

    assert archive[0]["evaluation"]["validity"] == 0
    assert all(
        (child / Path(item["code_path"]).parent / "execution.json").is_file()
        for item in archive
    )
    assert len(runtime.evaluation_prompts) == len(archive) - 1


def test_contract_runner_supports_source_only_contracts_and_has_stable_fingerprint(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate.py"
    candidate.write_text("pass\n", encoding="utf-8")
    runner = ContractCandidateRunner(tmp_path, (), (), timeout_seconds=2)

    execution = runner.run(candidate, tmp_path)

    assert execution.status == "succeeded"
    assert execution.artifacts == ()
    fingerprint = contract_candidate_runner_fingerprint(_contract(), ())
    assert len(fingerprint) == 64
    assert fingerprint == contract_candidate_runner_fingerprint(_contract(), ())


@pytest.mark.parametrize("location", ["source", "target"])
def test_contract_runner_rejects_dangling_input_symlinks(
    tmp_path: Path, location: str
) -> None:
    source_root = tmp_path / "source"
    source = source_root / "data" / "raw" / "orders.csv"
    source.parent.mkdir(parents=True)
    source.write_text("id\norder-1\n", encoding="utf-8")
    descriptor = CandidateInputArtifact(
        "data/raw/orders.csv",
        source.stat().st_size,
        hashlib.sha256(source.read_bytes()).hexdigest(),
    )
    candidate_root = tmp_path / "candidate"
    candidate_root.mkdir()
    candidate = candidate_root / "candidate.py"
    candidate.write_text("pass\n", encoding="utf-8")
    if location == "source":
        source.unlink()
        source.symlink_to(source_root / "missing.csv")
    else:
        (candidate_root / "data").symlink_to(candidate_root / "missing")

    with pytest.raises(EvolutionError, match="symlink"):
        ContractCandidateRunner(source_root, (descriptor,), (), timeout_seconds=2).run(
            candidate, candidate_root
        )


def test_conversational_resume_rejects_tampered_child_input(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    runtime = GroundedRuntime()
    monkeypatch.setattr("famou.cli.build_runtime", lambda *args, **kwargs: runtime)
    orders = tmp_path / "orders.csv"
    orders.write_text("id\norder-1\n", encoding="utf-8")
    home = tmp_path / "home"
    args = [
        "solve",
        "optimize observed orders and return routes.csv",
        "--runtime",
        "mock",
        "--input",
        str(orders),
        "--evolve",
        "--max-rounds",
        "2",
        "--timeout",
        "2",
        "--json",
        "--home",
        str(home),
    ]
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
    child_input = Path(first["evolution"]["workspace"]) / "data" / "raw" / "orders.csv"
    child_input.write_text("tampered", encoding="utf-8")

    assert main(
        [
            "solve",
            "--resume",
            "--run-id",
            first["run_id"],
            "--runtime",
            "mock",
            "--evolve",
            "--max-rounds",
            "2",
            "--timeout",
            "2",
            "--json",
            "--home",
            str(home),
        ]
    ) == 2
    assert "different data" in capsys.readouterr().err
