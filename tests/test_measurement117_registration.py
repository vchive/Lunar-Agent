"""Extended deadlines are the only measurement-condition changes from frozen 115."""
from __future__ import annotations

import importlib.util
import json
import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from famou.config import Config

HERE = Path(__file__).resolve().parents[1] / "specs/117-extended-deadline-acceptance/measurement"


@pytest.fixture
def registered_module(monkeypatch):
    monkeypatch.syspath_prepend(str(HERE))
    spec = importlib.util.spec_from_file_location("measurement117_registration", HERE / "campaign.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def reference(module):
    return json.loads((module.REFERENCE / "manifest.json").read_text())


def new_payload(module):
    old = reference(module)
    return {
        **deepcopy(old), "product_commit": module.PRODUCT_COMMIT,
        "campaign_id": module.CAMPAIGN_ID, "campaign_root": ".lunar/" + module.CAMPAIGN_ID,
        "previous_campaign": old["campaign_id"], "limits": deepcopy(module.LIMITS),
        "condition_changes": module.condition_changes(old),
    }


def test_new_registration_keeps_fixed_tasks_and_changes_exactly_two_deadlines(registered_module):
    module = registered_module
    old, payload = reference(module), new_payload(module)
    assert module.PRODUCT_COMMIT == "9a26a73e38d52b18f003b262a8746bb22496c156"
    assert module.CAMPAIGN_ID != old["campaign_id"]
    assert module.REFERENCE.name == "measurement"
    assert module.REFERENCE.parent.name == "115-isolated-intake-acceptance"
    assert module.sha(module.REFERENCE / "manifest.json") == module.REFERENCE_SHA256
    assert payload["limits"] == {**old["limits"], "wall_seconds": 3600, "request_seconds": 600}
    assert payload["limits"] == {
        "wall_seconds": 3600, "request_seconds": 600, "max_requests": 16,
        "token_stop_threshold": 160000, "tool_steps_per_invocation": 4,
    }
    assert module.condition_changes(old) == {
        "product_commit": {"before": old["product_commit"], "after": module.PRODUCT_COMMIT},
        "wall_seconds": {"before": 1200, "after": 3600},
        "request_seconds": {"before": 180, "after": 600},
    }
    assert module.CASES == old["cases"]
    assert {key: module.holdouts(key) for key in module.CASES} == old["holdouts"]
    assert payload["planned_attempts"] == len(payload["schedule"]) == 2
    assert payload["retries_or_replacements"] == 0
    module.check_fixed_conditions(payload)


@pytest.mark.parametrize("field", [
    "provider", "cases", "holdouts", "optima", "population", "runtime_options", "sampling",
    "schedule", "planned_attempts", "concurrency", "retries_or_replacements", "primary",
    "failure_quality", "cost_micros",
])
def test_changed_fixed_condition_is_rejected(registered_module, field):
    payload = new_payload(registered_module)
    payload[field] = {"changed": True}
    with pytest.raises(ValueError, match="fixed_conditions_changed"):
        registered_module.check_fixed_conditions(payload)


@pytest.mark.parametrize("field", [
    "wall_seconds", "request_seconds", "max_requests", "token_stop_threshold",
    "tool_steps_per_invocation", "extra_allowance",
])
def test_arbitrary_limit_change_is_rejected(registered_module, field):
    payload = new_payload(registered_module)
    payload["limits"][field] = payload["limits"].get(field, 0) + 1
    with pytest.raises(ValueError, match="fixed_conditions_changed"):
        registered_module.check_fixed_conditions(payload)


def test_old_deadlines_and_changed_launcher_limits_are_rejected(registered_module, monkeypatch):
    payload = new_payload(registered_module)
    payload["limits"] = reference(registered_module)["limits"]
    with pytest.raises(ValueError, match="fixed_conditions_changed"):
        registered_module.check_fixed_conditions(payload)
    payload = new_payload(registered_module)
    monkeypatch.setattr(registered_module, "LIMITS", {**payload["limits"], "request_seconds": 601})
    with pytest.raises(ValueError, match="fixed_conditions_changed"):
        registered_module.check_fixed_conditions(payload)


@pytest.mark.parametrize("field", ["product_commit", "campaign_id", "campaign_root", "previous_campaign"])
def test_wrong_identity_or_old_campaign_root_is_rejected(registered_module, field):
    payload = new_payload(registered_module)
    payload[field] = reference(registered_module).get(field, "unregistered")
    with pytest.raises(ValueError, match="campaign_identity_changed"):
        registered_module.check_fixed_conditions(payload)


@pytest.mark.parametrize("change", ["missing", "deadline", "extra"])
def test_condition_change_declaration_must_match_reference(registered_module, change):
    payload = new_payload(registered_module)
    if change == "missing":
        del payload["condition_changes"]
    elif change == "deadline":
        payload["condition_changes"]["request_seconds"]["before"] = 600
    else:
        payload["condition_changes"]["population"] = {"before": 2, "after": 3}
    with pytest.raises(ValueError, match="condition_changes_invalid"):
        registered_module.check_fixed_conditions(payload)


def test_historical_registration_byte_drift_is_rejected(registered_module, monkeypatch, tmp_path):
    payload = new_payload(registered_module)
    (tmp_path / "manifest.json").write_text(json.dumps(reference(registered_module)) + " ")
    monkeypatch.setattr(registered_module, "REFERENCE", tmp_path)
    with pytest.raises(ValueError, match="historical_registration_changed"):
        registered_module.check_fixed_conditions(payload)


@pytest.mark.parametrize("helper", ["runtime_guard", "analyze", "tasks"])
def test_shadowed_shared_helper_is_rejected(registered_module, monkeypatch, tmp_path, helper):
    monkeypatch.setattr(registered_module.importlib, "import_module",
                        lambda _: SimpleNamespace(__file__=str(tmp_path / (helper + ".py"))))
    with pytest.raises(ValueError, match="shared_module_mismatch"):
        registered_module.shared_module(helper)


@pytest.mark.parametrize("filename", ["worker.py", "response_guard.py"])
def test_worker_and_passive_response_wrapper_keep_frozen_115_bytes(registered_module, filename):
    assert (HERE / filename).read_bytes() == (registered_module.REFERENCE / filename).read_bytes()


def test_clean_environment_sets_600_second_config_and_discards_ambient_settings(
    registered_module, monkeypatch, tmp_path,
):
    for name, value in {
        "OPENAI_API_KEY": "offline-secret", "FAMOU_API_KEY": "offline-secret",
        "FAMOU_RUNTIME_TIMEOUT": "1", "FAMOU_MAX_RETRIES": "99",
        "FAMOU_HOME": "/ambient/private", "FAMOU_MODEL": "other-model",
        "FAMOU_ENDPOINT": "https://ambient.invalid", "PYTHONPATH": "/ambient/code",
        "HTTPS_PROXY": "https://ambient-proxy.invalid", "UNRELATED_SECRET": "offline-secret",
    }.items():
        monkeypatch.setenv(name, value)
    clean = registered_module.clean_environment()
    assert set(clean) == {
        "PATH", "HOME", "LANG", "LC_ALL", "PYTHONHASHSEED", "PYTHONIOENCODING",
        "FAMOU_MAX_RETRIES", "FAMOU_RUNTIME_TIMEOUT",
    }
    assert clean["FAMOU_RUNTIME_TIMEOUT"] == "600"
    assert clean["FAMOU_MAX_RETRIES"] == "1"
    assert "offline-secret" not in json.dumps(clean)
    for name in list(os.environ):
        monkeypatch.delenv(name)
    for name, value in clean.items():
        monkeypatch.setenv(name, value)
    config = Config.from_env(tmp_path / "isolated-home")
    assert config.runtime_timeout == 600
    assert config.max_retries == 1
    assert config.home == tmp_path / "isolated-home"
