import json
from pathlib import Path

import pytest

from famou.algorithm import AlgorithmProblemContract
from famou.artifacts import ArtifactError, ArtifactStore
from famou.cli import _status_payload, main
from famou.config import Config
from famou.controller import LocalController
from famou.conversational import build_algorithm_plan
from famou.runtime import MockRuntime, RuntimeResult
from famou.store import Store


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "handoff-test",
            "problem_type": "routing",
            "statement": "Optimize routes.",
            "inputs": [{"path": "orders.csv", "format": "csv", "fields": {"id": "order"}}],
            "decision_variables": ["route order"],
            "objective": {"name": "distance", "direction": "minimize"},
            "hard_constraints": [],
            "soft_constraints": [],
            "success_criteria": ["Every order is served."],
            "deliverables": ["candidate"],
        }
    )


def test_solve_evolve_links_completed_child_and_returns_best_candidate(tmp_path: Path, capsys) -> None:
    home = tmp_path / "home"
    assert main(
        [
            "solve",
            "optimize a routing algorithm",
            "--runtime",
            "mock",
            "--evolve",
            "--strategy",
            "loop",
            "--max-rounds",
            "2",
            "--json",
            "--home",
            str(home),
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "succeeded"
    evolution = payload["evolution"]
    assert evolution["run_id"]
    assert evolution["status"] == "succeeded"
    assert evolution["result"]["best_candidate_path"]
    assert payload["run_id"] != evolution["run_id"]
    tasks = Store(home / "state.db").list_tasks(payload["run_id"])
    assert [task.state.value for task in tasks[1:]] == ["superseded"] * 4
    status_payload = _status_payload(Config(home), payload["run_id"])
    assert status_payload is not None
    assert status_payload["evolution"]["linked"]["run_id"] == evolution["run_id"]


def test_solve_evolve_resume_reuses_link_and_copies_staged_inputs(tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "orders.csv"
    input_path.write_text("id\n1\n", encoding="utf-8")
    home = tmp_path / "home"
    args = [
        "solve",
        "optimize routes",
        "--runtime",
        "mock",
        "--evolve",
        "--max-rounds",
        "1",
        "--input",
        str(input_path),
        "--json",
        "--home",
        str(home),
    ]
    assert main(args) == 0
    first = json.loads(capsys.readouterr().out)
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
            "1",
            "--json",
            "--home",
            str(home),
        ]
    ) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["evolution"]["run_id"] == first["evolution"]["run_id"]
    child = Path(first["evolution"]["workspace"])
    copied = child / "data" / "raw" / "orders.csv"
    assert copied.read_text(encoding="utf-8") == "id\n1\n"
    assert str(input_path) not in (child / "evolution" / "contract.json").read_text(encoding="utf-8")


def test_solve_evolve_resume_rejects_changed_strategy_settings(tmp_path: Path, capsys) -> None:
    home = tmp_path / "home"
    assert main(
        [
            "solve",
            "optimize routes",
            "--runtime",
            "mock",
            "--evolve",
            "--max-rounds",
            "1",
            "--json",
            "--home",
            str(home),
        ]
    ) == 0
    first = json.loads(capsys.readouterr().out)
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
            "--json",
            "--home",
            str(home),
        ]
    ) == 2
    assert "does not match" in capsys.readouterr().err


def test_supersede_pending_plan_tasks_preserves_intake_success(tmp_path: Path) -> None:
    config = Config(tmp_path / "home")
    controller = LocalController(config, type("Runtime", (), {"name": "mock"})())
    contract = _contract()
    run = controller.create_conversational_run("optimize routes")
    plan = build_algorithm_plan(run.goal, contract)
    controller.store.attach_plan_to_run(run.id, plan)
    assert controller.store.supersede_pending_tasks(run.id, "evolution handoff") == 4
    tasks = controller.store.list_tasks(run.id)
    assert all(task.state.value == "superseded" for task in tasks[1:])


def test_solve_rejects_silent_evolution_controls_without_opt_in(tmp_path: Path, capsys) -> None:
    assert main(
        [
            "solve",
            "optimize routes",
            "--runtime",
            "mock",
            "--max-rounds",
            "2",
            "--json",
            "--home",
            str(tmp_path / "home"),
        ]
    ) == 2
    assert "require --evolve" in capsys.readouterr().err


def test_invalid_evolution_bounds_do_not_create_an_intake_run(tmp_path: Path, capsys) -> None:
    home = tmp_path / "home"
    assert main(
        [
            "solve",
            "optimize routes",
            "--runtime",
            "mock",
            "--evolve",
            "--max-rounds",
            "0",
            "--json",
            "--home",
            str(home),
        ]
    ) == 2
    assert "invalid solve evolution options" in capsys.readouterr().err
    assert not (home / "runs").exists() or not any((home / "runs").iterdir())


def test_copy_staged_inputs_rejects_conflicts_and_symlink_targets(tmp_path: Path) -> None:
    config = Config(tmp_path / "home")
    controller = LocalController(config, type("Runtime", (), {"name": "mock"})())
    source = controller.create_conversational_run("optimize routes")
    source_file = source.workspace / "data" / "raw" / "orders.csv"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("id\n1\n", encoding="utf-8")
    ArtifactStore(source.workspace, controller.store, source.id).record(
        source_file, controller.store.list_tasks(source.id)[0].id, kind="input_data"
    )
    target = controller.create_evolution_run(_contract(), workspace=tmp_path / "child")
    assert controller.copy_staged_inputs(source.id, target.id) == ("data/raw/orders.csv",)
    target_file = target.workspace / "data" / "raw" / "orders.csv"
    target_file.write_text("id\n2\n", encoding="utf-8")
    with pytest.raises(ArtifactError, match="different data"):
        controller.copy_staged_inputs(source.id, target.id)

    symlink_target = controller.create_evolution_run(_contract(), workspace=tmp_path / "child-symlink")
    outside = tmp_path / "outside"
    outside.mkdir()
    symlink_file = symlink_target.workspace / "data" / "raw" / "orders.csv"
    symlink_file.parent.mkdir(parents=True, exist_ok=True)
    symlink_file.symlink_to(outside / "orders.csv")
    with pytest.raises(ArtifactError, match="symlinked"):
        controller.copy_staged_inputs(source.id, symlink_target.id)


def test_answer_continues_a_persisted_evolution_request_after_clarification(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    class ClarifyingRuntime(MockRuntime):
        name = "clarifying-mock"

        def __init__(self) -> None:
            self.compiler_calls = 0

        def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
            if "contract compiler" in prompt:
                self.compiler_calls += 1
                if self.compiler_calls == 1:
                    return RuntimeResult(
                        json.dumps(
                            {
                                "status": "needs_input",
                                "questions": [{"question": "Objective?", "options": ["time"]}],
                            }
                        )
                    )
                return RuntimeResult(json.dumps({"status": "compiled", "contract": _contract().to_dict()}))
            return super().run(prompt, workspace, timeout)

    runtime = ClarifyingRuntime()
    monkeypatch.setattr("famou.cli.build_runtime", lambda *args, **kwargs: runtime)
    home = tmp_path / "home"
    assert main(
        [
            "solve",
            "optimize routes",
            "--runtime",
            "mock",
            "--evolve",
            "--max-rounds",
            "1",
            "--json",
            "--home",
            str(home),
        ]
    ) == 0
    pending = json.loads(capsys.readouterr().out)
    assert pending["status"] == "awaiting_input"
    assert main(
        [
            "answer",
            pending["run_id"],
            "minimize time",
            "--runtime",
            "mock",
            "--json",
            "--home",
            str(home),
        ]
    ) == 0
    completed = json.loads(capsys.readouterr().out)
    assert completed["evolution"]["status"] == "succeeded"
