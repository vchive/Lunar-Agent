"""Bounded SQLite observations without opening SQLite on any source file.

The returned inventory is not recovery authority. SQLite may rebuild its WAL index only
inside a private temporary directory; source reads may update ordinary access times.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import stat
import struct
import tempfile
from contextlib import ExitStack, closing
from pathlib import Path
from typing import Any

MAX_DATABASE_BYTES = 128 * 1024 * 1024
MAX_WAL_BYTES = 64 * 1024 * 1024
MAX_SOURCE_BYTES = MAX_DATABASE_BYTES + MAX_WAL_BYTES
MAX_ROWS = 4096
MAX_PAYLOAD_BYTES = 64 * 1024
MAX_TOTAL_PAYLOAD_BYTES = 8 * 1024 * 1024
MAX_SQL_STEPS = 2_000_000
_CHUNK_BYTES = 1024 * 1024
_TEXT_BYTES = 4096
_EVENT_TYPES = (
    "artifact_recorded", "evolution_linked", "evolution_parent_linked",
    "materialization_launch_intended", "materialization_execution_prepared",
    "materialization_execution_committed", "evolved_candidate_executed",
    "materialization_execution_attested",
    "materialization_delivery_prepared", "evolved_outputs_promoted",
    "output_publication_committed", "materialization_publication_prepared",
    "materialization_publication_committed", "evolved_candidate_materialized",
)
_EVENT_PREFIXES = (
    "event-materialization-launch-intended-", "event-materialization-execution-prepared-",
    "event-materialization-execution-artifact-recorded-", "event-materialization-execution-committed-",
    "event-materialization-execution-attested-",
    "event-materialization-delivery-prepared-", "event-evolved-outputs-promoted-",
    "event-output-publication-committed-", "event-materialization-publication-prepared-",
    "event-materialization-artifact-recorded-", "event-materialization-publication-committed-",
    "event-evolved-materialization-",
)


class DiagnosticSnapshotError(ValueError):
    """A fixed diagnostic code without retained data or raw storage exceptions."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(reason: str) -> None:
    raise DiagnosticSnapshotError("diagnostic_database_" + reason)


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _parent(database: Path) -> tuple[int, str]:
    path = database.expanduser().absolute()
    if ".." in path.parts or len(os.fsencode(path)) > _TEXT_BYTES or not path.name:
        _fail("unsafe")
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        for index, part in enumerate(path.parts[1:-1]):
            info = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
            # macOS exposes /var and /tmp as stable system symlinks. Permit only
            # these two root-level aliases; user workspace links remain unsafe.
            if stat.S_ISLNK(info.st_mode) and index == 0:
                if part not in {"var", "tmp"}:
                    _fail("unsafe")
            elif not stat.S_ISDIR(info.st_mode):
                _fail("unsafe")
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
            if not (stat.S_ISLNK(info.st_mode) and index == 0 and part in {"var", "tmp"}):
                flags |= os.O_NOFOLLOW
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            if not stat.S_ISLNK(info.st_mode) and (info.st_dev, info.st_ino) != (
                os.fstat(next_descriptor).st_dev, os.fstat(next_descriptor).st_ino
            ):
                os.close(next_descriptor)
                _fail("changed")
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor, path.name
    except BaseException:
        os.close(descriptor)
        raise


def _stat(parent: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _sources(parent: int, name: str, stack: ExitStack) -> dict[str, tuple[int, tuple[int, ...]] | None]:
    if _stat(parent, name + "-journal") is not None:
        _fail("journal_present")
    sources = {}
    total = 0
    for suffix, maximum in (("", MAX_DATABASE_BYTES), ("-wal", MAX_WAL_BYTES)):
        info = _stat(parent, name + suffix)
        if info is None:
            if not suffix:
                _fail("missing")
            sources[suffix] = None
            continue
        if not stat.S_ISREG(info.st_mode):
            _fail("unsafe")
        if info.st_size > maximum:
            _fail("limit_exceeded")
        total += info.st_size
        descriptor = os.open(
            name + suffix, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            dir_fd=parent,
        )
        stack.callback(os.close, descriptor)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or _identity(opened) != _identity(info):
            _fail("changed")
        sources[suffix] = descriptor, _identity(opened)
    if total > MAX_SOURCE_BYTES:
        _fail("limit_exceeded")
    return sources


def _unchanged(database: Path, parent: int, name: str, sources: dict) -> None:
    try:
        reopened, _ = _parent(database)
        try:
            before, after = os.fstat(parent), os.fstat(reopened)
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                _fail("changed")
        finally:
            os.close(reopened)
        if _stat(parent, name + "-journal") is not None:
            _fail("changed")
        for suffix, source in sources.items():
            current = _stat(parent, name + suffix)
            if source is None:
                if current is not None:
                    _fail("changed")
            elif current is None or _identity(current) != source[1] or _identity(os.fstat(source[0])) != source[1]:
                _fail("changed")
    except (OSError, DiagnosticSnapshotError):
        _fail("changed")


def _copy_file(descriptor: int, target: Path, size: int) -> None:
    # Never follow or reopen a source by its pathname after capturing the descriptor.
    with target.open("xb") as output:
        os.chmod(target, 0o600)
        remaining = size
        while remaining:
            data = os.read(descriptor, min(remaining, _CHUNK_BYTES))
            if not data:
                _fail("changed")
            output.write(data)
            remaining -= len(data)
        if os.read(descriptor, 1):
            _fail("changed")


def _check_wal(database: Path) -> None:
    """Reject obvious copied WAL damage that SQLite would otherwise silently ignore."""
    wal = Path(str(database) + "-wal")
    if not wal.exists() or wal.stat().st_size == 0:
        return
    with wal.open("rb") as source:
        header = source.read(32)
    if len(header) != 32:
        _fail("invalid")
    magic, version, page_size, _, _, _, first, second = struct.unpack(">8I", header)
    if (magic not in {0x377F0682, 0x377F0683} or version != 3007000
        or not 512 <= page_size <= 65536 or page_size & (page_size - 1)
        or (wal.stat().st_size - 32) % (page_size + 24)):
        _fail("invalid")
    words = struct.unpack("<6I" if magic == 0x377F0682 else ">6I", header[:24])
    checksum = [0, 0]
    for index in range(0, 6, 2):
        checksum[0] = (checksum[0] + words[index] + checksum[1]) & 0xFFFFFFFF
        checksum[1] = (checksum[1] + words[index + 1] + checksum[0]) & 0xFFFFFFFF
    if checksum != [first, second]:
        _fail("invalid")


def _temporary_root(database: Path) -> Path:
    # Ignore TMPDIR: it may point inside the source workspace. No temporary-probe
    # file or SQLite sidecar may be created there even if it would later be deleted.
    source = database.expanduser().absolute().parent
    for candidate in (Path("/tmp"), Path("/var/tmp")):
        resolved = candidate.resolve()
        if resolved.is_dir() and resolved != source and resolved not in source.parents:
            return resolved
    _fail("unsafe")


def _json(raw: Any, budget: list[int]) -> dict:
    if not isinstance(raw, str):
        _fail("invalid")
    size = len(raw.encode("utf-8"))
    budget[0] += size
    if size > MAX_PAYLOAD_BYTES or budget[0] > MAX_TOTAL_PAYLOAD_BYTES:
        _fail("limit_exceeded")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                _fail("invalid")
            result[key] = value
        return result

    def constant(_):
        _fail("invalid")

    value = json.loads(raw, object_pairs_hook=unique, parse_constant=constant)
    if not isinstance(value, dict):
        _fail("invalid")
    json.dumps(value, allow_nan=False)
    return value


def _text(value: Any, *, nullable: bool = False) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str) or len(value.encode("utf-8")) > _TEXT_BYTES or "\0" in value:
        _fail("invalid")


def _query(database: Path, parent_id: str, child_id: str) -> dict:
    suffix = hashlib.sha256(f"{parent_id}\0{child_id}".encode()).hexdigest()
    event_ids = tuple(prefix + suffix for prefix in _EVENT_PREFIXES)
    artifact_ids = tuple(prefix + suffix for prefix in (
        "artifact-materialization-execution-", "artifact-materialization-publication-",
    ))
    rows_read = 0
    payload_bytes = [0]
    steps = 0

    def progress():
        nonlocal steps
        steps += 100
        return int(steps > MAX_SQL_STEPS)

    with closing(sqlite3.connect(database.as_uri() + "?mode=rw", uri=True, timeout=0)) as connection:
        connection.row_factory = sqlite3.Row
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_PAYLOAD_BYTES + 16 * 1024)
        connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 16 * 1024)
        connection.set_progress_handler(progress, 100)
        connection.execute("PRAGMA trusted_schema = OFF")
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")

        def select(sql, parameters=()):
            nonlocal rows_read
            rows = []
            for row in connection.execute(sql + " LIMIT ?", (*parameters, MAX_ROWS + 1)):
                rows_read += 1
                if rows_read > MAX_ROWS:
                    _fail("limit_exceeded")
                value = dict(row)
                if "payload" in value:
                    value["payload"] = _json(value["payload"], payload_bytes)
                rows.append(value)
            return rows

        try:
            checked = connection.execute("PRAGMA quick_check(1)").fetchone()
            if checked is None or checked[0] != "ok":
                _fail("invalid")
            schema = select("SELECT name, type FROM sqlite_schema WHERE name IN ('runs','tasks','events','artifacts')")
            if {row["name"] for row in schema} != {"runs", "tasks", "events", "artifacts"} or any(
                row["type"] != "table" for row in schema
            ):
                _fail("invalid")
            runs = select("SELECT id, workspace FROM runs WHERE id IN (?, ?) ORDER BY id", (parent_id, child_id))
            if len(runs) != 2 or {row["id"] for row in runs} != {parent_id, child_id}:
                _fail("runs_missing")
            tasks = select("SELECT id, run_id FROM tasks WHERE run_id IN (?, ?) ORDER BY id", (parent_id, child_id))
            # Capture fixed pair IDs irrespective of their current owner/type. The candidate
            # execution ID also includes its candidate digest, so inspect its bounded prefix.
            events = select(
                "SELECT id, run_id, task_id, type, payload FROM events WHERE "
                "(run_id IN (?, ?) AND type IN (" + ",".join("?" for _ in _EVENT_TYPES) + ")) "
                "OR id IN (" + ",".join("?" for _ in event_ids) + ") "
                "OR id GLOB 'event-evolved-candidate-executed-*' ORDER BY id",
                (parent_id, child_id, *_EVENT_TYPES, *event_ids),
            )
            artifacts = select(
                "SELECT id, run_id, task_id, path, kind, size, sha256 FROM artifacts "
                "WHERE run_id IN (?, ?) OR id IN (?, ?) "
                "OR id GLOB 'artifact-output-publication-*' ORDER BY id",
                (parent_id, child_id, *artifact_ids),
            )
        except sqlite3.Error as exc:
            if steps > MAX_SQL_STEPS:
                _fail("query_limit")
            if isinstance(exc, sqlite3.DataError):
                _fail("limit_exceeded")
            _fail("invalid")
    for row in runs:
        _text(row["id"])
        _text(row["workspace"])
    for row in tasks:
        _text(row["id"])
        _text(row["run_id"])
    observed_events = []
    for row in events:
        for key in ("id", "run_id", "type"):
            _text(row[key])
        _text(row["task_id"], nullable=True)
        candidate = row["payload"].get("candidate_sha256")
        derived = "event-evolved-candidate-executed-" + hashlib.sha256(
            f"{parent_id}\0{child_id}\0{candidate}".encode()
        ).hexdigest() if isinstance(candidate, str) else None
        if row["run_id"] in {parent_id, child_id} or row["id"] in event_ids or row["id"] == derived:
            observed_events.append(row)
    observed_artifacts = []
    for row in artifacts:
        for key in ("id", "run_id", "task_id", "path", "kind", "sha256"):
            _text(row[key])
        if type(row["size"]) is not int:
            _fail("invalid")
        derived = "artifact-output-publication-" + hashlib.sha256(
            f"{parent_id}\0{child_id}\0{row['path']}".encode()
        ).hexdigest()
        if row["run_id"] in {parent_id, child_id} or row["id"] in artifact_ids or row["id"] == derived:
            observed_artifacts.append(row)
    return {"runs": runs, "tasks": tasks, "events": observed_events, "artifacts": observed_artifacts}


def diagnostic_snapshot(database: Path, parent_id: str, child_id: str) -> dict:
    """Return a bounded copied observation; never open or initialize the source with SQLite."""
    if parent_id == child_id or any(
        not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value) is None
        for value in (parent_id, child_id)
    ):
        raise DiagnosticSnapshotError("diagnostic_run_identity_invalid")
    try:
        with ExitStack() as stack:
            parent, name = _parent(Path(database))
            stack.callback(os.close, parent)
            sources = _sources(parent, name, stack)
            with tempfile.TemporaryDirectory(prefix="lunar-diagnostic-", dir=_temporary_root(Path(database))) as temporary:
                copied = Path(temporary) / "snapshot.db"
                for suffix, source in sources.items():
                    if source is not None:
                        _copy_file(source[0], Path(str(copied) + suffix), source[1][2])
                _unchanged(Path(database), parent, name, sources)
                _check_wal(copied)
                result = _query(copied, parent_id, child_id)
                _unchanged(Path(database), parent, name, sources)
                return result
    except DiagnosticSnapshotError:
        raise
    except FileNotFoundError:
        _fail("missing")
    except OSError:
        _fail("unreadable")
    except (sqlite3.Error, ValueError, TypeError, RecursionError, OverflowError):
        _fail("invalid")
