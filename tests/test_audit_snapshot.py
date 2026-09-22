from __future__ import annotations

import gc
import json
import sqlite3
from pathlib import Path

import pytest

from lunar_evolution._audit_snapshot import AuditSnapshotError, audit_events, audit_snapshot
from lunar_evolution.store import Store


@pytest.fixture(autouse=True)
def retained_fixture_connections(monkeypatch):
    """Keep fixture writers alive until teardown, preventing incidental GC checkpoints.

    sqlite3.Connection.__exit__ commits but does not close. Store fixtures otherwise leave
    unreachable connections whose collection can checkpoint the source WAL during an audit.
    AuditStore overrides _connect, so this only retains the fixture's source connections.
    """
    original = Store._connect
    connections = []

    def connect(store):
        connection = original(store)
        connections.append(connection)
        return connection

    monkeypatch.setattr(Store, "_connect", connect)
    yield connections
    for connection in connections:
        connection.close()


def source_state(database: Path):
    return {
        path.name: (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns,
                    path.stat().st_ctime_ns, path.stat().st_mode)
        for path in database.parent.iterdir() if path.is_file()
    }


def test_snapshot_reads_rowid_order_and_closes_without_source_side_effects(tmp_path: Path):
    database = tmp_path / "state.db"
    store = Store(database)
    store.initialize()
    run = store.create_run("fixture", tmp_path / "run")
    store.append_event(run.id, "first", {"n": 1})
    store.append_event(run.id, "second", {"n": 2})
    before = source_state(database)
    with audit_snapshot(database) as view:
        gc.collect()  # Forced collection cannot release explicitly retained fixture writers.
        events = audit_events(view, run.id)
        assert [event["type"] for event in events][-2:] == ["first", "second"]
        assert [event["sequence"] for event in events] == sorted(event["sequence"] for event in events)
        with pytest.raises(sqlite3.DatabaseError):
            view.initialize()
        connections = list(view._connections)
        assert view.get_run(run.id).id == run.id
        assert view.list_events(run.id) == events
    assert source_state(database) == before
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    with pytest.raises(AuditSnapshotError, match="invalid"):
        view.get_run(run.id)


def test_gc_checkpoint_is_a_real_source_change(tmp_path, retained_fixture_connections):
    """Reproduce the flake's cause without weakening production change detection."""
    store = Store(tmp_path / "state.db")
    store.initialize()
    for connection in retained_fixture_connections:
        connection.close()
    retained_fixture_connections.clear()

    class CyclicConnection(sqlite3.Connection):
        pass

    was_enabled = gc.isenabled()
    gc.disable()
    try:
        connection = sqlite3.connect(store.database, factory=CyclicConnection)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("INSERT INTO schema_migrations(version,applied_at) VALUES (999,'fixture')")
        connection.commit()
        connection.cycle = connection
        del connection
        wal = Path(str(store.database) + "-wal")
        assert wal.is_file() and wal.stat().st_size > 0
        before = source_state(store.database)
        with pytest.raises(AuditSnapshotError, match="audit_snapshot_changed"), audit_snapshot(store.database):
            gc.collect()
            assert source_state(store.database) != before
            assert not wal.exists()  # Last writer collection checkpointed and removed its WAL.
    finally:
        if was_enabled:
            gc.enable()


def test_snapshot_rejects_missing_or_non_store_and_does_not_create_files(tmp_path: Path):
    missing = tmp_path / "missing" / "state.db"
    with pytest.raises(AuditSnapshotError, match="audit_snapshot_"), audit_snapshot(missing):
        pass
    with pytest.raises(AuditSnapshotError, match="events_invalid"):
        audit_events(object(), "run")
    assert not missing.parent.exists()


def test_events_payload_is_bounded_and_duplicate_json_keys_rejected(tmp_path: Path):
    database = tmp_path / "state.db"
    store = Store(database)
    store.initialize()
    run = store.create_run("fixture", tmp_path / "run")
    with store._connect() as connection:
        connection.execute(
            "INSERT INTO events (id, run_id, type, payload, created_at) VALUES (?, ?, ?, ?, ?)",
            ("bad", run.id, "bad", '{"x":1,"x":2}', "2026-01-01T00:00:00+00:00"),
        )
    with audit_snapshot(database) as view, pytest.raises(AuditSnapshotError, match="payload_invalid"):
        audit_events(view, run.id)


@pytest.mark.parametrize("raw,reason", [
    ('{"x":"' + "x" * (64 * 1024) + '"}', "limit_exceeded"),
    ('{"x":NaN}', "payload_invalid"),
    ('[]', "payload_invalid"),
])
def test_invalid_payloads(tmp_path, raw, reason):
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("fixture", tmp_path / "run")
    with store._connect() as connection:
        connection.execute("UPDATE events SET payload = ? WHERE run_id = ?", (raw, run.id))
    before = source_state(store.database)
    with audit_snapshot(store.database) as view, pytest.raises(AuditSnapshotError, match=reason):
        audit_events(view, run.id)
    assert source_state(store.database) == before


@pytest.mark.parametrize("count,size", [(4097, 0), (140, 63000)])
def test_event_aggregate_limits(tmp_path, count, size):
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("fixture", tmp_path / "run")
    with store._connect() as connection:
        connection.executemany(
            "INSERT INTO events (id,run_id,type,payload,created_at) VALUES (?,?,?,?,?)",
            ((f"event-{i}", run.id, "fixture", json.dumps({"data": "x" * size}), "time")
             for i in range(count)),
        )
    with (
        audit_snapshot(store.database) as view,
        pytest.raises(AuditSnapshotError, match="limit_exceeded"),
    ):
        audit_events(view, run.id)


def test_parent_child_insertion_order_ignores_timestamps(tmp_path):
    store = Store(tmp_path / "state.db")
    store.initialize()
    parent = store.create_run("parent", tmp_path / "parent")
    child = store.create_run("child", tmp_path / "child")
    store.append_event(parent.id, "first", {})
    store.append_event(child.id, "second", {})
    with store._connect() as connection:
        connection.execute("UPDATE events SET created_at = '9999' WHERE type = 'first'")
        connection.execute("UPDATE events SET created_at = '0000' WHERE type = 'second'")
    with audit_snapshot(store.database) as view:
        events = audit_events(view, parent.id, child.id)
        assert [event["type"] for event in events][-2:] == ["first", "second"]
        assert events[-2]["run_id"] == parent.id and events[-1]["run_id"] == child.id


def test_source_change_during_snapshot_is_rejected_after_consistent_reads(tmp_path):
    store = Store(tmp_path / "state.db")
    store.initialize()
    run = store.create_run("fixture", tmp_path / "run")
    with pytest.raises(AuditSnapshotError, match="changed"), audit_snapshot(store.database) as view:
        original = view.list_events(run.id)
        store.append_event(run.id, "concurrent", {})
        assert view.list_events(run.id) == original


def test_sql_step_limit_and_write_operations_are_blocked(tmp_path, monkeypatch):
    import lunar_evolution._audit_snapshot as module

    store = Store(tmp_path / "state.db")
    store.initialize()
    monkeypatch.setattr(module, "MAX_SQL_STEPS", 1000)
    with audit_snapshot(store.database) as view, view._connect() as connection:
        for statement in (
            "PRAGMA query_only=OFF", "CREATE TABLE injected (data TEXT)",
            "ATTACH DATABASE ':memory:' AS injected", "DELETE FROM events",
        ):
            with pytest.raises(sqlite3.DatabaseError):
                connection.execute(statement)
        with pytest.raises(sqlite3.OperationalError, match="interrupted"):
            connection.execute(
                "WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<100000) "
                "SELECT sum(x) FROM n",
            ).fetchone()


def test_no_initialization_or_live_sqlite_open(tmp_path, monkeypatch):
    store = Store(tmp_path / "state.db")
    store.initialize()
    original = sqlite3.connect
    connections = []

    def connect(database, **kwargs):
        assert str(store.database) not in str(database)
        connections.append(database)
        return original(database, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    monkeypatch.setattr(Store, "initialize", lambda _: pytest.fail("must not initialize"))
    with audit_snapshot(store.database) as view:
        assert audit_events(view, "missing-run") == []
    assert connections


def test_empty_schema_is_rejected_without_migration(tmp_path):
    database = tmp_path / "state.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE marker(x)")
    before = source_state(database)
    with pytest.raises(AuditSnapshotError, match="schema_invalid"), audit_snapshot(database):
        pytest.fail("invalid schema admitted")
    assert source_state(database) == before


@pytest.mark.parametrize("name", ["rowid", "_rowid_", "oid", "ROWID"])
def test_shadowed_sqlite_sequence_is_rejected(tmp_path, name):
    store = Store(tmp_path / "state.db")
    store.initialize()
    with store._connect() as connection:
        connection.execute(f'ALTER TABLE events ADD COLUMN "{name}" INTEGER')
    with pytest.raises(AuditSnapshotError, match="schema_invalid"), audit_snapshot(store.database):
        pytest.fail("shadowed rowid admitted")
