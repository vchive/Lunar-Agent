"""Offline 117 routing preserves one attempt per slot and the registered deadline limits."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from famou import cli
from famou.runtime import ModelTurn, OpenAICompatibleRuntime

HERE = Path(__file__).resolve().parents[1] / "specs/117-extended-deadline-acceptance/measurement"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def campaign(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(HERE))
    module = load_module("measurement117_runner", HERE / "campaign.py")
    monkeypatch.setitem(sys.modules, "campaign", module)
    monkeypatch.setattr(module, "REPO", tmp_path)
    monkeypatch.setattr(module, "MANIFEST", tmp_path / "offline-manifest.json")
    monkeypatch.setattr(module, "git", lambda *args: "offline-registration-commit")
    module.MANIFEST.write_text("{}")
    return module


@pytest.fixture
def manifest(campaign):
    return {
        "campaign_id": campaign.CAMPAIGN_ID, "campaign_root": ".lunar/" + campaign.CAMPAIGN_ID,
        "planned_attempts": 2, "limits": campaign.LIMITS,
        "schedule": [{"index": index, "case_key": key, "attempt_id": f"slot-{index:03d}-attempt-001"}
                     for index, key in enumerate(campaign.CASES, 1)],
        "cases": campaign.CASES, "provider": {"requested_model": "offline-model"},
        "population": {"size": 2, "offspring_per_iteration": 1, "islands": 1,
                       "max_rounds": 1, "stagnation_rounds": 3, "seed": 113},
    }


def process_result(**extra):
    return {"process_status": "exited", "exit_code": 2, "cleanup_verified": True,
            "remaining_observed_pids": [], "elapsed_seconds": 0.01, **extra}


def start_slot(campaign, manifest):
    root = campaign.REPO / manifest["campaign_root"]
    campaign.write_new(root / "started.json", {
        "campaign_id": manifest["campaign_id"], "manifest_sha256": campaign.sha(campaign.MANIFEST),
        "schedule": manifest["schedule"],
    })
    slot = manifest["schedule"][0]
    slot_root = root / slot["attempt_id"]
    campaign.write_new(slot_root / "started.json", {
        **slot, "manifest_sha256": campaign.sha(campaign.MANIFEST),
    })
    return root, slot_root


def load_worker(monkeypatch, campaign, manifest):
    response = load_module("measurement117_response_wrapper", HERE / "response_guard.py")
    monkeypatch.setitem(sys.modules, "response_guard", response)
    worker = load_module("measurement117_worker", HERE / "worker.py")
    monkeypatch.setattr(worker, "verify", lambda **kwargs: manifest)
    return worker


def test_supervisor_routes_new_worker_3600_seconds_once_per_slot(campaign, manifest):
    root = campaign.REPO / manifest["campaign_root"]
    old_root = campaign.REPO / ".lunar/acceptance115-glm-5.2-isolated-intake-20260916"
    old_root.mkdir(parents=True)
    old_marker = old_root / "started.json"
    old_marker.write_text("old campaign must remain unchanged")
    calls = []

    def runner(command, slot_root, wall_seconds):
        assert Path(command[1]) == HERE / "worker.py"
        assert command[0] == sys.executable
        assert slot_root.parent == root
        assert wall_seconds == 3600
        assert (slot_root / "started.json").is_file()
        calls.append(command[-1])
        return process_result()

    result = campaign.run_slots(manifest, root, runner)

    assert result["started_attempts"] == result["planned_attempts"] == 2
    assert calls == ["1", "2"]
    assert old_marker.read_text() == "old campaign must remain unchanged"
    for slot in manifest["schedule"]:
        receipt = json.loads((root / slot["attempt_id"] / "finished.json").read_text())
        assert receipt["exit_code"] == 2
    with pytest.raises(FileExistsError):
        campaign.run_slots(manifest, root, runner)
    assert calls == ["1", "2"]


@pytest.mark.parametrize("outcome", ["unknown_cleanup", "residual", "exception", "interrupt"])
def test_uncertain_first_slot_stops_launch_but_keeps_two_attempt_denominator(
    campaign, manifest, outcome,
):
    root = campaign.REPO / manifest["campaign_root"]
    calls = []

    def runner(*args):
        calls.append(1)
        if outcome == "exception":
            raise OSError("private diagnostic text")
        if outcome == "interrupt":
            raise KeyboardInterrupt()
        return process_result(
            cleanup_verified=False, remaining_observed_pids=[123] if outcome == "residual" else [],
        )

    result = campaign.run_slots(manifest, root, runner)

    assert len(calls) == result["started_attempts"] == 1
    assert result["planned_attempts"] == 2
    assert result["status"] == "stopped_before_remaining_slots"
    assert not (root / manifest["schedule"][1]["attempt_id"]).exists()
    assert "private diagnostic text" not in (root / manifest["schedule"][0]["attempt_id"] / "finished.json").read_text()


@pytest.mark.parametrize("native_fails", [False, True])
def test_worker_uses_registered_limits_and_one_fake_native_call_without_retry(
    campaign, manifest, monkeypatch, capsys, native_fails,
):
    root, slot_root = start_slot(campaign, manifest)
    worker = load_worker(monkeypatch, campaign, manifest)
    shared = campaign.shared_module("runtime_guard")
    provider = shared.ProviderConfiguration("https://offline.invalid/v1", "offline-fixture-key", "offline-model")
    provider_calls, native_calls, cli_calls, guards = [], [], [], []

    def offline_provider(**kwargs):
        provider_calls.append(kwargs)
        return provider

    real_guard = worker.RuntimeGuard

    def guarded(*args, **kwargs):
        assert kwargs["max_requests"] == 16
        assert kwargs["token_stop_threshold"] == 160000
        assert kwargs["request_seconds"] == 600
        assert 3500 < kwargs["wall_seconds"] <= 3600
        guard = real_guard(*args, **kwargs)
        guards.append(guard)
        return guard

    def forbidden(*args, **kwargs):
        pytest.fail("offline worker test attempted real HTTP transport")

    def fake_native(runtime, messages, tools=(), timeout=None):
        native_calls.append((messages, tools, timeout))
        assert runtime.model == "offline-model"
        assert timeout == 600
        assert guards[0].requests == 1
        if native_fails:
            raise TimeoutError("offline provider detail")
        return ModelTurn("offline answer", response_model="offline-model", usage={
            "input_tokens": 3, "output_tokens": 2, "total_tokens": 5,
        })

    def fake_cli(args):
        cli_calls.append(list(args))
        OpenAICompatibleRuntime().complete([{"role": "user", "content": "offline turn"}], timeout=900)
        print(json.dumps({"status": "offline-test-only"}))
        return 2

    monkeypatch.setattr(worker, "load_provider", offline_provider)
    monkeypatch.setattr(worker, "RuntimeGuard", guarded)
    monkeypatch.setattr("famou.runtime.exchange", forbidden)
    monkeypatch.setattr("famou.runtime.urlopen", forbidden)
    monkeypatch.setattr(OpenAICompatibleRuntime, "complete", fake_native)
    monkeypatch.setattr(cli, "main", fake_cli)

    assert worker.main(1) == 2
    with pytest.raises(FileExistsError):
        worker.main(1)

    assert len(provider_calls) == len(cli_calls) == len(native_calls) == len(guards) == 1
    parsed = cli.build_parser().parse_args(cli_calls[0])
    assert parsed.timeout == 600
    assert parsed.max_steps == 4 and parsed.workers == 1
    assert parsed.evolve and parsed.multi_file and parsed.agent_loop
    assert not parsed.allow_exec and not parsed.memory and not parsed.session_history
    assert parsed.population_size == 2 and parsed.offspring_per_iteration == 1
    assert parsed.islands == 1 and parsed.seed == 113
    assert parsed.max_rounds == 1 and parsed.stagnation_rounds == 3
    assert Path(parsed.home) == slot_root / "home"
    assert parsed.workspace == slot_root / "workspace"
    assert {Path(path) for path in parsed.input_files} == {
        slot_root / "inputs" / name
        for name in manifest["cases"][manifest["schedule"][0]["case_key"]]["inputs"]
    }
    assert guards[0].snapshot()["provider_requests"] == 1
    assert not (root / manifest["schedule"][1]["attempt_id"]).exists()
    result = json.loads((slot_root / "worker-finished.json").read_text())
    assert result["status"] == ("worker_failed" if native_fails else "returned")
    assert result["guard"]["usage_complete"] is (not native_fails)
    output = capsys.readouterr().out
    assert provider.api_key not in output and "offline provider detail" not in output


def test_worker_setup_failure_consumes_slot_without_retrying_provider(
    campaign, manifest, monkeypatch, capsys,
):
    _, slot_root = start_slot(campaign, manifest)
    worker = load_worker(monkeypatch, campaign, manifest)
    calls = []

    def unavailable(**kwargs):
        calls.append(1)
        raise RuntimeError("offline private setup detail")

    monkeypatch.setattr(worker, "load_provider", unavailable)
    assert worker.main(1) == 2
    with pytest.raises(FileExistsError):
        worker.main(1)
    assert calls == [1]
    assert "offline private setup detail" not in capsys.readouterr().out
    result = json.loads((slot_root / "worker-finished.json").read_text())
    assert result["guard"] is None and result["status"] == "worker_failed"


@pytest.mark.parametrize("change", ["wrong_campaign", "wrong_slot", "finished_campaign", "finished_slot"])
def test_worker_rejects_bad_markers_before_loading_provider(campaign, manifest, monkeypatch, change):
    root, slot_root = start_slot(campaign, manifest)
    if change in {"wrong_campaign", "wrong_slot"}:
        path = (root if change == "wrong_campaign" else slot_root) / "started.json"
        marker = json.loads(path.read_text())
        marker["campaign_id" if change == "wrong_campaign" else "attempt_id"] = "old-registration"
        path.write_text(json.dumps(marker))
    else:
        campaign.write_new((root if change == "finished_campaign" else slot_root) / "finished.json", {})
    worker = load_worker(monkeypatch, campaign, manifest)

    def forbidden(**kwargs):
        pytest.fail("unregistered slot must not read provider configuration")

    monkeypatch.setattr(worker, "load_provider", forbidden)
    with pytest.raises(ValueError, match="slot_not_started"):
        worker.main(1)
    assert not (slot_root / "worker-started.json").exists()
