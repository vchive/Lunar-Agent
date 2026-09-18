"""Portable source delivery, read-only preparation and bounded acceptance reporting."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_measurement134_case import compiled

from famou.algorithm import EvaluationReport
from famou.automatic_solve_bundle import _profile_payload
from famou.bundle_delivery import inspect_bundle_delivery, publish_bundle_delivery
from famou.candidate_bundle import CandidateSourceBundle, CandidateSourceFile
from famou.candidate_evaluation_spec import canonical_json
from famou.candidate_execution import CandidateExecutionInput
from famou.evaluator_bundle import EvaluatorBundleError
from famou.models import RunStatus
from famou.source_constraints import source_check_evidence

HERE = Path(__file__).resolve().parents[1] / "specs/134-budgeted-multifile-acceptance/measurement"


@pytest.fixture
def modules(monkeypatch):
    loaded = {}
    for name in ("case", "observation", "supervision", "campaign", "analysis"):
        spec = importlib.util.spec_from_file_location("measurement134_analysis_" + name, HERE / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        loaded[name] = module
    return SimpleNamespace(**loaded)


def fixture(modules, slot, monkeypatch, *, value=3):
    a, case = modules.analysis, modules.case
    workspace = slot / "workspace"
    contract, frozen, _ = compiled(case, workspace)
    parent = SimpleNamespace(id="parent", status=RunStatus.SUCCEEDED, workspace=workspace)
    child = SimpleNamespace(id="child", status=RunStatus.SUCCEEDED, workspace=workspace / "evolution-run")
    sources = {"main.py": b"raise AssertionError('measurement must never execute candidate')\n", "empty.py": b""}
    bundle = CandidateSourceBundle(contract.digest(), "main.py", tuple(
        CandidateSourceFile(name, len(raw), hashlib.sha256(raw).hexdigest()) for name, raw in sources.items()
    ))
    harness = (frozen.root / "evaluator.py").read_bytes()
    native_profile = _profile_payload(frozen, (CandidateExecutionInput(
        "limit.json", "parent-input", len(case.INPUT_BYTES), hashlib.sha256(case.INPUT_BYTES).hexdigest(),
    ),), contract, 600)
    evaluator = native_profile["evaluator"]
    (workspace / "bundle-profile.json").write_bytes(canonical_json(native_profile))
    output = canonical_json({"value": value})
    materials = {"source/" + name: raw for name, raw in sources.items()}
    materials.update({
        "contract.json": canonical_json(contract.to_dict()), "source-bundle.json": canonical_json(bundle.to_dict()),
        "evaluation/evaluator.py": harness, "evaluation/spec.json": canonical_json(evaluator),
        "evaluation/report.json": canonical_json(EvaluationReport("1", evaluator["evaluator_id"], 1, 3, {}, ()).to_dict()),
        "evaluation/source-checks.json": canonical_json(source_check_evidence(contract, bundle)),
        "inputs/limit.json": case.INPUT_BYTES,
        "output/result.json": output,
    })
    (workspace / "output").mkdir()
    (workspace / "output/result.json").write_bytes(output)
    artifacts = [{"kind": "output", "path": "output/result.json", "size": len(output),
                  "sha256": hashlib.sha256(output).hexdigest()}]
    identity = {"candidate_id": "fixture", "contract_sha256": contract.digest(), "bundle_sha256": bundle.digest(),
                "receipt_sha256": "a" * 64, "evaluation_sha256": "b" * 64}
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
    policy = {"bundle_mode": "compiled", "timeout": 600, "evaluator_preparation_timeout": 900,
              "evaluator_preparation_wall_timeout": 1860, "timeout_source": "explicit",
              "evaluator_preparation_timeout_source": "explicit",
              "evaluator_preparation_wall_timeout_source": "explicit"}
    started = {"schema_version": "2", "parent_run_id": parent.id, "attempt_id": "preparation-" + "a" * 32,
               "status": "started", "stage": "preparation", "error_category": None, "recoverable": False,
               "preparation_budgets": {"candidate_timeout_seconds": 600, "request_timeout_seconds": 900,
                                       "wall_timeout_seconds": 1860}}
    events = [{"type": "evolution_requested", "payload": policy},
              {"type": "bundle_preparation_started", "payload": started},
              {"type": "bundle_profile_prepared"}, {"type": "bundle_candidate_delivered", "payload": terminal}]
    store = SimpleNamespace(get_run_by_workspace=lambda _: parent,
                            get_run=lambda identifier: parent if identifier == parent.id else child,
                            get_current_plan=lambda _: plan, list_events=lambda _: events,
                            list_artifacts=lambda _: artifacts)
    preparation = {"schema_version": "1", "parent_run_id": parent.id, "attempt_id": None,
                   "status": "prepared", "stage": "profile_publish", "error_category": None, "recoverable": False}
    monkeypatch.setattr(a, "ReadOnlyStore", lambda _: store)
    monkeypatch.setattr(a, "validate_automatic_solve_bundle", lambda *_: None)
    monkeypatch.setattr(a, "automatic_bundle_preparation_status", lambda *_: preparation)
    (slot / "cli.json").write_bytes(canonical_json(cli))
    return SimpleNamespace(slot=slot, workspace=workspace, package=package, contract=contract,
                           terminal=terminal, cli=cli, plan=plan, events=events, artifacts=artifacts,
                           store=store, parent=parent, child=child, sources=sources, frozen=frozen,
                           preparation=preparation, evaluator=evaluator)


def repin(f, *, replacements=None, removed=(), protocol=None):
    root = f.package.delivery_path
    manifest = json.loads((root / "delivery.json").read_bytes())
    manifest["identity"] = {key: f.terminal[key] for key in manifest["identity"]}
    if protocol is not None:
        manifest["protocol"] = protocol
    for name in removed:
        (root / name).unlink()
        del manifest["files"][name]
    for name, raw in (replacements or {}).items():
        (root / name).write_bytes(raw)
        manifest["files"][name] = {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    raw = canonical_json(manifest)
    (root / "delivery.json").write_bytes(raw)
    f.terminal["delivery_sha256"] = hashlib.sha256(raw).hexdigest()
    (f.slot / "cli.json").write_bytes(canonical_json(f.cli))


@pytest.mark.parametrize("value", [0, 2, 3])
def test_verified_source_delivery_reports_feasibility_and_optimality_separately(modules, tmp_path, monkeypatch, value):
    f = fixture(modules, tmp_path, monkeypatch, value=value)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = modules.analysis.inspect_product(tmp_path)
    assert result["primary_valid_completion"] is True
    assert result["preparation_verified"] is result["contract_verified"] is result["delivery_verified"] is True
    assert result["source_evidence_verified"] is result["source_check_validity"] is True
    assert result["source_python_count"] == 2
    assert result["source_checks"] == [{"id": "python-files", "kind": "python_file_count",
                                         "minimum": 2, "observed": 2, "passed": True}]
    assert result["quality"] == value and result["quality_gap"] == 3 - value
    assert result["optimal"] is (value == 3)
    assert modules.analysis.verified_preparation(tmp_path)[1].fingerprint == f.frozen.fingerprint
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("value", [-1, 4, True, 2.0, "3", None])
def test_verified_delivery_cannot_override_independent_math(modules, tmp_path, monkeypatch, value):
    fixture(modules, tmp_path, monkeypatch, value=value)
    result = modules.analysis.inspect_product(tmp_path)
    assert result["delivery_verified"] is result["source_evidence_verified"] is True
    assert result["output_check"]["validity"] is result["primary_valid_completion"] is False
    assert result["quality"] is result["quality_gap"] is None


@pytest.mark.parametrize("drift", ["input", "contract", "preparation", "frozen"])
def test_verified_preparation_rejects_input_contract_status_or_frozen_drift(modules, tmp_path, monkeypatch, drift):
    f = fixture(modules, tmp_path, monkeypatch)
    if drift == "input":
        (f.workspace / "data/raw/limit.json").write_text('{"limit":2}\n')
    elif drift == "contract":
        f.plan.algorithm_problem["hard_constraints"][1]["source_check"]["minimum"] = 1
    elif drift == "preparation":
        f.preparation["status"] = "failed"
    else:
        (f.frozen.root / "evaluator.py").chmod(0o600)
        (f.frozen.root / "evaluator.py").write_text("raise AssertionError('must not execute')\n")
    with pytest.raises((ValueError, EvaluatorBundleError)):
        modules.analysis.verified_preparation(tmp_path)
    result = modules.analysis.inspect_product(tmp_path)
    assert result["primary_valid_completion"] is False
    assert result["quality"] is result["quality_gap"] is None


@pytest.mark.parametrize("drift", [
    "cli_parent", "event", "duplicate_event", "child", "child_workspace", "terminal_contract", "delivery_path",
    "output_copy", "artifact", "missing_evidence", "protocol", "source_count", "source_evidence", "invalid_report",
])
def test_delivery_binding_and_canonical_source_evidence_cannot_be_bypassed(modules, tmp_path, monkeypatch, drift):
    f = fixture(modules, tmp_path, monkeypatch)
    if drift == "cli_parent":
        f.cli["run_id"] = "wrong-parent"
    elif drift == "event":
        f.events[-1]["payload"] = {**f.terminal, "candidate_id": "other"}
    elif drift == "duplicate_event":
        f.events.append(f.events[-1])
    elif drift == "child":
        f.child.status = RunStatus.FAILED
    elif drift == "child_workspace":
        f.child.workspace = f.workspace / "other"
    elif drift == "terminal_contract":
        f.terminal["contract_sha256"] = "d" * 64
    elif drift == "delivery_path":
        f.terminal["delivery_path"] = "../other"
    elif drift == "output_copy":
        (f.workspace / "output/result.json").write_text('{"value":2}\n')
    elif drift == "artifact":
        f.artifacts[0]["sha256"] = "d" * 64
    elif drift == "missing_evidence":
        repin(f, removed=("evaluation/source-checks.json",))
    elif drift == "protocol":
        repin(f, protocol="lunar-bundle-delivery-v1")
    elif drift == "source_count":
        raw = f.sources["main.py"]
        bundle = CandidateSourceBundle(f.contract.digest(), "main.py", (
            CandidateSourceFile("main.py", len(raw), hashlib.sha256(raw).hexdigest()),
        ))
        f.terminal["bundle_sha256"] = bundle.digest()
        repin(f, removed=("source/empty.py",), replacements={
            "source-bundle.json": canonical_json(bundle.to_dict()),
            "evaluation/source-checks.json": canonical_json(source_check_evidence(f.contract, bundle)),
        })
    elif drift == "source_evidence":
        evidence = json.loads((f.package.delivery_path / "evaluation/source-checks.json").read_bytes())
        evidence["checks"][0]["observed"] = 999
        repin(f, replacements={"evaluation/source-checks.json": canonical_json(evidence)})
    else:
        report = EvaluationReport("1", f.evaluator["evaluator_id"], 0, 0, {},
                                  ({"code": "valid-value", "message": "Invalid."},)).to_dict()
        repin(f, replacements={"evaluation/report.json": canonical_json(report)})
    (tmp_path / "cli.json").write_bytes(canonical_json(f.cli))
    result = modules.analysis.inspect_product(tmp_path)
    assert result["primary_valid_completion"] is result["delivery_verified"] is False
    assert result["quality"] is result["quality_gap"] is None


@pytest.mark.parametrize("drift", ["input_missing", "input_value", "input_bytes", "evaluator", "spec"])
def test_rehashed_portable_delivery_stays_bound_to_native_preparation(modules, tmp_path, monkeypatch, drift):
    f = fixture(modules, tmp_path, monkeypatch)
    if drift == "input_missing":
        repin(f, removed=("inputs/limit.json",))
        (f.package.delivery_path / "inputs").rmdir()
    elif drift in {"input_value", "input_bytes"}:
        content = b'{"limit":2}\n' if drift == "input_value" else b'{"limit": 3}\n'
        repin(f, replacements={"inputs/limit.json": content})
    elif drift == "evaluator":
        content = b"raise AssertionError('a foreign harness must not receive delivery credit')\n"
        spec = {**f.evaluator, "harness_sha256": hashlib.sha256(content).hexdigest(), "harness_size": len(content)}
        repin(f, replacements={"evaluation/evaluator.py": content, "evaluation/spec.json": canonical_json(spec)})
    else:
        spec = {**f.evaluator, "timeout_seconds": f.evaluator["timeout_seconds"] + 1}
        repin(f, replacements={"evaluation/spec.json": canonical_json(spec)})
    # The portable package itself is internally consistent after every hash is renewed.
    # Acceptance must still reject its disagreement with this native preparation.
    inspect_bundle_delivery(f.package.delivery_path, expected_delivery_sha256=f.terminal["delivery_sha256"])
    result = modules.analysis.inspect_product(tmp_path)
    assert result["preparation_verified"] is True
    assert result["output_check"] == {"validity": True, "quality": 3}
    assert result["primary_valid_completion"] is result["delivery_verified"] is False
    assert result["quality"] is result["quality_gap"] is None


def test_missing_run_is_read_only_and_has_null_quality(modules, tmp_path):
    result = modules.analysis.inspect_product(tmp_path)
    assert result["primary_valid_completion"] is result["preparation_verified"] is False
    assert result["quality"] is result["quality_gap"] is None
    assert list(tmp_path.iterdir()) == []


def test_read_only_store_connections_reject_writes(modules, tmp_path):
    path = tmp_path / "state.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE existing (value TEXT)")
    before = path.read_bytes()
    with modules.analysis.ReadOnlyStore(path)._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM existing").fetchone()[0] == 0
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("INSERT INTO existing VALUES ('mutated')")
    assert path.read_bytes() == before


def test_killed_wal_writer_rows_are_read_without_changing_retained_shm(modules, tmp_path):
    path = tmp_path / "state.db"
    program = (
        "import os,sqlite3,sys; "
        "c=sqlite3.connect(sys.argv[1]); "
        "c.execute('PRAGMA journal_mode=WAL'); "
        "c.execute('PRAGMA wal_autocheckpoint=0'); "
        "c.execute('CREATE TABLE existing (value TEXT)'); "
        "c.execute(\"INSERT INTO existing VALUES ('committed-in-wal')\"); "
        "c.commit(); os._exit(0)"
    )
    subprocess.run([sys.executable, "-c", program, str(path)], check=True, timeout=5)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    assert {"state.db", "state.db-wal", "state.db-shm"} <= set(before)
    with modules.analysis.ReadOnlyStore(path)._connect() as connection:
        assert connection.execute("SELECT value FROM existing").fetchone()[0] == "committed-in-wal"
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM existing")
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def journal(path, count=4):
    rows = []
    for index in range(1, count + 1):
        rows.extend([
            {"kind": "request_started", "index": index, "requested_model": "glm-5.2",
             "request_sha256": f"{index:064x}", "request_timeout_seconds": 600},
            {"kind": "request_finished", "index": index, "outcome": "succeeded", "elapsed_seconds": 2,
             "usage": {"input_tokens": 3, "output_tokens": 5, "total_tokens": 8},
             "known_usage": {"input_tokens": 3 * index, "output_tokens": 5 * index, "total_tokens": 8 * index},
             "failure_reason": None, "response_status": 200},
        ])
    path.write_bytes(b"".join(canonical_json(row) + b"\n" for row in rows))
    return rows


def test_usage_accepts_full_native_sequence_and_binds_transport_stages(modules, tmp_path):
    a = modules.analysis
    journal(tmp_path / "calls.jsonl", 20)
    result = a.usage_summary(tmp_path / "calls.jsonl")
    assert result["provider_requests"] == result["finished_requests"] == 20
    assert result["known_usage"] == {"input_tokens": 60, "output_tokens": 100, "total_tokens": 160}
    assert [row["stage"] for row in result["requests"][:4]] == [
        "contract_compiler", "evaluator_compiler", "evaluator_auditor", "candidate",
    ]
    request = result["requests"][3]
    row = {"request_index": 4, "request_sha256": request["request_sha256"], "stage": "candidate",
           "outcome": "response", "elapsed_ms": 10, "exchange_count": 1, "status": 200,
           "transport_observation": None, "private": "must-stay-private"}
    path = tmp_path / "transport.jsonl"
    path.write_bytes(canonical_json(row) + b"\n")
    assert "must-stay-private" not in json.dumps(a.transport_summary(path, result["requests"]))
    row["stage"] = "evaluator_auditor"
    path.write_bytes(canonical_json(row) + b"\n")
    with pytest.raises(ValueError, match="stage"):
        a.transport_summary(path, result["requests"])


@pytest.mark.parametrize("drift", ["21_requests", "overlap", "usage", "subtotal", "timeout", "model", "outcome"])
def test_invalid_usage_evidence_is_rejected(modules, tmp_path, drift):
    path = tmp_path / "calls.jsonl"
    rows = journal(path, 21 if drift == "21_requests" else 4)
    if drift == "overlap":
        rows[1], rows[2] = rows[2], rows[1]
    elif drift == "usage":
        rows[-1]["usage"]["input_tokens"] = True
    elif drift == "subtotal":
        rows[-1]["known_usage"]["total_tokens"] = 0
    elif drift == "timeout":
        rows[0]["request_timeout_seconds"] = 601
    elif drift == "model":
        rows[0]["requested_model"] = "private"
    elif drift == "outcome":
        rows[-1]["outcome"] = "private"
    path.write_bytes(b"".join(canonical_json(row) + b"\n" for row in rows))
    with pytest.raises(ValueError):
        modules.analysis.usage_summary(path)


@pytest.mark.parametrize("stage,count", [("compiler_response", 2), ("compiler_preflight", 2),
                                         ("auditor_response", 3), ("auditor_preflight", 3)])
def test_native_local_diagnostics_bind_to_accepted_preparation_requests(modules, tmp_path, stage, count):
    a = modules.analysis
    journal(tmp_path / "calls.jsonl", count)
    detail = {"schema_version": "1", "stage": stage,
              "reason": "response_invalid" if stage.endswith("response") else "preflight_failed",
              "probe_index": None, "input_index": None, "order_index": None}
    product = {"preparation_verified": False, "preparation": {
        "status": "failed", "stage": stage, "error_category": "validation_error",
        "recoverable": False, "local_failure": detail,
    }}
    usage = a.usage_summary(tmp_path / "calls.jsonl")
    assert a.local_failure_summary(product, usage, None) == detail
    with pytest.raises(ValueError, match="context"):
        a.local_failure_summary(product, usage, {"fingerprint": "present"})
    usage["requests"][-1]["outcome"] = "provider_error"
    with pytest.raises(ValueError, match="request"):
        a.local_failure_summary(product, usage, None)


def retained_campaign(modules, tmp_path, monkeypatch, *, prepared=True):
    a, c = modules.analysis, modules.campaign
    manifest = {"campaign_root": ".lunar/offline134", "product_commit": "a" * 40}
    monkeypatch.setattr(a, "REPO", tmp_path)
    monkeypatch.setattr(a, "HERE", tmp_path / "spec/measurement")
    monkeypatch.setattr(a, "MANIFEST", tmp_path / "manifest.json")
    a.HERE.mkdir(parents=True)
    c.write_new(a.MANIFEST, manifest)
    root = tmp_path / manifest["campaign_root"]
    slot = root / "attempt-001"
    marker = {"campaign_id": a.CAMPAIGN_ID, "manifest_sha256": a.sha(a.MANIFEST),
              "registration_commit": "b" * 40}
    c.write_new(root / "started.json", marker)
    c.write_new(root / "finished.json", marker)
    c.write_new(slot / "started.json", marker)
    c.write_new(slot / "finished.json", {"process_status": "exited", "exit_code": 0,
                                         "cleanup_verified": True, "remaining_observed_pids": [],
                                         "elapsed_seconds": 10})
    if prepared:
        f = fixture(modules, slot, monkeypatch)
        frozen = {"fingerprint": f.frozen.fingerprint, "contract_sha256": f.frozen.contract_sha256,
                  "input_profile_sha256": f.frozen.input_profile_sha256,
                  "files": {p.name: a.sha(p) for p in sorted(f.frozen.root.iterdir())}}
        c.write_new(slot / "frozen.json", frozen)
        rows = []
        for index, definition in enumerate(modules.case.holdouts(), 1):
            expected = definition["expected"]
            row = {"name": definition["name"], "status": "completed", "matched": True,
                   "snapshot_started": True, "observed": {
                       "validity": expected["validity"], "quality": expected["quality"],
                       "combined_score": expected["combined_score"], "constraint_code_present": True,
                   }}
            rows.append(row)
            c.write_new(slot / "holdouts" / f"{index:03d}.json", row)
        c.write_new(slot / "worker-finished.json", {"status": "completed", "stage": "finished", "native_exit_code": 0,
                                                     "frozen": frozen, "holdouts": rows})
        journal(slot / "calls.jsonl")
    return manifest, root, slot


def test_summary_publishes_once_and_does_not_execute_retained_programs(modules, tmp_path, monkeypatch):
    manifest, root, _ = retained_campaign(modules, tmp_path, monkeypatch)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}

    def forbidden(*args, **kwargs):
        pytest.fail("read-only analysis attempted execution")

    import famou.evaluator_bundle as evaluator
    from famou import runtime
    monkeypatch.setattr(modules.case, "_snapshot_probe", forbidden)
    monkeypatch.setattr(modules.case, "audit_holdouts", forbidden)
    monkeypatch.setattr(evaluator, "_snapshot_probe", forbidden)
    monkeypatch.setattr(runtime.OpenAICompatibleRuntime, "complete", forbidden)
    result = modules.analysis.summarize(manifest)
    assert result["primary_success"] == result["joint_success"] == result["preparation_success"] == 1
    assert result["quality"] == 3 and result["gap"] == 0 and result["optimal"] is True
    assert result["holdouts"]["matched"] == result["holdouts"]["executed"] == 8
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
    with pytest.raises(FileExistsError):
        modules.analysis.summarize(manifest)


def test_failure_before_preparation_is_summarized_without_creating_product_state(modules, tmp_path, monkeypatch):
    manifest, _, slot = retained_campaign(modules, tmp_path, monkeypatch, prepared=False)
    result = modules.analysis.summarize(manifest)
    assert result["primary_success"] == result["joint_success"] == result["preparation_success"] == 0
    assert result["quality"] is result["gap"] is result["local_failure"] is None
    assert not (slot / "home").exists() and not (slot / "workspace").exists()


@pytest.mark.parametrize("state", ["worker_missing", "worker_failed", "timed_out", "cleanup_failed"])
def test_partial_attempt_retains_product_observations_but_null_official_quality(modules, tmp_path, monkeypatch, state):
    manifest, _, slot = retained_campaign(modules, tmp_path, monkeypatch)
    if state == "worker_missing":
        (slot / "worker-finished.json").unlink()
    elif state == "worker_failed":
        path = slot / "worker-finished.json"
        value = json.loads(path.read_bytes())
        value.update(status="failed", stage="holdouts")
        path.write_bytes(canonical_json(value))
    else:
        path = slot / "finished.json"
        value = json.loads(path.read_bytes())
        if state == "timed_out":
            value.update(process_status="timed_out", exit_code=-15)
        else:
            value["cleanup_verified"] = False
        path.write_bytes(canonical_json(value))
    result = modules.analysis.summarize(manifest)
    assert result["primary_success"] == 1 and result["joint_success"] == 0
    assert result["product"]["output_check"] == {"validity": True, "quality": 3}
    assert result["quality"] is result["gap"] is None and result["optimal"] is False


@pytest.mark.parametrize("drift", ["frozen", "binding", "holdout_claim", "holdout_bool", "holdout_gap", "worker_holdouts"])
def test_invalid_retained_evidence_prevents_summary_publication(modules, tmp_path, monkeypatch, drift):
    manifest, root, slot = retained_campaign(modules, tmp_path, monkeypatch)
    if drift == "frozen":
        path = slot / "frozen.json"
        value = json.loads(path.read_bytes())
        value["fingerprint"] = "f" * 64
    elif drift == "binding":
        path = root / "finished.json"
        value = json.loads(path.read_bytes())
        value["manifest_sha256"] = "f" * 64
    elif drift == "holdout_gap":
        (slot / "holdouts/002.json").unlink()
        path = None
    elif drift == "worker_holdouts":
        path = slot / "worker-finished.json"
        value = json.loads(path.read_bytes())
        value["holdouts"] = []
    else:
        path = slot / "holdouts/001.json"
        value = json.loads(path.read_bytes())
        if drift == "holdout_claim":
            value["observed"]["validity"] = 1
        else:
            value["observed"]["quality"] = True
    if path is not None:
        path.write_bytes(canonical_json(value))
    with pytest.raises(ValueError):
        modules.analysis.summarize(manifest)
    assert not (modules.analysis.HERE.parent / "postrun").exists()


@pytest.mark.parametrize("index,timeout,valid", [(1, 601, False), (2, 900, True), (3, 899, True),
                                              (2, 901, False), (4, 601, False), (4, 0.1, True)])
def test_registered_request_caps_are_stage_specific(modules, tmp_path, index, timeout, valid):
    path = tmp_path / "calls.jsonl"
    rows = journal(path)
    rows[2 * (index - 1)]["request_timeout_seconds"] = timeout
    path.write_bytes(b"".join(canonical_json(row) + b"\n" for row in rows))
    if valid:
        assert modules.analysis.usage_summary(path)["requests"][index - 1]["request_timeout_seconds"] == timeout
    else:
        with pytest.raises(ValueError, match="timeout"):
            modules.analysis.usage_summary(path)


@pytest.mark.parametrize("status", [None, 200, 429, 503])
def test_transport_status_is_observed_without_inventing_success(modules, tmp_path, status):
    path = tmp_path / "calls.jsonl"
    rows = journal(path, 1)
    rows[-1]["response_status"] = None
    path.write_bytes(b"".join(canonical_json(row) + b"\n" for row in rows))
    usage = modules.analysis.usage_summary(path)
    row = {"request_index": 1, "request_sha256": usage["requests"][0]["request_sha256"],
           "stage": "contract_compiler", "outcome": "response", "exchange_count": 1, "status": status}
    transport = tmp_path / "transport.jsonl"
    transport.write_bytes(canonical_json(row) + b"\n")
    assert modules.analysis.transport_summary(transport, usage["requests"])[0]["status"] == status


def test_transport_summary_aligns_missing_optional_rows_as_unknown(modules, tmp_path):
    calls = tmp_path / "calls.jsonl"
    journal(calls, 2)
    requests = modules.analysis.usage_summary(calls)["requests"]
    row = {"request_index": 1, "request_sha256": requests[0]["request_sha256"],
           "stage": "contract_compiler", "outcome": "response", "exchange_count": 1,
           "status": 200}
    transport = tmp_path / "transport.jsonl"
    transport.write_bytes(canonical_json(row) + b"\n")

    projected = modules.analysis.transport_summary(transport, requests)

    assert [item["index"] for item in projected] == [1, 2]
    assert projected[0]["status"] == 200
    assert projected[1] == {
        "index": 2, "stage": "evaluator_compiler", "outcome": "unavailable",
        "transport_observation": None, "status": None, "exchange_count": 0,
        "elapsed_ms": None, "request_body_bytes": None, "response_body_bytes": None,
    }


@pytest.mark.parametrize("mutation", ["duplicate", "unbound"])
def test_transport_summary_rejects_duplicate_or_unbound_exchange(modules, tmp_path, mutation):
    calls = tmp_path / "calls.jsonl"
    journal(calls, 1)
    requests = modules.analysis.usage_summary(calls)["requests"]
    row = {"request_index": 1, "request_sha256": requests[0]["request_sha256"],
           "stage": "contract_compiler", "outcome": "response", "exchange_count": 1,
           "status": 200}
    rows = [row, dict(row)] if mutation == "duplicate" else [
        {**row, "request_index": 2, "request_sha256": "b" * 64},
    ]
    transport = tmp_path / "transport.jsonl"
    transport.write_bytes(b"".join(canonical_json(item) + b"\n" for item in rows))

    with pytest.raises(ValueError, match="index"):
        modules.analysis.transport_summary(transport, requests)


@pytest.mark.parametrize("field,value", [("status", True), ("status", 99), ("status", 600),
                                         ("status", "private"), ("exchange_count", 2),
                                         ("request_sha256", None), ("request_sha256", "a" * 64),
                                         ("stage", "evaluator_compiler"), ("status", 503)])
def test_transport_status_requires_one_bound_consistent_exchange(modules, tmp_path, field, value):
    journal(tmp_path / "calls.jsonl", 1)
    requests = modules.analysis.usage_summary(tmp_path / "calls.jsonl")["requests"]
    row = {"request_index": 1, "request_sha256": requests[0]["request_sha256"], "stage": "contract_compiler",
           "outcome": "response", "exchange_count": 1, "status": 200}
    row[field] = value
    path = tmp_path / "transport.jsonl"
    path.write_bytes(canonical_json(row) + b"\n")
    with pytest.raises(ValueError):
        modules.analysis.transport_summary(path, requests)


def test_one_observed_native_exchange_may_include_http_redirects(modules, tmp_path):
    journal(tmp_path / "calls.jsonl", 1)
    requests = modules.analysis.usage_summary(tmp_path / "calls.jsonl")["requests"]
    detail = {"last_milestone": "response_headers_received", "http_exchange_index": 2, "elapsed_ms": 10}
    row = {"request_index": 1, "request_sha256": requests[0]["request_sha256"], "stage": "contract_compiler",
           "outcome": "response", "exchange_count": 1, "status": 200, "transport_observation": detail}
    path = tmp_path / "transport.jsonl"
    path.write_bytes(canonical_json(row) + b"\n")
    assert modules.analysis.transport_summary(path, requests)[0]["transport_observation"] == detail


@pytest.mark.parametrize("drift", ["missing", "duplicate", "candidate", "request", "wall", "source",
                                  "start_missing", "start_budget", "start_parent", "profile_candidate",
                                  "profile_evaluator"])
def test_registered_preparation_policy_is_required_for_success(modules, tmp_path, monkeypatch, drift):
    f = fixture(modules, tmp_path, monkeypatch)
    policy = f.events[0]["payload"]
    if drift == "missing":
        f.events.pop(0)
    elif drift == "duplicate":
        f.events.insert(0, f.events[0])
    elif drift in {"candidate", "request", "wall"}:
        policy[{"candidate": "timeout", "request": "evaluator_preparation_timeout",
                "wall": "evaluator_preparation_wall_timeout"}[drift]] += 1
    elif drift == "source":
        policy["evaluator_preparation_wall_timeout_source"] = "default"
    elif drift == "start_missing":
        f.events.pop(1)
    elif drift == "start_budget":
        f.events[1]["payload"]["preparation_budgets"]["request_timeout_seconds"] = 600
    elif drift == "start_parent":
        f.events[1]["payload"]["parent_run_id"] = "other"
    else:
        path = f.workspace / "bundle-profile.json"
        profile = json.loads(path.read_bytes())
        target = profile if drift == "profile_candidate" else profile["evaluator"]
        target["timeout_seconds"] = 900
        path.write_bytes(canonical_json(profile))
    result = modules.analysis.inspect_product(tmp_path)
    assert result["primary_valid_completion"] is result["preparation_verified"] is False
    assert result["quality"] is result["quality_gap"] is None


def test_persisted_parent_status_and_budget_sources_are_independent_of_cli(modules, tmp_path, monkeypatch):
    f = fixture(modules, tmp_path, monkeypatch)
    f.parent.status = RunStatus.RUNNING
    f.cli["status"] = "failed"
    (tmp_path / "cli.json").write_bytes(canonical_json(f.cli))
    result = modules.analysis.inspect_product(tmp_path)
    assert result["product_status"] == "failed"
    assert result["persisted_parent_status"] == "running"
    assert result["preparation_budgets"] == {
        "candidate_timeout": {"seconds": 600, "source": "explicit"},
        "evaluator_preparation_timeout": {"seconds": 900, "source": "explicit"},
        "evaluator_preparation_wall_timeout": {"seconds": 1860, "source": "explicit"}}


@pytest.mark.parametrize("wall", [False, True])
def test_native_request_and_wall_diagnostics_survive_safe_projection(modules, tmp_path, monkeypatch, wall):
    f = fixture(modules, tmp_path, monkeypatch)
    f.parent.status = RunStatus.RUNNING
    f.preparation.update(schema_version="4" if wall else "3", status="failed", stage="evaluator_compile",
                         error_category="preparation_timeout" if wall else "runtime_error", recoverable=True,
                         request_failure={"schema_version": "1", "reason": "transport_timeout",
                                          "response_status": None, "transport_observation": None,
                                          "request_observation": {"phase": "open_response", "elapsed_ms": 900000,
                                                                  "request_timeout_ms": 900000}})
    if wall:
        f.preparation["wall_failure"] = {"schema_version": "1", "reason": "wall_timeout",
                                         "elapsed_ms": 1860000, "wall_timeout_ms": 1860000}
    result = modules.analysis.inspect_product(tmp_path)
    assert result["preparation"]["schema_version"] == ("4" if wall else "3")
    assert result["preparation"]["request_failure"] == f.preparation["request_failure"]
    if wall:
        assert result["preparation"]["wall_failure"] == f.preparation["wall_failure"]
    assert result["primary_valid_completion"] is False


@pytest.mark.parametrize("drift", [None, "clipped", "reason", "status", "timing", "outcome", "later_request", "frozen"])
def test_native_request_failure_binds_to_the_final_accounted_request(modules, tmp_path, drift):
    a = modules.analysis
    path = tmp_path / "calls.jsonl"
    rows = journal(path, 2)
    observation = {"phase": "open_response", "elapsed_ms": 600000, "request_timeout_ms": 600000}
    if drift == "clipped":
        rows[-2]["request_timeout_seconds"] = 599.9995
        observation["request_timeout_ms"] = 599999
    rows[-1].update(outcome="provider_error", failure_reason="transport_timeout", response_status=None,
                    usage=None, known_usage=rows[1]["known_usage"], observation=observation)
    path.write_bytes(b"".join(canonical_json(row) + b"\n" for row in rows))
    usage = a.usage_summary(path)
    detail = {"schema_version": "1", "reason": "transport_timeout", "response_status": None,
              "request_observation": dict(observation), "transport_observation": None}
    product = {"preparation_verified": False, "persisted_parent_status": "running", "preparation": {
        "schema_version": "3", "status": "failed", "stage": "evaluator_compile", "recoverable": True,
        "error_category": "runtime_error", "request_failure": detail}}
    frozen = None
    if drift == "reason":
        detail["reason"] = "transport_error"
    elif drift == "status":
        detail["response_status"] = 503
    elif drift == "timing":
        detail["request_observation"]["request_timeout_ms"] = 900000
    elif drift == "outcome":
        usage["requests"][-1]["outcome"] = "succeeded"
    elif drift == "later_request":
        usage["provider_requests"] += 1
    elif drift == "frozen":
        frozen = {"fingerprint": "present"}
    if drift in {None, "clipped"}:
        assert a.request_failure_summary(product, usage, frozen) == detail
    else:
        with pytest.raises(ValueError):
            a.request_failure_summary(product, usage, frozen)


def test_request_admission_after_failed_accounting_is_rejected(modules, tmp_path):
    path = tmp_path / "calls.jsonl"
    rows = journal(path)
    rows[3]["outcome"] = "provider_error"
    path.write_bytes(b"".join(canonical_json(row) + b"\n" for row in rows))
    with pytest.raises(ValueError, match="admission_stopped"):
        modules.analysis.usage_summary(path)


@pytest.mark.parametrize("value", [True, 1860001, "private", 0])
def test_invalid_wall_failure_detail_never_enters_public_results(modules, tmp_path, monkeypatch, value):
    f = fixture(modules, tmp_path, monkeypatch)
    f.preparation.update(schema_version="4", status="failed", stage="profile_publish",
                         error_category="preparation_timeout", recoverable=True,
                         wall_failure={"schema_version": "1", "reason": "wall_timeout",
                                       "elapsed_ms": 1860000, "wall_timeout_ms": value})
    result = modules.analysis.inspect_product(tmp_path)
    assert result["preparation"] is None and result["primary_valid_completion"] is False
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize("wall", [False, True])
def test_failed_preparation_summary_keeps_denominator_unknown_usage_and_native_details(
    modules, tmp_path, monkeypatch, wall,
):
    manifest, _, slot = retained_campaign(modules, tmp_path, monkeypatch, prepared=False)
    f = fixture(modules, slot, monkeypatch)
    f.parent.status = RunStatus.RUNNING
    f.cli["status"] = "failed"
    (slot / "cli.json").write_bytes(canonical_json(f.cli))
    detail = {"schema_version": "1", "reason": "transport_timeout", "response_status": None,
              "transport_observation": None, "request_observation": {
                  "phase": "open_response", "elapsed_ms": 900000, "request_timeout_ms": 900000}}
    f.preparation.update(schema_version="4" if wall else "3", status="failed", stage="evaluator_compile",
                         error_category="preparation_timeout" if wall else "runtime_error", recoverable=True,
                         request_failure=detail)
    if wall:
        f.preparation["wall_failure"] = {"schema_version": "1", "reason": "wall_timeout",
                                         "elapsed_ms": 1860000, "wall_timeout_ms": 1860000}
    path = slot / "calls.jsonl"
    rows = journal(path, 2)
    rows[-2]["request_timeout_seconds"] = 900
    rows[-1].update(outcome="provider_error", failure_reason="transport_timeout", response_status=None,
                    usage=None, known_usage=rows[1]["known_usage"], observation=detail["request_observation"])
    path.write_bytes(b"".join(canonical_json(row) + b"\n" for row in rows))
    before = {p: p.read_bytes() for p in slot.rglob("*") if p.is_file()}
    result = modules.analysis.summarize(manifest)
    assert result["planned_attempts"] == 1
    assert result["primary_success"] == result["preparation_success"] == result["joint_success"] == 0
    assert result["request_failure"] == detail
    assert result["wall_failure"] == (f.preparation["wall_failure"] if wall else None)
    assert result["usage"]["total_usage"] is result["quality"] is result["gap"] is None
    assert result["usage"]["known_usage"]["total_tokens"] == 8
    assert {p: p.read_bytes() for p in slot.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("outcome", ["provider_error", "observed_token_threshold_reached"])
def test_wall_failure_without_typed_request_detail_retains_final_stopped_request(modules, tmp_path, outcome):
    path = tmp_path / "calls.jsonl"
    rows = journal(path, 2)
    rows[-1].update(outcome=outcome, response_status=None)
    path.write_bytes(b"".join(canonical_json(row) + b"\n" for row in rows))
    usage = modules.analysis.usage_summary(path)
    detail = {"schema_version": "1", "reason": "wall_timeout", "elapsed_ms": 1860000, "wall_timeout_ms": 1860000}
    product = {"persisted_parent_status": "running", "preparation_verified": False, "preparation": {
        "schema_version": "4", "status": "failed", "stage": "evaluator_compile", "recoverable": True,
        "error_category": "preparation_timeout", "wall_failure": detail}}
    assert modules.analysis.wall_failure_summary(product, usage, None) == detail
    assert modules.analysis.request_failure_summary(product, usage, None) is None


@pytest.mark.parametrize("native_exit", [None, 1, True])
def test_joint_success_and_official_quality_require_native_integer_zero(modules, tmp_path, monkeypatch, native_exit):
    manifest, _, slot = retained_campaign(modules, tmp_path, monkeypatch)
    path = slot / "worker-finished.json"
    worker = json.loads(path.read_bytes())
    worker["native_exit_code"] = native_exit
    path.write_bytes(canonical_json(worker))
    if native_exit is True:
        with pytest.raises(ValueError, match="native_exit"):
            modules.analysis.summarize(manifest)
    else:
        result = modules.analysis.summarize(manifest)
        assert result["primary_success"] == 1 and result["joint_success"] == 0
        assert result["quality"] is result["gap"] is None
