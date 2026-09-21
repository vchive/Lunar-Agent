"""A scored multi-file child publishes its complete evidence to the linked solve parent."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_bundle_population import MAIN_SOURCE, build_context
from test_bundle_population_controller import _calls

from lunar_evolution import bundle_parent_delivery as delivery_module
from lunar_evolution.budget import BudgetSpec
from lunar_evolution.bundle_delivery import PrivateTree
from lunar_evolution.config import Config
from lunar_evolution.controller import LocalController
from lunar_evolution.conversational import build_algorithm_plan
from lunar_evolution.evolution import CandidateArchive, CandidateDraft, EvolutionError
from lunar_evolution.output_publication import OutputPublicationUncertain
from lunar_evolution.runtime import MockRuntime


class SimulatedCrash(BaseException):
    """A stopped process skips normal exception compensation."""


def _completed(tmp_path, *, budget=None, wrong_workspace=False, absent_outputs=False):
    context = build_context(tmp_path)
    if absent_outputs:
        harness = (b'print(\'{"schema_version":"1","evaluator_id":"bundle-population-fixture",'
                   b'"validity":1,"quality":1.0,"combined_score":1.0,"detailed_scores":{},"error_info":[]}\')\n')
        pipeline = context.bundle_pipeline
        pipeline.harness_path.write_bytes(harness)
        pipeline.evaluator = replace(pipeline.evaluator, harness_sha256=hashlib.sha256(harness).hexdigest(), harness_size=len(harness))
        context = replace(context, contract=replace(context.contract, outputs=tuple(
            replace(spec, required=False) for spec in context.contract.outputs
        )), config=pipeline.configure(
            replace(context.config, evaluator_fingerprint=None, runner_fingerprint=None),
        ), generate=lambda _: CandidateDraft.from_files({
            "solve/main.py": "from pathlib import Path\nPath('count').write_text('x')\n",
            "solve/helper.py": "value = 1\n",
        }, entrypoint="solve/main.py"))
    controller = LocalController(Config(tmp_path / "home"), MockRuntime())
    parent = controller.create_conversational_run("choose best value", workspace=tmp_path / "parent")
    root = Path(parent.workspace)
    (root / "data/raw").mkdir(parents=True)
    (root / "data/raw/value").write_bytes(b"10")
    task = controller.store.list_tasks(parent.id)[0]
    attempt = controller.store.claim_task(task.id, "fixture")
    controller.store.finish_task(task.id, attempt.id, True)
    plan = build_algorithm_plan(parent.goal, context.contract)
    if budget is not None:
        plan = replace(plan, budget=BudgetSpec(max_artifact_bytes=budget))
    controller.store.attach_plan_to_run(parent.id, plan)
    controller.store.add_artifact(parent.id, task.id, "data/raw/value", hashlib.sha256(b"10").hexdigest(), 2, "input_data")
    controller.store.supersede_pending_tasks(parent.id, "replaced by explicit evolution handoff")
    parent = controller.store.settle_run(parent.id)
    child_root = context.workspace if wrong_workspace else root / "evolution-run"
    context = replace(context, workspace=child_root)
    child = controller.create_evolution_run(context.contract, workspace=child_root)
    controller.store.append_event(parent.id, "evolution_linked", {
        "evolution_run_id": child.id, "contract_sha256": context.contract.digest(), "strategy": "population",
    })
    controller.store.append_event(child.id, "evolution_parent_linked", {
        "parent_run_id": parent.id, "contract_sha256": context.contract.digest(),
    })
    child, result = controller.run_evolution(
        child.id, context.contract, context.generate, context.evaluate, context.config,
        bundle_pipeline=context.bundle_pipeline,
    )
    assert parent.status.value == child.status.value == "succeeded"
    return context, controller, parent, child, result


def _finish(fixture):
    context, controller, parent, child, result = fixture
    return controller.deliver_bundle_to_parent(parent.id, child.id, context.contract, result)


def _packages(parent):
    return sorted((Path(parent.workspace) / ".bundle-deliveries").glob(".bundle-delivery-*"))


def _events(controller, parent, kind):
    return [event for event in controller.store.list_events(parent.id) if event["type"] == kind]


def test_parent_delivers_complete_scored_bundle_and_reuses_it_without_execution(tmp_path):
    fixture = _completed(tmp_path)
    context, controller, parent, child, _ = fixture
    calls = _calls(context.workspace)
    payload = _finish(fixture)
    root = Path(parent.workspace)
    copied = root / payload["delivery_path"]
    assert payload["mode"] == "bundle" and payload["status"] == "succeeded"
    assert payload["validation"]["passed"] is True and "execution" not in payload
    assert payload["observation"] == "evaluation-time"
    assert json.loads((root / "output/result.json").read_bytes())["value"] == 9
    assert (copied / "source/solve/main.py").read_text() == MAIN_SOURCE
    assert (copied / "source/solve/helper.py").read_text().endswith("return 9\n")
    assert json.loads((root / payload["evaluation_report_path"]).read_bytes())["combined_score"] == 9
    rows = controller.store.list_artifacts(parent.id)
    package_rows = [row for row in rows if row["path"].startswith(payload["delivery_path"] + "/")]
    assert len(package_rows) == len([path for path in copied.rglob("*") if path.is_file()])
    assert {row["kind"] for row in package_rows} >= {"bundle_source", "bundle_evaluation_report", "bundle_delivery_manifest"}
    decision = controller.deliver(parent.id)
    assert decision.evidence[:3] == tuple(payload["delivery_path"] + "/" + name for name in (
        "delivery.json", "source-bundle.json", "evaluation/report.json",
    ))
    events = controller.store.list_events(parent.id)
    assert _finish(fixture) == payload
    assert controller.deliver(parent.id) == decision
    assert controller.store.list_artifacts(parent.id) == rows
    assert controller.store.list_events(parent.id) == events
    assert len(_packages(parent)) == 1
    assert _calls(context.workspace) == calls
    assert not _events(controller, parent, "evolved_candidate_materialized")
    assert not (Path(child.workspace) / "evolution/materialization").exists()


@pytest.mark.parametrize("changed", ["source", "report", "input", "parent_output", "selection", "link"])
def test_parent_rejects_changed_authority_before_allocating_copy(tmp_path, changed):
    fixture = _completed(tmp_path)
    context, controller, parent, child, result = fixture
    candidate = CandidateArchive(context.workspace).best()
    if changed == "source":
        target = context.workspace / Path(candidate.code_path).parent / "helper.py"
        target.write_bytes(target.read_bytes() + b" ")
    elif changed == "report":
        target = context.workspace / candidate.bundle_evidence["evaluation_path"] / "report.json"
        target.write_bytes(target.read_bytes() + b" ")
    elif changed == "input":
        (Path(parent.workspace) / "data/raw/value").write_bytes(b"11")
    elif changed == "parent_output":
        target = Path(parent.workspace) / "output/result.json"
        target.parent.mkdir()
        target.write_bytes(b"conflicting bytes")
    elif changed == "selection":
        fixture = (*fixture[:-1], replace(result, best_score=123.0))
    else:
        controller.store.append_event(child.id, "evolution_parent_linked", {
            "parent_run_id": "wrong-parent", "contract_sha256": context.contract.digest(),
        })
    calls = _calls(context.workspace)
    with pytest.raises((EvolutionError, ValueError)):
        _finish(fixture)
    assert not (Path(parent.workspace) / ".bundle-deliveries").exists()
    assert _calls(context.workspace) == calls


@pytest.mark.parametrize("changed", ["source", "report", "output", "ledger", "terminal"])
def test_parent_completed_delivery_rejects_drift_read_only(tmp_path, changed):
    fixture = _completed(tmp_path)
    context, controller, parent, _child, _ = fixture
    payload = _finish(fixture)
    root = Path(parent.workspace)
    if changed in {"source", "report", "output"}:
        relative = {"source": payload["delivery_path"] + "/source/solve/helper.py",
                    "report": payload["evaluation_report_path"], "output": "output/result.json"}[changed]
        path = root / relative
        path.write_bytes(path.read_bytes() + b" ")
    elif changed == "ledger":
        row = next(row for row in controller.store.list_artifacts(parent.id) if row["kind"] == "bundle_source")
        controller.store.add_artifact(parent.id, row["task_id"], row["path"], "a" * 64, row["size"], row["kind"])
    else:
        controller.store.append_event(parent.id, "bundle_candidate_delivered", {**payload, "error": "rewritten"})
    calls, events = _calls(context.workspace), controller.store.list_events(parent.id)
    with pytest.raises((EvolutionError, ValueError, OutputPublicationUncertain)):
        controller.deliver(parent.id)
    with pytest.raises((EvolutionError, ValueError, OutputPublicationUncertain)):
        _finish(fixture)
    assert len(_packages(parent)) == 1
    assert controller.store.list_events(parent.id) == events
    assert _calls(context.workspace) == calls


def test_parent_rejects_workspace_and_missing_reciprocal_link(tmp_path):
    fixture = _completed(tmp_path, wrong_workspace=True)
    _, controller, parent, child, _ = fixture
    (Path(parent.workspace) / "evolution-run").mkdir()
    with pytest.raises(EvolutionError, match="workspace_mismatch"):
        _finish(fixture)
    assert _packages(parent) == []
    with controller.store._connect() as connection:
        connection.execute("UPDATE runs SET workspace = ? WHERE id = ?", (str(Path(parent.workspace) / "evolution-run"), child.id))
        connection.execute("DELETE FROM events WHERE run_id = ? AND type = ?", (child.id, "evolution_parent_linked"))
    with pytest.raises(EvolutionError, match="links_invalid"):
        _finish(fixture)


def test_parent_budget_includes_complete_copy_and_promoted_output_before_mutation(tmp_path):
    fixture = _completed(tmp_path)
    _, controller, parent, child, _ = fixture
    identity, materials, _ = controller._verified_bundle_evolution_delivery(child.id)
    required = 2 + sum(map(len, materials.values())) + len(delivery_module._copy_manifest(identity, materials)) + len(materials["output/result.json"])
    budget = BudgetSpec(max_artifact_bytes=required - 1)
    with controller.store._connect() as connection:
        connection.execute("UPDATE runs SET budget = ? WHERE id = ?", (json.dumps(budget.to_dict()), parent.id))
    with pytest.raises(EvolutionError, match="budget_exceeded"):
        _finish(fixture)
    assert not (Path(parent.workspace) / ".bundle-deliveries").exists()
    assert not (Path(parent.workspace) / "output/result.json").exists()
    with controller.store._connect() as connection:
        connection.execute("UPDATE runs SET budget = ? WHERE id = ?", (json.dumps(replace(budget, max_artifact_bytes=required).to_dict()), parent.id))
    assert _finish(fixture)["status"] == "succeeded"
    assert sum(row["size"] for row in controller.store.list_artifacts(parent.id)) == required


def test_parent_cancelled_before_delivery_does_not_allocate(tmp_path):
    fixture = _completed(tmp_path)
    _, controller, parent, _, _ = fixture
    with controller.store._connect() as connection:
        connection.execute("UPDATE runs SET status = 'cancelled' WHERE id = ?", (parent.id,))
    with pytest.raises(EvolutionError, match="cancelled"):
        _finish(fixture)
    assert not (Path(parent.workspace) / ".bundle-deliveries").exists()


def test_partial_copy_is_retained_and_resume_allocates_complete_copy_without_execution(tmp_path, monkeypatch):
    fixture = _completed(tmp_path)
    context, _, parent, _, _ = fixture
    before = _calls(context.workspace)
    original = PrivateTree.write

    def stop_before_completion(self, name, content):
        if name == "delivery.json":
            raise SimulatedCrash("copy interrupted")
        return original(self, name, content)

    with monkeypatch.context() as patch:
        patch.setattr(PrivateTree, "write", stop_before_completion)
        with pytest.raises(SimulatedCrash):
            _finish(fixture)
    incomplete = _packages(parent)
    assert len(incomplete) == 1 and not (incomplete[0] / "delivery.json").exists()
    assert _finish(fixture)["status"] == "succeeded"
    assert len(_packages(parent)) == 2
    assert not (incomplete[0] / "delivery.json").exists()
    assert _calls(context.workspace) == before


@pytest.mark.parametrize("boundary", ["artifact", "terminal"])
def test_resume_reuses_pinned_copy_after_registration_or_terminal_event_interrupt(tmp_path, monkeypatch, boundary):
    fixture = _completed(tmp_path)
    context, controller, parent, _, _ = fixture
    before = _calls(context.workspace)
    if boundary == "artifact":
        original = controller.store.add_artifact

        def interrupted(*args, **kwargs):
            original(*args, **kwargs)
            raise SimulatedCrash("artifact registered then process stopped")
        method = "add_artifact"
    else:
        original = controller.store.append_event

        def interrupted(*args, **kwargs):
            if args[1] == "bundle_candidate_delivered":
                raise SimulatedCrash("outputs committed before terminal event")
            return original(*args, **kwargs)
        method = "append_event"
    with monkeypatch.context() as patch:
        patch.setattr(controller.store, method, interrupted)
        with pytest.raises(SimulatedCrash):
            _finish(fixture)
    packages = _packages(parent)
    assert len(packages) == 1
    assert _finish(fixture)["status"] == "succeeded"
    assert _packages(parent) == packages
    assert len(_events(controller, parent, "bundle_delivery_prepared")) == 1
    assert len(_events(controller, parent, "bundle_candidate_delivered")) == 1
    assert len(_events(controller, parent, "evolved_outputs_promoted")) == 1
    assert _calls(context.workspace) == before


def test_known_output_commit_rollback_is_stable_failed_delivery(tmp_path, monkeypatch):
    fixture = _completed(tmp_path)
    context, controller, parent, _, _ = fixture
    before = _calls(context.workspace)

    def fail_commit(*args, **kwargs):
        raise RuntimeError("database rejected transaction")

    with monkeypatch.context() as patch:
        patch.setattr(controller.store, "commit_output_publication", fail_commit)
        payload = _finish(fixture)
    assert payload["status"] == "failed" and payload["outputs"] == []
    assert payload["validation"]["passed"] is True
    assert payload["error"] == "output_publication_rolled_back"
    assert not (Path(parent.workspace) / "output/result.json").exists()
    assert _finish(fixture) == payload
    assert len(_packages(parent)) == 1
    with pytest.raises(ValueError, match="no successful bundle delivery"):
        controller.deliver(parent.id)
    assert _calls(context.workspace) == before


def test_unknown_output_commit_is_preserved_then_resumed_without_execution(tmp_path, monkeypatch):
    fixture = _completed(tmp_path)
    context, controller, parent, _, _ = fixture
    before = _calls(context.workspace)
    original = controller.store.commit_output_publication

    def commit_then_crash(*args, **kwargs):
        original(*args, **kwargs)
        raise SimulatedCrash("database committed then process stopped")

    with monkeypatch.context() as patch:
        patch.setattr(controller.store, "commit_output_publication", commit_then_crash)
        with pytest.raises(SimulatedCrash):
            _finish(fixture)
    assert not _events(controller, parent, "bundle_candidate_delivered")
    assert (Path(parent.workspace) / "output/result.json").is_file()
    assert _finish(fixture)["status"] == "succeeded"
    assert len(_events(controller, parent, "evolved_outputs_promoted")) == 1
    assert len(_packages(parent)) == 1
    assert _calls(context.workspace) == before


def test_parent_bundle_with_absent_optional_outputs_delivers_source_and_report(tmp_path):
    fixture = _completed(tmp_path, absent_outputs=True)
    _, controller, parent, _, _ = fixture
    payload = _finish(fixture)
    assert payload["status"] == "succeeded" and payload["outputs"] == []
    assert not (Path(parent.workspace) / "output").exists()
    assert controller.deliver(parent.id).evidence[:3] == tuple(payload["delivery_path"] + "/" + name for name in (
        "delivery.json", "source-bundle.json", "evaluation/report.json",
    ))
    assert _finish(fixture) == payload


def test_unknown_commit_inspection_preserves_files_until_store_available(tmp_path, monkeypatch):
    fixture = _completed(tmp_path)
    context, controller, parent, _, _ = fixture
    before = _calls(context.workspace)
    original_commit = controller.store.commit_output_publication
    original_inspect = controller.store.output_publication_committed
    committed = False

    def commit(*args, **kwargs):
        nonlocal committed
        result = original_commit(*args, **kwargs)
        committed = True
        return result

    def unavailable(*args, **kwargs):
        if committed:
            raise RuntimeError("database unavailable during commit inspection")
        return original_inspect(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(controller.store, "commit_output_publication", commit)
        patch.setattr(controller.store, "output_publication_committed", unavailable)
        with pytest.raises(OutputPublicationUncertain):
            _finish(fixture)
    assert (Path(parent.workspace) / "output/result.json").is_file()
    assert not _events(controller, parent, "bundle_candidate_delivered")
    assert _finish(fixture)["status"] == "succeeded"
    assert len(_packages(parent)) == 1
    assert _calls(context.workspace) == before


def test_interruption_before_output_commit_resumes_to_stable_rollback(tmp_path, monkeypatch):
    fixture = _completed(tmp_path)
    context, controller, parent, _, _ = fixture
    before = _calls(context.workspace)

    def interrupt(*args, **kwargs):
        raise SimulatedCrash("stopped before database commit")

    with monkeypatch.context() as patch:
        patch.setattr(controller.store, "commit_output_publication", interrupt)
        with pytest.raises(SimulatedCrash):
            _finish(fixture)
    assert (Path(parent.workspace) / "output/result.json").is_file()
    payload = _finish(fixture)
    assert payload["status"] == "failed" and payload["error"] == "output_publication_rolled_back"
    assert not (Path(parent.workspace) / "output/result.json").exists()
    assert _finish(fixture) == payload
    assert len(_packages(parent)) == 1
    assert _calls(context.workspace) == before
