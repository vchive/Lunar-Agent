"""One-slot admission and native isolated preparation under a real local supervisor."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest
from test_measurement123_case import SOURCE, suite

from famou.agent_loop import ISOLATED_SYSTEM_PROMPT
from famou.http_transport import TransportObservation, TransportResponse
from famou.runtime import ModelRequestFailure, ModelTurn, OpenAICompatibleRuntime

HERE = (Path(__file__).resolve().parents[1]
        / "specs/123-small-evaluator-diagnostic/measurement")


def load(monkeypatch, name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def modules(monkeypatch, tmp_path):
    case = load(monkeypatch, "measurement123_runner_case", "case.py")
    observation = load(monkeypatch, "measurement123_runner_observation", "observation.py")
    supervision = load(monkeypatch, "measurement123_runner_supervision", "supervision.py")
    for name, module in (("case", case), ("observation", observation), ("supervision", supervision)):
        monkeypatch.setitem(sys.modules, name, module)
    campaign = load(monkeypatch, "measurement123_runner_campaign", "campaign.py")
    monkeypatch.setitem(sys.modules, "campaign", campaign)
    monkeypatch.setattr(campaign, "REPO", tmp_path)
    monkeypatch.setattr(campaign, "MANIFEST", tmp_path / "manifest.json")
    monkeypatch.setattr(campaign, "git", lambda *args: "offline-registration-commit")
    campaign.MANIFEST.write_text("{}\n")
    _, profile = case.stage_inputs(tmp_path / "registered-input")
    provider = observation.ProviderConfiguration(
        "https://offline.invalid/v1", "offline-fixture-secret", "glm-5.2",
    )
    manifest = {
        "campaign_id": campaign.CAMPAIGN_ID,
        "campaign_root": ".lunar/" + campaign.CAMPAIGN_ID,
        "limits": dict(campaign.LIMITS), "planned_attempts": 1,
        "schedule": [{"index": 1, "attempt_id": "attempt-001"}],
        "provider": provider.safe_metadata("glm-5.2"),
        "input_profile": profile, "contract": case.contract().to_dict(),
    }
    return campaign, case, observation, supervision, manifest, provider


def process_result(**changes):
    return {
        "process_status": "exited", "exit_code": 0, "cleanup_verified": True,
        "remaining_observed_pids": [], "elapsed_seconds": 0.01, "error_type": None,
        **changes,
    }


def start_worker(campaign, manifest):
    root = campaign.REPO / manifest["campaign_root"]
    root.mkdir(parents=True, mode=0o700)
    slot = root / "attempt-001"
    slot.mkdir(mode=0o700)
    marker = {
        "campaign_id": campaign.CAMPAIGN_ID,
        "manifest_sha256": campaign.sha(campaign.MANIFEST),
        "registration_commit": "offline-registration-commit", "index": 1,
    }
    campaign.write_new(root / "started.json", marker)
    campaign.write_new(slot / "started.json", marker)
    return root, slot


def test_run_claims_one_new_slot_before_launch_and_never_reopens_it(modules):
    campaign, _, _, _, manifest, _ = modules
    old = campaign.REPO / ".lunar/acceptance120-frozen"
    old.mkdir(parents=True)
    (old / "started.json").write_bytes(b"old immutable evidence")
    calls = []

    def runner(command, slot, wall):
        assert command == [sys.executable, str(HERE / "worker.py")]
        assert wall == 1320
        assert slot.name == "attempt-001"
        assert (slot / "started.json").is_file()
        assert (slot.parent / "started.json").is_file()
        assert slot.stat().st_mode & 0o777 == 0o700
        calls.append(command)
        return process_result()

    result = campaign.run(manifest, runner)
    assert result["status"] == "finished" and result["planned_attempts"] == 1
    assert len(calls) == 1
    root = campaign.REPO / manifest["campaign_root"]
    assert json.loads((root / "attempt-001/finished.json").read_text())["cleanup_verified"]
    assert (root / "started.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        campaign.run(manifest, runner)
    assert len(calls) == 1
    assert (old / "started.json").read_bytes() == b"old immutable evidence"


@pytest.mark.parametrize("outcome", ["cleanup_unknown", "exception", "interrupt"])
def test_run_retains_consumed_slot_when_supervision_cannot_finish_safely(modules, outcome):
    campaign, _, _, _, manifest, _ = modules
    calls = []

    def runner(*args):
        calls.append(1)
        if outcome == "exception":
            raise OSError("private exception prose")
        if outcome == "interrupt":
            raise KeyboardInterrupt("private exception prose")
        return process_result(cleanup_verified=False, remaining_observed_pids=[123])

    result = campaign.run(manifest, runner)
    assert result["status"] == "cleanup_unverified" and result["planned_attempts"] == 1
    root = campaign.REPO / manifest["campaign_root"]
    assert (root / "attempt-001/finished.json").is_file()
    assert "private exception prose" not in (root / "attempt-001/finished.json").read_text()
    with pytest.raises(FileExistsError):
        campaign.run(manifest, runner)
    assert calls == [1]


@pytest.mark.parametrize("outcome,expected_calls", [
    ("success", 2), ("compiler_json", 1), ("compiler_source", 1),
    ("compiler_preflight", 1), ("compiler_timeout", 1), ("auditor_json", 2),
])
def test_worker_native_isolation_limits_and_conditional_auditor(
    modules, monkeypatch, capsys, outcome, expected_calls,
):
    campaign, case, observation, _, manifest, provider = modules
    _, slot = start_worker(campaign, manifest)
    worker = load(monkeypatch, "measurement123_runner_worker", "worker.py")
    verifications, provider_calls, native_calls, guards = [], [], [], []

    def verify(**kwargs):
        verifications.append(kwargs)
        return manifest

    def get_provider(**kwargs):
        assert (slot / "worker-started.json").is_file()
        provider_calls.append(kwargs)
        return provider

    real_guard = worker.RuntimeGuard

    def guard(*args, **kwargs):
        assert kwargs["max_requests"] == 2
        assert kwargs["request_seconds"] == 600
        assert kwargs["token_stop_threshold"] == 160000
        assert 1300 < kwargs["wall_seconds"] <= 1320
        instance = real_guard(*args, **kwargs)
        guards.append(instance)
        return instance

    def forbidden(*args, **kwargs):
        pytest.fail("offline runner test attempted real network or provider configuration")

    def native(runtime, messages, tools=(), timeout=None):
        index = len(native_calls) + 1
        native_calls.append(messages)
        assert index == guards[0].requests
        assert runtime.model == "glm-5.2" and runtime.api_key == provider.api_key
        assert timeout == 600 and tools == ()
        assert [item["role"] for item in messages] == ["system", "user"]
        assert messages[0]["content"] == ISOLATED_SYSTEM_PROMPT
        assert "lunar-candidate-evaluation-request-v1" in messages[1]["content"]
        if index == 1:
            assert "compiling one frozen local evaluator bundle" in messages[1]["content"]
            if outcome == "compiler_timeout":
                raise ModelRequestFailure("private provider prose", "transport_timeout")
            source = SOURCE
            if outcome == "compiler_source":
                source = "import subprocess\n" + source
            if outcome == "compiler_preflight":
                source = source.replace("0 <= value <= limit", "0 <= value < limit")
            text = json.dumps({**suite(2), "evaluator_source": source, "objective": "Maximize value."})
            if outcome == "compiler_json":
                text = "not a compiler envelope"
        else:
            assert index == 2
            assert "independent adversarial evaluator auditor" in messages[1]["content"]
            text = "not an audit suite" if outcome == "auditor_json" else json.dumps(suite(4))
        return ModelTurn(text, response_model="glm-5.2", usage={
            "input_tokens": 3, "output_tokens": 2, "total_tokens": 5,
        })

    monkeypatch.setattr(worker, "verify", verify)
    monkeypatch.setattr(worker, "load_provider", get_provider)
    monkeypatch.setattr(worker, "RuntimeGuard", guard)
    monkeypatch.setattr(observation._shared, "load_provider", forbidden)
    monkeypatch.setattr("famou.runtime.exchange", forbidden)
    monkeypatch.setattr("famou.runtime.urlopen", forbidden)
    monkeypatch.setattr(OpenAICompatibleRuntime, "complete", native)
    if outcome != "success":
        monkeypatch.setattr(worker, "audit_holdouts", forbidden)

    assert worker.main() == (0 if outcome == "success" else 1)
    assert OpenAICompatibleRuntime.complete is native
    assert len(native_calls) == expected_calls
    assert len(provider_calls) == len(guards) == 1
    assert provider_calls == [{"requested_model": "glm-5.2", "expected": manifest["provider"]}]
    assert all(item == {"committed": True} for item in verifications)
    with pytest.raises(FileExistsError):
        worker.main()
    assert len(native_calls) == expected_calls and len(provider_calls) == 1
    result = json.loads((slot / "worker-finished.json").read_text())
    assert result["guard"]["provider_requests"] == expected_calls
    assert result["guard"]["usage_complete"] is (outcome != "compiler_timeout")
    assert len(result["holdouts"]) == (8 if outcome == "success" else 0)
    assert (result["frozen"] is not None) is (outcome == "success")
    if outcome == "success":
        assert all(row["matched"] for row in result["holdouts"])
        assert len(list((slot / "holdouts").glob("*.json"))) == 8
        assert result["frozen"]["contract_sha256"] == case.contract().digest()
    assert "private provider prose" not in json.dumps(result)
    assert "private-generated-text" not in json.dumps(result)
    assert provider.api_key not in capsys.readouterr().out


@pytest.mark.parametrize("invalid", ["root_marker", "slot_marker", "finished"])
def test_worker_requires_matching_unfinished_attempt_before_provider_access(modules, monkeypatch, invalid):
    campaign, _, _, _, manifest, _ = modules
    root, slot = start_worker(campaign, manifest)
    worker = load(monkeypatch, "measurement123_runner_marker_worker", "worker.py")
    monkeypatch.setattr(worker, "verify", lambda **kwargs: manifest)

    def forbidden(*args, **kwargs):
        pytest.fail("invalid marker attempted provider access")

    monkeypatch.setattr(worker, "load_provider", forbidden)
    if invalid == "finished":
        campaign.write_new(root / "finished.json", {})
    else:
        target = root if invalid == "root_marker" else slot
        (target / "started.json").write_text('{}\n')
    with pytest.raises(ValueError, match="attempt_"):
        worker.main()
    assert not (slot / "worker-started.json").exists()


def test_worker_setup_failure_consumes_claim_without_model_call(modules, monkeypatch):
    campaign, _, _, _, manifest, _ = modules
    _, slot = start_worker(campaign, manifest)
    worker = load(monkeypatch, "measurement123_runner_setup_worker", "worker.py")
    manifest["input_profile"] = {"wrong": "profile"}
    monkeypatch.setattr(worker, "verify", lambda **kwargs: manifest)

    def forbidden(*args, **kwargs):
        pytest.fail("failed setup attempted provider access")

    monkeypatch.setattr(worker, "load_provider", forbidden)
    assert worker.main() == 1
    result = json.loads((slot / "worker-finished.json").read_text())
    assert result["stage"] == "setup" and result["guard"] is None
    assert result["frozen"] is None and result["holdouts"] == []
    with pytest.raises(FileExistsError):
        worker.main()


def test_successful_worker_evidence_is_summarized_once_without_reexecution(
    modules, monkeypatch, tmp_path,
):
    campaign, case, _, _, manifest, provider = modules
    manifest.update(
        product_commit=campaign.PRODUCT_COMMIT,
        compiler_request=campaign.fixed_conditions()["compiler_request"],
    )
    campaign.MANIFEST.write_text(campaign.canonical(manifest))
    monkeypatch.setattr(campaign, "git", lambda *args: "a" * 40)
    worker = load(monkeypatch, "measurement123_success_evidence_worker", "worker.py")
    monkeypatch.setattr(worker, "verify", lambda **kwargs: manifest)
    monkeypatch.setattr(worker, "load_provider", lambda **kwargs: provider)
    exchanges = []

    def forbidden(*args, **kwargs):
        pytest.fail("read-only summary attempted model or evaluator execution")

    def offline_exchange(request, timeout):
        exchanges.append(request.data)
        assert timeout == 600
        index = len(exchanges)
        assert index <= 2
        if index == 1:
            assert len(request.data) == manifest["compiler_request"]["bytes"]
            assert hashlib.sha256(request.data).hexdigest() == manifest["compiler_request"]["sha256"]
            answer = {**suite(2), "evaluator_source": SOURCE, "objective": "Maximize value."}
        else:
            answer = suite(4)
        response = {"model": "glm-5.2", "choices": [{"message": {
            "role": "assistant", "content": json.dumps(answer),
        }}], "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}
        return TransportResponse(
            200, json.dumps(response).encode(),
            TransportObservation("response_headers_received", 1, 1),
        )

    monkeypatch.setattr("famou.runtime.exchange", offline_exchange)
    monkeypatch.setattr("famou.runtime.urlopen", forbidden)

    def runner(command, slot, wall):
        assert command == [sys.executable, str(HERE / "worker.py")] and wall == 1320
        return process_result(exit_code=worker.main())

    assert campaign.run(manifest, runner)["status"] == "finished"
    assert len(exchanges) == 2
    slot = campaign.REPO / manifest["campaign_root"] / "attempt-001"
    assert json.loads((slot / "worker-finished.json").read_text())["status"] == "completed"
    analysis = load(monkeypatch, "measurement123_success_evidence_analysis", "analysis.py")
    output = tmp_path / "public/measurement"
    output.mkdir(parents=True)
    monkeypatch.setattr(analysis, "HERE", output)
    monkeypatch.setattr("famou.runtime.exchange", forbidden)
    monkeypatch.setattr(OpenAICompatibleRuntime, "complete", forbidden)
    monkeypatch.setattr(worker, "compile_evaluator_bundle", forbidden)
    monkeypatch.setattr(case, "_snapshot_probe", forbidden)
    monkeypatch.setattr("famou.candidate_execution_runner._bounded_process_bytes", forbidden)

    result = analysis.summarize(manifest)
    assert result["planned_attempts"] == result["preparation_success"] == result["joint_success"] == 1
    assert result["holdouts"]["planned"] == result["holdouts"]["executed"] == result["holdouts"]["matched"] == 8
    assert result["usage"]["provider_requests"] == result["usage"]["finished_requests"] == 2
    assert result["usage"]["usage_complete"] is True
    assert result["usage"]["total_usage"] == {
        "input_tokens": 6, "output_tokens": 4, "total_tokens": 10,
    }
    assert len(result["transport"]) == 2
    assert all(row["transport_observation"]["last_milestone"] == "response_headers_received"
               for row in result["transport"])
    assert result["frozen"] == json.loads((slot / "frozen.json").read_text())
    assert result["quality"] is result["gap"] is result["usage"]["cost_micros"] is None
    postrun = output.parent / "postrun"
    before = {path.name: path.read_bytes() for path in postrun.iterdir()}
    assert json.loads(before["results.json"]) == result
    inventory = json.loads(before["evidence.json"])["files"]
    retained = campaign.REPO / manifest["campaign_root"]
    for name, expected in inventory.items():
        raw = (retained / name).read_bytes()
        assert expected == {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    assert "private-generated-text" not in json.dumps(result)
    with pytest.raises(FileExistsError):
        analysis.summarize(manifest)
    assert {path.name: path.read_bytes() for path in postrun.iterdir()} == before
    assert len(exchanges) == 2


def test_supervisor_scrubs_ambient_secrets_and_runtime_settings(modules, monkeypatch):
    _, _, _, supervision, _, _ = modules
    for key in ("OPENAI_API_KEY", "FAMOU_API_KEY", "FAMOU_MODEL", "FAMOU_RUNTIME_TIMEOUT",
                "FAMOU_MAX_RETRIES", "PYTHONPATH", "HTTPS_PROXY", "UNRELATED_SECRET"):
        monkeypatch.setenv(key, "private-ambient-value")
    environment = supervision.clean_environment()
    assert set(environment) == {"PATH", "HOME", "LANG", "LC_ALL", "PYTHONHASHSEED", "PYTHONIOENCODING"}
    assert "private-ambient-value" not in json.dumps(environment)


def test_supervisor_short_local_deadline_reaps_worker_and_observed_child(modules, tmp_path):
    _, _, _, supervision, _, _ = modules
    slot = tmp_path / "supervised"
    slot.mkdir()
    pids = slot / "pids.json"
    program = (
        "import json,os,subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        "open(sys.argv[1],'w').write(json.dumps([os.getpid(),child.pid])); "
        "time.sleep(60)"
    )
    started = time.monotonic()
    result = supervision.supervise([sys.executable, "-c", program, str(pids)], slot, 0.8)
    assert result["process_status"] == "timed_out"
    assert result["exit_code"] is not None
    assert result["cleanup_verified"] is True and result["remaining_observed_pids"] == []
    assert time.monotonic() - started < 6
    observed = json.loads(pids.read_text())
    table = supervision.process_table()
    assert all(pid not in table or table[pid][2].startswith("Z") for pid in observed)
    assert os.getpid() not in observed


def test_supervisor_local_success_preserves_output_and_proves_cleanup(modules, tmp_path):
    _, _, _, supervision, _, _ = modules
    slot = tmp_path / "supervised-success"
    slot.mkdir()
    result = supervision.supervise([sys.executable, "-c", "print('offline-success')"], slot, 3)
    assert result["process_status"] == "exited" and result["exit_code"] == 0
    assert result["cleanup_verified"] is True and result["remaining_observed_pids"] == []
    assert (slot / "stdout.log").read_text() == "offline-success\n"
    assert (slot / "stderr.log").read_bytes() == b""
