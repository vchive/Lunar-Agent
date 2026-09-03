import json
from pathlib import Path

import pytest

from famou.algorithm import AlgorithmProblemContract, EvaluationReport
from famou.cli import _status_payload, main
from famou.config import Config
from famou.controller import LocalController
from famou.conversational import build_algorithm_plan
from famou.evolution import CandidateDraft, EvolutionConfig, EvolutionError
from famou.runtime import MockRuntime, RuntimeResult


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "materialize-routes",
            "problem_type": "routing",
            "statement": "Assign every order to a route.",
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
        }
    )


def _valid_report() -> EvaluationReport:
    return EvaluationReport.from_dict(
        {
            "schema_version": "1",
            "evaluator_id": "fixture-evaluator",
            "validity": 1,
            "quality": 1.0,
            "combined_score": 1.0,
            "detailed_scores": {},
            "error_info": [],
        }
    )


def _evolution_fixture(
    tmp_path: Path, source: str, *, filename: str = "candidate.py"
) -> tuple[LocalController, object, object, object]:
    controller = LocalController(Config(tmp_path / "home"), MockRuntime())
    contract = _contract()
    parent = controller.create_conversational_run("optimize routes")
    controller.store.attach_plan_to_run(parent.id, build_algorithm_plan(parent.goal, contract))
    child = controller.create_evolution_run(contract, workspace=tmp_path / "evolution-run")
    settled, result = controller.run_evolution(
        child.id,
        contract,
        lambda request: CandidateDraft(source, filename=filename),
        lambda candidate, candidate_contract: _valid_report(),
        EvolutionConfig(max_rounds=1, stagnation_rounds=1),
    )
    assert settled.status.value == "succeeded"
    return controller, parent, child, result


class MaterializingRuntime:
    name = "materializing-fixture"

    def __init__(self, source: str) -> None:
        self.source = source

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        del workspace, timeout
        if "algorithm contract compiler" in prompt:
            return RuntimeResult(
                json.dumps({"status": "compiled", "contract": _contract().to_dict()})
            )
        if "solver in a bounded local algorithm-evolution run" in prompt:
            return RuntimeResult(self.source)
        if "Return exactly one JSON EvaluationReport object" in prompt:
            return RuntimeResult(json.dumps(_valid_report().to_dict()))
        raise AssertionError("unexpected runtime prompt")

    def cancel(self) -> None:
        return None

    def process_info(self) -> tuple[None, None]:
        return (None, None)

    def set_process_observer(self, observer) -> None:
        del observer


def test_solve_evolve_materializes_reports_and_delivers_output(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    source = (
        "import os\n"
        "from pathlib import Path\n"
        "assert 'FAMOU_API_KEY' not in os.environ\n"
        "counter = Path('execution-count.txt')\n"
        "count = int(counter.read_text()) if counter.exists() else 0\n"
        "counter.write_text(str(count + 1))\n"
        "Path('output').mkdir(exist_ok=True)\n"
        "Path('output/routes.csv').write_text('item_id,route_id\\norder-1,route-a\\n')\n"
    )
    runtime = MaterializingRuntime(source)
    monkeypatch.setattr("famou.cli.build_runtime", lambda *args, **kwargs: runtime)
    monkeypatch.setenv("FAMOU_API_KEY", "sk-should-not-reach-candidate")
    orders = tmp_path / "orders.csv"
    orders.write_text("id\norder-1\n", encoding="utf-8")
    home = tmp_path / "home"

    assert (
        main(
            [
                "solve",
                "optimize routes and return a table",
                "--runtime",
                "mock",
                "--input",
                str(orders),
                "--evolve",
                "--max-rounds",
                "1",
                "--json",
                "--home",
                str(home),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "succeeded"
    assert payload["run_status"] == "succeeded"
    assert payload["evolution"]["materialization"]["status"] == "succeeded"
    assert [item["path"] for item in payload["algorithm_outputs"]] == [
        "output/routes.csv"
    ]
    parent_output = Path(payload["workspace"]) / "output" / "routes.csv"
    assert parent_output.read_text(encoding="utf-8") == "item_id,route_id\norder-1,route-a\n"

    status = _status_payload(Config(home), payload["run_id"])
    assert status is not None
    assert status["evolution"]["linked"]["materialization"]["status"] == "succeeded"
    assert status["algorithm_outputs"][0]["sha256"] == payload["algorithm_outputs"][0][
        "sha256"
    ]
    assert main(["deliver", payload["run_id"], "--json", "--home", str(home)]) == 0
    delivered = json.loads(capsys.readouterr().out)
    assert "output/routes.csv" in delivered["evidence"]

    assert (
        main(
            [
                "solve",
                "--resume",
                "--run-id",
                payload["run_id"],
                "--runtime",
                "mock",
                "--evolve",
                "--max-rounds",
                "1",
                "--json",
                "--home",
                str(home),
            ]
        )
        == 0
    )
    resumed = json.loads(capsys.readouterr().out)
    attempt = (
        Path(resumed["evolution"]["workspace"])
        / resumed["evolution"]["materialization"]["attempt_path"]
    )
    assert (attempt / "execution-count.txt").read_text(encoding="utf-8") == "1"

    parent_output.write_text("tampered\n", encoding="utf-8")
    assert main(["deliver", payload["run_id"], "--json", "--home", str(home)]) == 2
    assert "no longer matches its digest" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("source", "error"),
    [
        ("pass\n", "regular file"),
        (
            """from pathlib import Path
Path('output').mkdir()
Path('output/routes.csv').write_text('item_id\\norder-1\\n')
""",
            "fields",
        ),
        ("raise SystemExit(7)\n", "process"),
        ("import time\ntime.sleep(0.2)\n", "timed out"),
    ],
)
def test_materialization_failures_do_not_promote_outputs(
    tmp_path: Path, source: str, error: str
) -> None:
    controller, parent, child, result = _evolution_fixture(tmp_path, source)
    materialized = controller.materialize_evolved_outputs(
        parent.id,
        child.id,
        _contract(),
        result,
        timeout_seconds=0.02,
    )

    assert materialized["status"] == "failed"
    assert error in str(materialized["error"]).lower()
    assert not (parent.workspace / "output" / "routes.csv").exists()
    assert not any(
        item["kind"] == "output" for item in controller.store.list_artifacts(parent.id)
    )


def test_solve_reports_composite_failure_when_final_output_is_missing(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    runtime = MaterializingRuntime("pass\n")
    monkeypatch.setattr("famou.cli.build_runtime", lambda *args, **kwargs: runtime)
    home = tmp_path / "home"

    assert (
        main(
            [
                "solve",
                "optimize routes and return a table",
                "--runtime",
                "mock",
                "--evolve",
                "--max-rounds",
                "1",
                "--json",
                "--home",
                str(home),
            ]
        )
        == 1
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "failed"
    assert payload["run_status"] == "succeeded"
    assert payload["evolution"]["status"] == "failed"
    assert payload["evolution"]["materialization"] is None
    assert payload["algorithm_outputs"] == []
    assert main(["deliver", payload["run_id"], "--json", "--home", str(home)]) == 2
    assert "no successful evolved output materialization" in capsys.readouterr().err


def test_materialization_rejects_symlink_oversize_and_parent_conflict(tmp_path: Path) -> None:
    outside = tmp_path / "outside.csv"
    symlink_source = (
        "from pathlib import Path\n"
        f"outside = Path({str(outside)!r})\n"
        "outside.write_text('item_id,route_id\\n1,A\\n')\n"
        "Path('output').mkdir()\n"
        "Path('output/routes.csv').symlink_to(outside)\n"
    )
    controller, parent, child, result = _evolution_fixture(tmp_path / "symlink", symlink_source)
    failed = controller.materialize_evolved_outputs(
        parent.id, child.id, _contract(), result, timeout_seconds=1
    )
    assert failed["status"] == "failed"
    assert "outside" in failed["error"] or "symlink" in failed["error"]

    oversize_source = (
        "from pathlib import Path\n"
        "Path('output').mkdir()\n"
        "Path('output/routes.csv').write_text('item_id,route_id\\n' + 'x' * (256 * 1024))\n"
    )
    controller, parent, child, result = _evolution_fixture(tmp_path / "oversize", oversize_source)
    failed = controller.materialize_evolved_outputs(
        parent.id, child.id, _contract(), result, timeout_seconds=1
    )
    assert failed["status"] == "failed"
    assert "exceeds" in failed["error"]

    valid_source = (
        "from pathlib import Path\n"
        "Path('output').mkdir()\n"
        "Path('output/routes.csv').write_text('item_id,route_id\\n1,A\\n')\n"
    )
    controller, parent, child, result = _evolution_fixture(tmp_path / "conflict", valid_source)
    target = parent.workspace / "output" / "routes.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("do not overwrite\n", encoding="utf-8")
    failed = controller.materialize_evolved_outputs(
        parent.id, child.id, _contract(), result, timeout_seconds=1
    )
    assert failed["status"] == "failed"
    assert "different data" in failed["error"]
    assert target.read_text(encoding="utf-8") == "do not overwrite\n"


def test_materialization_terminal_results_are_idempotent_and_tamper_evident(
    tmp_path: Path,
) -> None:
    source = (
        "from pathlib import Path\n"
        "counter = Path('execution-count.txt')\n"
        "counter.write_text(str(int(counter.read_text()) + 1) if counter.exists() else '1')\n"
        "Path('output').mkdir(exist_ok=True)\n"
        "Path('output/routes.csv').write_text('item_id,route_id\\n1,A\\n')\n"
    )
    controller, parent, child, result = _evolution_fixture(tmp_path / "success", source)
    first = controller.materialize_evolved_outputs(
        parent.id, child.id, _contract(), result, timeout_seconds=1
    )
    second = controller.materialize_evolved_outputs(
        parent.id, child.id, _contract(), result, timeout_seconds=1
    )
    assert second == first
    attempt = child.workspace / first["attempt_path"]
    assert (attempt / "execution-count.txt").read_text(encoding="utf-8") == "1"

    candidate = child.workspace / result.best_candidate_path
    candidate.write_text(source + "\n# tampered\n", encoding="utf-8")
    with pytest.raises(EvolutionError, match="candidate digest"):
        controller.materialize_evolved_outputs(
            parent.id, child.id, _contract(), result, timeout_seconds=1
        )

    controller, parent, child, result = _evolution_fixture(
        tmp_path / "failed", "from pathlib import Path\nPath('execution-count.txt').write_text('1')\n"
    )
    first = controller.materialize_evolved_outputs(
        parent.id, child.id, _contract(), result, timeout_seconds=1
    )
    second = controller.materialize_evolved_outputs(
        parent.id, child.id, _contract(), result, timeout_seconds=1
    )
    assert first["status"] == "failed"
    assert second == first
    attempt = child.workspace / first["attempt_path"]
    assert (attempt / "execution-count.txt").read_text(encoding="utf-8") == "1"


def test_automatic_materialization_rejects_non_python_best_candidate(tmp_path: Path) -> None:
    controller, parent, child, result = _evolution_fixture(
        tmp_path,
        "not executable source",
        filename="candidate.txt",
    )

    materialized = controller.materialize_evolved_outputs(
        parent.id, child.id, _contract(), result, timeout_seconds=1
    )
    assert materialized["status"] == "failed"
    assert "requires a .py candidate" in materialized["error"]
