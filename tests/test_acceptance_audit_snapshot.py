"""Provider-free integration boundaries for the combined acceptance audit wrapper."""
from __future__ import annotations

import copy
import gc
import subprocess
from pathlib import Path

import pytest
from test_algorithm import _contract
from test_audit_request import _request_payload

from lunar_evolution._audit_request import AcceptanceAuditError, build_acceptance_audit_request
from lunar_evolution.acceptance_audit import audit_acceptance_artifacts
from lunar_evolution.acceptance_observer import build_acceptance_manifest
from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.controller import LocalController
from lunar_evolution.conversational import build_algorithm_plan
from lunar_evolution.holdout_audit import build_holdout_declaration
from lunar_evolution.store import Store


@pytest.fixture(autouse=True)
def forbid_execution(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("audit constructed a controller or executed a process")

    monkeypatch.setattr(LocalController, "__init__", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


def request_payload(tmp_path: Path):
    payload = _request_payload()
    payload["manifest"] = dict(payload["manifest"])
    payload["manifest"]["campaign_root"] = "campaign-root-new"
    payload["paths"] = dict(payload["paths"])
    payload["paths"]["parent_workspace"] = "parent"
    payload["paths"]["child_workspace"] = "parent/evolution-run"
    return build_acceptance_audit_request(payload)


def seed_store(tmp_path: Path):
    database = tmp_path / "state.db"
    store = Store(database)
    store.initialize()
    parent = store.create_run("parent", tmp_path / "campaign-root-new" / "parent")
    child = store.create_run("child", tmp_path / "campaign-root-new" / "parent" / "evolution-run")
    child.workspace.mkdir(parents=True)
    contract = AlgorithmProblemContract.from_dict(_contract(evolution={"strategy": "population"}))
    store.attach_plan_to_run(parent.id, build_algorithm_plan(parent.goal, contract))
    payload = _request_payload()
    payload["identities"] = dict(payload["identities"])
    payload["identities"].update(parent_run_id=parent.id, child_run_id=child.id)
    payload["manifest"] = dict(payload["manifest"])
    payload["manifest"].pop("manifest_sha256")
    payload["manifest"]["task_sha256"] = contract.digest()
    payload["manifest"] = build_acceptance_manifest(payload["manifest"])
    payload["pins"]["contract_sha256"] = contract.digest()
    declaration = dict(payload["holdout_declaration"])
    declaration.pop("declaration_sha256")
    declaration["manifest_sha256"] = payload["manifest"]["manifest_sha256"]
    payload["holdout_declaration"] = build_holdout_declaration(declaration)
    payload["paths"] = dict(payload["paths"])
    payload["paths"].update(parent_workspace="parent", child_workspace="parent/evolution-run")
    request = build_acceptance_audit_request(payload)
    gc.collect()
    return database, request


def audit(request, database: Path, root: Path):
    return audit_acceptance_artifacts(
        request, database=database, audit_root=root, stage_receipts=[], holdout_receipts=[],
    )


def test_missing_runs_are_unverifiable_without_provider_or_controller(tmp_path: Path):
    request = request_payload(tmp_path)
    database = tmp_path / "state.db"
    store = Store(database)
    store.initialize()
    root = tmp_path / "campaign-root-new"
    root.mkdir()
    gc.collect()
    before = database.read_bytes()
    report = audit(request, database, root)
    assert report["boundaries"][1]["boundary"] == "snapshot"
    assert report["boundaries"][1]["status"] == "unverifiable"
    assert report["primary_eligible"] is False and report["joint_eligible"] is False
    assert report["provider_called_during_audit"] is False
    assert report["executed_during_audit"] is False
    assert report["mutated_during_audit"] is False
    assert database.read_bytes() == before


def test_intake_only_store_does_not_initialize_or_call_runtime(tmp_path: Path):
    database, request = seed_store(tmp_path)
    root = tmp_path / "campaign-root-new"
    before = database.read_bytes()
    report = audit(request, database, root)
    assert report["primary_eligible"] is False
    assert report["boundaries"][1]["status"] == "verified"
    prepared = next(item for item in report["boundaries"] if item["boundary"] == "preparation")
    assert prepared["status"] == "unverifiable"
    assert prepared["reason"] == "prepared_receipt_missing"
    assert database.read_bytes() == before
    assert not (root / "bundle-profile.json").exists()


def test_campaign_root_name_and_symlink_are_rejected_without_opening_source(tmp_path: Path):
    database, request = seed_store(tmp_path)
    before = database.read_bytes()
    wrong = tmp_path / "different-root"
    wrong.mkdir()
    report = audit(request, database, wrong)
    assert report["boundaries"][1]["status"] == "failed"
    assert report["boundaries"][1]["reason"] == "campaign_root_mismatch"
    (tmp_path / "links").mkdir()
    link = tmp_path / "links" / "campaign-root-new"
    link.symlink_to(tmp_path / "campaign-root-new", target_is_directory=True)
    report = audit(request, database, link)
    assert report["boundaries"][1]["status"] == "unverifiable"
    assert database.read_bytes() == before


def test_request_and_stage_receipts_are_not_used_as_launch_authority(tmp_path: Path):
    database, request = seed_store(tmp_path)
    forged = copy.deepcopy(request)
    forged["manifest"]["provider"] = "should-not-be-used"
    before = database.read_bytes()
    with pytest.raises(AcceptanceAuditError):
        audit(forged, database, tmp_path / "campaign-root-new")
    assert database.read_bytes() == before
