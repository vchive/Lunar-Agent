"""Exercise the new bindings through pinned native two-slot execution/receipt fixtures."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "specs/082-http-deadline-measurement/measurement/adapter.py"
_spec = importlib.util.spec_from_file_location("offline082_runner_adapter", ADAPTER)
_adapter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_adapter)
_previous = _adapter.load_previous_test("runner", overrides={"ADAPTER": ADAPTER})
# Reuse test functions with their private fixture globals. Only the fixed old helper-count test
# is replaced below; every native worker/receipt/launch scenario now receives the 082 adapter.
globals().update({name: value for name, value in vars(_previous).items()
                  if name == "adapter" or name.startswith("test_")})


def test_prior_helper_closure_is_pinned_and_private(adapter, tmp_path, monkeypatch):
    assert len(adapter.HELPER_FILES) == 23
    assert adapter.PREVIOUS_ROOT == ROOT / "specs/074-corrected-staged-measurement"
    assert not any("076-public-plan-handoff-measurement" in path for path in adapter.HELPER_FILES)
    for relative, expected in adapter.HELPER_FILES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected
    assert adapter.load_prior_postrun().__file__.endswith("072-master-budget-measurement/postrun/audit.py")
    assert adapter.load_previous_postrun().__file__.endswith("074-corrected-staged-measurement/postrun/audit.py")
    root = tmp_path / "previous"
    (root / "measurement").mkdir(parents=True)
    (root / "measurement/worker.py").write_text("raise AssertionError('must not execute')")
    monkeypatch.setattr(adapter, "PREVIOUS_ROOT", root)
    with pytest.raises(ValueError, match="helper changed"):
        adapter.load_previous("worker")


def test_all_wrappers_bind_new_paths_implementation_and_prior_profile_source(adapter):
    audit, prepare = adapter.load_current("audit"), adapter.load_current("prepare")
    worker, campaign = adapter.load_worker(), adapter.load_campaign()
    assert audit.IMPLEMENTATION == audit.native.IMPLEMENTATION == adapter.IMPLEMENTATION
    assert audit.check_source.__globals__ is audit.native.__dict__
    assert audit.check_cases.__globals__["check_workflow"] is audit.check_workflow
    assert audit.check_workflow.__globals__["CAMPAIGN_ID"] == adapter.CAMPAIGN_ID
    assert prepare.PRIOR_ROOT == "specs/078-master-planning-role-measurement"
    assert prepare.CAMPAIGN == campaign.CAMPAIGN == adapter.CAMPAIGN
    assert prepare.HERE == campaign.HERE == ADAPTER.parent
    assert worker.native.verify_bindings is worker.verify_bindings
    assert worker.verify_bindings.__globals__ is worker.__dict__
    assert campaign.launch.__globals__ is campaign.__dict__
    assert campaign.native.HERE == ADAPTER.parent
    assert campaign.native.CAMPAIGN == adapter.CAMPAIGN
    assert all(Path(module.__file__).parent == ADAPTER.parent for module in (audit, prepare, worker, campaign))


@pytest.mark.parametrize("name", ["prepare", "worker", "campaign", "audit", "dry_run"])
def test_previous_helper_pins_reject_tampering_before_import(adapter, monkeypatch, name):
    monkeypatch.setitem(adapter.PREVIOUS_FILES, f"measurement/{name}.py", "0" * 64)
    with pytest.raises(ValueError, match="helper changed"):
        adapter.load_current(name)


_previous_scaffold = _previous.scaffold


def scaffold(tmp_path, adapter, monkeypatch):
    import json

    worker, campaign_module, campaign, manifest, _, profile, env = _previous_scaffold(tmp_path, adapter, monkeypatch)
    # Add the new frozen readiness identity to the inherited wholly synthetic filesystem.
    readiness = campaign / 'readiness.json'
    identity = {'fixture': 'never dispatched'}
    readiness.write_text(json.dumps({'subject_runtime': identity}))
    manifest['frozen_files_sha256'][readiness.relative_to(worker.REPO).as_posix()] = worker.file_sha256(readiness)
    (campaign / 'manifest.json').write_text(json.dumps(manifest))
    digest = worker.file_sha256(campaign / 'manifest.json')
    (campaign / 'manifest.sha256').write_text(digest + '\n')

    def verify(repo, expected):
        assert repo == worker.REPO and expected == identity
        return identity

    monkeypatch.setattr(worker.subject_runtime, 'verify', verify)
    return worker, campaign_module, campaign, manifest, digest, profile, env


_previous.scaffold = scaffold


def test_worker_rechecks_runtime_after_native_frozen_bindings_and_before_dispatch(adapter, monkeypatch):
    worker = adapter.load_worker()
    campaign = worker.REPO / '.lunar/fixture'
    seen = []
    identity = {'fixture': 'exact interpreter and helper'}
    monkeypatch.setattr(worker, '_native_verify_bindings', lambda *args, **kwargs: seen.append('native'))
    monkeypatch.setattr(worker, 'read_json', lambda path: {'subject_runtime': identity})
    monkeypatch.setattr(worker.subject_runtime, 'verify', lambda repo, expected: seen.append((repo, expected)))
    manifest = {'frozen_files_sha256': {'.lunar/fixture/readiness.json': 'a' * 64}}
    worker.native.verify_bindings(campaign / 'manifest.json', campaign, manifest, 'd' * 64, {}, require_started=False)
    assert seen == ['native', (worker.REPO, identity)]
    assert worker.verify_bindings.__globals__ is worker.__dict__

    def reject(*args):
        raise ValueError('subject runtime identity mismatch')

    monkeypatch.setattr(worker.subject_runtime, 'verify', reject)
    with pytest.raises(ValueError, match='subject runtime identity'):
        worker.native.verify_bindings(campaign / 'manifest.json', campaign, manifest, 'd' * 64, {})
