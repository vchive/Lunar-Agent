"""Reconcile explicitly prepared execution registration without invoking a candidate.

Callers hold the Feature 090 materialization lifecycle lock throughout these operations.
A returned runner result or explicit local operator receipt may initiate preparation.
Automatic recovery never creates preparation from raw execution evidence.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from .budget import BudgetSpec
from .evolution import (
    MAX_STATE_BYTES,
    CandidateExecution,
    EvolutionError,
    _fsync_directory,
    _fsync_directory_chain,
    _read_bounded_regular_file,
    _strict_json_loads,
)
from .materialization_launch import inspect_launch_intent
from .models import Run
from .store import Store

DIRECTORY = "evolution/materialization/.execution-publication"
MAX_JOURNAL_BYTES = 24 * 1024
_INVALID = "materialization_execution_evidence_invalid"


class MaterializationExecutionUncertain(EvolutionError):
    """Retain execution evidence; no terminal failure may replace unknown registration."""


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


def _root(run: Run) -> Path:
    raw = Path(run.workspace).expanduser()
    if raw.is_symlink() or not raw.is_dir():
        raise MaterializationExecutionUncertain(_INVALID)
    return raw.resolve()


def _path(root: Path, relative: str) -> Path:
    path = Path(relative)
    if (path.is_absolute() or path.as_posix() != relative or not path.parts
        or any(part in {".", ".."} for part in path.parts)):
        raise MaterializationExecutionUncertain(_INVALID)
    current = root
    for index, part in enumerate(path.parts):
        current = current / part
        if _present(current):
            mode = os.lstat(current).st_mode
            if stat.S_ISLNK(mode) or (index < len(path.parts) - 1 and not stat.S_ISDIR(mode)):
                raise MaterializationExecutionUncertain(_INVALID)
    return current


def _read(path: Path, maximum: int) -> bytes:
    return _read_bounded_regular_file(path, maximum, error=_INVALID)


def _sync(directory: Path) -> None:
    _fsync_directory(directory, error="materialization_execution_sync_failed")


def _sync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise MaterializationExecutionUncertain(_INVALID)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_record(directory: Path, name: str, content: bytes) -> None:
    temporary = _path(directory, "." + name + ".tmp")
    if _present(temporary):
        if _read(temporary, MAX_JOURNAL_BYTES) != content:
            raise MaterializationExecutionUncertain(_INVALID)
        _sync_file(temporary)
    else:
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600,
        )
        try:
            _sync(directory)
            view = memoryview(content)
            while view:
                count = os.write(descriptor, view)
                if count <= 0:
                    raise OSError("execution publication write made no progress")
                view = view[count:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    os.link(temporary, _path(directory, name), follow_symlinks=False)
    temporary.unlink()
    _sync(directory)


def _write_complete(directory: Path, digest: str) -> None:
    _write_record(directory, "completed.json", _encode({"journal_sha256": digest}))


def _completion(directory: Path, digest: str) -> str | None:
    expected = _encode({"journal_sha256": digest})
    found: list[str] = []
    for name in ("completed.json", ".completed.json.tmp"):
        path = _path(directory, name)
        if _present(path):
            if _read(path, MAX_JOURNAL_BYTES) != expected:
                raise MaterializationExecutionUncertain(_INVALID)
            found.append(name)
    return found[0] if found else None


def _execution(root: Path, identity: dict[str, Any]) -> tuple[CandidateExecution, bytes, os.stat_result]:
    relative = identity["attempt_path"] + "/execution.json"
    if _present(_path(root, identity["attempt_path"] + "/.execution.json.tmp")):
        raise MaterializationExecutionUncertain(_INVALID)
    path = _path(root, relative)
    before = os.lstat(path)
    content = _read(path, MAX_STATE_BYTES)
    after = os.lstat(_path(root, relative))
    def fingerprint(info):
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns
    execution = CandidateExecution.from_dict(_strict_json_loads(content))
    if fingerprint(before) != fingerprint(after) or _encode(execution.to_dict()) != content:
        raise MaterializationExecutionUncertain(_INVALID)
    return execution, content, after


def _journal(
    parent: Run, child: Run, identity: dict[str, Any], intent: dict[str, Any],
    content: bytes, info: os.stat_result, *, attestation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "schema_version": "1", "parent_run_id": parent.id, "evolution_run_id": child.id,
        "task_id": identity["task_id"], "launch_intent_sha256": _digest(_encode(intent)),
        "execution_path": identity["attempt_path"] + "/execution.json",
        "execution_sha256": _digest(content), "execution_size": len(content),
        "artifact_id": "artifact-materialization-execution-" + _digest(f"{parent.id}\0{child.id}".encode()),
        "device": info.st_dev, "inode": info.st_ino,
    }
    if attestation is not None:
        from .materialization_attestation import validate_receipt

        receipt = validate_receipt(attestation)
        expected = {
            **{key: result[key] for key in (
                "schema_version", "parent_run_id", "evolution_run_id", "task_id",
                "launch_intent_sha256", "execution_path", "execution_sha256", "execution_size", "device", "inode",
            )},
            **{key: identity[key] for key in ("candidate_id", "candidate_sha256", "attempt_path")},
            "nonce": receipt["nonce"],
        }
        if receipt != expected:
            raise MaterializationExecutionUncertain(_INVALID)
        result["attestation"] = receipt
    return result


def _load(store: Store, parent: Run, child: Run, identity: dict[str, Any]) -> tuple[dict, dict, CandidateExecution, str]:
    root = _root(child)
    intent = inspect_launch_intent(store, child, identity)
    if intent is None or identity["parent_run_id"] != parent.id:
        raise MaterializationExecutionUncertain(_INVALID)
    directory = _path(root, DIRECTORY)
    content = _read(_path(directory, "journal.json"), MAX_JOURNAL_BYTES)
    journal = _strict_json_loads(content)
    execution, execution_content, info = _execution(root, identity)
    expected = _journal(
        parent, child, identity, intent, execution_content, info, attestation=journal.get("attestation"),
    )
    if content != _encode(expected) or journal != expected:
        raise MaterializationExecutionUncertain(_INVALID)
    temporary = _path(directory, ".journal.json.tmp")
    if _present(temporary) and _read(temporary, MAX_JOURNAL_BYTES) != content:
        raise MaterializationExecutionUncertain(_INVALID)
    return journal, intent, execution, _digest(content)


def _no_downstream(parent: Run, child: Run) -> None:
    root = _root(child)
    for name in (
        "result.json", ".result.json.tmp", ".terminal-publication", ".terminal-publication.lock",
        ".delivery-publication",
    ):
        if _present(_path(root, "evolution/materialization/" + name)):
            raise MaterializationExecutionUncertain(_INVALID)
    suffix = _digest(f"{parent.id}\0{child.id}".encode())
    # A new intake may not create its workspace until output publication starts.
    raw_parent = Path(parent.workspace).expanduser()
    if _present(raw_parent) and _present(_path(_root(parent), ".evolved-output-publications/" + suffix)):
        raise MaterializationExecutionUncertain(_INVALID)


def _status(store: Store, parent: Run, child: Run, identity: dict, loaded: tuple) -> str:
    journal, intent, execution, digest = loaded
    try:
        return store.materialization_execution_status(
            parent.id, child.id, identity["task_id"], intent, execution.to_dict(), journal_sha256=digest,
            **({"attestation": journal["attestation"]} if "attestation" in journal else {}),
        )
    except Exception as exc:
        raise MaterializationExecutionUncertain("materialization_execution_commit_unknown") from exc


def _finish(store: Store, parent: Run, child: Run, identity: dict, *, repair: bool) -> CandidateExecution:
    loaded = _load(store, parent, child, identity)
    journal, intent, execution, digest = loaded
    root = _root(child)
    directory = _path(root, DIRECTORY)
    completion = _completion(directory, digest)
    status = _status(store, parent, child, identity, loaded)
    if status == "absent" or (completion is not None and status != "committed"):
        raise MaterializationExecutionUncertain(_INVALID)
    if status == "prepared":
        if not repair:
            raise MaterializationExecutionUncertain(_INVALID)
        _no_downstream(parent, child)
        path = _path(root, journal["execution_path"])
        _sync_file(path)
        _fsync_directory_chain(path.parent, root, error="materialization_execution_sync_failed")
        if _load(store, parent, child, identity) != loaded or _completion(directory, digest) is not None:
            raise MaterializationExecutionUncertain(_INVALID)
        try:
            store.commit_materialization_execution(
                parent.id, child.id, identity["task_id"], intent, execution.to_dict(),
                journal_sha256=digest, max_artifact_bytes=(child.budget or BudgetSpec()).max_artifact_bytes,
                **({"attestation": journal["attestation"]} if "attestation" in journal else {}),
            )
        except Exception as exc:
            if _status(store, parent, child, identity, loaded) != "committed":
                raise MaterializationExecutionUncertain("materialization_execution_not_committed") from exc
    if (_status(store, parent, child, identity, loaded) != "committed"
        or _load(store, parent, child, identity) != loaded
        or _completion(directory, digest) != completion):
        raise MaterializationExecutionUncertain(_INVALID)
    if completion == "completed.json":
        if repair:
            # A previous process may have linked the receipt before its directory was synced.
            _sync_file(directory / completion)
            _sync(directory)
    elif repair:
        _write_complete(directory, digest)
    else:
        raise MaterializationExecutionUncertain(_INVALID)
    if (_load(store, parent, child, identity) != loaded
        or _completion(directory, digest) != "completed.json"
        or _status(store, parent, child, identity, loaded) != "committed"):
        raise MaterializationExecutionUncertain(_INVALID)
    return execution


def _recover(
    store: Store, parent: Run, child: Run, identity: dict[str, Any], *, repair: bool,
) -> CandidateExecution | None:
    try:
        if not _present(_path(_root(child), DIRECTORY)):
            if store.has_materialization_execution(parent.id, child.id):
                raise MaterializationExecutionUncertain(_INVALID)
            return None
        return _finish(store, parent, child, identity, repair=repair)
    except MaterializationExecutionUncertain:
        raise
    except Exception as exc:
        raise MaterializationExecutionUncertain(_INVALID) from exc


def recover_materialization_execution(
    store: Store, parent: Run, child: Run, identity: dict[str, Any],
) -> CandidateExecution | None:
    """Reconcile an exact prepared execution batch; never prepare raw runner evidence."""
    return _recover(store, parent, child, identity, repair=True)


def inspect_materialization_execution(
    store: Store, parent: Run, child: Run, identity: dict[str, Any],
) -> CandidateExecution | None:
    """Read-only validation for terminal publication, including retained modern evidence."""
    return _recover(store, parent, child, identity, repair=False)


def publish_materialization_execution(
    store: Store, parent: Run, child: Run, identity: dict[str, Any], execution: CandidateExecution,
    *, attestation: dict[str, Any] | None = None,
) -> CandidateExecution:
    """Prepare a returned result or exact explicit attestation and commit its ledger batch."""
    try:
        if not isinstance(execution, CandidateExecution):
            raise MaterializationExecutionUncertain(_INVALID)
        root = _root(child)
        intent = inspect_launch_intent(store, child, identity)
        if intent is None or identity["parent_run_id"] != parent.id:
            raise MaterializationExecutionUncertain(_INVALID)
        recorded, content, info = _execution(root, identity)
        if _encode(execution.to_dict()) != content:
            raise MaterializationExecutionUncertain(_INVALID)
        directory = _path(root, DIRECTORY)
        _no_downstream(parent, child)
        journal = _journal(parent, child, identity, intent, content, info, attestation=attestation)
        journal_content = _encode(journal)
        if len(journal_content) > MAX_JOURNAL_BYTES:
            raise MaterializationExecutionUncertain(_INVALID)
        digest = _digest(journal_content)
        loaded = (journal, intent, recorded, digest)
        status = _status(store, parent, child, identity, loaded)
        existing = _present(directory)
        if existing:
            if attestation is None or _load(store, parent, child, identity) != loaded:
                raise MaterializationExecutionUncertain(_INVALID)
            if status != "absent":
                return _finish(store, parent, child, identity, repair=True)
            if _completion(directory, digest) is not None or _present(_path(directory, ".journal.json.tmp")):
                raise MaterializationExecutionUncertain(_INVALID)
        elif status != "absent" or store.has_materialization_execution(parent.id, child.id):
            raise MaterializationExecutionUncertain(_INVALID)
        execution_path = _path(root, journal["execution_path"])
        _sync_file(execution_path)
        _fsync_directory_chain(execution_path.parent, root, error="materialization_execution_sync_failed")
        if not existing:
            directory.mkdir(mode=0o700)
            _sync(directory.parent)
            _write_record(directory, "journal.json", journal_content)
        else:
            _sync_file(directory / "journal.json")
        _fsync_directory_chain(directory, root, error="materialization_execution_sync_failed")
        if _load(store, parent, child, identity) != loaded:
            raise MaterializationExecutionUncertain(_INVALID)
        _no_downstream(parent, child)
        try:
            store.prepare_materialization_execution(
                parent.id, child.id, identity["task_id"], intent, execution.to_dict(),
                journal_sha256=digest, max_artifact_bytes=(child.budget or BudgetSpec()).max_artifact_bytes,
                **({"attestation": attestation} if attestation is not None else {}),
            )
        except Exception as exc:
            if _status(store, parent, child, identity, loaded) != "prepared":
                raise MaterializationExecutionUncertain("materialization_execution_not_prepared") from exc
        return _finish(store, parent, child, identity, repair=True)
    except MaterializationExecutionUncertain:
        raise
    except Exception as exc:
        raise MaterializationExecutionUncertain(_INVALID) from exc
