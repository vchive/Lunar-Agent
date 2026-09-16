"""Offline acceptance analysis of fixture harnesses and malformed delivered JSON."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from famou.algorithm import AlgorithmProblemContract
from famou.bundle_delivery import publish_bundle_delivery
from famou.conversational import build_algorithm_plan
from famou.store import Store

MEASUREMENT = Path(__file__).resolve().parents[1] / "specs/113-real-multifile-acceptance/measurement"

CORRECT_HARNESS = '''import json
from pathlib import Path
items = {item["id"]: item for item in json.loads(Path("inputs/items.json").read_text())["items"]}
limits = json.loads(Path("inputs/limits.json").read_text())
result = json.loads(Path("output/result.json").read_text())
summary = json.loads(Path("output/summary.json").read_text())
ids = result.get("selected_ids") if type(result) is dict else None
valid = type(result) is dict and set(result) == {"selected_ids"} and type(ids) is list
valid = valid and all(type(item) is str and item in items for item in ids)
value = weight = count = 0
if valid:
    value = sum(items[item]["value"] for item in ids)
    weight = sum(items[item]["weight"] for item in ids)
    count = len(ids)
    valid = len(set(ids)) == count and count <= limits["max_items"] and weight <= limits["capacity"]
valid = valid and type(summary) is dict and set(summary) == {"total_value", "total_weight", "item_count"}
valid = valid and all(type(item) is int for item in summary.values())
valid = valid and summary == {"total_value":value,"total_weight":weight,"item_count":count}
print(json.dumps({"schema_version":"1","evaluator_id":"compiled-bundle","validity":int(valid),
 "quality":value if valid else None,"combined_score":value / max(1, limits["capacity"]) if valid else 0,
 "detailed_scores":{},"error_info":[] if valid else [{"code":"invalid","message":"invalid output"}]}))
'''


@pytest.fixture
def analyzer(monkeypatch):
    monkeypatch.syspath_prepend(str(MEASUREMENT))
    specification = importlib.util.spec_from_file_location("measurement113_analyze", MEASUREMENT / "analyze.py")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _contract(*, extra_field=False):
    return AlgorithmProblemContract.from_dict({
        "schema_version": "1", "problem_id": "acceptance-fixture", "problem_type": "packing",
        "statement": "Choose items within the capacity and report exact totals.",
        "inputs": [{"path": name, "format": "json", "fields": {"data": "registered input"}}
                   for name in ("items.json", "limits.json")],
        "decision_variables": ["selected ids"], "objective": {"name": "total_value", "direction": "maximize"},
        "hard_constraints": [], "soft_constraints": [], "success_criteria": ["Feasible output."],
        "deliverables": ["output/result.json", "output/summary.json"],
        "outputs": [{"path": "output/result.json", "format": "json",
                     "fields": ["selected_ids", "unrequested_field"] if extra_field else ["selected_ids"]},
                    {"path": "output/summary.json", "format": "json",
                     "fields": ["total_value", "total_weight", "item_count"]}],
    })


def _files(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_correct_harness_audit_separates_schema_rejection_and_checks_quality(analyzer, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    evaluator = workspace / "fixture.py"
    evaluator.write_text(CORRECT_HARNESS)
    (workspace / "candidate.py").write_text("raise AssertionError('candidate must not execute')\n")
    before = _files(workspace)
    result = analyzer._audit_evaluator(tmp_path, "budget_selection", _contract(), evaluator)
    assert result["total"] == 12 and result["expected_valid"] == 3 and result["expected_invalid"] == 9
    assert result["schema_rejections"] == 1 and result["harness_rejections"] == 8
    assert result["correct_accepts"] == 3 and result["correct_rejections"] == 9
    assert result["false_accepts"] == result["false_rejects"] == result["harness_errors"] == 0
    assert result["quality_agreements"] == 3 and result["quality_disagreements"] == 0
    assert result["score_order"] == [{"first": "feasible_suboptimal", "second": "feasible_optimal", "agrees": True}]
    assert result["contract_declarations"]["match_task"] is True
    assert _files(workspace) == before
    assert (tmp_path / result["audit_path"]).is_dir()


def test_false_accepts_are_distinct_from_product_schema_rejections(analyzer, tmp_path):
    evaluator = tmp_path / "fixture.py"
    evaluator.write_text('print(\'{"schema_version":"1","evaluator_id":"compiled-bundle","validity":1,"quality":0,"combined_score":0,"detailed_scores":{},"error_info":[]}\')\n')
    result = analyzer._audit_evaluator(tmp_path, "budget_selection", _contract(), evaluator)
    assert result["false_accepts"] == 8
    assert result["correct_rejections"] == result["schema_rejections"] == 1
    assert result["quality_disagreements"] == 3
    assert result["harness_errors"] == 0


def test_crashing_harness_does_not_receive_correct_rejection_credit(analyzer, tmp_path):
    evaluator = tmp_path / "fixture.py"
    evaluator.write_text("raise RuntimeError('fixture process failure')\n")
    result = analyzer._audit_evaluator(tmp_path, "budget_selection", _contract(), evaluator)
    assert result["harness_errors"] == 11 and result["harness_rejections"] == 0
    assert result["schema_rejections"] == result["correct_rejections"] == 1
    assert result["false_accepts"] == result["false_rejects"] == result["quality_agreements"] == 0


def test_overstrict_generated_contract_is_measured_as_false_rejection(analyzer, tmp_path):
    evaluator = tmp_path / "fixture.py"
    evaluator.write_text("raise AssertionError('schema precheck must stop before invocation')\n")
    result = analyzer._audit_evaluator(tmp_path, "budget_selection", _contract(extra_field=True), evaluator)
    assert result["schema_rejections"] == 12 and result["harness_errors"] == 0
    assert result["false_rejects"] == 3 and result["correct_rejections"] == 9


@pytest.mark.parametrize("malformed", [b'{"selected_ids":[],"selected_ids":[]}', b'{', b'NaN'])
def test_malformed_outputs_are_invalid_even_when_product_result_is_absent(analyzer, tmp_path, malformed):
    output = tmp_path / "workspace/output"
    output.mkdir(parents=True)
    (output / "result.json").write_bytes(malformed)
    (output / "summary.json").write_text('{"total_value":0,"total_weight":0,"item_count":0}')
    before = _files(tmp_path / "workspace")
    result = analyzer.analyze_slot(tmp_path, "budget_selection")
    assert result["output_check"]["validity"] is False
    assert result["output_check"]["quality"] is None and result["quality_gap"] is None
    assert result["primary_valid_completion"] is False and result["evaluator_audit"] is None
    assert not (tmp_path / "home").exists()
    assert _files(tmp_path / "workspace") == before


def test_valid_suboptimal_output_quality_is_independent_of_product_success(analyzer, tmp_path):
    expected = analyzer.holdouts("budget_selection")[0]
    output = tmp_path / "workspace/output"
    output.mkdir(parents=True)
    for name, value in expected["outputs"].items():
        (tmp_path / "workspace" / name).write_text(json.dumps(value))
    result = analyzer.analyze_slot(tmp_path, "budget_selection")
    assert result["output_check"] == expected["expected"]
    assert result["optimum"] == 37
    assert result["quality"] is None and result["quality_gap"] is None
    assert result["primary_valid_completion"] is False


def test_store_projection_uses_read_only_database_connection(analyzer, tmp_path):
    database = tmp_path / "home/state.db"
    writable = Store(database)
    writable.initialize()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    parent = writable.create_run_with_plan(build_algorithm_plan("fixture", _contract()), workspace=workspace)
    readonly = analyzer.ReadOnlyStore(database)
    assert readonly.get_run_by_workspace(workspace).id == parent.id
    assert readonly.get_current_plan(parent.id).algorithm_problem == _contract().to_dict()
    with readonly._connect() as connection, pytest.raises(sqlite3.OperationalError):
        connection.execute("DELETE FROM runs")
    before = _files(workspace)
    result = analyzer.analyze_slot(tmp_path, "budget_selection")
    assert result["evaluator_audit"] is None and result["evaluator_audit_unavailable"] == "no_frozen_evaluator"
    assert result["primary_valid_completion"] is False
    assert _files(workspace) == before


@pytest.mark.parametrize("drift", [None, "output", "package", "event"])
def test_delivery_binds_cli_event_portable_files_and_parent_output_bytes(analyzer, tmp_path, drift):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    parent, child = SimpleNamespace(id="parent"), SimpleNamespace(
        id="child", workspace=workspace / "evolution-run", status=SimpleNamespace(value="succeeded"),
    )
    contract = _contract()
    identity = {key: "a" * 64 for key in ("contract_sha256", "bundle_sha256", "receipt_sha256", "evaluation_sha256")}
    identity.update(contract_sha256=contract.digest(), candidate_id="fixture-candidate")
    materials = {"source/main.py": b"raise AssertionError('do not execute')\n", "source/helper.py": b"value = 1\n",
                 "source-bundle.json": b"{}", "evaluation/report.json": b"{}"}
    outputs = analyzer.holdouts("budget_selection")[0]["outputs"]
    materials.update({name: json.dumps(value).encode() for name, value in outputs.items()})
    destination = workspace / ".bundle-deliveries"
    destination.mkdir()
    package = publish_bundle_delivery(destination, identity=identity, materials=materials)
    rows = []
    for name in outputs:
        path = workspace / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(materials[name])
        rows.append({"path": name, "kind": "output", "sha256": hashlib.sha256(materials[name]).hexdigest(), "size": len(materials[name])})
    terminal = {"mode": "bundle", "status": "succeeded", "parent_run_id": parent.id,
                "evolution_run_id": child.id, **identity, "delivery_sha256": package.digest(),
                "delivery_path": package.delivery_path.relative_to(workspace).as_posix()}
    saved_terminal = dict(terminal)
    store = SimpleNamespace(get_run=lambda _: child, list_artifacts=lambda _: rows,
                            list_events=lambda _: [{"type": "bundle_candidate_delivered", "payload": saved_terminal}])
    cli = {"run_id": parent.id, "evolution": {"run_id": child.id, "materialization": terminal}}
    if drift == "output":
        (workspace / "output/result.json").write_bytes(b"{}")
    elif drift == "package":
        (package.delivery_path / "source/helper.py").write_bytes(b"changed")
    elif drift == "event":
        terminal["candidate_id"] = "another-candidate"
    if drift is None:
        assert analyzer._delivery(store, parent, contract, cli, workspace) == ["helper.py", "main.py"]
    else:
        with pytest.raises((ValueError, RuntimeError)):
            analyzer._delivery(store, parent, contract, cli, workspace)
