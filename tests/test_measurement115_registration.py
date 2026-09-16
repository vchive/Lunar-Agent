"""New registration preserves fixed conditions and refuses shadowed shared helpers."""
from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parents[1] / "specs/115-isolated-intake-acceptance/measurement"


@pytest.fixture
def registered_module(monkeypatch):
    monkeypatch.syspath_prepend(str(HERE))
    spec = importlib.util.spec_from_file_location("measurement115_fixed_conditions", HERE / "campaign.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reference(module):
    return json.loads((module.SHARED / "manifest.json").read_text())


def test_new_source_identity_keeps_same_tasks_limits_and_reference(registered_module):
    module = registered_module
    old = reference(module)
    assert module.PRODUCT_COMMIT == "5e2568f286b709c7f8bd4c883bf654582908e736"
    assert module.CAMPAIGN_ID != old["campaign_id"]
    assert module.LIMITS == old["limits"]
    assert module.CASES == old["cases"]
    assert {key: module.holdouts(key) for key in module.CASES} == old["holdouts"]
    revised = {**old, "product_commit": module.PRODUCT_COMMIT, "campaign_id": module.CAMPAIGN_ID}
    module.check_fixed_conditions(revised)


@pytest.mark.parametrize("field", ["provider", "limits", "cases", "holdouts", "optima",
                                  "population", "runtime_options", "sampling", "schedule",
                                  "planned_attempts", "concurrency", "retries_or_replacements",
                                  "primary", "failure_quality", "cost_micros"])
def test_changed_fixed_condition_rejected_before_registration(registered_module, field):
    payload = deepcopy(reference(registered_module))
    payload[field] = {"changed": True}
    with pytest.raises(ValueError, match="fixed_conditions_changed"):
        registered_module.check_fixed_conditions(payload)


def test_historical_registration_drift_rejected(registered_module, monkeypatch, tmp_path):
    old = reference(registered_module)
    (tmp_path / "manifest.json").write_text(json.dumps(old) + " ")
    monkeypatch.setattr(registered_module, "SHARED", tmp_path)
    with pytest.raises(ValueError, match="historical_registration_changed"):
        registered_module.check_fixed_conditions(old)


def test_shadowed_helper_rejected(registered_module, monkeypatch, tmp_path):
    monkeypatch.setattr(registered_module.importlib, "import_module",
                        lambda _: SimpleNamespace(__file__=str(tmp_path / "runtime_guard.py")))
    with pytest.raises(ValueError, match="shared_module_mismatch"):
        registered_module.shared_module("runtime_guard")
