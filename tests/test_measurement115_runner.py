"""Offline campaign supervision, immutable attempts, and incomplete evidence accounting."""
from __future__ import annotations

import importlib.util
import json
import os
import signal
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parents[1] / "specs/115-isolated-intake-acceptance/measurement"


@pytest.fixture
def campaign(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(HERE))
    spec = importlib.util.spec_from_file_location("measurement115_campaign_runner", HERE / "campaign.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules, "campaign", module)
    local_here = tmp_path / "specs/115/measurement"
    local_here.mkdir(parents=True)
    monkeypatch.setattr(module, "HERE", local_here)
    monkeypatch.setattr(module, "REPO", tmp_path)
    monkeypatch.setattr(module, "MANIFEST", local_here / "manifest.json")
    monkeypatch.setattr(module, "git", lambda *args: "fixture-commit")
    monkeypatch.setattr(module, "check_fixed_conditions", lambda payload: None)
    original_shared = module.shared_module
    monkeypatch.setattr(module, "shared_module", lambda name:
                        sys.modules[name] if name == "analyze" and name in sys.modules else original_shared(name))
    module.MANIFEST.write_text("{}")
    return module


@pytest.fixture
def manifest(campaign):
    return {
        "campaign_id": "offline-115", "campaign_root": "private/campaign", "product_commit": "fixture",
        "planned_attempts": 2, "limits": campaign.LIMITS,
        "schedule": [{"index": index, "case_key": key, "attempt_id": f"slot-{index:03d}-attempt-001"}
                     for index, key in enumerate(campaign.CASES, 1)],
        "cases": campaign.CASES, "provider": {"requested_model": "fixture-model"},
        "population": {"size": 2, "offspring_per_iteration": 1, "islands": 1,
                       "max_rounds": 1, "stagnation_rounds": 3, "seed": 113},
        "limitations": [],
    }


def process_result(**extra):
    return {"process_status": "exited", "exit_code": 2, "cleanup_verified": True,
            "remaining_observed_pids": [], "elapsed_seconds": 0.01, **extra}


def root_for(campaign, manifest):
    return campaign.REPO / manifest["campaign_root"]


def started(campaign, manifest, *, first=True):
    root = root_for(campaign, manifest)
    campaign.write_new(root / "started.json", {
        "campaign_id": manifest["campaign_id"], "manifest_sha256": campaign.sha(campaign.MANIFEST),
        "schedule": manifest["schedule"],
    })
    if first:
        slot = manifest["schedule"][0]
        campaign.write_new(root / slot["attempt_id"] / "started.json", {
            **slot, "manifest_sha256": campaign.sha(campaign.MANIFEST),
        })
    return root


def completed_usage(index=1):
    return {"kind": "request_finished", "index": index, "outcome": "succeeded",
            "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
            "response_model": "fixture-model"}


def write_journal(path, rows, suffix=""):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows) + suffix)


def stub_analysis(monkeypatch):
    def analyze(*args):
        return {"primary_valid_completion": True,
                "output_check": {"validity": True, "quality": 42}, "quality_gap": 0}
    monkeypatch.setitem(sys.modules, "analyze", SimpleNamespace(analyze_slot=analyze))


@pytest.mark.parametrize("terminal", ["timeout", "normal_exit"])
def test_real_supervisor_cleans_same_group_and_separate_session_children(campaign, tmp_path, terminal):
    slot = tmp_path / "slot"
    slot.mkdir()
    pid_file = slot / "pids.json"
    child_code = "import time; time.sleep(60)"
    script = (
        "import json, os, subprocess, sys, time\n"
        f"one = subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
        f"two = subprocess.Popen([sys.executable, '-c', {child_code!r}], start_new_session=True)\n"
        "open(sys.argv[1], 'w').write(json.dumps([os.getpid(), one.pid, two.pid]))\n"
        f"time.sleep({60 if terminal == 'timeout' else 0.4})\n"
    )
    try:
        result = campaign.supervise([sys.executable, "-c", script, str(pid_file)], slot,
                                    0.65 if terminal == "timeout" else 5)
        assert result["process_status"] == ("timed_out" if terminal == "timeout" else "exited")
        assert result["cleanup_verified"] is True
        assert result["remaining_observed_pids"] == []
        table = campaign.process_table()
        assert pid_file.exists()
        for pid in json.loads(pid_file.read_text()):
            assert pid not in table or table[pid][2].startswith("Z")
        assert result["elapsed_seconds"] < 5
    finally:
        if pid_file.exists():
            for pid in json.loads(pid_file.read_text()):
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def test_exclusive_campaign_preserves_two_failed_slots_and_never_retries(campaign, manifest):
    calls = []

    def runner(command, slot_root, wall_seconds):
        assert json.loads((slot_root / "started.json").read_text())["manifest_sha256"]
        calls.append(command[-1])
        return process_result()

    root = root_for(campaign, manifest)
    result = campaign.run_slots(manifest, root, runner)
    assert result["started_attempts"] == result["planned_attempts"] == 2
    assert calls == ["1", "2"]
    for slot in manifest["schedule"]:
        assert json.loads((root / slot["attempt_id"] / "finished.json").read_text())["exit_code"] == 2
    with pytest.raises(FileExistsError):
        campaign.run_slots(manifest, root, runner)
    assert calls == ["1", "2"]


@pytest.mark.parametrize("outcome", ["residual", "unknown_cleanup", "exception", "interrupt"])
def test_cleanup_uncertainty_or_interruption_stops_later_slots(campaign, manifest, outcome):
    calls = []

    def runner(*args):
        calls.append(1)
        if outcome == "interrupt":
            raise KeyboardInterrupt()
        if outcome == "exception":
            raise OSError("private error text")
        if outcome == "residual":
            return process_result(remaining_observed_pids=[123], cleanup_verified=False)
        return process_result(cleanup_verified=False)

    root = root_for(campaign, manifest)
    result = campaign.run_slots(manifest, root, runner)
    assert len(calls) == result["started_attempts"] == 1
    assert result["planned_attempts"] == 2
    assert result["status"] == "stopped_before_remaining_slots"
    assert not (root / manifest["schedule"][1]["attempt_id"]).exists()
    assert (root / "finished.json").exists()
    assert "private error text" not in (root / manifest["schedule"][0]["attempt_id"] / "finished.json").read_text()


def test_abruptly_interrupted_campaign_summary_keeps_all_planned_failures(
    campaign, manifest, monkeypatch,
):
    stub_analysis(monkeypatch)
    root = started(campaign, manifest)
    slot_root = root / manifest["schedule"][0]["attempt_id"]
    write_journal(slot_root / "calls.jsonl", [
        {"kind": "request_started", "index": 1}, completed_usage(),
        {"kind": "request_started", "index": 2},
    ], suffix='{"kind":"request_finished"')
    summary = campaign.summarize(manifest)
    result = json.loads(Path(summary["results"]).read_text())
    assert result["planned_attempts"] == len(result["slots"]) == 2
    assert result["valid_completions"] == result["registered_valid_completions"] == 0
    assert result["campaign_finished"] is False
    first, second = result["slots"]
    assert first["process"]["process_status"] == "interrupted_or_unfinished"
    assert first["usage"]["known_usage"]["total_tokens"] == 5
    assert first["usage"]["provider_requests"] == 2
    assert first["usage"]["pending_requests"] == [2]
    assert first["usage"]["usage_complete"] is False
    assert first["usage"]["journal_malformed"] is True
    assert first["output_check"]["quality"] == 42
    assert first["quality"] is None and first["quality_gap"] is None
    assert second["process"]["process_status"] == "not_started"
    assert second["usage"]["provider_requests"] == 0


@pytest.mark.parametrize("violation", ["unknown_usage", "guard_stop", "timeout", "none"])
def test_delivery_and_registered_envelope_have_distinct_outcomes(campaign, manifest, monkeypatch, violation):
    stub_analysis(monkeypatch)
    root = started(campaign, manifest)
    slot_root = root / manifest["schedule"][0]["attempt_id"]
    usage = completed_usage()
    if violation == "unknown_usage":
        usage.update(usage=None, outcome="provider_error")
    write_journal(slot_root / "calls.jsonl", [{"kind": "request_started", "index": 1}, usage])
    known = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0} if violation == "unknown_usage" else usage["usage"]
    campaign.write_new(slot_root / "worker-finished.json", {
        "status": "returned", "exit_code": 0,
        "guard": {"provider_requests": 1, "finished_requests": 1, "known_usage": known,
                  "usage_complete": violation != "unknown_usage",
                  "stopped_reason": "request_limit_reached" if violation == "guard_stop" else None},
    })
    campaign.write_new(slot_root / "finished.json", process_result(
        exit_code=0, process_status="timed_out" if violation == "timeout" else "exited",
    ))
    result = json.loads(Path(campaign.summarize(manifest)["results"]).read_text())
    first = result["slots"][0]
    assert first["delivery_completion"] is True
    assert first["primary_valid_completion"] is (violation != "timeout")
    assert first["registered_valid_completion"] is (violation == "none")
    assert first["measurement_envelope_verified"] is (violation == "none")


def test_usage_summary_keeps_known_prefix_and_rejects_duplicate_or_malformed_counters(campaign, tmp_path):
    path = tmp_path / "journal.jsonl"
    write_journal(path, [
        {"kind": "request_started", "index": 1}, completed_usage(), completed_usage(),
        {"kind": "request_started", "index": 2},
        {"kind": "request_finished", "index": 2, "usage": {"total_tokens": 100}},
        ["not-an-object"],
    ])
    summary = campaign.usage_summary(path)
    assert summary["known_usage"]["total_tokens"] == 5
    assert summary["provider_requests"] == summary["finished_requests"] == 2
    assert summary["usage_complete"] is False and summary["journal_malformed"] is True


def load_worker(monkeypatch, campaign):
    spec = importlib.util.spec_from_file_location("measurement115_worker_runner", HERE / "worker.py")
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    return worker


def test_worker_claim_is_exclusive_and_setup_failure_never_retries_credentials(
    campaign, manifest, monkeypatch, capsys,
):
    started(campaign, manifest)
    worker = load_worker(monkeypatch, campaign)
    monkeypatch.setattr(worker, "verify", lambda **kwargs: manifest)
    calls = []

    def unavailable(**kwargs):
        calls.append(1)
        raise RuntimeError("credential-private-error")

    monkeypatch.setattr(worker, "load_provider", unavailable)
    assert worker.main(1) == 2
    with pytest.raises(FileExistsError):
        worker.main(1)
    assert calls == [1]
    assert "credential-private-error" not in capsys.readouterr().out
    result = json.loads((root_for(campaign, manifest) / manifest["schedule"][0]["attempt_id"] /
                         "worker-finished.json").read_text())
    assert result["status"] == "worker_failed" and result["guard"] is None


@pytest.mark.parametrize("change", ["wrong_case", "finished_campaign", "finished_slot"])
def test_worker_rejects_invalid_slot_marker_before_credentials(campaign, manifest, monkeypatch, change):
    root = started(campaign, manifest)
    slot_root = root / manifest["schedule"][0]["attempt_id"]
    if change == "wrong_case":
        marker = json.loads((slot_root / "started.json").read_text())
        marker["case_key"] = "other-case"
        (slot_root / "started.json").write_text(json.dumps(marker))
    else:
        campaign.write_new((root if change == "finished_campaign" else slot_root) / "finished.json", {})
    worker = load_worker(monkeypatch, campaign)
    monkeypatch.setattr(worker, "verify", lambda **kwargs: manifest)

    def forbidden(**kwargs):
        raise AssertionError("credentials must not be loaded")

    monkeypatch.setattr(worker, "load_provider", forbidden)
    with pytest.raises(ValueError, match="slot_not_started"):
        worker.main(1)
    assert not (slot_root / "worker-started.json").exists()


def verification_fixture(campaign, monkeypatch):
    product = ["src/famou/__init__.py", "pyproject.toml"]
    measured = ["specs/115/measurement/campaign.py"]
    for relative in product + measured:
        target = campaign.REPO / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# frozen fixture\n")
    manifest = {"product_files": campaign.file_pins([campaign.REPO / p for p in product]),
                "measurement_files": campaign.file_pins([campaign.REPO / p for p in measured]),
                "historical_files": {},
                "runtime": {"fixture": True}, "cases": campaign.CASES,
                "holdouts": {key: campaign.holdouts(key) for key in campaign.CASES}}
    campaign.MANIFEST.write_text(json.dumps(manifest))
    monkeypatch.setattr(campaign, "runtime_identity", lambda: {"fixture": True})
    monkeypatch.setattr(campaign, "git", lambda *args: "\n".join(product) if args[0] == "ls-files" else "commit")
    blobs = {relative: (campaign.REPO / relative).read_bytes() for relative in product + measured}
    blobs[campaign.MANIFEST.relative_to(campaign.REPO).as_posix()] = campaign.MANIFEST.read_bytes()
    monkeypatch.setattr(campaign.subprocess, "check_output", lambda command, **kwargs:
                        blobs[command[-1].removeprefix("HEAD:")])
    return blobs


def test_verify_requires_each_pinned_source_committed_not_only_manifest(campaign, monkeypatch):
    blobs = verification_fixture(campaign, monkeypatch)
    campaign.verify(committed=True)
    blobs["specs/115/measurement/campaign.py"] = b"previous committed bytes"
    with pytest.raises(ValueError, match="registered_file_not_committed"):
        campaign.verify(committed=True)


def test_verify_rejects_added_unpinned_product_module(campaign, monkeypatch):
    verification_fixture(campaign, monkeypatch)
    (campaign.REPO / "src/famou/unpinned.py").write_text("# additional importable source\n")
    with pytest.raises(ValueError, match="product_file_set_changed"):
        campaign.verify()
