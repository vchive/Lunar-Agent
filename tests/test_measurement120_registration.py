"""Supported source acceptance registers scope changes without rewriting history."""
from __future__ import annotations

import importlib.util
import json
import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from famou.config import Config

HERE = Path(__file__).resolve().parents[1] / "specs/120-supported-scope-acceptance/measurement"


@pytest.fixture
def registered_module(monkeypatch):
    monkeypatch.syspath_prepend(str(HERE))
    spec = importlib.util.spec_from_file_location("measurement120_registration", HERE / "campaign.py")
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
        "cases": deepcopy(module.CASES), "primary": module.PRIMARY,
        "condition_changes": module.condition_changes(old),
    }


def test_new_registration_changes_product_and_goal_scope_but_keeps_mathematical_cases(
    registered_module,
):
    module = registered_module
    old, payload = reference(module), new_payload(module)
    assert module.PRODUCT_COMMIT == "c5695088c83bf69188bd7ae222056c8b63233656"
    assert module.CAMPAIGN_ID != old["campaign_id"]
    assert module.REFERENCE.parent.name == "117-extended-deadline-acceptance"
    assert module.sha(module.REFERENCE / "manifest.json") == module.REFERENCE_SHA256
    assert payload["limits"] == old["limits"] == {
        "wall_seconds": 3600, "request_seconds": 600, "max_requests": 16,
        "token_stop_threshold": 160000, "tool_steps_per_invocation": 4,
    }
    assert module.condition_changes(old) == {
        "product_commit": {"before": old["product_commit"], "after": module.PRODUCT_COMMIT},
        "task_goals": {
            "before": {key: case["goal"] for key, case in old["cases"].items()},
            "after": {key: case["goal"] for key, case in module.CASES.items()},
        },
        "primary": {"before": old["primary"], "after": module.PRIMARY},
    }
    assert set(module.CASES) == set(old["cases"])
    for key, case in module.CASES.items():
        assert {field: value for field, value in case.items() if field != "goal"} == {
            field: value for field, value in old["cases"][key].items() if field != "goal"
        }
        assert case["goal"] != old["cases"][key]["goal"]
        assert "python_file_count" in case["goal"]
        assert "source_check" in case["goal"]
        assert "verification_scope" in case["goal"]
    assert {key: module.holdouts(key) for key in module.CASES} == old["holdouts"]
    assert {key: module.optimum(key, case["inputs"]) for key, case in module.CASES.items()} == old["optima"]
    assert payload["planned_attempts"] == len(payload["schedule"]) == 2
    assert payload["retries_or_replacements"] == 0
    assert module.PRIMARY != old["primary"]
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


@pytest.mark.parametrize("change", ["old_goal", "new_goal", "input", "added_case", "removed_case"])
def test_task_scope_and_input_drift_are_rejected(registered_module, change):
    payload = new_payload(registered_module)
    key = next(iter(payload["cases"]))
    if change == "old_goal":
        payload["cases"][key]["goal"] = reference(registered_module)["cases"][key]["goal"]
    elif change == "new_goal":
        payload["cases"][key]["goal"] += " Require an imported helper module."
    elif change == "input":
        name = next(iter(payload["cases"][key]["inputs"]))
        payload["cases"][key]["inputs"][name] = {"changed": True}
    elif change == "added_case":
        payload["cases"]["replacement"] = deepcopy(payload["cases"][key])
    else:
        del payload["cases"][key]
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


def test_changed_launcher_limits_are_rejected(registered_module, monkeypatch):
    payload = new_payload(registered_module)
    monkeypatch.setattr(registered_module, "LIMITS", {**payload["limits"], "request_seconds": 601})
    with pytest.raises(ValueError, match="fixed_conditions_changed"):
        registered_module.check_fixed_conditions(payload)


@pytest.mark.parametrize("change", ["input", "added_case", "removed_case"])
def test_rewriting_task_module_cannot_silently_change_registered_mathematical_problem(
    registered_module, monkeypatch, change,
):
    cases = deepcopy(registered_module.CASES)
    key = next(iter(cases))
    if change == "input":
        cases[key]["inputs"] = {"substituted.json": {}}
    elif change == "added_case":
        cases["replacement"] = deepcopy(cases[key])
    else:
        del cases[key]
    monkeypatch.setattr(registered_module, "CASES", cases)
    payload = new_payload(registered_module)
    with pytest.raises(ValueError, match="fixed_conditions_changed"):
        registered_module.check_fixed_conditions(payload)


@pytest.mark.parametrize("field", ["product_commit", "campaign_id", "campaign_root", "previous_campaign"])
def test_wrong_identity_or_old_campaign_root_is_rejected(registered_module, field):
    payload = new_payload(registered_module)
    payload[field] = reference(registered_module).get(field, "unregistered")
    with pytest.raises(ValueError, match="campaign_identity_changed"):
        registered_module.check_fixed_conditions(payload)


@pytest.mark.parametrize("change", ["missing", "goals_before", "goals_after", "primary", "extra"])
def test_condition_change_declaration_must_match_reference(registered_module, change):
    payload = new_payload(registered_module)
    if change == "missing":
        del payload["condition_changes"]
    elif change.startswith("goals_"):
        payload["condition_changes"]["task_goals"][change.removeprefix("goals_")] = {}
    elif change == "primary":
        payload["condition_changes"]["primary"]["before"] = "unregistered measure"
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
def test_worker_and_passive_response_wrapper_keep_frozen_117_bytes(registered_module, filename):
    assert (HERE / filename).read_bytes() == (registered_module.REFERENCE / filename).read_bytes()


def test_clean_environment_sets_registered_timeout_and_discards_ambient_settings(
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
