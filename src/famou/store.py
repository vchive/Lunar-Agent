"""Durable SQLite state for local runs.

The store deliberately exposes small operations instead of leaking SQL into the controller. Every
mutating operation emits an event, and event IDs are idempotency keys.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import Attempt, Run, RunStatus, Task, TaskStatus


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    goal TEXT NOT NULL,
    status TEXT NOT NULL,
    workspace TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    parent_id TEXT REFERENCES tasks(id),
    title TEXT NOT NULL,
    prompt TEXT NOT NULL,
    state TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    result_path TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tasks_run_state_idx ON tasks(run_id, state, created_at);
CREATE TABLE IF NOT EXISTS attempts (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    runtime TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    heartbeat_at TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    task_id TEXT REFERENCES tasks(id),
    type TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_run_idx ON events(run_id, created_at);
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    task_id TEXT NOT NULL REFERENCES tasks(id),
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size INTEGER NOT NULL,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, database: str | Path) -> None:
        self.database = Path(database).expanduser().resolve()

    def _connect(self) -> sqlite3.Connection:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES(?, ?)",
                (1, utc_now()),
            )

    def create_run(self, goal: str, workspace: str | Path | None = None) -> Run:
        goal = goal.strip()
        if not goal:
            raise ValueError("goal must not be empty")
        run_id = uuid.uuid4().hex
        task_id = f"task-{uuid.uuid4().hex[:12]}"
        timestamp = utc_now()
        workspace_path = (
            Path(workspace).expanduser().resolve()
            if workspace is not None
            else (self.database.parent / "runs" / run_id).resolve()
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO runs(id, goal, status, workspace, created_at, updated_at) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (run_id, goal, RunStatus.PENDING.value, str(workspace_path), timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO tasks(id, run_id, title, prompt, state, created_at, updated_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    run_id,
                    "Execute user goal",
                    goal,
                    TaskStatus.PENDING.value,
                    timestamp,
                    timestamp,
                ),
            )
            self._append_event(
                connection,
                run_id,
                task_id,
                "run_created",
                {"goal": goal},
            )
        return self.get_run(run_id)  # type: ignore[return-value]

    def get_run(self, run_id: str) -> Run | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return Run(
            id=row["id"],
            goal=row["goal"],
            status=RunStatus(row["status"]),
            workspace=Path(row["workspace"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get_task(self, task_id: str) -> Task | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._task_from_row(row) if row else None

    def list_tasks(self, run_id: str) -> list[Task]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE run_id = ? ORDER BY created_at, id", (run_id,)
            ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def next_task(self, run_id: str) -> Task | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE run_id = ? AND state IN (?, ?, ?) "
                "ORDER BY created_at, id LIMIT 1",
                (
                    run_id,
                    TaskStatus.PENDING.value,
                    TaskStatus.READY.value,
                    TaskStatus.UNCERTAIN.value,
                ),
            ).fetchone()
        return self._task_from_row(row) if row else None

    def claim_task(self, task_id: str, runtime: str) -> Attempt | None:
        attempt_id = f"attempt-{uuid.uuid4().hex}"
        timestamp = utc_now()
        with self._connect() as connection:
            updated = connection.execute(
                "UPDATE tasks SET state = ?, attempts = attempts + 1, updated_at = ? "
                "WHERE id = ? AND state IN (?, ?, ?)",
                (
                    TaskStatus.RUNNING.value,
                    timestamp,
                    task_id,
                    TaskStatus.PENDING.value,
                    TaskStatus.READY.value,
                    TaskStatus.UNCERTAIN.value,
                ),
            ).rowcount
            if updated != 1:
                return None
            task = connection.execute("SELECT run_id, attempts FROM tasks WHERE id = ?", (task_id,)).fetchone()
            connection.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
                (RunStatus.RUNNING.value, timestamp, task["run_id"], RunStatus.PENDING.value),
            )
            connection.execute(
                "INSERT INTO attempts(id, task_id, runtime, status, started_at, heartbeat_at) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (attempt_id, task_id, runtime, "running", timestamp, timestamp),
            )
            self._append_event(
                connection,
                task["run_id"],
                task_id,
                "task_claimed",
                {"attempt_id": attempt_id, "runtime": runtime, "attempt": task["attempts"]},
            )
            row = connection.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
        return self._attempt_from_row(row)

    def finish_task(
        self,
        task_id: str,
        attempt_id: str,
        success: bool,
        result_path: str | None = None,
        error: str | None = None,
    ) -> bool:
        timestamp = utc_now()
        new_state = TaskStatus.SUCCEEDED.value if success else TaskStatus.FAILED.value
        attempt_state = "succeeded" if success else "failed"
        with self._connect() as connection:
            task = connection.execute("SELECT run_id, state FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if task is None:
                raise ValueError(f"unknown task: {task_id}")
            updated = connection.execute(
                "UPDATE tasks SET state = ?, result_path = ?, last_error = ?, updated_at = ? "
                "WHERE id = ? AND state = ?",
                (new_state, result_path, error, timestamp, task_id, TaskStatus.RUNNING.value),
            ).rowcount
            if updated != 1:
                return False
            connection.execute(
                "UPDATE attempts SET status = ?, finished_at = ?, heartbeat_at = ?, error = ? WHERE id = ?",
                (attempt_state, timestamp, timestamp, error, attempt_id),
            )
            self._append_event(
                connection,
                task["run_id"],
                task_id,
                "task_succeeded" if success else "task_failed",
                {"attempt_id": attempt_id, "result_path": result_path, "error": error},
            )
        return True

    def retry_task(self, task_id: str, attempt_id: str, error: str) -> bool:
        timestamp = utc_now()
        with self._connect() as connection:
            task = connection.execute("SELECT run_id, state FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if task is None:
                raise ValueError(f"unknown task: {task_id}")
            updated = connection.execute(
                "UPDATE tasks SET state = ?, last_error = ?, updated_at = ? "
                "WHERE id = ? AND state = ?",
                (TaskStatus.READY.value, error, timestamp, task_id, TaskStatus.RUNNING.value),
            ).rowcount
            if updated != 1:
                return False
            connection.execute(
                "UPDATE attempts SET status = ?, finished_at = ?, heartbeat_at = ?, error = ? WHERE id = ?",
                ("failed", timestamp, timestamp, error, attempt_id),
            )
            self._append_event(
                connection,
                task["run_id"],
                task_id,
                "task_retry_scheduled",
                {"attempt_id": attempt_id, "error": error},
            )
        return True

    def recover_running(self, run_id: str) -> int:
        timestamp = utc_now()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM tasks WHERE run_id = ? AND state = ?",
                (run_id, TaskStatus.RUNNING.value),
            ).fetchall()
            for row in rows:
                task_id = row["id"]
                connection.execute(
                    "UPDATE tasks SET state = ?, updated_at = ?, last_error = ? WHERE id = ?",
                    (
                        TaskStatus.UNCERTAIN.value,
                        timestamp,
                        "controller restarted while task was running",
                        task_id,
                    ),
                )
                connection.execute(
                    "UPDATE attempts SET status = ?, heartbeat_at = ?, error = ? "
                    "WHERE task_id = ? AND status = ?",
                    (
                        "uncertain",
                        timestamp,
                        "controller restarted before attempt completed",
                        task_id,
                        "running",
                    ),
                )
                self._append_event(
                    connection,
                    run_id,
                    task_id,
                    "task_recovered",
                    {"reason": "controller_restart"},
                )
        return len(rows)

    def settle_run(self, run_id: str) -> Run | None:
        timestamp = utc_now()
        with self._connect() as connection:
            current = connection.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
            if current is None:
                return None
            rows = connection.execute("SELECT state FROM tasks WHERE run_id = ?", (run_id,)).fetchall()
            if not rows:
                return self.get_run(run_id)
            states = {row["state"] for row in rows}
            if TaskStatus.FAILED.value in states:
                status = RunStatus.FAILED.value
            elif states == {TaskStatus.SUCCEEDED.value}:
                status = RunStatus.SUCCEEDED.value
            elif TaskStatus.CANCELLED.value in states:
                status = RunStatus.CANCELLED.value
            else:
                status = RunStatus.RUNNING.value
            connection.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE id = ? AND status != ?",
                (status, timestamp, run_id, RunStatus.CANCELLED.value),
            )
            if (
                status in {RunStatus.SUCCEEDED.value, RunStatus.FAILED.value}
                and current["status"] != status
            ):
                self._append_event(connection, run_id, None, f"run_{status}", {})
        return self.get_run(run_id)

    def cancel_run(self, run_id: str) -> bool:
        timestamp = utc_now()
        with self._connect() as connection:
            run = connection.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
            if run is None:
                return False
            changed = connection.execute(
                "UPDATE runs SET status = ?, updated_at = ? WHERE id = ? AND status NOT IN (?, ?, ?)",
                (
                    RunStatus.CANCELLED.value,
                    timestamp,
                    run_id,
                    RunStatus.SUCCEEDED.value,
                    RunStatus.FAILED.value,
                    RunStatus.CANCELLED.value,
                ),
            ).rowcount
            connection.execute(
                "UPDATE tasks SET state = ?, updated_at = ? WHERE run_id = ? AND state NOT IN (?, ?, ?)",
                (
                    TaskStatus.CANCELLED.value,
                    timestamp,
                    run_id,
                    TaskStatus.SUCCEEDED.value,
                    TaskStatus.FAILED.value,
                    TaskStatus.CANCELLED.value,
                ),
            )
            connection.execute(
                "UPDATE attempts SET status = ?, finished_at = ? WHERE task_id IN "
                "(SELECT id FROM tasks WHERE run_id = ?) AND status = ?",
                ("cancelled", timestamp, run_id, "running"),
            )
            if changed:
                self._append_event(connection, run_id, None, "run_cancelled", {})
        return bool(changed)

    def add_artifact(
        self,
        run_id: str,
        task_id: str,
        path: str,
        sha256: str,
        size: int,
        kind: str = "result",
    ) -> str:
        artifact_id = f"artifact-{uuid.uuid4().hex}"
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO artifacts(id, run_id, task_id, path, sha256, size, kind, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (artifact_id, run_id, task_id, path, sha256, size, kind, utc_now()),
            )
            self._append_event(
                connection,
                run_id,
                task_id,
                "artifact_recorded",
                {"artifact_id": artifact_id, "path": path, "sha256": sha256, "size": size},
            )
        return artifact_id

    def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, task_id, path, sha256, size, kind, created_at FROM artifacts "
                "WHERE run_id = ? ORDER BY created_at, id",
                (run_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_events(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, task_id, type, payload, created_at FROM events "
                "WHERE run_id = ? ORDER BY created_at, id",
                (run_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "type": row["type"],
                "payload": json.loads(row["payload"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        task_id: str | None = None,
        event_id: str | None = None,
    ) -> bool:
        with self._connect() as connection:
            return self._append_event(connection, run_id, task_id, event_type, payload, event_id)

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        run_id: str,
        task_id: str | None,
        event_type: str,
        payload: dict[str, Any],
        event_id: str | None = None,
    ) -> bool:
        event_id = event_id or f"event-{uuid.uuid4().hex}"
        inserted = connection.execute(
            "INSERT OR IGNORE INTO events(id, run_id, task_id, type, payload, created_at) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (event_id, run_id, task_id, event_type, json.dumps(payload, sort_keys=True), utc_now()),
        ).rowcount
        return inserted == 1

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> Task:
        result_path = Path(row["result_path"]) if row["result_path"] else None
        return Task(
            id=row["id"],
            run_id=row["run_id"],
            title=row["title"],
            prompt=row["prompt"],
            state=TaskStatus(row["state"]),
            attempts=row["attempts"],
            result_path=result_path,
            last_error=row["last_error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _attempt_from_row(row: sqlite3.Row) -> Attempt:
        return Attempt(
            id=row["id"],
            task_id=row["task_id"],
            runtime=row["runtime"],
            status=row["status"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            error=row["error"],
        )
