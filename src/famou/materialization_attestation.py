"""Explicit local authorization for one exact retained execution registration.

An operator-supplied receipt is an audit statement, not proof of process execution.
Neither validation nor registration invokes a runner or publishes outputs.
"""

from __future__ import annotations

import os
import re
import stat
import tempfile
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any

from . import diagnostic_snapshot as snapshot
from .evolution import MAX_STATE_BYTES, CandidateExecution, _strict_json_loads
from .materialization_execution import (
    DIRECTORY,
    MaterializationExecutionUncertain,
    _digest,
    _encode,
    _execution,
    _journal,
    _load,
    _no_downstream,
    _path,
    _present,
    _read,
    _root,
    publish_materialization_execution,
)
from .materialization_launch import (
    INTENT_PATH,
    MAX_INTENT_BYTES,
    MaterializationBusy,
    inspect_launch_intent,
    materialization_lock,
)
from .models import Run
from .store import Store

MAX_ATTESTATION_BYTES = 16 * 1024
_INVALID = "materialization_attestation_invalid"
_KEYS = {
    "schema_version", "parent_run_id", "evolution_run_id", "task_id", "launch_intent_sha256",
    "candidate_id", "candidate_sha256", "attempt_path", "execution_path", "execution_sha256",
    "execution_size", "device", "inode", "nonce",
}
_ID = r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}"


def validate_receipt(receipt: Any) -> dict[str, Any]:
    """Detach a strictly bounded schema without reading or initializing any source state."""
    try:
        if not isinstance(receipt, dict) or set(receipt) != _KEYS or receipt["schema_version"] != "1":
            raise ValueError
        for key in ("parent_run_id", "evolution_run_id", "task_id", "candidate_id"):
            if not isinstance(receipt[key], str) or re.fullmatch(_ID, receipt[key]) is None:
                raise ValueError
        if receipt["parent_run_id"] == receipt["evolution_run_id"]:
            raise ValueError
        for key in ("launch_intent_sha256", "candidate_sha256", "execution_sha256"):
            if not isinstance(receipt[key], str) or re.fullmatch(r"[0-9a-f]{64}", receipt[key]) is None:
                raise ValueError
        attempt = f"evolution/materialization/{receipt['candidate_id']}-{receipt['candidate_sha256'][:12]}"
        if receipt["attempt_path"] != attempt or receipt["execution_path"] != attempt + "/execution.json":
            raise ValueError
        if any(type(receipt[key]) is not int or receipt[key] < 0 for key in ("device", "inode", "execution_size")):
            raise ValueError
        if any(receipt[key] >= 2**64 for key in ("device", "inode")):
            raise ValueError
        if not 0 < receipt["execution_size"] <= MAX_STATE_BYTES:
            raise ValueError
        if not isinstance(receipt["nonce"], str) or re.fullmatch(r"[A-Za-z0-9._~-]{32,128}", receipt["nonce"]) is None:
            raise ValueError
        content = _encode(receipt)
        if len(content) > MAX_ATTESTATION_BYTES:
            raise ValueError
        return _strict_json_loads(content)
    except Exception:  # noqa: BLE001 - fixed public errors never disclose retained data.
        raise MaterializationExecutionUncertain(_INVALID) from None


def read_attestation_receipt(path: Path) -> dict[str, Any]:
    try:
        # Check all ancestors as well as the final no-follow regular-file read.
        path = Path(path).expanduser().absolute()
        if ".." in path.parts:
            raise ValueError
        with ExitStack() as stack:
            parent, name = snapshot._parent(path)
            stack.callback(os.close, parent)
            descriptor = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent,
            )
            stack.callback(os.close, descriptor)
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_ATTESTATION_BYTES:
                raise ValueError
            chunks = []
            remaining = MAX_ATTESTATION_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            content = b"".join(chunks)
            after = os.fstat(descriptor)
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            current_parent, _ = snapshot._parent(path)
            stack.callback(os.close, current_parent)
            if (
                len(content) != before.st_size or len(content) > MAX_ATTESTATION_BYTES
                or snapshot._identity(before) != snapshot._identity(after)
                or snapshot._identity(before) != snapshot._identity(current)
                or (os.fstat(parent).st_dev, os.fstat(parent).st_ino)
                != (os.fstat(current_parent).st_dev, os.fstat(current_parent).st_ino)
            ):
                raise ValueError
        receipt = validate_receipt(_strict_json_loads(content))
        if _encode(receipt) != content:
            raise ValueError
        return receipt
    except Exception:  # noqa: BLE001 - fixed public errors never disclose retained data.
        raise MaterializationExecutionUncertain(_INVALID) from None


@contextmanager
def _snapshot_store(database: Path):
    """Reuse 093's bounded no-follow DB/WAL copying before opening any live SQLite connection."""
    with ExitStack() as stack:
        parent, name = snapshot._parent(database)
        stack.callback(os.close, parent)
        sources = snapshot._sources(parent, name, stack)
        temporary = stack.enter_context(tempfile.TemporaryDirectory(
            prefix="lunar-attestation-", dir=snapshot._temporary_root(database),
        ))
        copied = Path(temporary) / "snapshot.db"
        for suffix, source in sources.items():
            if source is not None:
                snapshot._copy_file(source[0], Path(str(copied) + suffix), source[1][2])
        snapshot._unchanged(database, parent, name, sources)
        snapshot._check_wal(copied)
        yield Store(copied)
        snapshot._unchanged(database, parent, name, sources)


def _validate_source(store: Store, parent: Run, child: Run, receipt: dict) -> tuple[dict, CandidateExecution]:
    if receipt["parent_run_id"] != parent.id or receipt["evolution_run_id"] != child.id:
        raise ValueError
    root = _root(child)
    content = _read(_path(root, INTENT_PATH), MAX_INTENT_BYTES)
    intent = _strict_json_loads(content)
    identity = {key: value for key, value in intent.items() if key not in {"runner_sha256", "timeout_seconds"}}
    if inspect_launch_intent(store, child, identity) != intent:
        raise ValueError
    execution, execution_bytes, info = _execution(root, identity)
    expected = {
        "schema_version": "1", "parent_run_id": parent.id, "evolution_run_id": child.id,
        "task_id": identity["task_id"], "launch_intent_sha256": _digest(content),
        "candidate_id": identity["candidate_id"], "candidate_sha256": identity["candidate_sha256"],
        "attempt_path": identity["attempt_path"], "execution_path": identity["attempt_path"] + "/execution.json",
        "execution_sha256": _digest(execution_bytes), "execution_size": len(execution_bytes),
        "device": info.st_dev, "inode": info.st_ino, "nonce": receipt["nonce"],
    }
    if receipt != expected:
        raise ValueError
    _no_downstream(parent, child)
    journal = _journal(parent, child, identity, intent, execution_bytes, info, attestation=receipt)
    loaded = (journal, intent, execution, _digest(_encode(journal)))
    recorded = store.materialization_execution_attestation_recorded(
        parent.id, child.id, identity["task_id"], intent, execution.to_dict(), receipt,
        journal_sha256=loaded[3], require_no_downstream=True,
    )
    if _present(_path(root, DIRECTORY)):
        if _load(store, parent, child, identity) != loaded:
            raise ValueError
        if not recorded:
            # Only an exact final attested journal can be explicitly retried before DB preparation.
            for name in ("completed.json", ".completed.json.tmp", ".journal.json.tmp"):
                if _present(_path(root, DIRECTORY + "/" + name)):
                    raise ValueError
    elif recorded:
        raise ValueError
    return identity, execution


def attest_materialization_execution(
    store: Store, parent: Run, child: Run, receipt_path: Path,
) -> CandidateExecution:
    """Register exact operator-attested bytes under the existing nonblocking lifecycle lock."""
    return _attest_receipt(store, parent, child, read_attestation_receipt(receipt_path))


def _attest_receipt(store: Store, parent: Run, child: Run, receipt: dict) -> CandidateExecution:
    try:
        _validate_source(store, parent, child, receipt)
        with materialization_lock(child):
            for expected in (parent, child):
                current = store.get_run(expected.id)
                if current is None or current.workspace != expected.workspace or current.budget != expected.budget:
                    raise ValueError
            identity, execution = _validate_source(store, parent, child, receipt)
            return publish_materialization_execution(
                store, parent, child, identity, execution, attestation=receipt,
            )
    except MaterializationBusy:
        raise
    except Exception:  # noqa: BLE001 - fixed public errors never disclose retained data.
        raise MaterializationExecutionUncertain(_INVALID) from None


def attest_from_database(database: Path, parent_id: str, child_id: str, receipt_path: Path) -> dict:
    """CLI entry: fully preflight a private copy before using normal live storage."""
    receipt = read_attestation_receipt(receipt_path)
    try:
        if receipt["parent_run_id"] != parent_id or receipt["evolution_run_id"] != child_id:
            raise ValueError
        database = Path(database).expanduser().absolute()
        with _snapshot_store(database) as copied:
            parent, child = copied.get_run(parent_id), copied.get_run(child_id)
            if parent is None or child is None:
                raise ValueError
            _validate_source(copied, parent, child, receipt)
        _attest_receipt(Store(database), parent, child, receipt)
        return {"status": "registered", "parent_run_id": parent_id, "evolution_run_id": child_id,
                "task_id": receipt["task_id"], "receipt_sha256": _digest(_encode(receipt))}
    except MaterializationBusy:
        raise
    except Exception:  # noqa: BLE001 - fixed public errors never disclose retained data.
        raise MaterializationExecutionUncertain(_INVALID) from None
