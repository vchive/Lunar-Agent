"""Offline worker wiring: native receipt authority and phase process boundaries."""

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest
from test_effect_trial import _fixture

from famou.effect_trial import EffectTrialError, _profile_digest
from famou.profiles import ModelProfile

WORKER = Path(__file__).resolve().parents[1] / "specs/069-webagent-normal-workflow/measurement/worker.py"


@pytest.fixture
def worker():
    spec = importlib.util.spec_from_file_location("offline_measurement069_worker", WORKER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def scaffold(tmp_path, worker, monkeypatch):
    tmp_path = tmp_path.resolve()
    suite_path, baseline_path, _, _, _ = _fixture(tmp_path)
    monkeypatch.setattr(worker, "REPO", tmp_path)
    campaign = tmp_path / "offline-campaign"
    inputs = campaign / "inputs"
    inputs.mkdir(parents=True)
    (campaign / "slots/001").mkdir(parents=True)
    cli = tmp_path / ".venv/bin/lunar-agent"
    cli.parent.mkdir(parents=True)
    cli.write_text("offline-placeholder")
    suite = json.loads(suite_path.read_text())
    worker.write_new(inputs / "fixture_case-suite.json", suite)
    baseline = json.loads(baseline_path.read_text())
    baseline["model"]["requested"] = "glm-5.2"
    worker.write_new(inputs / "fixture_case-baseline.json", baseline)
    profile = ModelProfile("offline-profile", "glm-5.2", max_steps=200, timeout_seconds=5400,
                           max_total_tokens=8000000)
    worker.write_new(inputs / "profile.json", profile.to_dict())
    environment = {
        "FAMOU_MODEL_ENDPOINT": "https://subject.invalid", "FAMOU_API_KEY": "fixture-subject",
        "ANTHROPIC_BASE_URL": "https://harness.invalid", "ANTHROPIC_AUTH_TOKEN": "fixture-extractor",
        "ANTHROPIC_MODEL": "glm-5.2",
    }
    slot = {"index": 1, "arm": "M", "case_key": "fixture_case", "workflow_config": None,
            "request_sha256": worker.request_sha256(suite, _profile_digest(profile))}
    manifest = {
        "campaign_id": campaign.name, "profile_sha256": _profile_digest(profile),
        "cases": {"fixture_case": {"public_root_rel": "case", "private_root_rel": "private"}},
        "execution": {"subject_outer_seconds": 5430, "harness_outer_seconds": 3630},
        "endpoints": {key: hashlib.sha256(environment[key].encode()).hexdigest()
                      for key in ("FAMOU_MODEL_ENDPOINT", "ANTHROPIC_BASE_URL")},
    }
    return campaign, manifest, slot, environment


@pytest.mark.parametrize("failure", [None, "subject_process", "missing_receipt", "changed_request_pin"])
def test_native_runner_owns_receipt_gate_and_phase_timeouts(tmp_path, worker, monkeypatch, failure):
    campaign, manifest, slot, configured = scaffold(tmp_path, worker, monkeypatch)
    checked, called = [], []
    monkeypatch.setattr(worker, "verify_bindings", lambda *args, **kwargs: checked.append(args))
    if failure == "changed_request_pin":
        slot["request_sha256"] = "a" * 64

    def process(command, *, cwd, env, timeout):
        request = json.loads((cwd / "request.json").read_text())
        called.append(cwd.name)
        if cwd.name == "subject":
            assert timeout == 5430
            assert "FAMOU_API_KEY" in env and "ANTHROPIC_AUTH_TOKEN" not in env
            assert "--model-profile" in command
            (cwd / "solution.json").write_text('{"fixture": true}')
            if failure == "subject_process":
                return subprocess.CompletedProcess(command, 2)
            if failure == "missing_receipt":
                return subprocess.CompletedProcess(command, 0)
            receipt = {
                "schema_version": "1", "mode": "normal", "status": "completed",
                "requested_model": "glm-5.2", "effective_model": "glm-5.2",
                "model_evidence": "provider_observed", "interaction_turns": 2,
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                "model_profile_sha256": request["model_profile_sha256"], "cost_micros": None,
            }
        else:
            assert timeout == 3630
            assert "ANTHROPIC_AUTH_TOKEN" in env and "FAMOU_API_KEY" not in env
            receipt = {
                "schema_version": "1", "status": "completed",
                **{key: request[key] for key in ("benchmark", "evaluation_profile", "case", "harness")},
                "extraction_status": "completed", "validity_score": 1,
                "overall_score": 1.2, "quality_score": None, "detail_metrics": {},
            }
        worker.write_new(cwd / "receipt.json", receipt)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(worker, "_default_executor", process)
    executor = worker.RegisteredExecutor(campaign / "manifest.json", campaign, manifest, "a" * 64, slot)
    runner = worker.build_runner(manifest, campaign, slot, configured, process_executor=executor)
    report = runner.run().to_dict()
    run = report["cases"][0]["runs"][0]
    root = campaign / "slots/001"
    if failure is None:
        assert called == ["subject", "harness"] and len(checked) == 2
        assert run["ready"] and run["overall_score"] == 1.2
        assert worker.read_json(root / "subject-started.json")["outer_timeout_seconds"] == 5430
        assert worker.read_json(root / "harness-started.json")["outer_timeout_seconds"] == 3630
    else:
        assert called == ([] if failure == "changed_request_pin" else ["subject"])
        assert not run["ready"] and run["overall_score"] is None
        assert not (root / "harness-started.json").exists()
    assert "fixture-subject" not in (root / "trial/report.json").read_text()
    assert "fixture-extractor" not in (root / "trial/report.json").read_text()
    with pytest.raises(EffectTrialError):
        runner.run()


def test_environment_split_checks_endpoints_and_ignores_ambient_values(tmp_path, worker, monkeypatch):
    _, manifest, _, configured = scaffold(tmp_path, worker, monkeypatch)
    configured["UNRELATED_PRIVATE_TOKEN"] = "must-not-be-forwarded"
    subject, harness = worker.split_environment(configured, manifest)
    assert set(subject) == {*worker.SUBJECT_ENV_NAMES, "PYTHONDONTWRITEBYTECODE"}
    assert set(harness) == {*worker.HARNESS_ENV_NAMES, "PYTHONDONTWRITEBYTECODE"}
    configured["FAMOU_MODEL_ENDPOINT"] = "https://changed.invalid"
    with pytest.raises(EffectTrialError):
        worker.split_environment(configured, manifest)


def test_control_files_never_overwrite_or_follow_links(tmp_path, worker):
    root = tmp_path.resolve()
    marker = root / "started.json"
    worker.write_new(marker, {"index": 1})
    with pytest.raises(FileExistsError):
        worker.write_new(marker, {"index": 2})
    assert worker.read_json(marker) == {"index": 1}
    (root / "linked").symlink_to(root, target_is_directory=True)
    with pytest.raises(EffectTrialError):
        worker.confined(root, "linked/started.json")
    for relative in ("../outside", "a/../outside", "a//b", "/outside"):
        with pytest.raises(EffectTrialError):
            worker.confined(root, relative)
