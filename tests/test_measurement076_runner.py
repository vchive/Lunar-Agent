"""Exercise the new bindings through pinned native two-slot execution/receipt fixtures."""
import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "specs/076-public-plan-handoff-measurement/measurement/adapter.py"
_spec = importlib.util.spec_from_file_location("offline076_runner_adapter", ADAPTER)
_adapter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_adapter)
_previous = _adapter.load_previous_test("runner", overrides={"ADAPTER": ADAPTER})
# Reuse test functions with their private fixture globals. Only the fixed old helper-count test
# is replaced below; every native worker/receipt/launch scenario now receives the 076 adapter.
globals().update({name: value for name, value in vars(_previous).items()
                  if name == "adapter" or name.startswith("test_")})


def test_prior_helper_closure_is_pinned_and_private(adapter, tmp_path, monkeypatch):
    assert len(adapter.HELPER_FILES) == 23
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
    assert prepare.PRIOR_ROOT == "specs/074-corrected-staged-measurement"
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
