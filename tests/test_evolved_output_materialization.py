import hashlib
import json
import os
import shutil
import stat
import sys
from dataclasses import replace
from pathlib import Path

import pytest

import famou.evolution as evolution_module
from famou.algorithm import AlgorithmProblemContract, EvaluationReport
from famou.artifacts import ArtifactStore
from famou.cli import _status_payload, main
from famou.config import Config
from famou.controller import LocalController
from famou.conversational import build_algorithm_plan
from famou.evolution import (
    Candidate,
    CandidateArchive,
    CandidateDraft,
    CandidateExecution,
    CommandCandidateRunner,
    EvolutionConfig,
    EvolutionError,
    StrategyResult,
)
from famou.output_publication import OutputPublicationUncertain
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
    tmp_path: Path, source: str, *, filename: str = "candidate.py",
    contract: AlgorithmProblemContract | None = None,
) -> tuple[LocalController, object, object, object]:
    controller = LocalController(Config(tmp_path / "home"), MockRuntime())
    contract = contract or _contract()
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


def _openevolve_fixture(
    tmp_path: Path,
) -> tuple[LocalController, object, object, StrategyResult]:
    producer = tmp_path / "fake_openevolve.py"
    producer.parent.mkdir(parents=True, exist_ok=True)
    candidate_source = (
        "from pathlib import Path\n"
        "Path('output').mkdir(exist_ok=True)\n"
        "Path('output/routes.csv').write_text("
        "'item_id,route_id\\norder-1,route-a\\n')\n"
    )
    producer.write_text(
        "import json, pathlib, sys\n"
        "config = json.loads(pathlib.Path(sys.argv[1]).read_text())\n"
        "root = pathlib.Path.cwd()\n"
        f"(root / 'candidate.py').write_text({candidate_source!r})\n"
        "evaluation = {"
        "'schema_version':'1','evaluator_id':'external','validity':1,"
        "'quality':999,'combined_score':999,'detailed_scores':{},'error_info':[]}\n"
        "(root / config['result_path']).write_text(json.dumps("
        "{'candidate_path':'candidate.py','evaluation':evaluation}))\n",
        encoding="utf-8",
    )
    controller = LocalController(Config(tmp_path / "home"), MockRuntime())
    contract = _contract()
    parent = controller.create_conversational_run("optimize routes")
    controller.store.attach_plan_to_run(parent.id, build_algorithm_plan(parent.goal, contract))
    child = controller.create_evolution_run(contract, workspace=tmp_path / "evolution-run")
    controller.store.append_event(
        parent.id,
        "evolution_linked",
        {
            "evolution_run_id": child.id,
            "contract_sha256": contract.digest(),
            "strategy": "openevolve",
        },
    )
    controller.store.append_event(
        child.id,
        "evolution_parent_linked",
        {
            "parent_run_id": parent.id,
            "contract_sha256": contract.digest(),
            "strategy": "openevolve",
        },
    )
    settled, result = controller.run_evolution(
        child.id,
        contract,
        lambda request: pytest.fail("OpenEvolve called the Lunar candidate generator"),
        lambda candidate, candidate_contract: _valid_report(),
        EvolutionConfig(
            strategy="openevolve",
            command=(sys.executable, str(producer)),
            timeout_seconds=5,
            evaluator_fingerprint="a" * 64,
        ),
    )
    assert settled.status.value == "succeeded"
    return controller, parent, child, result


def _counted_materialization_source(*, output: bool) -> str:
    source = (
        "from pathlib import Path\n"
        "counter = Path('execution-count.txt')\n"
        "counter.write_text(str(int(counter.read_text()) + 1) if counter.exists() else '1')\n"
    )
    if output:
        source += (
            "Path('output').mkdir(exist_ok=True)\n"
            "Path('output/routes.csv').write_text('item_id,route_id\\n1,A\\n')\n"
        )
    return source


def _materialization_attempt_path(child, result: StrategyResult) -> Path:
    candidate = child.workspace / result.best_candidate_path
    digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
    return (
        child.workspace
        / "evolution"
        / "materialization"
        / f"{result.best_candidate_id}-{digest[:12]}"
    )


def _batch_materialization_fixture(tmp_path: Path):
    first = _contract().outputs[0]
    contract = replace(_contract(), outputs=(first, replace(first, path="output/second.csv")))
    source = _counted_materialization_source(output=True) + (
        "Path('output/second.csv').write_text('item_id,route_id\\n2,B\\n')\n"
    )
    return (*_evolution_fixture(tmp_path, source, contract=contract), contract)


def _publication_journal(parent, child) -> Path:
    key = hashlib.sha256(f"{parent.id}\0{child.id}".encode()).hexdigest()
    return parent.workspace / ".evolved-output-publications" / key / "journal.json"


def test_batch_database_failure_produces_replayable_failure_without_partial_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, parent, child, result, contract = _batch_materialization_fixture(tmp_path)
    with controller.store._connect() as connection:
        connection.execute(
            "CREATE TRIGGER fail_second_output BEFORE INSERT ON artifacts "
            "WHEN NEW.kind = 'output' AND NEW.path = 'output/second.csv' "
            "BEGIN SELECT RAISE(ABORT, 'fixture failure'); END"
        )
    materialized = controller.materialize_evolved_outputs(
        parent.id, child.id, contract, result, timeout_seconds=1
    )
    assert materialized["status"] == "failed"
    assert materialized["outputs"] == []
    assert all(not (parent.workspace / spec.path).exists() for spec in contract.outputs)
    assert not [row for row in controller.store.list_artifacts(parent.id) if row["kind"] == "output"]
    assert not [event for event in controller.store.list_events(parent.id) if event["type"] in {
        "evolved_outputs_promoted", "output_publication_committed",
    }]
    assert _publication_journal(parent, child).with_name("rolled-back.json").is_file()
    monkeypatch.setattr(CommandCandidateRunner, "run", lambda *a, **k: pytest.fail("reexecuted"))
    assert controller.materialize_evolved_outputs(
        parent.id, child.id, contract, result, timeout_seconds=1
    ) == materialized
    assert (_materialization_attempt_path(child, result) / "execution-count.txt").read_text() == "1"


@pytest.mark.parametrize("committed", [False, True])
def test_unknown_publication_preserves_attempt_without_terminal_claim_or_reexecution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, committed: bool,
) -> None:
    controller, parent, child, result, contract = _batch_materialization_fixture(tmp_path)

    def unavailable(*args, **kwargs):
        raise OSError("fixture database unavailable")

    original_commit = controller.store.commit_output_publication
    with monkeypatch.context() as patch:
        def unknown_commit(*args, **kwargs):
            if committed:
                original_commit(*args, **kwargs)
            patch.setattr(controller.store, "output_publication_committed", unavailable)
            raise OSError("fixture commit outcome unavailable")

        patch.setattr(controller.store, "commit_output_publication", unknown_commit)
        with pytest.raises(OutputPublicationUncertain, match="output_publication_commit_unknown"):
            controller.materialize_evolved_outputs(
                parent.id, child.id, contract, result, timeout_seconds=1
            )
    marker = child.workspace / "evolution/materialization/result.json"
    assert not marker.exists()
    assert all((parent.workspace / spec.path).is_file() for spec in contract.outputs)
    assert _publication_journal(parent, child).is_file()
    outputs = [row for row in controller.store.list_artifacts(parent.id) if row["kind"] == "output"]
    assert len(outputs) == (2 if committed else 0)
    monkeypatch.setattr(CommandCandidateRunner, "run", lambda *a, **k: pytest.fail("reexecuted"))
    for _ in range(2):
        with pytest.raises(EvolutionError, match="materialization marker is missing"):
            controller.materialize_evolved_outputs(
                parent.id, child.id, contract, result, timeout_seconds=1
            )
        assert not marker.exists()
        assert all((parent.workspace / spec.path).exists() == committed for spec in contract.outputs)
    assert (_materialization_attempt_path(child, result) / "execution-count.txt").read_text() == "1"


def test_materialization_resume_reconciles_interrupted_batch_before_marker_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, parent, child, result, contract = _batch_materialization_fixture(tmp_path)
    original = os.link
    first = parent.workspace / contract.outputs[0].path

    class Interrupted(BaseException):
        pass

    def interrupt(source, target, *args, **kwargs):
        original(source, target, *args, **kwargs)
        if Path(target) == first:
            raise Interrupted

    with monkeypatch.context() as patch:
        patch.setattr(os, "link", interrupt)
        with pytest.raises(Interrupted):
            controller.materialize_evolved_outputs(
                parent.id, child.id, contract, result, timeout_seconds=1
            )
    assert first.is_file()
    assert not (parent.workspace / contract.outputs[1].path).exists()
    monkeypatch.setattr(CommandCandidateRunner, "run", lambda *a, **k: pytest.fail("reexecuted"))
    for _ in range(2):
        with pytest.raises(EvolutionError, match="materialization marker is missing"):
            controller.materialize_evolved_outputs(
                parent.id, child.id, contract, result, timeout_seconds=1
            )
        assert all(not (parent.workspace / spec.path).exists() for spec in contract.outputs)
    assert _publication_journal(parent, child).with_name("rolled-back.json").is_file()
    assert (_materialization_attempt_path(child, result) / "execution-count.txt").read_text() == "1"


@pytest.mark.parametrize("drift", ["content", "missing_directory"])
def test_cached_materialization_rejects_publication_journal_drift(
    tmp_path: Path, drift: str,
) -> None:
    controller, parent, child, result = _evolution_fixture(
        tmp_path, _counted_materialization_source(output=True)
    )
    materialized = controller.materialize_evolved_outputs(
        parent.id, child.id, _contract(), result, timeout_seconds=1
    )
    journal = _publication_journal(parent, child)
    if drift == "missing_directory":
        shutil.rmtree(journal.parent)
    else:
        content = json.loads(journal.read_bytes())
        content["entries"][0]["existed"] = True
        journal.write_text(json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    _assert_cached_replay_rejected_without_writes(controller, parent, child, result, materialized)


def _assert_cached_replay_rejected_without_writes(
    controller: LocalController,
    parent,
    child,
    result: StrategyResult,
    materialized: dict,
) -> None:
    parent_artifacts = controller.store.list_artifacts(parent.id)
    child_artifacts = controller.store.list_artifacts(child.id)
    parent_events = controller.store.list_events(parent.id)
    child_events = controller.store.list_events(child.id)
    attempt = child.workspace / materialized["attempt_path"]
    counter = attempt / "execution-count.txt"
    execution_count = counter.read_text(encoding="utf-8") if counter.is_file() else None

    with pytest.raises(EvolutionError):
        controller.materialize_evolved_outputs(
            parent.id, child.id, _contract(), result, timeout_seconds=1
        )

    assert controller.store.list_artifacts(parent.id) == parent_artifacts
    assert controller.store.list_artifacts(child.id) == child_artifacts
    assert controller.store.list_events(parent.id) == parent_events
    assert controller.store.list_events(child.id) == child_events
    assert (counter.read_text(encoding="utf-8") if counter.is_file() else None) == execution_count


@pytest.mark.parametrize("failure", ["write", "fsync", "replace"])
def test_execution_evidence_failure_preserves_temporary_node(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    workspace = tmp_path / "attempt"
    workspace.mkdir()
    original_write = os.write
    original_fsync = os.fsync
    original_replace = os.replace

    def fail_write(descriptor: int, content: bytes | memoryview) -> int:
        if failure == "write":
            raise OSError("simulated execution evidence write failure")
        return original_write(descriptor, content)

    def fail_regular_fsync(descriptor: int) -> None:
        if failure == "fsync" and stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("simulated execution evidence fsync failure")
        original_fsync(descriptor)

    def fail_replace(source: str | os.PathLike[str], target: str | os.PathLike[str]) -> None:
        if failure == "replace" and Path(source).name == ".execution.json.tmp":
            raise OSError("simulated execution evidence replace failure")
        original_replace(source, target)

    monkeypatch.setattr(os, "write", fail_write)
    monkeypatch.setattr(os, "fsync", fail_regular_fsync)
    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(
        EvolutionError,
        match="^candidate execution evidence could not be persisted$",
    ):
        evolution_module._write_execution_evidence(
            workspace,
            CandidateExecution(status="succeeded", exit_code=0, duration_ms=1),
        )

    temporary = workspace / ".execution.json.tmp"
    assert temporary.is_file() and not temporary.is_symlink()
    assert not (workspace / "execution.json").exists()


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


@pytest.mark.parametrize("obstruction", ["symlink", "file"])
def test_materialization_rejects_obstructed_optional_output_ancestors(
    tmp_path: Path, obstruction: str,
) -> None:
    payload = _contract().to_dict()
    payload["outputs"].append({
        "path": "output/extra/summary.json", "format": "json", "required": False,
    })
    contract = AlgorithmProblemContract.from_dict(payload)
    source = (
        "from pathlib import Path\n"
        "Path('output').mkdir()\n"
        "Path('output/routes.csv').write_text('item_id,route_id\\n1,A\\n')\n"
        + (
            "Path('output/extra').symlink_to('missing-directory')\n"
            if obstruction == "symlink" else "Path('output/extra').write_text('obstruction')\n"
        )
    )
    controller, parent, child, result = _evolution_fixture(tmp_path, source, contract=contract)
    failed = controller.materialize_evolved_outputs(
        parent.id, child.id, contract, result, timeout_seconds=2,
    )
    assert failed["status"] == "failed"
    assert not (parent.workspace / "output/routes.csv").exists()
    assert not any(item["kind"] == "output" for item in controller.store.list_artifacts(parent.id))


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


@pytest.mark.parametrize(
    ("obstruction", "error"),
    [
        ("materialization_file", "directory could not be prepared"),
        ("temporary_file", "temporary result already exists"),
        ("temporary_directory", "temporary result already exists"),
        ("temporary_symlink", "temporary result already exists"),
    ],
)
def test_materialization_obstructions_fail_before_execution_or_ledger_writes(
    tmp_path: Path,
    obstruction: str,
    error: str,
) -> None:
    controller, parent, child, result = _evolution_fixture(
        tmp_path, _counted_materialization_source(output=True)
    )
    materialization = child.workspace / "evolution" / "materialization"
    if obstruction == "materialization_file":
        materialization.write_text("blocked", encoding="utf-8")
    else:
        materialization.mkdir()
        temporary = materialization / ".result.json.tmp"
        if obstruction == "temporary_file":
            temporary.write_text("blocked", encoding="utf-8")
        elif obstruction == "temporary_directory":
            temporary.mkdir()
        else:
            target = tmp_path / "outside-temporary"
            target.write_text("blocked", encoding="utf-8")
            temporary.symlink_to(target)
    parent_artifacts = controller.store.list_artifacts(parent.id)
    child_artifacts = controller.store.list_artifacts(child.id)
    parent_events = controller.store.list_events(parent.id)
    child_events = controller.store.list_events(child.id)

    with pytest.raises(EvolutionError, match=error):
        controller.materialize_evolved_outputs(
            parent.id, child.id, _contract(), result, timeout_seconds=1
        )

    assert not list(child.workspace.rglob("execution-count.txt"))
    assert not (parent.workspace / "output" / "routes.csv").exists()
    assert controller.store.list_artifacts(parent.id) == parent_artifacts
    assert controller.store.list_artifacts(child.id) == child_artifacts
    assert controller.store.list_events(parent.id) == parent_events
    assert controller.store.list_events(child.id) == child_events


@pytest.mark.parametrize("tamper", ["ledger", "internal"])
def test_failed_materialization_marker_is_immutable_and_internally_consistent(
    tmp_path: Path,
    tamper: str,
) -> None:
    source = (
        "from pathlib import Path\n"
        "counter = Path('execution-count.txt')\n"
        "counter.write_text(str(int(counter.read_text()) + 1) if counter.exists() else '1')\n"
    )
    controller, parent, child, result = _evolution_fixture(tmp_path, source)
    first = controller.materialize_evolved_outputs(
        parent.id, child.id, _contract(), result, timeout_seconds=1
    )
    assert first["status"] == "failed"
    marker = child.workspace / "evolution" / "materialization" / "result.json"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    if tamper == "ledger":
        payload["error"] = "changed failure evidence"
    else:
        payload["error"] = None
    marker.write_text(json.dumps(payload), encoding="utf-8")
    parent_artifacts_before = controller.store.list_artifacts(parent.id)
    child_artifacts_before = controller.store.list_artifacts(child.id)
    events_before = controller.store.list_events(parent.id)

    with pytest.raises(EvolutionError):
        controller.materialize_evolved_outputs(
            parent.id, child.id, _contract(), result, timeout_seconds=1
        )

    attempt = child.workspace / first["attempt_path"]
    assert (attempt / "execution-count.txt").read_text(encoding="utf-8") == "1"
    assert controller.store.list_artifacts(parent.id) == parent_artifacts_before
    assert controller.store.list_artifacts(child.id) == child_artifacts_before
    assert controller.store.list_events(parent.id) == events_before


@pytest.mark.parametrize("output", [True, False], ids=["success", "failed"])
@pytest.mark.parametrize("mutation", ["delete", "payload", "task", "id"])
def test_cached_materialization_requires_exact_parent_result_event(
    tmp_path: Path,
    output: bool,
    mutation: str,
) -> None:
    controller, parent, child, result = _evolution_fixture(
        tmp_path, _counted_materialization_source(output=output)
    )
    materialized = controller.materialize_evolved_outputs(
        parent.id, child.id, _contract(), result, timeout_seconds=1
    )
    event = next(
        item
        for item in controller.store.list_events(parent.id)
        if item["type"] == "evolved_candidate_materialized"
    )
    with controller.store._connect() as connection:
        if mutation == "delete":
            connection.execute("DELETE FROM events WHERE id = ?", (event["id"],))
        elif mutation == "payload":
            changed = dict(event["payload"])
            changed["candidate_sha256"] = "0" * 64
            connection.execute(
                "UPDATE events SET payload = ? WHERE id = ?",
                (json.dumps(changed, sort_keys=True), event["id"]),
            )
        elif mutation == "task":
            task_id = controller.store.list_tasks(parent.id)[0].id
            connection.execute(
                "UPDATE events SET task_id = ? WHERE id = ?", (task_id, event["id"])
            )
        else:
            connection.execute(
                "UPDATE events SET id = ? WHERE id = ?",
                ("event-tampered-materialization", event["id"]),
            )

    _assert_cached_replay_rejected_without_writes(
        controller, parent, child, result, materialized
    )


@pytest.mark.parametrize("output", [True, False], ids=["success", "failed"])
@pytest.mark.parametrize("mutation", ["delete", "payload", "task", "id"])
def test_cached_materialization_requires_exact_child_execution_event(
    tmp_path: Path,
    output: bool,
    mutation: str,
) -> None:
    controller, parent, child, result = _evolution_fixture(
        tmp_path, _counted_materialization_source(output=output)
    )
    materialized = controller.materialize_evolved_outputs(
        parent.id, child.id, _contract(), result, timeout_seconds=1
    )
    event = next(
        item
        for item in controller.store.list_events(child.id)
        if item["type"] == "evolved_candidate_executed"
    )
    with controller.store._connect() as connection:
        if mutation == "delete":
            connection.execute("DELETE FROM events WHERE id = ?", (event["id"],))
        elif mutation == "payload":
            changed = dict(event["payload"])
            changed["duration_ms"] += 1
            connection.execute(
                "UPDATE events SET payload = ? WHERE id = ?",
                (json.dumps(changed, sort_keys=True), event["id"]),
            )
        elif mutation == "task":
            connection.execute(
                "UPDATE events SET task_id = NULL WHERE id = ?", (event["id"],)
            )
        else:
            connection.execute(
                "UPDATE events SET id = ? WHERE id = ?",
                ("event-tampered-execution", event["id"]),
            )

    _assert_cached_replay_rejected_without_writes(
        controller, parent, child, result, materialized
    )


@pytest.mark.parametrize("mutation", ["digest", "task", "duplicate", "canonical"])
def test_cached_materialization_requires_exact_execution_artifact(
    tmp_path: Path,
    mutation: str,
) -> None:
    controller, parent, child, result = _evolution_fixture(
        tmp_path, _counted_materialization_source(output=True)
    )
    materialized = controller.materialize_evolved_outputs(
        parent.id, child.id, _contract(), result, timeout_seconds=1
    )
    execution_relative = materialized["execution"]["evidence_path"]
    artifact = next(
        item
        for item in controller.store.list_artifacts(child.id)
        if item["path"] == execution_relative
        and item["kind"] == "evolved_candidate_execution"
    )
    if mutation == "duplicate":
        controller.store.add_artifact(
            child.id,
            artifact["task_id"],
            artifact["path"],
            artifact["sha256"],
            artifact["size"],
            artifact["kind"],
        )
    else:
        with controller.store._connect() as connection:
            if mutation == "digest":
                connection.execute(
                    "UPDATE artifacts SET sha256 = ? WHERE id = ?",
                    ("0" * 64, artifact["id"]),
                )
            elif mutation == "task":
                parent_task = controller.store.list_tasks(parent.id)[0].id
                connection.execute(
                    "UPDATE artifacts SET task_id = ? WHERE id = ?",
                    (parent_task, artifact["id"]),
                )
            else:
                evidence = child.workspace / execution_relative
                raw = json.loads(evidence.read_text(encoding="utf-8"))
                raw["stdout_bytes"] += 1
                encoded = (
                    json.dumps(raw, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
                ).encode("utf-8")
                evidence.write_bytes(encoded)
                connection.execute(
                    "UPDATE artifacts SET sha256 = ?, size = ? WHERE id = ?",
                    (hashlib.sha256(encoded).hexdigest(), len(encoded), artifact["id"]),
                )

    _assert_cached_replay_rejected_without_writes(
        controller, parent, child, result, materialized
    )


@pytest.mark.parametrize(
    "mutation",
    ["artifact_id", "artifact_task", "event_delete", "event_payload", "event_task", "event_id"],
)
def test_cached_success_binds_output_artifact_and_promotion_event(
    tmp_path: Path,
    mutation: str,
) -> None:
    controller, parent, child, result = _evolution_fixture(
        tmp_path, _counted_materialization_source(output=True)
    )
    materialized = controller.materialize_evolved_outputs(
        parent.id, child.id, _contract(), result, timeout_seconds=1
    )
    output = materialized["outputs"][0]
    promotion = next(
        item
        for item in controller.store.list_events(parent.id)
        if item["type"] == "evolved_outputs_promoted"
    )
    with controller.store._connect() as connection:
        if mutation == "artifact_id":
            connection.execute(
                "UPDATE artifacts SET id = ? WHERE id = ?",
                ("artifact-tampered-output", output["artifact_id"]),
            )
        elif mutation == "artifact_task":
            child_task = controller.store.list_tasks(child.id)[0].id
            connection.execute(
                "UPDATE artifacts SET task_id = ? WHERE id = ?",
                (child_task, output["artifact_id"]),
            )
        elif mutation == "event_delete":
            connection.execute("DELETE FROM events WHERE id = ?", (promotion["id"],))
        elif mutation == "event_payload":
            changed = dict(promotion["payload"])
            changed["evolution_run_id"] = "tampered"
            connection.execute(
                "UPDATE events SET payload = ? WHERE id = ?",
                (json.dumps(changed, sort_keys=True), promotion["id"]),
            )
        elif mutation == "event_task":
            connection.execute(
                "UPDATE events SET task_id = NULL WHERE id = ?", (promotion["id"],)
            )
        else:
            connection.execute(
                "UPDATE events SET id = ? WHERE id = ?",
                ("event-tampered-promotion", promotion["id"]),
            )

    _assert_cached_replay_rejected_without_writes(
        controller, parent, child, result, materialized
    )


def test_materialization_reuses_matching_output_owned_by_another_parent_task(
    tmp_path: Path,
) -> None:
    controller, parent, child, result = _evolution_fixture(
        tmp_path, _counted_materialization_source(output=True)
    )
    output = parent.workspace / "output" / "routes.csv"
    output.parent.mkdir(parents=True)
    output.write_text("item_id,route_id\n1,A\n", encoding="utf-8")
    tasks = controller.store.list_tasks(parent.id)
    owner = next(task for task in tasks if task.plan_task_id == "solve")
    other = next(task for task in tasks if task.id != owner.id)
    existing_id = controller.store.add_artifact(
        parent.id,
        other.id,
        "output/routes.csv",
        hashlib.sha256(output.read_bytes()).hexdigest(),
        output.stat().st_size,
        "output",
    )

    first = controller.materialize_evolved_outputs(
        parent.id, child.id, _contract(), result, timeout_seconds=1
    )
    second = controller.materialize_evolved_outputs(
        parent.id, child.id, _contract(), result, timeout_seconds=1
    )

    assert first == second
    assert first["status"] == "succeeded"
    assert first["outputs"][0]["artifact_id"] == existing_id
    rows = [
        item
        for item in controller.store.list_artifacts(parent.id)
        if item["path"] == "output/routes.csv" and item["kind"] == "output"
    ]
    assert len(rows) == 1
    assert rows[0]["task_id"] == other.id
    promoted = next(
        item
        for item in controller.store.list_events(parent.id)
        if item["type"] == "evolved_outputs_promoted"
    )
    assert promoted["task_id"] == owner.id


def test_output_promotion_rejects_fixed_event_collision_before_publication(
    tmp_path: Path,
) -> None:
    controller, parent, child, _result = _evolution_fixture(
        tmp_path, _counted_materialization_source(output=True)
    )
    attempt = tmp_path / "standalone-attempt"
    candidate_output = attempt / "output" / "routes.csv"
    candidate_output.parent.mkdir(parents=True)
    candidate_output.write_text("item_id,route_id\n1,A\n", encoding="utf-8")
    event_id = "event-evolved-outputs-promoted-" + hashlib.sha256(
        f"{parent.id}\0{child.id}".encode()
    ).hexdigest()
    controller.store.append_event(
        parent.id,
        "tampered_promotion",
        {},
        event_id=event_id,
    )
    artifacts_before = controller.store.list_artifacts(parent.id)
    events_before = controller.store.list_events(parent.id)

    with pytest.raises(EvolutionError, match="promotion event already exists"):
        controller._promote_evolved_outputs(
            parent, child.id, attempt, _contract().outputs
        )

    assert not (parent.workspace / "output" / "routes.csv").exists()
    assert controller.store.list_artifacts(parent.id) == artifacts_before
    assert controller.store.list_events(parent.id) == events_before


@pytest.mark.parametrize("output", [True, False], ids=["success", "failed"])
def test_missing_terminal_marker_never_reexecutes_recorded_attempt(
    tmp_path: Path,
    output: bool,
) -> None:
    controller, parent, child, result = _evolution_fixture(
        tmp_path, _counted_materialization_source(output=output)
    )
    materialized = controller.materialize_evolved_outputs(
        parent.id, child.id, _contract(), result, timeout_seconds=1
    )
    marker = child.workspace / "evolution" / "materialization" / "result.json"
    marker.unlink()

    _assert_cached_replay_rejected_without_writes(
        controller, parent, child, result, materialized
    )


@pytest.mark.parametrize(
    "execution_node",
    [
        "regular",
        "directory",
        "symlink",
        "broken_symlink",
        "fifo",
        "symlinked_attempt",
    ],
)
@pytest.mark.parametrize("evidence_name", ["execution.json", ".execution.json.tmp"])
def test_missing_marker_rejects_unrecorded_execution_node_before_attempt_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    execution_node: str,
    evidence_name: str,
) -> None:
    controller, parent, child, result = _evolution_fixture(
        tmp_path, _counted_materialization_source(output=True)
    )
    attempt = _materialization_attempt_path(child, result)
    if execution_node == "symlinked_attempt":
        attempt.parent.mkdir(parents=True)
        outside = tmp_path / "outside-attempt"
        outside.mkdir()
        (outside / evidence_name).write_text("unrecorded\n", encoding="utf-8")
        (outside / "staging-sentinel").write_text("preserve\n", encoding="utf-8")
        attempt.symlink_to(outside, target_is_directory=True)
        execution_path = outside / evidence_name
        sentinel = outside / "staging-sentinel"
    else:
        attempt.mkdir(parents=True)
        sentinel = attempt / "staging-sentinel"
        sentinel.write_text("preserve\n", encoding="utf-8")
        execution_path = attempt / evidence_name
        if execution_node == "regular":
            execution_path.write_text("unrecorded\n", encoding="utf-8")
        elif execution_node == "directory":
            execution_path.mkdir()
        elif execution_node in {"symlink", "broken_symlink"}:
            target = tmp_path / "execution-target"
            if execution_node == "symlink":
                target.write_text("outside\n", encoding="utf-8")
            execution_path.symlink_to(target)
        else:
            os.mkfifo(execution_path)
    artifacts_before = controller.store.list_artifacts(child.id)
    parent_events_before = controller.store.list_events(parent.id)
    child_events_before = controller.store.list_events(child.id)
    calls = 0

    def reject_run(
        self: CommandCandidateRunner,
        candidate_path: Path,
        workspace: Path,
        timeout: float | None = None,
    ):
        del self, candidate_path, workspace, timeout
        nonlocal calls
        calls += 1
        pytest.fail("unrecorded execution evidence replayed the candidate")

    monkeypatch.setattr(CommandCandidateRunner, "run", reject_run)

    with pytest.raises(
        EvolutionError,
        match="^materialization marker is missing from a recorded attempt$",
    ):
        controller.materialize_evolved_outputs(
            parent.id, child.id, _contract(), result, timeout_seconds=1
        )

    assert calls == 0
    assert sentinel.read_bytes() == b"preserve\n"
    assert os.path.lexists(execution_path)
    if execution_node == "directory":
        assert execution_path.is_dir() and not execution_path.is_symlink()
    elif execution_node in {"symlink", "broken_symlink"}:
        assert execution_path.is_symlink()
    elif execution_node == "fifo":
        assert stat.S_ISFIFO(os.lstat(execution_path).st_mode)
    elif execution_node == "symlinked_attempt":
        assert attempt.is_symlink()
    else:
        assert execution_path.read_bytes() == b"unrecorded\n"
    assert controller.store.list_artifacts(child.id) == artifacts_before
    assert controller.store.list_events(parent.id) == parent_events_before
    assert controller.store.list_events(child.id) == child_events_before


@pytest.mark.parametrize("evidence_name", ["execution.json", ".execution.json.tmp"])
def test_missing_marker_preserves_attempt_when_execution_node_cannot_be_inspected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    evidence_name: str,
) -> None:
    controller, parent, child, result = _evolution_fixture(
        tmp_path, _counted_materialization_source(output=True)
    )
    attempt = _materialization_attempt_path(child, result)
    attempt.mkdir(parents=True)
    sentinel = attempt / "staging-sentinel"
    sentinel.write_text("preserve\n", encoding="utf-8")
    evidence_path = attempt / evidence_name
    artifacts_before = controller.store.list_artifacts(child.id)
    parent_events_before = controller.store.list_events(parent.id)
    child_events_before = controller.store.list_events(child.id)
    original_lstat = os.lstat
    calls = 0

    def fail_selected_lstat(path: str | bytes | os.PathLike[str] | os.PathLike[bytes], *args, **kwargs):
        if Path(path) == evidence_path:
            raise PermissionError("simulated uninspectable execution evidence")
        return original_lstat(path, *args, **kwargs)

    def reject_run(
        self: CommandCandidateRunner,
        candidate_path: Path,
        workspace: Path,
        timeout: float | None = None,
    ):
        del self, candidate_path, workspace, timeout
        nonlocal calls
        calls += 1
        pytest.fail("uninspectable execution evidence replayed the candidate")

    monkeypatch.setattr(CommandCandidateRunner, "run", reject_run)
    with monkeypatch.context() as context:
        context.setattr(os, "lstat", fail_selected_lstat)
        with pytest.raises(
            EvolutionError,
            match="^materialization marker is missing from a recorded attempt$",
        ):
            controller.materialize_evolved_outputs(
                parent.id, child.id, _contract(), result, timeout_seconds=1
            )

    assert calls == 0
    assert sentinel.read_bytes() == b"preserve\n"
    assert attempt.is_dir() and not attempt.is_symlink()
    assert controller.store.list_artifacts(child.id) == artifacts_before
    assert controller.store.list_events(parent.id) == parent_events_before
    assert controller.store.list_events(child.id) == child_events_before


def test_missing_marker_rejects_crash_after_execution_before_artifact_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, parent, child, result = _evolution_fixture(
        tmp_path, _counted_materialization_source(output=True)
    )
    original_run = CommandCandidateRunner.run
    original_record = ArtifactStore.record
    calls = 0

    def counted_run(
        self: CommandCandidateRunner,
        candidate_path: Path,
        workspace: Path,
        timeout: float | None = None,
    ):
        nonlocal calls
        calls += 1
        return original_run(self, candidate_path, workspace, timeout)

    def fail_execution_record(
        self: ArtifactStore,
        path: str | Path,
        task_id: str,
        kind: str = "result",
    ) -> str:
        if kind == "evolved_candidate_execution":
            raise OSError("simulated crash before execution artifact record")
        return original_record(self, path, task_id, kind)

    monkeypatch.setattr(CommandCandidateRunner, "run", counted_run)
    monkeypatch.setattr(ArtifactStore, "record", fail_execution_record)

    with pytest.raises(EvolutionError, match="artifact ledger digest mismatch"):
        controller.materialize_evolved_outputs(
            parent.id, child.id, _contract(), result, timeout_seconds=1
        )

    attempt = _materialization_attempt_path(child, result)
    execution_path = attempt / "execution.json"
    assert calls == 1
    assert execution_path.is_file() and not execution_path.is_symlink()
    execution_before = execution_path.read_bytes()
    assert not (attempt.parent / "result.json").exists()
    assert not any(
        item["kind"] == "evolved_candidate_execution"
        for item in controller.store.list_artifacts(child.id)
    )
    assert not any(
        item["type"] == "evolved_candidate_executed"
        for item in controller.store.list_events(child.id)
    )

    monkeypatch.setattr(ArtifactStore, "record", original_record)
    parent_artifacts = controller.store.list_artifacts(parent.id)
    child_artifacts = controller.store.list_artifacts(child.id)
    parent_events = controller.store.list_events(parent.id)
    child_events = controller.store.list_events(child.id)

    with pytest.raises(
        EvolutionError,
        match="^materialization marker is missing from a recorded attempt$",
    ):
        controller.materialize_evolved_outputs(
            parent.id, child.id, _contract(), result, timeout_seconds=1
        )

    assert calls == 1
    assert execution_path.read_bytes() == execution_before
    assert controller.store.list_artifacts(parent.id) == parent_artifacts
    assert controller.store.list_artifacts(child.id) == child_artifacts
    assert controller.store.list_events(parent.id) == parent_events
    assert controller.store.list_events(child.id) == child_events


def test_execution_evidence_replace_failure_blocks_marker_and_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, parent, child, result = _evolution_fixture(
        tmp_path, _counted_materialization_source(output=True)
    )
    original_replace = os.replace

    def fail_execution_replace(
        source: str | os.PathLike[str],
        target: str | os.PathLike[str],
    ) -> None:
        if Path(source).name == ".execution.json.tmp":
            raise OSError("simulated execution evidence replace failure")
        original_replace(source, target)

    with monkeypatch.context() as context:
        context.setattr(os, "replace", fail_execution_replace)
        with pytest.raises(
            EvolutionError,
            match="^failed materialization has unexpected execution evidence$",
        ):
            controller.materialize_evolved_outputs(
                parent.id, child.id, _contract(), result, timeout_seconds=1
            )

    attempt = _materialization_attempt_path(child, result)
    temporary = attempt / ".execution.json.tmp"
    counter = attempt / "execution-count.txt"
    assert counter.read_text(encoding="utf-8") == "1"
    assert temporary.is_file() and not temporary.is_symlink()
    temporary_before = temporary.read_bytes()
    assert not (attempt / "execution.json").exists()
    assert not (attempt.parent / "result.json").exists()
    parent_artifacts = controller.store.list_artifacts(parent.id)
    child_artifacts = controller.store.list_artifacts(child.id)
    parent_events = controller.store.list_events(parent.id)
    child_events = controller.store.list_events(child.id)

    with pytest.raises(
        EvolutionError,
        match="^materialization marker is missing from a recorded attempt$",
    ):
        controller.materialize_evolved_outputs(
            parent.id, child.id, _contract(), result, timeout_seconds=1
        )

    assert counter.read_text(encoding="utf-8") == "1"
    assert temporary.read_bytes() == temporary_before
    assert controller.store.list_artifacts(parent.id) == parent_artifacts
    assert controller.store.list_artifacts(child.id) == child_artifacts
    assert controller.store.list_events(parent.id) == parent_events
    assert controller.store.list_events(child.id) == child_events


def test_failed_before_execution_marker_rejects_later_temporary_evidence(
    tmp_path: Path,
) -> None:
    controller, parent, child, result = _evolution_fixture(
        tmp_path, "not executable source", filename="candidate.txt"
    )
    first = controller.materialize_evolved_outputs(
        parent.id, child.id, _contract(), result, timeout_seconds=1
    )
    assert first["execution"]["evidence_path"] is None
    attempt = child.workspace / first["attempt_path"]
    temporary = attempt / ".execution.json.tmp"
    temporary.write_text("late execution evidence\n", encoding="utf-8")
    parent_artifacts = controller.store.list_artifacts(parent.id)
    child_artifacts = controller.store.list_artifacts(child.id)
    parent_events = controller.store.list_events(parent.id)
    child_events = controller.store.list_events(child.id)

    with pytest.raises(
        EvolutionError,
        match="^failed materialization has unexpected execution evidence$",
    ):
        controller.materialize_evolved_outputs(
            parent.id, child.id, _contract(), result, timeout_seconds=1
        )

    assert temporary.read_bytes() == b"late execution evidence\n"
    assert controller.store.list_artifacts(parent.id) == parent_artifacts
    assert controller.store.list_artifacts(child.id) == child_artifacts
    assert controller.store.list_events(parent.id) == parent_events
    assert controller.store.list_events(child.id) == child_events


def test_missing_marker_cleans_safe_preexecution_staging_then_runs_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller, parent, child, result = _evolution_fixture(
        tmp_path, _counted_materialization_source(output=True)
    )
    attempt = _materialization_attempt_path(child, result)
    attempt.mkdir(parents=True)
    stale_staging = attempt / "staging-only.txt"
    stale_staging.write_text("safe to replace\n", encoding="utf-8")
    original_run = CommandCandidateRunner.run
    calls = 0

    def counted_run(
        self: CommandCandidateRunner,
        candidate_path: Path,
        workspace: Path,
        timeout: float | None = None,
    ):
        nonlocal calls
        calls += 1
        return original_run(self, candidate_path, workspace, timeout)

    monkeypatch.setattr(CommandCandidateRunner, "run", counted_run)

    materialized = controller.materialize_evolved_outputs(
        parent.id, child.id, _contract(), result, timeout_seconds=1
    )

    assert materialized["status"] == "succeeded"
    assert calls == 1
    assert not stale_staging.exists()
    assert (attempt / "execution.json").is_file()
    assert (attempt.parent / "result.json").is_file()


def test_failed_before_execution_replays_without_execution_authority(
    tmp_path: Path,
) -> None:
    controller, parent, child, result = _evolution_fixture(
        tmp_path, "not executable source", filename="candidate.txt"
    )
    first = controller.materialize_evolved_outputs(
        parent.id, child.id, _contract(), result, timeout_seconds=1
    )
    second = controller.materialize_evolved_outputs(
        parent.id, child.id, _contract(), result, timeout_seconds=1
    )

    assert first == second
    assert first["status"] == "failed"
    assert first["execution"] == {
        "status": "failed",
        "exit_code": None,
        "duration_ms": 0,
        "evidence_path": None,
    }
    assert not any(
        item["type"] == "evolved_candidate_executed"
        for item in controller.store.list_events(child.id)
    )
    assert not any(
        item["kind"] == "evolved_candidate_execution"
        for item in controller.store.list_artifacts(child.id)
    )


@pytest.mark.parametrize(
    "mutation", ["status", "execution", "validation", "outputs", "error"]
)
def test_failed_before_execution_rejects_internally_inconsistent_marker(
    tmp_path: Path,
    mutation: str,
) -> None:
    controller, parent, child, result = _evolution_fixture(
        tmp_path, "not executable source", filename="candidate.txt"
    )
    materialized = controller.materialize_evolved_outputs(
        parent.id, child.id, _contract(), result, timeout_seconds=1
    )
    marker = child.workspace / "evolution" / "materialization" / "result.json"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    if mutation == "status":
        payload["status"] = "succeeded"
    elif mutation == "execution":
        payload["execution"]["status"] = "succeeded"
    elif mutation == "validation":
        payload["validation"]["passed"] = True
    elif mutation == "outputs":
        payload["outputs"] = [{}]
    else:
        payload["error"] = None
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )
    marker.write_bytes(encoded)
    event = next(
        item
        for item in controller.store.list_events(parent.id)
        if item["type"] == "evolved_candidate_materialized"
    )
    event_payload = {key: payload.get(key) for key in event["payload"]}
    with controller.store._connect() as connection:
        connection.execute(
            "UPDATE artifacts SET sha256 = ?, size = ? "
            "WHERE run_id = ? AND path = ? AND kind = ?",
            (
                hashlib.sha256(encoded).hexdigest(),
                len(encoded),
                child.id,
                "evolution/materialization/result.json",
                "evolved_materialization",
            ),
        )
        connection.execute(
            "UPDATE events SET payload = ? WHERE id = ?",
            (json.dumps(event_payload, sort_keys=True), event["id"]),
        )

    _assert_cached_replay_rejected_without_writes(
        controller, parent, child, result, materialized
    )


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


def test_strategy_result_rejects_unknown_strategy() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        StrategyResult(
            strategy="future",
            status="completed",
            iterations=0,
            evaluated_candidates=0,
            valid_candidates=0,
            best_candidate_id=None,
            best_score=None,
            archive_path="evolution/archive.jsonl",
        )


def test_historical_loop_archive_cannot_be_relabeled_by_result_reader(
    tmp_path: Path,
) -> None:
    archive = CandidateArchive(tmp_path)
    source = archive.candidates_root / "candidate-0001" / "candidate.py"
    source.parent.mkdir(parents=True)
    source.write_text("historical = True\n", encoding="utf-8")
    candidate = Candidate(
        candidate_id="candidate-0001",
        code_path=source.relative_to(tmp_path).as_posix(),
        parent_id=None,
        generation=0,
        iteration=1,
        strategy="loop",
        island_id=None,
        evaluation=_valid_report(),
        created_at=1.0,
    )
    archive.archive_path.write_text(
        json.dumps(candidate.to_dict(), ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    historical = archive.result("loop", "completed", 1)
    assert historical.strategy == "loop"
    assert historical.best_candidate_id == candidate.candidate_id
    for active in ("population", "openevolve"):
        with pytest.raises(EvolutionError, match="loop_strategy_retired"):
            archive.result(active, "completed", 1)

    assert {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    } == before


def test_materialization_rejects_retired_child_state_before_candidate_execution(
    tmp_path: Path,
) -> None:
    source = (
        "from pathlib import Path\n"
        "Path('executed.txt').write_text('yes')\n"
        "Path('output').mkdir()\n"
        "Path('output/routes.csv').write_text('item_id,route_id\\n1,A\\n')\n"
    )
    controller, parent, child, result = _evolution_fixture(tmp_path, source)
    state_path = child.workspace / "evolution" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["strategy"] = "loop"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(EvolutionError):
        controller.materialize_evolved_outputs(
            parent.id, child.id, _contract(), result, timeout_seconds=1
        )

    assert not (child.workspace / "evolution" / "materialization").exists()
    assert not (parent.workspace / "output" / "routes.csv").exists()


@pytest.mark.parametrize("tamper", ["strategy", "path"])
def test_materialization_rejects_tampered_archive_identity_before_execution(
    tmp_path: Path,
    tamper: str,
) -> None:
    source = (
        "from pathlib import Path\n"
        "Path('output').mkdir()\n"
        "Path('output/routes.csv').write_text('item_id,route_id\\n1,A\\n')\n"
    )
    controller, parent, child, result = _evolution_fixture(tmp_path, source)
    archive_path = child.workspace / "evolution" / "archive.jsonl"
    records = [
        json.loads(line)
        for line in archive_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if tamper == "strategy":
        records[0]["strategy"] = "openevolve"
    else:
        alternate = archive_path.parent / "candidates" / records[0]["candidate_id"] / "other.py"
        alternate.write_text(source, encoding="utf-8")
        records[0]["code_path"] = alternate.relative_to(child.workspace).as_posix()
    archive_path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )

    with pytest.raises(EvolutionError):
        controller.materialize_evolved_outputs(
            parent.id, child.id, _contract(), result, timeout_seconds=1
        )

    assert not (child.workspace / "evolution" / "materialization").exists()
    assert not (parent.workspace / "output" / "routes.csv").exists()


def test_materialization_rejects_mismatched_parent_evolution_link(
    tmp_path: Path,
) -> None:
    controller, parent, child, result = _evolution_fixture(
        tmp_path,
        "from pathlib import Path\n"
        "Path('output').mkdir()\n"
        "Path('output/routes.csv').write_text('item_id,route_id\\n1,A\\n')\n",
    )
    controller.store.append_event(
        parent.id,
        "evolution_linked",
        {
            "evolution_run_id": child.id,
            "contract_sha256": _contract().digest(),
            "strategy": "openevolve",
        },
    )

    with pytest.raises(EvolutionError, match="evolution link"):
        controller.materialize_evolved_outputs(
            parent.id, child.id, _contract(), result, timeout_seconds=1
        )

    assert not (child.workspace / "evolution" / "materialization").exists()


def test_materialization_rejects_coordinated_strategy_rewrite_against_ledger(
    tmp_path: Path,
) -> None:
    source = (
        "from pathlib import Path\n"
        "Path('output').mkdir()\n"
        "Path('output/routes.csv').write_text('item_id,route_id\\n1,A\\n')\n"
    )
    controller, parent, child, result = _evolution_fixture(tmp_path, source)
    archive_path = child.workspace / "evolution" / "archive.jsonl"
    rewritten_records = []
    for line in archive_path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        record["strategy"] = "openevolve"
        rewritten_records.append(json.dumps(record, sort_keys=True))
    archive_path.write_text("\n".join(rewritten_records) + "\n", encoding="utf-8")

    state_path = child.workspace / "evolution" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["strategy"] = "openevolve"
    state["config"]["strategy"] = "openevolve"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    result_path = child.workspace / "evolution" / "result.json"
    persisted_result = json.loads(result_path.read_text(encoding="utf-8"))
    persisted_result["strategy"] = "openevolve"
    result_path.write_text(json.dumps(persisted_result), encoding="utf-8")

    with pytest.raises(EvolutionError, match="artifact digest"):
        controller.materialize_evolved_outputs(
            parent.id,
            child.id,
            _contract(),
            replace(result, strategy="openevolve"),
            timeout_seconds=1,
        )

    assert not (child.workspace / "evolution" / "materialization").exists()
    assert not (parent.workspace / "output" / "routes.csv").exists()


def test_materialization_accepts_explicit_openevolve_override_of_population_contract(
    tmp_path: Path,
) -> None:
    controller, parent, child, result = _openevolve_fixture(tmp_path)

    materialized = controller.materialize_evolved_outputs(
        parent.id, child.id, _contract(), result, timeout_seconds=2
    )

    assert _contract().evolution.strategy == "population"
    assert result.strategy == "openevolve"
    assert materialized["status"] == "succeeded"
    state = json.loads(
        (child.workspace / "evolution" / "state.json").read_text(encoding="utf-8")
    )
    archive = CandidateArchive(child.workspace).records()
    assert state["strategy"] == state["config"]["strategy"] == "openevolve"
    assert {candidate.strategy for candidate in archive} == {"openevolve"}
    linked = [
        event["payload"]
        for event in controller.store.list_events(parent.id)
        if event["type"] == "evolution_linked"
    ]
    assert linked[-1]["strategy"] == "openevolve"
    assert (parent.workspace / "output" / "routes.csv").is_file()
