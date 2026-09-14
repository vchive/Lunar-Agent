"""Durable, non-replayable authorization for one final materialization runner entry."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .evolution import (
    MAX_SOURCE_BYTES,
    MIN_PROCESS_TIMEOUT_SECONDS,
    CommandCandidateRunner,
    EvolutionError,
    _fsync_directory,
    _fsync_directory_chain,
    _read_bounded_regular_file,
    _strict_json_loads,
)
from .models import Run
from .store import Store

MAX_INTENT_BYTES = 8192
INTENT_PATH = "evolution/materialization/launch-intent.json"
_TEMP_PATH = "evolution/materialization/.launch-intent.json.tmp"
_INVALID = "materialization_launch_evidence_invalid"


class MaterializationLaunchUncertain(EvolutionError):
    """Preserve the attempt; launch evidence cannot authorize a new execution."""


class MaterializationBusy(EvolutionError):
    """Another process currently owns this child's materialization lifecycle."""


def _encode(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            + "\n").encode("utf-8")


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _present(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    return True


def _root(child: Run) -> Path:
    path = Path(child.workspace).expanduser()
    if path.is_symlink() or not path.is_dir():
        raise MaterializationLaunchUncertain(_INVALID)
    return path.resolve()


def _path(root: Path, relative: str) -> Path:
    relative_path = Path(relative)
    if (relative_path.is_absolute() or relative_path.as_posix() != relative
        or not relative_path.parts or any(p in {".", ".."} for p in relative_path.parts)):
        raise MaterializationLaunchUncertain(_INVALID)
    current = root
    for index, part in enumerate(relative_path.parts):
        current = current / part
        if _present(current):
            mode = os.lstat(current).st_mode
            if stat.S_ISLNK(mode) or (index < len(relative_path.parts) - 1 and not stat.S_ISDIR(mode)):
                raise MaterializationLaunchUncertain(_INVALID)
    return current


def _read(path: Path, limit: int) -> bytes:
    return _read_bounded_regular_file(path, limit, error=_INVALID)


def _sync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise MaterializationLaunchUncertain(_INVALID)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def materialization_lock(child: Run):
    """Fail promptly on contention; never wait for a potentially long-running candidate."""
    try:
        root = _root(child)
        lock = _path(root, "evolution/.materialization.lock")
        descriptor = os.open(
            lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, 0o600,
        )
    except Exception as exc:
        raise MaterializationLaunchUncertain(_INVALID) from exc
    try:
        held = os.fstat(descriptor)
        if not stat.S_ISREG(held.st_mode) or held.st_nlink != 1:
            raise MaterializationLaunchUncertain(_INVALID)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise MaterializationBusy("materialization_already_running") from exc
        current = os.lstat(lock)
        if (held.st_dev, held.st_ino) != (current.st_dev, current.st_ino):
            raise MaterializationLaunchUncertain(_INVALID)
        yield
    finally:
        os.close(descriptor)


def _verify_source(root: Path, identity: dict[str, Any]) -> Path:
    source = _path(root, identity["attempt_path"] + "/candidate.py")
    if _digest(_read(source, MAX_SOURCE_BYTES)) != identity["candidate_sha256"]:
        raise MaterializationLaunchUncertain(_INVALID)
    return source


def inspect_launch_intent(
    store: Store, child: Run, identity: dict[str, Any],
) -> dict[str, Any] | None:
    """Observe exact intent; this function never grants permission to run a candidate."""
    try:
        root = _root(child)
        path, temporary = _path(root, INTENT_PATH), _path(root, _TEMP_PATH)
        if not _present(path):
            if _present(temporary) or store.has_materialization_launch_intent(
                identity["parent_run_id"], child.id,
            ):
                raise MaterializationLaunchUncertain(_INVALID)
            return None
        content = _read(path, MAX_INTENT_BYTES)
        value = _strict_json_loads(content)
        if (not isinstance(value, dict) or set(value) != {*identity, "runner_sha256", "timeout_seconds"}
            or any(value.get(key) != expected for key, expected in identity.items())
            or _encode(value) != content or not isinstance(value["runner_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["runner_sha256"])
            or type(value["timeout_seconds"]) not in {int, float}
            or not math.isfinite(value["timeout_seconds"])
            or not 0 < value["timeout_seconds"] <= 86400):
            raise MaterializationLaunchUncertain(_INVALID)
        if _present(temporary) and _read(temporary, MAX_INTENT_BYTES) != content:
            raise MaterializationLaunchUncertain(_INVALID)
        if not store.materialization_launch_intent_recorded(
            identity["parent_run_id"], child.id, identity["task_id"], value,
        ):
            raise MaterializationLaunchUncertain(_INVALID)
        _verify_source(root, identity)
        return value
    except MaterializationLaunchUncertain:
        raise
    except Exception as exc:
        raise MaterializationLaunchUncertain(_INVALID) from exc


def _write_intent(root: Path, content: bytes) -> None:
    path, temporary = _path(root, INTENT_PATH), _path(root, _TEMP_PATH)
    descriptor = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600,
    )
    try:
        # Even a partial file identifies a preparation that must not be silently cleaned up.
        _fsync_directory(path.parent, error="materialization_launch_sync_failed")
        view = memoryview(content)
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                raise OSError("launch intent write made no progress")
            view = view[count:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.link(temporary, path, follow_symlinks=False)
    temporary.unlink()
    _fsync_directory_chain(path.parent, root, error="materialization_launch_sync_failed")


def prepare_launch_intent(
    store: Store, child: Run, identity: dict[str, Any], runner: CommandCandidateRunner,
) -> None:
    """Authorize only this first caller, which must hold the lifecycle lock through execution."""
    try:
        if inspect_launch_intent(store, child, identity) is not None:
            raise MaterializationLaunchUncertain("materialization_launch_already_intended")
        root = _root(child)
        source = _verify_source(root, identity)
        _sync_file(source)
        _fsync_directory_chain(source.parent, root, error="materialization_launch_sync_failed")
        intent = {
            **identity,
            "runner_sha256": _digest(_encode({
                "command": list(runner.command), "environment": runner.environment,
                "max_output_bytes": runner.max_output_bytes,
            })),
            "timeout_seconds": max(float(runner.timeout_seconds), MIN_PROCESS_TIMEOUT_SECONDS),
        }
        content = _encode(intent)
        if len(content) > MAX_INTENT_BYTES:
            raise MaterializationLaunchUncertain(_INVALID)
        _write_intent(root, content)
        try:
            store.record_materialization_launch_intent(
                identity["parent_run_id"], child.id, identity["task_id"], intent,
            )
        except Exception as exc:
            if not store.materialization_launch_intent_recorded(
                identity["parent_run_id"], child.id, identity["task_id"], intent,
            ):
                raise MaterializationLaunchUncertain("materialization_launch_commit_unknown") from exc
        if inspect_launch_intent(store, child, identity) != intent:
            raise MaterializationLaunchUncertain(_INVALID)
    except MaterializationLaunchUncertain:
        raise
    except Exception as exc:
        raise MaterializationLaunchUncertain(_INVALID) from exc
