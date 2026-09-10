"""Rebind the sealed audit fixtures and independently check 078 paths and helper closure."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "specs/078-master-planning-role-measurement/measurement/adapter.py"
_spec = importlib.util.spec_from_file_location("offline078_audit_adapter", ADAPTER)
_adapter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_adapter)
_previous = _adapter.load_previous_test("audit", overrides={"ADAPTER": ADAPTER})
globals().update({name: value for name, value in vars(_previous).items()
                  if name in {"adapter", "audit"} or name.startswith("test_")})


def test_prior_audit_is_privately_bound_without_changing_four_slot_module(adapter, audit):
    untouched = adapter.load_prior("audit")
    assert len(untouched.ORDER) == 4 and len(audit.ORDER) == 2
    assert untouched.CAMPAIGN_ID != audit.CAMPAIGN_ID
    assert audit.native.IMPLEMENTATION == "fba6ab8cf5b27d3bd1b42f353907a6ae21c25ef9"
    assert untouched.IMPLEMENTATION == "5c89e049c184c52090f665131e3290ea3359bc04"
    assert audit.check_source.__globals__ is audit.native.__dict__
    assert audit.check_cases.__globals__["check_workflow"] is audit.check_workflow
    assert audit.native.check_schedule is not audit.check_schedule
    manifest, request = _previous.schedule(audit)
    audit.check_schedule(manifest)
    for slot in manifest["slots"]:
        audit.check_workflow(manifest, slot, request)
    with pytest.raises(untouched.AuditError):
        untouched.check_schedule(manifest)


def freeze_fixture(tmp_path, monkeypatch, audit):
    here = tmp_path / "specs/078-master-planning-role-measurement/measurement"
    campaign = tmp_path / ".lunar" / audit.CAMPAIGN_ID
    paths = {*(here.parent / name for name in audit.REQUIRED_CODE),
             *(tmp_path / relative for relative in audit.EXPECTED_HELPERS),
             tmp_path / "tests/test_measurement078_audit.py", tmp_path / "tests/test_measurement078_runner.py",
             tmp_path / ".lunar/real-eval-20260908/ccswitch.py", tmp_path / ".venv/bin/lunar-agent",
             tmp_path / ".lunar/harness-venv-high-score-20260909/bin/python",
             campaign / "inputs/profile.json", campaign / "readiness.json"}
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"frozen\n")
    digest = hashlib.sha256(b"frozen\n").hexdigest()
    monkeypatch.setattr(audit, "HELPER_FILES", dict.fromkeys(audit.EXPECTED_HELPERS, digest))
    monkeypatch.setattr(audit.subprocess, "check_output", lambda *_a, **_k: b"frozen\n")
    manifest = {"frozen_files_sha256": {path.relative_to(tmp_path).as_posix(): digest for path in paths}}
    audit.check_frozen(tmp_path, campaign, manifest, here)
    return here, campaign, manifest


_previous.freeze_fixture = freeze_fixture


def test_dry_run_uses_new_scenarios_and_freezes_all_test_bytes(adapter):
    dry = adapter.load_current("dry_run")
    assert dry.native.NODES == dry.NODES and dry.native.SCENARIOS == dry.SCENARIOS
    assert {"tests/test_measurement078_runner.py", "tests/test_measurement078_audit.py",
            "tests/test_master_plan_envelope_integration.py", "tests/test_master_plan_vocabulary.py",
            "tests/test_master_planning_role_integration.py",
            "specs/078-master-planning-role-measurement/postrun/test_audit.py"} <= set(dry.NODES)
    assert "tests/test_measurement074_runner.py" not in dry.NODES
    assert "specs/074-corrected-staged-measurement/postrun/test_audit.py" in dry.TEST_MODULES
    assert "tests/test_master_planning_role_integration.py" in dry.TEST_MODULES
    assert any("tests/test_master_planning_role_integration.py" in nodes
               for nodes in dry.SCENARIOS.values())
    audit = adapter.load_current("audit")
    assert set(dry.TEST_MODULES) <= audit.code_paths(ROOT, ADAPTER.parent)
    assert all((ROOT / node.split("::")[0]).is_file() for node in dry.NODES)
    pins = {"tests/fixture.py": "a" * 64}
    dry.verify_test_pins({"frozen_files_sha256": pins}, pins)
    with pytest.raises(dry.DryRunError):
        dry.verify_test_pins({"frozen_files_sha256": {}}, pins)


@pytest.mark.parametrize("prior", ["074-corrected-staged-measurement", "076-public-plan-handoff-measurement"])
def test_new_audit_default_and_explicit_paths_reject_old_registration(audit, adapter, tmp_path, prior):
    assert audit.audit.__kwdefaults__["repo"] == adapter.REPO
    with pytest.raises(audit.AuditError, match="registration paths"):
        audit.audit(adapter.REPO / "specs" / prior / "measurement/manifest.json", adapter.CAMPAIGN)
    with pytest.raises(audit.AuditError, match="registration paths"):
        audit.audit(tmp_path / "specs/078-master-planning-role-measurement/measurement/manifest.json",
                    tmp_path / ".lunar/real-eval-glm-5.2-corrected-staged-20260910", repo=tmp_path)


def test_history_uses_sealed_076_chain_and_keeps_historical_samples_out(audit):
    assert audit.PRIOR_ROOT == "specs/076-public-plan-handoff-measurement"
    assert audit.SEALED_HISTORY[audit.PRIOR_ROOT + "/measurement/manifest.json"] == (
        "6690a02223aa3ea34bd5f88d9482d75d4a087857d69edd4245ac04479a321b76"
    )
    history = audit.historical_map(ROOT)
    assert len(history) == 30
    assert set(audit.SEALED_HISTORY) <= set(history)
    assert any(path.startswith("specs/074-corrected-staged-measurement/") for path in history)
    assert any(path.startswith("specs/072-master-budget-measurement/") for path in history)
    assert any(path.startswith("specs/069-webagent-normal-workflow/") for path in history)
    assert audit.OUTCOMES["historical_attempts_in_denominator"] == 0
    assert audit.OUTCOMES["retries_or_replacements"] == 0


def test_fixed_protocol_matches_076_with_only_the_registered_source_changed(adapter, audit):
    import json

    baseline = json.loads((ROOT / "specs/076-public-plan-handoff-measurement/measurement/manifest.json").read_text())
    assert adapter.IMPLEMENTATION == "fba6ab8cf5b27d3bd1b42f353907a6ae21c25ef9"
    assert adapter.IMPLEMENTATION != baseline["implementation_commit"]
    assert adapter.CAMPAIGN_ID == "real-eval-glm-5.2-master-role-20260910"
    assert adapter.EXECUTION == baseline["execution"]
    assert adapter.POLICIES == baseline["policies"]
    assert adapter.ORDER == [(slot["budget_arm"], slot["case_key"]) for slot in baseline["slots"]]
    assert audit.PROFILE_SHA == baseline["profile_sha256"]
    assert audit.CEILINGS == baseline["slots"][0]["workflow_config"]["manifest"]["ceilings"]
    assert audit.OUTCOMES == baseline["outcomes"]


@pytest.mark.parametrize("relative", [
    "measurement/adapter.py", "measurement/worker.py", "postrun/audit.py", "postrun/test_audit.py",
])
def test_new_wrapper_is_required_in_freeze_even_when_old_helper_exists(tmp_path, monkeypatch, audit, relative):
    here, campaign, manifest = freeze_fixture(tmp_path, monkeypatch, audit)
    path = here.parent / relative
    path.unlink()
    del manifest["frozen_files_sha256"][path.relative_to(tmp_path).as_posix()]
    with pytest.raises(audit.AuditError, match="missing required"):
        audit.check_frozen(tmp_path, campaign, manifest, here)
