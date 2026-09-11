"""Bounded local macOS assertion smoke; no model, network, sleep or permanent settings.

Run from the repository with:
  .venv/bin/python specs/083-host-execution-guard/validation/native-smoke.py --output NEW_JSON

The process-exit scenario uses os._exit(0), not a crash or SIGKILL. The query examines only the
owned test child's fixed assertion name/type; no raw system assertion inventory is persisted.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import selectors
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from famou.host_awake import MacOSIdleSleepAssertion, _IOKitAPI


def require(condition):
    if not condition:
        raise ValueError("native_smoke_failed")


def normal_and_exceptional():
    outcomes = []
    for exceptional in (False, True):
        guard = MacOSIdleSleepAssertion()
        acquired = None
        try:
            acquired = guard.acquire()
            require(guard.verify() == acquired)
            if exceptional:
                raise RuntimeError("fixed_validation_exception")
        except RuntimeError:
            require(exceptional)
        finally:
            guard.release()
        require(acquired is not None)
        raw = guard._api.io.IOPMAssertionCopyProperties(acquired["assertion_id"])
        absent = not raw
        if raw:
            guard._api.cf.CFRelease(raw)
        require(absent)
        guard.release()
        outcomes.append({
            "exceptional_body": exceptional, "acquired_verified": True,
            "queried_after_release_absent": absent,
        })
    return outcomes


def process_exit():
    api = _IOKitAPI()
    pointer = ctypes.c_void_p
    api._bind(api.io, "IOPMCopyAssertionsByProcess", ctypes.c_int32, [ctypes.POINTER(pointer)])
    api._bind(api.cf, "CFNumberCreate", pointer, [pointer, ctypes.c_long, pointer])
    api._bind(api.cf, "CFArrayGetTypeID", ctypes.c_ulong, [])
    api._bind(api.cf, "CFArrayGetCount", ctypes.c_long, [pointer])
    api._bind(api.cf, "CFArrayGetValueAtIndex", pointer, [pointer, ctypes.c_long])

    def owned_count(pid):
        with api._resources() as owned:
            dictionary = pointer()
            status = api.io.IOPMCopyAssertionsByProcess(ctypes.byref(dictionary))
            require(status == 0 and dictionary.value)
            owned.append(dictionary.value)
            require(api.cf.CFGetTypeID(dictionary.value) == api.cf.CFDictionaryGetTypeID())
            number = ctypes.c_int32(pid)
            key = api.cf.CFNumberCreate(None, 3, ctypes.byref(number))
            require(key)
            owned.append(key)
            entries = api.cf.CFDictionaryGetValue(dictionary.value, key)
            if not entries:
                return 0
            require(api.cf.CFGetTypeID(entries) == api.cf.CFArrayGetTypeID())
            type_key = api._string("AssertType", owned)
            name_key = api._string("AssertName", owned)
            level_key = api._string("AssertLevel", owned)
            expected_type = api._string("PreventUserIdleSystemSleep", owned)
            expected_name = api._string("Lunar Agent evaluation", owned)
            matched = 0
            count = api.cf.CFArrayGetCount(entries)
            require(0 <= count <= 16)
            for index in range(count):
                item = api.cf.CFArrayGetValueAtIndex(entries, index)
                require(item and api.cf.CFGetTypeID(item) == api.cf.CFDictionaryGetTypeID())
                kind = api.cf.CFDictionaryGetValue(item, type_key)
                name = api.cf.CFDictionaryGetValue(item, name_key)
                level = api.cf.CFDictionaryGetValue(item, level_key)
                value = ctypes.c_int32()
                if (kind and name and level and api.cf.CFEqual(kind, expected_type)
                        and api.cf.CFEqual(name, expected_name)
                        and api.cf.CFGetTypeID(level) == api.cf.CFNumberGetTypeID()
                        and api.cf.CFNumberGetValue(level, 3, ctypes.byref(value))
                        and value.value == 255):
                    matched += 1
            return matched

    source = """import json, os, sys
from famou.host_awake import MacOSIdleSleepAssertion
guard = MacOSIdleSleepAssertion()
print(json.dumps(guard.acquire()), flush=True)
sys.stdin.buffer.read(1)
os._exit(0)
"""
    child = subprocess.Popen(
        [sys.executable, "-u", "-c", source], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    try:
        with selectors.DefaultSelector() as watcher:
            watcher.register(child.stdout, selectors.EVENT_READ)
            require(watcher.select(5))
        evidence = json.loads(child.stdout.readline(4096))
        require(evidence["owner_pid"] == child.pid and evidence["verified"] is True)
        before = owned_count(child.pid)
        require(before == 1)
        child.stdin.write(b"x")
        child.stdin.flush()
        require(child.wait(timeout=5) == 0)
        after = owned_count(child.pid)
        for _ in range(20):
            if after == 0:
                break
            time.sleep(0.05)
            after = owned_count(child.pid)
        require(after == 0)
        return {
            "child_pid": child.pid, "active_owned_assertions_before": before,
            "active_owned_assertions_after": after, "exit_method": "os._exit(0)",
            "exit_without_python_cleanup": True, "process_reaped": True,
        }
    finally:
        if child.poll() is None:
            child.kill()
        child.wait()
        child.stdin.close()
        child.stdout.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(sys.platform == "darwin" and not args.output.exists())
    repository = Path(__file__).resolve().parents[3]
    report = {
        "schema_version": "1", "kind": "feature083_native_assertion_smoke",
        "started_utc": datetime.now(UTC).isoformat(), "owner_pid": os.getpid(),
        "source_sha256": {
            path: hashlib.sha256((repository / path).read_bytes()).hexdigest()
            for path in (
                "src/famou/host_awake.py", "tests/test_host_awake.py",
                "specs/083-host-execution-guard/validation/native-smoke.py",
            )
        },
        "scoped_release": normal_and_exceptional(),
        "process_exit": process_exit(),
        "model_calls": 0, "network_calls": 0, "system_sleep_requested": False,
        "permanent_settings_changed": False, "raw_system_inventory_saved": False,
        "limitations": [
            "Point-in-time assertion properties do not prove uninterrupted wakefulness.",
            "Process-exit evidence is from ordinary os._exit(0) on this local macOS host.",
            "This is not a SIGKILL, crash, lid-close, low-battery or system-sleep test.",
            "Local cleanup evidence is not a cross-platform or all-failure-mode guarantee.",
        ],
        "completed_utc": datetime.now(UTC).isoformat(),
        "passed": True,
    }
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"passed": True, "output": str(args.output)}, sort_keys=True))


if __name__ == "__main__":
    main()
