"""Read-only database snapshots for the semantic acceptance auditor.

The helper deliberately keeps the source database outside the SQLite connection.  A bounded
database/WAL copy is made by :mod:`materialization_attestation`; callers receive a ``Store``
compatible object whose connections are read-only and whose event reader exposes SQLite's
insertion sequence (``rowid``) instead of treating timestamps as an ordering authority.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .materialization_attestation import _snapshot_store
from .store import Store

MAX_EVENT_ROWS = 4096
MAX_EVENT_PAYLOAD_BYTES = 64 * 1024
MAX_EVENT_PAYLOAD_TOTAL_BYTES = 8 * 1024 * 1024
MAX_SQL_STEPS = 2_000_000


class AuditSnapshotError(ValueError):
    """A bounded snapshot could not be inspected; the code contains no source path."""

    def __init__(self, code: str) -> None:
        allowed = {
            "invalid", "missing", "changed", "limit_exceeded", "query_limit",
            "payload_invalid", "schema_invalid", "events_invalid",
        }
        self.code = code if code in allowed else "invalid"
        super().__init__("audit_snapshot_" + self.code)


def _fail(code: str) -> None:
    raise AuditSnapshotError(code) from None


def _bounded_id(value: object) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 4096 or "\x00" in value:
        _fail("events_invalid")
    return value


def _payload(raw: object, total: list[int]) -> dict[str, Any]:
    if not isinstance(raw, str):
        _fail("payload_invalid")
    size = len(raw.encode("utf-8"))
    total[0] += size
    if size > MAX_EVENT_PAYLOAD_BYTES or total[0] > MAX_EVENT_PAYLOAD_TOTAL_BYTES:
        _fail("limit_exceeded")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                _fail("payload_invalid")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda _value: _fail("payload_invalid"),
        )
    except AuditSnapshotError:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError):
        _fail("payload_invalid")
    if not isinstance(value, dict):
        _fail("payload_invalid")
    return value


def _readonly_authorizer(action: int, first: object, second: object, *_args: object) -> int:
    # The copy is already opened read-only, but the authorizer makes accidental writes and
    # schema changes fail even if a future caller uses a lower-level Store method.
    denied = {
        sqlite3.SQLITE_CREATE_INDEX, sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_CREATE_TEMP_INDEX,
        sqlite3.SQLITE_CREATE_TEMP_TABLE, sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
        sqlite3.SQLITE_CREATE_TEMP_VIEW, sqlite3.SQLITE_CREATE_TRIGGER, sqlite3.SQLITE_CREATE_VIEW,
        sqlite3.SQLITE_DELETE, sqlite3.SQLITE_DROP_INDEX, sqlite3.SQLITE_DROP_TABLE,
        sqlite3.SQLITE_DROP_TEMP_INDEX, sqlite3.SQLITE_DROP_TEMP_TABLE,
        sqlite3.SQLITE_DROP_TEMP_TRIGGER, sqlite3.SQLITE_DROP_TEMP_VIEW,
        sqlite3.SQLITE_DROP_TRIGGER, sqlite3.SQLITE_DROP_VIEW, sqlite3.SQLITE_INSERT,
        sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_ALTER_TABLE, sqlite3.SQLITE_ATTACH,
        sqlite3.SQLITE_DETACH, sqlite3.SQLITE_REINDEX, sqlite3.SQLITE_ANALYZE,
    }
    if action == sqlite3.SQLITE_PRAGMA and second is not None and first not in {"table_xinfo"}:
        return sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION and second == "load_extension":
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_DENY if action in denied else sqlite3.SQLITE_OK


class AuditStore(Store):
    """A ``Store`` view whose connections cannot initialize or mutate the snapshot."""

    def __init__(self, database: str | Path) -> None:
        super().__init__(database)
        self._connections: list[sqlite3.Connection] = []
        self._closed = False

    def _close(self) -> None:
        self._closed = True
        for connection in self._connections:
            connection.close()
        self._connections.clear()

    def _connect(self) -> sqlite3.Connection:
        if self._closed:
            _fail("invalid")
        connection = None
        try:
            connection = sqlite3.connect(
                self.database.as_uri() + "?mode=ro", uri=True, timeout=5,
            )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only = ON")
            connection.execute("PRAGMA trusted_schema = OFF")
            connection.set_authorizer(_readonly_authorizer)
            connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_EVENT_PAYLOAD_BYTES + 16 * 1024)
            connection.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 16 * 1024)
            connection.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 128)
            steps = 0

            def progress() -> int:
                nonlocal steps
                steps += 100
                return int(steps > MAX_SQL_STEPS)

            connection.set_progress_handler(progress, 100)
            self._connections.append(connection)
            return connection
        except sqlite3.Error:
            if connection is not None:
                connection.close()
            raise AuditSnapshotError("invalid") from None

    def list_events(self, run_id: str) -> list[dict[str, Any]]:
        return audit_events(self, run_id)


def audit_events(
    store: AuditStore,
    parent_id: str,
    child_id: str | None = None,
) -> list[dict[str, Any]]:
    """Read bounded events with durable SQLite ``rowid`` sequence numbers.

    ``created_at`` is retained for display only; callers must use ``sequence`` for ordering.
    """

    if not isinstance(store, AuditStore):
        _fail("events_invalid")
    parent_id = _bounded_id(parent_id)
    if child_id is not None:
        child_id = _bounded_id(child_id)
        ids = (parent_id, child_id)
    else:
        ids = (parent_id,)
    placeholders = ",".join("?" for _ in ids)
    total = [0]
    try:
        with store._connect() as connection:
            cursor = connection.execute(
                "SELECT rowid AS sequence, id, run_id, task_id, type, payload, created_at "
                f"FROM events WHERE run_id IN ({placeholders}) ORDER BY rowid LIMIT ?",
                (*ids, MAX_EVENT_ROWS + 1),
            )
            rows = []
            for row in cursor:
                if len(rows) >= MAX_EVENT_ROWS:
                    _fail("limit_exceeded")
                item = dict(row)
                item["payload"] = _payload(item["payload"], total)
                rows.append(item)
    except AuditSnapshotError:
        raise
    except sqlite3.OperationalError as exc:
        if "interrupted" in str(exc).lower():
            _fail("query_limit")
        _fail("events_invalid")
    except sqlite3.DataError:
        _fail("limit_exceeded")
    except sqlite3.Error:
        _fail("events_invalid")
    if len(rows) > MAX_EVENT_ROWS:
        _fail("limit_exceeded")
    result: list[dict[str, Any]] = []
    previous_sequence = 0
    for row in rows:
        if (type(row["sequence"]) is not int or row["sequence"] <= previous_sequence
                or row["sequence"] < 1):
            _fail("events_invalid")
        previous_sequence = row["sequence"]
        for key in ("id", "run_id", "type"):
            _bounded_id(row[key])
        task_id = row["task_id"]
        if task_id is not None:
            _bounded_id(task_id)
        result.append({
            "sequence": row["sequence"], "id": row["id"], "run_id": row["run_id"],
            "task_id": task_id, "type": row["type"], "payload": row["payload"],
            "created_at": row["created_at"],
        })
    return result


@contextmanager
def audit_snapshot(database: str | Path) -> Iterator[AuditStore]:
    """Yield a read-only ``Store`` backed by a bounded private DB/WAL snapshot."""

    try:
        with _snapshot_store(Path(database)) as copied:
            view = AuditStore(copied.database)
            try:
                with view._connect() as connection:
                    rows = connection.execute(
                        "SELECT name, type FROM sqlite_schema WHERE name IN "
                        "('runs','tasks','events','artifacts')",
                    ).fetchall()
                    if ({row["name"] for row in rows} != {"runs", "tasks", "events", "artifacts"}
                            or any(row["type"] != "table" for row in rows)):
                        _fail("schema_invalid")
                    event_columns = connection.execute("PRAGMA table_xinfo(events)").fetchall()
                    if any(row["name"].lower() in {"rowid", "_rowid_", "oid"}
                           for row in event_columns):
                        _fail("schema_invalid")
                yield view
            finally:
                view._close()
    except AuditSnapshotError:
        raise
    except (OSError, sqlite3.Error, TypeError, ValueError, RecursionError) as exc:
        code = getattr(exc, "code", "")
        if code == "diagnostic_database_changed":
            raise AuditSnapshotError("changed") from None
        if code == "diagnostic_database_limit_exceeded":
            raise AuditSnapshotError("limit_exceeded") from None
        raise AuditSnapshotError("invalid") from None


__all__ = [
    "MAX_EVENT_PAYLOAD_BYTES",
    "MAX_EVENT_PAYLOAD_TOTAL_BYTES",
    "MAX_EVENT_ROWS",
    "AuditSnapshotError",
    "AuditStore",
    "audit_events",
    "audit_snapshot",
]
