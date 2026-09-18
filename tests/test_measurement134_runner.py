"""Native full automatic solve under the registered guard, using only fresh local fixtures."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from test_measurement134_case import SOURCE, fixture_contract, suite

from famou.agent_loop import ISOLATED_SYSTEM_PROMPT
from famou.runtime import (
    ModelRequestFailure,
    ModelRequestObservation,
    ModelTurn,
    OpenAICompatibleRuntime,
)

HERE = (Path(__file__).resolve().parents[1]
        / "specs/134-budgeted-multifile-acceptance/measurement")


def load(monkeypatch, name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def modules(monkeypatch, tmp_path):
    case = load(monkeypatch, "measurement134_runner_case", "case.py")
    observation = load(monkeypatch, "measurement134_runner_observation", "observation.py")
    supervision = load(monkeypatch, "measurement134_runner_supervision", "supervision.py")
    for name, module in (("case", case), ("observation", observation), ("supervision", supervision)):
        monkeypatch.setitem(sys.modules, name, module)
    campaign = load(monkeypatch, "measurement134_runner_campaign", "campaign.py")
    monkeypatch.setitem(sys.modules, "campaign", campaign)
    monkeypatch.setattr(campaign, "REPO", tmp_path)
    monkeypatch.setattr(campaign, "MANIFEST", tmp_path / "manifest.json")
    campaign.MANIFEST.write_text("{}\n")
    analysis = load(monkeypatch, "measurement134_runner_analysis", "analysis.py")
    monkeypatch.setitem(sys.modules, "analysis", analysis)
    worker = load(monkeypatch, "measurement134_runner_worker", "worker.py")
    provider = observation.ProviderConfiguration("https://offline.invalid/v1", "offline-fixture-secret", "glm-5.2")
    manifest = {
        "campaign_id": campaign.CAMPAIGN_ID, "campaign_root": ".lunar/" + campaign.CAMPAIGN_ID,
        "limits": dict(campaign.LIMITS), "planned_attempts": 1,
        "schedule": [{"index": 1, "attempt_id": "attempt-001"}],
        "provider": provider.safe_metadata("glm-5.2"), "goal": case.GOAL,
        "input_utf8": case.INPUT_BYTES.decode(), "input_sha256": hashlib.sha256(case.INPUT_BYTES).hexdigest(),
        "population": {"size": 2, "offspring_per_iteration": 1, "islands": 1,
                       "max_rounds": 1, "stagnation_rounds": 3, "seed": 129},
        "runtime_options": {"max_steps": 4},
    }
    monkeypatch.setenv("FAMOU_MAX_RETRIES", "1")
    monkeypatch.setenv("FAMOU_RUNTIME_TIMEOUT", "600")
    monkeypatch.setattr(worker, "verify", lambda **kwargs: manifest)
    return campaign, case, observation, analysis, worker, manifest, provider


def start_worker(campaign, manifest):
    root = campaign.REPO / manifest["campaign_root"]
    slot = root / "attempt-001"
    slot.mkdir(parents=True, mode=0o700)
    marker = {"campaign_id": campaign.CAMPAIGN_ID, "manifest_sha256": campaign.sha(campaign.MANIFEST), "index": 1}
    campaign.write_new(root / "started.json", marker)
    campaign.write_new(slot / "started.json", marker)
    return root, slot


CANDIDATE = '''import json, os
from pathlib import Path
from helper import choose
limit = json.loads((Path(os.environ["LUNAR_CANDIDATE_INPUT_ROOT"]) / "limit.json").read_bytes())["limit"]
Path("output").mkdir(exist_ok=True)
Path("output/result.json").write_text(json.dumps({"value": choose(limit)}))
'''


def install_runtime(modules, monkeypatch, slot, outcome="success"):
    _, _, observation, _, worker, _, provider = modules
    requests, provider_calls = [], []

    def get_provider(**kwargs):
        assert (slot / "worker-started.json").is_file()
        provider_calls.append(kwargs)
        return provider

    def forbidden(*args, **kwargs):
        pytest.fail("offline fixture attempted a real provider or network")

    def native(runtime, messages, tools=(), timeout=None):
        index = len(requests) + 1
        requests.append(messages)
        assert runtime.model == "glm-5.2" and runtime.api_key == provider.api_key
        expected_timeout = 900 if index in (2, 3) else 600
        assert expected_timeout - 1 < timeout <= expected_timeout
        prompt = messages[-1]["content"]
        if index <= 3:
            assert not tools
            assert [item["role"] for item in messages] == ["system", "user"]
            assert messages[0]["content"] == ISOLATED_SYSTEM_PROMPT
        if index == 1:
            assert "contract compiler" in prompt
            data = fixture_contract().to_dict()
            if outcome == "contract_scope":
                data["hard_constraints"][1]["source_check"]["minimum"] = 1
            text = "private-invalid-contract" if outcome == "contract_response" else json.dumps({"status": "compiled", "contract": data})
        elif index == 2:
            assert "compiling one frozen local evaluator bundle" in prompt
            if outcome == "compiler_provider_failure":
                failure = ModelRequestFailure("private-provider-failure", "transport_timeout")
                failure.observation = ModelRequestObservation("open_response", 900000, 900000)
                raise failure
            text = "private-invalid-evaluator" if outcome == "compiler_response" else json.dumps({
                **suite(2), "evaluator_source": SOURCE, "objective": "Maximize the exact independently read value.",
            })
        elif index == 3:
            assert "independent adversarial evaluator auditor" in prompt
            if outcome == "auditor_provider_failure":
                failure = ModelRequestFailure("private-provider-failure", "transport_timeout")
                failure.observation = ModelRequestObservation("open_response", 900000, 900000)
                raise failure
            text = "private-invalid-auditor" if outcome == "auditor_response" else json.dumps(suite(4))
        else:
            assert tools and "LUNAR_CANDIDATE_INPUT_ROOT" in prompt
            names = [item["function"]["name"] for item in tools]
            assert not any("exec" in name or "memory" in name for name in names)
            assert "private-generated-text" not in json.dumps(messages)
            if outcome == "candidate_provider_failure":
                raise ModelRequestFailure("private-provider-failure", "transport_timeout")
            files = {"solve/main.py": CANDIDATE, "solve/helper.py": f"def choose(limit):\n    return {index - 3}\n"}
            if outcome == "candidate_source":
                files = {"solve/main.py": "raise ValueError('private-candidate-failure')\n"}
            text = json.dumps({"entrypoint": "solve/main.py", "files": files, "metadata": {}})
        return ModelTurn(text, response_model="glm-5.2", usage={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5})

    monkeypatch.setattr(worker, "load_provider", get_provider)
    monkeypatch.setattr(observation._shared, "load_provider", forbidden)
    monkeypatch.setattr("famou.runtime.exchange", forbidden)
    monkeypatch.setattr("famou.runtime.urlopen", forbidden)
    monkeypatch.setattr(OpenAICompatibleRuntime, "complete", native)
    return requests, provider_calls


def test_native_full_cli_preparation_population_delivery_and_eight_holdouts(modules, monkeypatch, capsys):
    campaign, case, _, analysis, worker, manifest, provider = modules
    _, slot = start_worker(campaign, manifest)
    requests, provider_calls = install_runtime(modules, monkeypatch, slot)
    assert worker.main() == 0
    retained = json.loads((slot / "worker-finished.json").read_text())
    assert retained["status"] == "completed" and retained["stage"] == "finished"
    assert retained["native_exit_code"] == 0 and retained["error_class"] is None
    assert retained["frozen"]["contract_sha256"] == fixture_contract().digest()
    assert len(retained["holdouts"]) == 8 and all(row["matched"] for row in retained["holdouts"])
    assert len(list((slot / "holdouts").glob("*.json"))) == 8
    assert (slot / "inputs/limit.json").read_bytes() == case.INPUT_BYTES
    cli = json.loads((slot / "cli.json").read_text())
    assert cli["status"] == cli["run_status"] == "succeeded"
    assert cli["evolution"]["result"]["evaluated_candidates"] == 3
    assert cli["evolution"]["preparation_budgets"] == {
        "candidate_timeout": {"seconds": 600, "source": "explicit"},
        "evaluator_preparation_timeout": {"seconds": 900, "source": "explicit"},
        "evaluator_preparation_wall_timeout": {"seconds": 1860, "source": "explicit"},
    }
    starts = [row for row in map(json.loads, (slot / "calls.jsonl").read_text().splitlines())
              if row["kind"] == "request_started"]
    assert [round(row["request_timeout_seconds"]) for row in starts] == [600, 900, 900, 600, 600, 600]
    profile_raw = (slot / "workspace/bundle-profile.json").read_bytes()
    profile = json.loads(profile_raw)
    assert profile["timeout_seconds"] == profile["evaluator"]["timeout_seconds"] == 600
    assert b"preparation" not in profile_raw
    assert len(requests) == 6 and retained["guard"]["provider_requests"] == 6
    assert json.loads((slot / "workspace/output/result.json").read_text())["value"] == 3
    assert analysis.inspect_product(slot)["primary_valid_completion"]
    assert provider_calls == [{"requested_model": "glm-5.2", "expected": manifest["provider"]}]
    with pytest.raises(FileExistsError):
        worker.main()
    assert len(requests) == 6 and len(provider_calls) == 1
    assert provider.api_key not in capsys.readouterr().out


@pytest.mark.parametrize("outcome,prepared,expected_requests", [
    ("contract_response", False, 1), ("compiler_response", False, 2), ("auditor_response", False, 3),
    ("contract_scope", False, 6), ("candidate_source", True, 5), ("candidate_provider_failure", True, 4),
])
def test_native_failures_keep_attempt_and_holdouts_depend_only_on_verified_preparation(
    modules, monkeypatch, outcome, prepared, expected_requests,
):
    campaign, _, _, _, worker, manifest, _ = modules
    _, slot = start_worker(campaign, manifest)
    requests, _ = install_runtime(modules, monkeypatch, slot, outcome)
    assert worker.main() == 1
    result = json.loads((slot / "worker-finished.json").read_text())
    assert result["status"] == "failed"
    assert (result["frozen"] is not None) is prepared
    assert len(result["holdouts"]) == (8 if prepared else 0)
    assert len(requests) == expected_requests
    assert "private-invalid" not in json.dumps(result)
    assert "private-candidate" not in json.dumps(result)
    assert "private-provider" not in json.dumps(result)
    if outcome == "candidate_provider_failure":
        assert result["guard"]["stopped_reason"] == "provider_error"
        assert all(row["matched"] for row in result["holdouts"])
        product = modules[3].inspect_product(slot)
        assert product["primary_valid_completion"] is False
        assert product["quality"] is None and product["quality_gap"] is None
    with pytest.raises(FileExistsError):
        worker.main()
    assert len(requests) == expected_requests


@pytest.mark.parametrize("invalid", ["root_marker", "slot_marker", "finished"])
def test_worker_rejects_unregistered_or_finished_slot_before_provider_access(modules, monkeypatch, invalid):
    campaign, _, _, _, worker, manifest, _ = modules
    root, slot = start_worker(campaign, manifest)
    if invalid == "finished":
        campaign.write_new(slot / "finished.json", {})
    else:
        path = (root if invalid == "root_marker" else slot) / "started.json"
        path.write_text("{}")
    monkeypatch.setattr(worker, "load_provider", lambda **kwargs: pytest.fail("provider loaded before marker validation"))
    with pytest.raises(ValueError):
        worker.main()
    assert not (slot / "worker-started.json").exists()


def test_setup_failure_consumes_slot_before_provider_and_never_runs_cli(modules, monkeypatch):
    campaign, _, _, _, worker, manifest, _ = modules
    _, slot = start_worker(campaign, manifest)
    manifest["input_sha256"] = "0" * 64
    monkeypatch.setattr(worker, "load_provider", lambda **kwargs: pytest.fail("provider loaded with drifted input"))
    assert worker.main() == 1
    result = json.loads((slot / "worker-finished.json").read_text())
    assert result["stage"] == "setup" and result["error_class"] == "ValueError"
    assert result["guard"] is None and result["frozen"] is None
    with pytest.raises(FileExistsError):
        worker.main()


def test_unexpected_native_exception_after_preparation_still_runs_holdouts_once(modules, monkeypatch):
    from famou import cli

    campaign, _, _, _, worker, manifest, _ = modules
    _, slot = start_worker(campaign, manifest)
    requests, _ = install_runtime(modules, monkeypatch, slot)
    native = cli.main

    def raised_after_return(args):
        assert native(args) == 0
        raise RuntimeError("private-after-native-return")

    monkeypatch.setattr(cli, "main", raised_after_return)
    assert worker.main() == 1
    result = json.loads((slot / "worker-finished.json").read_text())
    assert result["status"] == "failed" and result["stage"] == "solve"
    assert result["solve_error_class"] == "RuntimeError" and result["native_exit_code"] is None
    assert result["frozen"] is not None and len(result["holdouts"]) == 8
    assert len(requests) == 6 and all(row["matched"] for row in result["holdouts"])
    assert "private-after" not in json.dumps(result)


def test_request_stop_after_preparation_does_not_block_local_holdouts(modules, monkeypatch):
    campaign, _, _, _, worker, manifest, _ = modules
    _, slot = start_worker(campaign, manifest)
    requests, _ = install_runtime(modules, monkeypatch, slot)
    manifest["limits"]["max_requests"] = 3
    assert worker.main() == 1
    result = json.loads((slot / "worker-finished.json").read_text())
    assert result["guard"]["stopped_reason"] == "request_limit_reached"
    assert len(requests) == 3 and len(result["holdouts"]) == 8
    assert all(row["matched"] for row in result["holdouts"])


def test_local_holdouts_stay_inside_original_worker_wall_deadline(modules, monkeypatch):
    campaign, _, _, _, worker, manifest, _ = modules
    _, slot = start_worker(campaign, manifest)
    requests, _ = install_runtime(modules, monkeypatch, slot)
    verify = worker.verified_preparation
    clock = worker.time.monotonic

    def after_deadline(path):
        result = verify(path)
        now = clock()
        monkeypatch.setattr(worker.time, "monotonic", lambda: now + manifest["limits"]["wall_seconds"] + 1)
        return result

    monkeypatch.setattr(worker, "verified_preparation", after_deadline)
    assert worker.main() == 1
    result = json.loads((slot / "worker-finished.json").read_text())
    assert result["frozen"] is not None and result["holdouts"] == []
    assert result["stage"] == "holdouts" and result["error_class"] == "ValueError"
    assert len(requests) == 6 and not (slot / "holdout-workspaces").exists()


@pytest.mark.parametrize("stage,expected_requests", [("compiler", 2), ("auditor", 3)])
def test_preparation_request_failure_preserves_typed_observation_and_stops_admission(
    modules, monkeypatch, stage, expected_requests,
):
    campaign, _, _, _, worker, manifest, _ = modules
    _, slot = start_worker(campaign, manifest)
    requests, _ = install_runtime(modules, monkeypatch, slot, stage + "_provider_failure")
    assert worker.main() == 1
    result = json.loads((slot / "worker-finished.json").read_text())
    cli = json.loads((slot / "cli.json").read_text())
    preparation = cli["evolution"]["preparation"]
    assert cli["status"] == "failed" and cli["run_status"] == "running"
    assert preparation["schema_version"] == "3" and preparation["recoverable"] is True
    assert preparation["stage"] == {"compiler": "evaluator_compile", "auditor": "evaluator_audit"}[stage]
    assert preparation["request_failure"]["reason"] == "transport_timeout"
    assert preparation["request_failure"]["request_observation"] == {
        "phase": "open_response", "elapsed_ms": 900000, "request_timeout_ms": 900000,
    }
    assert result["guard"]["stopped_reason"] == "provider_error"
    assert result["guard"]["usage_complete"] is False
    assert len(requests) == expected_requests
    assert result["frozen"] is None and result["holdouts"] == []
    assert not (slot / "workspace/bundle-profile.json").exists()
    assert not (slot / "workspace/evolution-run").exists()
    assert "private-provider" not in json.dumps(cli)


@pytest.mark.parametrize("expiry,expected_requests", [("before_compiler", 1), ("after_compiler", 2)])
def test_preparation_wall_expiry_prevents_child_profile_and_extra_requests(
    modules, monkeypatch, expiry, expected_requests,
):
    from famou import automatic_solve_bundle as automatic
    from famou import evaluator_bundle
    from famou.store import Store

    campaign, _, _, _, worker, manifest, _ = modules
    _, slot = start_worker(campaign, manifest)
    requests, _ = install_runtime(modules, monkeypatch, slot)
    now = [100.0]
    monkeypatch.setattr(automatic, "monotonic", lambda: now[0])
    if expiry == "before_compiler":
        original = evaluator_bundle._compiler_prompt

        def prompt(*args, **kwargs):
            result = original(*args, **kwargs)
            now[0] += 1860
            return result

        monkeypatch.setattr(evaluator_bundle, "_compiler_prompt", prompt)
    else:
        original = OpenAICompatibleRuntime.complete

        def native(*args, **kwargs):
            result = original(*args, **kwargs)
            if len(requests) == 2:
                now[0] += 1860
            return result

        monkeypatch.setattr(OpenAICompatibleRuntime, "complete", native)
    assert worker.main() == 1
    cli = json.loads((slot / "cli.json").read_text())
    result = json.loads((slot / "worker-finished.json").read_text())
    preparation = cli["evolution"]["preparation"]
    assert cli["status"] == "failed" and cli["run_status"] == "running"
    assert preparation["schema_version"] == "4"
    assert preparation["stage"] == "evaluator_compile" and preparation["recoverable"] is True
    assert preparation["error_category"] == "preparation_timeout"
    assert preparation["wall_failure"] == {
        "schema_version": "1", "reason": "wall_timeout", "elapsed_ms": 1860000,
        "wall_timeout_ms": 1860000,
    }
    assert len(requests) == expected_requests
    assert result["frozen"] is None and result["holdouts"] == []
    assert not (slot / "workspace/bundle-profile.json").exists()
    assert not (slot / "workspace/evolution-run").exists()
    store = Store(slot / "home/state.db")
    events = store.list_events(cli["run_id"])
    assert not any(row["type"] == "bundle_profile_prepared" for row in events)
    assert len([row for row in events if row["type"] == "bundle_preparation_started"]) == 1
    with pytest.raises(FileExistsError):
        worker.main()
    assert len(requests) == expected_requests
