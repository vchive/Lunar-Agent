"""Bound one Feature 139 worker and prove best-effort process-tree cleanup."""
from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def clean_environment() -> dict[str, str]:
    """Return the complete allow-listed environment for the child worker."""
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(Path.home()),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONHASHSEED": "0",
        "PYTHONIOENCODING": "utf-8",
        "FAMOU_MAX_RETRIES": "1",
        "FAMOU_RUNTIME_TIMEOUT": "600",
    }


def process_table() -> dict[int, tuple[int, int, str]]:
    rows = subprocess.check_output(
        ["ps", "-axo", "pid=,ppid=,pgid=,stat="], text=True, timeout=3,
    )
    return {
        int(pid): (int(ppid), int(pgid), state)
        for pid, ppid, pgid, state in (line.split() for line in rows.splitlines())
    }


def descendants(pid: int, table: dict[int, tuple[int, int, str]]) -> set[int]:
    result: set[int] = set()
    pending = [pid]
    while pending:
        parent = pending.pop()
        children = {
            child for child, (ppid, _, _) in table.items()
            if ppid == parent
        } - result
        result.update(children)
        pending.extend(children)
    return result


def stop_process_tree(
    process: subprocess.Popen[bytes],
    observed: dict[int, int] | None = None,
) -> list[int]:
    """Kill only observed PID/group pairs and report any survivors."""
    table = process_table()
    owned = {} if observed is None else dict(observed)
    owned.update({
        pid: table[pid][1]
        for pid in descendants(process.pid, table) | {process.pid}
        if pid in table
    })
    alive = {
        pid for pid, group in owned.items()
        if pid in table and table[pid][1] == group and not table[pid][2].startswith("Z")
    }
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
        live = sorted(
            pid for pid, group in owned.items()
            if pid in remaining and remaining[pid][1] == group
            and not remaining[pid][2].startswith("Z")
        )
        if not live or time.monotonic() >= deadline:
            return live
        time.sleep(0.02)


def supervise(command: list[str], slot_root: Path, wall_seconds: float) -> dict[str, object]:
    """Run one worker in its own session and always attempt bounded cleanup."""
    if (type(command) is not list or not command
            or any(type(part) is not str or not part for part in command)
            or type(wall_seconds) not in (int, float) or wall_seconds <= 0
            or slot_root.is_symlink() or not slot_root.is_dir()):
        raise ValueError("invalid_supervision_request")
    started = time.monotonic()
    with (slot_root / "stdout.log").open("xb") as stdout, (
        slot_root / "stderr.log"
    ).open("xb") as stderr:
        process = subprocess.Popen(
            command,
            cwd=REPO,
            env=clean_environment(),
            stdout=stdout,
            stderr=stderr,
            start_new_session=True,
        )
        observed: dict[int, int] = {}
        remaining_pids: list[int] = []
        error_type = None
        deadline = started + wall_seconds
        try:
            while True:
                table = process_table()
                observed.update({
                    pid: table[pid][1]
                    for pid in descendants(process.pid, table) | {process.pid}
                    if pid in table
                })
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
        except BaseException as exc:  # noqa: BLE001 - cleanup remains mandatory
            status = (
                "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit))
                else "supervisor_failed"
            )
            error_type = type(exc).__name__
        try:
            remaining_pids = stop_process_tree(process, observed)
            cleanup_verified = not remaining_pids
        except Exception as exc:  # noqa: BLE001 - unknown cleanup blocks success
            cleanup_verified = False
            error_type = type(exc).__name__
            try:
                process.kill()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
        exit_code = process.returncode
    return {
        "process_status": status,
        "exit_code": exit_code,
        "elapsed_seconds": max(0.0, time.monotonic() - started),
        "remaining_observed_pids": remaining_pids,
        "cleanup_verified": cleanup_verified,
        "error_type": error_type,
    }
