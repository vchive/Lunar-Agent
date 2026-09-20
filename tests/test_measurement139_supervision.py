"""Offline process supervision checks for the one Feature 139 slot."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

HERE = (
    Path(__file__).resolve().parents[1]
    / "specs/139-real-multifile-closure/measurement"
)
SPEC = importlib.util.spec_from_file_location(
    "measurement139_supervision_test", HERE / "supervision.py",
)
assert SPEC is not None and SPEC.loader is not None
supervision = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(supervision)


def test_clean_environment_drops_ambient_credentials_and_overrides(monkeypatch):
    for key in (
        "OPENAI_API_KEY", "FAMOU_API_KEY", "FAMOU_MODEL", "PYTHONPATH",
        "HTTPS_PROXY", "UNRELATED_SECRET", "FAMOU_RUNTIME_TIMEOUT",
    ):
        monkeypatch.setenv(key, "private-ambient-value")
    environment = supervision.clean_environment()
    assert set(environment) == {
        "PATH", "HOME", "LANG", "LC_ALL", "PYTHONHASHSEED", "PYTHONIOENCODING",
        "FAMOU_MAX_RETRIES", "FAMOU_RUNTIME_TIMEOUT",
    }
    assert environment["FAMOU_MAX_RETRIES"] == "1"
    assert environment["FAMOU_RUNTIME_TIMEOUT"] == "600"
    assert "private-ambient-value" not in json.dumps(environment)


def test_short_deadline_reaps_worker_and_observed_child(tmp_path):
    slot = tmp_path / "slot"
    slot.mkdir()
    pids = slot / "pids.json"
    program = (
        "import json,os,subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
        "open(sys.argv[1],'w').write(json.dumps([os.getpid(),child.pid])); "
        "time.sleep(60)"
    )
    started = time.monotonic()
    result = supervision.supervise(
        [sys.executable, "-c", program, str(pids)], slot, 0.8,
    )
    assert result["process_status"] == "timed_out"
    assert result["exit_code"] is not None
    assert result["cleanup_verified"] is True
    assert result["remaining_observed_pids"] == []
    assert time.monotonic() - started < 6
    observed = json.loads(pids.read_text())
    table = supervision.process_table()
    assert all(pid not in table or table[pid][2].startswith("Z") for pid in observed)
    assert os.getpid() not in observed


def test_success_preserves_output_and_proves_cleanup(tmp_path):
    slot = tmp_path / "slot"
    slot.mkdir()
    result = supervision.supervise(
        [sys.executable, "-c", "print('offline-success')"], slot, 3,
    )
    assert result["process_status"] == "exited"
    assert result["exit_code"] == 0
    assert result["cleanup_verified"] is True
    assert result["remaining_observed_pids"] == []
    assert (slot / "stdout.log").read_text() == "offline-success\n"
    assert (slot / "stderr.log").read_bytes() == b""


def test_invalid_or_reused_slot_is_rejected_before_launch(tmp_path):
    missing = tmp_path / "missing"
    for slot, command in (
        (missing, [sys.executable, "-c", "pass"]),
        (tmp_path, []),
    ):
        try:
            supervision.supervise(command, slot, 1)
        except ValueError as exc:
            assert str(exc) == "invalid_supervision_request"
        else:
            raise AssertionError("invalid supervision request was accepted")

    slot = tmp_path / "slot"
    slot.mkdir()
    (slot / "stdout.log").write_text("occupied")
    try:
        supervision.supervise([sys.executable, "-c", "pass"], slot, 1)
    except FileExistsError:
        pass
    else:
        raise AssertionError("a consumed output slot was reused")
