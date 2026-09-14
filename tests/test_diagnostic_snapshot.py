"""Source DB/WAL bytes remain untouched while SQLite reads a bounded private copy."""

import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

import famou.diagnostic_snapshot as snapshot
from famou.diagnostic_snapshot import DiagnosticSnapshotError, diagnostic_snapshot

PARENT = "parent-1"
CHILD = "child-1"
SCHEMA = """
CREATE TABLE runs(id TEXT PRIMARY KEY, workspace TEXT NOT NULL, goal TEXT);
CREATE TABLE tasks(id TEXT PRIMARY KEY, run_id TEXT NOT NULL, title TEXT);
CREATE TABLE events(id TEXT PRIMARY KEY, run_id TEXT, task_id TEXT, type TEXT, payload TEXT);
CREATE TABLE artifacts(id TEXT PRIMARY KEY, run_id TEXT, task_id TEXT, path TEXT, kind TEXT, size INTEGER, sha256 TEXT);
"""


def seed(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(SCHEMA)
        connection.executemany("INSERT INTO runs VALUES(?,?,?)", [
            (PARENT, str(path.parent / "parent"), "private parent goal"),
            (CHILD, str(path.parent / "child"), "private child goal"),
        ])
        connection.executemany("INSERT INTO tasks VALUES(?,?,?)", [
            ("parent-task", PARENT, "private title"), ("child-task", CHILD, "private title"),
        ])
        connection.execute("INSERT INTO events VALUES(?,?,?,?,?)", (
            "launch", CHILD, "child-task", "materialization_launch_intended", '{"intent_sha256":"observed"}',
        ))
        connection.execute("INSERT INTO events VALUES(?,?,?,?,?)", (
            "noise", CHILD, "child-task", "solver_log", '{"private_log":"private log"}',
        ))
        connection.execute("INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)", (
            "artifact", CHILD, "child-task", "evolution/materialization/result.json", "evolved_materialization", 2, "a" * 64,
        ))
        connection.commit()
    finally:
        connection.close()


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "source" / "state.db"
    path.parent.mkdir()
    seed(path)
    return path


def source_state(database: Path) -> dict:
    return {
        str(path.relative_to(database.parent)): (
            path.read_bytes() if path.is_file() and not path.is_symlink() else None,
            path.lstat().st_mode, path.lstat().st_ino, path.lstat().st_mtime_ns, path.lstat().st_ctime_ns,
        ) for path in database.parent.rglob("*")
    }


def inspect(database: Path) -> dict:
    return diagnostic_snapshot(database, PARENT, CHILD)


def reject(database: Path, code: str) -> None:
    before = source_state(database)
    with pytest.raises(DiagnosticSnapshotError, match="^" + code + "$") as caught:
        inspect(database)
    assert caught.value.code == code
    assert source_state(database) == before


def test_checkpointed_wal_database_without_sidecars_uses_only_temporary_sqlite(database: Path, monkeypatch) -> None:
    assert database.read_bytes()[18:20] == b"\x02\x02"
    assert list(database.parent.iterdir()) == [database]
    before = source_state(database)
    original = sqlite3.connect
    opened = []

    def connect(path, **kwargs):
        copied = Path(unquote(urlparse(path).path))
        assert copied != database and database.parent not in copied.parents
        assert str(path).endswith("?mode=rw") and kwargs["uri"] is True
        opened.append(copied)
        return original(path, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    value = inspect(database)
    assert set(value) == {"runs", "tasks", "events", "artifacts"}
    assert len(value["runs"]) == len(value["tasks"]) == 2
    assert all(set(row) == {"id", "workspace"} for row in value["runs"])
    assert all(set(row) == {"id", "run_id"} for row in value["tasks"])
    assert [row["id"] for row in value["events"]] == ["launch"]
    assert value["events"][0]["payload"] == {"intent_sha256": "observed"}
    assert set(value["events"][0]) == {"id", "run_id", "task_id", "type", "payload"}
    assert set(value["artifacts"][0]) == {"id", "run_id", "task_id", "path", "kind", "size", "sha256"}
    assert all(secret not in json.dumps(value) for secret in ("private parent goal", "private child goal", "private title", "private log"))
    assert source_state(database) == before
    assert len(opened) == 1 and not opened[0].parent.exists()


def test_uncheckpointed_committed_wal_is_visible_without_source_changes(database: Path) -> None:
    writer = sqlite3.connect(database)
    try:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO events VALUES(?,?,?,?,?)", (
            "wal-only", CHILD, "child-task", "materialization_delivery_prepared", '{"plan_size":37}',
        ))
        writer.commit()
        assert Path(str(database) + "-wal").stat().st_size > 0
        before = source_state(database)
        assert {row["id"] for row in inspect(database)["events"]} == {"launch", "wal-only"}
        assert source_state(database) == before
    finally:
        writer.close()


def test_retained_wal_without_source_shm_is_reconstructed_only_in_copy(database: Path) -> None:
    writer = sqlite3.connect(database)
    writer.execute("INSERT INTO events VALUES(?,?,?,?,?)", (
        "retained-wal", CHILD, "child-task", "materialization_execution_committed", '{}',
    ))
    writer.commit()
    main = database.read_bytes()
    wal = Path(str(database) + "-wal").read_bytes()
    writer.close()
    database.write_bytes(main)
    Path(str(database) + "-wal").write_bytes(wal)
    assert not Path(str(database) + "-shm").exists()
    before = source_state(database)
    assert "retained-wal" in {row["id"] for row in inspect(database)["events"]}
    assert source_state(database) == before


def test_source_shm_is_never_opened_or_copied(database: Path, monkeypatch) -> None:
    shm = Path(str(database) + "-shm")
    shm.write_bytes(b"ignored wal index")
    original = os.open

    def open_file(path, *args, **kwargs):
        assert not str(path).endswith("-shm")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", open_file)
    before = source_state(database)
    assert len(inspect(database)["runs"]) == 2
    assert source_state(database) == before


def test_temporary_environment_cannot_redirect_sqlite_into_source(database: Path, monkeypatch) -> None:
    monkeypatch.setenv("TMPDIR", str(database.parent))
    monkeypatch.setattr(tempfile, "tempdir", str(database.parent))
    original = sqlite3.connect

    def connect(path, **kwargs):
        copied = Path(unquote(urlparse(path).path))
        assert database.parent not in copied.parents
        return original(path, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    before = source_state(database)
    assert len(inspect(database)["runs"]) == 2
    assert source_state(database) == before


@pytest.mark.parametrize("damage", ["short", "header", "checksum", "partial_frame"])
def test_obviously_damaged_wal_cannot_silently_downgrade_to_main_database(database: Path, damage: str) -> None:
    writer = sqlite3.connect(database)
    writer.execute("INSERT INTO events VALUES(?,?,?,?,?)", (
        "retained-wal", CHILD, "child-task", "materialization_execution_committed", '{}',
    ))
    writer.commit()
    main = database.read_bytes()
    wal = bytearray(Path(str(database) + "-wal").read_bytes())
    writer.close()
    if damage == "short":
        wal = wal[:5]
    elif damage == "header":
        wal[:4] = b"oops"
    elif damage == "checksum":
        wal[24] ^= 1
    else:
        wal = wal[:-1]
    database.write_bytes(main)
    Path(str(database) + "-wal").write_bytes(wal)
    reject(database, "diagnostic_database_invalid")


@pytest.mark.parametrize("kind", ["missing", "empty", "garbage", "schema", "missing_run", "duplicate_run", "view"])
def test_bad_or_missing_storage_is_bounded_and_never_initialized(database: Path, kind: str) -> None:
    code = "diagnostic_database_invalid"
    if kind == "missing":
        database.unlink()
        code = "diagnostic_database_missing"
    elif kind in {"empty", "garbage"}:
        database.write_bytes(b"" if kind == "empty" else b"private corrupt storage")
    else:
        with sqlite3.connect(database) as connection:
            if kind == "schema":
                connection.execute("DROP TABLE events")
            elif kind == "missing_run":
                connection.execute("DELETE FROM runs WHERE id=?", (CHILD,))
                code = "diagnostic_database_runs_missing"
            elif kind == "duplicate_run":
                connection.execute("ALTER TABLE runs RENAME TO old_runs")
                connection.execute("CREATE TABLE runs AS SELECT * FROM old_runs")
                connection.execute("INSERT INTO runs SELECT * FROM old_runs WHERE id=?", (CHILD,))
                code = "diagnostic_database_runs_missing"
            else:
                connection.execute("ALTER TABLE events RENAME TO old_events")
                connection.execute("CREATE VIEW events AS SELECT * FROM old_events")
    reject(database, code)


def test_missing_parent_directory_is_not_created(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "state.db"
    with pytest.raises(DiagnosticSnapshotError, match="^diagnostic_database_missing$"):
        inspect(path)
    assert not path.parent.exists()


@pytest.mark.parametrize("suffix", ["", "-wal"])
@pytest.mark.parametrize("kind", ["symlink", "fifo", "directory"])
def test_unsafe_main_or_wal_nodes_are_rejected_before_open(database: Path, suffix: str, kind: str) -> None:
    target = Path(str(database) + suffix)
    if target.exists():
        target.unlink()
    if kind == "symlink":
        target.symlink_to(database.parent / "absent-target")
    elif kind == "fifo":
        os.mkfifo(target)
    else:
        target.mkdir()
    # source_state deliberately never reads FIFOs.
    reject(database, "diagnostic_database_unsafe")


def test_symlinked_source_parent_is_rejected(database: Path) -> None:
    alias = database.parent.parent / "alias"
    alias.symlink_to(database.parent, target_is_directory=True)
    with pytest.raises(DiagnosticSnapshotError, match="^diagnostic_database_unsafe$"):
        inspect(alias / database.name)


@pytest.mark.parametrize("kind", ["file", "symlink", "fifo", "directory"])
def test_rollback_journal_is_never_recovered(database: Path, kind: str) -> None:
    path = Path(str(database) + "-journal")
    if kind == "file":
        path.write_bytes(b"retained rollback journal")
    elif kind == "symlink":
        path.symlink_to(database)
    elif kind == "fifo":
        os.mkfifo(path)
    else:
        path.mkdir()
    reject(database, "diagnostic_database_journal_present")


@pytest.mark.parametrize("limit", ["MAX_DATABASE_BYTES", "MAX_WAL_BYTES", "MAX_SOURCE_BYTES", "MAX_ROWS", "MAX_PAYLOAD_BYTES", "MAX_TOTAL_PAYLOAD_BYTES"])
def test_limits_decline_instead_of_returning_truncated_absence(database: Path, monkeypatch, limit: str) -> None:
    if limit == "MAX_WAL_BYTES":
        Path(str(database) + "-wal").write_bytes(b"x" * 32)
    monkeypatch.setattr(snapshot, limit, 1)
    reject(database, "diagnostic_database_limit_exceeded")


def test_sql_instruction_budget_is_enforced(database: Path, monkeypatch) -> None:
    monkeypatch.setattr(snapshot, "MAX_SQL_STEPS", 0)
    reject(database, "diagnostic_database_query_limit")


@pytest.mark.parametrize("raw", ["{", "[]", '{"x":NaN}', '{"x":1e999}', '{"x":1,"x":2}', '{"private":"' + "x" * 66000 + '"}'])
def test_malformed_and_excessive_payloads_do_not_escape(database: Path, raw: str) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE events SET payload=? WHERE id='launch'", (raw,))
    reject(database, "diagnostic_database_limit_exceeded" if len(raw) > 65536 else "diagnostic_database_invalid")


@pytest.mark.parametrize("change", ["main_write", "main_replace", "wal_appears", "wal_disappears", "wal_write", "journal_appears", "parent_replace"])
def test_copy_rejects_concurrent_file_group_changes(database: Path, monkeypatch, change: str) -> None:
    wal = Path(str(database) + "-wal")
    if change in {"wal_disappears", "wal_write"}:
        wal.write_bytes(b"")
    original = snapshot._copy_file
    changed = False

    def copy(descriptor, target, size):
        nonlocal changed
        original(descriptor, target, size)
        if changed:
            return
        changed = True
        if change == "main_write":
            with database.open("ab") as output:
                output.write(b"change")
        elif change == "main_replace":
            replacement = database.with_name("replacement")
            replacement.write_bytes(database.read_bytes())
            replacement.replace(database)
        elif change == "wal_appears":
            wal.write_bytes(b"")
        elif change == "wal_disappears":
            wal.unlink()
        elif change == "wal_write":
            wal.write_bytes(b"change")
        elif change == "journal_appears":
            Path(str(database) + "-journal").write_bytes(b"")
        else:
            database.parent.rename(database.parent.with_name("moved"))
            database.parent.mkdir()
    monkeypatch.setattr(snapshot, "_copy_file", copy)
    with pytest.raises(DiagnosticSnapshotError, match="^diagnostic_database_changed$"):
        inspect(database)


def test_source_change_during_sql_query_declines_the_report(database: Path, monkeypatch) -> None:
    original = snapshot._query

    def query(*args):
        result = original(*args)
        with database.open("ab") as output:
            output.write(b"change")
        return result

    monkeypatch.setattr(snapshot, "_query", query)
    with pytest.raises(DiagnosticSnapshotError, match="^diagnostic_database_changed$"):
        inspect(database)


def test_read_open_and_query_errors_are_fixed_and_temporary_storage_is_cleaned(database: Path, monkeypatch) -> None:
    opened = []

    def connect(path, **kwargs):
        opened.append(Path(unquote(urlparse(path).path)))
        raise sqlite3.OperationalError("private diagnostic including absolute paths")

    monkeypatch.setattr(sqlite3, "connect", connect)
    reject(database, "diagnostic_database_invalid")
    assert len(opened) == 1 and not opened[0].parent.exists()


def test_unreadable_source_uses_no_sqlite_or_raw_os_diagnostics(database: Path, monkeypatch) -> None:
    original = os.open

    def open_file(path, *args, **kwargs):
        if str(path) == database.name:
            raise PermissionError("private source path")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", open_file)
    reject(database, "diagnostic_database_unreadable")


def test_reserved_pair_ids_are_retained_after_owner_and_type_drift(database: Path) -> None:
    suffix = hashlib.sha256(f"{PARENT}\0{CHILD}".encode()).hexdigest()
    candidate = "b" * 64
    executed = "event-evolved-candidate-executed-" + hashlib.sha256(f"{PARENT}\0{CHILD}\0{candidate}".encode()).hexdigest()
    path = "output/routes.csv"
    output = "artifact-output-publication-" + hashlib.sha256(f"{PARENT}\0{CHILD}\0{path}".encode()).hexdigest()
    with sqlite3.connect(database) as connection:
        for prefix in snapshot._EVENT_PREFIXES:
            connection.execute("INSERT INTO events VALUES(?,?,?,?,?)", (prefix + suffix, "foreign", None, "unrelated", "{}"))
        connection.execute("INSERT INTO events VALUES(?,?,?,?,?)", (executed, "foreign", None, "unrelated", json.dumps({"candidate_sha256": candidate})))
        connection.execute("INSERT INTO events VALUES(?,?,?,?,?)", ("event-evolved-candidate-executed-other", "foreign", None, "unrelated", "{}"))
        for identity in ("artifact-materialization-execution-" + suffix, "artifact-materialization-publication-" + suffix, output):
            connection.execute("INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)", (identity, "foreign", "foreign-task", path, "unrelated", 7, "c" * 64))
        connection.execute("INSERT INTO artifacts VALUES(?,?,?,?,?,?,?)", ("artifact-output-publication-other", "foreign", "foreign-task", path, "output", 7, "c" * 64))
    before = source_state(database)
    value = inspect(database)
    event_ids = {row["id"] for row in value["events"]}
    assert {prefix + suffix for prefix in snapshot._EVENT_PREFIXES} <= event_ids
    assert executed in event_ids and "event-evolved-candidate-executed-other" not in event_ids
    artifact_ids = {row["id"] for row in value["artifacts"]}
    assert output in artifact_ids and "artifact-output-publication-other" not in artifact_ids
    assert source_state(database) == before


@pytest.mark.parametrize("parent,child", [(PARENT, PARENT), ("", CHILD), ("../parent", CHILD), (PARENT, None), (True, CHILD)])
def test_invalid_run_ids_are_rejected_without_opening_storage(database: Path, monkeypatch, parent, child) -> None:
    def forbidden(*args, **kwargs):
        raise AssertionError("must not open source")

    monkeypatch.setattr(snapshot, "_parent", forbidden)
    with pytest.raises(DiagnosticSnapshotError, match="^diagnostic_run_identity_invalid$"):
        diagnostic_snapshot(database, parent, child)
