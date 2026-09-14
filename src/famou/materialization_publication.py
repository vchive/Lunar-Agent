"""Finish an explicitly prepared terminal result without repeating candidate execution."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .budget import BudgetSpec
from .evolution import (
    EvolutionError,
    _fsync_directory,
    _fsync_directory_chain,
    _read_bounded_regular_file,
    _strict_json_loads,
)
from .models import Run
from .store import Store

MAX_RESULT_BYTES = 64 * 1024
MAX_JOURNAL_BYTES = 4096
MARKER_PATH = "evolution/materialization/result.json"
_INVALID = "materialization_publication_evidence_invalid"
Validator = Callable[[dict[str, Any]], None]


class MaterializationPublicationError(EvolutionError):
    """Retain the prepared result; its terminal publication could not be confirmed."""


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


def _path(root: Path, relative: str) -> Path:
    current = root
    parts = Path(relative).parts
    for index, part in enumerate(parts):
        current = current / part
        if _present(current):
            mode = os.lstat(current).st_mode
            if stat.S_ISLNK(mode) or (index < len(parts) - 1 and not stat.S_ISDIR(mode)):
                raise MaterializationPublicationError(_INVALID)
    return current


def _root(child: Run) -> Path:
    raw = Path(child.workspace).expanduser()
    if raw.is_symlink() or not raw.is_dir():
        raise MaterializationPublicationError(_INVALID)
    return raw.resolve()


def _read(path: Path, limit: int) -> bytes:
    return _read_bounded_regular_file(path, limit, error=_INVALID)


def _sync(directory: Path) -> None:
    _fsync_directory(directory, error="materialization_publication_sync_failed")


def _sync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise MaterializationPublicationError(_INVALID)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_new(path: Path, content: bytes) -> None:
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
    )
    try:
        view = memoryview(content)
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                raise OSError("terminal publication write made no progress")
            view = view[count:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_record(directory: Path, name: str, content: bytes) -> None:
    temporary = directory / ("." + name + ".tmp")
    if _present(temporary):
        if _read(temporary, MAX_JOURNAL_BYTES) != content:
            raise MaterializationPublicationError(_INVALID)
        _sync_file(temporary)
    else:
        _write_new(temporary, content)
    os.link(temporary, directory / name, follow_symlinks=False)
    temporary.unlink()
    _sync(directory)


def _write_complete(directory: Path, journal_digest: str) -> None:
    _write_record(directory, "completed.json", _encode({"journal_sha256": journal_digest}))


@contextmanager
def _locked(root: Path):
    materialization = _path(root, "evolution/materialization")
    if not _present(materialization):
        materialization.mkdir(mode=0o700)
        _sync(materialization.parent)
    if not materialization.is_dir():
        raise MaterializationPublicationError(_INVALID)
    lock = _path(root, "evolution/materialization/.terminal-publication.lock")
    descriptor = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        held = os.fstat(descriptor)
        if not stat.S_ISREG(held.st_mode) or held.st_nlink != 1:
            raise MaterializationPublicationError(_INVALID)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        current = os.lstat(lock)
        if (held.st_dev, held.st_ino) != (current.st_dev, current.st_ino):
            raise MaterializationPublicationError(_INVALID)
        yield
    finally:
        os.close(descriptor)


def _owner(store: Store, child: Run) -> str:
    tasks = store.list_tasks(child.id)
    if len(tasks) != 1:
        raise MaterializationPublicationError(_INVALID)
    return tasks[0].id


def _artifact_id(parent: Run, child: Run) -> str:
    return "artifact-materialization-publication-" + _digest(f"{parent.id}\0{child.id}".encode())


def _load(
    root: Path, parent: Run, child: Run, task_id: str,
) -> tuple[dict[str, Any], bytes, dict[str, Any], str]:
    directory = _path(root, "evolution/materialization/.terminal-publication")
    if not directory.is_dir():
        raise MaterializationPublicationError(_INVALID)
    journal_content = _read(_path(directory, "journal.json"), MAX_JOURNAL_BYTES)
    journal = _strict_json_loads(journal_content)
    expected = {
        "schema_version": "1", "parent_run_id": parent.id, "evolution_run_id": child.id,
        "task_id": task_id, "marker_path": MARKER_PATH, "artifact_id": _artifact_id(parent, child),
    }
    if (not isinstance(journal, dict) or set(journal) != {
        *expected, "marker_sha256", "marker_size", "device", "inode",
    } or any(journal.get(key) != value for key, value in expected.items())
        or _encode(journal) != journal_content
        or any(type(journal[key]) is not int or journal[key] < 0
               for key in ("marker_size", "device", "inode"))
        or journal["marker_size"] > MAX_RESULT_BYTES):
        raise MaterializationPublicationError(_INVALID)
    stage = _path(directory, "result.blob")
    content = _read(stage, MAX_RESULT_BYTES)
    identity = os.lstat(stage)
    if (len(content) != journal["marker_size"] or _digest(content) != journal["marker_sha256"]
        or (identity.st_dev, identity.st_ino) != (journal["device"], journal["inode"])):
        raise MaterializationPublicationError(_INVALID)
    payload = _strict_json_loads(content)
    if not isinstance(payload, dict) or _encode(payload) != content:
        raise MaterializationPublicationError(_INVALID)
    return journal, content, payload, _digest(journal_content)


def _marker_exists(root: Path, journal: dict[str, Any], content: bytes) -> bool:
    marker = _path(root, MARKER_PATH)
    if not _present(marker):
        return False
    identity = os.lstat(marker)
    if (_read(marker, MAX_RESULT_BYTES) != content
        or (identity.st_dev, identity.st_ino) != (journal["device"], journal["inode"])):
        raise MaterializationPublicationError(_INVALID)
    return True


def _completion_state(directory: Path, digest: str) -> str | None:
    expected = _encode({"journal_sha256": digest})
    for name in ("completed.json", ".completed.json.tmp"):
        path = _path(directory, name)
        if _present(path) and _read(path, MAX_JOURNAL_BYTES) != expected:
            raise MaterializationPublicationError(_INVALID)
    if _present(directory / "completed.json"):
        return "completed"
    if _present(directory / ".completed.json.tmp"):
        return "temporary"
    return None


def _status(store: Store, parent: Run, child: Run, task_id: str, payload: dict, digest: str) -> str:
    try:
        return store.materialization_publication_status(
            parent.id, child.id, task_id, payload, journal_sha256=digest,
        )
    except Exception as exc:
        raise MaterializationPublicationError("materialization_publication_commit_unknown") from exc


def _finish(store: Store, parent: Run, child: Run, root: Path, validate: Validator) -> dict[str, Any]:
    task_id = _owner(store, child)
    directory = _path(root, "evolution/materialization/.terminal-publication")
    journal, content, payload, digest = _load(root, parent, child, task_id)
    completion = _completion_state(directory, digest)
    marker_exists = _marker_exists(root, journal, content)
    status = _status(store, parent, child, task_id, payload, digest)
    if status == "absent" or (completion is not None and status != "committed"):
        raise MaterializationPublicationError(_INVALID)
    if status == "committed" and not marker_exists:
        raise MaterializationPublicationError("materialization marker is missing from a recorded attempt")
    # The callback is the controller's full existing contract/candidate/execution/output validator.
    validate(_strict_json_loads(content))
    if _load(root, parent, child, task_id) != (journal, content, payload, digest):
        raise MaterializationPublicationError(_INVALID)
    if _marker_exists(root, journal, content) != marker_exists:
        raise MaterializationPublicationError(_INVALID)
    if _completion_state(directory, digest) != completion:
        raise MaterializationPublicationError(_INVALID)
    if completion == "completed":
        # A prior process may have linked this acknowledgement but exited before directory fsync.
        _sync_file(directory / "completed.json")
        _sync(directory)
        return payload
    if status == "prepared":
        marker = _path(root, MARKER_PATH)
        if not marker_exists:
            os.link(directory / "result.blob", marker, follow_symlinks=False)
        _sync_file(marker)
        _sync(marker.parent)
        if not _marker_exists(root, journal, content):
            raise MaterializationPublicationError(_INVALID)
        validate(_strict_json_loads(content))
        if (_load(root, parent, child, task_id) != (journal, content, payload, digest)
            or not _marker_exists(root, journal, content)
            or _completion_state(directory, digest) is not None):
            raise MaterializationPublicationError(_INVALID)
        try:
            store.commit_materialization_publication(
                parent.id, child.id, task_id, payload, journal_sha256=digest,
                max_artifact_bytes=(child.budget or BudgetSpec()).max_artifact_bytes,
            )
        except Exception as exc:
            if _status(store, parent, child, task_id, payload, digest) != "committed":
                raise MaterializationPublicationError("materialization_publication_not_committed") from exc
    if _status(store, parent, child, task_id, payload, digest) != "committed":
        raise MaterializationPublicationError("materialization_publication_not_committed")
    if (_load(root, parent, child, task_id) != (journal, content, payload, digest)
        or not _marker_exists(root, journal, content)):
        raise MaterializationPublicationError(_INVALID)
    _write_complete(directory, digest)
    return payload


def recover_materialization_result(
    store: Store, parent: Run, child: Run, *, validate: Validator,
) -> dict[str, Any] | None:
    """Resume terminal publication only with exact modern preparation evidence."""
    try:
        root = _root(child)
        directory = _path(root, "evolution/materialization/.terminal-publication")
        if not _present(directory):
            if store.has_materialization_publication(parent.id, child.id):
                raise MaterializationPublicationError(_INVALID)
            return None
        with _locked(root):
            return _finish(store, parent, child, root, validate)
    except EvolutionError:
        raise
    except Exception as exc:
        raise MaterializationPublicationError(_INVALID) from exc


def inspect_materialization_result(
    store: Store, parent: Run, child: Run, *, validate: Validator,
) -> dict[str, Any] | None:
    """Require an intact committed result without repairing any terminal evidence."""
    try:
        root = _root(child)
        directory = _path(root, "evolution/materialization/.terminal-publication")
        if not _present(directory):
            if store.has_materialization_publication(parent.id, child.id):
                raise MaterializationPublicationError(_INVALID)
            return None
        task_id = _owner(store, child)
        journal, content, payload, digest = _load(root, parent, child, task_id)
        _completion_state(directory, digest)
        if (_status(store, parent, child, task_id, payload, digest) != "committed"
            or not _marker_exists(root, journal, content)):
            raise MaterializationPublicationError(_INVALID)
        validate(_strict_json_loads(content))
        return payload
    except EvolutionError:
        raise
    except Exception as exc:
        raise MaterializationPublicationError(_INVALID) from exc


def publish_materialization_result(
    store: Store, parent: Run, child: Run, payload: dict[str, Any], *, validate: Validator,
) -> dict[str, Any]:
    """Prepare, publish and register one immutable terminal result."""
    try:
        content = _encode(payload)
        if len(content) > MAX_RESULT_BYTES:
            raise MaterializationPublicationError(_INVALID)
        validate(_strict_json_loads(content))
        root = _root(child)
        with _locked(root):
            directory = _path(root, "evolution/materialization/.terminal-publication")
            task_id = _owner(store, child)
            if _present(directory):
                if _load(root, parent, child, task_id)[1] != content:
                    raise MaterializationPublicationError(_INVALID)
                return _finish(store, parent, child, root, validate)
            if (store.has_materialization_publication(parent.id, child.id)
                or _present(_path(root, MARKER_PATH))
                or _present(_path(root, "evolution/materialization/.result.json.tmp"))):
                raise MaterializationPublicationError(_INVALID)
            directory.mkdir(mode=0o700)
            _sync(directory.parent)
            stage = directory / "result.blob"
            _write_new(stage, content)
            identity = os.lstat(stage)
            journal = {
                "schema_version": "1", "parent_run_id": parent.id, "evolution_run_id": child.id,
                "task_id": task_id, "marker_path": MARKER_PATH, "marker_sha256": _digest(content),
                "marker_size": len(content), "artifact_id": _artifact_id(parent, child),
                "device": identity.st_dev, "inode": identity.st_ino,
            }
            _sync(directory)
            journal_content = _encode(journal)
            if len(journal_content) > MAX_JOURNAL_BYTES:
                raise MaterializationPublicationError(_INVALID)
            _write_record(directory, "journal.json", journal_content)
            _fsync_directory_chain(directory, root, error="materialization_publication_sync_failed")
            digest = _digest(journal_content)
            try:
                store.prepare_materialization_publication(
                    parent.id, child.id, task_id, _strict_json_loads(content), journal_sha256=digest,
                    max_artifact_bytes=(child.budget or BudgetSpec()).max_artifact_bytes,
                )
            except Exception as exc:
                if _status(store, parent, child, task_id, _strict_json_loads(content), digest) != "prepared":
                    raise MaterializationPublicationError("materialization_publication_not_prepared") from exc
            return _finish(store, parent, child, root, validate)
    except EvolutionError:
        raise
    except Exception as exc:
        raise MaterializationPublicationError(_INVALID) from exc
