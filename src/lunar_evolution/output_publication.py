"""Recoverable, no-clobber publication of an evolved output batch.

SQLite acknowledges the immutable journal and the entire artifact batch together. Retained staged
hard links prove which new output paths this transaction owns when an uncommitted batch rolls back.
This protocol does not make multiple filesystem directory entries simultaneously visible.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .algorithm import MAX_OUTPUTS, OutputSpec
from .artifacts import ArtifactError
from .automatic_solve_lifecycle import SolveExecutionBudgetExceeded, SolveExecutionCancelled
from .evaluator import MAX_ARTIFACT_BYTES
from .evolution import (
    EvolutionError,
    _fsync_directory,
    _read_bounded_regular_file,
    _strict_json_loads,
)
from .models import Run
from .store import Store

MAX_JOURNAL_BYTES = 128 * 1024
_ROOT = ".evolved-output-publications"
_INVALID = "output_publication_evidence_invalid"


class OutputPublicationError(ArtifactError, EvolutionError):
    """Publication was rejected or its uncommitted files were rolled back."""


class OutputPublicationUncertain(OutputPublicationError):
    """Evidence cannot prove commit or safe rollback; preserve the complete attempt."""


def _key(parent_id: str, child_id: str) -> str:
    return hashlib.sha256(f"{parent_id}\0{child_id}".encode()).hexdigest()


def _present(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    return True


def _root(parent: Run, *, create: bool = False) -> Path:
    raw = Path(parent.workspace).expanduser()
    if create and not _present(raw):
        ancestor = raw.parent
        while not _present(ancestor):
            ancestor = ancestor.parent
        _mkdirs(ancestor.resolve(), raw.resolve())
    if raw.is_symlink() or not raw.is_dir():
        raise OutputPublicationUncertain(_INVALID)
    return raw.resolve()


def _confined(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or path.as_posix() != relative or any(
        part in {".", ".."} for part in path.parts
    ) or not path.parts:
        raise OutputPublicationUncertain(_INVALID)
    current = root
    for index, component in enumerate(path.parts):
        current = current / component
        if _present(current):
            mode = os.lstat(current).st_mode
            if stat.S_ISLNK(mode) or (index < len(path.parts) - 1 and not stat.S_ISDIR(mode)):
                raise OutputPublicationUncertain(_INVALID)
    return current


def _target(root: Path, relative: str) -> Path:
    if not relative.startswith("output/"):
        raise OutputPublicationUncertain(_INVALID)
    return _confined(root, relative)


def _read(path: Path, limit: int = MAX_ARTIFACT_BYTES) -> bytes:
    try:
        return _read_bounded_regular_file(path, limit, error=_INVALID)
    except Exception as exc:
        raise OutputPublicationUncertain(_INVALID) from exc


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _encode(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            + "\n").encode("utf-8")


def _sync(path: Path) -> None:
    _fsync_directory(path, error="output_publication_sync_failed")


def _mkdirs(root: Path, path: Path) -> None:
    relative = path.relative_to(root)
    current = root
    for part in relative.parts:
        child = current / part
        if not _present(child):
            child.mkdir(mode=0o700)
            _sync(current)
        if child.is_symlink() or not child.is_dir():
            raise OutputPublicationUncertain(_INVALID)
        current = child


def _write_new(path: Path, content: bytes) -> None:
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
    )
    try:
        view = memoryview(content)
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                raise OSError("publication write made no progress")
            view = view[count:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_marker(directory: Path, name: str, payload: dict[str, Any]) -> None:
    temporary = directory / ("." + name + ".tmp")
    content = _encode(payload)
    if _present(temporary):
        if _read(temporary, MAX_JOURNAL_BYTES) != content:
            raise OutputPublicationUncertain(_INVALID)
        descriptor = os.open(temporary, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    else:
        _write_new(temporary, content)
    # No-clobber publication, including acknowledgements. Never replace another journal.
    os.link(temporary, directory / name, follow_symlinks=False)
    temporary.unlink()
    _sync(directory)


@contextmanager
def _locked(root: Path):
    directory = root / _ROOT
    _mkdirs(root, directory)
    lock = directory / ".lock"
    descriptor = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        held = os.fstat(descriptor)
        if not stat.S_ISREG(held.st_mode) or held.st_nlink != 1:
            raise OutputPublicationUncertain(_INVALID)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        current = os.lstat(lock)
        if (held.st_dev, held.st_ino) != (current.st_dev, current.st_ino):
            raise OutputPublicationUncertain(_INVALID)
        yield directory
    finally:
        os.close(descriptor)


def _projection(spec: OutputSpec, content: bytes, artifact_id: str) -> dict[str, Any]:
    return {"artifact_id": artifact_id, "path": spec.path, "format": spec.format,
            "fields": list(spec.fields), "required": spec.required,
            "size": len(content), "sha256": _digest(content)}


def _validate_paths(specs: tuple[OutputSpec, ...]) -> None:
    # Conservatively reject aliases even on case-sensitive hosts, keeping journals portable to
    # the default case-insensitive macOS filesystem. File/directory prefix collisions are invalid.
    paths = [unicodedata.normalize("NFC", spec.path).casefold() for spec in specs]
    if len(set(paths)) != len(paths) or any(
        right.startswith(left + "/") for left in paths for right in paths if left != right
    ):
        raise OutputPublicationUncertain(_INVALID)


def _load(
    directory: Path, parent: Run, child_id: str, specs: tuple[OutputSpec, ...]
) -> tuple[dict[str, Any], str]:
    _validate_paths(specs)
    if directory.is_symlink() or not directory.is_dir():
        raise OutputPublicationUncertain(_INVALID)
    content = _read(directory / "journal.json", MAX_JOURNAL_BYTES)
    try:
        journal = _strict_json_loads(content)
        if not isinstance(journal, dict) or set(journal) != {
            "schema_version", "parent_run_id", "evolution_run_id", "owner_task_id", "entries"
        } or journal["schema_version"] != "1" or journal["parent_run_id"] != parent.id or (
            journal["evolution_run_id"] != child_id
        ) or not isinstance(journal["owner_task_id"], str) or content != _encode(journal):
            raise ValueError(_INVALID)
        entries = journal["entries"]
        if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_OUTPUTS:
            raise ValueError(_INVALID)
        known = {spec.path: spec for spec in specs}
        paths: list[str] = []
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict) or set(entry) != {
                "output", "stage", "device", "inode", "existed"
            } or entry["stage"] != f"{index:02d}.blob" or not isinstance(entry["existed"], bool):
                raise ValueError(_INVALID)
            if any(type(entry[k]) is not int or entry[k] < 0 for k in ("device", "inode")):
                raise ValueError(_INVALID)
            output = entry["output"]
            if not isinstance(output, dict) or set(output) != {
                "artifact_id", "path", "format", "fields", "required", "size", "sha256"
            } or not isinstance(output["path"], str):
                raise ValueError(_INVALID)
            spec = known[output["path"]]
            if (output["format"] != spec.format or output["fields"] != list(spec.fields)
                or output["required"] is not spec.required or type(output["size"]) is not int
                or not 0 <= output["size"] <= MAX_ARTIFACT_BYTES
                or not isinstance(output["sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", output["sha256"])
                or not isinstance(output["artifact_id"], str) or not output["artifact_id"]):
                raise ValueError(_INVALID)
            paths.append(output["path"])
        if len(set(paths)) != len(paths) or paths != [s.path for s in specs if s.path in paths]:
            raise ValueError(_INVALID)
        if any(s.required and s.path not in paths for s in specs):
            raise ValueError(_INVALID)
        if len({e["output"]["artifact_id"] for e in entries}) != len(entries):
            raise ValueError(_INVALID)
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        raise OutputPublicationUncertain(_INVALID) from exc
    return journal, _digest(content)


def _verify_files(root: Path, directory: Path, entries: list[dict[str, Any]]) -> None:
    # Inspect the entire batch first; no partial rollback on a later conflicting path.
    for entry in entries:
        output = entry["output"]
        staged = _confined(directory, entry["stage"])
        content = _read(staged)
        identity = os.lstat(staged)
        if ((identity.st_dev, identity.st_ino) != (entry["device"], entry["inode"])
            or len(content) != output["size"] or _digest(content) != output["sha256"]):
            raise OutputPublicationUncertain(_INVALID)
        target = _target(root, output["path"])
        if _present(target):
            current = os.lstat(target)
            data = _read(target)
            if len(data) != output["size"] or _digest(data) != output["sha256"]:
                raise OutputPublicationUncertain(_INVALID)
            if not entry["existed"] and (current.st_dev, current.st_ino) != (
                entry["device"], entry["inode"]
            ):
                raise OutputPublicationUncertain(_INVALID)
        elif entry["existed"]:
            raise OutputPublicationUncertain(_INVALID)


def _sync_outputs(root: Path, entries: list[dict[str, Any]]) -> None:
    # Reused files may have been written without fsync by their original producer.
    directories = {root}
    for entry in entries:
        target = _target(root, entry["output"]["path"])
        descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise OutputPublicationUncertain(_INVALID)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        directory = target.parent
        while directory != root:
            directories.add(directory)
            directory = directory.parent
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        _sync(directory)


def _reconcile(
    store: Store, parent: Run, child_id: str, specs: tuple[OutputSpec, ...], directory: Path
) -> tuple[str, tuple[dict[str, Any], ...]]:
    journal, digest = _load(directory, parent, child_id, specs)
    entries = journal["entries"]
    root = _root(parent)
    _verify_files(root, directory, entries)
    outputs = [entry["output"] for entry in entries]
    try:
        committed = store.output_publication_committed(
            parent.id, child_id, outputs, journal_sha256=digest,
            owner_task_id=journal["owner_task_id"],
        )
    except Exception as exc:
        raise OutputPublicationUncertain("output_publication_commit_unknown") from exc
    rolled_back = directory / "rolled-back.json"
    if _present(rolled_back):
        expected = _encode({"journal_sha256": digest})
        if _read(rolled_back, MAX_JOURNAL_BYTES) != expected or committed or any(
            not e["existed"] and _present(_target(root, e["output"]["path"])) for e in entries
        ):
            raise OutputPublicationUncertain(_INVALID)
        _sync(directory)
        return "rolled_back", tuple(outputs)
    if committed:
        if any(not _present(_target(root, e["output"]["path"])) for e in entries):
            raise OutputPublicationUncertain(_INVALID)
        return "committed", tuple(outputs)
    temporary_rollback = directory / ".rolled-back.json.tmp"
    if _present(temporary_rollback) and _read(
        temporary_rollback, MAX_JOURNAL_BYTES
    ) != _encode({"journal_sha256": digest}):
        raise OutputPublicationUncertain(_INVALID)
    # The batch is proven uncommitted. Only our exact retained hardlinks may be removed.
    try:
        for entry in entries:
            if entry["existed"]:
                continue
            target = _target(root, entry["output"]["path"])
            if _present(target):
                _verify_files(root, directory, entries)
                target.unlink()
            # A previous process may have exited after unlink but before its directory fsync.
            ancestor = target.parent
            while not _present(ancestor):
                ancestor = ancestor.parent
            _sync(ancestor)
        _write_marker(directory, "rolled-back.json", {"journal_sha256": digest})
    except Exception as exc:
        raise OutputPublicationUncertain("output_publication_rollback_unknown") from exc
    return "rolled_back", tuple(outputs)


def recover_outputs(
    store: Store, parent: Run, evolution_run_id: str, specs: tuple[OutputSpec, ...]
) -> str | None:
    """Reconcile a retained batch without creating an execution or terminal result."""
    return recover_output_batch(store, parent, evolution_run_id, specs)[0]


def _require_no_output_evidence(store: Store, parent: Run, child_id: str) -> None:
    _require_no_publication(store, parent.id, child_id)
    suffix = _key(parent.id, child_id)
    reserved = {prefix + suffix for prefix in (
        "event-evolved-outputs-promoted-", "event-output-publication-committed-",
    )}
    for event in store.list_events(parent.id):
        payload = event.get("payload")
        if event.get("id") in reserved or (
            event.get("type") in {"evolved_outputs_promoted", "output_publication_committed"}
            and isinstance(payload, dict) and payload.get("evolution_run_id") == child_id
        ):
            raise OutputPublicationUncertain(_INVALID)
        if event.get("type") == "artifact_recorded" and isinstance(payload, dict):
            path = payload.get("path")
            if isinstance(path, str) and payload.get("artifact_id") == (
                "artifact-output-publication-" + _digest(f"{parent.id}\0{child_id}\0{path}".encode())
            ):
                raise OutputPublicationUncertain(_INVALID)
    for row in store.list_artifacts(parent.id):
        if row["id"] == "artifact-output-publication-" + _digest(
            f"{parent.id}\0{child_id}\0{row['path']}".encode()
        ):
            raise OutputPublicationUncertain(_INVALID)


def _inspect_batch(
    store: Store, parent: Run, child_id: str, specs: tuple[OutputSpec, ...], directory: Path,
) -> tuple[str, tuple[dict[str, Any], ...]]:
    journal, digest = _load(directory, parent, child_id, specs)
    root = _root(parent)
    entries = journal["entries"]
    _verify_files(root, directory, entries)
    outputs = tuple(entry["output"] for entry in entries)
    committed = store.output_publication_committed(
        parent.id, child_id, list(outputs), journal_sha256=digest,
        owner_task_id=journal["owner_task_id"],
    )
    rollback = _encode({"journal_sha256": digest})
    for name in ("rolled-back.json", ".rolled-back.json.tmp"):
        path = directory / name
        if _present(path) and (_read(path, MAX_JOURNAL_BYTES) != rollback or committed):
            raise OutputPublicationUncertain(_INVALID)
    if _present(directory / "rolled-back.json"):
        if any(not entry["existed"] and _present(_target(root, entry["output"]["path"])) for entry in entries):
            raise OutputPublicationUncertain(_INVALID)
        return "rolled_back", outputs
    if committed:
        if any(not _present(_target(root, entry["output"]["path"])) for entry in entries):
            raise OutputPublicationUncertain(_INVALID)
        return "committed", outputs
    return "uncommitted", outputs


def recover_output_batch(
    store: Store, parent: Run, evolution_run_id: str, specs: tuple[OutputSpec, ...], *,
    expected_outputs: list[dict[str, Any]] | None = None, reconcile: bool = True,
) -> tuple[str | None, tuple[dict[str, Any], ...]]:
    """Inspect or reconcile a batch after checking delivery's byte metadata under the lock."""
    _validate_paths(specs)
    # Intake creates run records before the parent has needed a workspace on disk.
    if not _present(Path(parent.workspace).expanduser()):
        if expected_outputs is None:
            _require_no_publication(store, parent.id, evolution_run_id)
        else:
            _require_no_output_evidence(store, parent, evolution_run_id)
        return None, ()
    root = _root(parent)
    directory = _confined(root, f"{_ROOT}/{_key(parent.id, evolution_run_id)}")
    if not _present(directory):
        if expected_outputs is None:
            _require_no_publication(store, parent.id, evolution_run_id)
        else:
            _require_no_output_evidence(store, parent, evolution_run_id)
        return None, ()
    try:
        with _locked(root):
            if expected_outputs is not None:
                journal, _ = _load(directory, parent, evolution_run_id, specs)
                metadata = [{key: value for key, value in entry["output"].items() if key != "artifact_id"}
                            for entry in journal["entries"]]
                if _encode(metadata) != _encode(expected_outputs):
                    raise OutputPublicationUncertain(_INVALID)
            if not reconcile:
                return _inspect_batch(store, parent, evolution_run_id, specs, directory)
            return _reconcile(store, parent, evolution_run_id, specs, directory)
    except OutputPublicationUncertain:
        raise
    except Exception as exc:
        raise OutputPublicationUncertain(_INVALID) from exc


def _require_no_publication(store: Store, parent_id: str, child_id: str) -> None:
    try:
        if store.has_output_publication(parent_id, child_id):
            raise OutputPublicationUncertain(_INVALID)
    except OutputPublicationUncertain:
        raise
    except Exception as exc:
        raise OutputPublicationUncertain("output_publication_commit_unknown") from exc


def publish_outputs(
    store: Store,
    parent: Run,
    evolution_run_id: str,
    owner_task_id: str,
    prepared: list[tuple[OutputSpec, bytes]],
    max_artifact_bytes: int,
    *, continuation_guard=None,
) -> tuple[dict[str, Any], ...]:
    """Publish a verified batch, or restore its previously absent final paths."""
    def guard():
        if continuation_guard is not None:
            continuation_guard()

    guard()
    if not prepared:
        recover_outputs(store, parent, evolution_run_id, ())
        return ()
    root = _root(parent, create=True)
    specs = tuple(spec for spec, _ in prepared)
    _validate_paths(specs)
    if (len(prepared) > MAX_OUTPUTS or len({s.path for s in specs}) != len(specs)
        or any(not isinstance(data, bytes) or len(data) > MAX_ARTIFACT_BYTES for _, data in prepared)):
        raise OutputPublicationError(_INVALID)
    try:
        with _locked(root) as publications:
            guard()
            directory = publications / _key(parent.id, evolution_run_id)
            if _present(directory):
                journal, _ = _load(directory, parent, evolution_run_id, specs)
                # Reject a changed request before reconciliation can mutate uncommitted files.
                if journal["owner_task_id"] != owner_task_id or any(
                    entry["output"] != _projection(spec, content, entry["output"]["artifact_id"])
                    for entry, (spec, content) in zip(journal["entries"], prepared, strict=True)
                ):
                    raise OutputPublicationUncertain(_INVALID)
                status, outputs = _reconcile(store, parent, evolution_run_id, specs, directory)
                if status == "committed":
                    guard()
                    return outputs
                raise OutputPublicationError("output_publication_already_rolled_back")
            _require_no_publication(store, parent.id, evolution_run_id)
            rows = store.list_artifacts(parent.id)
            task_ids = {task.id for task in store.list_tasks(parent.id)}
            if owner_task_id not in task_ids or any(
                type(row["size"]) is not int or row["size"] < 0 for row in rows
            ):
                raise OutputPublicationError("output_publication_ledger_mismatch")
            entries = []
            additional = 0
            for index, (spec, content) in enumerate(prepared):
                target = _target(root, spec.path)
                nearest = target.parent
                while not _present(nearest):
                    nearest = nearest.parent
                if os.stat(nearest).st_dev != os.stat(root).st_dev:
                    raise OutputPublicationError("output_publication_cross_volume")
                digest = _digest(content)
                existed = _present(target)
                if existed and _read(target) != content:
                    raise OutputPublicationError("output_publication_output_conflict")
                matching = [r for r in rows if r["kind"] == "output" and r["path"] == spec.path]
                if len(matching) > 1 or any(
                    r["sha256"] != digest or r["size"] != len(content)
                    or r["task_id"] not in task_ids for r in matching
                ) or (matching and not existed):
                    raise OutputPublicationError("output_publication_ledger_mismatch")
                artifact_id = matching[0]["id"] if matching else (
                    "artifact-output-publication-" + _digest(
                        f"{parent.id}\0{evolution_run_id}\0{spec.path}".encode()
                    )
                )
                if not matching:
                    additional += len(content)
                entries.append({"output": _projection(spec, content, artifact_id),
                                "stage": f"{index:02d}.blob", "existed": existed})
            if sum(r["size"] for r in rows) + additional > max_artifact_bytes:
                raise OutputPublicationError("output_publication_budget_exceeded")
            directory.mkdir(mode=0o700)
            _sync(publications)
            for entry, (_, content) in zip(entries, prepared, strict=True):
                stage = directory / entry["stage"]
                _write_new(stage, content)
                identity = os.lstat(stage)
                entry.update(device=identity.st_dev, inode=identity.st_ino)
            _sync(directory)
            journal = {"schema_version": "1", "parent_run_id": parent.id,
                       "evolution_run_id": evolution_run_id, "owner_task_id": owner_task_id,
                       "entries": entries}
            if len(_encode(journal)) > MAX_JOURNAL_BYTES:
                raise OutputPublicationUncertain(_INVALID)
            _write_marker(directory, "journal.json", journal)
            try:
                _verify_files(root, directory, entries)
                outputs = [entry["output"] for entry in entries]
                # Reuse the full ledger validator before any final link. Conflicting reserved
                # IDs or orphan events must not leave files whose rollback cannot be proven.
                if store.output_publication_committed(
                    parent.id, evolution_run_id, outputs,
                    journal_sha256=_digest(_encode(journal)), owner_task_id=owner_task_id,
                ):
                    raise OutputPublicationUncertain("output_publication_commit_unknown")
                for entry in entries:
                    guard()
                    target = _target(root, entry["output"]["path"])
                    if entry["existed"]:
                        continue
                    _mkdirs(root, target.parent)
                    if os.stat(target.parent).st_dev != entry["device"]:
                        raise OutputPublicationError("output_publication_cross_volume")
                    os.link(directory / entry["stage"], target, follow_symlinks=False)
                    _sync(target.parent)
                _verify_files(root, directory, entries)
                _sync_outputs(root, entries)
                _verify_files(root, directory, entries)
                guard()
                store.commit_output_publication(
                    parent.id, owner_task_id, evolution_run_id, outputs,
                    journal_sha256=_digest(_encode(journal)), max_artifact_bytes=max_artifact_bytes,
                )
                status, verified = _reconcile(store, parent, evolution_run_id, specs, directory)
                if status != "committed":
                    raise OutputPublicationUncertain("output_publication_commit_unknown")
                guard()
                return verified
            except (SolveExecutionBudgetExceeded, SolveExecutionCancelled):
                _reconcile(store, parent, evolution_run_id, specs, directory)
                raise
            except Exception as exc:
                status, verified = _reconcile(store, parent, evolution_run_id, specs, directory)
                if status == "committed":
                    return verified
                raise OutputPublicationError("output_publication_rolled_back") from exc
    except (OutputPublicationError, SolveExecutionBudgetExceeded, SolveExecutionCancelled):
        raise
    except Exception as exc:
        raise OutputPublicationUncertain("output_publication_prepare_failed") from exc
