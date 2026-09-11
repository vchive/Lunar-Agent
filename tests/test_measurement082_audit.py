"""Rebind the sealed audit fixtures and independently check 082 paths and helper closure."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "specs/082-http-deadline-measurement/measurement/adapter.py"
_spec = importlib.util.spec_from_file_location("offline082_audit_adapter", ADAPTER)
_adapter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_adapter)
_previous = _adapter.load_previous_test("audit", overrides={"ADAPTER": ADAPTER})
globals().update({name: value for name, value in vars(_previous).items()
                  if name in {"adapter", "audit"} or name.startswith("test_")})


def test_prior_audit_is_privately_bound_without_changing_four_slot_module(adapter, audit):
    untouched = adapter.load_prior("audit")
    assert len(untouched.ORDER) == 4 and len(audit.ORDER) == 2
    assert untouched.CAMPAIGN_ID != audit.CAMPAIGN_ID
    assert audit.native.IMPLEMENTATION == "e36b103fd6fc4a64304d16ae446e0383dab0a8a8"
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
    here = tmp_path / "specs/082-http-deadline-measurement/measurement"
    campaign = tmp_path / ".lunar" / audit.CAMPAIGN_ID
    paths = {*(here.parent / name for name in audit.REQUIRED_CODE),
             *(tmp_path / relative for relative in audit.EXPECTED_HELPERS),
             tmp_path / "tests/test_measurement082_audit.py", tmp_path / "tests/test_measurement082_runner.py",
             tmp_path / "tests/test_measurement082_runtime.py",
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
    assert {"tests/test_measurement082_runner.py", "tests/test_measurement082_audit.py",
            "tests/test_master_plan_envelope_integration.py", "tests/test_master_plan_vocabulary.py",
            "tests/test_master_planning_role_integration.py",
            "specs/082-http-deadline-measurement/postrun/test_audit.py"} <= set(dry.NODES)
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
        audit.audit(tmp_path / "specs/082-http-deadline-measurement/measurement/manifest.json",
                    tmp_path / ".lunar/real-eval-glm-5.2-corrected-staged-20260910", repo=tmp_path)


def test_history_uses_sealed_078_chain_and_keeps_historical_samples_out(audit):
    assert audit.PRIOR_ROOT == "specs/078-master-planning-role-measurement"
    assert audit.SEALED_HISTORY[audit.PRIOR_ROOT + "/measurement/manifest.json"] == (
        "605cfd030b3b65e9bc1995157f44acdbbbbe7e55837b6f4a27b7042afb996804"
    )
    history = audit.historical_map(ROOT)
    assert len(history) == 36
    assert set(audit.SEALED_HISTORY) <= set(history)
    assert any(path.startswith("specs/074-corrected-staged-measurement/") for path in history)
    assert any(path.startswith("specs/072-master-budget-measurement/") for path in history)
    assert any(path.startswith("specs/069-webagent-normal-workflow/") for path in history)
    assert audit.OUTCOMES["historical_attempts_in_denominator"] == 0
    assert audit.OUTCOMES["retries_or_replacements"] == 0


def test_fixed_protocol_matches_078_with_only_the_registered_source_changed(adapter, audit):
    import json

    baseline = json.loads((ROOT / "specs/078-master-planning-role-measurement/measurement/manifest.json").read_text())
    assert adapter.IMPLEMENTATION == "e36b103fd6fc4a64304d16ae446e0383dab0a8a8"
    assert adapter.IMPLEMENTATION != baseline["implementation_commit"]
    assert adapter.CAMPAIGN_ID == "real-eval-glm-5.2-http-deadline-20260911"
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


def test_deadline_helper_is_required_in_complete_source_identity(audit, tmp_path, monkeypatch):
    # Reconstruct only the pinned Git source in an isolated fixture. Product development must
    # not run a sealed campaign's live-source audit against today's checkout.
    listing_command = ['git', 'ls-tree', '-r', '--name-only', _adapter.IMPLEMENTATION,
                       '--', 'src/famou']
    listing = audit.subprocess.check_output(listing_command, cwd=ROOT, text=True)
    pinned = {
        relative: audit.subprocess.check_output(
            ['git', 'show', f'{_adapter.IMPLEMENTATION}:{relative}'], cwd=ROOT,
        )
        for relative in listing.splitlines() if relative.endswith('.py')
    }
    for relative, content in pinned.items():
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)

    def fixture_git(command, **kwargs):
        assert kwargs['cwd'] == tmp_path
        if command == listing_command:
            return listing
        assert command[:2] == ['git', 'show'] and len(command) == 3
        commit, relative = command[2].split(':', 1)
        assert commit == _adapter.IMPLEMENTATION
        return pinned[relative]

    monkeypatch.setattr(audit.subprocess, 'check_output', fixture_git)
    source = {relative: audit.sha(tmp_path / relative) for relative in pinned}
    assert len(source) == 38 and 'src/famou/http_transport.py' in source
    manifest = {'implementation_commit': _adapter.IMPLEMENTATION,
                'source_files_sha256': source, 'source_sha256': audit.object_sha(source)}
    audit.check_source(tmp_path, manifest)
    del source['src/famou/http_transport.py']
    manifest['source_sha256'] = audit.object_sha(source)
    with pytest.raises(audit.AuditError):
        audit.check_source(tmp_path, manifest)


def test_subject_runtime_identity_is_frozen_and_checked_before_launch(adapter, audit, tmp_path, monkeypatch):
    from types import SimpleNamespace

    identity = {'fixture': 'owned subject executable and helper'}
    observed = []
    monkeypatch.setattr(audit, '_harness_check_runtime', lambda *args: observed.append('harness'))
    monkeypatch.setattr(audit, 'read', lambda path: {'subject_runtime': identity})
    monkeypatch.setattr(audit, 'subject_runtime', SimpleNamespace(
        verify=lambda repo, expected: observed.append((repo, expected))))
    audit.check_runtime(tmp_path, tmp_path / 'campaign', {})
    assert observed == ['harness', (tmp_path, identity)]
    assert 'measurement/runtime_identity.py' in audit.REQUIRED_CODE
    assert 'tests/test_measurement082_runtime.py' in audit.code_paths(ROOT, ADAPTER.parent)
    prepare = adapter.load_current('prepare')
    saved = []
    monkeypatch.setattr(prepare, '_write_new', lambda path, value: saved.append((path, value)))
    monkeypatch.setattr(prepare, 'subject_runtime', SimpleNamespace(capture=lambda repo: identity))
    prepare.write_new(prepare.CAMPAIGN / 'readiness.json', {'model_calls': 0})
    prepare.write_new(prepare.CAMPAIGN / 'inputs/profile.json', {'model': 'fixture'})
    assert saved[0][1] == {'model_calls': 0, 'subject_runtime': identity}
    assert saved[1][1] == {'model': 'fixture'}


def test_guarded_deadline_nodes_do_not_include_real_network_modules(adapter):
    dry = adapter.load_current('dry_run')
    assert 'tests/test_http_transport_deadline.py' not in dry.NODES
    assert 'tests/test_http_transport_tls.py' not in dry.NODES
    assert 'tests/test_model_failure_evidence.py' not in dry.NODES
    assert 'tests/test_model_request_timing.py' not in dry.NODES
    assert 'tests/test_http_transport_deadline.py::test_request_pipe_blockage_obeys_same_deadline' in dry.NODES
    assert 'tests/test_model_request_timing.py::test_observation_is_frozen_and_manual_failure_remains_v3' in dry.NODES


@pytest.mark.parametrize('changed', [None, 'packages', 'python_version'])
def test_runtime_rechecks_installed_identity_with_a_bounded_credential_free_probe(tmp_path, monkeypatch, audit, changed):
    # Preserve the inherited harness-specific fixture; the subject gate is exercised separately.
    monkeypatch.setattr(audit, 'check_runtime', audit._harness_check_runtime)
    _previous.test_runtime_rechecks_installed_identity_with_a_bounded_credential_free_probe(
        tmp_path, monkeypatch, audit, changed)
