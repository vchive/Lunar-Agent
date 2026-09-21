"""Cross-entry-point regression checks for the population-first default.

These tests deliberately compare an omitted strategy with an explicit ``population`` request.
The commands use deterministic local fixtures, so the check covers the contract compiler,
conversational solve handoff, standalone evolution, and benchmark construction without invoking a
model, provider, or external evolution framework.
"""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

import pytest

from lunar_evolution.algorithm import (
    LOOP_STRATEGY_RETIRED_MESSAGE,
    AlgorithmProblemContract,
    EvaluationReport,
)
from lunar_evolution.benchmark import BenchmarkRun
from lunar_evolution.cli import main
from lunar_evolution.config import Config
from lunar_evolution.controller import LocalController
from lunar_evolution.conversational import (
    CallableContractCompiler,
    CompilationResult,
    ContractCompilationError,
    RuntimeContractCompiler,
    build_algorithm_plan,
)
from lunar_evolution.evolution import (
    Candidate,
    CandidateArchive,
    CandidateDraft,
    EvolutionConfig,
    EvolutionContext,
    EvolutionError,
    LoopStrategy,
    PopulationStrategy,
    StrategyResult,
)
from lunar_evolution.policy import PlanDocument, PlanPatch
from lunar_evolution.runtime import MockRuntime, RuntimeResult
from lunar_evolution.store import Store


def _contract_payload() -> dict[str, object]:
    """Return a valid contract with the evolution strategy intentionally omitted."""

    return {
        "schema_version": "1",
        "problem_id": "population-default-fixture",
        "problem_type": "routing",
        "statement": "Find a bounded deterministic route.",
        "inputs": [{"path": "items.csv", "format": "csv", "fields": {"id": "item id"}}],
        "decision_variables": ["route order"],
        "objective": {"name": "quality", "direction": "maximize"},
        "hard_constraints": [],
        "soft_constraints": [],
        "success_criteria": ["Every item is served."],
        "deliverables": ["route source"],
    }


def _write_contract(path: Path) -> AlgorithmProblemContract:
    payload = _contract_payload()
    path.write_text(json.dumps(payload), encoding="utf-8")
    return AlgorithmProblemContract.from_dict(payload)


def _write_command_fixtures(root: Path) -> tuple[Path, Path]:
    generator = root / "generator.py"
    generator.write_text(
        "import json, pathlib, sys\n"
        "request = json.loads(pathlib.Path(sys.argv[-1]).read_text())\n"
        "value = int(request['iteration']) + len(request['archive'])\n"
        "print(json.dumps({'source': f'def solve():\\n    return {value}\\n'}))\n",
        encoding="utf-8",
    )
    evaluator = root / "evaluator.py"
    evaluator.write_text(
        "import json\n"
        "print(json.dumps({'schema_version':'1','evaluator_id':'population-default-fixture',"
        "'validity':1,'quality':1,'combined_score':1,'detailed_scores':{},'error_info':[]}))\n",
        encoding="utf-8",
    )
    return generator, evaluator


def _command(path: Path) -> str:
    return shlex.join((sys.executable, str(path)))


def _state_for(result: dict[str, object]) -> dict[str, object]:
    workspace = Path(result["workspace"])
    return json.loads((workspace / "evolution" / "state.json").read_text(encoding="utf-8"))


def _loop_contract_payload() -> dict[str, object]:
    payload = _contract_payload()
    payload["evolution"] = {
        "strategy": "loop",
        "max_rounds": 3,
        "stagnation_rounds": 2,
    }
    return payload


def _algorithm_plan(
    *,
    plan_id: str,
    contract: dict[str, object],
    version: int = 1,
    parent_version: int | None = None,
) -> PlanDocument:
    return PlanDocument.from_dict(
        {
            "plan_id": plan_id,
            "version": version,
            "parent_version": parent_version,
            "goal": "optimize a deterministic route",
            "tasks": [{"id": "solve", "prompt": "write a deterministic route"}],
            "algorithm_problem": contract,
        }
    )


def _write_call_marker_command(root: Path) -> tuple[str, Path]:
    """Return a valid local command whose execution leaves an observable marker."""

    marker = root / "fixture-called"
    fixture = root / "must-not-run.py"
    fixture.write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('called', encoding='utf-8')\n"
        "raise SystemExit(97)\n",
        encoding="utf-8",
    )
    return shlex.join((sys.executable, str(fixture))), marker


def _assert_no_run_or_workspace(home: Path, workspace: Path, marker: Path) -> None:
    assert not workspace.exists()
    assert not marker.exists()
    runs = home / "runs"
    assert not runs.exists() or not any(runs.iterdir())


def _assert_retired_json(capsys) -> None:
    output = capsys.readouterr()
    assert output.out == ""
    payload = json.loads(output.err)
    assert payload["error"] == "loop_strategy_retired"
    assert "population" in payload["message"]
    assert "openevolve" in payload["message"]


def test_contract_compiler_and_plan_materialize_population_by_default(tmp_path: Path) -> None:
    omitted = AlgorithmProblemContract.from_dict(_contract_payload())
    assert omitted.evolution.strategy == "population"

    compiled = RuntimeContractCompiler(MockRuntime()).compile(
        "optimize a deterministic route",
        tmp_path,
    )
    assert compiled.contract is not None
    assert compiled.contract.evolution.strategy == "population"

    plan = build_algorithm_plan("optimize a deterministic route", omitted)
    assert plan.algorithm_problem is not None
    assert plan.algorithm_problem["evolution"]["strategy"] == "population"

    explicit = AlgorithmProblemContract.from_dict(
        {
            **omitted.to_dict(),
            "evolution": {
                "strategy": "population",
                "max_rounds": omitted.evolution.max_rounds,
                "stagnation_rounds": omitted.evolution.stagnation_rounds,
            },
        }
    )
    assert explicit.evolution.strategy == omitted.evolution.strategy
    assert explicit.digest() == omitted.digest()


def test_runtime_contract_compiler_rejects_model_selected_loop_with_fixed_code(
    tmp_path: Path,
) -> None:
    class ExplicitLoopRuntime:
        name = "explicit-loop-contract-fixture"

        def __init__(self) -> None:
            self.calls = 0

        def run(
            self,
            prompt: str,
            workspace: Path,
            timeout: float | None = None,
        ) -> RuntimeResult:
            del prompt, workspace, timeout
            self.calls += 1
            return RuntimeResult(
                json.dumps(
                    {
                        "status": "compiled",
                        "contract": _loop_contract_payload(),
                        "evidence": [],
                    }
                )
            )

    runtime = ExplicitLoopRuntime()
    workspace = tmp_path / "compiler-workspace"
    with pytest.raises(ContractCompilationError) as caught:
        RuntimeContractCompiler(runtime, mock_fallback=False).compile(
            "optimize a deterministic route",
            workspace,
        )

    assert str(caught.value).startswith("loop_strategy_retired:")
    assert "population" in str(caught.value)
    assert "openevolve" in str(caught.value)
    assert runtime.calls == 1
    assert not workspace.exists()


def test_callable_contract_compiler_rejects_loop_result(tmp_path: Path) -> None:
    compiler = CallableContractCompiler(
        lambda goal, workspace, answer=None, timeout=None: CompilationResult(
            "compiled",
            contract=AlgorithmProblemContract.from_dict(_loop_contract_payload()),
        )
    )

    with pytest.raises(ContractCompilationError, match="^loop_strategy_retired:"):
        compiler.compile("optimize a deterministic route", tmp_path)


def test_solve_projects_compiler_selected_loop_and_terminal_resume(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    class LoopContractRuntime:
        name = "loop-contract-runtime-fixture"

        def __init__(self) -> None:
            self.calls = 0

        def run(
            self,
            prompt: str,
            workspace: Path,
            timeout: float | None = None,
        ) -> RuntimeResult:
            del prompt, workspace, timeout
            self.calls += 1
            return RuntimeResult(
                json.dumps({"status": "compiled", "contract": _loop_contract_payload()})
            )

    runtime = LoopContractRuntime()
    monkeypatch.setattr("lunar_evolution.cli.build_runtime", lambda *args, **kwargs: runtime)
    home = tmp_path / "home"
    fresh = [
        "solve",
        "optimize a deterministic route",
        "--runtime",
        "mock",
        "--json",
        "--home",
        str(home),
    ]

    assert main(fresh) == 1
    first_output = capsys.readouterr()
    assert first_output.err == ""
    first = json.loads(first_output.out)
    assert first["status"] == "failed"
    assert first["error"] == "loop_strategy_retired"
    assert "population" in first["message"]
    assert "openevolve" in first["message"]
    assert runtime.calls == 1

    assert main(
        [
            "solve",
            "--resume",
            "--run-id",
            first["run_id"],
            "--runtime",
            "mock",
            "--json",
            "--home",
            str(home),
        ]
    ) == 1
    resumed_output = capsys.readouterr()
    assert resumed_output.err == ""
    resumed = json.loads(resumed_output.out)
    assert resumed["run_id"] == first["run_id"]
    assert resumed["error"] == "loop_strategy_retired"
    assert runtime.calls == 1
    run = Store(home / "state.db").get_run(first["run_id"])
    assert run is not None
    assert run.status.value == "failed"
    assert not (run.workspace / "solve" / "contract.json").exists()
    assert not (run.workspace / "evolution").exists()


def test_answer_projects_compiler_selected_loop(tmp_path: Path, capsys, monkeypatch) -> None:
    class ClarifyingLoopRuntime:
        name = "clarifying-loop-runtime-fixture"

        def __init__(self) -> None:
            self.calls = 0

        def run(
            self,
            prompt: str,
            workspace: Path,
            timeout: float | None = None,
        ) -> RuntimeResult:
            del prompt, workspace, timeout
            self.calls += 1
            if self.calls == 1:
                return RuntimeResult(
                    json.dumps(
                        {
                            "status": "needs_input",
                            "questions": [{"question": "Objective?", "options": ["quality"]}],
                        }
                    )
                )
            return RuntimeResult(
                json.dumps({"status": "compiled", "contract": _loop_contract_payload()})
            )

    runtime = ClarifyingLoopRuntime()
    monkeypatch.setattr("lunar_evolution.cli.build_runtime", lambda *args, **kwargs: runtime)
    home = tmp_path / "home"
    common = ["--runtime", "mock", "--json", "--home", str(home)]

    assert main(["solve", "optimize a deterministic route", *common]) == 0
    pending = json.loads(capsys.readouterr().out)
    assert pending["status"] == "awaiting_input"

    assert main(["answer", pending["run_id"], "quality", *common]) == 1
    answered_output = capsys.readouterr()
    assert answered_output.err == ""
    answered = json.loads(answered_output.out)
    assert answered["status"] == "failed"
    assert answered["error"] == "loop_strategy_retired"
    assert "population" in answered["message"]
    assert "openevolve" in answered["message"]
    assert runtime.calls == 2


def test_cli_plan_rejects_new_loop_contract_before_run_creation(tmp_path: Path, capsys) -> None:
    plan_path = tmp_path / "loop-plan.json"
    plan_path.write_text(
        json.dumps(
            _algorithm_plan(
                plan_id="loop-plan",
                contract=_loop_contract_payload(),
            ).to_dict()
        ),
        encoding="utf-8",
    )
    home = tmp_path / "home"

    assert main(["plan", str(plan_path), "--runtime", "mock", "--json", "--home", str(home)]) == 2

    _assert_retired_json(capsys)
    assert not any((home / "runs").iterdir())
    with Store(home / "state.db")._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_cli_benchmark_rejects_legacy_loop_contract_without_implicit_conversion(
    tmp_path: Path,
    capsys,
) -> None:
    contract_path = tmp_path / "loop-contract.json"
    contract_path.write_text(json.dumps(_loop_contract_payload()), encoding="utf-8")
    command, marker = _write_call_marker_command(tmp_path)
    workspace = tmp_path / "benchmark"
    home = tmp_path / "home"

    assert main(
        [
            "benchmark",
            str(contract_path),
            "--generator-command",
            command,
            "--evaluator-command",
            command,
            "--workspace",
            str(workspace),
            "--json",
            "--home",
            str(home),
        ]
    ) == 2

    _assert_retired_json(capsys)
    _assert_no_run_or_workspace(home, workspace, marker)


@pytest.mark.parametrize(
    ("strategy", "strategy_command"),
    [
        ("population", "--generator-command"),
        ("openevolve", "--openevolve-command"),
    ],
)
def test_cli_evolve_cannot_relabel_legacy_loop_contract(
    tmp_path: Path,
    capsys,
    strategy: str,
    strategy_command: str,
) -> None:
    contract_path = tmp_path / "loop-contract.json"
    contract_path.write_text(json.dumps(_loop_contract_payload()), encoding="utf-8")
    command, marker = _write_call_marker_command(tmp_path)
    workspace = tmp_path / "evolution"
    home = tmp_path / "home"

    assert main(
        [
            "evolve",
            str(contract_path),
            "--strategy",
            strategy,
            strategy_command,
            command,
            "--evaluator-command",
            command,
            "--workspace",
            str(workspace),
            "--json",
            "--home",
            str(home),
        ]
    ) == 2

    _assert_retired_json(capsys)
    _assert_no_run_or_workspace(home, workspace, marker)


def test_solve_evolve_cannot_relabel_historical_loop_plan(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    controller = LocalController(Config(home), MockRuntime())
    legacy = _algorithm_plan(plan_id="legacy-loop-plan", contract=_loop_contract_payload())
    run = controller.store.create_run_with_plan(legacy)
    events_before = controller.store.list_events(run.id)
    files_before = {
        path.relative_to(run.workspace).as_posix(): path.read_bytes()
        for path in run.workspace.rglob("*")
        if path.is_file()
    }

    class MustNotRunRuntime(MockRuntime):
        def run(self, prompt: str, workspace: Path, timeout: float | None = None):
            del prompt, workspace, timeout
            raise AssertionError("historical loop plan reached a runtime boundary")

    monkeypatch.setattr("lunar_evolution.cli.build_runtime", lambda *args, **kwargs: MustNotRunRuntime())

    assert main(
        [
            "solve",
            "--resume",
            "--run-id",
            run.id,
            "--evolve",
            "--strategy",
            "population",
            "--runtime",
            "mock",
            "--json",
            "--home",
            str(home),
        ]
    ) == 2

    _assert_retired_json(capsys)
    with controller.store._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
    assert controller.store.list_events(run.id) == events_before
    assert {
        path.relative_to(run.workspace).as_posix(): path.read_bytes()
        for path in run.workspace.rglob("*")
        if path.is_file()
    } == files_before
    assert not (run.workspace / "evolution-run").exists()


def test_controller_resume_keeps_historical_loop_plan_read_only(tmp_path: Path) -> None:
    class MustNotRunRuntime(MockRuntime):
        def __init__(self) -> None:
            self.calls = 0

        def run(self, prompt: str, workspace: Path, timeout: float | None = None):
            del prompt, workspace, timeout
            self.calls += 1
            raise AssertionError("historical loop plan reached a runtime boundary")

    runtime = MustNotRunRuntime()
    controller = LocalController(Config(tmp_path / "home"), runtime)
    legacy = _algorithm_plan(plan_id="legacy-loop-plan", contract=_loop_contract_payload())
    run = controller.store.create_run_with_plan(legacy)
    events_before = controller.store.list_events(run.id)
    tasks_before = controller.store.list_tasks(run.id)
    files_before = {
        path.relative_to(run.workspace).as_posix(): path.read_bytes()
        for path in run.workspace.rglob("*")
        if path.is_file()
    }

    with pytest.raises(EvolutionError) as caught:
        controller.resume(run.id)

    assert str(caught.value) == LOOP_STRATEGY_RETIRED_MESSAGE
    assert runtime.calls == 0
    assert controller.store.get_run(run.id) == run
    assert controller.store.list_tasks(run.id) == tasks_before
    assert controller.store.list_events(run.id) == events_before
    assert {
        path.relative_to(run.workspace).as_posix(): path.read_bytes()
        for path in run.workspace.rglob("*")
        if path.is_file()
    } == files_before


def test_answer_keeps_historical_loop_plan_read_only(
    tmp_path: Path,
    capsys,
) -> None:
    home = tmp_path / "home"
    controller = LocalController(Config(home), MockRuntime())
    legacy = _algorithm_plan(plan_id="legacy-loop-plan", contract=_loop_contract_payload())
    run = controller.store.create_run_with_plan(legacy)
    task = controller.store.next_task(run.id)
    assert task is not None
    attempt = controller.store.claim_task(task.id, "historical-fixture")
    assert attempt is not None
    assert controller.store.await_input(
        task.id,
        attempt.id,
        f"tasks/{task.id}/input-request.json",
        "Choose an objective",
        ["quality"],
    )
    run_before = controller.store.get_run(run.id)
    pending_before = controller.store.pending_input(run.id)
    tasks_before = controller.store.list_tasks(run.id)
    events_before = controller.store.list_events(run.id)
    files_before = {
        path.relative_to(run.workspace).as_posix(): path.read_bytes()
        for path in run.workspace.rglob("*")
        if path.is_file()
    }

    assert main(
        [
            "answer",
            run.id,
            "quality",
            "--runtime",
            "mock",
            "--json",
            "--home",
            str(home),
        ]
    ) == 2

    _assert_retired_json(capsys)
    persisted = Store(home / "state.db")
    assert persisted.get_run(run.id) == run_before
    assert persisted.pending_input(run.id) == pending_before
    assert persisted.list_tasks(run.id) == tasks_before
    assert persisted.list_events(run.id) == events_before
    assert {
        path.relative_to(run.workspace).as_posix(): path.read_bytes()
        for path in run.workspace.rglob("*")
        if path.is_file()
    } == files_before


def test_replan_rejects_new_loop_contract_before_revision_mutation(tmp_path: Path) -> None:
    controller = LocalController(Config(tmp_path / "home"), MockRuntime())
    original = _algorithm_plan(plan_id="active-plan", contract=_contract_payload())
    run = controller.start_plan(original)
    manifest = run.workspace / "algorithm-workspace.json"
    manifest_before = manifest.read_bytes()
    events_before = controller.store.list_events(run.id)
    revised = _algorithm_plan(
        plan_id=original.plan_id,
        contract=_loop_contract_payload(),
        version=2,
        parent_version=1,
    )

    with pytest.raises(EvolutionError, match="^loop_strategy_retired:"):
        controller.replan(run.id, revised, "request a retired strategy")

    current = controller.store.get_current_plan(run.id)
    assert current is not None and current.version == 1
    assert len(controller.store.list_plan_revisions(run.id)) == 1
    assert controller.store.list_events(run.id) == events_before
    assert manifest.read_bytes() == manifest_before


def test_patch_rejects_historical_loop_plan_before_revision_mutation(tmp_path: Path) -> None:
    controller = LocalController(Config(tmp_path / "home"), MockRuntime())
    legacy = _algorithm_plan(plan_id="legacy-loop-plan", contract=_loop_contract_payload())
    run = controller.store.create_run_with_plan(legacy)
    events_before = controller.store.list_events(run.id)
    patch = PlanPatch(
        plan_id=legacy.plan_id,
        base_version=1,
        reason="attempt to modify a historical plan",
        operations=({"op": "update_task", "id": "solve", "prompt": "changed"},),
    )

    with pytest.raises(EvolutionError, match="^loop_strategy_retired:"):
        controller.patch_plan(run.id, patch)

    current = controller.store.get_current_plan(run.id)
    assert current is not None and current.version == 1
    assert len(controller.store.list_plan_revisions(run.id)) == 1
    assert controller.store.list_events(run.id) == events_before


def test_replan_cannot_relabel_historical_loop_plan_as_population(
    tmp_path: Path,
) -> None:
    controller = LocalController(Config(tmp_path / "home"), MockRuntime())
    legacy = _algorithm_plan(plan_id="legacy-loop-plan", contract=_loop_contract_payload())
    run = controller.store.create_run_with_plan(legacy)
    events_before = controller.store.list_events(run.id)
    workspace_before = {
        path.relative_to(run.workspace).as_posix(): path.read_bytes()
        for path in run.workspace.rglob("*")
        if path.is_file()
    }
    revised = _algorithm_plan(
        plan_id=legacy.plan_id,
        contract=_contract_payload(),
        version=2,
        parent_version=1,
    )

    with pytest.raises(EvolutionError, match="^loop_strategy_retired:"):
        controller.replan(run.id, revised, "silently relabel the historical strategy")

    current = controller.store.get_current_plan(run.id)
    assert current is not None and current.version == 1
    assert current.algorithm_problem is not None
    assert current.algorithm_problem["evolution"]["strategy"] == "loop"
    assert len(controller.store.list_plan_revisions(run.id)) == 1
    assert controller.store.list_events(run.id) == events_before
    assert {
        path.relative_to(run.workspace).as_posix(): path.read_bytes()
        for path in run.workspace.rglob("*")
        if path.is_file()
    } == workspace_before


def test_population_strategy_rejects_legacy_contract_before_workspace_mutation(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "population"
    context = EvolutionContext(
        AlgorithmProblemContract.from_dict(_loop_contract_payload()),
        workspace,
        lambda request: CandidateDraft("def solve():\n    return 1\n"),
        lambda path, contract: EvaluationReport.from_dict(
            {
                "schema_version": "1",
                "evaluator_id": "must-not-run",
                "validity": 1,
                "quality": 1,
                "combined_score": 1,
                "detailed_scores": {},
                "error_info": [],
            }
        ),
        EvolutionConfig(),
    )

    with pytest.raises(EvolutionError, match="^loop_strategy_retired:"):
        PopulationStrategy(context)

    assert not workspace.exists()


def test_materialization_rejects_historical_loop_result_before_run_lookup(
    tmp_path: Path,
) -> None:
    controller = LocalController(Config(tmp_path / "home"), MockRuntime())
    result = StrategyResult(
        strategy="loop",
        status="completed",
        iterations=1,
        evaluated_candidates=1,
        valid_candidates=1,
        best_candidate_id="candidate-0001",
        best_score=1.0,
        best_candidate_path="evolution/candidates/candidate-0001/candidate.py",
        archive_path="evolution/archive.jsonl",
    )

    with pytest.raises(EvolutionError, match="^loop_strategy_retired:"):
        controller.materialize_evolved_outputs(
            "missing-parent",
            "missing-evolution",
            AlgorithmProblemContract.from_dict(_loop_contract_payload()),
            result,
        )


@pytest.mark.parametrize("entrypoint", ["solve", "evolve", "benchmark"])
def test_cli_rejects_explicit_loop_after_parsing_without_starting_work(
    tmp_path: Path,
    capsys,
    entrypoint: str,
) -> None:
    case_root = tmp_path / entrypoint
    case_root.mkdir()
    home = case_root / "home"
    workspace = case_root / "workspace"
    command, marker = _write_call_marker_command(case_root)

    if entrypoint == "solve":
        arguments = [
            "solve",
            "optimize a deterministic route",
            "--runtime",
            "subprocess",
            "--command",
            command,
            "--evolve",
            "--strategy",
            "loop",
        ]
    else:
        contract_path = case_root / "contract.json"
        _write_contract(contract_path)
        arguments = [
            entrypoint,
            str(contract_path),
            "--strategy",
            "loop",
            "--generator-command",
            command,
            "--evaluator-command",
            command,
        ]
    arguments.extend(
        [
            "--workspace",
            str(workspace),
            "--json",
            "--home",
            str(home),
        ]
    )

    assert main(arguments) == 2
    _assert_retired_json(capsys)
    _assert_no_run_or_workspace(home, workspace, marker)


def test_retired_loop_strategy_run_and_resume_do_not_mutate_or_call_callbacks(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "legacy-loop"
    workspace.mkdir()
    sentinel = workspace / "historical.json"
    sentinel.write_text('{"strategy":"loop"}\n', encoding="utf-8")
    calls = {"generate": 0, "evaluate": 0}

    def generate(_request):
        calls["generate"] += 1
        return CandidateDraft("raise AssertionError('retired loop generator ran')\n")

    def evaluate(_path, _contract):
        calls["evaluate"] += 1
        raise AssertionError("retired loop evaluator ran")

    strategy = LoopStrategy(
        EvolutionContext(
            AlgorithmProblemContract.from_dict(_loop_contract_payload()),
            workspace,
            generate,
            evaluate,
            EvolutionConfig(),
        )
    )
    before = {
        path.relative_to(workspace).as_posix(): path.read_bytes()
        for path in workspace.rglob("*")
        if path.is_file()
    }

    for operation in (strategy.run, strategy.resume):
        with pytest.raises(EvolutionError) as caught:
            operation()
        assert str(caught.value).startswith("loop_strategy_retired")

    after = {
        path.relative_to(workspace).as_posix(): path.read_bytes()
        for path in workspace.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert calls == {"generate": 0, "evaluate": 0}
    assert not (workspace / "evolution").exists()


@pytest.mark.parametrize(
    ("strategy", "message"),
    [("loop", LOOP_STRATEGY_RETIRED_MESSAGE), ("unknown", "unsupported candidate strategy")],
)
def test_candidate_archive_rejects_explicit_inactive_state_strategy_before_layout(
    tmp_path: Path,
    strategy: str,
    message: str,
) -> None:
    workspace = tmp_path / strategy
    archive = CandidateArchive(workspace)
    sentinel = workspace / "historical.json"
    sentinel.write_text('{"preserve":true}\n', encoding="utf-8")
    before = sentinel.read_bytes()

    with pytest.raises(EvolutionError) as caught:
        archive.write_state({"schema_version": "1", "strategy": strategy})

    assert str(caught.value) == message
    assert sentinel.read_bytes() == before
    assert not archive.root.exists()
    assert not archive.state_path.exists()


def test_legacy_loop_contract_and_benchmark_run_remain_readable() -> None:
    legacy_contract = AlgorithmProblemContract.from_dict(_loop_contract_payload())
    assert legacy_contract.evolution.strategy == "loop"
    assert (
        AlgorithmProblemContract.from_dict(legacy_contract.to_dict()).digest()
        == legacy_contract.digest()
    )

    payload = {
        "strategy": "loop",
        "status": "completed",
        "elapsed_ms": 125,
        "evaluated_candidates": 3,
        "valid_candidates": 2,
        "best_score": 4.5,
        "best_candidate_path": "strategies/loop/evolution/candidates/candidate-3.py",
        "workspace": "strategies/loop",
        "archive": "strategies/loop/evolution/archive.jsonl",
        "error": None,
    }
    historical = BenchmarkRun(**payload)
    assert historical.to_dict() == payload


def test_historical_loop_candidate_archive_and_result_are_read_only(tmp_path: Path) -> None:
    archive = CandidateArchive(tmp_path)
    legacy_source = tmp_path / "evolution" / "candidates" / "candidate-0001" / "candidate.py"
    legacy_source.parent.mkdir(parents=True)
    legacy_source.write_text("def solve():\n    return 1\n", encoding="utf-8")
    candidate = Candidate(
        candidate_id="candidate-0001",
        code_path=legacy_source.relative_to(tmp_path).as_posix(),
        parent_id=None,
        generation=0,
        iteration=1,
        strategy="loop",
        island_id=None,
        evaluation=EvaluationReport.from_dict(
            {
                "schema_version": "1",
                "evaluator_id": "historical-fixture",
                "validity": 1,
                "quality": 1,
                "combined_score": 1,
                "detailed_scores": {},
                "error_info": [],
            }
        ),
        created_at=1.0,
    )
    archive.archive_path.write_text(json.dumps(candidate.to_dict()) + "\n", encoding="utf-8")
    before = archive.archive_path.read_bytes()

    assert [item.strategy for item in archive.records()] == ["loop"]
    assert Candidate.from_dict(archive.records()[0].to_dict()).strategy == "loop"
    historical_result = archive.result("loop", "completed", 1)
    assert historical_result.strategy == "loop"
    assert historical_result.best_candidate_id == "candidate-0001"
    assert archive.archive_path.read_bytes() == before


def test_solve_evolve_omitted_strategy_matches_explicit_population(
    tmp_path: Path, capsys
) -> None:
    def run(home: Path, explicit: bool) -> tuple[dict[str, object], dict[str, object]]:
        args = [
            "solve",
            "optimize a deterministic route",
            "--runtime",
            "mock",
            "--evolve",
            "--max-rounds",
            "1",
            "--population-size",
            "1",
            "--offspring-per-iteration",
            "1",
            "--seed",
            "7",
            "--json",
            "--home",
            str(home),
        ]
        if explicit:
            args[args.index("--evolve") + 1 : args.index("--max-rounds")] = [
                "--strategy",
                "population",
            ]
        assert main(args) == 0
        output = capsys.readouterr()
        assert not output.err
        payload = json.loads(output.out)
        return payload, _state_for(payload["evolution"])

    omitted, omitted_state = run(tmp_path / "solve-omitted", False)
    explicit, explicit_state = run(tmp_path / "solve-explicit", True)

    assert omitted["evolution"]["strategy"] == explicit["evolution"]["strategy"] == "population"
    assert omitted["compiler"]["contract_sha256"] == explicit["compiler"]["contract_sha256"]
    assert omitted_state["config"] == explicit_state["config"]
    assert omitted_state["strategy"] == explicit_state["strategy"] == "population"


def test_standalone_evolve_omitted_strategy_matches_explicit_population(
    tmp_path: Path, capsys
) -> None:
    contract_path = tmp_path / "contract.json"
    contract = _write_contract(contract_path)
    generator, evaluator = _write_command_fixtures(tmp_path)

    def run(home: Path, explicit: bool) -> tuple[dict[str, object], dict[str, object]]:
        args = [
            "evolve",
            str(contract_path),
            "--generator-command",
            _command(generator),
            "--evaluator-command",
            _command(evaluator),
            "--max-rounds",
            "1",
            "--population-size",
            "1",
            "--offspring-per-iteration",
            "1",
            "--seed",
            "7",
            "--json",
            "--home",
            str(home),
        ]
        if explicit:
            args[2:2] = ["--strategy", "population"]
        assert main(args) == 0
        output = capsys.readouterr()
        assert not output.err
        payload = json.loads(output.out)
        return payload, _state_for(payload)

    omitted, omitted_state = run(tmp_path / "evolve-omitted", False)
    explicit, explicit_state = run(tmp_path / "evolve-explicit", True)

    assert omitted["strategy"] == explicit["strategy"] == "population"
    assert omitted["contract_sha256"] == explicit["contract_sha256"] == contract.digest()
    assert omitted_state["config"] == explicit_state["config"]
    assert omitted_state["strategy"] == explicit_state["strategy"] == "population"


def test_benchmark_omitted_strategy_matches_explicit_population(tmp_path: Path, capsys) -> None:
    contract_path = tmp_path / "contract.json"
    contract = _write_contract(contract_path)
    generator, evaluator = _write_command_fixtures(tmp_path)

    def run(workspace: Path, explicit: bool) -> dict[str, object]:
        args = [
            "benchmark",
            str(contract_path),
            "--generator-command",
            _command(generator),
            "--evaluator-command",
            _command(evaluator),
            "--max-rounds",
            "1",
            "--population-size",
            "1",
            "--offspring-per-iteration",
            "1",
            "--seed",
            "7",
            "--json",
            "--workspace",
            str(workspace),
            "--home",
            str(workspace.parent / "home"),
        ]
        if explicit:
            args[2:2] = ["--strategy", "population"]
        assert main(args) == 0
        output = capsys.readouterr()
        assert not output.err
        return json.loads(output.out)

    omitted = run(tmp_path / "benchmark-omitted", False)
    explicit = run(tmp_path / "benchmark-explicit", True)

    assert omitted["contract_sha256"] == explicit["contract_sha256"] == contract.digest()
    assert omitted["config"] == explicit["config"]
    assert omitted["config"]["strategies"] == ["population"]
    assert [item["strategy"] for item in omitted["runs"]] == ["population"]
    assert [item["strategy"] for item in explicit["runs"]] == ["population"]
