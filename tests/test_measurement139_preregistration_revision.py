"""The unused 40-minute registration is archived before one 50-minute launch."""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from measurement139_native_support import prepare_worker
from measurement139_support import campaign, feature139

registration = importlib.import_module(f"{feature139.__name__}.registration")
runner = importlib.import_module(f"{feature139.__name__}.runner")
supervision = importlib.import_module(f"{feature139.__name__}.supervision")
ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_NAME = "specs/139-real-multifile-closure/measurement/registrations/unlaunched-40min.json"
ARCHIVE_SHA = "26fb2d8b447fd5f5b848016a55e041c5f273903f610d4b7c39c0bf10613f19f9"


def test_archived_registration_bytes_and_only_authorized_fixed_condition_changes():
    raw = (ROOT / ARCHIVE_NAME).read_bytes()
    assert len(raw) == 30853 and hashlib.sha256(raw).hexdigest() == ARCHIVE_SHA
    old = json.loads(raw)
    revised = registration.fixed_contract()
    expected = {key: copy.deepcopy(old[key]) for key in revised}
    for key in ("registration_id", "campaign_id", "campaign_root"):
        expected[key] += "-50min"
    expected["budgets"]["wall_seconds"] = 3000
    assert revised == expected
    assert revised["attempt_id"] == "attempt-001"
    assert revised["planned_attempts"] == 1 and revised["retries_or_replacements"] == 0
    assert campaign.RequestLedger().wall_seconds == runner.LIMITS["wall_seconds"] == 3000


@pytest.mark.parametrize("field,error", [
    ("registration_id", "duplicate_registration_identity"),
    ("campaign_id", "duplicate_campaign_identity"),
    ("campaign_root", "historical_campaign_root_reuse"),
])
def test_archive_is_in_inventory_and_prior_identity_checks(tmp_path, field, error):
    archived = tmp_path / ARCHIVE_NAME
    archived.parent.mkdir(parents=True)
    archived.write_bytes((ROOT / ARCHIVE_NAME).read_bytes())
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    assert ARCHIVE_NAME in registration._tracked_feature_names(tmp_path)
    assert ARCHIVE_NAME in registration._prior_manifest_names(tmp_path)
    expected = registration.fixed_contract()
    expected[field] = json.loads(archived.read_bytes())[field]

    def forbidden():
        pytest.fail("identity check contacted a provider")

    store = registration.RegistrationRepository(
        repo=tmp_path, manifest_path=tmp_path / "manifest.json", expected_contract=expected,
        measurement_names=lambda: registration._tracked_feature_names(tmp_path),
        historical_names=(ARCHIVE_NAME,),
        prior_manifest_names=lambda: registration._prior_manifest_names(tmp_path),
        provider_probe=forbidden,
    )
    with pytest.raises(registration.RegistrationStoreError, match=error):
        store._assert_unique_identity()
    assert not (tmp_path / "manifest.json").exists()


def test_worker_receives_full_3000_second_runtime_guard_before_offline_native_solve(tmp_path, monkeypatch):
    fixture = prepare_worker(monkeypatch, tmp_path)
    actual_guard = fixture.worker.RuntimeGuard
    seen = []

    def capture(*args, **kwargs):
        seen.append(kwargs["wall_seconds"])
        return actual_guard(*args, **kwargs)

    # Isolate only the worker clock; native request/trace clocks continue normally.
    monkeypatch.setattr(fixture.worker, "time", SimpleNamespace(monotonic=lambda: 100.0))
    monkeypatch.setattr(fixture.worker, "RuntimeGuard", capture)
    assert fixture.worker.main() == 0
    assert seen == [3000.0]
    assert len(fixture.requests) == 5 and len(fixture.result()["holdouts"]) == 8


def test_supervisor_accepts_work_past_2400_and_stops_at_3000_seconds(tmp_path, monkeypatch):
    clock = [0.0]
    wait_times = []

    class Process:
        pid = 10000001
        returncode = None

        def wait(self, timeout):
            wait_times.append((clock[0], timeout))
            clock[0] = [2400.0, 2999.0, 3000.0][len(wait_times) - 1]
            raise subprocess.TimeoutExpired("offline-worker", timeout)

    process = Process()

    def cleanup(observed_process, _observed):
        assert observed_process is process and clock[0] == 3000
        process.returncode = -9
        return []

    monkeypatch.setattr(supervision, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(supervision.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(supervision, "process_table", dict)
    monkeypatch.setattr(supervision, "stop_process_tree", cleanup)
    result = supervision.supervise(["offline-worker"], tmp_path, runner.LIMITS["wall_seconds"])
    assert [started for started, _timeout in wait_times] == [0, 2400, 2999]
    assert result["process_status"] == "timed_out" and result["elapsed_seconds"] == 3000
    assert result["cleanup_verified"] is True and result["remaining_observed_pids"] == []
