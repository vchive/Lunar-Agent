"""Offline source-aware acceptance rejects omitted, downgraded, or invalid evidence."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_measurement113_analysis import CORRECT_HARNESS, _contract

from famou.algorithm import AlgorithmProblemContract, EvaluationReport
from famou.bundle_delivery import publish_bundle_delivery
from famou.candidate_bundle import CandidateSourceBundle, CandidateSourceFile
from famou.candidate_evaluation_spec import CandidateEvaluationSpec, canonical_json
from famou.source_constraints import source_check_evidence

MEASUREMENT = Path(__file__).resolve().parents[1] / "specs/120-supported-scope-acceptance/measurement"


@pytest.fixture
def analyzer():
    specification = importlib.util.spec_from_file_location(
        "measurement120_source_analysis", MEASUREMENT / "source_analysis.py",
    )
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _source_contract(*, minimum=2, scope="source", checker=True, soft=False):
    value = _contract().to_dict()
    constraint = {
        "id": "two-files", "description": "At least two lowercase .py source files.",
        "source": "user_confirmed", "verification": "independent", "verification_scope": scope,
    }
    if checker:
        constraint["source_check"] = {"kind": "python_file_count", "minimum": minimum}
    value["soft_constraints" if soft else "hard_constraints"].append(constraint)
    return AlgorithmProblemContract.from_dict(value)


def _fixture(analyzer, tmp_path, monkeypatch, *, source_contract=True):
    legacy = analyzer.shared_analyzer()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    contract = _source_contract() if source_contract else _contract()
    parent = SimpleNamespace(id="parent", status=SimpleNamespace(value="succeeded"))
    child = SimpleNamespace(id="child", workspace=workspace / "evolution-run",
                            status=SimpleNamespace(value="succeeded"))
    sources = {"main.py": b"raise AssertionError('acceptance must not run source')\n", "empty.py": b""}
    bundle = CandidateSourceBundle(contract.digest(), "main.py", tuple(
        CandidateSourceFile(name, len(raw), hashlib.sha256(raw).hexdigest())
        for name, raw in sources.items()
    ))
    harness = b"raise AssertionError('delivery inspection must not run harness')\n"
    evaluator = CandidateEvaluationSpec(hashlib.sha256(harness).hexdigest(), len(harness),
                                        (str(Path(sys.executable).resolve()), "-I"),
                                        evaluator_id="acceptance-fixture", timeout_seconds=3)
    materials = {"source/" + name: raw for name, raw in sources.items()}
    materials.update({
        "contract.json": canonical_json(contract.to_dict()),
        "source-bundle.json": canonical_json(bundle.to_dict()),
        "evaluation/evaluator.py": harness,
        "evaluation/spec.json": canonical_json(evaluator.to_dict()),
        "evaluation/report.json": canonical_json(
            EvaluationReport("1", evaluator.evaluator_id, 1, 37.0, {}, ()).to_dict(),
        ),
    })
    if source_contract:
        materials["evaluation/source-checks.json"] = canonical_json(source_check_evidence(contract, bundle))
    outputs = next(item["outputs"] for item in legacy.holdouts("budget_selection")
                   if item["name"] == "feasible_optimal")
    rows = []
    for name, value in outputs.items():
        materials[name] = canonical_json(value)
        path = workspace / name
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(materials[name])
        rows.append({"kind": "output", "path": name, "size": len(materials[name]),
                     "sha256": hashlib.sha256(materials[name]).hexdigest()})
    identity = {"candidate_id": "fixture", "contract_sha256": contract.digest(),
                "bundle_sha256": bundle.digest(), "receipt_sha256": "a" * 64,
                "evaluation_sha256": "b" * 64}
    destination = workspace / ".bundle-deliveries"
    destination.mkdir()
    package = publish_bundle_delivery(destination, identity=identity, materials=materials)
    terminal = {"mode": "bundle", "status": "succeeded", "parent_run_id": parent.id,
                "evolution_run_id": child.id, **identity, "delivery_sha256": package.digest(),
                "delivery_path": package.delivery_path.relative_to(workspace).as_posix()}
    cli = {"status": "succeeded", "run_id": parent.id, "evolution": {
        "status": "succeeded", "run_id": child.id, "materialization": terminal,
    }}
    plan = SimpleNamespace(algorithm_problem=contract.to_dict())
    store = SimpleNamespace(
        get_run_by_workspace=lambda _: parent, get_run=lambda _: child,
        get_current_plan=lambda _: plan, list_artifacts=lambda _: rows,
        list_events=lambda _: [{"type": "bundle_profile_prepared"},
                               {"type": "bundle_candidate_delivered", "payload": dict(terminal)}],
    )
    monkeypatch.setattr(legacy, "ReadOnlyStore", lambda _: store)
    monkeypatch.setattr(legacy, "validate_automatic_solve_bundle", lambda *args: None)
    (tmp_path / "cli.json").write_bytes(canonical_json(cli))
    return SimpleNamespace(workspace=workspace, package=package, contract=contract, terminal=terminal,
                           cli=cli, store=store, plan=plan, sources=sources, rows=rows)


def _repin(tmp_path, fixture, *, replacements=None, removed=(), protocol=None):
    root = fixture.package.delivery_path
    manifest = json.loads((root / "delivery.json").read_bytes())
    manifest["identity"] = {key: fixture.terminal[key] for key in manifest["identity"]}
    if protocol is not None:
        manifest["protocol"] = protocol
    for name in removed:
        (root / name).unlink()
        del manifest["files"][name]
    for name, raw in (replacements or {}).items():
        (root / name).write_bytes(raw)
        manifest["files"][name] = {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    raw_manifest = canonical_json(manifest)
    (root / "delivery.json").write_bytes(raw_manifest)
    fixture.terminal["delivery_sha256"] = hashlib.sha256(raw_manifest).hexdigest()
    (tmp_path / "cli.json").write_bytes(canonical_json(fixture.cli))


def test_source_contract_and_portable_evidence_are_required_for_valid_completion(analyzer, tmp_path, monkeypatch):
    fixture = _fixture(analyzer, tmp_path, monkeypatch)
    before = {p: p.read_bytes() for p in fixture.workspace.rglob("*") if p.is_file()}
    result = analyzer.analyze_slot(tmp_path, "budget_selection")
    assert result["primary_valid_completion"] is True
    assert result["quality"] == result["optimum"] == 37 and result["quality_gap"] == 0
    assert result["source_contract_requirement"] is result["source_evidence_verified"] is True
    assert result["source_python_files"] == ["empty.py", "main.py"]
    assert result["source_python_count"] == 2 and result["source_file_requirement"] is True
    assert result["source_check_protocol"] == "lunar-source-checks-v1"
    assert result["source_delivery_protocol"] == "lunar-bundle-delivery-source-v1"
    assert result["source_checks"] == [{"id": "two-files", "kind": "python_file_count",
                                         "minimum": 2, "observed": 2, "passed": True}]
    assert {p: p.read_bytes() for p in fixture.workspace.rglob("*") if p.is_file()} == before


def test_two_legacy_files_do_not_replace_omitted_compiled_source_requirement(analyzer, tmp_path, monkeypatch):
    _fixture(analyzer, tmp_path, monkeypatch, source_contract=False)
    result = analyzer.analyze_slot(tmp_path, "budget_selection")
    assert result["product_success"] is result["delivery_verified"] is True
    assert result["source_python_count"] == 2 and result["output_check"]["quality"] == 37
    assert result["source_contract_requirement"] is result["source_evidence_verified"] is False
    assert result["primary_valid_completion"] is result["source_file_requirement"] is False
    assert result["quality"] is result["quality_gap"] is None


@pytest.mark.parametrize("changed", [
    "missing_evidence", "missing_contract", "downgrade", "source_fail", "source_count_fail", "output_fail",
])
def test_rehashed_invalid_source_delivery_cannot_receive_completion_credit(analyzer, tmp_path, monkeypatch, changed):
    fixture = _fixture(analyzer, tmp_path, monkeypatch)
    if changed in {"missing_evidence", "missing_contract"}:
        _repin(tmp_path, fixture, removed=("evaluation/source-checks.json" if changed == "missing_evidence"
                                          else "contract.json",))
    elif changed == "downgrade":
        _repin(tmp_path, fixture, protocol="lunar-bundle-delivery-v1")
    elif changed == "source_fail":
        evidence = json.loads((fixture.package.delivery_path / "evaluation/source-checks.json").read_bytes())
        evidence["validity"] = False
        evidence["checks"][0]["passed"] = False
        _repin(tmp_path, fixture, replacements={"evaluation/source-checks.json": canonical_json(evidence)})
    elif changed == "source_count_fail":
        raw = fixture.sources["main.py"]
        bundle = CandidateSourceBundle(fixture.contract.digest(), "main.py", (
            CandidateSourceFile("main.py", len(raw), hashlib.sha256(raw).hexdigest()),
        ))
        fixture.terminal["bundle_sha256"] = bundle.digest()
        evidence = source_check_evidence(fixture.contract, bundle)
        assert evidence["validity"] is False and evidence["checks"][0]["observed"] == 1
        _repin(tmp_path, fixture, removed=("source/empty.py",), replacements={
            "source-bundle.json": canonical_json(bundle.to_dict()),
            "evaluation/source-checks.json": canonical_json(evidence),
        })
    else:
        report = EvaluationReport("1", "acceptance-fixture", 0, 0.0, {},
                                  ({"code": "invalid", "message": "Invalid output."},)).to_dict()
        _repin(tmp_path, fixture, replacements={"evaluation/report.json": canonical_json(report)})
    result = analyzer.analyze_slot(tmp_path, "budget_selection")
    assert result["source_contract_requirement"] is True
    assert result["delivery_verified"] is result["source_evidence_verified"] is False
    assert result["primary_valid_completion"] is False
    assert result["quality"] is result["quality_gap"] is None
    assert result["output_check"]["quality"] == 37


def test_valid_source_evidence_cannot_override_independent_output_failure(analyzer, tmp_path, monkeypatch):
    fixture = _fixture(analyzer, tmp_path, monkeypatch)
    name = "output/summary.json"
    raw = canonical_json({"total_value": 999, "total_weight": 0, "item_count": 0})
    (fixture.workspace / name).write_bytes(raw)
    for row in fixture.rows:
        if row["path"] == name:
            row.update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    _repin(tmp_path, fixture, replacements={name: raw})
    result = analyzer.analyze_slot(tmp_path, "budget_selection")
    assert result["source_evidence_verified"] is result["delivery_verified"] is True
    assert result["output_check"]["validity"] is False
    assert result["primary_valid_completion"] is False
    assert result["quality"] is result["quality_gap"] is None


@pytest.mark.parametrize("options", [
    {"minimum": 1}, {"minimum": 3}, {"checker": False}, {"soft": True},
    {"checker": False, "scope": "execution"},
])
def test_changed_or_unsupported_contract_does_not_match_registration(analyzer, options):
    with pytest.raises(ValueError):
        analyzer._registered_source_contract(_source_contract(**options))


def test_shared_analyzer_import_does_not_borrow_or_replace_generic_tasks(analyzer, monkeypatch):
    foreign = SimpleNamespace(CASES={"unexpected": {}})
    monkeypatch.setitem(sys.modules, "tasks", foreign)
    legacy = analyzer.shared_analyzer()
    assert set(legacy.CASES) == {"budget_selection", "worker_assignment"}
    assert sys.modules["tasks"] is foreign
    assert sum(len(legacy.holdouts(key)) for key in legacy.CASES) == 24


def test_source_contract_preserves_output_only_holdout_audit(analyzer, tmp_path):
    evaluator = tmp_path / "fixture.py"
    evaluator.write_text(CORRECT_HARNESS)
    result = analyzer.shared_analyzer()._audit_evaluator(
        tmp_path, "budget_selection", _source_contract(), evaluator,
    )
    assert result["total"] == 12
    assert result["correct_accepts"] == result["quality_agreements"] == 3
    assert result["correct_rejections"] == 9
    assert result["false_accepts"] == result["false_rejects"] == result["harness_errors"] == 0


def test_failed_slot_keeps_quality_unknown_without_creating_product_files(analyzer, tmp_path):
    result = analyzer.analyze_slot(tmp_path, "worker_assignment")
    assert result["primary_valid_completion"] is result["source_evidence_verified"] is False
    assert result["quality"] is result["quality_gap"] is result["source_check_validity"] is None
    assert list(tmp_path.iterdir()) == []
