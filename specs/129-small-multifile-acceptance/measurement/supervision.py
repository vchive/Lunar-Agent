"""Frozen120 process supervision, with explicit repository/environment arguments."""
from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def clean_environment():
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(Path.home()),
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONHASHSEED": "0",
            "PYTHONIOENCODING": "utf-8", "FAMOU_MAX_RETRIES": "1",
            "FAMOU_RUNTIME_TIMEOUT": "600"}


def process_table():
    rows = subprocess.check_output(["ps", "-axo", "pid=,ppid=,pgid=,stat="], text=True,
                                   timeout=3)
    return {int(a): (int(b), int(c), state)
            for a, b, c, state in (line.split() for line in rows.splitlines())}


def descendants(pid, table):
    result, todo = set(), [pid]
    while todo:
        parent = todo.pop()
        children = {child for child, (ppid, _, _) in table.items() if ppid == parent} - result
        result.update(children)
        todo.extend(children)
    return result


def stop_process_tree(process, observed=None):
    # Retain observed group ownership after a worker exits and its children are reparented.
    # This is bounded best-effort cleanup of observed descendants, not an OS sandbox.
    table = process_table()
    owned = {} if observed is None else dict(observed)
    owned.update({pid: table[pid][1] for pid in descendants(process.pid, table) | {process.pid}
                  if pid in table})
    alive = {pid for pid, group in owned.items()
             if pid in table and table[pid][1] == group and not table[pid][2].startswith("Z")}
    groups = {owned[pid] for pid in alive}
    groups.discard(os.getpgrp())
    for group in groups:
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            pass
    for pid in alive:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=5)
    deadline = time.monotonic() + 1
    while True:
        remaining = process_table()
        live = sorted(pid for pid, group in owned.items() if pid in remaining
                      and remaining[pid][1] == group and not remaining[pid][2].startswith("Z"))
        if not live or time.monotonic() >= deadline:
            return live
        time.sleep(0.02)


def supervise(command, slot_root, wall_seconds):
    started = time.monotonic()
    with (slot_root / "stdout.log").open("xb") as out, (slot_root / "stderr.log").open("xb") as err:
        process = subprocess.Popen(command, cwd=REPO, env=clean_environment(),
                                   stdout=out, stderr=err, start_new_session=True)
        cleanup, observed, error_type = [], {}, None
        deadline = started + wall_seconds
        try:
            while True:
                table = process_table()
                observed.update({pid: table[pid][1]
                                 for pid in descendants(process.pid, table) | {process.pid}
                                 if pid in table})
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    status = "timed_out"
                    break
                try:
                    process.wait(timeout=min(0.2, remaining))
                    status = "exited" if time.monotonic() < deadline else "timed_out"
                    break
                except subprocess.TimeoutExpired:
                    continue
        except BaseException as exc:  # noqa: BLE001 - cleanup is mandatory after interruption
            status = "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "supervisor_failed"
            error_type = type(exc).__name__
        try:
            cleanup = stop_process_tree(process, observed)
            cleanup_verified = not cleanup
        except Exception as exc:  # noqa: BLE001 - unknown cleanup must block the next slot
            cleanup_verified = False
            error_type = type(exc).__name__
            try:
                process.kill()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
        code = process.returncode
    return {"process_status": status, "exit_code": code,
            "elapsed_seconds": time.monotonic() - started, "remaining_observed_pids": cleanup,
            "cleanup_verified": cleanup_verified, "error_type": error_type}
