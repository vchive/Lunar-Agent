"""Preregistration and retained evidence stay independent of old real campaign slots."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parents[1] / "specs/134-budgeted-multifile-acceptance/measurement"


@pytest.fixture
def modules(monkeypatch):
    loaded = {}
    for name in ("case", "observation", "supervision", "campaign", "analysis"):
        spec = importlib.util.spec_from_file_location("measurement134_registration_" + name, HERE / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        loaded[name] = module
    return SimpleNamespace(**loaded)


@pytest.fixture
def registered(modules, monkeypatch, tmp_path):
    """Exercise registration against a real disposable product commit, not live src."""
    c = modules.campaign
    for name, content in {
        "src/offline_product.py": "VALUE = 1\n", "pyproject.toml": "[project]\nname = 'offline134'\n",
        "fixture/measurement.py": "MEASUREMENT = 1\n", "fixture/history.json": "{}\n",
    }.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.setattr(c, "REPO", tmp_path)
    c.git("add", "src", "pyproject.toml", "fixture")
    c.git("-c", "user.name=Offline134", "-c", "user.email=offline134@example.invalid",
          "commit", "-qm", "Synthetic registration product")
    monkeypatch.setattr(c, "PRODUCT_COMMIT", c.git("rev-parse", "HEAD"))
    monkeypatch.setattr(c, "MANIFEST", tmp_path / "manifest.json")
    monkeypatch.setattr(c, "measurement_paths", lambda: [tmp_path / "fixture/measurement.py"])
    monkeypatch.setattr(c, "historical_paths", lambda: [tmp_path / "fixture/history.json"])
    monkeypatch.setattr(c, "runtime_identity", lambda: {"fixture": "offline-runtime"})
    fixed = c.fixed_conditions()
    monkeypatch.setattr(c, "load_provider", lambda **kwargs: SimpleNamespace(safe_metadata=lambda model: fixed["provider"]))
    c.prepare()
    return c


def test_fixed_native_acceptance_preserves_separate_denominator(modules):
    c = modules.campaign
    value = c.fixed_conditions()
    assert value["product_commit"] == "15710bd420d70aa07a06ee9dd4329dfbf1912b2b"
    assert value["limits"] == {"request_seconds": 900, "candidate_seconds": 600,
                               "preparation_request_seconds": 900, "preparation_wall_seconds": 1860,
                               "wall_seconds": 2400, "max_requests": 20,
                               "token_stop_threshold": 160000, "holdout_seconds": 5}
    assert value["preparation_policy"] == {
        "timeout": 600, "evaluator_preparation_timeout": 900,
        "evaluator_preparation_wall_timeout": 1860, "timeout_source": "explicit",
        "evaluator_preparation_timeout_source": "explicit",
        "evaluator_preparation_wall_timeout_source": "explicit",
    }
    assert value["planned_attempts"] == 1 and value["retries_or_replacements"] == 0
    assert value["runtime_options"]["preparation_message_roles"] == ["system", "user"]
    assert value["runtime_options"]["preparation_tools"] == 0
    assert value["runtime_options"]["generated_contract"] is True
    assert value["runtime_options"]["max_retries"] == 1
    assert value["runtime_options"]["max_steps"] == 4
    assert value["population"] == {"size": 2, "offspring_per_iteration": 1, "islands": 1,
                                   "max_rounds": 1, "stagnation_rounds": 3, "seed": 129}
    assert value["holdouts"] == modules.case.holdouts()
    assert value["input_utf8"] == '{"limit":3}\n'
    assert value["goal"] == modules.case.GOAL
    assert value["goal_sha256"] == hashlib.sha256(modules.case.GOAL.encode()).hexdigest()
    assert "contract" not in value and "compiler_request" not in value
    prior = json.loads(c.REFERENCE.read_text())
    for field in ("input_utf8", "input_sha256", "holdouts", "sampling", "provider", "response_capture"):
        assert value[field] == prior[field]
    assert value["reference_preparation"]["manifest_sha256"] == c.sha(c.REFERENCE)
    previous = json.loads(c.PRIOR_ATTEMPT.read_text())
    assert value["reference_attempt"] == {
        "campaign_id": previous["campaign_id"],
        "manifest_sha256": c.sha(c.PRIOR_ATTEMPT),
        "product_commit": previous["product_commit"],
    }
    assert value["campaign_id"] == "acceptance134-glm-5.2-budgeted-multifile-20260918"
    assert value["campaign_root"] != prior["campaign_root"]
    assert value["campaign_root"] != json.loads(c.PRIOR_ATTEMPT.read_text())["campaign_root"]
    assert c.REFERENCE.relative_to(c.REPO).as_posix() in c.pins(c.historical_paths())
    assert c.PRIOR_ATTEMPT.relative_to(c.REPO).as_posix() in c.pins(c.historical_paths())
    assert previous["campaign_id"] == "acceptance131-glm-5.2-small-multifile-20260917"
    assert value["changed_conditions"]["comparison"] == "new_independent_acceptance_not_causal"
    assert value["limits"]["wall_seconds"] == previous["limits"]["wall_seconds"]
    assert value["limits"]["candidate_seconds"] == previous["limits"]["request_seconds"]


def test_offline_registration_is_once_only_and_verifies_without_provider_requests(registered):
    manifest = registered.verify()
    assert manifest["planned_attempts"] == 1
    assert set(manifest["product_files"])
    assert set(manifest["product_files"]) == {"src/offline_product.py", "pyproject.toml"}
    assert set(manifest["measurement_files"]) == {"fixture/measurement.py"}
    assert set(manifest["historical_files"]) == {"fixture/history.json"}
    with pytest.raises(ValueError, match="already_exists"):
        registered.prepare()


def commit_registration(c):
    c.git("add", "manifest.json")
    c.git("-c", "user.name=Offline134", "-c", "user.email=offline134@example.invalid",
          "commit", "-qm", "Synthetic fixed registration")
    c.git("update-ref", "refs/remotes/origin/main", c.git("rev-parse", "HEAD"))


def test_committed_registration_verifies_only_the_disposable_repository(registered):
    with pytest.raises(subprocess.CalledProcessError):
        registered.verify(committed=True)
    commit_registration(registered)
    result = registered.verify(committed=True)
    assert result["product_commit"] == registered.PRODUCT_COMMIT
    assert result["product_commit"] != registered.git("rev-parse", "HEAD")


def test_product_drift_is_rejected_before_a_temporary_manifest_is_created(registered):
    registered.MANIFEST.unlink()
    (registered.REPO / "src/offline_product.py").write_text("VALUE = 2\n")
    with pytest.raises(ValueError, match="product_changed"):
        registered.prepare()
    assert not registered.MANIFEST.exists()


@pytest.mark.parametrize("name", ["src/offline_product.py", "pyproject.toml"])
@pytest.mark.parametrize("action", ["prepare", "verify"])
def test_deleted_fixed_product_file_cannot_be_omitted_from_registration(registered, name, action):
    c = registered
    c.git("rm", "-q", name)
    if action == "prepare":
        c.MANIFEST.unlink()
    else:
        value = json.loads(c.MANIFEST.read_text())
        del value["product_files"][name]
        c.MANIFEST.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="product_file_set_changed"):
        getattr(c, action)()
    if action == "prepare":
        assert not c.MANIFEST.exists()


@pytest.mark.parametrize("action", ["prepare", "verify"])
def test_added_tracked_product_file_cannot_expand_the_fixed_product(registered, action):
    c = registered
    path = c.REPO / "src/extra.py"
    path.write_text("EXTRA = 1\n")
    c.git("add", "src/extra.py")
    if action == "prepare":
        c.MANIFEST.unlink()
    else:
        value = json.loads(c.MANIFEST.read_text())
        value["product_files"]["src/extra.py"] = c.sha(path)
        c.MANIFEST.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="product_file_set_changed"):
        getattr(c, action)()
    if action == "prepare":
        assert not c.MANIFEST.exists()


def test_input_mathematics_still_matches_preparation_reference(modules, monkeypatch):
    monkeypatch.setattr(modules.campaign, "INPUT_BYTES", b'{"limit":4}\n')
    with pytest.raises(ValueError, match="prior_mathematics_changed"):
        modules.campaign.fixed_conditions()


def test_prior_attempt_condition_drift_is_rejected(modules, monkeypatch, tmp_path):
    prior = json.loads(modules.campaign.PRIOR_ATTEMPT.read_text())
    prior["population"]["seed"] = 131
    path = tmp_path / "prior.json"
    path.write_text(json.dumps(prior))
    monkeypatch.setattr(modules.campaign, "PRIOR_ATTEMPT", path)
    monkeypatch.setattr(modules.campaign, "PRIOR_ATTEMPT_SHA", modules.campaign.sha(path))
    with pytest.raises(ValueError, match="prior_attempt_conditions_changed"):
        modules.campaign.fixed_conditions()


@pytest.mark.parametrize("condition", ["unpushed", "uncommitted_manifest", "uncommitted_pin"])
def test_unpushed_or_uncommitted_registration_is_rejected_before_launch(registered, condition):
    c = registered
    commit_registration(c)
    value = json.loads(c.MANIFEST.read_text())
    if condition == "unpushed":
        c.git("update-ref", "refs/remotes/origin/main", c.PRODUCT_COMMIT)
        expected = "registration_not_pushed"
    elif condition == "uncommitted_manifest":
        value["registered_utc"] = "different-registration-time"
        c.MANIFEST.write_text(json.dumps(value))
        expected = "manifest_not_committed"
    else:
        path = c.REPO / "fixture/measurement.py"
        path.write_text("MEASUREMENT = 2\n")
        value["measurement_files"]["fixture/measurement.py"] = c.sha(path)
        c.MANIFEST.write_text(json.dumps(value))
        expected = "registered_bytes_not_committed"
    with pytest.raises(ValueError, match=expected):
        c.verify(committed=True)


@pytest.mark.parametrize("field", [
    "limits", "goal", "goal_sha256", "input_utf8", "input_sha256", "population",
    "holdouts", "planned_attempts", "retries_or_replacements", "sampling", "runtime_options",
    "provider", "campaign_root", "primary", "secondary", "joint",
    "reference_preparation", "reference_attempt", "local_failure_capture", "holdout_continuation",
    "official_quality_requires", "preparation_policy", "request_failure_capture", "wall_failure_capture",
    "transport_status_capture", "changed_conditions",
])
def test_changed_fixed_conditions_are_rejected(registered, field):
    value = json.loads(registered.MANIFEST.read_text())
    value[field] = None
    registered.MANIFEST.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="fixed_conditions"):
        registered.verify()


@pytest.mark.parametrize("group", ["product_files", "measurement_files", "historical_files"])
def test_file_set_omission_is_rejected(registered, group):
    value = json.loads(registered.MANIFEST.read_text())
    value[group].pop(next(iter(value[group])))
    registered.MANIFEST.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="file_set"):
        registered.verify()


@pytest.mark.parametrize("group", ["product_files", "measurement_files", "historical_files"])
def test_registered_byte_drift_is_rejected(registered, group):
    value = json.loads(registered.MANIFEST.read_text())
    value[group][next(iter(value[group]))] = "0" * 64
    registered.MANIFEST.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="registered_bytes"):
        registered.verify()


@pytest.mark.parametrize("reason", ["provider_registration_mismatch", "provider_configuration_unavailable"])
def test_provider_failure_before_launch_does_not_consume_the_only_slot(registered, monkeypatch, reason):
    c = registered
    manifest = c.verify()
    root = c.REPO / manifest["campaign_root"]
    calls = []

    def unavailable(*, requested_model, expected):
        calls.append((requested_model, expected))
        assert not root.exists()
        raise ValueError(reason)

    monkeypatch.setattr(c, "load_provider", unavailable)
    with pytest.raises(ValueError, match=reason):
        c.run(manifest, runner=lambda *args: pytest.fail("worker must not start"))
    assert calls == [("glm-5.2", manifest["provider"])]
    assert not root.exists()


def test_provider_identity_is_checked_before_successful_slot_creation(registered, monkeypatch):
    c = registered
    manifest = c.verify()
    root = c.REPO / manifest["campaign_root"]
    order = []

    def provider(*, requested_model, expected):
        assert requested_model == "glm-5.2" and expected == manifest["provider"]
        assert not root.exists()
        order.append("provider")
        return SimpleNamespace(safe_metadata=lambda model: expected)

    def runner(command, slot, wall):
        assert (slot / "started.json").is_file()
        order.append("worker")
        return {"process_status": "exited", "exit_code": 0, "cleanup_verified": True,
                "remaining_observed_pids": [], "elapsed_seconds": 1.0}

    monkeypatch.setattr(c, "load_provider", provider)
    c.run(manifest, runner=runner)
    assert order == ["provider", "worker"]


def test_summarize_admission_does_not_require_current_provider_credentials(registered, monkeypatch, capsys):
    c = registered
    before = c.MANIFEST.read_bytes()
    monkeypatch.setattr(c, "load_provider", lambda **kwargs: pytest.fail("summary must not load credentials"))
    monkeypatch.setattr(c, "summarize", lambda manifest: {"status": "offline-summary"})
    monkeypatch.setattr(sys, "argv", ["campaign.py", "summarize"])
    c.main()
    assert json.loads(capsys.readouterr().out) == {"status": "offline-summary"}
    assert c.MANIFEST.read_bytes() == before


@pytest.mark.parametrize("failure", [False, True])
def test_campaign_consumes_only_one_slot_even_when_supervisor_fails(registered, failure):
    calls = []

    def runner(command, slot, wall):
        calls.append(command)
        assert wall == 2400
        assert (slot / "started.json").is_file()
        assert (slot.parent / "started.json").is_file()
        if failure:
            raise OSError("private supervisor detail")
        return {"process_status": "exited", "exit_code": 0, "cleanup_verified": True,
                "remaining_observed_pids": [], "elapsed_seconds": 1.0}

    manifest = registered.verify()
    value = registered.run(manifest, runner=runner)
    assert value["status"] == ("cleanup_unverified" if failure else "finished")
    with pytest.raises(FileExistsError):
        registered.run(manifest, runner=runner)
    assert len(calls) == 1
    evidence = json.loads((registered.REPO / manifest["campaign_root"] / "attempt-001/finished.json").read_text())
    assert evidence["process_status"] == ("supervisor_failed" if failure else "exited")
    assert "private supervisor detail" not in json.dumps(evidence)
