"""Two-slot protocol and dependency checks without provider configuration or real campaigns."""
import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "specs/074-corrected-staged-measurement/measurement/adapter.py"


@pytest.fixture
def adapter():
    spec = importlib.util.spec_from_file_location("offline074_adapter", ADAPTER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def audit(adapter):
    return adapter.load_current("audit")


def schedule(audit):
    request = {"benchmark": {"name": "famou-bench"}, "public_files": [], "run_index": 1}
    digest = hashlib.sha256(audit.canonical(request, newline=True)).hexdigest()
    manifest = {"schema_version": "1", "campaign_id": audit.CAMPAIGN_ID, "planned_attempts": 2,
                "policies": deepcopy(audit.POLICIES), "execution": deepcopy(audit.EXECUTION),
                "outcomes": deepcopy(audit.OUTCOMES), "source_sha256": "a" * 64,
                "profile_sha256": audit.PROFILE_SHA, "slots": []}
    for index, (group, key) in enumerate(audit.ORDER, 1):
        workflow = {"manifest": {
            "run_id": f"{audit.CAMPAIGN_ID}-slot-{index:03d}", "attempt_id": f"slot-{index:03d}-attempt-001",
            "source_sha256": manifest["source_sha256"], "suite_key": "famou-bench", "case_key": key,
            "request_sha256": digest, "model_profile_sha256": audit.PROFILE_SHA, "ceilings": dict(audit.CEILINGS),
        }, "policy": dict(audit.POLICIES[group])}
        manifest["slots"].append({"index": index, "arm": "S", "budget_arm": group, "case_key": key,
                                  "request_sha256": digest, "workflow_config": workflow})
    return manifest, request


def test_prior_audit_is_privately_bound_without_changing_four_slot_module(adapter, audit):
    untouched = adapter.load_prior("audit")
    assert untouched.CAMPAIGN_ID != audit.CAMPAIGN_ID
    assert len(untouched.ORDER) == 4 and len(audit.ORDER) == 2
    assert untouched.IMPLEMENTATION == "5c89e049c184c52090f665131e3290ea3359bc04"
    assert audit.native.IMPLEMENTATION == "c28e498e539b3ed6e37d743145ba1c38f9b1e9e2"
    assert audit.check_source.__globals__ is audit.native.__dict__
    assert audit.check_cases.__globals__["check_workflow"] is audit.check_workflow
    assert audit.native.check_schedule is not audit.check_schedule
    manifest, request = schedule(audit)
    audit.check_schedule(manifest)
    for slot in manifest["slots"]:
        audit.check_workflow(manifest, slot, request)
    with pytest.raises(untouched.AuditError):
        untouched.check_schedule(manifest)


@pytest.mark.parametrize("change", [
    "extra_slot", "missing_slot", "reordered", "normal", "group300", "master_budget",
    "extra_wave", "planned4", "denominator4", "unknown_zero", "duration", "replacement",
])
def test_two_slot_schedule_rejects_protocol_changes(audit, change):
    manifest, _request = schedule(audit)
    if change == "extra_slot":
        manifest["slots"].append({**manifest["slots"][1], "index": 3})
    elif change == "missing_slot":
        manifest["slots"].pop()
    elif change == "reordered":
        manifest["slots"].reverse()
    elif change == "normal":
        manifest["slots"][0]["arm"] = "M"
    elif change == "group300":
        manifest["slots"][0]["budget_arm"] = "master_300"
    elif change == "master_budget":
        manifest["policies"]["master_1200"]["master_seconds"] = 1800
    elif change == "extra_wave":
        manifest["execution"]["waves"].append([1, 2])
    elif change == "planned4":
        manifest["planned_attempts"] = 4
    else:
        field, value = {
            "denominator4": ("fixed_denominator_per_budget_arm", 4),
            "unknown_zero": ("unscored_failure", 0), "duration": ("master_duration_seconds", 1200),
            "replacement": ("retries_or_replacements", 1),
        }[change]
        manifest["outcomes"][field] = value
    with pytest.raises(audit.AuditError):
        audit.check_schedule(manifest)


@pytest.mark.parametrize("field,value", [
    ("run_id", "old-campaign-slot-002"), ("attempt_id", "slot-001-attempt-001"),
    ("request_sha256", "b" * 64), ("model_profile_sha256", "b" * 64),
    ("source_sha256", "b" * 64), ("case_key", "sheet_metal_nesting"),
])
def test_workflow_rejects_cross_attempt_or_source_identity(audit, field, value):
    manifest, request = schedule(audit)
    slot = manifest["slots"][1]
    slot["workflow_config"]["manifest"][field] = value
    with pytest.raises(audit.AuditError, match="shared budget"):
        audit.check_workflow(manifest, slot, request)


def test_preparation_workflows_match_actual_native_request_bytes(adapter, audit):
    prepare = adapter.load_current("prepare")
    manifest, request = schedule(audit)
    suite = SimpleNamespace(benchmark=SimpleNamespace(name="famou-bench"))
    for slot in manifest["slots"]:
        assert prepare.workflow_for(slot["index"], slot["case_key"], suite, manifest["profile_sha256"],
                                    manifest["source_sha256"], slot["request_sha256"]) == slot["workflow_config"]
    with pytest.raises(audit.AuditError, match="request digest"):
        audit.check_workflow(manifest, manifest["slots"][0], {**request, "run_index": 2})
    manifest["slots"][0]["workflow_config"]["manifest"]["ceilings"]["max_tool_steps"] = 201
    with pytest.raises(audit.AuditError, match="shared budget"):
        audit.check_workflow(manifest, manifest["slots"][0], request)


def test_reused_source_validator_checks_current_git_bytes_and_complete_set(tmp_path, monkeypatch, audit):
    relative = "src/famou/fixture.py"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    original = b"VALUE = 1\n"
    path.write_bytes(original)
    manifest = {"implementation_commit": audit.IMPLEMENTATION,
                "source_files_sha256": {relative: audit.sha(path)}}
    manifest["source_sha256"] = audit.object_sha(manifest["source_files_sha256"])

    def git(command, **kwargs):
        assert audit.IMPLEMENTATION in " ".join(command)
        return relative + "\n" if command[1] == "ls-tree" else original

    monkeypatch.setattr(audit.native.subprocess, "check_output", git)
    audit.check_source(tmp_path, manifest)
    path.write_bytes(b"VALUE = 2\n")
    manifest["source_files_sha256"][relative] = audit.sha(path)
    manifest["source_sha256"] = audit.object_sha(manifest["source_files_sha256"])
    with pytest.raises(audit.AuditError, match="pinned commit"):
        audit.check_source(tmp_path, manifest)
    path.write_bytes(original)
    path.with_name("extra.py").write_text("unexpected")
    manifest["source_files_sha256"][relative] = audit.sha(path)
    with pytest.raises(audit.AuditError, match="file set"):
        audit.check_source(tmp_path, manifest)


def freeze_fixture(tmp_path, monkeypatch, audit):
    here = tmp_path / "specs/074-corrected-staged-measurement/measurement"
    campaign = tmp_path / ".lunar" / audit.CAMPAIGN_ID
    paths = {*(here.parent / name for name in audit.REQUIRED_CODE),
             *(tmp_path / relative for relative in audit.EXPECTED_HELPERS),
             tmp_path / "tests/test_measurement074_audit.py", tmp_path / "tests/test_measurement074_runner.py",
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


@pytest.mark.parametrize("change", ["missing_helper_pin", "missing_script", "new_unpinned_test", "rehashed_helper"])
def test_freeze_requires_actual_helper_closure_reporters_and_tests(tmp_path, monkeypatch, audit, change):
    here, campaign, manifest = freeze_fixture(tmp_path, monkeypatch, audit)
    if change == "missing_helper_pin":
        del manifest["frozen_files_sha256"][next(iter(audit.HELPER_FILES))]
    elif change == "missing_script":
        path = here.parent / "postrun/render_report.py"
        path.unlink()
        del manifest["frozen_files_sha256"][path.relative_to(tmp_path).as_posix()]
    elif change == "new_unpinned_test":
        (tmp_path / "tests/extra.py").write_text("unregistered")
    else:
        relative = next(iter(audit.HELPER_FILES))
        path = tmp_path / relative
        path.write_bytes(b"changed\n")
        manifest["frozen_files_sha256"][relative] = audit.sha(path)
        audit.HELPER_FILES[relative] = audit.sha(path)
    with pytest.raises(audit.AuditError):
        audit.check_frozen(tmp_path, campaign, manifest, here)


def test_fixed_dependency_closure_rejects_missing_loader_entry(tmp_path, monkeypatch, audit):
    here, _campaign, _manifest = freeze_fixture(tmp_path, monkeypatch, audit)
    audit.HELPER_FILES.pop(next(iter(audit.HELPER_FILES)))
    with pytest.raises(audit.AuditError, match="helper closure"):
        audit.code_paths(tmp_path, here)


def test_sealed_history_is_exact_context_and_requires_final_acceptance(tmp_path, monkeypatch, audit):
    root = tmp_path / audit.PRIOR_ROOT
    (root / "measurement").mkdir(parents=True)
    (root / "postrun").mkdir()
    prior = tmp_path / "context.json"
    prior.write_text("historical context only")
    registration = root / "measurement/manifest.json"
    registration.write_text(json.dumps({"historical_files_sha256": {"context.json": audit.sha(prior)}}))
    final = root / "postrun/final-audit.json"
    payload = {"passed": True, "complete": True, "final_acceptance": True,
               "manifest_sha256": audit.sha(registration)}
    final.write_text(json.dumps(payload))
    pins = {path.relative_to(tmp_path).as_posix(): audit.sha(path) for path in (registration, final)}
    monkeypatch.setattr(audit, "SEALED_HISTORY", pins)
    history = audit.historical_map(tmp_path)
    audit.check_history(tmp_path, {"historical_files_sha256": history})
    with pytest.raises(audit.AuditError, match="historical context"):
        audit.check_history(tmp_path, {"historical_files_sha256": {**history, "extra.json": "a" * 64}})
    payload["complete"] = False
    final.write_text(json.dumps(payload))
    pins[final.relative_to(tmp_path).as_posix()] = audit.sha(final)
    with pytest.raises(audit.AuditError, match="final seal"):
        audit.historical_map(tmp_path)


@pytest.mark.parametrize("marker", ["slots", "summary.json", "started.json", "terminated.json",
                                   "slot-001-started.json", "slot-002-terminated.json", "slot-003-started.json"])
def test_unstarted_gate_rejects_residual_or_extra_slot_evidence(tmp_path, audit, marker):
    audit.check_unstarted(tmp_path)
    (tmp_path / marker).write_text("{}")
    with pytest.raises(audit.AuditError, match="unstarted"):
        audit.check_unstarted(tmp_path)


@pytest.mark.parametrize("kind", ["missing", "duplicate", "skipped", "failure", "error"])
def test_reused_offline_report_requires_complete_passing_selected_tests(tmp_path, monkeypatch, adapter, kind):
    dry = adapter.load_current("dry_run")
    monkeypatch.setattr(dry.native, "NODES", ("tests/example.py::test_one",))
    case = '<testcase classname="example" name="test_one">'
    case += f"<{kind}/>" if kind in {"skipped", "failure", "error"} else ""
    case += "</testcase>"
    case = "" if kind == "missing" else case * 2 if kind == "duplicate" else case
    report = tmp_path / "results.xml"
    report.write_text("<testsuite>" + case + "</testsuite>")
    with pytest.raises(dry.DryRunError):
        dry.parse_results(report)


def test_dry_run_uses_new_scenarios_and_freezes_all_test_bytes(adapter):
    dry = adapter.load_current("dry_run")
    assert dry.native.NODES == dry.NODES and dry.native.SCENARIOS == dry.SCENARIOS
    assert "tests/test_measurement074_runner.py" in dry.NODES
    assert "tests/test_master_plan_envelope_integration.py" in dry.NODES
    assert "specs/074-corrected-staged-measurement/postrun/test_audit.py" in dry.NODES
    pins = {"tests/fixture.py": "a" * 64}
    dry.verify_test_pins({"frozen_files_sha256": pins}, pins)
    with pytest.raises(dry.DryRunError):
        dry.verify_test_pins({"frozen_files_sha256": {}}, pins)


@pytest.mark.parametrize("changed", [None, "packages", "python_version"])
def test_runtime_rechecks_installed_identity_with_a_bounded_credential_free_probe(
    tmp_path, monkeypatch, audit, changed,
):
    launcher = tmp_path / ".lunar/harness-venv-high-score-20260909/bin/python"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("inert launcher fixture")
    campaign = tmp_path / ".lunar" / audit.CAMPAIGN_ID
    campaign.mkdir()
    historical = tmp_path / ".lunar/real-eval-glm-5.2-high-score-20260909"
    historical.mkdir()
    readiness = {"python_version": "3.13.1", "packages": {"fixture-package": "1.0"},
                 "harness_python_sha256": audit.sha(launcher)}
    for directory in (campaign, historical):
        (directory / "readiness.json").write_text(json.dumps(readiness))
    actual = {key: deepcopy(readiness[key]) for key in ("python_version", "packages")}
    if changed:
        actual[changed] = {"fixture-package": "2.0"} if changed == "packages" else "3.13.2"
    calls = []

    def probe(command, **kwargs):
        calls.append(command)
        assert command[:2] == [str(launcher), "-c"] and len(command) == 3
        assert kwargs["env"] == {"PATH": audit.os.defpath, "PYTHONDONTWRITEBYTECODE": "1"}
        assert kwargs["timeout"] == 30 and kwargs["text"] is True
        return json.dumps(actual)

    monkeypatch.setattr(audit.subprocess, "check_output", probe)
    old = {"harness_python_sha256": audit.sha(launcher)}
    if changed:
        with pytest.raises(audit.AuditError, match="installed harness"):
            audit.check_runtime(tmp_path, campaign, old)
    else:
        audit.check_runtime(tmp_path, campaign, old)
    assert len(calls) == 1
