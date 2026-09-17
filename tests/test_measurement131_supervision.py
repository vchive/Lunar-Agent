"""Actual process cleanup and explicit child runtime defaults, without providers."""
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1] / "specs/131-small-multifile-recheck/measurement"
spec = importlib.util.spec_from_file_location("measurement131_supervision_test", HERE / "supervision.py")
supervision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(supervision)

def test_supervisor_scrubs_ambient_secrets_and_runtime_settings(monkeypatch):
    for key in ("OPENAI_API_KEY", "FAMOU_API_KEY", "FAMOU_MODEL", "FAMOU_RUNTIME_TIMEOUT",
                "FAMOU_MAX_RETRIES", "PYTHONPATH", "HTTPS_PROXY", "UNRELATED_SECRET"):
        monkeypatch.setenv(key, "private-ambient-value")
    environment = supervision.clean_environment()
    assert set(environment) == {"PATH", "HOME", "LANG", "LC_ALL", "PYTHONHASHSEED", "PYTHONIOENCODING",
                                "FAMOU_MAX_RETRIES", "FAMOU_RUNTIME_TIMEOUT"}
    assert environment["FAMOU_MAX_RETRIES"] == "1"
    assert environment["FAMOU_RUNTIME_TIMEOUT"] == "600"
    assert "private-ambient-value" not in json.dumps(environment)


def test_supervisor_short_local_deadline_reaps_worker_and_observed_child(tmp_path):
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


def test_supervisor_local_success_preserves_output_and_proves_cleanup(tmp_path):
    slot = tmp_path / "supervised-success"
    slot.mkdir()
    result = supervision.supervise([sys.executable, "-c", "print('offline-success')"], slot, 3)
    assert result["process_status"] == "exited" and result["exit_code"] == 0
    assert result["cleanup_verified"] is True and result["remaining_observed_pids"] == []
    assert (slot / "stdout.log").read_text() == "offline-success\n"
    assert (slot / "stderr.log").read_bytes() == b""
