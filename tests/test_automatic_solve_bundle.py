"""Automatically prepared exact bundle profiles retain and validate their full authority."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest
from test_frozen_evaluator_bundle import EVALUATOR_SOURCE, BundleRuntime, _contract, _envelope

from famou.automatic_solve_bundle import (
    prepare_automatic_solve_bundle,
    validate_automatic_solve_bundle,
)
from famou.budget import BudgetSpec
from famou.bundle_evolution import load_bundle_pipeline
from famou.config import Config
from famou.controller import LocalController
from famou.conversational import build_algorithm_plan
from famou.evaluator_bundle import compile_evaluator_bundle
from famou.evolution import (
    CandidateDraft,
    CandidateInputArtifact,
    EvolutionConfig,
    EvolutionContext,
    EvolutionError,
    PopulationStrategy,
)
from famou.solve_bundle import bundle_pipeline_sha256

SNAPSHOT_SOURCE = EVALUATOR_SOURCE.replace(
    '"evaluator_id": "frozen-exact-cost"', '"evaluator_id": "compiled-bundle"',
).replace(
    "    candidate = Path(sys.argv[1])\n    root = candidate.parent\n",
    '    request = json.loads(Path(sys.argv[1]).read_text())\n'
    '    assert request["protocol"] == "lunar-candidate-evaluation-request-v1"\n'
    '    root = Path.cwd()\n',
).replace('root / "data/raw/orders.csv"', 'root / "inputs/orders.csv"')


def _fixture(tmp_path, *, budget=None):
    contract = _contract()
    runtime = BundleRuntime(_envelope(SNAPSHOT_SOURCE))
    controller = LocalController(Config(tmp_path / "home"), runtime)
    parent = controller.create_conversational_run("Assign orders at minimum cost", workspace=tmp_path / "parent")
    task = controller.store.list_tasks(parent.id)[0]
    attempt = controller.store.claim_task(task.id, "fixture")
    controller.store.finish_task(task.id, attempt.id, True)
    plan = build_algorithm_plan(parent.goal, contract)
    if budget is not None:
        plan = replace(plan, budget=BudgetSpec(max_artifact_bytes=budget))
    controller.store.attach_plan_to_run(parent.id, plan)
    _record_input(controller, parent, task.id, "orders.csv", b"id\nobserved-order\n")
    return controller, parent, contract, runtime


def _record_input(controller, parent, task_id, name, content, *, digest=None):
    target = parent.workspace / "data/raw" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    controller.store.add_artifact(
        parent.id, task_id, "data/raw/" + name,
        digest or hashlib.sha256(content).hexdigest(), len(content), "input_data",
    )


def _prepare(fixture):
    controller, parent, contract, _ = fixture
    return prepare_automatic_solve_bundle(controller, parent.id, contract, timeout_seconds=3)


def _snapshot(controller, parent):
    files = {path.relative_to(parent.workspace).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
             for path in parent.workspace.rglob("*") if path.is_file()}
    return files, controller.store.list_artifacts(parent.id), controller.store.list_events(parent.id)


def _prepared_events(controller, parent):
    return [event for event in controller.store.list_events(parent.id) if event["type"] == "bundle_profile_prepared"]


def _write_frozen(path, content):
    path.chmod(0o644)
    path.write_bytes(content)
    path.chmod(0o444)


def test_prepare_freezes_snapshot_evaluator_and_indexes_profile_and_evidence(tmp_path):
    fixture = _fixture(tmp_path)
    controller, parent, contract, runtime = fixture

    pipeline = _prepare(fixture)

    assert (runtime.bundle_calls, runtime.audit_calls) == (1, 1)
    assert (runtime.generation_calls, runtime.evaluator_calls) == (0, 0)
    assert pipeline.input_root == parent.workspace / "data/raw"
    assert pipeline.harness_path == parent.workspace / "evaluator-bundle/evaluator.py"
    assert pipeline.evaluator.evaluator_id == "compiled-bundle"
    assert [(item.target, item.source_label, item.size, item.sha256) for item in pipeline.inputs] == [
        ("orders.csv", "parent-input", 18, hashlib.sha256(b"id\nobserved-order\n").hexdigest()),
    ]
    profile = load_bundle_pipeline(parent.workspace / "bundle-profile.json")
    assert bundle_pipeline_sha256(profile) == bundle_pipeline_sha256(pipeline)
    assert profile.harness_path == pipeline.harness_path
    evidence = {path.relative_to(parent.workspace).as_posix(): path.read_bytes()
                for path in (parent.workspace / "evaluator-bundle").iterdir()}
    evidence["bundle-profile.json"] = (parent.workspace / "bundle-profile.json").read_bytes()
    rows = controller.store.list_artifacts(parent.id)
    for path, content in evidence.items():
        matches = [row for row in rows if row["path"] == path]
        assert len(matches) == 1
        assert matches[0]["size"] == len(content)
        assert matches[0]["sha256"] == hashlib.sha256(content).hexdigest()
    events = _prepared_events(controller, parent)
    assert len(events) == 1
    pins = json.dumps(events[0]["payload"])
    assert contract.digest() in pins
    assert bundle_pipeline_sha256(pipeline) in pins
    assert hashlib.sha256(evidence["bundle-profile.json"]).hexdigest() in pins
    assert not (parent.workspace / "evolution-run").exists()


def test_prepared_profile_drives_real_multifile_execution_and_snapshot_scoring(tmp_path):
    fixture = _fixture(tmp_path)
    _, parent, contract, runtime = fixture
    pipeline = _prepare(fixture)
    costs = iter((9, 5, 1))

    def generate(_request):
        return CandidateDraft.from_files({
            "solve/main.py": (
                "import csv, os\nfrom pathlib import Path\nfrom helper import route_cost\n"
                "with (Path(os.environ['LUNAR_CANDIDATE_INPUT_ROOT'])/'orders.csv').open(newline='') as stream:\n"
                "    orders=list(csv.DictReader(stream))\n"
                "Path('output').mkdir(exist_ok=True)\n"
                "body='item_id,route_id,cost\\n'+''.join(f\"{row['id']},r1,{route_cost()}\\n\" for row in orders)\n"
                "Path('output/routes.csv').write_text(body)\n"
            ),
            "solve/helper.py": f"def route_cost():\n    return {next(costs)}\n",
        }, entrypoint="solve/main.py")

    result = PopulationStrategy(EvolutionContext(
        contract=contract, workspace=parent.workspace / "independent-pipeline", generate=generate,
        evaluate=pipeline, bundle_pipeline=pipeline,
        config=pipeline.configure(EvolutionConfig(
            strategy="population", max_rounds=1, stagnation_rounds=3, population_size=2,
            offspring_per_iteration=1, num_islands=1, rng_seed=7,
        )),
    )).run()

    assert result.status == "completed"
    assert result.evaluated_candidates == result.valid_candidates == 3
    assert result.best_score == 0.5
    assert (runtime.bundle_calls, runtime.audit_calls) == (1, 1)
    assert runtime.evaluator_calls == 0


def test_prepare_resume_and_readonly_validation_preserve_files_rows_and_model_counts(tmp_path):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture
    first = _prepare(fixture)
    before = _snapshot(controller, parent)

    validate_automatic_solve_bundle(controller.store, parent.id)
    resumed = _prepare(fixture)

    assert bundle_pipeline_sha256(resumed) == bundle_pipeline_sha256(first)
    assert _snapshot(controller, parent) == before
    assert (runtime.bundle_calls, runtime.audit_calls) == (1, 1)


@pytest.mark.parametrize("changed", ["missing_input", "extra_input", "conflicting_input"])
def test_invalid_initial_input_ledger_rejects_before_evaluator_models(tmp_path, changed):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture
    if changed == "missing_input":
        (parent.workspace / "data/raw/orders.csv").unlink()
    else:
        task_id = controller.store.list_tasks(parent.id)[0].id
        if changed == "extra_input":
            _record_input(controller, parent, task_id, "extra.csv", b"id\nextra\n")
        else:
            _record_input(controller, parent, task_id, "orders.csv", b"id\nobserved-order\n", digest="e" * 64)
    before = _snapshot(controller, parent)

    with pytest.raises((EvolutionError, ValueError)):
        _prepare(fixture)

    after_files, after_artifacts, after_events = _snapshot(controller, parent)
    after_files.pop(".bundle-profile.lock", None)
    assert (after_files, after_artifacts, after_events) == before
    assert (runtime.bundle_calls, runtime.audit_calls) == (0, 0)


@pytest.mark.parametrize("changed", ["profile", "evaluator", "manifest", "objective", "input_bytes", "extra_input", "conflicting_input"])
def test_prepared_authority_drift_rejects_without_recompile_or_ledger_writes(tmp_path, changed):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture
    _prepare(fixture)
    if changed == "profile":
        path = parent.workspace / "bundle-profile.json"
        payload = json.loads(path.read_text())
        payload["dependency_sha256"] = "e" * 64
        _write_frozen(path, json.dumps(payload).encode())
    elif changed in {"evaluator", "manifest", "objective"}:
        name = {"evaluator": "evaluator.py", "manifest": "manifest.json", "objective": "objective.md"}[changed]
        path = parent.workspace / "evaluator-bundle" / name
        _write_frozen(path, path.read_bytes() + b"\nchanged\n")
    elif changed == "input_bytes":
        (parent.workspace / "data/raw/orders.csv").write_bytes(b"id\nchanged-order\n")
    else:
        task_id = controller.store.list_tasks(parent.id)[0].id
        if changed == "extra_input":
            _record_input(controller, parent, task_id, "extra.csv", b"id\nextra\n")
        else:
            _record_input(controller, parent, task_id, "orders.csv", b"id\nobserved-order\n", digest="e" * 64)
    before = _snapshot(controller, parent)

    with pytest.raises((EvolutionError, ValueError)):
        validate_automatic_solve_bundle(controller.store, parent.id)
    with pytest.raises((EvolutionError, ValueError)):
        _prepare(fixture)

    assert _snapshot(controller, parent) == before
    assert (runtime.bundle_calls, runtime.audit_calls) == (1, 1)


@pytest.mark.parametrize("changed", ["missing_input_row", "missing_evidence_row", "changed_evidence_row"])
def test_prepared_artifact_ledger_drift_rejects_even_when_file_bytes_match(tmp_path, changed):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture
    _prepare(fixture)
    with controller.store._connect() as connection:
        if changed == "missing_input_row":
            connection.execute("DELETE FROM artifacts WHERE run_id = ? AND kind = 'input_data'", (parent.id,))
        elif changed == "missing_evidence_row":
            connection.execute("DELETE FROM artifacts WHERE run_id = ? AND path = 'bundle-profile.json'", (parent.id,))
        else:
            connection.execute("UPDATE artifacts SET sha256 = ? WHERE run_id = ? AND path = 'bundle-profile.json'", ("e" * 64, parent.id))
    before = _snapshot(controller, parent)

    with pytest.raises((EvolutionError, ValueError)):
        validate_automatic_solve_bundle(controller.store, parent.id)
    with pytest.raises((EvolutionError, ValueError)):
        _prepare(fixture)

    assert _snapshot(controller, parent) == before
    assert (runtime.bundle_calls, runtime.audit_calls) == (1, 1)


@pytest.mark.parametrize("relative", [
    "bundle-profile.json", "evaluator-bundle/evaluator.py", "evaluator-bundle/manifest.json",
    "evaluator-bundle/objective.md", "evaluator-bundle/probes.json", "evaluator-bundle/audit.json",
    "evaluator-bundle/input-profile.json", "data/raw/orders.csv",
])
def test_missing_prepared_files_reject_instead_of_rebuilding(tmp_path, relative):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture
    _prepare(fixture)
    target = parent.workspace / relative
    target.parent.chmod(0o755)
    target.unlink()
    before = _snapshot(controller, parent)

    with pytest.raises((EvolutionError, ValueError)):
        validate_automatic_solve_bundle(controller.store, parent.id)
    with pytest.raises((EvolutionError, ValueError)):
        _prepare(fixture)

    assert _snapshot(controller, parent) == before
    assert (runtime.bundle_calls, runtime.audit_calls) == (1, 1)


def test_profile_row_without_marker_does_not_authorize_rebuilding_a_missing_profile(tmp_path):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture
    _prepare(fixture)
    # The state immediately before marker commit has all evidence rows but no prepared event.
    with controller.store._connect() as connection:
        connection.execute("DELETE FROM events WHERE run_id = ? AND type = 'bundle_profile_prepared'", (parent.id,))
    (parent.workspace / "bundle-profile.json").unlink()
    assert not _prepared_events(controller, parent)
    before = _snapshot(controller, parent)

    with pytest.raises((EvolutionError, ValueError)):
        validate_automatic_solve_bundle(controller.store, parent.id)
    with pytest.raises((EvolutionError, ValueError)):
        _prepare(fixture)

    assert _snapshot(controller, parent) == before
    assert (runtime.bundle_calls, runtime.audit_calls) == (1, 1)


def test_completed_frozen_bundle_without_prepared_marker_recovers_without_model_work(tmp_path):
    fixture = _fixture(tmp_path)
    controller, parent, contract, runtime = fixture
    content = (parent.workspace / "data/raw/orders.csv").read_bytes()
    frozen = compile_evaluator_bundle(
        runtime, contract, parent.workspace,
        inputs=(CandidateInputArtifact("data/raw/orders.csv", len(content), hashlib.sha256(content).hexdigest()),),
        timeout=3, invocation="snapshot",
    )
    assert not _prepared_events(controller, parent)
    assert not (parent.workspace / "bundle-profile.json").exists()

    pipeline = _prepare(fixture)

    assert pipeline.harness_path == frozen.root / "evaluator.py"
    assert (runtime.bundle_calls, runtime.audit_calls) == (1, 1)
    assert len(_prepared_events(controller, parent)) == 1
    validate_automatic_solve_bundle(controller.store, parent.id)


@pytest.mark.parametrize("registered", [False, True])
def test_child_without_prepared_authority_cannot_trigger_compilation(tmp_path, registered):
    fixture = _fixture(tmp_path)
    controller, parent, contract, runtime = fixture
    child_root = parent.workspace / "evolution-run"
    if registered:
        controller.create_evolution_run(contract, workspace=child_root)
    else:
        child_root.mkdir()
    before = _snapshot(controller, parent)

    with pytest.raises((EvolutionError, ValueError)):
        _prepare(fixture)

    assert _snapshot(controller, parent) == before
    assert (runtime.bundle_calls, runtime.audit_calls) == (0, 0)


def test_preparation_budget_includes_every_byte_of_frozen_evidence_and_profile(tmp_path):
    reference = _fixture(tmp_path / "reference")
    _prepare(reference)
    reference_controller, reference_parent, _, _ = reference
    required = sum(row["size"] for row in reference_controller.store.list_artifacts(reference_parent.id))
    fixture = _fixture(tmp_path / "bounded", budget=required - 1)
    controller, parent, _, runtime = fixture
    before = controller.store.list_artifacts(parent.id)

    with pytest.raises((EvolutionError, ValueError), match="budget"):
        _prepare(fixture)

    assert controller.store.list_artifacts(parent.id) == before
    assert not _prepared_events(controller, parent)
    assert (runtime.bundle_calls, runtime.audit_calls) == (1, 1)

    with controller.store._connect() as connection:
        connection.execute("UPDATE runs SET budget = ? WHERE id = ?", (
            json.dumps(BudgetSpec(max_artifact_bytes=required).to_dict()), parent.id,
        ))
    _prepare(fixture)
    rows = controller.store.list_artifacts(parent.id)
    assert sum(row["size"] for row in rows) == required
    assert len(_prepared_events(controller, parent)) == 1
    assert (runtime.bundle_calls, runtime.audit_calls) == (1, 1)


def test_preparation_observes_budget_lowered_during_evaluator_audit(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture
    run = runtime.run

    def lower_budget_after_audit(prompt, workspace, timeout=None):
        result = run(prompt, workspace, timeout)
        if "adversarial evaluator auditor" in prompt:
            with controller.store._connect() as connection:
                connection.execute("UPDATE runs SET budget = ? WHERE id = ?", (
                    json.dumps(BudgetSpec(max_artifact_bytes=18).to_dict()), parent.id,
                ))
        return result

    monkeypatch.setattr(runtime, "run", lower_budget_after_audit)
    before = controller.store.list_artifacts(parent.id)

    with pytest.raises((EvolutionError, ValueError), match="budget"):
        _prepare(fixture)

    assert controller.store.list_artifacts(parent.id) == before
    assert not _prepared_events(controller, parent)


@pytest.mark.parametrize("stage", ["during_artifacts", "before_marker"])
def test_interrupted_evidence_registration_recovers_without_recompiling(tmp_path, monkeypatch, stage):
    fixture = _fixture(tmp_path)
    controller, parent, _, runtime = fixture

    class PreparationInterrupted(BaseException):
        pass

    with monkeypatch.context() as interruption:
        if stage == "during_artifacts":
            add_artifact = controller.store.add_artifact

            def stop_after_first_artifact(*args, **kwargs):
                add_artifact(*args, **kwargs)
                raise PreparationInterrupted()

            interruption.setattr(controller.store, "add_artifact", stop_after_first_artifact)
        else:
            append_event = controller.store.append_event

            def stop_before_marker(run_id, kind, *args, **kwargs):
                if kind == "bundle_profile_prepared":
                    raise PreparationInterrupted()
                return append_event(run_id, kind, *args, **kwargs)

            interruption.setattr(controller.store, "append_event", stop_before_marker)
        with pytest.raises(PreparationInterrupted):
            _prepare(fixture)
    assert not _prepared_events(controller, parent)
    assert (parent.workspace / "bundle-profile.json").is_file()
    before_files, _, _ = _snapshot(controller, parent)
    before_validation = _snapshot(controller, parent)

    validate_automatic_solve_bundle(controller.store, parent.id)

    assert _snapshot(controller, parent) == before_validation
    _prepare(fixture)
    assert _snapshot(controller, parent)[0] == before_files
    rows = controller.store.list_artifacts(parent.id)
    assert len(rows) == len({row["path"] for row in rows})
    assert len(_prepared_events(controller, parent)) == 1
    assert (runtime.bundle_calls, runtime.audit_calls) == (1, 1)


@pytest.mark.parametrize("changed", ["profile", "evaluator", "prepared_marker"])
def test_generic_delivery_rechecks_automatic_preparation_authority(tmp_path, monkeypatch, capsys, changed):
    from test_conversational_automatic_bundle import automatic_setup

    from famou import cli

    runtime, args = automatic_setup(tmp_path, monkeypatch)
    assert cli.main(args) == 0
    payload = json.loads(capsys.readouterr().out)
    controller = LocalController(Config(tmp_path / "home"), runtime)
    parent = controller.store.get_run(payload["run_id"])
    assert controller.deliver(parent.id).action == "deliver"
    if changed == "profile":
        (parent.workspace / "bundle-profile.json").unlink()
    elif changed == "evaluator":
        target = parent.workspace / "evaluator-bundle/evaluator.py"
        _write_frozen(target, target.read_bytes() + b"\n# changed\n")
    else:
        with controller.store._connect() as connection:
            connection.execute("DELETE FROM events WHERE run_id = ? AND type = 'bundle_profile_prepared'", (parent.id,))
    before = _snapshot(controller, parent)

    with pytest.raises((EvolutionError, ValueError)):
        controller.deliver(parent.id)

    assert _snapshot(controller, parent) == before
    assert (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls, runtime.generator_calls) == (1, 1, 1, 4)
